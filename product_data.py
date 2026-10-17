import html,json,math,re
from urllib.parse import urlparse,urljoin

def structured_product(page,url):
    from app import walk,clean_price
    products=[]
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:data=json.loads(html.unescape(raw).strip())
        except (ValueError,TypeError):continue
        for p in walk(data):
            t=p.get('@type');t=t if isinstance(t,list) else [t]
            if 'Product' in t:products.append(p)
    unique={json.dumps(p,sort_keys=True):p for p in products};products=list(unique.values())
    path=urlparse(url).path.rstrip('/').casefold()
    exact=[p for p in products if urlparse(urljoin(url,str(p.get('url') or ''))).path.rstrip('/').casefold()==path and p.get('url')]
    candidates=exact or ([products[0]] if len(products)==1 and not products[0].get('url') else [])
    if not candidates:return None
    p=candidates[0];brand=p.get('brand');brand=brand.get('name') if isinstance(brand,dict) else brand
    base={'title':p.get('name'),'brand':brand,'sku':p.get('sku'),'mpn':p.get('mpn'),
          'gtin':p.get('gtin13') or p.get('gtin14') or p.get('gtin12') or p.get('gtin8') or p.get('gtin'),
          'price':None,'currency':None,'url':url}
    offers=p.get('offers') or [];offers=offers if isinstance(offers,list) else [offers]
    prices=[]
    for o in offers:
        if not isinstance(o,dict) or o.get('@type')=='AggregateOffer':continue
        if str(o.get('priceCurrency','')).upper() not in ('TRY','TL','₺'):continue
        availability=str(o.get('availability') or '').rsplit('/',1)[-1]
        if availability and availability not in ('InStock','LimitedAvailability','OnlineOnly'):continue
        price=clean_price(o.get('price'))
        if price is not None and math.isfinite(price) and 0<price<100000000:prices.append(price)
    if prices:base.update(price=min(prices),currency='TRY')
    return base if base.get('title') else None



def normalized_title(value):
    import unicodedata
    text=unicodedata.normalize('NFKD',str(value or '').casefold().replace('ı','i').replace('+',' plus '))
    return ' '.join(re.findall(r'[a-z0-9]+',''.join(c for c in text if not unicodedata.combining(c))))


def variant_signature(value):
    text=normalized_title(value)
    colors={'siyah','beyaz','lacivert','mavi','kirmizi','yesil','bej','gri','pembe','black','white','blue','red','green','pink','gray','grey'}
    color=tuple(sorted(set(text.split())&colors))
    amounts=tuple(sorted(re.findall(r'\b(\d+)\s*(gb|tb|ml|lt|kg|adet|li|lu|yaprak)\b',text)))
    return color,amounts


def same_product(base,candidate):
    from app import identity_match
    for key in ('gtin','mpn'):
        a=normalized_title(base.get(key));b=normalized_title(candidate.get(key))
        if a and b and a!=b:return False
    brand_a=normalized_title(base.get('brand')).replace(' ','')
    brand_b=normalized_title(candidate.get('brand')).replace(' ','')
    if brand_a and brand_b and brand_a!=brand_b:return False
    av=variant_signature(base.get('title'));bv=variant_signature(candidate.get('title'))
    if any(a and b and a!=b for a,b in zip(av,bv)):return False
    if base.get('gtin') and candidate.get('gtin'):
        return str(base['gtin']).strip()==str(candidate['gtin']).strip()
    if av==bv and identity_match(base,candidate):return True
    a=normalized_title(base.get('title'));b=normalized_title(candidate.get('title'))
    return bool(a==b and len(a)>=16 and len(a.split())>=3)
