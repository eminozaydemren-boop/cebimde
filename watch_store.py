"""CEBIMDE watch storage. Requires DATABASE_URL (PostgreSQL)."""
import os, json, secrets, math, hashlib
from itsdangerous import URLSafeTimedSerializer, BadData
from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify

watch_api=Blueprint("watch_api",__name__,url_prefix="/api/watches")

def db():
    import psycopg
    url=os.getenv("DATABASE_URL","")
    if not url: raise RuntimeError("Kalici veritabani baglanmadi (DATABASE_URL).")
    return psycopg.connect(url, connect_timeout=5)

def snapshot_signer():
    secret=os.getenv('WATCH_SIGNING_SECRET') or os.getenv('DATABASE_URL')
    if not secret:return None
    return URLSafeTimedSerializer(hashlib.sha256(secret.encode()).hexdigest(),salt='cebimde-price-v1')

def sign_snapshot(url, price, base=None, offers=None):
    signer=snapshot_signer()
    if not signer or not isinstance(price,(int,float)) or not math.isfinite(price) or not 0<price<100000000:
        return None
    from price_monitor import metadata
    return signer.dumps(dict(url=url,price=price,at=datetime.now(timezone.utc).isoformat(),monitor=metadata(base,offers,url)))

def read_snapshot(receipt,url):
    if not receipt:return None,None
    if not isinstance(receipt,str) or len(receipt)>16000:raise ValueError('Fiyat kaydi gecersiz.')
    signer=snapshot_signer()
    if not signer:raise ValueError('Fiyat kaydi dogrulanamadi.')
    try:
        data=signer.loads(receipt,max_age=86400)
        price=float(data['price'])
        at=datetime.fromisoformat(data['at'])
        if data['url']!=url or not math.isfinite(price) or not 0<price<100000000 or at.tzinfo is None:
            raise ValueError()
        return price,at
    except (BadData,ValueError,TypeError,KeyError):
        raise ValueError('Fiyat kaydi gecersiz veya suresi dolmus.')

