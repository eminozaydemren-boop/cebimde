"""Read fair, leased catalog batches; resume after the free run's bounded budget."""
import json,time
from brochure_reader import scan_batch
from brochure_client import Client,wait_for_deployment

def run():
    wait_for_deployment();client=Client();started=time.monotonic();batches=cards=pages=0
    while time.monotonic()-started<18*60 and batches<160:
        job=client.post('/api/brochures/jobs/claim',{}).get('job')
        if not job:break
        try:result=scan_batch(job['url'],job['page'],3)
        except Exception:result=dict(cards=[],nextPage=1,complete=True,state='unavailable',pagesRead=0)
        result.update(url=job['url'],lease=job['lease'])
        result.pop('pagesTotal',None)
        response=client.post('/api/brochures/jobs/complete',result)
        batches+=1;cards+=response.get('imported',0);pages+=result['pagesRead']
        print(json.dumps(dict(batches=batches,pagesRead=pages,cardsRead=cards)),flush=True)
    print(json.dumps(dict(completed=True,batches=batches,pagesRead=pages,cardsRead=cards)),flush=True)

if __name__=='__main__':run()
