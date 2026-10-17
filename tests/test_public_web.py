import socket,ssl
from unittest.mock import Mock
import pytest
import public_web as web

def test_new_public_merchants_do_not_require_a_shop_registry():
    assert web.normalize_url('www.another-retailer.com/product/widget-123')=='https://www.another-retailer.com/product/widget-123'
    assert web.normalize_url('http://retailer.com/widget')=='http://retailer.com/widget'

@pytest.mark.parametrize('url',['http://127.0.0.1/x','https://[::1]/x','http://169.254.169.254/latest','https://localhost/x','file:///etc/passwd','https://name:secret@retailer.com/x','https://retailer.com:8080/x'])
def test_nonpublic_and_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):web.normalize_url(url)


def test_hostname_resolving_to_private_ip_is_blocked(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))])
    with pytest.raises(ValueError):web.public_addresses('retailer.com',443)


def test_dns_is_pinned_and_tls_keeps_original_hostname(monkeypatch):
    dns=Mock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    monkeypatch.setattr(socket,'getaddrinfo',dns)
    response=Mock(status=200,headers={'Content-Type':'text/html; charset=utf-8'},stream=lambda *a,**kw:iter([b'<html>Product</html>']))
    pool=Mock(urlopen=lambda *a,**kw:response)
    factory=Mock(return_value=pool);monkeypatch.setattr(web.urllib3,'HTTPSConnectionPool',factory)
    result=web.fetch_page('https://retailer.com/widget')
    assert result[0]=='<html>Product</html>' and dns.call_count==1
    assert factory.call_args.args[0]=='93.184.216.34'
    options=factory.call_args.kwargs
    assert options['server_hostname']=='retailer.com' and options['assert_hostname']=='retailer.com'
    assert options['ssl_context'].verify_mode==ssl.CERT_REQUIRED


def test_redirect_into_private_network_is_blocked(monkeypatch):
    monkeypatch.setattr(web,'public_addresses',lambda *a:['93.184.216.34'])
    response=Mock(status=302,headers={'Location':'http://127.0.0.1/internal'})
    monkeypatch.setattr(web.urllib3,'HTTPSConnectionPool',lambda *a,**kw:Mock(urlopen=lambda *a,**kw:response))
    with pytest.raises(ValueError):web.fetch_page('https://retailer.com/product')


def test_large_storefront_stops_after_complete_main_product_head(monkeypatch):
    import json
    monkeypatch.setattr(web,'public_addresses',lambda *a:['93.184.216.34'])
    product={'@type':'Product','name':'Familia Natural Tuvalet Kağıdı 40\'lı','offers':{'@type':'Offer','price':599.95,'priceCurrency':'TRY','availability':'https://schema.org/InStock'}}
    head=('<head><script type="application/ld+json">'+json.dumps(product)+'</script></head>').encode()
    def chunks(*a,**kw):
        yield head
        raise AssertionError('Navigation menus must not be downloaded after the complete main offer')
    response=Mock(status=200,headers={'Content-Type':'text/html; charset=utf-8'},stream=chunks)
    monkeypatch.setattr(web.urllib3,'HTTPSConnectionPool',lambda *a,**kw:Mock(urlopen=lambda *a,**kw:response))
    result=web.fetch_page('https://retailer.com/familia-natural-40-li')
    assert '599.95' in result[0];response.close.assert_called_once()
