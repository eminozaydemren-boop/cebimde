"""Reject listings before invoking a product-price provider."""
import re
from urllib.parse import urlsplit,urlunsplit

class ProductLinkError(ValueError):
    def __init__(self,message,page_type='invalid'):
        super().__init__(message)
        self.page_type=page_type

PATTERNS={
 'hepsiburada.com':r'-(?:p|pm)-([A-Za-z0-9_-]+)(?:/|$)',
 'trendyol.com':r'-p-(\d+)(?:/|$)',
 'amazon.com.tr':r'/(?:dp|gp/product)/([A-Za-z0-9]{10})(?:/|$)',
 'n11.com':r'/urun/[^/]+-(?:P)?(\d+)(?:/|$)',
}

def product_link(raw):
    raw=str(raw or '').strip()
    if not raw or any(c.isspace() for c in raw):
        raise ProductLinkError('Tek bir ürünün tam bağlantısını gir.')
    if not re.match(r'^https?://',raw,re.I):raw='https://'+raw
    try:
        u=urlsplit(raw)
        host=(u.hostname or '').lower()
        if u.scheme not in ('http','https') or u.username or u.password or u.port not in (None,443):raise ValueError()
    except ValueError:
        raise ProductLinkError('Geçerli bir HTTPS ürün bağlantısı gir.')
    domain=host.removeprefix('www.')
    if domain not in PATTERNS:
        raise ProductLinkError('Bu mağaza henüz desteklenmiyor. Amazon Türkiye, Trendyol, Hepsiburada veya n11 ürün linkini gir.','unsupported')
    if domain=='hepsiburada.com' and u.path.lower().startswith('/dv/'):
        raise ProductLinkError('Bu bir kampanya sayfası. Kampanyadaki bir ürünü açıp o ürünün bağlantısını yapıştır.','campaign')
    if not re.search(PATTERNS[domain],u.path,re.I):
        raise ProductLinkError('Bu bağlantı tek bir ürün sayfası değil. Listeden bir ürünü açıp ürünün bağlantısını yapıştır.','listing')
    return urlunsplit(('https',host,u.path,u.query,''))
