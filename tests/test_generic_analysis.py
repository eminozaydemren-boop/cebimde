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
