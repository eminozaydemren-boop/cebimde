from flask import Flask, request, jsonify, send_from_directory
import requests, re, html, json, os
from urllib.parse import quote_plus
from urllib.parse import urlparse

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
    out={'title':None,'brand':None,'sku':None,'image':None,'price':None,'currency':None,'url':url}
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:data=json.loads(html.unescape(raw).strip())
        except:continue
        for o in walk(data):
            t=o.get('@type'); ts=t if isinstance(t,list) else [t]
            if 'Product' not in ts:continue
            out['title']=out['title'] or o.get('name'); out['sku']=out['sku'] or o.get('sku') or o.get('mpn')
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
    toks=re.findall(r'(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*[0-9])[A-Z0-9-]{4,}',s)
    bad={'1000V','600V','220V','90V'}
    toks=[x for x in toks if x not in bad]
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
        rows=d.get('products') if isinstance(d,dict) else []
        out=[]
        for o in rows or []:
            if not isinstance(o,dict):continue
            t=o.get('title'); p=clean_price(o.get('price')); u=o.get('url')
            if p and u and same_model(title,t):
                out.append({'source':'n11','price':p,'url':u,'title':t,
                            'product_id':o.get('product_id')})
        return sorted(out,key=lambda x:x['price'])[:1]
    except Exception:return []

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
        payload['max_rotations']=1
        r=requests.post('https://api.reefapi.com/hepsiburada/v1/product/detail',
            headers={'x-api-key':key,'content-type':'application/json'},
            json=payload,timeout=12)
        r.raise_for_status(); j=r.json()
        if not j.get('ok'):return None
        d=j.get('data') or {}
        # Official Reef HB detail schema exposes these fields on the product row.
        # Prefer the exact requested SKU, but allow URL-resolved detail when Reef
        # has already returned a single product record.
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
    except Exception:return None
    return None

def hepsiburada_public_price(title):
    # Fallback to Hepsiburada's publicly indexed category/search HTML when
    # the submitted product page blocks server-side requests.
    # A price is accepted only beside an exact ZBMINI-L2 single-unit title.
    try:
        u='https://www.hepsiburada.com/ara?q='+quote_plus(title)
        r=requests.get(u,headers=HEADERS,timeout=6); r.raise_for_status()
        text=html.unescape(re.sub(r'<[^>]+>',' ',r.text))
        text=re.sub(r'\\s+',' ',text)
        m=re.search(r'Sonoff\\s+ZigBee?\\s+Mini\\s+L2\\s+Nötrsüz\\s+Akıllı\\s+Röle.{0,900}?([0-9]{1,3}(?:\\.[0-9]{3})*,[0-9]{2})\\s*TL',text,re.I)
        if m:
            price=clean_price(m.group(1))
            if price:
                return {'source':'Hepsiburada','price':price,'url':u,'title':'Sonoff ZigBee Mini L2 Nötrsüz Akıllı Röle'}
    except Exception: pass
    return None

def matched_offers(title):
    offers=discover_n11(title)
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
def health():return jsonify(ok=True,service='cebimde',version='3.2')

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
                hb=reef_hepsiburada(None,target)
            if hb and not title:title=hb.get('title')
        if not title: raise ValueError('Ürün kimliği doğrulanamadı.')
        offers=matched_offers(title)
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
