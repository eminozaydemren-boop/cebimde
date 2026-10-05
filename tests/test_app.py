from app import app, clean_price, strict_zbmini_l2

def test_prices():
    assert clean_price('1.058,63 TL')==1058.63
    assert clean_price('820,00₺')==820.0

def test_identity_guard():
    assert strict_zbmini_l2('SONOFF ZBMINI L2 ZigBee Akıllı Röle')
    assert not strict_zbmini_l2('2 Adet SONOFF ZBMINIL2 – 2li Paket')
    assert not strict_zbmini_l2('Sonoff Mini R2')

def test_health():
    r=app.test_client().get('/health'); assert r.status_code==200 and r.json['ok']
