"""Public-runner OCR ingestion: short-lived OIDC, no saved credentials/artifacts."""
import json,os,time,urllib.request,urllib.parse,urllib.error
from brochure_reader import discover_catalogs,scan_catalog
BASE='https://cebimde.onrender.com'

def call(url,token=None,data=None):
    headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    body=None
    if data is not None:
        body=json.dumps(data,ensure_ascii=False).encode();headers['Content-Type']='application/json'
    with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers),timeout=25) as r:return json.load(r)

# A fixed public index, not product/price fixtures. Catalogs and images are discovered anew.
urls=discover_catalogs('https://katalog24.com.tr/anpa-gross')
cards=[]
for url in urls:
    cards.extend(scan_catalog(url))
    print(json.dumps({'catalogsRead':urls.index(url)+1,'cardsRead':len(cards)}),flush=True)
if not cards:raise SystemExit('No current campaign cards could be read; existing data retained.')
for attempt in range(16):
    try:
        if call(BASE+'/health').get('brochureReading')==1:break
    except (urllib.error.URLError,TimeoutError,ValueError):pass
    if attempt==15:raise SystemExit('Brochure deployment unavailable; no import attempted.')
    time.sleep(15)
url=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience='+urllib.parse.quote(BASE+'/price-watch',safe='')
oidc=call(url,token=os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN'])['value']
print('::add-mask::'+oidc,flush=True)
result=call(BASE+'/api/brochures/import',token=oidc,data={'cards':cards})
if not result.get('ok'):raise SystemExit('Brochure import failed.')
print(json.dumps({'imported':result.get('imported',0)}))
