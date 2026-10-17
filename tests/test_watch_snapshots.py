import math
import pytest
from itsdangerous import SignatureExpired
import watch_store
from app import app

URL='https://www.hepsiburada.com/sonoff-zbmini-l2-p-HBCV000TEST'

@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('WATCH_SIGNING_SECRET','local-test-secret-only')


def test_signed_price_is_bound_to_product_and_cannot_be_changed():
    receipt=watch_store.sign_snapshot(URL,123.45)
    price,at=watch_store.read_snapshot(receipt,URL)
    assert price==123.45 and at.tzinfo is not None
    with pytest.raises(ValueError):watch_store.read_snapshot(receipt,URL+'-other')
    with pytest.raises(ValueError):watch_store.read_snapshot(receipt+'x',URL)

@pytest.mark.parametrize('price',[0,-1,math.nan,math.inf,None,100000000])
def test_invalid_prices_never_receive_verified_receipt(price):
    assert watch_store.sign_snapshot(URL,price) is None


def test_expired_receipt_rejected(monkeypatch):
    class Expired:
        def loads(self,*args,**kwargs):raise SignatureExpired('expired')
    monkeypatch.setattr(watch_store,'snapshot_signer',lambda:Expired())
    with pytest.raises(ValueError):watch_store.read_snapshot('expired',URL)


def test_product_analysis_issues_receipt_without_extra_provider_calls(monkeypatch):
    import app as module
    class Response:
        text='test page'
        def raise_for_status(self):pass
    monkeypatch.setattr(module.requests,'get',lambda *a,**kw:Response())
    monkeypatch.setattr(module,'extract_product',lambda *a:{'title':'Sonoff ZBMINI-L2','price':150})
    monkeypatch.setattr(module,'reef_hepsiburada',lambda *a:None)
    monkeypatch.setattr(module,'reef_hepsiburada_offers',lambda *a:None)
    monkeypatch.setattr(module,'matched_offers',lambda *a:[{'price':123.45,'source':'test','url':URL}])
    r=app.test_client().get('/api/product',query_string={'url':URL})
    assert r.status_code==200
    product=r.json['product']
    assert watch_store.read_snapshot(product['watchReceipt'],URL)[0]==123.45
    assert product['price']==123.45


def test_unconfigured_server_keeps_existing_product_analysis(monkeypatch):
    monkeypatch.delenv('WATCH_SIGNING_SECRET')
    monkeypatch.delenv('DATABASE_URL',raising=False)
    assert watch_store.sign_snapshot(URL,123.45) is None
    assert app.test_client().get('/health').json['version']=='3.83'
