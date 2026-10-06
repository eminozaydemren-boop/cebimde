const q=s=>document.querySelector(s);const money=n=>new Intl.NumberFormat('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2}).format(n)+' TL';
function parseLink(raw){try{let u=new URL(raw.trim().match(/^https?:\/\//i)?raw.trim():'https://'+raw.trim()),h=u.hostname.toLowerCase(),source=null,id=null,type=null;if(['amazon.com.tr','www.amazon.com.tr'].includes(h)){source='Amazon TR';let m=u.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/|$)/i);if(m){id=m[1].toUpperCase();type='ASIN'}}else if(['trendyol.com','www.trendyol.com'].includes(h)){source='Trendyol';let m=u.pathname.match(/-p-(\d+)(?:\/|$)/i);if(m){id=m[1];type='Ürün ID'}}else if(['hepsiburada.com','www.hepsiburada.com'].includes(h)){source='Hepsiburada';let m=u.pathname.match(/-p-([A-Za-z0-9_-]+)(?:\/|$)/i);if(m){id=m[1];type='Ürün kodu'}}else if(['n11.com','www.n11.com'].includes(h)){source='n11';let m=u.pathname.match(/-(?:P)?(\d+)(?:\/|$)/i);if(m){id=m[1];type='Ürün ID'}}else return{error:'Bu mağaza henüz desteklenmiyor.'};return{source,id,type}}catch{return{error:'Geçerli bir ürün linki gir.'}}}
q('#analyze').onclick=async()=>{const raw=q('#url').value,r=parseLink(raw),box=q('#linkstatus'),a=q('#analysis');a.classList.add('hidden');if(r.error){box.className='linkstatus error';box.textContent=r.error;box.classList.remove('hidden');return}box.className='linkstatus ok';box.innerHTML=`✓ ${r.source} bağlantısı tanındı${r.id?` · ${r.type}: <b>${r.id}</b>`:''}. Doğrulanabilir kaynak aranıyor…`;box.classList.remove('hidden');if(location.protocol==='file:'){box.className='linkstatus error';box.innerHTML='Canlı doğrulama için <b>start.bat</b> ile aç.';return}try{let res=await fetch('/api/product?url='+encodeURIComponent(raw)),d=await res.json();if(!d.ok)throw new Error(d.error||'Doğrulanabilir veri bulunamadı.');let p=d.product;q('#productTitle').textContent=p.title;q('#sourceName').textContent=p.input_source||r.source;q('#sourceId').textContent=r.id?`${r.type}: ${r.id}`:'Ürün kimliği';q('#confidence').innerHTML='✓<br><small>doğrulandı</small>';let body='';if(p.price){let offers=(p.offers||[]).map((o,i)=>`<article class="${i===0?'best':''}"><div><b>${o.source}</b><span>${i===0?'En düşük doğrulanan teklif':'Doğrulanan teklif'}</span></div><strong>${money(o.price)}</strong><small><a href="${o.url}" target="_blank" rel="noopener">Kaynağı aç</a></small></article>`).join('');body=`<div class="notice success">✓ Ürün kimliği doğrulandı. <b>${(p.offers||[]).length||1} doğrulanmış fiyat kaynağı</b> bulundu.</div>${p.input_price?`<div class="notice">Gönderdiğin mağazadaki doğrulanan fiyat: <b>${money(p.input_price)}</b></div>`:''}${p.savings>0?`<div class="notice success">🎯 <b>AVINI YAKALADIK!</b> <b>${money(p.savings)}</b> daha ucuz.</div>`:''}<div class="offers">${offers||`<article class="best"><div><b>${p.price_source}</b></div><strong>${money(p.price)}</strong></article>`}</div><div class="pricebox"><span>EN DÜŞÜK DOĞRULANAN MALİYET</span><b>${money(p.price)}</b><small>Kampanya/kupon henüz düşülmedi.</small></div>`;}else body=`<div class="notice">⚠️ Ürün tanındı ancak doğrulanabilir güncel fiyat bulunamadı. Fiyat uydurulmadı.</div>`;q('#resultBody').innerHTML=body;if(p.price){mountCostCalculator(p);mountHuntControls(p,raw);updateHuntSnapshot(p,raw)}renderHuntList();box.innerHTML=`✓ ${p.title} doğrulandı${p.price?` · ${money(p.price)}`:''}`;a.classList.remove('hidden');a.scrollIntoView({behavior:'smooth'});}catch(e){box.className='linkstatus error';box.innerHTML=`⚠️ ${e.message} <b>Fiyat uydurulmadı.</b>`;}};


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


// V3.70: Device-local watchlist. This is not a background price monitor.
const HUNT_KEY='cebimde_hunts_v370';
function readHunts(){try{let a=JSON.parse(localStorage.getItem(HUNT_KEY)||'[]');return Array.isArray(a)?a:[]}catch{return []}}
function writeHunts(a){try{localStorage.setItem(HUNT_KEY,JSON.stringify(a.slice(0,30)));return true}catch{return false}}
function huntId(url){try{let u=new URL(url);return u.hostname+u.pathname}catch{return url}}
function updateHuntSnapshot(p,url){
 const id=huntId(url),a=readHunts(),h=a.find(x=>x.id===id);if(!h)return;
 h.lastPrice=Number(p.price);h.lastChecked=new Date().toISOString();
 if(!Array.isArray(h.history))h.history=[];
 if(!h.history.length||h.history[h.history.length-1].price!==h.lastPrice)h.history.push({at:h.lastChecked,price:h.lastPrice});
 h.history=h.history.slice(-30);writeHunts(a);
}
function mountHuntControls(p,url){
 const section=document.createElement('section');section.className='huntsetup';
 section.innerHTML='<h3>🎯 Bu ürün için av başlat</h3><p>Hedef fiyatını belirle. Takip bu tarayıcıda saklanır; fiyat yalnızca ürünü yeniden analiz ettiğinde güncellenir.</p><label>Hedef fiyat (TL) <input id="huntTarget" type="number" min="0.01" step="0.01" placeholder="Örn. 300"></label><button type="button" id="saveHunt">🎯 Avı kaydet</button><div id="huntFeedback" role="status"></div>';
 q('#resultBody').appendChild(section);
 const id=huntId(url),existing=readHunts().find(h=>h.id===id);
 if(existing)section.querySelector('#huntTarget').value=existing.target;
 section.querySelector('#saveHunt').onclick=()=>{
  const target=Number(section.querySelector('#huntTarget').value),feedback=section.querySelector('#huntFeedback');
  if(!Number.isFinite(target)||target<=0){feedback.textContent='Geçerli bir hedef fiyat gir.';return}
  const a=readHunts(),index=a.findIndex(h=>h.id===id),now=new Date().toISOString();
  const entry={id,url,title:p.title,target,lastPrice:Number(p.price),lastChecked:now,history:index>=0?a[index].history:[]};
  if(!entry.history.length||entry.history[entry.history.length-1].price!==entry.lastPrice)entry.history.push({at:now,price:entry.lastPrice});
  entry.history=entry.history.slice(-30);
  if(index>=0)a[index]=entry;else a.unshift(entry);
  feedback.textContent=writeHunts(a)?'✓ Av kaydedildi. Otomatik tarama ve bildirim henüz yok.':'Tarayıcı kaydı başarısız oldu.';
  renderHuntList();
 };
}
function renderHuntList(){
 const el=document.getElementById('huntList');if(!el)return;
 const a=readHunts();el.replaceChildren();
 if(!a.length){el.textContent='Henüz kayıtlı av yok.';return}
 a.forEach(h=>{
  const item=document.createElement('article');item.className='huntitem';
  const title=document.createElement('strong');title.textContent=h.title;
  const detail=document.createElement('div');detail.textContent='Hedef: '+money(h.target)+' · Son görülen: '+money(h.lastPrice);
  const status=document.createElement('div');status.className='huntstate';status.textContent=h.lastPrice<=h.target?'🎯 Son kontrolde hedef yakalandı!':'🎯 Avda · hedefe '+money(h.lastPrice-h.target)+' kaldı';
  const when=document.createElement('small');when.textContent='Son kontrol: '+new Date(h.lastChecked).toLocaleString('tr-TR')+' · Otomatik güncellenmez';
  const actions=document.createElement('div');actions.className='hunbuttons';
  const check=document.createElement('button');check.textContent='Fiyatı yeniden kontrol et';check.onclick=()=>{q('#url').value=h.url;q('#analyze').click();};
  const remove=document.createElement('button');remove.textContent='Avı sil';remove.onclick=()=>{writeHunts(readHunts().filter(x=>x.id!==h.id));renderHuntList()};
  actions.append(check,remove);item.append(title,detail,status,when,actions);el.append(item);
 });
}
renderHuntList();
