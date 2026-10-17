from product_data import structured_product
U='https://new-merchant.com/brand-widget-100ml'

def page(**overrides):
    import html
    values={'og:type':'product','og:title':'Example Brand Widget 100 ml','og:url':U,'product:price:amount':'149.90','product:price:currency':'TRY','product:brand':'Example','product:availability':'in stock'}
    values.update(overrides)
    return ''.join('<meta property="'+k+'" content="'+html.escape(v,quote=True)+'">' for k,v in values.items())

def test_new_merchant_standard_product_metadata_needs_no_adapter():
    p=structured_product(page(),U)
    assert p['title']=='Example Brand Widget 100 ml' and p['price']==149.9 and p['currency']=='TRY'

def test_metadata_cannot_turn_categories_recommendations_or_other_hosts_into_this_product():
    for data in [{'og:type':'website'},{'og:url':'https://new-merchant.com/other-product'},{'og:url':'https://evil.test/brand-widget-100ml'},{'og:url':''},{'og:url':'https://user@new-merchant.com/brand-widget-100ml'}]:
        assert structured_product(page(**data),U) is None

def test_missing_currency_out_of_stock_and_non_numeric_amounts_never_become_prices():
    for data in [{'product:price:currency':'USD'},{'product:price:currency':''},{'product:availability':'out of stock'},{'product:price:amount':'149 TL - 199 TL'},{'product:price:amount':'10%'},{'product:price:amount':'nan'},{'product:price:amount':'0'}]:
        assert structured_product(page(**data),U)['price'] is None
