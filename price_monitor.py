"""Credit-free monitoring: public structured offers only. Never calls ReefAPI."""
import html
import json
import math
import re
import time
from urllib.parse import urlparse,urljoin
import requests

def safe_source(url):
    from public_web import normalize_url
    try:normalize_url(url);return True
    except (ValueError,TypeError):return False


def metadata(base,offers,url):
    identity={k:str((base or {}).get(k) or '')[:300] for k in ('title','brand','mpn','gtin')}
    # Prefer independently verified retailers over marketplace pages that may block direct reads.
    sources=[]
    for offer in offers or []:
        u=offer.get('url') if isinstance(offer,dict) else None
        if safe_source(u) and u not in sources:sources.append(u)
    sources.sort(key=lambda u: urlparse(u).hostname in {'hepsiburada.com','www.hepsiburada.com','trendyol.com','www.trendyol.com','n11.com','www.n11.com','amazon.com.tr','www.amazon.com.tr'})
    if safe_source(url) and url not in sources:sources.append(url)
    return {'identity':identity,'sources':sources[:3]}


def public_page(url):
    from public_web import fetch_page
    try:return fetch_page(url,budget=7)
    except Exception:return None


def verified_offer(page,url,identity):
    from app import walk,clean_price
    from product_data import same_product
    found=[]
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:data=json.loads(html.unescape(raw).strip())
        except (ValueError,TypeError):continue
        for p in walk(data):
            types=p.get('@type');types=types if isinstance(types,list) else [types]
            if 'Product' not in types:continue
            brand=p.get('brand');brand=brand.get('name') if isinstance(brand,dict) else brand
            candidate={'title':p.get('name'),'brand':brand,'mpn':p.get('mpn'),
                       'gtin':p.get('gtin13') or p.get('gtin14') or p.get('gtin12') or p.get('gtin8') or p.get('gtin')}
            if not same_product(identity,candidate):continue
            offers=p.get('offers') or [];offers=offers if isinstance(offers,list) else [offers]
            for o in offers:
                if not isinstance(o,dict) or o.get('@type')=='AggregateOffer':continue
                if str(o.get('priceCurrency','')).upper() not in ('TRY','TL','₺'):continue
                available=str(o.get('availability') or '').rsplit('/',1)[-1]
                if available and available not in ('InStock','LimitedAvailability','OnlineOnly'):continue
                price=clean_price(o.get('price'))
                if price is not None and math.isfinite(price) and 0<price<100000000:
                    found.append({'price':round(price,2),'url':url})
    return min(found,key=lambda x:x['price']) if found else None


def check_watch(title,url,meta):
    meta=meta if isinstance(meta,dict) else {}
    identity=meta.get('identity') or {'title':title}
    sources=meta.get('sources') or [url]
    found=[]
    # Keep each request below the web worker's timeout. No retries or paid fallback.
    import time
    deadline=time.monotonic()+12
    for source in sources[:3]:
        if time.monotonic()>deadline-5:break
        try:
            result=public_page(source)
            if result:
                offer=verified_offer(result[0],result[1],identity)
                if offer:found.append(offer)
        except (requests.RequestException,ValueError,TypeError):continue
    return min(found,key=lambda x:x['price']) if found else None


def should_notify(price,target,hit_active,previous_notice_price):
    return price<=target and (not hit_active or previous_notice_price is None or price<float(previous_notice_price))
