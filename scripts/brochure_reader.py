"""Free brochure OCR worker. Runs on GitHub's standard public Ubuntu runner.
Only reads public Katalog24 catalog metadata and the image URLs present in it.
No price, product name, page number, or branch is supplied by configuration.
"""
import csv,io,json,os,re,subprocess,tempfile,hashlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse,urljoin,parse_qs
import requests

os.environ['OMP_THREAD_LIMIT']='1'

class CatalogHTML(HTMLParser):
    def __init__(self):
        super().__init__();self.images=[];self.links=[];self.scripts=[];self.in_json=False;self.chunk=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='img' and 'brochure-page-image' in a.get('class',''):self.images.append(a.get('data-src',''))
        if tag=='a' and a.get('href'):self.links.append(a['href'])
        if tag=='script' and a.get('type')=='application/ld+json':self.in_json=True;self.chunk=[]
    def handle_data(self,s):
        if self.in_json:self.chunk.append(s)
    def handle_endtag(self,tag):
        if tag=='script' and self.in_json:
            try:self.scripts.append(json.loads(''.join(self.chunk)))
            except ValueError:pass
            self.in_json=False

def read(url,image=False):
    # Restrict the crawler to this supported public catalog provider and its CDN.
    host=urlparse(url).hostname
    allowed=('priserocdn.com','www.priserocdn.com') if image else ('katalog24.com.tr','www.katalog24.com.tr')
    if urlparse(url).scheme!='https' or host not in allowed:raise ValueError('Unsupported brochure source')
    with requests.get(url,timeout=(5,15),stream=True,allow_redirects=False) as r:
        r.raise_for_status()
        if r.status_code!=200:raise ValueError('Unexpected redirect')
        chunks=[];length=0
        for chunk in r.iter_content(65536):
            length+=len(chunk)
            if length>(8_000_000 if image else 2_000_000):raise ValueError('Brochure too large')
            chunks.append(chunk)
        raw=b''.join(chunks)
        return raw if image else raw.decode('utf-8','replace')

def parse(page):
    p=CatalogHTML();p.feed(page);return p

def metadata(parser,url,today=None):
    today=today or date.today()
    for d in parser.scripts:
        if isinstance(d,dict) and d.get('@type')=='SaleEvent':
            start=str(d.get('startDate',''))[:10];end=str(d.get('endDate',''))[:10]
            try:
                if not date.fromisoformat(start)<=today<=date.fromisoformat(end):return None
            except ValueError:return None
            name=str(d.get('name',''))[:250];org=d.get('organizer',{})
            return dict(sourceUrl=url,startDate=start,endDate=end,campaign=name,
                        merchant=str(org.get('name') or '')[:100],
                        # Preserve the source's scope verbatim. Never infer nationwide coverage.
                        scope=name,scopeConfirmed=False)
    return None

def ocr(image,psm=11,whitelist=None,tsv=False):
    with tempfile.TemporaryDirectory() as td:
        f=Path(td)/'image.png';image.save(f)
        cmd=['tesseract',str(f),'stdout','--psm',str(psm),'-l','eng' if whitelist else os.getenv('BROCHURE_OCR_LANGUAGE','eng')]
        if whitelist:cmd+=['-c','tessedit_char_whitelist='+whitelist]
        if tsv:cmd+=['tsv']
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=25,check=True)
        return r.stdout

