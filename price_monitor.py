"""Credit-free monitoring: public structured offers only. Never calls ReefAPI."""
import html
import json
import math
import re
import time
from urllib.parse import urlparse,urljoin
import requests

PUBLIC_SHOPS={
 'hepsiburada.com','www.hepsiburada.com','trendyol.com','www.trendyol.com',
 'n11.com','www.n11.com','amazon.com.tr','www.amazon.com.tr',
 'robotistan.com','www.robotistan.com','uni-t.com.tr','www.uni-t.com.tr',
 'unitturkiye.com','www.unitturkiye.com','bauhaus.com.tr','www.bauhaus.com.tr',
 'perpaotomasyon.com','www.perpaotomasyon.com','elektrikdukani.com','www.elektrikdukani.com',
 'elcelektromarket.com','www.elcelektromarket.com','teknosa.com','www.teknosa.com',
 'mediamarkt.com.tr','www.mediamarkt.com.tr','vatanbilgisayar.com','www.vatanbilgisayar.com'
}

def safe_source(url):
    try:
        p=urlparse(url)
        return p.scheme=='https' and p.hostname in PUBLIC_SHOPS and not p.username and not p.password and p.port in (None,443)
    except (TypeError,ValueError):return False


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
    if not safe_source(url):return None
    # Redirects may only stay within the explicitly supported public retailer list.
    deadline=time.monotonic()+6
    for _ in range(2):
        if time.monotonic()>=deadline:return None
        with requests.get(url,timeout=(2,3),allow_redirects=False,stream=True,
                          headers={'User-Agent':'CEBIMDE-PriceMonitor/3.75','Accept':'text/html','Accept-Language':'tr-TR'}) as r:
            if r.status_code in (301,302,303,307,308):
                url=urljoin(url,r.headers.get('Location',''))
                if not safe_source(url):return None
                continue
            if r.status_code!=200 or 'html' not in r.headers.get('Content-Type','').lower():return None
            data=bytearray()
            for chunk in r.iter_content(65536):
                data.extend(chunk)
                if len(data)>1024*1024 or time.monotonic()>=deadline:return None
            return data.decode(r.encoding or 'utf-8',errors='replace'),url
    return None


def verified_offer(page,url,identity):
    from app import walk,identity_match,clean_price
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
            if not identity_match(identity,candidate):continue
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
