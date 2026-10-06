from flask import Flask, request, jsonify, send_from_directory
import requests, re, html, json, os
from html.parser import HTMLParser
from urllib.parse import quote_plus
from urllib.parse import urlparse, urljoin, parse_qs, unquote

class SearxLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            href=dict(attrs).get('href')
            if href:self.links.append(href)

def searx_result_urls(body, endpoint):
    parser=SearxLinkParser()
    try:parser.feed(body or '')
    except Exception:return []
    out=[]; seen=set()
    for raw in parser.links:
        try:
            u=urljoin(endpoint+'/',html.unescape(str(raw)).strip())
            qs=parse_qs(urlparse(u).query)
            target=(qs.get('url') or [None])[0]
            if target:
                d=unquote(target)
                if d.startswith(('http://','https://')):u=d
            if u.startswith(('http://','https://')) and u not in seen:
                seen.add(u); out.append(u)
        except Exception:continue
    return out

app=Flask(__name__, static_folder='web', static_url_path='')
ALLOWED={'www.hepsiburada.com','hepsiburada.com','www.amazon.com.tr','amazon.com.tr','www.trendyol.com','trendyol.com','www.n11.com','n11.com'}
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36','Accept-Language':'tr-TR,tr;q=0.9,en;q=0.7'}

def clean_price(v):
    if v is None:return None
    if isinstance(v,(int,float)):return float(v)
    s=str(v).replace('TL','').replace('₺','').replace('\xa0','').replace(' ','').strip()
    if ',' in s and '.' in s:s=s.replace('.','').replace(',','.')
    elif ',' in s:s=s.replace(',','.')
    try:return float(re.sub(r'[^0-9.]','',s))
    except:return None

def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from walk(v)
    elif isinstance(x,list):
        for v in x: yield from walk(v)

def extract_product(page,url):
    out={'title':None,'brand':None,'sku':None,'mpn':None,'gtin':None,'image':None,'price':None,'currency':None,'url':url}
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:data=json.loads(html.unescape(raw).strip())
        except:continue
        for o in walk(data):
            t=o.get('@type'); ts=t if isinstance(t,list) else [t]
            if 'Product' not in ts:continue
            out['title']=out['title'] or o.get('name'); out['sku']=out['sku'] or o.get('sku'); out['mpn']=out['mpn'] or o.get('mpn'); out['gtin']=out['gtin'] or o.get('gtin13') or o.get('gtin14') or o.get('gtin12') or o.get('gtin8') or o.get('gtin')
            b=o.get('brand'); out['brand']=out['brand'] or (b.get('name') if isinstance(b,dict) else b)
            im=o.get('image'); out['image']=out['image'] or (im[0] if isinstance(im,list) and im else im)
            offers=o.get('offers'); offers=offers[0] if isinstance(offers,list) and offers else offers
            if isinstance(offers,dict):
                out['price']=out['price'] or clean_price(offers.get('price') or offers.get('lowPrice'))
                out['currency']=out['currency'] or offers.get('priceCurrency')
    return out

def strict_zbmini_l2(title):
    s=(title or '').lower().replace('-','').replace(' ','')
    return ('zbminil2' in s or ('zigbee' in s and 'minil2' in s)) and not any(x in s for x in ['2adet','2li','paket','r2'])

def model_token(title):
    s=(title or '').upper()
    # Prefer actual manufacturer model codes, not electrical specifications
    # such as 90V-1000V or marketplace SKUs.
    if re.search(r'\\bUT[\\s-]*12D\\b',s):
        return 'UT12D'
    if re.search(r'\\bZBMINI[\\s-]*L2\\b',s):
        return 'ZBMINI-L2'
    toks=re.findall(r'(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*[0-9])[A-Z0-9-]{4,}',s)
    for m in re.finditer(r'\\b([A-Z]{1,5})[ -]+([0-9]{1,4}[A-Z]{1,4})\\b',s):
        toks.append(m.group(1)+m.group(2))
    bad={'1000V','600V','220V','90V'}
    toks=[x for x in toks if x.replace('-','') not in bad
          and not re.fullmatch(r'\\d+[A-Z]-\\d+[A-Z]',x)
          and not x.startswith('HBCV')]
    return max(toks,key=len) if toks else None

