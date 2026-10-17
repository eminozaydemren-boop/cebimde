from datetime import date
from unittest.mock import Mock
import brochure_queue as queue
from scripts import brochure_reader as reader

M='https://katalog24.com.tr/magaza/new-store'
U='https://katalog24.com.tr/new-store/brosur/1'

def test_provider_urls_reject_credentials_queries_ports_and_unrelated_hosts():
    assert queue.public_source(M,True) and queue.public_source(U)
    for url in ['http://katalog24.com.tr/a','https://evil.test/a','https://user@katalog24.com.tr/a','https://katalog24.com.tr:444/a','https://katalog24.com.tr/a?url=http://localhost','https://katalog24.com.tr/a#fragment','https://katalog24.com.tr/../a']:
        assert not queue.public_source(url)

def test_unlisted_merchant_is_discovered_without_code_changes(monkeypatch):
    body='<a class="shop-list-link" href="'+M+'" title="New Store kataloglar ve teklifler">Store</a><a class="shop-list-link" href="https://evil.test/magaza/bad" title="Bad">Bad</a>'
    monkeypatch.setattr(reader,'read',lambda url:body)
    assert reader.discover_directory()==[dict(url=M,name='New Store')]

def test_catalog_registration_requires_a_discovered_merchant_and_bounded_dates():
    c=dict(url=U,merchantUrl=M,startDate='2026-10-17',endDate='2026-10-25')
    assert queue.valid_catalog(c,{M})
    assert not queue.valid_catalog(c,set())
    assert not queue.valid_catalog(dict(c,endDate='2027-10-25'),{M})

def test_batch_result_validation_prevents_unbounded_cursors_and_pages():
    data=dict(url=U,lease='a'*32,cards=[],nextPage=4,complete=False,state='no_prices',pagesRead=3)
    assert queue.valid_result(data)
    for override in [dict(nextPage=1001),dict(pagesRead=4),dict(complete='true'),dict(lease='bad'),dict(state='made_up')]:
        assert not queue.valid_result(dict(data,**override))

def test_queue_mutations_require_repository_oidc(monkeypatch):
    from app import app
    monkeypatch.setattr(queue,'authorized',lambda:False)
    for route in ['directory','jobs/claim','jobs/complete']:
        assert app.test_client().post('/api/brochures/'+route,json={}).status_code==401

def test_invalid_queue_payloads_never_open_database(monkeypatch):
    from app import app
    monkeypatch.setattr(queue,'authorized',lambda:True)
    db=Mock(side_effect=AssertionError('Do not connect for invalid input'));monkeypatch.setattr(queue,'db',db)
    assert app.test_client().post('/api/brochures/directory',json={'merchants':[dict(url='https://evil.test/a',name='bad')],'catalogs':[]}).status_code==400
    assert app.test_client().post('/api/brochures/jobs/complete',json={'url':U}).status_code==400
    db.assert_not_called()

def test_large_catalog_batch_resumes_instead_of_being_skipped(monkeypatch):
    event='{"@type":"SaleEvent","startDate":"2026-10-17","endDate":"2026-10-25","name":"New store","organizer":{"name":"New Store"}}'
    body='<script type="application/ld+json">'+event+'</script><a href="'+U+'?page=128">128</a><img class="brochure-page-image" data-src="https://priserocdn.com/image.jpg">'
    monkeypatch.setattr(reader,'metadata',lambda *a,**kw:dict(title='New store',startDate='2026-10-17',endDate='2026-10-25',merchant='New Store'))
    calls=[]
    def read(url,image=False):
        calls.append(url);return b'image' if image else body
    monkeypatch.setattr(reader,'read',read);monkeypatch.setattr(reader,'read_image',lambda data:object())
    monkeypatch.setattr(reader,'extract_cards',lambda im:[])
    result=reader.scan_batch(U,64,3)
    assert result['nextPage']==67 and result['pagesRead']==3 and not result['complete']
    assert U+'?page=64' in calls and U+'?page=66' in calls and U+'?page=67' not in calls
