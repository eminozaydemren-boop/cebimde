"""Reject listings before invoking a product-price provider."""
import re
from urllib.parse import urlsplit,urlunsplit,parse_qsl

class ProductLinkError(ValueError):
    def __init__(self,message,page_type='invalid'):
        super().__init__(message)
        self.page_type=page_type

PATTERNS={
 'pazarama.com':r'-p-([A-Za-z0-9_-]+)(?:/|$)',
 'hepsiburada.com':r'-(?:p|pm)-([A-Za-z0-9_-]+)(?:/|$)',
 'trendyol.com':r'-p-(\d+)(?:/|$)',
 'amazon.com.tr':r'/(?:dp|gp/product)/([A-Za-z0-9]{10})(?:/|$)',
 'n11.com':r'/urun/[^/]+-(?:P)?(\d+)(?:/|$)',
}

def same_product_page(left,right):
    """Bind schema URLs to this page, allowing renamed slugs with the same store ID."""
    try:
        a=urlsplit(left);b=urlsplit(right)
        if a.scheme not in ('http','https') or b.scheme not in ('http','https'):return False
        if a.username or a.password or b.username or b.password:return False
        host=(a.hostname or '').removeprefix('www.').casefold()
        if not host or host!=(b.hostname or '').removeprefix('www.').casefold():return False
        if a.port not in (None,443 if a.scheme=='https' else 80) or b.port not in (None,443 if b.scheme=='https' else 80):return False
        def variants(query):
            return sorted((k,v) for k,v in parse_qsl(query,keep_blank_values=True)
                          if not k.casefold().startswith('utm_') and k.casefold() not in ('gclid','fbclid'))
        if variants(a.query)!=variants(b.query):return False
        if a.path.rstrip('/').casefold()==b.path.rstrip('/').casefold():return True
        pattern=PATTERNS.get(host)
        if not pattern:return False
        x=re.search(pattern,a.path,re.I);y=re.search(pattern,b.path,re.I)
        return bool(x and y and x.group(1).casefold()==y.group(1).casefold())
    except (ValueError,TypeError):return False

def product_link(raw):
    from public_web import normalize_url
    try:url=normalize_url(raw)
    except ValueError as e:raise ProductLinkError(str(e))
    u=urlsplit(url);host=u.hostname;domain=host.removeprefix('www.')
    if domain=='hepsiburada.com' and u.path.lower().startswith('/dv/'):
        raise ProductLinkError('Bu bir kampanya sayfası. Kampanyadaki bir ürünü açıp o ürünün bağlantısını yapıştır.','campaign')
    if domain in PATTERNS and not re.search(PATTERNS[domain],u.path,re.I):
        raise ProductLinkError('Bu bağlantı tek bir ürün sayfası değil. Listeden bir ürünü açıp ürünün bağlantısını yapıştır.','listing')
    return url
