from unittest.mock import Mock
import pytest
from product_links import product_link,ProductLinkError
from app import app

CAMPAIGN='https://www.hepsiburada.com/dv/elektronik-firsatlari?trackingId=21335034'

@pytest.mark.parametrize('url',[
 CAMPAIGN,
 'https://www.hepsiburada.com/laptop-c-98',
 'https://www.trendyol.com/sr?q=telefon',
 'https://www.amazon.com.tr/s?k=telefon',
 'https://www.n11.com/arama?q=telefon',
])
def test_listing_links_do_not_call_any_price_provider(monkeypatch,url):
    import app as module
    get=Mock(side_effect=AssertionError('A listing must not trigger a provider'))
    post=Mock(side_effect=AssertionError('A listing must not consume credits'))
    monkeypatch.setattr(module.requests,'get',get);monkeypatch.setattr(module.requests,'post',post)
    response=app.test_client().get('/api/product',query_string={'url':url})
    assert response.status_code==400
    assert response.json['errorCode']=='PRODUCT_LINK_REQUIRED'
    assert response.json['pageType'] in ('campaign','listing')
    get.assert_not_called();post.assert_not_called()


def test_exact_reported_campaign_has_specific_instruction():
    with pytest.raises(ProductLinkError) as error:product_link(CAMPAIGN)
    assert error.value.page_type=='campaign'
    assert 'Kampanyadaki bir ürünü açıp' in str(error.value)

@pytest.mark.parametrize('url',[
 'https://www.hepsiburada.com/sonoff-zbmini-l2-p-HBCV000TEST',
 'https://www.hepsiburada.com/sonoff-zbmini-l2-pm-HB000TEST',
 'https://www.trendyol.com/marka/urun-p-123456?merchantId=4',
 'https://www.amazon.com.tr/dp/B0ABCDE123',
 'https://www.amazon.com.tr/gp/product/B0ABCDE123/',
 'https://www.n11.com/urun/unit-ut12d-123456',
])
def test_supported_product_links_preserved(url):
    assert product_link(url)==url


def test_missing_scheme_and_fragment_normalized():
    assert product_link('www.hepsiburada.com/urun-p-HBCV000TEST#reviews')=='https://www.hepsiburada.com/urun-p-HBCV000TEST'

@pytest.mark.parametrize('url',['https://hepsiburada.com.evil.test/urun-p-HBCV000TEST','https://user:pass@www.hepsiburada.com/urun-p-HBCV000TEST','https://www.hepsiburada.com:8080/urun-p-HBCV000TEST'])
def test_fake_host_credentials_and_port_rejected(url):
    with pytest.raises(ProductLinkError):product_link(url)