def same_model(a,b):
    ma,mb=model_token(a),model_token(b)
    return bool(ma and mb and ma.replace('-','')==mb.replace('-',''))


def discover_n11(title):
    key=os.getenv('REEF_API_KEY','').strip()
    model=model_token(title)
    if not key or not model:return []
    try:
        r=requests.post('https://api.reefapi.com/n11/v1/search',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'query':model,'page':1,'max_rotations':1},timeout=10)
        r.raise_for_status(); j=r.json()
        if not j.get('ok'):return []
        d=j.get('data') or {}
        rows=[]
        if isinstance(d,dict):
            for k in ('products','results','items'):
                if isinstance(d.get(k),list):
                    rows=d.get(k); break
        elif isinstance(d,list): rows=d
        out=[]
        for o in rows or []:
            if not isinstance(o,dict):continue
            t=o.get('title') or o.get('name') or o.get('product_name')
            u=o.get('url') or o.get('product_url') or o.get('link')
            rawp=o.get('price_value')
            if rawp is None: rawp=o.get('price')
            if rawp is None: rawp=o.get('sale_price')
            if rawp is None: rawp=o.get('discounted_price')
            p=clean_price(rawp)
            if p and u and same_model(title,t):
                out.append({'source':'n11','price':p,'url':u,'title':t,
                            'product_id':o.get('product_id') or o.get('id'),
                            'verification':'marketplace_exact_model'})
        return sorted(out,key=lambda x:x['price'])[:1]
    except Exception as e:
        print('[N11_DISCOVERY_ERROR]',type(e).__name__,str(e)[:160],flush=True)
        return []

def discover_trendyol(title):
    key=os.getenv('REEF_API_KEY','').strip()
    model=model_token(title)
    if not key or not model:return []
    try:
        r=requests.post('https://api.reefapi.com/trendyol/v1/search',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'query':model,'page':1,'max_pages':1},timeout=10)
        r.raise_for_status(); j=r.json()
        if not j.get('ok'):return []
        d=j.get('data') or {}
        rows=d.get('results') if isinstance(d,dict) else []
        out=[]
        for o in rows or []:
            if not isinstance(o,dict):continue
            t=o.get('title'); u=o.get('url')
            # Reef search exposes a numeric price_value on live rows; prefer it
            # over locale-formatted strings to avoid Turkish separator errors.
            p=clean_price(o.get('price_value'))
            if p is None:p=clean_price(o.get('price'))
            if p and u and same_model(title,t):
                out.append({'source':'Trendyol','price':p,'url':u,'title':t,
                            'content_id':o.get('content_id')})
        return sorted(out,key=lambda x:x['price'])[:1]
    except Exception:return []

def discover_trendyol(title):
    key=os.getenv('REEF_API_KEY','').strip()
    model=model_token(title)
    if not key or not model:return []
    try:
        r=requests.post('https://api.reefapi.com/trendyol/v1/search',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'query':model,'page':1},timeout=10)
        r.raise_for_status(); j=r.json()
        if not j.get('ok'):return []
        d=j.get('data') or {}
        rows=(d.get('results') or d.get('products') or []) if isinstance(d,dict) else []
        out=[]
        for o in rows:
            if not isinstance(o,dict):continue
            t=o.get('title') or o.get('name'); u=o.get('url')
            p=clean_price(o.get('price_value') if o.get('price_value') is not None else o.get('price'))
            if p and u and same_model(title,t):
                out.append({'source':'Trendyol','price':p,'url':u,'title':t})
        return sorted(out,key=lambda x:x['price'])[:1]
    except Exception:return []

