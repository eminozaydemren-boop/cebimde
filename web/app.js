const q=s=>document.querySelector(s);const money=n=>new Intl.NumberFormat('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2}).format(n)+' TL';
function parseLink(raw){
 try{
  const value=raw.trim();if(!value||/\s/.test(value))return {error:'Tek bir ürünün tam bağlantısını gir.'};
  const u=new URL(/^https?:\/\//i.test(value)?value:'https://'+value);
  const host=u.hostname.toLowerCase(),domain=host.replace(/^www\./,''),path=u.pathname;
  if(!['http:','https:'].includes(u.protocol)||u.username||u.password||(u.port&&u.port!==(u.protocol==='https:'?'443':'80')))return {error:'Geçerli bir HTTPS ürün bağlantısı gir.'};
  u.hash='';u.port='';
  const stores={
   'pazarama.com':{source:'Pazarama',pattern:/-p-([A-Za-z0-9_-]+)(?:\/|$)/i,type:'Ürün kodu'},
   'hepsiburada.com':{source:'Hepsiburada',pattern:/-(?:p|pm)-([A-Za-z0-9_-]+)(?:\/|$)/i,type:'Ürün kodu'},
   'trendyol.com':{source:'Trendyol',pattern:/-p-(\d+)(?:\/|$)/i,type:'Ürün ID'},
   'amazon.com.tr':{source:'Amazon TR',pattern:/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/|$)/i,type:'ASIN'},
   'n11.com':{source:'n11',pattern:/\/urun\/[^/]+-(?:P)?(\d+)(?:\/|$)/i,type:'Ürün ID'}
  };
  const store=stores[domain];
  if(!store){
   if(!host.includes('.')||/\.(local|localhost|internal|test|invalid|example)$/.test(host)||/^[\d.]+$/.test(host))return {error:'Herkese açık bir mağazanın ürün bağlantısını gir.'};
   return {source:host,id:null,type:'Mağaza',url:u.href};
  }
  if(domain==='hepsiburada.com'&&path.toLowerCase().startsWith('/dv/'))return {error:'Bu bir kampanya sayfası. Kampanyadaki bir ürünü açıp o ürünün bağlantısını yapıştır.',pageUrl:u.href,kind:'campaign'};
  const match=path.match(store.pattern);
  if(!match)return {error:'Bu bağlantı tek bir ürün sayfası değil. Listeden bir ürünü açıp ürünün bağlantısını yapıştır.',pageUrl:u.href,kind:'listing'};
  return {source:store.source,id:match[1],type:store.type,url:u.href};
 }catch{return {error:'Geçerli bir ürün linki gir.'}}
}
async function requestProduct(raw,hint,report){
 const url='/api/product?url='+encodeURIComponent(raw)+'&name='+encodeURIComponent(hint);
 for(let attempt=0;attempt<4;attempt++){
  const response=await fetch(url),data=await response.json();
  if(!data.ok||data.product?.searchMode!=='open_web'||data.product?.search?.status!=='unavailable'||attempt===3)return data;
  report('Ürün aranıyor. Ücretsiz arama servisi açılıyor; otomatik yeniden deneniyor…');
  await new Promise(resolve=>setTimeout(resolve,12000));
 }
}
q('#analyze').onclick=async()=>{const r=parseLink(q('#url').value),raw=r.url||q('#url').value,box=q('#linkstatus'),a=q('#analysis');a.classList.add('hidden');if(r.error){box.className='linkstatus error';box.textContent=r.error;if(r.pageUrl){const link=document.createElement('a');link.href=r.pageUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent=r.kind==='campaign'?' Kampanyayı aç ve bir ürün seç':' Sayfayı aç ve bir ürün seç';box.appendChild(link);}box.classList.remove('hidden');return}box.className='linkstatus ok';box.innerHTML=`✓ ${r.source} bağlantısı tanındı${r.id?` · ${r.type}: <b>${r.id}</b>`:''}. Doğrulanabilir kaynak aranıyor…`;box.classList.remove('hidden');if(location.protocol==='file:'){box.className='linkstatus error';box.innerHTML='Canlı doğrulama için <b>start.bat</b> ile aç.';return}try{let d=await requestProduct(raw,q('#productHint')?.value||'',message=>{box.textContent=message});if(!d.ok)throw new Error(d.error||'Doğrulanabilir veri bulunamadı.');let p=d.product;q('#productTitle').textContent=p.title;q('#sourceName').textContent=p.input_source||r.source;q('#sourceId').textContent=r.id?`${r.type}: ${r.id}`:'Ürün kimliği';q('#confidence').innerHTML=p.identityVerified===false?'?<br><small>doğrulanamadı</small>':'✓<br><small>doğrulandı</small>';q('#statusLabel').textContent=p.identityVerified===false?'ÜRÜN BİLGİSİ DOĞRULANAMADI':'ÜRÜN DOĞRULANDI';let body='';if(p.price){let offers=(p.offers||[]).map((o,i)=>`<article class="${i===0?'best':''}"><div><b>${o.source}</b><span>${i===0?'En düşük doğrulanan teklif':'Doğrulanan teklif'}</span></div><strong>${money(o.price)}</strong><small><a href="${o.url}" target="_blank" rel="noopener">Kaynağı aç</a></small></article>`).join('');body=`<div class="notice success">✓ Ürün kimliği doğrulandı. <b>${(p.offers||[]).length||1} doğrulanmış fiyat kaynağı</b> bulundu.</div>${p.input_price?`<div class="notice">Gönderdiğin mağazadaki doğrulanan fiyat: <b>${money(p.input_price)}</b></div>`:''}${p.savings>0?`<div class="notice success">🎯 <b>AVINI YAKALADIK!</b> <b>${money(p.savings)}</b> daha ucuz.</div>`:''}<div class="offers">${offers||`<article class="best"><div><b>${p.price_source}</b></div><strong>${money(p.price)}</strong></article>`}</div><div class="pricebox"><span>EN DÜŞÜK DOĞRULANAN MALİYET</span><b>${money(p.price)}</b><small>Kampanya/kupon henüz düşülmedi.</small></div>`;}else body=`<div class="notice">⚠️ Bu ürün için doğrulanabilir güncel fiyat bulunamadı. ${['unavailable','not_configured'].includes(p.search?.status)?'Web araması şu anda kullanılamıyor. Biraz sonra yeniden dene.':'Ürün adı veya barkod alanını doldurup yeniden deneyebilirsin.'}</div>`;q('#resultBody').innerHTML=body;if(p.price){mountCostCalculator(p);mountHuntControls(p,raw);updateHuntSnapshot(p,raw)}renderHuntList();box.className='linkstatus '+(p.price?'ok':'pending');box.textContent=(p.identityVerified===false?'Arama tamamlandı: ':'✓ ')+p.title+(p.price?' · '+money(p.price):' · Doğrulanmış fiyat bulunamadı');a.classList.remove('hidden');a.scrollIntoView({behavior:'smooth'});}catch(e){box.className='linkstatus error';box.textContent='⚠️ '+e.message+' Fiyat uydurulmadı.';}};


// V3.69: Explicitly user-confirmed checkout adjustments. Never call them
// automatically verified campaigns; do not modify the server's base prices.
function mountCostCalculator(p){
 const host=document.createElement('section');host.className='checkoutcalc';
 host.innerHTML='<h3>🧮 Gerçek ödeme hesabı</h3><p>Seçtiğin mağazanın ödeme ekranındaki tutarları gir. CEBİMDE bu bilgileri otomatik doğrulamaz.</p><label>Mağaza <select id="checkoutStore"></select></label><label>Kargo (TL) <input id="checkoutShipping" type="number" min="0" step="0.01" value="0"></label><label>Uygulanmış kupon (TL) <input id="checkoutCoupon" type="number" min="0" step="0.01" value="0"></label><label>Uygulanmış banka/kart indirimi (TL) <input id="checkoutBank" type="number" min="0" step="0.01" value="0"></label><label class="confirm"><input id="checkoutConfirmed" type="checkbox"> Bu tutarları ödeme ekranında kontrol ettim.</label><div class="checkouttotal" id="checkoutTotal"></div><small>Kupon ve banka indirimi yalnızca bu üründe gerçekten uygulanıyorsa girilmeli. Kart numarası veya hesap bilgisi istenmez. Tutarlar kaydedilmez.</small>';
 q('#resultBody').appendChild(host);
 const sel=host.querySelector('#checkoutStore');
 (p.offers||[]).forEach((o,i)=>{let opt=document.createElement('option');opt.value=i;opt.textContent=o.source+' — '+money(o.price);sel.appendChild(opt)});
 const calc=()=>{
  let offer=(p.offers||[])[Number(sel.value)]||{price:p.price};
  const amount=id=>Math.max(0,Number(host.querySelector(id).value)||0);
  let shipping=amount('#checkoutShipping'),coupon=amount('#checkoutCoupon'),bank=amount('#checkoutBank');
  const confirmed=host.querySelector('#checkoutConfirmed').checked;
  const discount=Math.min(offer.price+shipping,coupon+bank);
  const total=Math.max(0,offer.price+shipping-discount);
  host.querySelector('#checkoutTotal').innerHTML=confirmed?
    '<span>Senin onayladığın ödeme tutarı</span><strong>'+money(total)+'</strong><small>CEBİMDE tarafından bağımsız doğrulanmadı.</small>':
    '<span>Doğrulanmış ürün fiyatı</span><strong>'+money(offer.price)+'</strong><small>Ek avantajlar henüz onaylanmadı; gerçek fiyattan düşülmedi.</small>';
 };
 host.querySelectorAll('input,select').forEach(el=>el.addEventListener('input',calc));
 host.querySelectorAll('input,select').forEach(el=>el.addEventListener('change',calc));calc();
}


// V3.74: Serialized synchronization; local edits survive slow or failed requests.
const HUNT_KEY='cebimde_hunts_v370';
function readHunts(){try{let a=JSON.parse(localStorage.getItem(HUNT_KEY)||'[]');return Array.isArray(a)?a:[]}catch{return []}}
function writeHunts(a){try{localStorage.setItem(HUNT_KEY,JSON.stringify(a));return true}catch{return false}}
function watchKey(){try{let k=localStorage.getItem('cebimde_watch_key');if(!k){let b=new Uint8Array(32);crypto.getRandomValues(b);k=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');localStorage.setItem('cebimde_watch_key',k)}return k}catch{return null}}
async function serverWatch(method,path,body){
 const key=watchKey();if(!key)throw Error('Tarayıcı depolaması kapalı.');
 const res=await fetch('/api/watches'+path,{method,headers:{'Content-Type':'application/json','X-Watch-Key':key},signal:AbortSignal.timeout(15000),body:body?JSON.stringify(body):undefined});
 const d=await res.json();if(!res.ok||!d.ok)throw Error(d.error||'Sunucu kaydı başarısız.');return d;
}
let syncPromise=null,syncRequested=false,monitorLastRun=null;
const deletingHunts=new Set(),checkingHunts=new Set();
function syncHunts(){
 syncRequested=true;
 if(syncPromise)return syncPromise;
 syncPromise=(async()=>{
  try{
   do{
    syncRequested=false;
    const status=await fetch('/api/watches/status',{signal:AbortSignal.timeout(15000)});
    if(!status.ok)throw Error('Sunucu bağlantısı bekleniyor.');
    const readiness=await status.json();monitorLastRun=readiness.monitoring?.lastRun||null;
    const remote=await serverWatch('GET','');
    const byUrl=new Map(remote.watches.map(w=>[huntId(w.url),w]));
    for(const h of readHunts()){
     if(deletingHunts.has(h.id))continue;
     if(h.dirty||!byUrl.has(h.id)){
      const body={url:h.url,title:h.title,target:h.target};
      if(h.snapshotReceipt&&Date.now()-Date.parse(h.lastChecked)<86400000)body.snapshotReceipt=h.snapshotReceipt;
      const saved=await serverWatch('POST','',body);
      const current=readHunts();const item=current.find(x=>x.id===h.id);
      if(item){item.serverId=saved.id;if(item.revision===h.revision){item.dirty=false;delete item.snapshotReceipt;}writeHunts(current);}
     }
    }
    const latest=await serverWatch('GET','');
    // Re-read after every await: user edits may have happened during the request.
    const current=readHunts();
    const merged=latest.watches.map(w=>{
     const id=huntId(w.url),old=current.find(h=>h.id===id)||{};
     const localNewer=old.lastPrice!=null&&(!w.lastChecked||Date.parse(old.lastChecked)>Date.parse(w.lastChecked));
     return {...old,...w,id,serverId:w.id,target:old.dirty?old.target:w.target,
      lastPrice:localNewer?old.lastPrice:w.lastPrice,lastChecked:localNewer?old.lastChecked:w.lastChecked};
    });
    const ids=new Set(merged.map(h=>h.id));
    for(const h of current)if(!ids.has(h.id))merged.push(h);
    writeHunts(merged);renderHuntList();
   }while(syncRequested);
   return true;
  }catch(e){console.info('Avlar cihazda korunuyor:',e.message);return false;}
  finally{syncPromise=null;}
 })();
 return syncPromise;
}
function huntId(url){try{let u=new URL(url);return u.hostname+u.pathname}catch{return url}}
function updateHuntSnapshot(p,url){
 const id=huntId(url),a=readHunts(),h=a.find(x=>x.id===id);if(!h)return;
 h.lastPrice=Number(p.price);h.lastChecked=new Date().toISOString();
 if(!Array.isArray(h.history))h.history=[];
 if(!h.history.length||h.history[h.history.length-1].price!==h.lastPrice)h.history.push({at:h.lastChecked,price:h.lastPrice});
 h.history=h.history.slice(-30);h.snapshotReceipt=p.watchReceipt;h.dirty=true;h.revision=crypto.randomUUID();writeHunts(a);syncHunts();
}
function mountHuntControls(p,url){
 const section=document.createElement('section');section.className='huntsetup';
 section.innerHTML='<h3>🎯 Bu ürün için av başlat</h3><p>Hedef fiyatını belirle. Avın sunucuyla eşitlenir. Güncel fiyat için ürünü yeniden analiz et. Açık mağaza verileri yaklaşık 6 saatte bir taranır. Hedef bildirimi site içinde gösterilir; telefon bildirimi gönderilmez.</p><label>Hedef fiyat (TL) <input id="huntTarget" type="number" min="0.01" step="0.01" placeholder="Örn. 300"></label><button type="button" id="saveHunt">🎯 Avı kaydet</button><div id="huntFeedback" role="status"></div>';
 q('#resultBody').appendChild(section);
 const id=huntId(url),existing=readHunts().find(h=>h.id===id);
 if(existing)section.querySelector('#huntTarget').value=existing.target;
 section.querySelector('#saveHunt').onclick=async()=>{
  const target=Number(section.querySelector('#huntTarget').value),feedback=section.querySelector('#huntFeedback');
  if(!Number.isFinite(target)||target<=0){feedback.textContent='Geçerli bir hedef fiyat gir.';return}
  const a=readHunts(),index=a.findIndex(h=>h.id===id),now=new Date().toISOString();
  const previous=index>=0?a[index]:{};
  const entry={...previous,id,url,title:p.title,target,lastPrice:Number(p.price),lastChecked:now,history:Array.isArray(previous.history)?previous.history:[],snapshotReceipt:p.watchReceipt,dirty:true,revision:crypto.randomUUID()};
  if(!entry.history.length||entry.history[entry.history.length-1].price!==entry.lastPrice)entry.history.push({at:now,price:entry.lastPrice});
  entry.history=entry.history.slice(-30);
  if(index>=0)a[index]=entry;else a.unshift(entry);
  if(!writeHunts(a)){feedback.textContent='Tarayıcı kaydı başarısız oldu.';return;}
  feedback.textContent='✓ Cihazda kaydedildi. Sunucuyla eşitleniyor…';
  renderHuntList();
  const synced=await syncHunts();
  feedback.textContent=synced?'✓ Av ve doğrulanmış fiyat sunucuyla eşitlendi.':'Sunucu bağlantısı bekleniyor; kayıt bu cihazda korundu.';
 };
}
function renderHuntList(){
 const el=document.getElementById('huntList');if(!el)return;
 const a=readHunts();el.replaceChildren();
 if(!a.length){el.textContent='Henüz kayıtlı av yok.';return}
 a.forEach(h=>{
  const item=document.createElement('article');item.className='huntitem';if(h.serverId)item.id='watch-'+h.serverId;
  const title=document.createElement('strong');title.textContent=h.title;
  const detail=document.createElement('div');detail.textContent='Hedef: '+money(h.target)+' · Son görülen: '+(h.lastPrice==null?'Henüz kontrol edilmedi':money(h.lastPrice));
  const status=document.createElement('div');status.className='huntstate';status.textContent=h.lastPrice==null?'🎯 Güncel fiyat kontrolü bekleniyor':h.lastPrice<=h.target?'🎯 Son kontrolde hedef yakalandı!':'🎯 Avda · hedefe '+money(h.lastPrice-h.target)+' kaldı';
  const when=document.createElement('small');when.textContent=(h.lastChecked?'Son kontrol: '+new Date(h.lastChecked).toLocaleString('tr-TR'):'Son kontrol: henüz yok')+' · '+(h.serverId&&!h.dirty?'Sunucuyla eşitlendi':'Cihazda kayıtlı; eşitleme bekleniyor')+' · '+(h.monitorState==='unavailable'?'Son kontrolde fiyat doğrulanamadı':monitorLastRun?'Otomatik tarama etkin':'İlk otomatik tarama bekleniyor');
  const actions=document.createElement('div');actions.className='hunbuttons';
  const check=document.createElement('button');check.textContent='Fiyatı ücretsiz kontrol et';check.disabled=checkingHunts.has(h.id);
  const feedback=document.createElement('small');feedback.className='huntfeedback';feedback.setAttribute('role','status');
  const setFeedback=text=>{const current=readHunts().find(x=>x.id===h.id);const row=current?.serverId?document.getElementById('watch-'+current.serverId):null;(row?.querySelector('.huntfeedback')||feedback).textContent=text;};
  const runCheck=async(sourceUrl)=>{
   if(checkingHunts.has(h.id))return;checkingHunts.add(h.id);
   check.disabled=true;setFeedback('Açık mağaza fiyatı kontrol ediliyor…');
   try{
    await syncHunts();
    const current=readHunts().find(x=>x.id===h.id);
    if(!current?.serverId)throw Error('Av henüz sunucuyla eşitlenmedi.');
    const result=await serverWatch('POST','/'+encodeURIComponent(current.serverId)+'/check',sourceUrl?{sourceUrl}:{});
    const synced=await syncHunts();
    if(!synced)throw Error('Kontrol tamamlandı; sonuçların eşitlenmesi bekleniyor.');
    setFeedback(result.verified?'✓ Güncel fiyat doğrulandı: '+money(result.price):'Güncel fiyat doğrulanamadı; son doğrulanan fiyat korundu.');
   }catch(e){setFeedback(e.message);}
   finally{checkingHunts.delete(h.id);check.disabled=false;const current=readHunts().find(x=>x.id===h.id);const row=current?.serverId?document.getElementById('watch-'+current.serverId):null;row?.querySelectorAll('button').forEach(b=>b.disabled=false);}
  };
  check.onclick=()=>runCheck();
  const remove=document.createElement('button');remove.textContent='Avı sil';remove.onclick=async()=>{
   if(deletingHunts.has(h.id))return;
   deletingHunts.add(h.id);remove.disabled=true;
   try{
    if(syncPromise)await syncPromise;
    const latest=readHunts().find(x=>x.id===h.id);
    if(latest?.serverId)await serverWatch('DELETE','/'+encodeURIComponent(latest.serverId));
    writeHunts(readHunts().filter(x=>x.id!==h.id));renderHuntList();
   }catch(e){alert('Av silinemedi; kayıt korundu. '+e.message);}
   finally{deletingHunts.delete(h.id);remove.disabled=false;}
  };
  actions.append(check,remove);item.append(title,detail,status,when,actions,feedback);
  const sources=document.createElement('details');
  const summary=document.createElement('summary');summary.textContent='Başka mağaza kaynağı ekle';
  const note=document.createElement('small');note.textContent='Aynı ürünün başka bir satıcıdaki bağlantısını ekle. Ürün ve fiyat doğrulanırsa kaydedilir.';
  const input=document.createElement('input');input.type='url';input.placeholder='https://…';input.setAttribute('aria-label','Aynı ürünün mağaza linki');
  const add=document.createElement('button');add.textContent='Kaynağı doğrula';add.disabled=checkingHunts.has(h.id);add.onclick=()=>{if(input.value.trim())runCheck(input.value.trim());};
  sources.append(summary,note,input,add);item.append(sources);
  if(h.notice){
   const notice=document.createElement('div');notice.className='notice success';notice.setAttribute('role','status');
   const message=document.createElement('strong');message.textContent='🎯 Hedef fiyat yakalandı: '+money(h.notice.price);
   const date=document.createElement('small');date.textContent=' '+new Date(h.notice.at).toLocaleString('tr-TR');
   notice.append(message,date);
   if(safeOfferLink(h.notice.url)){
    const link=document.createElement('a');link.href=h.notice.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=' Mağazayı aç';notice.append(link);
   }
   const seen=document.createElement('button');seen.textContent='Bildirimi okudum';seen.onclick=async()=>{
    seen.disabled=true;try{await serverWatch('POST','/'+encodeURIComponent(h.serverId)+'/notice/read',{at:h.notice.at});await syncHunts();}catch(e){seen.disabled=false;alert('Bildirim kaydedilemedi.');}
   };notice.append(seen);item.append(notice);
  }
  el.append(item);
 });
}
renderHuntList();

// Synchronize when PostgreSQL is configured; keep existing local hunts until then.
syncHunts();

// Retry synchronization when connectivity returns; this never queries price providers.
window.addEventListener('online',()=>syncHunts());
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')syncHunts();});

function safeOfferLink(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password}catch{return false}}
// Poll stored results only. This never calls the price API or consumes Reef credits.
setInterval(()=>{if(document.visibilityState==='visible')syncHunts();},60000);
