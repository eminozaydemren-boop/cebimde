from unittest.mock import Mock
import pytest
from app import app
import watch_store
import price_monitor

KEY='a'*64
URL='https://www.robotistan.com/unit-ut-12d-row-temassiz-ac-voltaj-test-cihazi'
ROW=('watch-id','UNI-T UT12D','https://www.hepsiburada.com/unit-ut12d-p-HBCVTEST',500,{},False,None,None)

class Conn:
    def __init__(self,row):self.row=row;self.writes=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,args=None):
        if sql.lstrip().startswith('SELECT'):return Mock(fetchone=lambda:self.row)
        self.writes.append((sql,args));return Mock()

@pytest.fixture
def db(monkeypatch):
    conn=Conn(ROW)
    monkeypatch.setattr(watch_store,'initialize',lambda:None)
    monkeypatch.setattr(watch_store,'db',lambda:conn)
    return conn

def test_free_recheck_records_verified_price_and_target_notice(db,monkeypatch):
    fetch=Mock(return_value={'price':400,'url':URL})
    monkeypatch.setattr(price_monitor,'check_watch',fetch)
    r=app.test_client().post('/api/watches/watch-id/check',headers={'X-Watch-Key':KEY},json={'sourceUrl':URL})
    assert r.status_code==200 and r.json['verified'] and r.json['notifications']==1
    assert fetch.call_count==1
    assert fetch.call_args.args[2]['sources']==[URL]
    assert any('monitor_meta' in sql for sql,args in db.writes)
    assert any(args[0]==400 and args[2] is True for sql,args in db.writes if 'last_price=%s' in sql)

def test_failed_new_source_is_not_saved_and_old_price_is_preserved(db,monkeypatch):
    monkeypatch.setattr(price_monitor,'check_watch',lambda *a:None)
    r=app.test_client().post('/api/watches/watch-id/check',headers={'X-Watch-Key':KEY},json={'sourceUrl':URL})
    assert r.status_code==200 and not r.json['verified'] and r.json['notifications']==0
    assert not any('monitor_meta=' in sql or 'last_price=' in sql for sql,args in db.writes)

def test_unauthorized_recheck_cannot_fetch_or_update(db,monkeypatch):
    fetch=Mock();monkeypatch.setattr(price_monitor,'check_watch',fetch)
    assert app.test_client().post('/api/watches/watch-id/check').status_code==401
    fetch.assert_not_called();assert not db.writes

def test_other_owners_missing_watch_is_404(db,monkeypatch):
    db.row=None;fetch=Mock();monkeypatch.setattr(price_monitor,'check_watch',fetch)
    r=app.test_client().post('/api/watches/other-owner/check',headers={'X-Watch-Key':KEY})
    assert r.status_code==404;fetch.assert_not_called()

def test_rate_limit_protects_existing_watch(db,monkeypatch):
    from datetime import datetime,timezone
    db.row=ROW[:-1]+(datetime.now(timezone.utc),)
    fetch=Mock();monkeypatch.setattr(price_monitor,'check_watch',fetch)
    assert app.test_client().post('/api/watches/watch-id/check',headers={'X-Watch-Key':KEY}).status_code==429
    fetch.assert_not_called()

def test_recheck_rejects_unsupported_source_before_fetch(db,monkeypatch):
    fetch=Mock();monkeypatch.setattr(price_monitor,'check_watch',fetch)
    r=app.test_client().post('/api/watches/watch-id/check',headers={'X-Watch-Key':KEY},json={'sourceUrl':'https://127.0.0.1/admin'})
    assert r.status_code==400;fetch.assert_not_called()
