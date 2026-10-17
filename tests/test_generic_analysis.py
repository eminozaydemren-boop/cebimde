import json
from unittest.mock import Mock
import pytest
import generic_analysis as generic
from product_data import same_product
from app import app

URL='https://www.different-seller.com/brand-widget-100ml-p-123'
def page():
    product={'@type':'Product','name':'Example Brand Widget 100 ml','url':URL,'brand':{'name':'Example'},'gtin13':'8692857016208',
             'offers':{'@type':'Offer','price':199.9,'priceCurrency':'TRY','availability':'https://schema.org/InStock'}}
    return '<script type="application/ld+json">'+json.dumps(product)+'</script>'


def test_unknown_seller_identified_and_compared_without_paid_provider(monkeypatch):
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:(page(),URL))
    compare=Mock(return_value=[{'source':'other-shop.com','price':180,'url':'https://other-shop.com/widget','title':'Example Brand Widget 100 ml'}])
    monkeypatch.setattr(generic,'compare',compare)
    paid=Mock(side_effect=AssertionError('No paid APIs'));monkeypatch.setattr(generic.requests,'post',paid)
    result=generic.analyze_any_seller(URL)
    assert result['input_price']==199.9 and result['price']==180 and result['savings']==19.9
    assert len(result['offers'])==2 and result['identityVerified'] is True
    assert compare.call_args.args[0]['gtin']=='8692857016208';paid.assert_not_called()


def test_blocked_source_uses_url_title_as_hint_but_never_invents_price(monkeypatch):
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:None)
    monkeypatch.setattr(generic,'compare',lambda base:[])
    result=generic.analyze_any_seller(URL)
    assert result['price'] is None and result['identityVerified'] is False
    assert 'brand widget 100ml' in result['title']


def test_generic_seller_route_is_no_longer_rejected(monkeypatch):
    analyze=Mock(return_value={'title':'Widget','price':100,'offers':[]})
    monkeypatch.setattr(generic,'analyze_any_seller',analyze)
    r=app.test_client().get('/api/product',query_string={'url':URL})
    assert r.status_code==200 and r.json['ok'];analyze.assert_called_once()


def test_pack_and_storage_conflicts_do_not_match_even_with_same_model():
    assert not same_product({'title':'Brand ABC123 128 GB','brand':'Brand','mpn':'ABC123'}, {'title':'Brand ABC123 256 GB','brand':'Brand','mpn':'ABC123'})
    assert not same_product({'title':'Papilion Mendil 4 lu 100 yaprak','brand':'Papilion'}, {'title':'Papilion Mendil 1 lu 100 yaprak','brand':'Papilion'})
    assert not same_product({'title':'Phone ABC123 Siyah','brand':'Brand','mpn':'ABC123'}, {'title':'Phone ABC123 Beyaz','brand':'Brand','mpn':'ABC123'})


def test_exact_full_consumer_product_title_can_match_without_model():
    a={'title':'Papilion Islak Mendil Lavanta 100 Yaprak','brand':'Papilion'}
    assert same_product(a,dict(a))
    assert not same_product(a,dict(a,title='Papilion Islak Mendil Lavanta 50 Yaprak'))


def test_gtin_conflict_overrides_same_title():
    a={'title':'Papilion Islak Mendil Lavanta 100 Yaprak','gtin':'123'}
    assert not same_product(a,dict(a,gtin='456'))


def test_model_tokens_survive_seller_url_word_separators():
    from app import model_token
    assert model_token('ut 12d row unit temassiz voltaj 1000v')=='UT12D'
    assert model_token('UNI-T UT-12D Row')=='UT12D'
    assert model_token('Sonoff ZBMINI L2')=='ZBMINI-L2'