def discover_amazon(title):
    key=os.getenv('REEF_API_KEY','').strip()
    model=model_token(title)
    if not key or not model:return []
    try:
        r=requests.post('https://api.reefapi.com/amazon/v1/search',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'query':model,'domain':'amazon.com.tr','page':1},timeout=10)
        r.raise_for_status(); j=r.json()
        if not j.get('ok'):return []
        d=j.get('data') or {}
        rows=(d.get('results') or d.get('products') or d.get('items') or []) if isinstance(d,dict) else []
        out=[]
        for o in rows:
            if not isinstance(o,dict):continue
            t=o.get('title') or o.get('name'); u=o.get('url') or o.get('product_url')
            p=clean_price(o.get('price_value') if o.get('price_value') is not None else o.get('price'))
            if p and u and same_model(title,t):
                out.append({'source':'Amazon TR','price':p,'url':u,'title':t})
        return sorted(out,key=lambda x:x['price'])[:1]
    except Exception:return []

def identity_match(base,cand):
    if not base or not cand:return False
    bg=str(base.get('gtin') or '').strip(); cg=str(cand.get('gtin') or '').strip()
    if bg and cg:return bg==cg
    bm=str(base.get('mpn') or '').upper().replace(' ',''); cm=str(cand.get('mpn') or '').upper().replace(' ','')
    if bm and cm:return bm==cm
    # Second safe path for shops that omit GTIN/MPN: require the exact model
    # plus matching brand and reject common bundle/accessory wording.
    bt=(base.get('title') or ''); ct=(cand.get('title') or '')
    if not same_model(bt,ct):return False
    bb=re.sub(r'[^A-Z0-9]','',str(base.get('brand') or '').upper())
    cb=re.sub(r'[^A-Z0-9]','',str(cand.get('brand') or '').upper())
    if not bb or not cb or bb!=cb:return False
    low=ct.lower()
    risky=('2 adet','2li','2 li','3 adet','3lu','3 lu','paket','set ','yedek','aksesuar','kablo','prob','adapt')
    if any(x in low for x in risky):return False
    return True

def verify_external_offer(base,url):
    try:
        host=(urlparse(url).hostname or '').lower()
        if not host or host in ALLOWED:return None
        r=requests.get(url,headers=HEADERS,timeout=4,allow_redirects=True); r.raise_for_status()
        final=(urlparse(r.url).hostname or '').lower()
        if not final:return None
        p=extract_product(r.text,r.url)
        # External web prices are accepted only from structured Product data.
        # The product identity must independently match by GTIN/MPN/model.
        # We intentionally do NOT infer a price from arbitrary nearby TL text:
        # installments, shipping, accessories and campaign amounts can otherwise
        # look like a much cheaper product price.
        if p.get('price') and identity_match(base,p):
            return {'source':final.replace('www.',''),'price':p['price'],'url':r.url,'title':p.get('title'),
                    'gtin':p.get('gtin'),'mpn':p.get('mpn'),'verification':'structured_product'}
        return None
    except Exception:return None

def discover_web_candidates(base):
    # Safe generic layer: only explicitly supplied/discovered candidate URLs are
    # accepted after live Product/Offer + identity verification. Search-provider
    # discovery can feed this list later without weakening verification.
    raw=os.getenv('CEBIMDE_EXTRA_PRODUCT_URLS','').strip()
    if not raw:return []
    out=[]
    for u in [x.strip() for x in raw.split(',') if x.strip()][:20]:
        x=verify_external_offer(base,u)
        if x:out.append(x)
    return out

def brave_discover(base):
    key=os.getenv('BRAVE_SEARCH_API_KEY','').strip()
    if not key:return []
    title=(base or {}).get('title') or ''
    gtin=str((base or {}).get('gtin') or '').strip()
    mpn=str((base or {}).get('mpn') or '').strip()
    model=model_token(title) or ''
    brand=str((base or {}).get('brand') or '').strip()
    needle=gtin or mpn or model
    if not needle:return []
    q=' '.join(x for x in [brand,needle,'satın al fiyat'] if x)
    try:
        r=requests.get('https://api.search.brave.com/res/v1/web/search',
          headers={'X-Subscription-Token':key,'Accept':'application/json'},
          params={'q':q,'country':'TR','search_lang':'tr','count':20,'safesearch':'moderate'},timeout=8)
        r.raise_for_status(); j=r.json()
        rows=((j.get('web') or {}).get('results') or [])
        seen=set(); out=[]
        for row in rows:
            u=(row or {}).get('url')
            if not u or u in seen:continue
            seen.add(u)
            host=(urlparse(u).hostname or '').lower().replace('www.','')
            if not host or any(x in host for x in ['youtube.com','facebook.com','instagram.com','x.com','twitter.com']):continue
            # Known marketplaces are already queried through dedicated providers.
            if any(x in host for x in ['hepsiburada.com','trendyol.com','n11.com','amazon.com.tr']):continue
            v=verify_external_offer(base,u)
            if v:out.append(v)
            if len(out)>=6:break
        return out
    except Exception:return []

