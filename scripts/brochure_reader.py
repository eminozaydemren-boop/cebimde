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
        cmd=['tesseract',str(f),'stdout','--psm',str(psm),'-l',os.getenv('BROCHURE_OCR_LANGUAGE','eng')]
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
        if .045*w<bw<.2*w and .015*h<bh<.065*h and 1.35<bw/bh<4 and len(xs)/(bw*bh)>.55:
            boxes.append((x0*3,y0*3,x1*3,y1*3))
    return sorted(boxes,key=lambda b:(b[1],b[0]))

def number(text):
    # Require cents. Large numbers printed on packs and discounts cannot become prices.
    s=re.sub(r'\s+','',text)
    if not re.fullmatch(r'\d{1,6}[,.]\d{2}',s):return None
    value=float(s.replace(',','.'))
    return value if 0<value<100000 else None

def price_from_label(image,box):
    from PIL import ImageOps
    im=image.crop(box).getchannel('G')
    im=im.crop((4,4,im.width-3,int(im.height*.77)))
    mask=im.point(lambda x:0 if x>165 else 255)
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
            if len(xx)>=3:parts.append((min(xx),min(yy),max(xx)+1,max(yy)+1))
    if not parts:return None
    height=max(p[3]-p[1] for p in parts)
    big=[p for p in parts if p[3]-p[1]>=height*.7]
    if not big:return None
    right=max(p[2] for p in big)
    cents=[p for p in parts if p[0]>=right and height*.3<=p[3]-p[1]<=height*.65 and p[1]<height*.3]
    if not cents:return None
    left=min(p[0] for p in cents)
    punctuation=[p for p in parts if right<=p[0]<left and p[1]>height*.4 and p[3]-p[1]<height*.4]
    if not punctuation:return None
    def digits(bounds,cents=False):
        crop=mask.crop(bounds);crop=ImageOps.expand(crop.resize((crop.width*6,crop.height*6)),border=18,fill=255)
        a=ocr(crop,6,'0123456789').strip()
        second=crop.resize((int(crop.width*1.3),int(crop.height*1.3))) if cents else crop
        b=ocr(second,6 if cents else 7,'0123456789').strip()
        return a if a==b and a.isdigit() else None
    whole=digits((min(p[0] for p in big),0,right,h))
    decimal=digits((left,min(p[1] for p in cents),max(p[2] for p in cents),max(p[3] for p in cents)),True)
    if not whole or len(whole)>6 or not decimal or len(decimal)!=2:return None
    return number(whole+','+decimal)

def read_image(raw):
    from PIL import Image
    im=Image.open(io.BytesIO(raw));im.load()
    if im.width*im.height>16_000_000:raise ValueError('Image too large')
    return im.convert('RGB')

def extract_cards(image):
    labels=red_labels(image)
    # Read text once for each page, keeping bounding boxes for isolated product cards.
    words=[]  # OCR is confined to each isolated caption, not unrelated page text.
    out=[]
    for box in labels:
        x,y,right,bottom=box;bw=right-x;bh=bottom-y
        same_row=[b[0] for b in labels if abs(b[1]-y)<bh*.6 and b[0]>right]
        x_end=min(same_row) if same_row else min(image.width,x+bw*2.3)
        if x_end-x>image.width*.42:continue
        below=[b[1] for b in labels if abs(b[0]-x)<bw*.4 and b[1]>bottom]
        y_end=min(below) if below else min(image.height,y+image.height*.24)
        if y_end-y>image.height*.42:continue
        def text_in(bounds):
            a,b,c,d=bounds
            return ' '.join(w['text'] for w in words if w.get('text','').strip() and float(w['conf'])>=20
                and a<=int(w['left'])+int(w['width'])/2<c and b<=int(w['top'])+int(w['height'])/2<d)
        title_box=(right+1,y-3,min(x_end-10,image.width),min(y_end,y+bh*1.5))
        if title_box[2]<=title_box[0]:continue
        from PIL import ImageOps
        crop=image.crop(title_box).convert('L');crop=ImageOps.expand(crop.resize((crop.width*4,crop.height*4)),border=30,fill=255)
        title=' '.join(ocr(crop,6).split())
        if len(title)<8:continue
        price=price_from_label(image,box)
        if price is None:continue
        text=title+' '+text_in((x,y,x_end,y_end))
        out.append(dict(title=title[:250],text=text[:1500],price=price,
                        region=[round(x/image.width,5),round(y/image.height,5),round(x_end/image.width,5),round(y_end/image.height,5)]))
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

if __name__=='__main__':
    import sys
    urls=sys.argv[1:] or discover_catalogs('https://katalog24.com.tr/anpa-gross')
    rows=[]
    for url in urls[:4]:rows+=scan_catalog(url)
    print(json.dumps({'cards':rows},ensure_ascii=False))
