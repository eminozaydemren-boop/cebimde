"""Repository-bound, short-lived OIDC client; never persists credentials."""
import json,os,time,urllib.request,urllib.parse,urllib.error
BASE='https://cebimde.onrender.com'

def call(url,token=None,data=None):
    headers={'Accept':'application/json'};body=None
    if token:headers['Authorization']='Bearer '+token
    if data is not None:body=json.dumps(data,ensure_ascii=False).encode();headers['Content-Type']='application/json'
    with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers),timeout=30) as r:return json.load(r)

class Client:
    def __init__(self):self.token=None;self.minted=0
    def post(self,path,data):
        if time.monotonic()-self.minted>150 or not self.token:
            url=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience='+urllib.parse.quote(BASE+'/price-watch',safe='')
            self.token=call(url,token=os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN'])['value']
            print('::add-mask::'+self.token,flush=True);self.minted=time.monotonic()
        result=call(BASE+path,token=self.token,data=data)
        if not result.get('ok'):raise RuntimeError('Brochure API request failed')
        return result

def wait_for_deployment():
    for attempt in range(16):
        try:
            if call(BASE+'/health').get('brochureDiscovery')==1:return
        except (urllib.error.URLError,TimeoutError,ValueError):pass
        if attempt==15:raise RuntimeError('Brochure discovery deployment not available')
        time.sleep(15)