def test_discovery_searches_model_and_ranks_any_seller_without_whitelist(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    body='''<a href="https://unlisted-retailer.com/category">Category</a>
    <a href="https://another-unlisted-seller.com/uni-t-ut12d">Product</a>
    <a href="https://youtube.com/watch?id=UT12D">Video</a>'''
    get=Mock(return_value=Mock(ok=True,status_code=200,text=body));monkeypatch.setattr(generic.requests,'get',get)
    urls=generic.discover({'title':'ut 12d row unit voltaj dedektoru','url':URL})
    assert urls[0]=='https://another-unlisted-seller.com/uni-t-ut12d'
    assert all('youtube.com' not in u for u in urls)
    assert any('UT12D' in call.kwargs['params']['q'] for call in get.call_args_list)


def test_distinct_merchants_get_slots_before_repeated_same_shop_pages(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    links=['https://one-shop.com/widget-ABC123-'+str(i) for i in range(8)]
    links+=['https://shop-'+str(i)+'.com/widget-ABC123' for i in range(5)]
    get=Mock(return_value=Mock(ok=True,status_code=200,text=''.join('<a href="'+u+'">Product</a>' for u in links)))
    monkeypatch.setattr(generic.requests,'get',get)
    base={'title':'Brand ABC123','url':URL,'brand':'Brand','mpn':'ABC123'}
    result=generic.discover(base)
    from urllib.parse import urlparse
    assert len(result)==12 and len({urlparse(u).hostname for u in result[:6]})==6
    assert base['_search']['candidates']==12


def test_user_name_overrides_unstructured_error_page_title(monkeypatch):
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:('<meta property="og:title" content="Access denied">',URL))
    compare=Mock(return_value=[]);monkeypatch.setattr(generic,'compare',compare)
    result=generic.analyze_any_seller(URL,'Papilion Islak Mendil Lavanta 100 Yaprak')
    assert compare.call_args.args[0]['title']=='Papilion Islak Mendil Lavanta 100 Yaprak'
    assert result['price'] is None and result['identityVerified'] is False


def test_barcode_hint_applies_even_when_page_has_metadata(monkeypatch):
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:('<h1>Product loading</h1>',URL))
    compare=Mock(return_value=[]);monkeypatch.setattr(generic,'compare',compare)
    generic.analyze_any_seller(URL,'4006381333931')
    assert compare.call_args.args[0]['gtin']=='4006381333931'


def test_hint_cannot_overwrite_verified_input_product_identity(monkeypatch):
    monkeypatch.setattr(generic,'fetch_page',lambda *a,**kw:(page(),URL))
    compare=Mock(return_value=[]);monkeypatch.setattr(generic,'compare',compare)
    result=generic.analyze_any_seller(URL,'Different Product 4006381333931')
    assert result['title']=='Example Brand Widget 100 ml' and result['input_price']==199.9
    assert compare.call_args.args[0]['gtin']=='8692857016208'


def test_pack_suffix_is_not_a_model_number():
    from app import model_token
    assert model_token('Familia Natural Tuvalet Kağıdı 40li') is None
    assert model_token('Papilion 100LU') is None