def initialize():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS watch_items (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
          product_url TEXT NOT NULL, target NUMERIC(12,2) NOT NULL,
          last_price NUMERIC(12,2), checked_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        conn.execute("""ALTER TABLE watch_items
          ADD COLUMN IF NOT EXISTS monitor_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN IF NOT EXISTS last_attempt TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS monitor_state TEXT NOT NULL DEFAULT 'pending',
          ADD COLUMN IF NOT EXISTS hit_active BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS notice_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS notice_price NUMERIC(12,2),
          ADD COLUMN IF NOT EXISTS notice_url TEXT,
          ADD COLUMN IF NOT EXISTS notice_read_at TIMESTAMPTZ""")
        conn.execute("""CREATE TABLE IF NOT EXISTS watch_monitor_status (
          id INTEGER PRIMARY KEY CHECK (id=1), last_run TIMESTAMPTZ NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS watch_owner_idx ON watch_items(owner)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS watch_owner_url_idx ON watch_items(owner,product_url)")

def owner():
    key=request.headers.get("X-Watch-Key","")
    if len(key)<32 or len(key)>128 or not all(c in "0123456789abcdef" for c in key.lower()):
        return None
    return key

def valid_url(value):
    try:
        u=urlparse(value)
        return u.scheme=="https" and u.hostname in {
          "hepsiburada.com","www.hepsiburada.com","trendyol.com","www.trendyol.com",
          "n11.com","www.n11.com","amazon.com.tr","www.amazon.com.tr"}
    except Exception:return False

@watch_api.route("",methods=["GET","POST"])
def collection():
    key=owner()
    if not key:return jsonify(ok=False,error="Tarayici av anahtari gerekli."),401
    try:
        initialize()
        with db() as conn:
            if request.method=="GET":
                rows=conn.execute("""SELECT id,title,product_url,target,last_price,checked_at,last_attempt,monitor_state,notice_at,notice_price,notice_url,notice_read_at
                     FROM watch_items WHERE owner=%s ORDER BY created_at DESC LIMIT 100""",(key,)).fetchall()
                return jsonify(ok=True,watches=[dict(id=r[0],title=r[1],url=r[2],
                  target=float(r[3]),lastPrice=float(r[4]) if r[4] is not None else None,
                  lastChecked=r[5].isoformat() if r[5] else None,
                  lastAttempt=r[6].isoformat() if r[6] else None,monitorState=r[7],
                  notice=dict(at=r[8].isoformat(),price=float(r[9]),url=r[10])
                    if r[8] and r[9] is not None and (r[11] is None or r[11]<r[8]) else None) for r in rows])
            data=request.get_json(silent=True) or {}
            if not isinstance(data,dict):
                return jsonify(ok=False,error="Kayit bir nesne olmali."),400
            title=str(data.get("title","")).strip()[:250]
            url=str(data.get("url","")).strip()
            try:target=float(data.get("target",0))
            except (ValueError,TypeError):target=0
            if not title or not valid_url(url) or not 0<target<100000000:
                return jsonify(ok=False,error="Urun veya hedef gecersiz."),400
            try:price,checked=read_snapshot(data.get('snapshotReceipt'),url)
            except ValueError as e:return jsonify(ok=False,error=str(e)),400
            meta=snapshot_signer().loads(data['snapshotReceipt'],max_age=86400).get('monitor',{}) if data.get('snapshotReceipt') else {}
            ident=secrets.token_hex(16)
            row=conn.execute("""INSERT INTO watch_items(id,owner,title,product_url,target,last_price,checked_at,monitor_meta)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (owner,product_url) DO UPDATE
                SET title=EXCLUDED.title,target=EXCLUDED.target,
                hit_active=CASE WHEN watch_items.target<>EXCLUDED.target THEN FALSE ELSE watch_items.hit_active END,
                monitor_meta=CASE WHEN EXCLUDED.monitor_meta<>'{}'::jsonb AND
                  (watch_items.checked_at IS NULL OR EXCLUDED.checked_at>=watch_items.checked_at)
                  THEN EXCLUDED.monitor_meta ELSE watch_items.monitor_meta END,
                last_price=CASE WHEN EXCLUDED.checked_at IS NOT NULL AND
                  (watch_items.checked_at IS NULL OR EXCLUDED.checked_at>watch_items.checked_at)
                  THEN EXCLUDED.last_price ELSE watch_items.last_price END,
                checked_at=CASE WHEN EXCLUDED.checked_at IS NOT NULL AND
                  (watch_items.checked_at IS NULL OR EXCLUDED.checked_at>watch_items.checked_at)
                  THEN EXCLUDED.checked_at ELSE watch_items.checked_at END
                RETURNING id""",(ident,key,title,url,target,price,checked,json.dumps(meta))).fetchone()
            return jsonify(ok=True,id=row[0]),200
    except Exception as e:
        if isinstance(e,RuntimeError):return jsonify(ok=False,error=str(e)),503
        return jsonify(ok=False,error="Veritabani islemi basarisiz."),503

@watch_api.route("/<watch_id>",methods=["DELETE"])
def delete(watch_id):
    key=owner()
    if not key:return jsonify(ok=False,error="Av anahtari gerekli."),401
    try:
        initialize()
        with db() as conn:
            conn.execute("DELETE FROM watch_items WHERE id=%s AND owner=%s",(watch_id,key))
        return jsonify(ok=True)
    except Exception:return jsonify(ok=False,error="Veritabani erisilemiyor."),503

@watch_api.route("/status",methods=["GET"])
def status():
    if not os.getenv("DATABASE_URL"):
        return jsonify(ok=False,configured=False,message="PostgreSQL baglantisi bekleniyor."),503
    try:
        initialize()
        with db() as conn:
            row=conn.execute('SELECT last_run FROM watch_monitor_status WHERE id=1').fetchone()
        return jsonify(ok=True,configured=True,message="Kalici veritabani hazir.",
                       monitoring=dict(mode='public_structured_data',intervalHours=6,lastRun=row[0].isoformat() if row else None))
    except Exception:
        return jsonify(ok=False,configured=True,message="Veritabani baglantisi dogrulanamadi."),503


@watch_api.post('/<watch_id>/notice/read')
def read_notice(watch_id):
    key=owner()
    if not key:return jsonify(ok=False,error='Av anahtari gerekli.'),401
    data=request.get_json(silent=True) or {}
    try:
        if not isinstance(data,dict):raise ValueError()
        at=datetime.fromisoformat(str(data.get('at','')))
        if at.tzinfo is None:raise ValueError()
    except (ValueError,TypeError):return jsonify(ok=False,error='Bildirim tarihi gecersiz.'),400
    try:
        initialize()
        with db() as conn:
            conn.execute('UPDATE watch_items SET notice_read_at=NOW() WHERE id=%s AND owner=%s AND notice_at=%s',(watch_id,key,at))
        return jsonify(ok=True)
    except Exception:return jsonify(ok=False,error='Bildirim kaydedilemedi.'),503

@watch_api.post('/monitor/run')
def monitor_run():
    from monitor_auth import authorized
    if not authorized(request.headers.get('Authorization','')):
        return jsonify(ok=False,error='Yetkisiz tarama istegi.'),401
    from price_monitor import check_watch,should_notify
    try:
        initialize()
        with db() as conn:
            locked=conn.execute('SELECT pg_try_advisory_xact_lock(74137501)').fetchone()[0]
            if not locked:return jsonify(ok=True,processed=0,busy=True)
            conn.execute('INSERT INTO watch_monitor_status(id,last_run) VALUES(1,NOW()) ON CONFLICT(id) DO UPDATE SET last_run=EXCLUDED.last_run')
            row=conn.execute("""SELECT id,title,product_url,target,monitor_meta,hit_active,notice_price
                FROM watch_items WHERE last_attempt IS NULL OR last_attempt<NOW()-INTERVAL '6 hours'
                ORDER BY last_attempt ASC NULLS FIRST,created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
            if not row:return jsonify(ok=True,processed=0)
            ident,title,url,target,meta,hit_active,notice_price=row
            result=check_watch(title,url,meta)
            if result:
                notify=should_notify(result['price'],float(target),hit_active,notice_price)
                conn.execute("""UPDATE watch_items SET last_attempt=NOW(),monitor_state='verified',
                    last_price=%s,checked_at=NOW(),hit_active=%s,
                    notice_at=CASE WHEN %s THEN NOW() ELSE notice_at END,
                    notice_price=CASE WHEN %s THEN %s ELSE notice_price END,
                    notice_url=CASE WHEN %s THEN %s ELSE notice_url END
                    WHERE id=%s""",(result['price'],result['price']<=float(target),notify,
                                     notify,result['price'],notify,result['url'],ident))
                return jsonify(ok=True,processed=1,verified=1,notifications=int(notify))
            conn.execute("UPDATE watch_items SET last_attempt=NOW(),monitor_state='unavailable' WHERE id=%s",(ident,))
            return jsonify(ok=True,processed=1,verified=0,notifications=0)
    except Exception:
        return jsonify(ok=False,error='Otomatik tarama tamamlanamadi.'),503
