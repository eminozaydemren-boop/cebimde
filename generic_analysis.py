"""Identify a product from any public seller, then verify matching web offers."""
import html,os,re,time
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin,unquote
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from public_web import normalize_url,fetch_page
from product_data import structured_product,same_product
from price_monitor import verified_offer

class ProductInfoRequired(ValueError):pass

class PageMeta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.meta={};self.heading=[];self.in_h1=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta':
            key=a.get('property') or a.get('name')
            if key:self.meta.setdefault(key.casefold(),a.get('content',''))
        if tag=='h1':self.in_h1=True
    def handle_endtag(self,tag):
        if tag=='h1':self.in_h1=False
    def handle_data(self,value):
        if self.in_h1:self.heading.append(value)


def gtin_in_url(url):
    for n in re.findall(r'(?<!\d)(\d{13}|\d{14}|\d{12}|\d{8})(?!\d)',url):
        if sum(int(c)*(3 if i%2==0 else 1) for i,c in enumerate(n[-2::-1]))%10 == (10-int(n[-1]))%10:return n
    return None


def url_title(url):
    path=unquote(urlparse(url).path)
    if re.search(r'/(?:search|arama|kategori|category|collections?)(?:/|$)',path,re.I):return None
    slug=path.rstrip('/').split('/')[-1]
    slug=re.split(r'-(?:p|pm)-',slug,flags=re.I)[0]
    slug=re.sub(r'\.(?:html?|aspx?)$','',slug,flags=re.I)
    title=re.sub(r'[-_]+',' ',slug).strip()
    return title[:250] if len(title)>=12 and len(title.split())>=2 else None


def discover(base):
    from app import model_token,searx_result_urls
    endpoint=os.getenv('SEARXNG_URL','').strip().rstrip('/')
    if not endpoint:return []
    title=base.get('title') or ''
    barcode=base.get('gtin');model=base.get('mpn') or model_token(title)
    queries=[]
    if barcode:queries.append(str(barcode)+' fiyat')
    if model:queries.append(' '.join(x for x in (base.get('brand'),str(model),'satın al fiyat') if x))
    queries.append('"'+title[:180]+'" fiyat')
    queries=list(dict.fromkeys(queries))[:2]
    def search(query):
        try:
            r=requests.get(endpoint+'/search',params={'q':query,'language':'tr-TR','categories':'general','pageno':1},timeout=4)
            return searx_result_urls(r.text,endpoint) if r.ok else []
        except requests.RequestException:return []
    urls=[]
    blocked=('google.com','bing.com','duckduckgo.com','youtube.com','facebook.com','instagram.com','pinterest.com','tiktok.com')
    with ThreadPoolExecutor(max_workers=2) as pool:
        for found in pool.map(search,queries):
            for url in found:
                try:
                    url=normalize_url(url);host=urlparse(url).hostname
                    if host==urlparse(endpoint).hostname or any(host==h or host.endswith('.'+h) for h in blocked):continue
                    if url!=base['url'] and url not in urls:urls.append(url)
                except ValueError:continue
    return urls[:6]


def compare(base):
    urls=discover(base)
    def verify(url):
        try:
            page=fetch_page(url,budget=5)
            if page:
                result=verified_offer(page[0],page[1],base)
                if result:return dict(result,source=urlparse(result['url']).hostname.removeprefix('www.'),title=base['title'])
        except Exception:pass
        return None
    # Four pages in parallel; discovery results alone never become prices.
    with ThreadPoolExecutor(max_workers=4) as pool:out=list(pool.map(verify,urls[:4]))
    return [x for x in out if x]


def analyze_any_seller(target,hint=''):
    target=normalize_url(target);source=target
    try:page=fetch_page(target,budget=7)
    except Exception:page=None
    base=None;structured=False
    if page:
        body,source=page
        base=structured_product(body,source)
        structured=bool(base)
        if not base:
            meta=PageMeta()
            try:meta.feed(body)
            except Exception:pass
            title=meta.meta.get('og:title') or ' '.join(meta.heading).strip()
            if title:base={'title':title[:250],'url':source,'price':None,'currency':None}
    if not base:
        title=str(hint or '').strip()[:250] or url_title(source)
        if not title:raise ProductInfoRequired('Bu linkten ürün adı okunamadı. Ürün adı veya barkod alanını doldurarak yeniden dene.')
        base={'title':title,'url':source,'price':None,'currency':None,'gtin':gtin_in_url(source) or gtin_in_url(hint)}
    base.setdefault('url',source)
    offers=[]
    if base.get('price') is not None:
        offers.append({'source':urlparse(source).hostname.removeprefix('www.'),'price':base['price'],'url':source,'title':base['title']})
    offers+=compare(base)
    offers=sorted({o['url']:o for o in offers}.values(),key=lambda o:o['price'])
    best=offers[0]['price'] if offers else None
    input_price=base.get('price')
    result={'title':base['title'],'input_source':urlparse(source).hostname.removeprefix('www.'),'input_url':target,
            'input_price':input_price,'offers':offers,'price':best,'price_source':offers[0]['source'] if offers else None,
            'currency':'TRY' if offers else None,'savings':round(input_price-best,2) if input_price and best and input_price>best else 0,
            'identityVerified':bool(structured or offers),'searchMode':'open_web'}
    from watch_store import sign_snapshot
    result['watchReceipt']=sign_snapshot(target,best,base=base,offers=offers)
    return result
