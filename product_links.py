"""Reject listings before invoking a product-price provider."""
import re
from urllib.parse import urlsplit,urlunsplit

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
