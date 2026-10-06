"""CEBIMDE watch storage. Requires DATABASE_URL (PostgreSQL)."""
import os, json, secrets
from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify

watch_api=Blueprint("watch_api",__name__,url_prefix="/api/watches")

def db():
    import psycopg
    url=os.getenv("DATABASE_URL","")
    if not url: raise RuntimeError("Kalici veritabani baglanmadi (DATABASE_URL).")
    return psycopg.connect(url)

def initialize():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS watch_items (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
          product_url TEXT NOT NULL, target NUMERIC(12,2) NOT NULL,
          last_price NUMERIC(12,2), checked_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS watch_owner_idx ON watch_items(owner)")

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
                rows=conn.execute("""SELECT id,title,product_url,target,last_price,checked_at
                     FROM watch_items WHERE owner=%s ORDER BY created_at DESC LIMIT 100""",(key,)).fetchall()
                return jsonify(ok=True,watches=[dict(id=r[0],title=r[1],url=r[2],
                  target=float(r[3]),lastPrice=float(r[4]) if r[4] is not None else None,
                  lastChecked=r[5].isoformat() if r[5] else None) for r in rows])
            data=request.get_json(silent=True) or {}
            title=str(data.get("title","")).strip()[:250]
            url=str(data.get("url","")).strip()
            try:target=float(data.get("target",0))
            except (ValueError,TypeError):target=0
            if not title or not valid_url(url) or not 0<target<100000000:
                return jsonify(ok=False,error="Urun veya hedef gecersiz."),400
            ident=secrets.token_hex(16)
            conn.execute("""INSERT INTO watch_items(id,owner,title,product_url,target)
                         VALUES(%s,%s,%s,%s,%s)""",(ident,key,title,url,target))
            return jsonify(ok=True,id=ident),201
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