def searxng_discover(base):
    endpoint=os.getenv('SEARXNG_URL','').strip().rstrip('/')
    if not endpoint:return []
    title=(base or {}).get('title') or ''
    needle=str((base or {}).get('gtin') or (base or {}).get('mpn') or model_token(title) or '').strip()
    brand=str((base or {}).get('brand') or '').strip()
    if not needle:return []
    # Search both the open Turkish web and high-value national retailers.
    # Every candidate still has to pass verify_external_offer; discovery alone
    # never becomes a price.
    national=('teknosa.com','mediamarkt.com.tr','vatanbilgisayar.com','pazarama.com',
              'pttavm.com','idefix.com','ciceksepeti.com','trendyol.com',
              'hepsiburada.com','n11.com','amazon.com.tr')
    # Keep the user-facing request below Render's proxy timeout. One broad
    # SearXNG query already returns multiple Turkish shops; site-specific deep
    # searches belong in background monitoring, not the interactive request.
    queries=[' '.join(x for x in [brand,needle,'satın al fiyat Türkiye'] if x)]
    headers={'User-Agent':'Mozilla/5.0 CEBIMDE/3.58','Accept-Language':'tr-TR,tr;q=0.9'}
    try:
        seen=set(); out=[]
        blocked=('youtube.com','facebook.com','instagram.com','x.com','twitter.com','wikipedia.org',
                 'pinterest.com','tiktok.com','linkedin.com','web.archive.org','archive.org')
        searx_host=(urlparse(endpoint).hostname or '').lower().replace('www.','')
        for q in queries:
            params={'q':q,'language':'tr-TR','safesearch':1,'categories':'general','pageno':1}
            # Render Free can cold-start SearXNG in 50s+. Give the first
            # request time to wake the service, then retry once before skipping.
            r=None
            for attempt in range(2):
                try:
                    r=requests.get(endpoint+'/search',params=params,
                                   headers=dict(headers,Accept='text/html'),
                                   timeout=65 if attempt==0 else 15)
                    if r.ok:break
                except requests.RequestException:
                    r=None
            if not r or not r.ok:continue
            urls=searx_result_urls(r.text,endpoint)
            checked=0
            for u in urls:
                if not u or u in seen:continue
                seen.add(u); host=(urlparse(u).hostname or '').lower().replace('www.','')
                if not host or host==searx_host or any(x in host for x in blocked):continue
                # Verify only a bounded set of unique live shop pages per query.
                # Archive/navigation noise is discarded before any page fetch.
                checked+=1
                if checked>4:break
                v=verify_external_offer(base,u)
                if v:out.append(v)
                if len(out)>=16:return sorted(out,key=lambda x:x['price'])
        return sorted(out,key=lambda x:x['price'])
    except Exception:return []


