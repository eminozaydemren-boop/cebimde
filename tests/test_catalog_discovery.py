import json
from urllib.parse import quote
from unittest.mock import Mock
import pytest
import catalog_discovery as catalog
import generic_analysis as generic

SOURCE='https://www.cimri.com/widget/en-ucuz-example-widget-100ml-fiyatlari,123'
INPUT='https://new-seller.com/example-widget-100ml'
EP='https://www.epey.com/temizlik/example-widget-100ml.html'
BASE={'title':'Example Widget Fresh 100 ml','url':INPUT}

def schema(product):return '<script type="application/ld+json">'+json.dumps(product)+'</script>'
def product(offers):return {'@type':'Product','name':BASE['title'],'url':SOURCE,'brand':{'name':'Example'},'offers':{'@type':'AggregateOffer','offers':offers}}
def card(title='Example Widget Fresh 100 ml',url='https://independent-shop.com/widget-100ml',price='129,90'):
    return '<a class="git" data-link="'+quote(url,safe='')+'"><span class="urun_adi">'+title+'<p>Satıcı</p></span><span class="urun_fiyat">'+price+' TL<p>Kargo</p></span></a>'

def test_nested_main_offers_discover_unlisted_merchants_but_not_recommendations():
    body=schema([product([{'@type':'Offer','url':INPUT,'price':10}]),{'@type':'Product','url':'https://www.cimri.com/unrelated','offers':{'@type':'Offer','url':'https://wrong-shop.com/other'}}])
    assert catalog.merchant_links(body,SOURCE)==[INPUT]

def test_encoded_epey_destinations_are_normalized_and_private_ips_rejected():
    body=card()+card(url='http://127.0.0.1/admin')+'<a href="https://unrelated.com/footer">Footer</a>'
    assert catalog.merchant_links(body,EP)==['https://independent-shop.com/widget-100ml']

def test_query_product_identity_is_not_removed_as_tracking():
    assert catalog.page_key(INPUT+'?sku=1')!=catalog.page_key(INPUT+'?sku=2')
    assert catalog.page_key(INPUT+'?utm_source=cimri')==catalog.page_key(INPUT)

def test_quotes_have_explicit_source_time_and_unverified_status():
    quote=catalog.catalog_quotes(card(),EP,BASE)[0]
    assert quote['price']==129.9 and quote['catalogUrl']==EP and quote['observedAt']
    assert quote['merchantVerified'] is False and quote['identityConfirmed'] is False

def test_conflicting_capacity_color_and_model_quotes_are_rejected():
    assert catalog.catalog_quotes(card(title='Example Widget Fresh 200 ml'),EP,BASE)==[]
    assert catalog.catalog_quotes(card(title='Example Widget Fresh Mavi 100 ml'),EP,dict(BASE,title='Example Widget Fresh Siyah 100 ml'))==[]
    assert not catalog.quoted_candidate({'title':'Sonoff ZBMINI L2'},'Sonoff S60 Zigbee')

def test_bundled_products_and_unrelated_text_do_not_become_quotes():
    base={'title':'Papia Tuvalet Kağıdı 32 li'}
    body=card(title='Papia Tuvalet Kağıdı 96 Rulo')+'<div>1 TL</div>'
    assert catalog.catalog_quotes(body,EP,base)==[]
    assert catalog.catalog_quotes(card(),SOURCE,BASE)==[]
    assert not catalog.quoted_candidate(base,'Papia Tuvalet Kağıdı 2 x 32 Rulo')
    assert catalog.quoted_candidate(base,"Papia 3 Katlı 32'lı Tuvalet Kağıdı (1 x 32 Rulo)")

def test_catalogs_recover_identity_only_from_exact_input_offer_link(monkeypatch):
    body=schema(product([{'@type':'Offer','url':INPUT,'price':10}]))
    def read(url,**kwargs):
        if '/arama?' in url:return '<a href="'+SOURCE+'">Result</a>',url
        if url==SOURCE:return body,url
        return None
    monkeypatch.setattr(catalog,'fetch_page',read)
    result=catalog.discover_catalogs(BASE)
    assert result['identity']['title']==BASE['title']
    assert result['identity']['brand']=='Example' and 'price' not in result['identity']
    assert result['urls']==[INPUT]

def test_generic_discovery_works_with_no_search_service_configured(monkeypatch):
    monkeypatch.delenv('SEARXNG_URL',raising=False)
    monkeypatch.setattr(generic,'discover_catalogs',lambda base:{'urls':['https://unknown-shop.com/example-widget'],'sources':[],'diagnostics':[]})
    web=Mock(side_effect=AssertionError('Do not depend on the broken search service'))
    monkeypatch.setattr(generic.requests,'get',web)
    base=dict(BASE)
    assert generic.discover(base)==['https://unknown-shop.com/example-widget']
    assert base['_search']['provider']=='public_catalogs';web.assert_not_called()

def test_catalog_prices_never_become_verified_prices_savings_or_watch_receipts(monkeypatch):
    quote=catalog.catalog_quotes(card(),EP,BASE)[0]
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:None)
    monkeypatch.setattr(generic,'discover_catalogs',lambda base:{'urls':[],'sources':[],'diagnostics':[],'quotes':[quote]})
    monkeypatch.delenv('SEARXNG_URL',raising=False)
    result=generic.analyze_any_seller(INPUT)
    assert result['catalogOffers']==[quote]
    assert result['price'] is None and result['offers']==[]
    assert result['savings']==0 and result['watchReceipt'] is None

def test_broad_consumer_queries_and_exact_models_are_generic():
    assert catalog.query_for({'title':"Papia Tuvalet Kağıdı 32'li"})=='papia 32'
    assert '40' in catalog.query_for({'title':"Familia Natural 40'lı"})
    assert 'UT12D' in catalog.query_for({'title':'UNI-T UT12D gerilim dedektoru'})
