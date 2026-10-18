"""Identify a product from any public seller, then verify matching web offers."""
import html,os,re,time
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin,unquote
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from public_web import normalize_url,fetch_page
from product_data import structured_product,same_product,plausible_product
from price_monitor import verified_offer
from product_links import product_link
from catalog_discovery import discover_catalogs
from search_api import discover_api

class ProductInfoRequired(ValueError):pass

class SearchResults(HTMLParser):
    """Read result articles, excluding engine errors, navigation and footer links."""
    def __init__(self):
        super().__init__(convert_charrefs=True);self.depth=0;self.links=[];self.articles=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='article' and 'result' in a.get('class','').split():
            self.depth+=1;self.articles=True
        if self.depth and tag=='a' and a.get('href'):self.links.append(a['href'])
    def handle_endtag(self,tag):
        if tag=='article' and self.depth:self.depth-=1

def search_links(body,endpoint):
    from app import searx_result_urls
    parser=SearchResults();parser.feed(body)
    # Older SearXNG themes can return fragments without an article wrapper.
    if not parser.articles:
        if '<html' in body.casefold():return []
        return searx_result_urls(body,endpoint)
    return searx_result_urls(''.join('<a href="'+html.escape(u,quote=True)+'"></a>' for u in parser.links),endpoint)

def candidate_link(url):
    """Skip definite listings before spending a limited verification slot."""
    url=product_link(url)
    path=unquote(urlparse(url).path).casefold()
    if re.search(r'/(?:search|arama|kategori(?:ler)?|categor(?:y|ies)|collections?|s)(?:/|$)',path):
        raise ValueError('listing')
    if re.search(r'-k-[a-z0-9]+/?$',path):raise ValueError('listing')
    return url

class PageMeta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.meta={};self.headings=[];self.current_heading=None;self.ignored=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta':
            key=a.get('property') or a.get('name')
            if key:self.meta.setdefault(key.casefold(),a.get('content',''))
        if tag in ('script','style'):self.ignored+=1
        if tag=='h1' and not self.ignored:
            self.current_heading=[];self.headings.append(self.current_heading)
    def handle_endtag(self,tag):
        if tag=='h1':self.current_heading=None
        if tag in ('script','style'):self.ignored=max(0,self.ignored-1)
    def handle_data(self,value):
        if self.current_heading is not None and not self.ignored:self.current_heading.append(value)
    @property
    def heading(self):
        # Separate h1 elements are separate headings, not parts of a product name.
        # Retailers commonly use additional h1 elements for product reviews.
        return next((parts for parts in self.headings if ''.join(parts).strip()),[])


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
    parts=path.strip('/').split('/')
    if (urlparse(url).hostname or '').removeprefix('www.')=='trendyol.com' and len(parts)==2:
        brand=re.sub(r'[-_]+',' ',parts[0]).strip()
        if brand and not title.casefold().startswith(brand.casefold()+' '):title=brand+' '+title
    return title[:250] if len(title)>=12 and len(title.split())>=2 else None