def reef_hepsiburada_offers(sku, url):
    key=os.getenv('REEF_API_KEY','').strip()
    if not key or not sku:return None
    try:
        r=requests.post('https://api.reefapi.com/hepsiburada/v1/product/offers',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'sku':sku},timeout=15)
        print('[HB_OFFERS] status=',r.status_code,'content_type=',r.headers.get('content-type'),flush=True)
        r.raise_for_status(); j=r.json()
        print('[HB_OFFERS] ok=',j.get('ok'),'error=',j.get('error') or j.get('message'),'data_type=',type(j.get('data')).__name__,flush=True)
        if not j.get('ok'):return None
        d=j.get('data') or {}
        candidates=[]
        for o in walk(d):
            if not isinstance(o,dict):continue
            price=clean_price(o.get('price'))
            if not price:continue
            order=o.get('buybox_order')
            candidates.append((order if isinstance(order,(int,float)) else 9999,price,o))
        if not candidates:return None
        candidates.sort(key=lambda x:(x[0],x[1]))
        _,price,o=candidates[0]
        return {'source':'Hepsiburada','price':price,'url':url,
                'title':o.get('title') or o.get('name') or sku,'sku':sku}
    except Exception as e:
        print('[HB_OFFERS_EXCEPTION]',type(e).__name__,str(e)[:300],flush=True)
        return None

def fetch_offer(url,source):
    r=requests.get(url,headers=HEADERS,timeout=6); r.raise_for_status()
    p=extract_product(r.text,url)
    if not strict_zbmini_l2(p['title']) or not p['price']: return None
    return {'source':source,'price':p['price'],'url':url,'title':p['title']}

def reef_hepsiburada(sku, url):
    key=os.getenv('REEF_API_KEY','').strip()
    if not key:return None
    try:
        payload={'sku':sku} if sku else {'url':url}
        payload['max_rotations']=3
        r=requests.post('https://api.reefapi.com/hepsiburada/v1/product/detail',
            headers={'x-api-key':key,'content-type':'application/json'},
            json=payload,timeout=12)
        print('[HB_DETAIL] status=',r.status_code,'content_type=',r.headers.get('content-type'),flush=True)
        r.raise_for_status(); j=r.json()
        print('[HB_DETAIL] ok=',j.get('ok'),'error=',j.get('error') or j.get('message'),'data_type=',type(j.get('data')).__name__,flush=True)
        if not j.get('ok'):return None
        d=j.get('data') or {}
        # Reef HB detail currently wraps the actual product in data.product.
        # Normalize that row first, then keep a recursive fallback for schema drift.
        product=d.get('product') if isinstance(d,dict) else None
        if isinstance(product,dict):
            rsku=str(product.get('sku') or product.get('productSku') or '').upper()
            title=product.get('title') or product.get('name') or product.get('productName')
            price=None
            for field in ('price','currentPrice','salePrice','discountedPrice','finalPrice'):
                price=clean_price(product.get(field))
                if price:break
            if not price:
                for o in walk(product):
                    if not isinstance(o,dict):continue
                    for field in ('price','currentPrice','salePrice','discountedPrice','finalPrice'):
                        price=clean_price(o.get(field))
                        if price:break
                    if price:break
            if price and (not sku or not rsku or rsku==sku.upper()):
                return {'source':'Hepsiburada','price':price,'url':url,
                        'title':title or sku,'sku':rsku or sku}
        if isinstance(d,dict):
            rsku=str(d.get('sku') or '').upper()
            title=d.get('title') or d.get('name')
            price=clean_price(d.get('price'))
            if price and (not sku or not rsku or rsku==sku.upper()):
                return {'source':'Hepsiburada','price':price,'url':url,
                        'title':title or sku,'sku':rsku or sku}
        # Defensive fallback for an envelope/wrapper around the product.
        for o in walk(d):
            if not isinstance(o,dict):continue
            rsku=str(o.get('sku') or '').upper()
            title=o.get('title') or o.get('name')
            price=clean_price(o.get('price'))
            if price and ((sku and rsku==sku.upper()) or (not sku and title)):
                return {'source':'Hepsiburada','price':price,'url':url,
                        'title':title or sku,'sku':rsku or sku}
    except Exception as e:
        print('[HB_DETAIL_EXCEPTION]',type(e).__name__,str(e)[:300],flush=True)
        return None
    return None

