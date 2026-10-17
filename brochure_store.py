"""Dated, conditional brochure prices. Kept separate from online offers and watches."""
import json,math,re,hashlib
from datetime import date,datetime,timezone
from urllib.parse import urlparse
from flask import Blueprint,request,jsonify
from product_data import normalized_title,variant_signature
from watch_store import db

brochure_api=Blueprint('brochure_api',__name__,url_prefix='/api/brochures')

def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS brochure_cards (
      id TEXT PRIMARY KEY, data JSONB NOT NULL, expires_on DATE NOT NULL,
      imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS brochure_expiry_idx ON brochure_cards(expires_on)')
    conn.execute("ALTER TABLE brochure_cards ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS brochure_image_idx ON brochure_cards((data->>'imageUrl'))")

def valid_card(card,today=None):
    today=today or datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Istanbul')).date()
    if not isinstance(card,dict):return False
    try:
        start=date.fromisoformat(card['startDate']);end=date.fromisoformat(card['endDate'])
        price=card['price'];region=card['region']
        return (start<=today<=end and (end-start).days<=60
            and type(price) in (int,float) and math.isfinite(price) and 0<price<100000
            and isinstance(region,list) and len(region)==4 and all(type(x) in (int,float) and 0<=x<=1 for x in region)
            and region[0]<region[2] and region[1]<region[3]
            and all(isinstance(card.get(k),str) and 0<len(card[k])<=limit for k,limit in [('title',250),('text',1500),('campaign',250),('scope',250),('merchant',100)])
            and urlparse(card['sourceUrl']).scheme=='https' and urlparse(card['sourceUrl']).hostname=='katalog24.com.tr'
            and urlparse(card['imageUrl']).scheme=='https' and urlparse(card['imageUrl']).hostname=='priserocdn.com'
            and re.fullmatch(r'[a-f0-9]{64}',card['imageSha256']) is not None)
    except (ValueError,TypeError,KeyError):return False

def match_card(base,card):
    # Match the printed heading, not stray text elsewhere on the page/another card.
    title=normalized_title(base.get('title'));other=normalized_title(card.get('title'))
    pack_a=variant_signature(title)[1];pack_b=variant_signature(other)[1]
    if pack_a or pack_b:
        if not pack_a or not pack_b or pack_a!=pack_b:return False
    else:
        from product_data import same_product
        return same_product(base,{'title':card.get('title')})
    a=set(re.findall(r'[a-z]{3,}',title));b=set(re.findall(r'[a-z]{3,}',other))
    a-= {'adet','rulo'};b-= {'adet','rulo'}
    brand=normalized_title(base.get('brand')) or (title.split()[0] if title else '')
    # Require brand plus two descriptive words; a pack count alone never matches.
    def close(word,target):
        if word==target:return True
        if min(len(word),len(target))<5 or abs(len(word)-len(target))>1:return False
        # One OCR character error, only for descriptive words; brand stays exact.
        if len(word)==len(target):return sum(x!=y for x,y in zip(word,target))==1
        short,long=(word,target) if len(word)<len(target) else (target,word)
        return any(long[:i]+long[i+1:]==short for i in range(len(long)))
    matched={word for word in b if any(close(word,target) for target in a)}
    return bool(brand and brand in other and len(matched)>=3 and b<=matched)

def find_brochures(base):
    if not __import__('os').getenv('DATABASE_URL'):return []
    try:
        with db() as conn:
            initialize(conn)
            needle=(normalized_title(base.get('brand')) or normalized_title(base.get('title')).split(' ')[0])
            rows=conn.execute("SELECT data,imported_at FROM brochure_cards WHERE expires_on >= (NOW() AT TIME ZONE 'Europe/Istanbul')::date AND imported_at >= NOW()-INTERVAL '24 hours' AND (search_text LIKE %s OR search_text='') ORDER BY imported_at DESC LIMIT 5000",('%'+needle+'%',)).fetchall()
        found=[]
        for card,at in rows:
            if valid_card(card) and match_card(base,card):
                found.append(dict(card,readAt=at.isoformat(),identityConfirmed=False,priceKind='brochure',currency='TRY',conditions='Şube, tarih ve stok koşulları geçerlidir. Ürün varyantını broşür görselinden kontrol et.'))
        unique={}
        for c in found:
            key=(c['imageUrl'],c['price'],variant_signature(c['title'])[1])
            unique.setdefault(key,c)
        return sorted(unique.values(),key=lambda x:x['price'])[:12]
    except Exception:return []

@brochure_api.post('/import')
def import_cards():
    from monitor_auth import authorized
    if not authorized(request.headers.get('Authorization','')):return jsonify(ok=False,error='Yetkisiz'),401
    if request.content_length is None or request.content_length>6_000_000:return jsonify(ok=False,error='Veri boyutu gecersiz'),413
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or not isinstance(data.get('cards'),list) or len(data['cards'])>5000:return jsonify(ok=False),400
    cards=data['cards']
    if any(not valid_card(c) for c in cards):return jsonify(ok=False,error='Brosur verisi gecersiz'),400
    try:
        with db() as conn:
            initialize(conn)
            save_cards(conn,cards)
            conn.execute('DELETE FROM brochure_cards WHERE expires_on < CURRENT_DATE-7')
        return jsonify(ok=True,imported=len(cards))
    except Exception:return jsonify(ok=False,error='Brosur kaydedilemedi'),503


def save_cards(conn,cards):
    # A changed source image supersedes prices read from its earlier image bytes.
    images={c['imageUrl']:c['imageSha256'] for c in cards}
    for image,digest in images.items():
        conn.execute("DELETE FROM brochure_cards WHERE data->>'imageUrl'=%s AND data->>'imageSha256'<>%s",(image,digest))
    for card in cards:
        # Only retain documented public product/campaign fields.
        item={k:card[k] for k in ('title','text','price','region','startDate','endDate','campaign','scope','merchant','sourceUrl','imageUrl','imageSha256')}
        ident=hashlib.sha256((item['imageUrl']+str(item['region'])).encode()).hexdigest()
        conn.execute('''INSERT INTO brochure_cards(id,data,expires_on,search_text) VALUES(%s,%s::jsonb,%s,%s)
            ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,expires_on=EXCLUDED.expires_on,imported_at=NOW(),search_text=EXCLUDED.search_text''',(ident,json.dumps(item),item['endDate'],normalized_title(item['title'])))
