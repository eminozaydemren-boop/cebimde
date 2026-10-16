const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('web/app.js','utf8');
const syncCode=source.slice(source.indexOf("const HUNT_KEY="),source.indexOf('function mountHuntControls'));
function setup(fetch){
 const storage=new Map();
 const ctx=vm.createContext({fetch,console,crypto:require('node:crypto').webcrypto,AbortSignal,Uint8Array,URL,Date,
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},renderHuntList(){}});
 vm.runInContext(syncCode+';globalThis.api={readHunts,writeHunts,syncHunts};',ctx);
 return ctx.api;
}
const response=d=>({ok:true,json:async()=>d});
const base={id:'www.hepsiburada.com/a',url:'https://www.hepsiburada.com/a',title:'Product',target:100,revision:'one',dirty:true,lastPrice:150,lastChecked:new Date().toISOString()};
function server(){
 let rows=[];
 return {get rows(){return rows},async fetch(url,opts={}){
  if(url.endsWith('/status'))return response({ok:true});
  if(opts.method==='POST'){
   const p=JSON.parse(opts.body);rows=[{...p,id:'server-id',lastPrice:null,lastChecked:null}];return response({ok:true,id:'server-id'});
  }
  return response({ok:true,watches:rows});
 }};
}
test('save keeps server ID and local price when server price is not yet known',async()=>{
 const remote=server();const api=setup(remote.fetch);api.writeHunts([base]);
 assert.equal(await api.syncHunts(),true);
 const saved=api.readHunts()[0];assert.equal(saved.serverId,'server-id');assert.equal(saved.dirty,false);assert.equal(saved.lastPrice,150);
});
test('edits during a slow request survive and are flushed by the next synchronization pass',async()=>{
 const remote=server();let release,entered;
 const waiting=new Promise(r=>entered=r);let delay=true;
 const api=setup(async(url,opts)=>{if(opts?.method==='POST'&&delay){delay=false;entered();await new Promise(r=>release=r);}return remote.fetch(url,opts);});
 api.writeHunts([base]);const first=api.syncHunts();await waiting;
 api.writeHunts([{...base,target:80,revision:'two'}]);const second=api.syncHunts();release();
 await Promise.all([first,second]);
 assert.equal(api.readHunts()[0].target,80);assert.equal(remote.rows[0].target,80);assert.equal(api.readHunts()[0].dirty,false);
});
test('failed synchronization keeps dirty edit and existing server ID for retry/deletion',async()=>{
 const api=setup(async()=>{throw Error('offline')});api.writeHunts([{...base,serverId:'server-id'}]);
 assert.equal(await api.syncHunts(),false);const saved=api.readHunts()[0];assert.equal(saved.serverId,'server-id');assert.equal(saved.dirty,true);assert.equal(saved.target,100);
});
test('more than thirty existing local watches are not silently discarded',()=>{
 const api=setup(async()=>{});api.writeHunts(Array.from({length:40},(_,i)=>({...base,id:String(i)})));assert.equal(api.readHunts().length,40);
});