def hepsiburada_public_price(title):
    # Fallback to Hepsiburada's publicly indexed category/search HTML when
    # the submitted product page blocks server-side requests.
    # A price is accepted only beside an exact ZBMINI-L2 single-unit title.
    try:
        u='https://www.hepsiburada.com/ara?q='+quote_plus(title)
        r=requests.get(u,headers=HEADERS,timeout=6); r.raise_for_status()
        text=html.unescape(re.sub(r'<[^>]+>',' ',r.text))
        text=re.sub(r'\s+',' ',text)
        m=re.search(r'Sonoff\\s+ZigBee?\\s+Mini\\s+L2\\s+Nötrsüz\\s+Akıllı\\s+Röle.{0,900}?([0-9]{1,3}(?:\\.[0-9]{3})*,[0-9]{2})\\s*TL',text,re.I)
        if m:
            price=clean_price(m.group(1))
            if price:
                return {'source':'Hepsiburada','price':price,'url':u,'title':'Sonoff ZigBee Mini L2 Nötrsüz Akıllı Röle'}
    except Exception: pass
    return None

def matched_offers(title, base=None):
    # Dedicated marketplace adapters are trusted through their own exact-model
    # checks. General-web discovery is separately subjected to identity_match().
    marketplace_offers=[]
    for provider in (discover_n11, discover_trendyol, discover_amazon):
        try:
            marketplace_offers += provider(title)
        except Exception:
            pass
    offers=marketplace_offers
    if base:
        offers+=discover_web_candidates(base)
        offers+=brave_discover(base)
        offers+=searxng_discover(base)
    if strict_zbmini_l2(title):
        sources=[('Bilteknik','https://bilteknik.com.tr/urun/sonoff-zbminil2-akilli-ev-rolesi')]
        for source,url in sources:
            try:
                x=fetch_offer(url,source)
                if x:offers.append(x)
            except Exception:pass
    # Deduplicate source+URL and sort by verified price.
    uniq={}
    for x in offers:uniq[(x['source'],x['url'])]=x
    return sorted(uniq.values(),key=lambda x:x['price'])

@app.errorhandler(Exception)
def unhandled(e):
    return jsonify(ok=False,error='Sunucu hatası. Fiyat uydurulmadı.'),500

@app.get('/')
def home():return send_from_directory('web','index.html')

@app.get('/health')
def health():return jsonify(ok=True,service='cebimde',version='3.58')

@app.get('/api/debug/n11')
def debug_n11():
    model=request.args.get('model','UT12D').strip().upper()
    if not re.fullmatch(r'[A-Z0-9-]{3,24}',model):return jsonify(ok=False,error='Gecersiz model'),400
    key=os.getenv('REEF_API_KEY','').strip()
    if not key:return jsonify(ok=False,error='Reef anahtari tanimli degil'),503
    try:
        r=requests.post('https://api.reefapi.com/n11/v1/search',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'query':model,'page':1,'max_rotations':1},timeout=8)
        j=r.json()
        d=j.get('data') if isinstance(j,dict) else None
        rows=[]
        if isinstance(d,dict):
            for k in ('products','results','items'):
                if isinstance(d.get(k),list):rows=d[k];break
        elif isinstance(d,list):rows=d
        sample=[]
        for x in rows[:5]:
            if not isinstance(x,dict):continue
            t=x.get('title') or x.get('name') or x.get('product_name')
            raw=x.get('price_value')
            if raw is None:raw=x.get('price')
            if raw is None:raw=x.get('sale_price')
            sample.append({'title':str(t or '')[:140],'model_match':same_model(model,t),
                'price_present':clean_price(raw) is not None,
                'url_present':bool(x.get('url') or x.get('product_url') or x.get('link')),
                'fields':list(x.keys())[:20]})
        return jsonify(ok=True,version='3.58',http_status=r.status_code,reef_ok=j.get('ok') if isinstance(j,dict) else None,
            error=str(j.get('error') or j.get('message') or '')[:180] if isinstance(j,dict) else '',
            data_type=type(d).__name__,data_keys=list(d.keys())[:20] if isinstance(d,dict) else [],
            count=len(rows),sample=sample)
    except Exception as e:return jsonify(ok=False,error=type(e).__name__),502