def discover_web(base):
    from app import model_token
    endpoint=os.getenv('SEARXNG_URL','').strip().rstrip('/')
    if not endpoint:
        base['_search']={'status':'not_configured','candidates':0};return []
    title=base.get('title') or ''
    barcode=base.get('gtin');model=base.get('mpn') or model_token(title)
    queries=[]
    if barcode:queries.append(str(barcode)+' fiyat')
    if model:queries.append(' '.join(x for x in (base.get('brand'),str(model),'satin al fiyat Turkiye') if x))
    if not barcode and not model:queries.append(title[:180]+' fiyat satın al')
    queries.append('"'+title[:180]+'" fiyat')
    queries=list(dict.fromkeys(queries))[:2]
    price_query_count=len(queries)
    queries.append(title[:160]+' broşür aktüel katalog')
    def search(query):
        try:
            # Free Render instances can need tens of seconds to wake. A seven-second
            # deadline discarded successful searches, independently of product/store.
            r=requests.get(endpoint+'/search',params={'q':query,'language':'tr-TR','categories':'general','pageno':1},headers={'User-Agent':'Mozilla/5.0 CEBIMDE/3.87','Accept':'text/html','Accept-Language':'tr-TR,tr;q=0.9'},timeout=(5,12))
            found=search_links(r.text,endpoint) if r.ok else []
            empty=bool(re.search(r'id=["\']no_results["\']|No results were found',r.text,re.I))
            upstream_failed=bool(re.search(r'class=["\']response-error["\']',r.text,re.I)) and not found
            # HTTP 200 error/challenge pages are not successful searches.
            return (bool(r.ok and (found or (empty and not upstream_failed))),found,{'httpStatus':r.status_code,'links':len(found),'state':'results' if found else 'upstream_unavailable' if upstream_failed else 'empty' if empty else 'invalid_response'})
        except requests.RequestException as error:return (False,[],{'state':type(error).__name__})
    urls=[];success=False;brochures=[];attempts=[]
    blocked=('google.com','bing.com','duckduckgo.com','youtube.com','facebook.com','instagram.com','pinterest.com','tiktok.com','akakce.com','cimri.com','epey.com','x.com','twitter.com','web.archive.org')
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index,(ok,found,diagnostic) in enumerate(pool.map(search,queries)):
            attempts.append(dict(diagnostic,kind='price' if index<price_query_count else 'brochure'))
            if index<price_query_count:success=success or ok
            for url in found:
                try:
                    url=normalize_url(url);host=urlparse(url).hostname
                    path=unquote(urlparse(url).path).casefold()
                    comparison=any(host==h or host.endswith('.'+h) for h in ('akakce.com','cimri.com'))
                    brochure=bool(re.search(r'/(?:brosur(?:ler)?|aktuel|katalog)[^/]*(?:/|[-.]|$)',path))
                    social=any(host==h or host.endswith('.'+h) for h in blocked if h not in ('akakce.com','cimri.com'))
                    if host==urlparse(endpoint).hostname or social:continue
                    if comparison or brochure:
                        if url not in [item['url'] for item in brochures]:brochures.append({'url':url,'source':host.removeprefix('www.'),'kind':'brochure' if brochure else 'comparison','identityConfirmed':False})
                    if comparison or brochure:continue
                    if index>=price_query_count:continue
                    url=candidate_link(url)
                    if url!=base['url'] and url not in urls:urls.append(url)
                except ValueError:continue
    # Rank by product identifiers in the URL, never by a fixed retailer list.
    needle=re.sub(r'[^a-z0-9]','',str(barcode or model or '').casefold())
    def rank(url):
        path=re.sub(r'[^a-z0-9]','',unquote(urlparse(url).path).casefold())
        return 0 if needle and needle in path else 1
    ranked=sorted(urls,key=rank)
    # Give each merchant one slot before checking further pages from the same shop.
    distinct=[];duplicates=[];hosts=set()
    for url in ranked:
        host=urlparse(url).hostname.removeprefix('www.')
        if host in hosts:duplicates.append(url)
        else:hosts.add(host);distinct.append(url)
    selected=(distinct+duplicates)[:12]
    base['_brochures']=sorted(brochures,key=lambda item:0 if item['kind']=='brochure' else 1)[:4]
    base['_search']={'status':'completed' if success else 'unavailable','candidates':len(selected),'attempts':attempts}
    return selected


def discover(base):
    """Catalog discovery works independently of the web search service."""
    api=discover_api(base)
    if api['state']=='rate_limited':
        base['_search']={'status':'rate_limited','provider':'tavily_free','candidates':0,'retryAfterSeconds':api['retryAfterSeconds']}
        return []
    if api['urls']:
        urls=[];duplicates=[];hosts=set()
        for value in api['urls']:
            try:url=candidate_link(value)
            except ValueError:continue
            host=urlparse(url).hostname.removeprefix('www.')
            if host in hosts:duplicates.append(url)
            else:hosts.add(host);urls.append(url)
        selected=(urls+duplicates)[:12]
        if selected:
            base['_search']={'status':'completed','provider':'tavily_free','candidates':len(selected),'attempts':[]}
            return selected
    catalog=discover_catalogs(base)
    base['_catalogQuotes']=catalog.get('quotes',[])
    if catalog.get('identity') and base.get('_inputStructured') is False:
        # Recover names only when the catalog explicitly links the submitted
        # merchant product page. Catalog prices never enter verified offers.
        base.update(catalog['identity'])
    urls=[]
    for url in catalog['urls']:
        try:
            url=candidate_link(url)
            if url!=base['url'] and url not in urls:urls.append(url)
        except ValueError:continue
    # Catalogs already expose real merchant destinations. Do not make three
    # failing web queries when independent discovery has usable candidates.
    if not urls:
        urls=discover_web(base)
    else:
        base['_search']={'status':'completed','provider':'public_catalogs','candidates':len(urls),'attempts':[]}
        base['_brochures']=catalog['sources'][:4]
    base['_search']['catalogs']=catalog['diagnostics']
    base['_search']['officialApi']=api['state']
    if api.get('httpStatus'):base['_search']['officialHttpStatus']=api['httpStatus']
    # Keep merchant diversity across catalog sources and remove tracking duplicates.
    distinct=[];duplicates=[];hosts=set();paths=set()
    for url in urls:
        p=urlparse(url);key=(p.hostname,p.path)
        if key in paths:continue
        paths.add(key);host=p.hostname.removeprefix('www.')
        if host in hosts:duplicates.append(url)
        else:hosts.add(host);distinct.append(url)
    selected=(distinct+duplicates)[:12]
    base['_search']['candidates']=len(selected)
    return selected


