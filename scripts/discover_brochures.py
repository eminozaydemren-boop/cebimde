"""Refresh the complete public merchant directory; no fixed retailer list."""
import json
from concurrent.futures import ThreadPoolExecutor
from brochure_reader import discover_directory,merchant_catalogs
from brochure_client import Client,wait_for_deployment

def discover():
    merchants=discover_directory()
    if not merchants:raise RuntimeError('Merchant directory unavailable; existing queue retained')
    def catalogs(m):
        try:
            out=merchant_catalogs(m);m['discoveryState']='read';return out
        except Exception:
            m['discoveryState']='unavailable';return []
    with ThreadPoolExecutor(max_workers=4) as pool:found=list(pool.map(catalogs,merchants))
    rows=list({c['url']:c for batch in found for c in batch}.values())
    return dict(merchants=merchants,catalogs=rows)

if __name__=='__main__':
    payload=discover();wait_for_deployment()
    result=Client().post('/api/brochures/directory',payload)
    print(json.dumps({k:result[k] for k in ('merchants','catalogs')}),flush=True)