@app.get('/api/debug/hb')
def debug_hb():
    sku=request.args.get('sku','').strip().upper()
    if not re.fullmatch(r'HBCV[0-9A-Z]+',sku):
        return jsonify(ok=False,error='Gecersiz SKU'),400
    key=os.getenv('REEF_API_KEY','').strip()
    out={'ok':True,'sku':sku,'reef_key_present':bool(key)}
    if not key:return jsonify(out)
    tests=[
        ('detail','https://api.reefapi.com/hepsiburada/v1/product/detail',{'sku':sku,'max_rotations':1}),
        ('offers','https://api.reefapi.com/hepsiburada/v1/product/offers',{'sku':sku})
    ]
    for label,endpoint,payload in tests:
        try:
            r=requests.post(endpoint,headers={'x-api-key':key,'content-type':'application/json'},json=payload,timeout=20)
            item={'http_status':r.status_code,'content_type':r.headers.get('content-type')}
            try:
                j=r.json()
                if isinstance(j,dict):
                    item['reef_ok']=j.get('ok')
                    item['error']=j.get('error') or j.get('message')
                    d=j.get('data')
                    item['data_type']=type(d).__name__
                    if isinstance(d,dict):
                        item['data_keys']=list(d.keys())[:25]
                        item['returned_sku']=d.get('sku')
                        item['title']=d.get('title') or d.get('name')
                        item['price']=d.get('price')
                        if isinstance(d.get('offers'),list):item['offers_count']=len(d.get('offers'))
                        # Safe nested diagnostics: expose only product field names and
                        # price-like values, never credentials or the full provider payload.
                        product=d.get('product')
                        if isinstance(product,dict):
                            item['product_keys']=list(product.keys())[:60]
                            item['product_title']=product.get('title') or product.get('name') or product.get('productName')
                            item['product_sku']=product.get('sku') or product.get('productSku')
                            price_fields={}
                            for k,v in product.items():
                                lk=str(k).lower()
                                if any(x in lk for x in ('price','amount','sale','discount','final','current')):
                                    if isinstance(v,(str,int,float,bool)) or v is None:
                                        price_fields[str(k)]=v
                                    elif isinstance(v,dict):
                                        price_fields[str(k)]={str(kk):vv for kk,vv in list(v.items())[:20] if isinstance(vv,(str,int,float,bool)) or vv is None}
                            item['product_price_fields']=price_fields
                    elif isinstance(d,list):
                        item['data_count']=len(d)
                        if d and isinstance(d[0],dict):item['first_keys']=list(d[0].keys())[:25]
            except Exception as e:
                item['json_error']=type(e).__name__
                item['body_prefix']=r.text[:300]
            out[label]=item
        except Exception as e:
            out[label]={'exception':type(e).__name__,'message':str(e)[:300]}
    return jsonify(out)


@app.get('/api/debug/web')
def debug_web():
    # Minimal diagnostics. Never let this endpoint throw a Flask 500.
    model=request.args.get('model','').strip()
    try:
        if not re.fullmatch(r'[A-Za-z0-9 ._-]{2,40}',model):
            return jsonify(ok=False,error='Gecersiz model'),400
        endpoint=os.getenv('SEARXNG_URL','').strip().rstrip('/')
        if not endpoint:
            return jsonify(ok=False,error='SEARXNG_URL yok'),503
        q='"'+model+'" fiyat satin al Turkiye'
        headers={'User-Agent':'Mozilla/5.0 CEBIMDE/3.58','Accept':'text/html','Accept-Language':'tr-TR,tr;q=0.9'}
        try:
            r=requests.get(endpoint+'/search',params={'q':q,'language':'tr-TR','safesearch':1,'categories':'general','pageno':1},
                           headers=headers,timeout=70)
        except Exception as e:
            return jsonify(ok=False,stage='searxng_request',error=type(e).__name__,message=str(e)[:300]),502
        body=r.text or ''
        if r.status_code >= 400:
            return jsonify(ok=False,version='3.58',stage='searxng_http',http_status=r.status_code,
                           searxng_host=(urlparse(endpoint).hostname or ''),
                           body_head=re.sub(r'\\s+',' ',body[:1200]),
                           content_type=r.headers.get('content-type')),200
        # Parse actual SearXNG result anchors, including redirect links.
        urls=searx_result_urls(body,endpoint)
        host0=(urlparse(endpoint).hostname or '').lower().replace('www.','')
        candidates=[]
        for u in urls:
            try:
                host=(urlparse(u).hostname or '').lower().replace('www.','')
            except Exception:
                continue
            if not host or host==host0: continue
            if any(x in host for x in ('youtube.com','facebook.com','instagram.com','x.com','twitter.com','wikipedia.org','pinterest.com','tiktok.com','linkedin.com')):
                continue
            candidates.append({'host':host,'url':u[:500]})
            if len(candidates)>=30: break
        return jsonify(ok=True,version='3.58',model=model,query=q,searxng_host=host0,
                       http_status=r.status_code,html_len=len(body),absolute_urls=len(urls),
                       candidates=candidates)
    except Exception as e:
        return jsonify(ok=False,version='3.58',stage='debug_guard',error=type(e).__name__,message=str(e)[:300]),200