def compare(base):
    urls=discover(base)
    def verify(url):
        try:
            page=fetch_page(url,budget=5)
            if page:
                result=verified_offer(page[0],page[1],base)
                if result:
                    candidate=structured_product(page[0],page[1])
                    return dict(result,source=urlparse(result['url']).hostname.removeprefix('www.'),title=candidate['title'])
                candidate=structured_product(page[0],page[1])
                if candidate and candidate.get('price') is not None and plausible_product(base,candidate):
                    return {'source':urlparse(page[1]).hostname.removeprefix('www.'),'url':page[1],'title':candidate['title'],'price':candidate['price'],'identityConfirmed':False}
        except Exception:pass
        return None
    # Check two batches with six concurrent reads. Listings and repeated merchants
    # no longer consume the entire first batch. Search text never becomes a price.
    with ThreadPoolExecutor(max_workers=6) as pool:out=list(pool.map(verify,urls[:12]))
    if not any(item and item.get('identityConfirmed') is not False for item in out) and not base.get('_catalogQuotes') and base.get('_search',{}).get('provider')=='public_catalogs':
        catalog_status=base['_search'];sources=base.get('_brochures',[])
        extra=[url for url in discover_web(base) if url not in urls][:6]
        web_status=base['_search'];base['_search']=dict(catalog_status,fallbackWebStatus=web_status['status'])
        base['_brochures']=(sources+base.get('_brochures',[]))[:4]
        with ThreadPoolExecutor(max_workers=6) as pool:out+=list(pool.map(verify,extra))
    base['_similar']=[x for x in out if x and x.get('identityConfirmed') is False]
    return [x for x in out if x and x.get('identityConfirmed') is not False]


def analyze_any_seller(target,hint=''):
    target=normalize_url(target);source=target
    input_read={}
    try:page=fetch_page(target,budget=7,diagnostics=input_read)
    except Exception as error:
        input_read['error']=type(error).__name__;page=None
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
            title=re.sub(r'\s+',' ',html.unescape(title or '')).strip()
            if title:base={'title':title[:250],'url':source,'price':None,'currency':None}
    if not base:
        title=str(hint or '').strip()[:250] or url_title(source)
        if not title:raise ProductInfoRequired('Bu linkten ürün adı okunamadı. Ürün adı veya barkod alanını doldurarak yeniden dene.')
        base={'title':title,'url':source,'price':None,'currency':None,'gtin':gtin_in_url(source) or gtin_in_url(hint)}
    if not structured:
        hint=str(hint or '').strip()[:250]
        barcode=gtin_in_url(hint) or gtin_in_url(source)
        if hint:base['title']=hint
        if barcode:base['gtin']=barcode
    base.setdefault('url',source)
    base['_inputStructured']=structured
    offers=[]
    if base.get('price') is not None:
        offers.append({'source':urlparse(source).hostname.removeprefix('www.'),'price':base['price'],'url':source,'title':base['title']})
    offers+=compare(base)
    offers=sorted({o['url']:o for o in offers}.values(),key=lambda o:o['price'])
    if offers and not structured:base['title']=offers[0]['title']
    best=offers[0]['price'] if offers else None
    input_price=base.get('price')
    result={'title':base['title'],'input_source':urlparse(source).hostname.removeprefix('www.'),'input_url':target,
            'input_price':input_price,'offers':offers,'price':best,'price_source':offers[0]['source'] if offers else None,
            'currency':'TRY' if offers else None,'savings':round(input_price-best,2) if input_price and best and input_price>best else 0,
            'identityVerified':bool(structured or offers),'searchMode':'open_web','similarOffers':base.get('_similar',[]),'catalogOffers':base.get('_catalogQuotes',[]),'brochureSources':base.get('_brochures',[]),'search':base.get('_search',{}),'inputRead':input_read}
    from brochure_store import find_brochures
    result['brochureOffers']=find_brochures(base)
    from watch_store import sign_snapshot
    result['watchReceipt']=sign_snapshot(target,best,base=base,offers=offers)
    return result