def red_labels(image):
    """Locate red price rectangles, rejecting header banners and product pictures."""
    small=image.resize((image.width//3,image.height//3)).convert('RGB');w,h=small.size
    mask=bytearray(1 if r>140 and r>g*1.6 and r>b*1.5 else 0 for r,g,b in small.getdata())
    boxes=[]
    for i in range(len(mask)):
        if not mask[i]:continue
        mask[i]=0;q=deque([i]);xs=[];ys=[]
        while q:
            j=q.popleft();x=j%w;y=j//w;xs.append(x);ys.append(y)
            for k in (j-1 if x else -1,j+1 if x<w-1 else -1,j-w,j+w):
                if 0<=k<len(mask) and mask[k]:mask[k]=0;q.append(k)
        x0,x1=min(xs),max(xs)+1;y0,y1=min(ys),max(ys)+1;bw=x1-x0;bh=y1-y0
        if .045*w<bw<.45*w and .015*h<bh<.18*h and 1.35<bw/bh<4:
            fill=len(xs)/(bw*bh)
            pixels=list(small.crop((x0,y0,x1,y1)).getdata())
            yellow=sum(r>150 and g>120 and b<110 for r,g,b in pixels)/len(pixels)
            if fill>.55 or (fill>.08 and yellow>.4):boxes.append((x0*3,y0*3,x1*3,y1*3))
    return sorted(boxes,key=lambda b:(b[1],b[0]))

def number(text):
    # Require cents. Large numbers printed on packs and discounts cannot become prices.
    s=re.sub(r'\s+','',text)
    if not re.fullmatch(r'\d{1,6}[,.]\d{2}',s):return None
    value=float(s.replace(',','.'))
    return value if 0<value<100000 else None

def price_from_label(image,box):
    from PIL import ImageOps
    rgb=image.crop(box).convert('RGB')
    yellow=sum(r>150 and g>120 and b<110 for r,g,b in rgb.getdata())/(rgb.width*rgb.height)>.3
    im=rgb.convert('L') if yellow else rgb.getchannel('G')
    im=im.crop((3,3,im.width-3,im.height-3))
    mask=im.point(lambda x:0 if (x<105 if yellow else x>165) else 255)
    # Raised cents have another baseline: OCR them separately rather than dropping
    # cents or interpreting 59,90 as 9,90. The ink geometry determines the split.
    w,h=mask.size;pixels=mask.load();seen=set();parts=[]
    for y in range(h):
        for x in range(w):
            if pixels[x,y] or (x,y) in seen:continue
            q=deque([(x,y)]);seen.add((x,y));xx=[];yy=[]
            while q:
                a,b=q.popleft();xx.append(a);yy.append(b)
                for c,d in ((a-1,b),(a+1,b),(a,b-1),(a,b+1)):
                    if 0<=c<w and 0<=d<h and not pixels[c,d] and (c,d) not in seen:seen.add((c,d));q.append((c,d))
            if len(xx)>=3:
                bounds=(min(xx),min(yy),max(xx)+1,max(yy)+1)
                if bounds[2]-bounds[0]>.9*w and bounds[3]-bounds[1]>.8*h:
                    for a,b in zip(xx,yy):pixels[a,b]=255
                else:parts.append(bounds)
    if not parts:return None
    height=max(p[3]-p[1] for p in parts)
    big=[p for p in parts if p[3]-p[1]>=height*.7]
    if not big:return None
    right=max(p[2] for p in big)
    cents=[p for p in parts if p[0]>=right and height*.3<=p[3]-p[1]<=height*.65 and p[1]<=min(b[1] for b in big)+height*.3]
    if not cents:
        plain=ImageOps.expand(mask.resize((mask.width*4,mask.height*4)),border=20,fill=255)
        a=number(ocr(plain,6,'0123456789,.'));b=number(ocr(plain,7,'0123456789,.'))
        return a if a is not None and a==b else None
    left=min(p[0] for p in cents)
    punctuation=[p for p in parts if right<=p[0]<left and p[1]>height*.4 and p[3]-p[1]<height*.4]
    if not punctuation:return None
    def digits(bounds,cents=False,single=False):
        crop=mask.crop(bounds);scale=160/max(1,crop.height);crop=ImageOps.expand(crop.resize((max(1,int(crop.width*scale)),160)),border=24,fill=255)
        a=ocr(crop,10 if single else (6 if cents else 8),'0123456789').strip()
        second=crop.resize((int(crop.width*1.3),int(crop.height*1.3))) if cents else crop
        b=ocr(second,13 if single else (6 if cents else 13),'0123456789').strip()
        return a if a==b and a.isdigit() else None
    whole=digits((min(p[0] for p in big),min(p[1] for p in big),right,max(p[3] for p in big)))
    decimal=digits((left,min(p[1] for p in cents),max(p[2] for p in cents),max(p[3] for p in cents)),True)
    if not decimal and len(cents)==2:
        chars=[digits(bounds,True,True) for bounds in sorted(cents)]
        if all(c and len(c)==1 for c in chars):decimal=''.join(chars)
    if not whole or len(whole)>6 or not decimal or len(decimal)!=2:return None
    return number(whole+','+decimal)

def read_image(raw):
    from PIL import Image
    im=Image.open(io.BytesIO(raw))
    if im.width*im.height>16_000_000:raise ValueError('Image too large')
    im.load()
    return im.convert('RGB')

def extract_cards(image):
    from PIL import ImageOps
    labels=red_labels(image);out=[]
    for box in labels:
        x,y,right,bottom=box;bw=right-x;bh=bottom-y
        same_row=[b[0] for b in labels if abs(b[1]-y)<bh*.6 and b[0]>right]
        x_end=min(same_row) if same_row else min(image.width,x+bw*2.3)
        below=[b[1] for b in labels if abs(b[0]-x)<bw*.4 and b[1]>bottom]
        y_end=min(below) if below else min(image.height,y+image.height*.24)
        price=price_from_label(image,box)
        if price is None:continue
        rgb=image.crop(box).convert('RGB')
        yellow=sum(r>150 and g>120 and b<110 for r,g,b in rgb.getdata())/(rgb.width*rgb.height)>.3
        side=(right+1,max(0,y-3),min(x_end-10,image.width),min(y_end,y+bh*1.5))
        above=(max(0,x-bw*.25),max(0,y-image.height*.09),min(image.width,right+bw*.3),y-3)
        left=(max(0,x-image.width*.32),max(0,y-image.height*.12),x-4,min(image.height,y+bh*.55))
        regions=[above,side] if yellow else ([left,above,side] if bw>image.width*.22 else [side,above])
        title=None;caption=None
        for bounds in regions:
            if bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:continue
            crop=image.crop(tuple(int(v) for v in bounds)).convert('L')
            crop=ImageOps.expand(crop.resize((crop.width*3,crop.height*3)),border=30,fill=255)
            candidate=' '.join(ocr(crop,6).split())
            if len(re.findall(r'[^\W\d_]{3,}',candidate))>=2:
                title=candidate[:250];caption=bounds;break
        if not title:continue
        region=(min(x,caption[0]),min(y,caption[1]),max(right,caption[2]),max(bottom,caption[3]))
        out.append(dict(title=title,text=title,price=price,
                        region=[round(region[0]/image.width,5),round(region[1]/image.height,5),round(region[2]/image.width,5),round(region[3]/image.height,5)]))
    return out

def scan_catalog(url,max_pages=32):
    parser=parse(read(url));meta=metadata(parser,url)
    if not meta:return []
    last=max([int(parse_qs(urlparse(u).query).get('page',['1'])[0]) for u in parser.links if urlparse(u).path==urlparse(url).path]+[1])
    if last>max_pages:return []
    urls=[url]+[url+('?page='+str(n)) for n in range(2,last+1)]
    def scan(page_url):
        try:
            p=parser if page_url==url else parse(read(page_url));rows=[]
            for image_url in p.images[:1]:
                raw=read(image_url,True);im=read_image(raw)
                cards=extract_cards(im)
                for card in cards:
                    card.update(meta,imageUrl=image_url,sourceUrl=page_url,imageSha256=hashlib.sha256(raw).hexdigest(),identityConfirmed=False)
                    rows.append(card)
            return rows
        except (requests.RequestException,ValueError,OSError,subprocess.SubprocessError):return []
    with ThreadPoolExecutor(max_workers=2) as pool:return [row for rows in pool.map(scan,urls) for row in rows]

def discover_catalogs(index_url):
    p=parse(read(index_url));urls=[]
    for url in p.links:
        url=urljoin(index_url,url)
        if urlparse(url).hostname=='katalog24.com.tr' and re.search(r'/(?:katalog-[^/]+|brosur/\d+)$',urlparse(url).path) and url not in urls:urls.append(url)
    return urls[:4]

class DirectoryHTML(CatalogHTML):
    def __init__(self):
        super().__init__();self.merchants=[];self.catalogs=[];self.indexes=[];self.active=None
    def handle_starttag(self,tag,attrs):
        super().handle_starttag(tag,attrs);a=dict(attrs)
        if tag=='div' and 'brochure-list-ite' in a.get('class',''):
            self.active={k:a.get(k,'') for k in ('af','at','t','fi')}
        if tag=='a':
            if 'shop-list-link' in a.get('class',''):
                self.merchants.append({'url':a.get('href',''),'name':a.get('title','').removesuffix(' kataloglar ve teklifler')})
            if 'btn-block' in a.get('class','') and a.get('title'):self.indexes.append(a.get('href',''))
            if 'brochure-list-link' in a.get('class','') and self.active:
                self.catalogs.append(dict(self.active,url=a.get('href',''),title=a.get('title','')));self.active=None

def parse_directory(body):
    p=DirectoryHTML();p.feed(body);return p

def provider_url(url):
    p=urlparse(url)
    return p.scheme=='https' and p.hostname=='katalog24.com.tr' and not p.username and not p.password and not p.port

def discover_directory():
    """Discover every merchant listed by the provider; no merchant whitelist."""
    p=parse_directory(read('https://katalog24.com.tr/'))
    return [m for m in p.merchants if provider_url(m['url']) and re.fullmatch(r'/magaza/[\w-]+',urlparse(m['url']).path)][:500]

def merchant_catalogs(merchant):
    from datetime import datetime,timezone
    from zoneinfo import ZoneInfo
    p=parse_directory(read(merchant['url']))
    indexes=[u for u in p.indexes if provider_url(u) and re.fullmatch(r'/[\w-]+',urlparse(u).path)]
    if not indexes:return []
    index=indexes[-1];p=parse_directory(read(index));today=datetime.now(ZoneInfo('Europe/Istanbul')).date();out=[]
    main=metadata(p,index,today)
    if main:
        event=next((d for d in p.scripts if isinstance(d,dict) and d.get('@type')=='SaleEvent'),{})
        canonical=event.get('url')
        out.append(dict(url=canonical if isinstance(canonical,str) and provider_url(canonical) else index,
                        merchantUrl=merchant['url'],merchant=merchant['name'],startDate=main['startDate'],endDate=main['endDate']))
    for item in p.catalogs:
        try:
            start=datetime.fromtimestamp(int(item['af']),timezone.utc).astimezone(ZoneInfo('Europe/Istanbul')).date()
            end=datetime.fromtimestamp(int(item['at']),timezone.utc).astimezone(ZoneInfo('Europe/Istanbul')).date()
            if start<=today<=end and 0<=(end-start).days<=60 and provider_url(item['url']):
                out.append(dict(url=item['url'],merchantUrl=merchant['url'],merchant=merchant['name'],startDate=start.isoformat(),endDate=end.isoformat()))
        except (ValueError,OverflowError):continue
    return list({c['url']:c for c in out if (date.fromisoformat(c['endDate'])-date.fromisoformat(c['startDate'])).days<=60}.values())[:100]

def scan_batch(url,start_page=1,page_count=3):
    """Resume a large catalog in bounded batches instead of skipping it entirely."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    p=parse(read(url));meta=metadata(p,url,datetime.now(ZoneInfo('Europe/Istanbul')).date())
    if not meta:return dict(cards=[],nextPage=1,complete=True,state='expired',pagesRead=0)
    last=max([int(parse_qs(urlparse(u).query).get('page',['1'])[0]) for u in p.links if urlparse(u).path==urlparse(url).path]+[1])
    if last>1000:raise ValueError('Excessive catalog length')
    start_page=max(1,min(start_page,last));end=min(last,start_page+page_count-1)
    def scan(n):
        page_url=url if n==1 else url+'?page='+str(n)
        page=p if n==1 else parse(read(page_url))
        if not page.images:return [],False
        rows=[]
        for image_url in page.images[:1]:
            raw=read(image_url,True);im=read_image(raw)
            for card in extract_cards(im):
                card.update(meta,imageUrl=image_url,sourceUrl=page_url,imageSha256=hashlib.sha256(raw).hexdigest(),identityConfirmed=False);rows.append(card)
        return rows,True
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(scan,range(start_page,end+1)))
    cards=[c for rows,ok in results for c in rows];read_count=sum(ok for rows,ok in results)
    return dict(cards=cards,nextPage=1 if end==last else end+1,complete=end==last,state='read' if cards else 'no_prices',pagesRead=read_count,pagesTotal=last)
