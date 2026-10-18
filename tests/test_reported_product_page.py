"""Regression: a real retailer uses WebPage.mainEntity and separate review Products."""
import json
import pytest
from unittest.mock import Mock
import generic_analysis as generic
from product_data import structured_product
from product_links import same_product_page

SOURCE='https://www.hepsiburada.com/flodex-tuvalet-kagidi-12-li-pm-HB00000YKN6S'
CANONICAL='https://www.hepsiburada.com/flodex-12-rulo-2-katli-tuvalet-kagidi-cilt-dostu-ve-yuksek-emicilik-ozelligi-pm-HB00000YKN6S'
TITLE='Flodex 12 Rulo 2 Katlı Tuvalet Kağıdı Cilt Dostu ve Yüksek Emicilik'

def source_page(offer_url=CANONICAL,currency='TRY',available='InStock'):
    main={'@type':'Product','name':TITLE,'sku':'HBV00000YKN6T','gtin':'8682560440186',
          'brand':{'name':'Flodex'},'offers':{'@type':'Offer','url':offer_url,'price':'190.00',
          'priceCurrency':currency,'availability':'https://schema.org/'+available}}
    review={'@type':'Product','name':TITLE+' Özelliği','sku':main['sku'],'brand':main['brand']}
    return ('<script type="application/ld+json">'+json.dumps({'@type':'WebPage','mainEntity':main})+'</script>'
            +'<script type="application/ld+json">'+json.dumps([review,review])+'</script>'
            +'<h1><a>Flodex</a> 12 Rulo 2 Katlı Tuvalet Kağıdı</h1>'
            +'<h1>12 Rulo 2 Katlı Tuvalet Kağıdı Değerlendirmeleri</h1><h1>Tüm Değerlendirmeler (422)</h1>')

def test_reported_page_price_and_identity_are_read_without_name_hint():
    p=structured_product(source_page(),SOURCE)
    assert p['title']==TITLE and p['price']==190 and p['gtin']=='8682560440186'

def test_reported_full_analysis_without_hint_keeps_real_source_price(monkeypatch):
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:(source_page(),SOURCE))
    compare=Mock(return_value=[]);monkeypatch.setattr(generic,'compare',compare)
    result=generic.analyze_any_seller(SOURCE)
    assert result['identityVerified'] and result['input_price']==190 and result['price']==190
    assert result['offers'][0]['url']==SOURCE and result['savings']==0
    assert result['title']==TITLE and 'Değerlendirm' not in compare.call_args.args[0]['title']

def test_heading_fallback_does_not_join_review_or_script_headings(monkeypatch):
    body='<h1><a>Brand</a> <span>Widget 12 Rulo</span></h1><h1>Widget Değerlendirmeleri</h1><h1>Tüm Değerlendirmeler (422)</h1><script>"<h1>Unrelated</h1>"</script>'
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:(body,SOURCE))
    compare=Mock(return_value=[]);monkeypatch.setattr(generic,'compare',compare)
    result=generic.analyze_any_seller(SOURCE)
    assert result['title']=='Brand Widget 12 Rulo' and result['price'] is None
    assert compare.call_args.args[0]['title']=='Brand Widget 12 Rulo'

@pytest.mark.parametrize('offer_url',[CANONICAL.replace('YKN6S','DIFFERENT'),
    CANONICAL.replace('www.hepsiburada.com','www.another-shop.com'),CANONICAL+'?variant=other'])
def test_unrelated_offer_is_never_used_as_this_product_price(offer_url):
    assert structured_product(source_page(offer_url),SOURCE) is None

@pytest.mark.parametrize('overrides',[{'currency':'USD'},{'available':'OutOfStock'}])
def test_binding_does_not_bypass_currency_or_stock_validation(overrides):
    assert structured_product(source_page(**overrides),SOURCE)['price'] is None

def test_explicit_other_product_url_cannot_be_overridden_by_offer_url():
    main={'@type':'Product','name':TITLE,'url':SOURCE.replace('YKN6S','OTHER'),
          'offers':{'@type':'Offer','url':SOURCE,'price':1,'priceCurrency':'TRY'}}
    body='<script type="application/ld+json">'+json.dumps(main)+'</script>'
    assert structured_product(body,SOURCE) is None

def test_multiple_bound_conflicting_product_identities_are_rejected():
    data=[{'@type':'Product','name':'Widget '+sku,'sku':sku,'offers':{'url':SOURCE,'price':1,'priceCurrency':'TRY'}} for sku in ['A','B']]
    body='<script type="application/ld+json">'+json.dumps(data)+'</script>'
    assert structured_product(body,SOURCE) is None

@pytest.mark.parametrize('left,right',[
    (SOURCE,CANONICAL),(SOURCE+'?utm_source=share',CANONICAL),
    ('https://www.trendyol.com/brand/old-name-p-123','https://www.trendyol.com/brand/new-name-p-123'),
    ('https://www.amazon.com.tr/dp/B0ABCDE123','https://www.amazon.com.tr/gp/product/B0ABCDE123/'),
])
def test_stable_store_ids_allow_canonical_slug_changes(left,right):
    assert same_product_page(left,right)

@pytest.mark.parametrize('left,right',[
    (SOURCE,SOURCE.replace('YKN6S','YKN7S')),(SOURCE,SOURCE+'?variant=other'),
    ('https://one-shop.com/widget','https://other-shop.com/widget'),
    ('https://one-shop.com/old-name','https://one-shop.com/new-name'),
    (SOURCE,SOURCE.replace('https://','https://user:pass@')),
])
def test_stable_binding_rejects_changed_identity_host_or_variant(left,right):
    assert not same_product_page(left,right)
