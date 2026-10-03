import assert from 'node:assert/strict';
import '../dist/core.js';
import '../dist/api.js';
const C=globalThis.PrivacyLensCore,A=globalThis.PrivacyLensAPI;
let count=0;
async function test(name,fn){await fn();count++;console.log('PASS '+name);}
for(const [width,height] of [[1440,1000],[900,1400],[4032,3024],[3024,4032]]) {
  for(const zoom of [.5,1,2,4]) await test('coordinate round trip '+width+'x'+height+' at '+zoom+'x',()=>{
    const rect={left:-73,top:-119,width:420*zoom,height:420*height/width*zoom};
    const expected={x:.27,y:.61};
    const point=C.screenPoint(rect.left+expected.x*rect.width,rect.top+expected.y*rect.height,rect);
    assert.ok(Math.abs(point.x-expected.x)<1e-10);assert.ok(Math.abs(point.y-expected.y)<1e-10);
    const pixels=C.toPixels({x:point.x,y:point.y,w:.18,h:.12},width,height);
    assert.deepEqual(C.toPixels(C.fromPixels(pixels,width,height),width,height),pixels);
    assert.ok(pixels.x+pixels.width<=width&&pixels.y+pixels.height<=height);
  });
}
await test('edge coverage stays in image',()=>assert.deepEqual(C.toPixels({x:.999,y:.999,w:.01,h:.01},1000,500),{x:999,y:499,width:1,height:1}));
await test('screen points clamp outside image',()=>assert.deepEqual(C.screenPoint(-100,300,{left:0,top:0,width:100,height:100}),{x:0,y:1}));
const state={width:1440,height:1000,analysisId:'sample',style:'solid',strength:80,regions:[{id:'keep',type:'ADDRESS',x:.1,y:.2,w:.3,h:.1,enabled:true},{id:'off',x:0,y:0,w:.2,h:.2,enabled:false}]};
await test('only selected final regions are sent',()=>{const p=C.payload(state);assert.equal(p.regions.length,1);assert.deepEqual(p.regions[0].bbox,{x:144,y:200,width:432,height:100});assert.equal(p.coordinate_space,'oriented_original_pixels');assert.equal(p.remove_metadata,true);assert.equal(p.output_format,'png');assert.ok(!JSON.stringify(p).includes('evidence'));});
await test('empty selection explicit',()=>assert.equal(C.payload({...state,regions:[]}).regions.length,0));
const response={status:'completed',coordinate_space:'oriented_original_pixels',width:1440,height:1000,regions:[{id:'r1',type:'NAME',bbox:{x:10,y:20,width:100,height:40},evidence:'테스트',ocr_status:'ok'}]};
await test('server boxes normalize correctly',()=>assert.deepEqual(C.toPixels(C.validateResult(response,1440,1000).regions[0],1440,1000),response.regions[0].bbox));
await test('dimension mismatch rejected',()=>assert.throws(()=>C.validateResult({...response,width:1000},1440,1000)));
await test('coordinate convention mismatch rejected',()=>assert.throws(()=>C.validateResult({...response,coordinate_space:'normalized'},1440,1000)));
await test('duplicate region IDs rejected',()=>assert.throws(()=>C.validateResult({...response,regions:[response.regions[0],response.regions[0]]},1440,1000)));
await test('out-of-bounds API coordinates rejected',()=>assert.throws(()=>C.fromPixels({x:1400,y:0,width:100,height:100},1440,1000)));
await test('NaN coordinates rejected',()=>assert.throws(()=>C.fromPixels({x:NaN,y:0,width:10,height:10},1440,1000)));
await test('partial OCR stays selected',()=>{const r=C.validateResult({...response,status:'partial',regions:[{...response.regions[0],ocr_status:'failed'}]},1440,1000);assert.equal(r.regions[0].enabled,true);assert.equal(r.regions[0].ocrStatus,'failed');});
await test('empty detection result valid',()=>assert.equal(C.validateResult({...response,regions:[]},1440,1000).regions.length,0));
await test('localhost API allowed',()=>assert.equal(C.normalizeEndpoint('http://127.0.0.1:8000/'),'http://127.0.0.1:8000'));
await test('external plaintext API rejected',()=>assert.throws(()=>C.normalizeEndpoint('http://example.com')));
await test('embedded credentials rejected',()=>assert.throws(()=>C.normalizeEndpoint('https://user:secret@example.com')));
const png=new Blob([new Uint8Array([137,80,78,71,13,10,26,10])],{type:'image/png'});
await test('analysis POST contains normalized image',async()=>{
 const api=A.client('http://localhost:8000',async(url,o)=>{assert.equal(url,'http://localhost:8000/api/analyze');assert.equal(o.method,'POST');assert.equal(o.credentials,'omit');assert.equal(o.redirect,'error');assert.ok(o.body.get('image') instanceof Blob);return new Response(JSON.stringify(response),{headers:{'content-type':'application/json'}});});
 assert.deepEqual(await api.analyze(png),response);
});
await test('redaction POST has final payload',async()=>{
 const api=A.client('http://localhost:8000',async(url,o)=>{assert.equal(url,'http://localhost:8000/api/redact');assert.deepEqual(JSON.parse(o.body.get('request')),C.payload(state));assert.ok(o.body.get('image') instanceof Blob);return new Response(png,{headers:{'content-type':'image/png'}});});
 assert.equal((await api.redact(png,C.payload(state))).type,'image/png');
});
await test('HTTP errors surfaced',async()=>{const api=A.client('http://localhost:8000',async()=>new Response('error',{status:500}));await assert.rejects(api.analyze(png),/HTTP 500/);});
await test('wrong analysis content type rejected',async()=>{const api=A.client('http://localhost:8000',async()=>new Response('<html>',{headers:{'content-type':'text/html'}}));await assert.rejects(api.analyze(png),/JSON/);});
await test('invalid processed PNG rejected',async()=>{const api=A.client('http://localhost:8000',async()=>new Response('not a png',{headers:{'content-type':'image/png'}}));await assert.rejects(api.redact(png,C.payload(state)),/PNG/);});
await test('request timeout surfaced',async()=>{const api=A.client('http://localhost:8000',(_,o)=>new Promise((res,rej)=>o.signal.addEventListener('abort',()=>rej(new DOMException('aborted','AbortError')))),10);await assert.rejects(api.analyze(png),/초과/);});
await test('response body timeout surfaced',async()=>{const api=A.client('http://localhost:8000',async(_,o)=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:()=>new Promise((res,rej)=>o.signal.addEventListener('abort',()=>rej(new DOMException('aborted','AbortError'))))}),10);await assert.rejects(api.analyze(png),/초과/);});
await test('cancel propagates AbortError',async()=>{const c=new AbortController();const api=A.client('http://localhost:8000',(_,o)=>new Promise((res,rej)=>{if(o.signal.aborted)rej(new DOMException('cancel','AbortError'));else o.signal.addEventListener('abort',()=>rej(new DOMException('cancel','AbortError')));}));const pending=api.analyze(png,{signal:c.signal});c.abort();await assert.rejects(pending,{name:'AbortError'});});
console.log('\n'+count+' geometry and API checks passed.');
