"""Persistent fair queue for every merchant discovered in the brochure directory."""
import json,re,secrets,hashlib,logging
from datetime import date
from urllib.parse import urlparse
from flask import Blueprint,request,jsonify
from watch_store import db
from brochure_store import initialize as initialize_cards,valid_card

queue_api=Blueprint('brochure_queue',__name__,url_prefix='/api/brochures')

def initialize(conn):
    initialize_cards(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS brochure_merchants (
        url TEXT PRIMARY KEY,name TEXT NOT NULL,seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),discovery_state TEXT NOT NULL DEFAULT 'read')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS brochure_catalogs (
        url TEXT PRIMARY KEY,merchant_url TEXT NOT NULL,start_date DATE NOT NULL,end_date DATE NOT NULL,
        seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),last_attempt TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,lease_until TIMESTAMPTZ,lease_id TEXT,
        next_page INTEGER NOT NULL DEFAULT 1,pages_read INTEGER NOT NULL DEFAULT 0,
        cards_read INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending')''')
    conn.execute('CREATE INDEX IF NOT EXISTS brochure_queue_due ON brochure_catalogs(completed_at,last_attempt)')
    conn.execute('''CREATE TABLE IF NOT EXISTS brochure_batch_receipts (
        lease_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, imported INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')

def database_failure(operation,error,message):
    # Never log SQL parameters, submitted cards, tokens or connection strings.
    logging.getLogger(__name__).error('Brochure database failure operation=%s type=%s sqlstate=%s',
        operation,type(error).__name__,getattr(error,'sqlstate',None))
    return jsonify(ok=False,error=message),503

def public_source(value,merchant=False):
    if not isinstance(value,str) or len(value)>1500:return False
    try:
        p=urlparse(value)
        pattern=r'/magaza/[\w-]+' if merchant else r'/[\w-]+(?:/(?:katalog-[\w-]+|brosur/\d+))?'
        return bool(p.scheme=='https' and p.hostname=='katalog24.com.tr' and not p.username and not p.password and not p.port and not p.query and not p.fragment and re.fullmatch(pattern,p.path))
    except (ValueError,TypeError):return False

def authorized():
    from monitor_auth import authorized as check
    return check(request.headers.get('Authorization',''))

def valid_catalog(c,merchants):
    try:
        start=date.fromisoformat(c['startDate']);end=date.fromisoformat(c['endDate'])
        return public_source(c['url']) and c['merchantUrl'] in merchants and 0<=(end-start).days<=60
    except (TypeError,ValueError,KeyError):return False

@queue_api.post('/directory')
def register_directory():
    if not authorized():return jsonify(ok=False),401
    if not request.content_length or request.content_length>2_000_000:return jsonify(ok=False),413
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(ok=False),400
    merchants=data.get('merchants');catalogs=data.get('catalogs')
    if not isinstance(merchants,list) or not isinstance(catalogs,list) or len(merchants)>500 or len(catalogs)>5000:return jsonify(ok=False),400
    if any(not isinstance(m,dict) or not public_source(m.get('url'),True) or not isinstance(m.get('name'),str) or not 0<len(m['name'])<=100 or m.get('discoveryState','read') not in ('read','unavailable') for m in merchants):return jsonify(ok=False),400
    keys={m['url'] for m in merchants}
    if any(not isinstance(c,dict) or not valid_catalog(c,keys) for c in catalogs):return jsonify(ok=False),400
    try:
        with db() as conn:
            initialize(conn)
            for m in merchants:
                conn.execute('''INSERT INTO brochure_merchants(url,name,discovery_state) VALUES(%s,%s,%s)
                    ON CONFLICT(url) DO UPDATE SET name=EXCLUDED.name,seen_at=NOW(),discovery_state=EXCLUDED.discovery_state''',(m['url'],m['name'],m.get('discoveryState','read')))
            for c in catalogs:
                conn.execute('''INSERT INTO brochure_catalogs(url,merchant_url,start_date,end_date) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(url) DO UPDATE SET merchant_url=EXCLUDED.merchant_url,
                    next_page=CASE WHEN brochure_catalogs.start_date<>EXCLUDED.start_date OR brochure_catalogs.end_date<>EXCLUDED.end_date THEN 1 ELSE brochure_catalogs.next_page END,
                    completed_at=CASE WHEN brochure_catalogs.start_date<>EXCLUDED.start_date OR brochure_catalogs.end_date<>EXCLUDED.end_date THEN NULL ELSE brochure_catalogs.completed_at END,
                    start_date=EXCLUDED.start_date,end_date=EXCLUDED.end_date,seen_at=NOW()''',(c['url'],c['merchantUrl'],c['startDate'],c['endDate']))
            conn.execute("DELETE FROM brochure_cards WHERE expires_on<CURRENT_DATE-7")
            conn.execute("DELETE FROM brochure_catalogs WHERE end_date<CURRENT_DATE-14")
            conn.execute("DELETE FROM brochure_batch_receipts WHERE created_at<NOW()-INTERVAL '2 days'")
        return jsonify(ok=True,merchants=len(merchants),catalogs=len(catalogs))
    except Exception as error:return database_failure('directory',error,'Dizin kaydedilemedi')

@queue_api.post('/jobs/claim')
def claim():
    if not authorized():return jsonify(ok=False),401
    try:
        with db() as conn:
            initialize(conn)
            row=conn.execute('''SELECT url,next_page,completed_at FROM brochure_catalogs
                WHERE seen_at>NOW()-INTERVAL '24 hours' AND end_date >= (NOW() AT TIME ZONE 'Europe/Istanbul')::date
                AND start_date <= (NOW() AT TIME ZONE 'Europe/Istanbul')::date
                AND (lease_until IS NULL OR lease_until<NOW())
                AND (completed_at IS NULL OR completed_at<NOW()-INTERVAL '6 hours')
                ORDER BY last_attempt ASC NULLS FIRST,url LIMIT 1 FOR UPDATE SKIP LOCKED''').fetchone()
            if row is None:return jsonify(ok=True,job=None)
            url,page,completed=row;lease=secrets.token_hex(16)
            conn.execute('''UPDATE brochure_catalogs SET last_attempt=NOW(),lease_until=NOW()+INTERVAL '10 minutes',lease_id=%s,
                next_page=CASE WHEN completed_at IS NOT NULL THEN 1 ELSE next_page END,
                pages_read=CASE WHEN completed_at IS NOT NULL THEN 0 ELSE pages_read END,
                cards_read=CASE WHEN completed_at IS NOT NULL THEN 0 ELSE cards_read END,
                completed_at=NULL,state='scanning' WHERE url=%s''',(lease,url))
        return jsonify(ok=True,job=dict(url=url,page=1 if completed else page,lease=lease))
    except Exception as error:return database_failure('claim',error,'Tarama kuyruguna erisilemiyor')

def valid_result(data):
    try:
        if not isinstance(data,dict) or not public_source(data.get('url')) or not re.fullmatch('[a-f0-9]{32}',str(data.get('lease',''))):return False
        if data.get('state') not in ('read','no_prices','expired','unavailable'):return False
        if type(data.get('complete')) is not bool:return False
        if type(data.get('nextPage')) is not int or not 1<=data['nextPage']<=1000:return False
        if type(data.get('pagesRead')) is not int or not 0<=data['pagesRead']<=3:return False
        cards=data.get('cards')
        if not isinstance(cards,list) or len(cards)>600 or any(not valid_card(c) for c in cards):return False
        return all(urlparse(c['sourceUrl']).path==urlparse(data['url']).path for c in cards)
    except (TypeError,ValueError,KeyError):return False

@queue_api.post('/jobs/complete')
def complete():
    if not authorized():return jsonify(ok=False),401
    if not request.content_length or request.content_length>2_000_000:return jsonify(ok=False),413
    data=request.get_json(silent=True)
    if not valid_result(data):return jsonify(ok=False,error='Tarama sonucu gecersiz'),400
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    try:
        with db() as conn:
            initialize(conn)
            receipt=conn.execute('SELECT payload_hash,imported FROM brochure_batch_receipts WHERE lease_id=%s',
                (data['lease'],)).fetchone()
            if receipt:
                if receipt[0]!=digest:return jsonify(ok=False,error='Tarama sonucu degistirilmis'),409
                return jsonify(ok=True,imported=receipt[1],replayed=True)
            # Lease and result are consumed in the same transaction: retries cannot double-count.
            row=conn.execute('''SELECT url FROM brochure_catalogs WHERE url=%s AND lease_id=%s
                AND lease_until>NOW() FOR UPDATE''',(data['url'],data['lease'])).fetchone()
            if not row:return jsonify(ok=False,error='Tarama sahipligi gecersiz'),409
            from brochure_store import save_cards
            save_cards(conn,data['cards'])
            conn.execute('''UPDATE brochure_catalogs SET next_page=%s,pages_read=pages_read+%s,
                cards_read=cards_read+%s,state=%s,lease_id=NULL,lease_until=NULL,
                completed_at=CASE WHEN %s THEN NOW() ELSE NULL END WHERE url=%s''',
                (data['nextPage'],data['pagesRead'],len(data['cards']),data['state'],data['complete'],data['url']))
            conn.execute('INSERT INTO brochure_batch_receipts(lease_id,payload_hash,imported) VALUES(%s,%s,%s)',
                (data['lease'],digest,len(data['cards'])))
        return jsonify(ok=True,imported=len(data['cards']))
    except Exception as error:return database_failure('complete',error,'Tarama sonucu kaydedilemedi')

@queue_api.get('/coverage')
def coverage():
    try:
        with db() as conn:
            initialize(conn)
            rows=conn.execute('''SELECT m.name,COUNT(c.url),MAX(c.last_attempt),COALESCE(SUM(c.pages_read),0),COALESCE(SUM(c.cards_read),0),
                COALESCE(BOOL_OR(c.state='unavailable'),FALSE),MAX(c.completed_at),m.discovery_state,
                (SELECT COUNT(*) FROM brochure_cards bc WHERE split_part(bc.data->>'sourceUrl','/',4)=split_part(m.url,'/',5) AND bc.expires_on>=(NOW() AT TIME ZONE 'Europe/Istanbul')::date AND bc.imported_at>NOW()-INTERVAL '24 hours')
                FROM brochure_merchants m LEFT JOIN brochure_catalogs c ON c.merchant_url=m.url
                AND c.end_date >= (NOW() AT TIME ZONE 'Europe/Istanbul')::date AND c.seen_at>NOW()-INTERVAL '24 hours'
                WHERE m.seen_at>NOW()-INTERVAL '24 hours' GROUP BY m.url,m.name,m.discovery_state ORDER BY m.name''').fetchall()
            priced=sum(r[8]>0 for r in rows)
        merchants=[dict(name=r[0],catalogs=r[1],lastAttempt=r[2].isoformat() if r[2] else None,pagesRead=r[3],cardsRead=r[4],unavailable=r[5],completedAt=r[6].isoformat() if r[6] else None,discoveryState=r[7],indexedCards=r[8]) for r in rows]
        return jsonify(ok=True,source='katalog24.com.tr',discoveredMerchants=len(rows),activeMerchants=sum(r[1]>0 for r in rows),attemptedMerchants=sum(r[2] is not None for r in rows),pricedMerchants=priced,merchants=merchants,exhaustive=False)
    except Exception as error:return database_failure('coverage',error,'Kapsama bilgisi alinamadi')
