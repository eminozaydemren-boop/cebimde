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

def fetch_offer(url,source):
    r=requests.get(url,headers=HEADERS,timeout=6); r.raise_for_status()
    p=extract_product(r.text,url)
    if not strict_zbmini_l2(p['title']) or not p['price']: return None
    return {'source':source,'price':p['price'],'url':url,'title':p['title']}

def reef_hepsiburada(sku, url):
    key=os.getenv('REEF_API_KEY','').strip()
    if not key: return None
    try:
        r=requests.post(
            'https://api.reefapi.com/hepsiburada/v1/product/detail',
            headers={'x-api-key':key,'content-type':'application/json'},
            json={'sku':sku} if sku else {'url':url},
            timeout=8)
        r.raise_for_status(); j=r.json()
        if not j.get('ok'): return None
        d=j.get('data') or {}
        candidates=[]
        for o in walk(d):
            if not isinstance(o,dict): continue
            osku=str(o.get('sku') or o.get('productSku') or o.get('merchantSku') or '').upper()
            otitle=o.get('title') or o.get('name') or o.get('productName')
            rawprice=o.get('price')
            if rawprice is None: rawprice=o.get('salePrice')
            if rawprice is None: rawprice=o.get('currentPrice')
            oprice=clean_price(rawprice)
            # Generic HB products: exact SKU is strongest. If Reef omits SKU,
            # accept a priced named product only when this request supplied a SKU.
            if oprice and ((sku and osku==sku.upper()) or (sku and not osku and otitle)):
                candidates.append((o,oprice,osku,otitle))
        if not candidates:return None
        exact=[x for x in candidates if sku and x[2]==sku.upper()]
        o,price,osku,title=(exact or candidates)[0]
        return {'source':'Hepsiburada','price':price,'url':url,'title':title or sku,'sku':osku or sku}
    except Exception: return None

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
    if not strict_zbmini_l2(title): return []
    sources=[
      ('Bilteknik','https://bilteknik.com.tr/urun/sonoff-zbminil2-akilli-ev-rolesi'),
      ('n11','https://www.n11.com/urun/sonoff-zigbee-mini-l2-akilli-role-41386553')]
    offers=[]
    for source,url in sources:
        try:
            x=fetch_offer(url,source)
            if x:offers.append(x)
        except Exception: pass
    return sorted(offers,key=lambda x:x['price'])

@app.errorhandler(Exception)
def unhandled(e):
    return jsonify(ok=False,error='Sunucu hatası. Fiyat uydurulmadı.'),500

@app.get('/')
def home():return send_from_directory('web','index.html')

@app.get('/health')
def health():return jsonify(ok=True,service='cebimde',version='2.7')

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
        if host in ('hepsiburada.com','www.hepsiburada.com') and sku:
            hb=reef_hepsiburada(sku,target)
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
