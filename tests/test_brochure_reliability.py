import hashlib
import json
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import Mock
import urllib.error

import pytest
import brochure_queue as queue
import brochure_store
from scripts import brochure_client as client


@pytest.mark.parametrize('code', [429, 502, 503, 504])
def test_transient_response_retries_same_payload(monkeypatch, code):
    post = Mock(side_effect=[urllib.error.HTTPError('https://example.test', code, 'temporary', {}, None), {'ok': True}])
    sleep = Mock()
    worker = client.Client()
    monkeypatch.setattr(worker, '_post', post)
    monkeypatch.setattr(client.time, 'sleep', sleep)
    payload = {'lease': 'a' * 32}
    assert worker.post('/api/brochures/jobs/complete', payload) == {'ok': True}
    assert post.call_count == 2
    assert post.call_args_list[0] == post.call_args_list[1]
    sleep.assert_called_once()


@pytest.mark.parametrize('code', [400, 401, 409])
def test_permanent_response_is_not_hidden(monkeypatch, code):
    worker = client.Client()
    post = Mock(side_effect=urllib.error.HTTPError('https://example.test', code, 'permanent', {}, None))
    monkeypatch.setattr(worker, '_post', post)
    with pytest.raises(urllib.error.HTTPError):
        worker.post('/api/brochures/jobs/complete', {})
    assert post.call_count == 1


def test_retries_have_a_hard_limit(monkeypatch):
    worker = client.Client()
    post = Mock(side_effect=urllib.error.HTTPError('https://example.test', 503, 'temporary', {}, None))
    monkeypatch.setattr(worker, '_post', post)
    monkeypatch.setattr(client.time, 'sleep', Mock())
    with pytest.raises(urllib.error.HTTPError):
        worker.post('/api/brochures/jobs/complete', {})
    assert post.call_count == 6


def test_ambiguous_claim_is_not_repeated(monkeypatch):
    worker = client.Client()
    post = Mock(side_effect=urllib.error.URLError('lost response'))
    monkeypatch.setattr(worker, '_post', post)
    with pytest.raises(urllib.error.URLError):
        worker.post('/api/brochures/jobs/claim', {})
    assert post.call_count == 1


def test_completion_retries_lost_response(monkeypatch):
    worker = client.Client()
    post = Mock(side_effect=[TimeoutError(), {'ok': True, 'replayed': True}])
    monkeypatch.setattr(worker, '_post', post)
    monkeypatch.setattr(client.time, 'sleep', Mock())
    assert worker.post('/api/brochures/jobs/complete', {})['replayed']


@pytest.mark.parametrize('changed', [False, True])
def test_lost_completion_response_does_not_write_or_count_again(monkeypatch, changed):
    from app import app
    payload = dict(url='https://katalog24.com.tr/store/brosur/1', lease='a' * 32,
                   cards=[], nextPage=4, complete=False, state='no_prices', pagesRead=3)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = (digest, 0)

    @contextmanager
    def db():
        yield conn

    monkeypatch.setattr(queue, 'db', db)
    monkeypatch.setattr(queue, 'initialize', Mock())
    monkeypatch.setattr(queue, 'authorized', lambda: True)
    save = Mock()
    monkeypatch.setattr(brochure_store, 'save_cards', save)
    if changed:
        payload['pagesRead'] = 2
    response = app.test_client().post('/api/brochures/jobs/complete', json=payload)
    assert response.status_code == (409 if changed else 200)
    if not changed:
        assert response.json['replayed'] is True
    save.assert_not_called()
    assert conn.execute.call_count == 1


def test_schema_lock_precedes_table_locks():
    conn = Mock()
    brochure_store.initialize(conn)
    assert 'pg_advisory_xact_lock' in conn.execute.call_args_list[0].args[0]
