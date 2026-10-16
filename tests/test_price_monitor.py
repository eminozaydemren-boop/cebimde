import json
from unittest.mock import Mock
import pytest
import jwt
import price_monitor as pm
import monitor_auth as auth
from app import app

IDENTITY={'title':'Sonoff ZBMINI-L2','brand':'Sonoff','mpn':'ZBMINI-L2'}
URL='https://www.robotistan.com/sonoff-zbmini-l2'

def page(**overrides):
    offer={'@type':'Offer','price':150,'priceCurrency':'TRY','availability':'https://schema.org/InStock'}
    offer.update(overrides)
    p={'@type':'Product','name':'Sonoff ZBMINI-L2','brand':{'name':'Sonoff'},'mpn':'ZBMINI-L2','offers':offer}
    return '<script type="application/ld+json">'+json.dumps(p)+'</script>'

def test_verified_matching_instock_try_offer():
    assert pm.verified_offer(page(),URL,IDENTITY)=={'price':150,'url':URL}

@pytest.mark.parametrize('offer',[{'priceCurrency':'USD'},{'price':0},{'price':'NaN'},{'availability':'https://schema.org/OutOfStock'},{'@type':'AggregateOffer'}])
def test_no_false_price_for_foreign_invalid_soldout_or_aggregate(offer):
    assert pm.verified_offer(page(**offer),URL,IDENTITY) is None

def test_unrelated_product_is_never_an_alert():
    assert pm.verified_offer(page(),URL,{'title':'Sonoff ZBMINI-R2','brand':'Sonoff','mpn':'ZBMINI-R2'}) is None

@pytest.mark.parametrize('url',['https://127.0.0.1/x','https://robotistan.com.evil.test/x','https://robotistan.com:8080/x','https://user:password@robotistan.com/x'])
def test_private_or_invalid_sources_rejected(url):
    assert not pm.safe_source(url)

def test_scan_does_not_call_paid_provider(monkeypatch):
    monkeypatch.setattr(pm,'public_page',lambda url:(page(),url))
    monkeypatch.setattr(pm.requests,'post',Mock(side_effect=AssertionError('Paid APIs must never be called')))
    result=pm.check_watch('Sonoff ZBMINI-L2',URL,{'identity':IDENTITY,'sources':[URL]})
    assert result['price']==150
    pm.requests.post.assert_not_called()

def test_failed_scan_preserves_no_fake_result(monkeypatch):
    monkeypatch.setattr(pm,'public_page',lambda url:None)
    assert pm.check_watch('Sonoff ZBMINI-L2',URL,{}) is None

def test_notification_only_for_new_target_or_lower_price():
    assert pm.should_notify(90,100,False,None)
    assert not pm.should_notify(90,100,True,90)
    assert pm.should_notify(80,100,True,90)
    assert not pm.should_notify(110,100,False,None)


def test_unsigned_monitor_call_cannot_access_database(monkeypatch):
    import watch_store
    monkeypatch.setattr(watch_store,'initialize',Mock(side_effect=AssertionError('Unauthorized DB access')))
    r=app.test_client().post('/api/watches/monitor/run')
    assert r.status_code==401
    watch_store.initialize.assert_not_called()


def claims(**changes):
    d={'repository_id':'1406293415','repository_owner_id':'338290043','repository':'eminozaydemren-boop/cebimde',
       'repository_visibility':'public','ref':'refs/heads/main','workflow_ref':auth.WORKFLOW,'event_name':'schedule'}
    d.update(changes);return d

@pytest.mark.parametrize('changes',[{'repository_id':'attacker'},{'repository_owner_id':'attacker'},{'ref':'refs/pull/1/merge'},{'event_name':'pull_request'},{'workflow_ref':'different.yml'},{'repository_visibility':'private'}])
def test_oidc_rejects_wrong_repository_ref_workflow_or_event(monkeypatch,changes):
    monkeypatch.setattr(auth,'jwks',lambda:Mock(get_signing_key_from_jwt=lambda token:Mock(key='test')))
    monkeypatch.setattr(jwt,'decode',lambda *a,**kw:claims(**changes))
    assert auth.authorized('Bearer token') is False


def test_oidc_accepts_only_valid_signed_workflow_claims(monkeypatch):
    monkeypatch.setattr(auth,'jwks',lambda:Mock(get_signing_key_from_jwt=lambda token:Mock(key='test')))
    decoder=Mock(return_value=claims());monkeypatch.setattr(jwt,'decode',decoder)
    assert auth.authorized('Bearer token') is True
    kw=decoder.call_args.kwargs
    assert kw['algorithms']==['RS256'] and kw['audience']==auth.AUDIENCE and kw['issuer']==auth.ISSUER

@pytest.mark.parametrize('change',[{}, {'aud':'wrong'}, {'exp':1}, {'repository_id':'attacker'}])
def test_real_rsa_signature_and_claim_validation(monkeypatch,change):
    import time
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    payload=claims(iss=auth.ISSUER,aud=auth.AUDIENCE,iat=int(time.time()),exp=int(time.time())+60)
    payload.update(change)
    monkeypatch.setattr(auth,'jwks',lambda:Mock(get_signing_key_from_jwt=lambda token:Mock(key=key.public_key())))
    token=jwt.encode(payload,key,algorithm='RS256')
    assert auth.authorized('Bearer '+token)==(not change)
