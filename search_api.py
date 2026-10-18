"""Optional official search API. Reject paid plans and enabled overage billing."""
import os,re,json,time,hashlib,threading,copy,math
from collections import OrderedDict
from urllib.parse import urlparse
import requests
from public_web import normalize_url

# A free /usage endpoint allows ten checks per ten minutes. One current free
# service worker shares short-lived usage checks and URL discovery (never prices).
# Reserve a credit before every POST, including failed/uncertain POSTs.
_lock=threading.Lock()
_state={}
_url_cache=OrderedDict()
USAGE_TTL=75
URL_TTL=300

def _limited(response,now):
    try:seconds=max(1,int(response.headers.get('Retry-After','60')))
    except (ValueError,TypeError):seconds=60
    _state['blocked_until']=now+seconds
    return {'urls':[],'state':'rate_limited','retryAfterSeconds':seconds}

def _projected(usage,reserved):
    result=copy.deepcopy(usage)
    if not isinstance(result,dict):return result
    for group,field in (('account','plan_usage'),('key','usage')):
        section=result.get(group)
        value=section.get(field) if isinstance(section,dict) else None
        if type(value) in (int,float):result[group][field]=value+reserved
    return result

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
    with _lock:return _discover_api(base,key)

def _discover_api(base,key):
    now=time.monotonic()
    scope=(hashlib.sha256(key.encode()).hexdigest(),time.strftime('%Y-%m',time.gmtime()))
    if _state.get('scope')!=scope:
        _state.clear();_state.update(scope=scope,reserved=0,checked_at=0,blocked_until=0)
        _url_cache.clear()
    query=str(base.get('gtin') or base.get('mpn') or base.get('title') or '')[:180]+' fiyat satın al Türkiye'
    cache_key=(query,bool(base.get('_merchantSearch')))
    if cache_key in _url_cache:
        stamp,urls=_url_cache[cache_key]
        if now-stamp<URL_TTL:
            return {'urls':[u for u in urls if u!=base.get('url')],'state':'completed'}
        del _url_cache[cache_key]
    if now<_state.get('blocked_until',0):
        return {'urls':[],'state':'rate_limited','retryAfterSeconds':math.ceil(_state['blocked_until']-now)}
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    try:
        if 'usage' not in _state or now-_state['checked_at']>=USAGE_TTL:
            usage=requests.get('https://api.tavily.com/usage',headers=headers,timeout=(3,5),allow_redirects=False)
            if usage.status_code==429:return _limited(usage,now)
            if usage.status_code!=200:return {'urls':[],'state':'usage_unavailable','httpStatus':usage.status_code}
            usage_data=usage.json()
            # Do not release local reservations if the provider's counter lags.
            previous=_projected(_state['usage'],_state['reserved']) if 'usage' in _state else {}
            if isinstance(usage_data,dict):
                for group,field in (('account','plan_usage'),('key','usage')):
                    old_group=previous.get(group) if isinstance(previous,dict) else None
                    new_group=usage_data.get(group)
                    old=old_group.get(field) if isinstance(old_group,dict) else None
                    new=new_group.get(field) if isinstance(new_group,dict) else None
                    if type(old) in (int,float) and type(new) in (int,float):usage_data[group][field]=max(old,new)
            _state.update(usage=usage_data,checked_at=now,reserved=0)
        usage_data=_projected(_state['usage'],_state['reserved'])
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
        _state['reserved']+=1
        payload={
            'query':query,'search_depth':'basic','auto_parameters':False,'topic':'general',
            'country':'turkey','language':'tr','max_results':20,'include_answer':False,
            'include_raw_content':False,'include_images':False,'include_usage':True,
            'exclude_domains':['google.com','youtube.com','facebook.com','instagram.com','akakce.com','cimri.com','epey.com']}
        if base.get('_merchantSearch'):
            from product_links import PATTERNS
            payload['include_domains']=list(PATTERNS)
        response=requests.post('https://api.tavily.com/search',headers=headers,json=payload,
            timeout=(3,10),allow_redirects=False)
        if response.status_code==429:return _limited(response,time.monotonic())
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
                if url not in urls:urls.append(url)
            except ValueError:continue
        # URL discovery only: never parse search snippets into price offers.
        _url_cache[cache_key]=(time.monotonic(),tuple(urls))
        while len(_url_cache)>128:_url_cache.popitem(last=False)
        return {'urls':[u for u in urls if u!=base.get('url')],'state':'completed'}
    except (requests.RequestException,ValueError,TypeError):return {'urls':[],'state':'unavailable'}
