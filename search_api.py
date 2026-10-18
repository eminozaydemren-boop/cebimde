"""Optional official search API. Reject paid plans and enabled overage billing."""
import os,re,json
from urllib.parse import urlparse
import requests
from public_web import normalize_url

def free_plan(usage,development=False):
    if not isinstance(usage,dict):return False
    account=usage.get('account') or {}
    if not isinstance(account,dict):return False
    def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool)
    limit=account.get('plan_limit');used=account.get('plan_usage')
    if str(account.get('current_plan','')).casefold()!='researcher':return False
    if not number(limit) or not 0<limit<=1000:return False
    if not number(used) or not 0<=used<limit-5:return False
    if not number(account.get('paygo_usage')) or account['paygo_usage']!=0:return False
    if 'paygo_limit' not in account:return False
    paygo=account['paygo_limit']
    if number(paygo):return paygo==0
    # The observed free, PAYGO-off account returns explicit null, not zero.
    # Do not interpret null as a zero/unlimited allowance. Accept it only for a
    # development key with a provider-enforced monthly cap whose ENTIRE remaining
    # budget fits inside the remaining free plan, with five credits held back.
    # Missing fields, uncapped keys and any paid usage still fail closed.
    if paygo is not None or not development:return False
    api_key=usage.get('key')
    if not isinstance(api_key,dict):return False
    key_limit=api_key.get('limit');key_used=api_key.get('usage')
    return (number(key_limit) and 0<key_limit<=limit-5
            and number(key_used) and 0<=key_used<key_limit and key_used<=used
            and key_limit-key_used<=limit-used-5)

def discover_api(base):
    key=os.getenv('TAVILY_API_KEY','').strip()
    if not key:return {'urls':[],'state':'not_configured'}
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    try:
        usage=requests.get('https://api.tavily.com/usage',headers=headers,timeout=(3,5),allow_redirects=False)
        if usage.status_code!=200:return {'urls':[],'state':'usage_unavailable'}
        usage_data=usage.json()
        if not free_plan(usage_data,development=key.startswith('tvly-dev-')):
            # Log only allowlisted billing field types/counts, never credentials,
            # response bodies, request headers, or arbitrary provider strings.
            account=usage_data.get('account',{}) if isinstance(usage_data,dict) else {}
            account=account if isinstance(account,dict) else {}
            diagnostic={name:(account[name] if account[name] is None or type(account[name]) in (int,float,bool) else type(account[name]).__name__) if name in account else 'missing'
                        for name in ('plan_limit','plan_usage','paygo_limit','paygo_usage')}
            diagnostic['researcher']=str(account.get('current_plan','')).casefold()=='researcher'
            print('[SEARCH_FREE_PLAN_REJECTED]',json.dumps(diagnostic),flush=True)
            return {'urls':[],'state':'free_plan_not_verified'}
        query=str(base.get('gtin') or base.get('mpn') or base.get('title') or '')[:180]+' fiyat satın al Türkiye'
        response=requests.post('https://api.tavily.com/search',headers=headers,json={
            'query':query,'search_depth':'basic','auto_parameters':False,'topic':'general',
            'country':'turkey','language':'tr','max_results':20,'include_answer':False,
            'include_raw_content':False,'include_images':False,'include_usage':True},
            timeout=(3,10),allow_redirects=False)
        if response.status_code!=200:return {'urls':[],'state':'unavailable','httpStatus':response.status_code}
        urls=[]
        data=response.json()
        if not isinstance(data,dict) or not isinstance(data.get('results'),list):return {'urls':[],'state':'invalid_response'}
        for result in data['results']:
            if not isinstance(result,dict):continue
            try:
                url=normalize_url(result.get('url'))
                host=urlparse(url).hostname.removeprefix('www.')
                if host in ('google.com','youtube.com','facebook.com','instagram.com','akakce.com','cimri.com','epey.com'):continue
                if url!=base.get('url') and url not in urls:urls.append(url)
            except ValueError:continue
        # URL discovery only: never parse search snippets into price offers.
        return {'urls':urls,'state':'completed'}
    except (requests.RequestException,ValueError,TypeError):return {'urls':[],'state':'unavailable'}