@app.get('/api/product')
def product():
    target=request.args.get('url','').strip()
    try:
        p=urlparse(target); host=(p.hostname or '').lower()
        if p.scheme not in ('http','https') or host not in ALLOWED: raise ValueError('Desteklenmeyen bağlantı.')
        title=None; input_product={}
        try:
            r=requests.get(target,headers=HEADERS,timeout=6); r.raise_for_status(); input_product=extract_product(r.text,target); title=input_product.get('title')
        except Exception: pass
        sku_match=re.search(r'(HBCV[0-9A-Z]+)',target,re.I) if host in ('hepsiburada.com','www.hepsiburada.com') else None
        sku=sku_match.group(1).upper() if sku_match else None
        hb=None
        if host in ('hepsiburada.com','www.hepsiburada.com'):
            # Reef accepts the original product URL too. Some HB URLs expose a
            # product code that is not the same SKU field returned in nested data.
            hb=reef_hepsiburada(sku,target)
            if not hb and sku:
                hb=reef_hepsiburada_offers(sku,target)
            if not hb and sku:
                hb=reef_hepsiburada(None,target)
            if hb and not title:title=hb.get('title')
        # Marketplace pages can block direct server fetches. For Hepsiburada,
        # a successful Reef detail response is authoritative for the submitted URL.
        if hb and hb.get('title'):
            title=hb['title']
        # Last-resort identity recovery from the submitted marketplace URL.
        # We still never invent a price: this only recovers the model/title needed
        # to query and verify price providers.
        if not title:
            slug=html.unescape((p.path or '').strip('/').split('-p-')[0]).replace('-',' ')
            slug=re.sub(r'\s+',' ',slug).strip()
            recovered_model=model_token(slug)
            if recovered_model:
                title=slug
        # A marketplace SKU alone is not a product identity. Do not label a
        # bare code as verified or compare unrelated marketplace results.
        if not title or (sku and title.strip().upper()==sku):
            raise ValueError('Ürün adı doğrulanamadı. Mağaza geçici olarak ürün bilgisini vermiyor; fiyat karşılaştırması yapılmadı.')

        base=dict(input_product or {})
        base['title']=title
        base['mpn']=base.get('mpn') or model_token(title)
        try:
            offers=matched_offers(title,base)
        except Exception as e:
            print('[MATCHED_OFFERS_EXCEPTION]',type(e).__name__,str(e)[:300],flush=True)
            offers=[]
        input_price=input_product.get('price')
        if hb:
            input_price=hb['price']
            offers.append(hb)
            offers=sorted(offers,key=lambda x:x['price'])
        best=offers[0]['price'] if offers else None
        savings=round(input_price-best,2) if input_price and best and input_price>best else 0
        result={'title':title,'input_source':host,'input_url':target,'input_price':input_price,'offers':offers,'price':best,'price_source':offers[0]['source'] if offers else None,'currency':'TRY' if offers else None,'savings':savings}
        return jsonify(ok=True,product=result)
    except Exception as e:return jsonify(ok=False,error=str(e)),422

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
