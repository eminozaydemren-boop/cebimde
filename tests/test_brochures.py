from datetime import date
from unittest.mock import Mock
from brochure_store import valid_card,match_card
from scripts.brochure_reader import parse,metadata,number

def card(**kw):
    d=dict(title="Familia Tuvalet Kağıdı 40'lı",text='Familia Plus Natural',price=239.,region=[.02,.6,.2,.9],startDate='2026-10-17',endDate='2026-10-25',campaign='Ataşehir Brandium açılışı',scope='Ataşehir Brandium açılışı',merchant='Anpa Gross',sourceUrl='https://katalog24.com.tr/anpa-gross/brosur/2?page=11',imageUrl='https://priserocdn.com/k2/tr/hash/10.jpg',imageSha256='a'*64)
    return dict(d,**kw)

def test_dated_source_validation_and_price_bounds():
    assert valid_card(card(),date(2026,10,20))
    for row in [card(price=float('nan')),card(price=True),card(price=-1),card(imageUrl='http://127.0.0.1/'),card(sourceUrl='https://evil.test/x'),card(endDate='2027-01-01'),card(region=[.8,.6,.2,.9])]:
        assert not valid_card(row,date(2026,10,20))
    assert not valid_card(card(),date(2026,10,26))
    assert not valid_card(card(),date(2026,10,16))

def test_brochure_candidate_requires_brand_type_and_equal_pack():
    base=dict(title="Familia Plus Natural Tuvalet Kağıdı 40'lı",brand='Familia')
    assert match_card(base,card())
    assert match_card(base,card(title="Familia Tuvolet Koğıdı 40'lı"))
    assert not match_card(base,card(title="Familia Tuvalet Kağıdı 32'li"))
    assert not match_card(base,card(title="Papia Tuvalet Kağıdı 40'lı"))
    assert not match_card(base,card(title="Familia Kağıt Havlu 40'lı"))
    assert not match_card(base,card(title="Familia Kağıdı 40'lı"))

def test_current_metadata_is_from_saleevent_not_url_guess():
    p=parse('<script type="application/ld+json">{"@type":"SaleEvent","startDate":"2026-10-17","endDate":"2026-10-25","name":"Brandium","organizer":{"name":"Anpa"}}</script>')
    assert metadata(p,'https://katalog24.com.tr/x',date(2026,10,20))['scope']=='Brandium'
    assert metadata(p,'https://katalog24.com.tr/x',date(2026,10,26)) is None
    assert metadata(parse('<h1>239 TL</h1>'),'https://katalog24.com.tr/x',date(2026,10,20)) is None

def test_ocr_number_requires_decimal_cents():
    assert number('239,00')==239
    assert number('59.90')==59.9
    assert number('239') is None
    assert number('9.9') is None
    assert number('2x239,00') is None

def test_import_requires_oidc_and_rejects_bad_payload(monkeypatch):
    import app,monitor_auth
    client=app.app.test_client()
    monkeypatch.setattr(monitor_auth,'authorized',lambda header:False)
    assert client.post('/api/brochures/import',json={'cards':[]}).status_code==401
    monkeypatch.setattr(monitor_auth,'authorized',lambda header:True)
    assert client.post('/api/brochures/import',json={'cards':[card(price=-1)]}).status_code==400

def test_brochure_price_never_changes_online_minimum_savings_or_snapshot(monkeypatch):
    import generic_analysis as g,brochure_store,watch_store
    monkeypatch.setattr(g,'fetch_page',lambda *a,**kw:None)
    monkeypatch.setattr(g,'compare',lambda base:[])
    monkeypatch.setattr(brochure_store,'find_brochures',lambda base:[card()])
    snapshot=Mock(return_value=None);monkeypatch.setattr(watch_store,'sign_snapshot',snapshot)
    result=g.analyze_any_seller('https://merchant.com/familia-natural-tuvalet-kagidi-40li')
    assert result['brochureOffers'][0]['price']==239
    assert result['price'] is None and result['offers']==[] and result['savings']==0
    assert snapshot.call_args.args[1] is None