def test_consumer_product_gets_unquoted_name_search(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    get=Mock(return_value=Mock(ok=True,status_code=200,text=''));monkeypatch.setattr(generic.requests,'get',get)
    generic.discover({'title':'familia natural tuvalet kagidi 40 li','url':URL})
    queries=[c.kwargs['params']['q'] for c in get.call_args_list]
    assert any(q.startswith('familia natural') for q in queries)
    assert all(not q.startswith('40LI') for q in queries)


def test_seller_pack_punctuation_does_not_prevent_same_product():
    assert same_product({'title':'familia natural tuvalet kagidi 40 li'}, {'title':"Familia Natural Tuvalet Kağıdı 40'lı",'brand':'Familia'})
    assert not same_product({'title':'familia natural tuvalet kagidi 40 li'}, {'title':"Familia Natural Tuvalet Kağıdı 32'li",'brand':'Familia'})


def test_structured_offer_for_a_different_explicit_product_url_is_rejected():
    from product_data import structured_product
    assert structured_product(page(),'https://www.different-seller.com/different-product') is None


def test_consumer_pack_units_match_but_multipacks_stay_distinct():
    a={'title':"Familia Natural Tuvalet Kağıdı 40'lı"}
    assert same_product(a,{'title':'Familia Natural Tuvalet Kağıdı 40 Rulo'})
    assert not same_product(a,{'title':'Familia Natural Tuvalet Kağıdı 32 Rulo'})
    assert not same_product(a,{'title':'Familia Natural Tuvalet Kağıdı 40 Rulo 3 Paket'})


def test_encoded_titles_and_single_brand_arrays_are_read():
    from product_data import structured_product
    data={'@type':'Product','name':'Familia Natural Tuvalet Kağıdı 40&#039;lı','brand':[{'name':'Familia'}],
          'description':'Includes "quoted" text','offers':{'@type':'Offer','price':439.9,'priceCurrency':'TRY'}}
    parsed=structured_product('<script type="application/ld+json">'+json.dumps(data)+'</script>',URL)
    assert parsed['title']=="Familia Natural Tuvalet Kağıdı 40'lı" and parsed['brand']=='Familia'


def test_similar_consumer_names_never_become_verified_comparisons(monkeypatch):
    candidate_url='https://another-shop.com/familia-plus-natural-40li'
    data={'@type':'Product','name':"Familia Plus Natural 40'lı Tuvalet Kağıdı",'brand':[{'name':'Familia'}],
          'offers':{'@type':'Offer','price':439.9,'priceCurrency':'TRY'}}
    body='<script type="application/ld+json">'+json.dumps(data)+'</script>'
    input_url='https://retailer.com/familia-natural-tuvalet-kagidi-40-li'
    monkeypatch.setattr(generic,'fetch_page',lambda url,**kw:(body,candidate_url) if url==candidate_url else None)
    monkeypatch.setattr(generic,'discover',lambda base:[candidate_url])
    result=generic.analyze_any_seller(input_url)
    assert result['similarOffers'][0]['price']==439.9
    assert result['offers']==[] and result['price'] is None and result['input_price'] is None
    assert not result['identityVerified'] and result['savings']==0 and result['watchReceipt'] is None


def test_similar_consumer_names_do_not_override_gtin_or_pack_conflicts():
    from product_data import plausible_product
    a={'title':'Familia Natural Tuvalet Kagidi 40 li','gtin':'123'}
    assert not plausible_product(a,{'title':'Familia Plus Natural Tuvalet Kagidi 40 li','brand':'Familia','gtin':'456'})
    assert not plausible_product(a,{'title':'Familia Plus Natural Tuvalet Kagidi 32 li','brand':'Familia'})


def test_selected_marketplace_candidate_uses_only_public_analysis(monkeypatch):
    analyze=Mock(return_value={'title':'Selected Product','price':100,'offers':[]})
    monkeypatch.setattr(generic,'analyze_any_seller',analyze)
    import app as application
    paid=Mock(side_effect=AssertionError('Paid marketplace adapter must not run'))
    monkeypatch.setattr(application,'reef_hepsiburada',paid)
    r=app.test_client().get('/api/product',query_string={'url':'https://www.hepsiburada.com/product-p-HBCV000TEST','mode':'public'})
    assert r.status_code==200 and r.json['product']['title']=='Selected Product'
    analyze.assert_called_once();paid.assert_not_called()


def test_same_consumer_title_words_match_despite_word_order():
    a={'title':"Familia Plus Natural 40'lı Tuvalet Kağıdı",'brand':'Familia'}
    assert same_product(a,{'title':"Famılıa Plus Natural Tuvalet Kağıdı 40'Lı",'brand':'FAMILIA'})
    assert not same_product(a,{'title':"Familia Natural Tuvalet Kağıdı 40'Lı",'brand':'Familia'})
    assert not same_product(a,{'title':"Familia Plus Natural Tuvalet Kağıdı 32'Lı",'brand':'Familia'})


def test_brochure_discovery_never_turns_search_mentions_into_price_offers(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    def search(url,**kw):
        brochure='broşür aktüel katalog' in kw['params']['q']
        body=('<a href="https://campaigns.com/brosur/familia-40li">239 TL brochure</a>' if brochure else
              '<a href="https://www.akakce.com/tuvalet-kagidi/familia-40li.html">239 TL</a><a href="https://retailer.com/familia-40li">Product</a>')
        return Mock(ok=True,status_code=200,text=body)
    monkeypatch.setattr(generic.requests,'get',search)
    base={'title':'Familia Natural Tuvalet Kagidi 40 li','url':URL}
    candidates=generic.discover(base)
    assert candidates==['https://retailer.com/familia-40li']
    assert base['_brochures'][0]['kind']=='brochure'
    assert len(base['_brochures'])==2
    assert all('price' not in source and source['identityConfirmed'] is False for source in base['_brochures'])


def test_successful_brochure_search_does_not_hide_failed_price_search(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    def search(url,**kw):
        return Mock(status_code=200,ok='broşür aktüel katalog' in kw['params']['q'],text='<a href="https://retailer.com/brosur/familia">Campaign</a>')
    monkeypatch.setattr(generic.requests,'get',search)
    base={'title':'Familia Natural Tuvalet Kagidi 40 li','url':URL}
    assert generic.discover(base)==[]
    assert base['_search']['status']=='unavailable' and base['_brochures']


def test_search_waits_for_free_instance_instead_of_discarding_after_seven_seconds(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    get=Mock(return_value=Mock(ok=True,status_code=200,text='<article class="result result-default"><a href="https://independent-shop.com/ABC123">Product</a></article>'))
    monkeypatch.setattr(generic.requests,'get',get)
    base={'title':'Brand ABC123','url':URL}
    assert generic.discover(base)==['https://independent-shop.com/ABC123']
    assert all(call.kwargs['timeout']==(10,30) for call in get.call_args_list)


def test_result_articles_exclude_footer_error_and_navigation_links():
    body='''<html><a href="https://github.com/searxng/searxng">Code</a>
    <article class="result result-default"><a href="https://retailer.com/item">Item</a></article>
    <a href="https://another-service.com/help">Help</a></html>'''
    assert generic.search_links(body,'https://search-service.com')==['https://retailer.com/item']


def test_http_200_error_page_is_not_a_completed_search(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    monkeypatch.setattr(generic.requests,'get',Mock(return_value=Mock(ok=True,status_code=200,text='<html><p>Search temporarily unavailable</p><a href="https://github.com/searxng/searxng">Help</a></html>')))
    base={'title':'Brand ABC123','url':URL}
    assert generic.discover(base)==[]
    assert base['_search']['status']=='unavailable'


def test_upstream_errors_are_not_reported_as_no_matching_product(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    body='<html><td class="response-error">Suspended: too many requests</td><p>No results were found</p></html>'
    monkeypatch.setattr(generic.requests,'get',Mock(return_value=Mock(ok=True,status_code=200,text=body)))
    base={'title':'Brand ABC123','url':URL}
    assert generic.discover(base)==[]
    assert base['_search']['status']=='unavailable'
    assert all(a['state']=='upstream_unavailable' for a in base['_search']['attempts'])


def test_known_listings_do_not_consume_product_verification_slots(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    links=['https://www.trendyol.com/papia-32-li-tuvalet-kagidi-y-s51087',
           'https://www.amazon.com.tr/s?k=papia','https://retailer.com/kategoriler/kagit',
           'https://new-seller.com/brand-widget-100ml']
    body='<html>'+''.join('<article class="result"><a href="'+u+'">Result</a></article>' for u in links)+'</html>'
    monkeypatch.setattr(generic.requests,'get',Mock(return_value=Mock(ok=True,status_code=200,text=body)))
    assert generic.discover({'title':'Brand Widget 100ml','url':URL})==[links[-1]]


@pytest.mark.parametrize('title',["Papia Tuvalet Kağıdı 32'li",'Sonoff ZBMINI L2','Faber Castell Grip 0.7 mm','Example Şampuan 500 ml'])
def test_any_product_type_can_be_discovered_without_a_merchant_whitelist(monkeypatch,title):
    monkeypatch.setenv('SEARXNG_URL','https://search-service.com')
    get=Mock(return_value=Mock(ok=True,status_code=200,text='<article class="result"><a href="https://previously-unknown-shop.com/product">Item</a></article>'))
    monkeypatch.setattr(generic.requests,'get',get)
    base={'title':title,'url':URL}
    assert generic.discover(base)==['https://previously-unknown-shop.com/product']
    assert base['_search']['status']=='completed'
