from unittest.mock import Mock
import pytest
import search_api

def usage(**overrides):
    account={'current_plan':'Researcher','plan_usage':10,'plan_limit':1000,'paygo_limit':0,'paygo_usage':0}
    account.update(overrides);return {'account':account}

@pytest.mark.parametrize('values',[{'current_plan':'Project'},{'paygo_limit':100},{'paygo_limit':None},{'plan_usage':999},{'plan_usage':-1},{'plan_limit':None},{'paygo_usage':1}])
def test_paid_ambiguous_or_exhausted_accounts_are_rejected(values):
    assert not search_api.free_plan(usage(**values))

def test_only_free_researcher_plan_with_zero_overage_is_allowed():
    assert search_api.free_plan(usage())

def capped_usage(**overrides):
    value=usage(paygo_limit=None,**overrides)
    value['key']={'usage':10,'limit':900}
    return value

def test_explicit_null_requires_development_key_and_enforced_free_budget():
    assert search_api.free_plan(capped_usage(),development=True)
    assert not search_api.free_plan(capped_usage())

@pytest.mark.parametrize('key',[{}, {'usage':10,'limit':None}, {'usage':10,'limit':1000},
    {'usage':10,'limit':True}, {'usage':900,'limit':900}, {'usage':-1,'limit':900},
    {'usage':11,'limit':900}, {'usage':None,'limit':900}])
def test_null_never_allows_missing_unlimited_or_inconsistent_key_limits(key):
    value=capped_usage();value['key']=key
    assert not search_api.free_plan(value,development=True)

@pytest.mark.parametrize('overrides',[{'current_plan':'Project'},{'plan_usage':110},
    {'plan_usage':999},{'paygo_limit':100},{'paygo_usage':1}])
def test_capped_key_still_rejects_paid_or_insufficient_free_account(overrides):
    value=capped_usage();value['account'].update(overrides)
    assert not search_api.free_plan(value,development=True)

def test_missing_paygo_field_is_not_explicit_disabled_null():
    value=capped_usage();del value['account']['paygo_limit']
    assert not search_api.free_plan(value,development=True)

def test_capped_development_key_can_search_with_observed_paygo_off_response(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','tvly-dev-fake-test-key')
    monkeypatch.setattr(search_api.requests,'get',Mock(return_value=Mock(status_code=200,json=lambda:capped_usage())))
    post=Mock(return_value=Mock(status_code=200,json=lambda:{'results':[]}))
    monkeypatch.setattr(search_api.requests,'post',post)
    assert search_api.discover_api({'title':'Example'})['state']=='completed'
    post.assert_called_once()

def test_missing_key_makes_no_network_requests(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY',raising=False)
    get=Mock();monkeypatch.setattr(search_api.requests,'get',get)
    assert search_api.discover_api({'title':'Example'})['state']=='not_configured';get.assert_not_called()

def test_no_search_call_is_made_if_free_plan_cannot_be_verified(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','test-key')
    monkeypatch.setattr(search_api.requests,'get',Mock(return_value=Mock(status_code=200,json=lambda:usage(paygo_limit=100))))
    post=Mock();monkeypatch.setattr(search_api.requests,'post',post)
    assert search_api.discover_api({'title':'Example'})['state']=='free_plan_not_verified';post.assert_not_called()

def test_basic_discovery_uses_only_urls_never_snippet_prices(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','test-key')
    monkeypatch.setattr(search_api.requests,'get',Mock(return_value=Mock(status_code=200,json=lambda:usage())))
    post=Mock(return_value=Mock(status_code=200,json=lambda:{'results':[{'url':'https://new-shop.com/item','content':'1 TL'}, {'url':'http://127.0.0.1/admin'}]}))
    monkeypatch.setattr(search_api.requests,'post',post)
    result=search_api.discover_api({'title':'Example Product','url':'https://source.com/item'})
    assert result=={'urls':['https://new-shop.com/item'],'state':'completed'}
    assert post.call_args.kwargs['json']['search_depth']=='basic'
    assert post.call_args.kwargs['json']['auto_parameters'] is False
    assert post.call_args.kwargs['allow_redirects'] is False
