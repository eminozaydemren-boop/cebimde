const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const prefix=fs.readFileSync('web/app.js','utf8').split("q('#analyze').onclick")[0];
function runner(responses){
 let calls=0;
 const request=vm.runInNewContext(prefix+';requestProduct',{URL,fetch:async()=>({json:async()=>responses[Math.min(calls++,responses.length-1)]}),setTimeout:resolve=>resolve()});
 return {request,calls:()=>calls};
}
test('unavailable search never silently repeats or claims a cold start',async()=>{
 const unavailable={ok:true,product:{searchMode:'open_web',search:{status:'unavailable'}}};
 const ready={ok:true,product:{price:123,searchMode:'open_web',search:{status:'completed'}}};
 const r=runner([unavailable,ready]);const messages=[];
 const result=await r.request('https://seller.com/product','',m=>messages.push(m));
 assert.equal(result.product.search.status,'unavailable');assert.equal(r.calls(),1);assert.equal(messages.length,0);
});
test('existing marketplace results are never retried by free-search recovery',async()=>{
 const r=runner([{ok:true,product:{title:'Product',price:100}}]);
 await r.request('https://www.trendyol.com/product-p-123','',()=>{});assert.equal(r.calls(),1);
});
test('unavailable free search makes one request',async()=>{
 const r=runner([{ok:true,product:{searchMode:'open_web',search:{status:'unavailable'}}}]);
 await r.request('https://seller.com/product','',()=>{});assert.equal(r.calls(),1);
});

test('upstream access failures do not trigger repeated identical searches',async()=>{
 const data={ok:true,product:{searchMode:'open_web',search:{status:'unavailable',attempts:[{kind:'price',state:'upstream_unavailable'}]}}};
 const r=runner([data]);
 await r.request('https://seller.com/product','',()=>{throw Error('Do not retry upstream block');});
 assert.equal(r.calls(),1);
});

test('selected candidates explicitly request the public route',async()=>{
 let requested;
 const request=vm.runInNewContext(prefix+';requestProduct',{URL,fetch:async url=>{requested=url;return {json:async()=>({ok:true,product:{price:100}})}},setTimeout:resolve=>resolve()});
 await request('https://www.hepsiburada.com/product-p-HBCV000TEST','',()=>{},true);
 assert.equal(new URL(requested,'https://cebimde.onrender.com').searchParams.get('mode'),'public');
});

test('every initial merchant link requests free public analysis',async()=>{
 let requested=[];
 const request=vm.runInNewContext(prefix+';requestProduct',{URL,fetch:async url=>{requested.push(url);return {json:async()=>({ok:true,product:{price:100}})}},setTimeout:resolve=>resolve()});
 for(const url of ['https://www.trendyol.com/product-p-123','https://www.avansas.com/example-product','https://new-shop.com/example-product']){
  await request(url,'',()=>{});
 }
 assert.equal(requested.length,3);
 assert.ok(requested.every(url=>new URL(url,'https://cebimde.onrender.com').searchParams.get('mode')==='public'));
});

test('available brochure results render immediately when web search is waking',async()=>{
 const result={ok:true,product:{brochureOffers:[{price:239}],searchMode:'open_web',search:{status:'unavailable'}}};
 const r=runner([result]);
 const returned=await r.request('https://seller.com/product','',()=>{throw Error('Should render available brochure result');});
 assert.equal(r.calls(),1);assert.equal(returned.product.brochureOffers[0].price,239);
});

test('rate limited searches make one request and never announce service wakeup',async()=>{
 const r=runner([{ok:true,product:{searchMode:'open_web',search:{status:'rate_limited',retryAfterSeconds:120}}}]);
 const d=await r.request('https://seller.com/product','',()=>{throw Error('No automatic retry');});
 assert.equal(d.product.search.status,'rate_limited');assert.equal(r.calls(),1);
});

test('analysis button blocks overlapping requests and recovers after failure',async()=>{
 const source=fs.readFileSync('web/app.js','utf8');
 const handler=source.slice(0,source.indexOf('\n\n',source.indexOf("q('#analyze').onclick")));
 const elements={};
 for(const id of ['url','linkstatus','analysis','analyze','productHint'])elements['#'+id]={value:'',textContent:'',disabled:false,classList:{add(){},remove(){}}};
 elements['#url'].value='https://www.trendyol.com/honor/600-pro-p-123456';
 let calls=0,rejectRequest;
 vm.runInNewContext(handler,{URL,document:{querySelector:id=>elements[id]},location:{protocol:'https:'},fetch:()=>{calls++;return new Promise((resolve,reject)=>{rejectRequest=reject});}});
 const first=elements['#analyze'].onclick();
 assert.equal(elements['#analyze'].disabled,true);
 await elements['#analyze'].onclick();assert.equal(calls,1);
 rejectRequest(new Error('offline'));await first;
 assert.equal(elements['#analyze'].disabled,false);
 assert.equal(elements['#analyze'].textContent,'Ürünü analiz et');
});
