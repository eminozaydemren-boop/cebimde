"""Bounded public HTTP reads with DNS pinning and redirect validation."""
import ipaddress,re,socket,ssl,time
from urllib.parse import urlsplit,urlunsplit,urljoin
import certifi,urllib3

class PublicURLFailure(ValueError):pass


def normalize_url(value):
    raw=str(value or '').strip()
    if not raw or len(raw)>4096 or any(c.isspace() for c in raw):raise PublicURLFailure('Geçerli bir ürün bağlantısı gir.')
    if not re.match(r'^https?://',raw,re.I):raw='https://'+raw
    try:
        p=urlsplit(raw);host=(p.hostname or '').rstrip('.').encode('idna').decode().lower()
        if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,443 if p.scheme=='https' else 80):raise ValueError()
        if not host or '.' not in host or host.endswith(('.local','.localhost','.internal','.test','.invalid','.example')):raise ValueError()
        if host in ('cebimde.onrender.com','metadata.google.internal'):raise ValueError()
        try:ipaddress.ip_address(host)
        except ValueError:pass
        else:raise ValueError()
        if not re.fullmatch(r'[a-z0-9.-]+',host):raise ValueError()
    except (ValueError,UnicodeError):raise PublicURLFailure('Herkese açık bir mağazanın HTTP veya HTTPS ürün bağlantısını gir.')
    return urlunsplit((p.scheme,host,p.path or '/',p.query,''))


def public_addresses(host,port):
    addresses=list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise PublicURLFailure('Özel ağ adresleri okunamaz.')
    return sorted(addresses,key=lambda ip: ipaddress.ip_address(ip).version)


def fetch_page(value,budget=8,diagnostics=None):
    diagnostics=diagnostics if diagnostics is not None else {}
    url=normalize_url(value);deadline=time.monotonic()+budget
    for _ in range(4):
        p=urlsplit(url);port=443 if p.scheme=='https' else 80
        diagnostics['stage']='dns'
        ips=public_addresses(p.hostname,port)
        remaining=deadline-time.monotonic()
        if remaining<=0:return None
        # The socket uses this validated IP, not a second DNS lookup. TLS still checks the original host.
        if p.scheme=='https':
            pool=urllib3.HTTPSConnectionPool(ips[0],port=port,server_hostname=p.hostname,
                assert_hostname=p.hostname,ssl_context=ssl.create_default_context(cafile=certifi.where()))
        else:pool=urllib3.HTTPConnectionPool(ips[0],port=port)
        response=None
        try:
            diagnostics['stage']='connect'
            response=pool.urlopen('GET',urlunsplit(('','',p.path or '/',p.query,'')),
                headers={'Host':p.hostname,'User-Agent':'Mozilla/5.0 (compatible; CEBIMDE/3.83)','Accept':'text/html,application/xhtml+xml','Accept-Language':'tr-TR,tr;q=0.9'},
                assert_same_host=False,redirect=False,retries=False,preload_content=False,
                timeout=urllib3.Timeout(connect=min(3,remaining),read=min(3,remaining),total=remaining))
            diagnostics.update(stage='response',status=response.status)
            if response.status in (301,302,303,307,308):
                location=response.headers.get('Location')
                if not location:return None
                url=normalize_url(urljoin(url,location));continue
            if response.status!=200:return None
            content_type=response.headers.get('Content-Type','')
            if not any(kind in content_type.lower() for kind in ('text/html','application/xhtml+xml')):return None
            diagnostics['stage']='body'
            data=bytearray();head_checked=False
            for chunk in response.stream(16384,decode_content=True):
                data.extend(chunk)
                diagnostics['bytes']=len(data)
                if len(data)>4*1024*1024 or time.monotonic()>=deadline:return None
                # Large storefront menus need not download after the main head offer is complete.
                head_end=data.lower().find(b'</head>') if not head_checked else -1
                if head_end>=0:
                    head_checked=True
                    if b'application/ld+json' in data[:head_end].lower():
                        from product_data import structured_product
                        head=bytes(data[:head_end+7]).decode('utf-8',errors='replace')
                        product=structured_product(head,url)
                        if product and product.get('price') is not None:
                            diagnostics['stage']='product_head';return head,url
            charset=re.search(r'charset=([\w-]+)',content_type,re.I)
            try:body=data.decode(charset.group(1) if charset else 'utf-8',errors='replace')
            except LookupError:body=data.decode('utf-8',errors='replace')
            diagnostics['stage']='complete'
            return body,url
        finally:
            if response is not None:response.close()
            pool.close()
    return None
