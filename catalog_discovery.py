"""Independent public catalog discovery. Catalog quotes are never merchant verification."""
import html,json,re
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin,unquote,quote_plus,parse_qsl
from concurrent.futures import ThreadPoolExecutor
from public_web import fetch_page,normalize_url
from product_data import normalized_title,structured_product,variant_signature

CATALOGS={'cimri.com','epey.com'}

def tokens(value):
    text=normalized_title(value)
    text=re.sub(r'\b(\d+)\s*(?:li|lu|rulo|adet)\b',r'\1',text)
    return set(text.split())-{'li','lu','rulo','adet','katli','en','ucuz','fiyatlari','fiyati','html'}

def rank(base,url):
    want=tokens(base['title']);got=tokens(unquote(urlparse(url).path))
    common=want&got
    return (-len(common),len({v for v in got-want if v.isalpha()}),len(got))

def query_for(base):
    from app import model_token
    title=base.get('title','');model=base.get('mpn') or model_token(title)
    if base.get('gtin'):return str(base['gtin'])
    if model:return (str(base.get('brand') or title.split()[0])+' '+str(model)).strip()
    # Broad brand/quantity retrieval; rank full names and variants afterwards.
    words=normalized_title(title).split()
    amounts=re.findall(r'\b\d+\b',re.sub(r'(\d+)(?:li|lu|rulo)',r'\1',normalized_title(title)))
    return ' '.join(([str(base.get('brand') or (words[0] if words else ''))]+amounts[-2:]) if amounts else words[:6])

