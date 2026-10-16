const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const code=fs.readFileSync('web/app.js','utf8');
const parse=vm.runInNewContext(code.slice(0,code.indexOf("q('#analyze').onclick"))+';parseLink',{URL});
test('reported campaign is identified before any analysis request',()=>{
 const result=parse('https://www.hepsiburada.com/dv/elektronik-firsatlari?trackingId=21335034');
 assert.equal(result.kind,'campaign');assert.match(result.error,/kampanya sayfası/);assert.equal(result.id,undefined);
});
test('listing and search pages are not product links',()=>{
 for(const url of ['https://www.hepsiburada.com/laptop-c-98','https://www.trendyol.com/sr?q=telefon','https://www.amazon.com.tr/s?k=telefon','https://www.n11.com/arama?q=telefon'])assert.equal(parse(url).kind,'listing');
});
test('all supported product formats still parse',()=>{
 for(const url of ['https://www.hepsiburada.com/urun-p-HBCV000TEST','https://www.hepsiburada.com/urun-pm-HB000TEST','https://www.trendyol.com/marka/urun-p-12345','https://www.amazon.com.tr/dp/B0ABCDE123','https://www.n11.com/urun/unit-ut12d-123456'])assert.ok(parse(url).id,url);
});
test('normalizes a pasted product hostname to HTTPS',()=>{
 assert.equal(parse('www.hepsiburada.com/urun-p-HBCV000TEST').url,'https://www.hepsiburada.com/urun-p-HBCV000TEST');
});
test('rejects unsafe URLs without creating an open-page link',()=>{
 for(const url of ['https://user:pass@www.hepsiburada.com/urun-p-HBCV000TEST','https://www.hepsiburada.com:8080/urun-p-HBCV000TEST','https://hepsiburada.com.evil.test/urun-p-HBCV000TEST']){const result=parse(url);assert.ok(result.error);assert.equal(result.pageUrl,undefined);}
});
