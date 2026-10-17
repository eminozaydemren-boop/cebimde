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
test('a waking free search is retried and returns the verified result',async()=>{
 const unavailable={ok:true,product:{searchMode:'open_web',search:{status:'unavailable'}}};
 const ready={ok:true,product:{price:123,searchMode:'open_web',search:{status:'completed'}}};
 const r=runner([unavailable,ready]);const messages=[];
 const result=await r.request('https://seller.com/product','',m=>messages.push(m));
 assert.equal(result.product.price,123);assert.equal(r.calls(),2);assert.equal(messages.length,1);
});
test('existing marketplace results are never retried by free-search recovery',async()=>{
 const r=runner([{ok:true,product:{title:'Product',price:100}}]);
 await r.request('https://www.trendyol.com/product-p-123','',()=>{});assert.equal(r.calls(),1);
});
test('unavailable free search stops after four total attempts',async()=>{
 const r=runner([{ok:true,product:{searchMode:'open_web',search:{status:'unavailable'}}}]);
 await r.request('https://seller.com/product','',()=>{});assert.equal(r.calls(),4);
});

test('selected candidates explicitly request the public route',async()=>{
 let requested;
 const request=vm.runInNewContext(prefix+';requestProduct',{URL,fetch:async url=>{requested=url;return {json:async()=>({ok:true,product:{price:100}})}},setTimeout:resolve=>resolve()});
 await request('https://www.hepsiburada.com/product-p-HBCV000TEST','',()=>{},true);
 assert.equal(new URL(requested,'https://cebimde.onrender.com').searchParams.get('mode'),'public');
});