class Links(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.links=[];self.merchants=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a':
            if a.get('data-link'):self.merchants.append(unquote(a['data-link']))
            for key in ('href','data-link'):
                if a.get(key):self.links.append(unquote(a[key]) if key=='data-link' else a[key])

def walk(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from walk(v)
    elif isinstance(value,list):
        for v in value:yield from walk(v)

def main_offers(body,source):
    offers=[]
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',body,re.I|re.S):
        try:data=json.loads(raw)
        except (ValueError,TypeError):
            try:data=json.loads(html.unescape(raw))
            except (ValueError,TypeError):continue
        for product in walk(data):
            if product.get('@type')!='Product' or not product.get('url') or page_key(product['url'])!=page_key(source):continue
            offers.extend(item for item in walk(product.get('offers')) if item.get('@type')=='Offer' and item.get('url'))
    return offers

def merchant_links(body,source):
    links=Links();links.feed(body);urls=list(links.merchants)
    # Read merchant destinations only from this page's main Product schema.
    urls.extend(item['url'] for item in main_offers(body,source))
    found=[]
    for value in urls:
        try:
            url=normalize_url(urljoin(source,value));host=urlparse(url).hostname.removeprefix('www.')
            if host in CATALOGS or host.endswith(('.cimri.com','.epey.com')):continue
            if not value.startswith(('https://','http://')):continue
            if any(host==h or host.endswith('.'+h) for h in ('youtube.com','facebook.com','instagram.com','google.com','apple.com','cimri.io')):continue
            if re.search(r'\.(?:png|jpe?g|svg|css|js|webp)(?:\?|$)',url,re.I):continue
            if url not in found:found.append(url)
        except ValueError:continue
    return found

def page_key(url):
    p=urlparse(url)
    tracking={'trackingid','merchantid','magaza','vendorid','ref'}
    query=tuple(sorted((k,v) for k,v in parse_qsl(p.query) if not k.casefold().startswith('utm_') and k.casefold() not in tracking))
    return ((p.hostname or '').removeprefix('www.'),unquote(p.path).rstrip('/'),query)

def quoted_candidate(base,title):
    from app import model_token
    a=variant_signature(base.get('title'));b=variant_signature(title)
    # Repeated pack descriptions ("32'li (1 x 32 rulo)") are one pack,
    # while "2 x 32 rulo" must never be compared to a single 32-pack.
    def multipacks(value):
        return {(int(n),int(size)) for n,size in re.findall(r'\b(\d+)\s*x\s*(\d+)\b',normalized_title(value)) if int(n)>1}
    if multipacks(base.get('title'))!=multipacks(title):return False
    if a[0] and b[0] and a[0]!=b[0]:return False
    if a[1] and b[1] and set(a[1])!=set(b[1]):return False
    model=model_token(base.get('title',''));other=model_token(title)
    if model:return bool(other and re.sub(r'\W','',model).casefold()==re.sub(r'\W','',other).casefold())
    anchors={v for v in tokens(base.get('title','')) if v.isalpha()}
    return len(anchors)>=3 and anchors.issubset(tokens(title))

def catalog_quotes(body,source,base):
    """Explicit, attributed Epey offer cards, separate from verified shop prices."""
    from app import clean_price
    quotes=[]
    if urlparse(source).hostname!='www.epey.com':return quotes
    for attributes,inner in re.findall(r'<a\b([^>]*\bdata-link=[^>]*)>(.*?)</a>',body,re.I|re.S):
        target=re.search(r'data-link=["\']([^"\']+)',attributes,re.I)
        name=re.search(r'class=["\']urun_adi["\'][^>]*>(.*?)(?:<p\b|</span>)',inner,re.S|re.I)
        price=re.search(r'class=["\']urun_fiyat["\'][^>]*>\s*([\d.,]+)\s*(?:TL|₺)',inner,re.S|re.I)
        if not target or not name or not price:continue
        title=' '.join(html.unescape(re.sub('<[^>]+>',' ',name[1])).split())
        if not quoted_candidate(base,title):continue
        try:url=normalize_url(unquote(html.unescape(target[1])))
        except ValueError:continue
        amount=clean_price(price[1])
        if not amount or not 0<amount<100000000:continue
        quotes.append({'title':title,'url':url,'source':urlparse(url).hostname.removeprefix('www.'),'price':amount,
                       'catalogSource':'Epey','catalogUrl':source,'observedAt':datetime.now(timezone.utc).isoformat(),
                       'identityConfirmed':False,'merchantVerified':False})
    return sorted({q['url']:q for q in quotes}.values(),key=lambda q:q['price'])[:12]

def discover_catalogs(base):
    from app import model_token
    model=model_token(base.get('title',''))
    query=query_for(base)
    sources=[('cimri','https://www.cimri.com/arama?q='+quote_plus(query)),
             ('epey','https://www.epey.com/ara/?ara='+quote_plus(query))]
    diagnostics=[]
    def search(pair):
        provider,url=pair;diag={'provider':provider}
        try:page=fetch_page(url,budget=6,diagnostics=diag)
        except Exception as error:diag['error']=type(error).__name__;page=None
        if not page:return [],diag
        parser=Links();parser.feed(page[0]);candidates=[]
        for href in parser.links:
            url=urljoin(page[1],href).split('#')[0];host=urlparse(url).hostname or ''
            other_model=model_token(unquote(urlparse(url).path).replace('-',' '))
            if model and other_model and re.sub(r'\W','',model).casefold()!=re.sub(r'\W','',other_model).casefold():continue
            product=(provider=='cimri' and host=='www.cimri.com' and re.search(r'fiyatlari(?:,|%2[cC])\d+',url)) or (provider=='epey' and host=='www.epey.com' and urlparse(url).path.endswith('.html'))
            if product and url not in candidates and -rank(base,url)[0]>=min(2,len(tokens(base['title']))):candidates.append(url)
        diag['products']=len(candidates)
        return sorted(candidates,key=lambda u:rank(base,u))[:2],diag
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(search,sources))
    products=[]
    for found,diag in results:products+=found;diagnostics.append(diag)
    def read(url):
        try:
            page=fetch_page(url,budget=6)
            if page:
                links=merchant_links(page[0],page[1]);identity=None
                if any(page_key(item['url'])==page_key(base['url']) for item in main_offers(page[0],page[1])):
                    product=structured_product(page[0],page[1])
                    if product:identity={k:product.get(k) for k in ('title','brand','gtin','mpn') if product.get(k)}
                return links,{'url':page[1],'source':urlparse(page[1]).hostname,'kind':'comparison','identityConfirmed':False},identity,catalog_quotes(page[0],page[1],base)
        except Exception:pass
        return [],None,None,[]
    with ThreadPoolExecutor(max_workers=4) as pool:details=list(pool.map(read,products[:4]))
    urls=[];pages=[];identities=[];quotes=[]
    for found,page,identity,listed in details:
        if page:pages.append(page)
        if identity:identities.append(identity)
        quotes+=listed
        for url in found:
            if url not in urls:urls.append(url)
    # Conflicting catalog identities are not resolved automatically.
    identity=identities[0] if identities and len({normalized_title(i['title']) for i in identities})==1 else None
    return {'urls':sorted(urls,key=lambda u:rank(base,u))[:36],'sources':pages,'diagnostics':diagnostics,'identity':identity,
            'quotes':sorted({q['url']:q for q in quotes}.values(),key=lambda q:q['price'])[:12]}
