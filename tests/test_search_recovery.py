import pytest
from unittest.mock import Mock
import generic_analysis as generic
from product_data import plausible_product,same_product
from app import model_token

TITLE='Honor 600 Pro 5G 512 GB 12 GB RAM Honor Turkiye Garantili'

def test_trendyol_brand_path_is_retained_in_fallback_name():
    assert generic.url_title('https://www.trendyol.com/honor/600-pro-5g-512-gb-12-gb-ram-p-1140479956').startswith('honor 600 pro')
    assert model_token(TITLE)=='600PRO'

def test_rate_limit_does_not_trigger_failed_legacy_searches(monkeypatch):
    monkeypatch.setattr(generic,'discover_api',lambda base:{'urls':[],'state':'rate_limited','retryAfterSeconds':120})
    fallback=Mock(side_effect=AssertionError('No fallback storm'))
    monkeypatch.setattr(generic,'discover_catalogs',fallback)
    base={'title':TITLE}
    assert generic.discover(base)==[]
    assert base['_search']['status']=='rate_limited'
    fallback.assert_not_called()

def test_phone_color_options_remain_unconfirmed_candidates():
    base={'title':TITLE};candidate={'title':'Honor 600 Pro 5G 512 GB 12 GB RAM Siyah','brand':'Honor'}
    assert plausible_product(base,candidate)
    assert not same_product(base,candidate)

@pytest.mark.parametrize('title',[
    'Honor 400 Pro 5G 512 GB 12 GB RAM Siyah',
    'Honor 600 Pro 5G 256 GB 12 GB RAM Siyah',
    'Honor 600 Pro 5G 512 GB 8 GB RAM Siyah',
    'Honor 600 Pro 5G 512 GB 12 GB RAM Kilif',
    'Honor 600 Pro 5G 512 GB 12 GB RAM Ekran Koruyucu',
    'Honor 600 Pro Plus 5G 512 GB 12 GB RAM Siyah',
])
def test_other_models_storage_ram_and_accessories_are_rejected(title):
    assert not plausible_product({'title':TITLE},{'title':title,'brand':'Honor'})
