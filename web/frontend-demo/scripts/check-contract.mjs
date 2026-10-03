// 화면 ↔ Privacy Lens 서버 계약 검사. 서버 없이 가짜 fetch 로 돈다.
// 픽스처의 report 는 실제 서버(/analyze)가 낸 응답을 그대로 옮긴 것이다(OCR 은 ScriptedBackend).
import assert from 'node:assert/strict';
import '../dist/core.js';
import '../dist/api.js';
const C=globalThis.PrivacyLensCore,A=globalThis.PrivacyLensAPI;
let count=0;
async function test(name,fn){await fn();count++;console.log('PASS '+name);}

// ---------------------------------------------------------------- 좌표
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

// ---------------------------------------------------------------- 서버 결과 → 화면
const report={"width":400,"height":320,"findings":[
  {"kind":"mobile","box":{"x":20,"y":126,"w":260,"h":24,"poly":[[20,126],[280,130],[279,154],[19,150]]},"certainty":"read","certainty_label":"내용 확인됨","severity":"cover","severity_label":"가림 권장","message":"'연락처' 주변에서 휴대전화번호가 인식됨","evidence_text":"010-5179-2931","group_id":"g0","context_words":["연락처"],"detail":{}},
  {"kind":"name","box":{"x":105,"y":77,"w":79,"h":35},"certainty":"read","certainty_label":"내용 확인됨","severity":"cover","severity_label":"가림 권장","message":"'받는분' 주변에서 이름으로 보이는 문자열이 인식됨","evidence_text":"박민준","group_id":"g0","context_words":["받는분"],"detail":{}},
  {"kind":"service_line","box":{"x":20,"y":270,"w":200,"h":22},"certainty":"partial","certainty_label":"일부만 인식됨","severity":"info","severity_label":"참고","message":"대표번호가 인식됨","evidence_text":"1577-1234","group_id":"g1","context_words":[],"detail":{}},
  {"kind":"qr","box":{"x":390,"y":300,"w":20,"h":30},"certainty":"read","certainty_label":"내용 확인됨","severity":"review","severity_label":"검토 권장","message":"QR코드에 웹주소가 들어 있음","evidence_text":null,"group_id":null,"context_words":[],"detail":{"payload_kind":"url","host":"trace.example.co.kr"}},
  {"kind":"address_unit","box":{"x":10,"y":10,"w":40,"h":20},"certainty":"region","certainty_label":"내용 확인 불가","severity":"review","severity_label":"검토 권장","message":"문서 또는 카드로 추정되는 영역이 있으나 글자가 흐려 내용을 확인하지 못했습니다","evidence_text":null,"group_id":null,"context_words":[],"detail":{}},
  {"kind":"long_digits","box":{"x":500,"y":10,"w":40,"h":20},"certainty":"read","certainty_label":"내용 확인됨","severity":"info","severity_label":"참고","message":"긴 자릿수의 숫자가 인식됨","evidence_text":"123","group_id":null,"context_words":[],"detail":{}},
  {"kind":"gps","box":null,"certainty":"read","certainty_label":"내용 확인됨","severity":"cover","severity_label":"가림 권장","message":"사진 파일에 촬영 위치 좌표가 포함됨 (37.27500, 127.00417)","evidence_text":null,"group_id":null,"context_words":[],"detail":{"lat":37.275,"lon":127.00417}}],
  "groups":[{"group_id":"g0","box":{"x":20,"y":77,"w":260,"h":73},"kinds":["name","mobile"],"message":"같은 영역 안에서 이름으로 보이는 문자열, 휴대전화번호가 함께 노출됨. 서로 연결할 수 있는 상태입니다","severity":"cover","severity_label":"가림 권장"}],
  "elapsed_ms":132,"ocr_backend":"paddleocr 3.7.0 · PP-OCRv6_medium_det + korean_PP-OCRv5_mobile_rec","notes":[]};
const result=C.fromReport(report);
const byKind=k=>result.regions.find(r=>r.finding===k);
await test('report dimensions and backend kept',()=>{assert.equal(result.width,400);assert.equal(result.height,320);assert.match(result.backend,/PP-OCRv6/);assert.equal(result.elapsedMs,132);});
await test('every boxed finding becomes a region, gps does not',()=>{assert.equal(result.regions.length,5);assert.ok(!result.regions.some(r=>r.finding==='gps'));});
await test('nothing is selected by default',()=>assert.ok(result.regions.every(r=>r.enabled===false)));
await test('severity and certainty carried',()=>{const p=byKind('service_line');assert.equal(p.severity,'info');assert.equal(p.certainty,'partial');assert.equal(p.certaintyLabel,'일부만 인식됨');});
await test('kind maps to type and label',()=>{assert.equal(byKind('mobile').type,'PHONE');assert.equal(byKind('mobile').label,'휴대전화번호');assert.equal(byKind('name').type,'NAME');assert.equal(byKind('qr').type,'BARCODE');});
await test('server message becomes the reason, recognized text the preview',()=>{assert.equal(byKind('name').reason,"'받는분' 주변에서 이름으로 보이는 문자열이 인식됨");assert.equal(byKind('name').text,'박민준');});
await test('unreadable text is never invented',()=>assert.equal(byKind('address_unit').text,'내용을 확인하지 못했어요'));
await test('QR link host shown, path hidden',()=>{assert.match(byKind('qr').text,/trace\.example\.co\.kr/);assert.ok(!/\/t\//.test(byKind('qr').text));});
await test('box slightly past the edge is clipped, not rejected',()=>{const q=byKind('qr');assert.ok(q.x+q.w<=1+1e-12&&q.y+q.h<=1+1e-12);});
await test('box entirely outside is dropped',()=>assert.equal(byKind('long_digits'),undefined));
await test('tilted outline normalized',()=>{const m=byKind('mobile');assert.equal(m.poly.length,4);assert.deepEqual(m.poly[1],[280/400,130/320]);assert.equal(byKind('name').poly,null);});
await test('groups and gps surfaced',()=>{assert.equal(result.groups.length,1);assert.match(result.groups[0],/함께 노출됨/);assert.equal(result.gps.length,1);assert.match(result.gps[0].message,/위치 좌표/);});
await test('partial flag when any reading is uncertain',()=>assert.equal(result.partial,true));
await test('malformed report rejected',()=>{assert.throws(()=>C.fromReport({width:10,height:10}));assert.throws(()=>C.fromReport({...report,width:0}));});

// ---------------------------------------------------------------- 화면 → 서버
const state={width:400,height:320,style:'blur',regions:result.regions.map(r=>({...r}))};
await test('only selected regions are sent',()=>{assert.deepEqual(C.boxes(state),[]);state.regions[0].enabled=true;assert.equal(C.boxes(state).length,1);});
await test('box in original pixels as x,y,w,h',()=>{const b=C.boxes({...state,regions:[{...byKind('name'),enabled:true}]})[0];assert.deepEqual({x:b.x,y:b.y,w:b.w,h:b.h},{x:105,y:77,w:79,h:35});assert.equal(b.poly,undefined);});
await test('tilted outline sent back in pixels',()=>{const b=C.boxes({...state,regions:[{...byKind('mobile'),enabled:true}]})[0];assert.deepEqual(b.poly,[[20,126],[280,130],[279,154],[19,150]]);});
await test('payload has style and no recognized text',()=>{const p=C.payload(state);assert.equal(p.style,'blur');assert.ok(!JSON.stringify(p).includes('010-5179'));assert.equal(C.payload({...state,style:'pixel'}).style,'blur');});

// ---------------------------------------------------------------- 통신
const png=new Blob([new Uint8Array([137,80,78,71,13,10,26,10])],{type:'image/png'});
const file=new File([png],'photo.jpg',{type:'image/jpeg'});
const json=body=>new Response(JSON.stringify(body),{headers:{'content-type':'application/json'}});
await test('analyze posts original file, mode and ticket',async()=>{
  const api=A.client('',async(url,o)=>{assert.equal(url,'/analyze');assert.equal(o.method,'POST');assert.equal(o.redirect,'error');
    assert.equal(o.body.get('image').name,'photo.jpg');assert.equal(o.body.get('mode'),'baseline');assert.equal(o.body.get('ticket'),'t-12345678');return json({report,preview:'',preview_scale:1});});
  assert.equal((await api.analyze(file,{mode:'baseline',ticket:'t-12345678'})).report.width,400);
});
await test('preview posts boxes and style',async()=>{
  const boxes=[{x:1,y:2,w:3,h:4}];
  const api=A.client('',async(url,o)=>{assert.equal(url,'/redact/preview');assert.deepEqual(JSON.parse(o.body.get('boxes')),boxes);assert.equal(o.body.get('style'),'solid');return json({preview:'x',preview_scale:1,style:'solid'});});
  assert.equal((await api.preview(file,boxes,'solid')).style,'solid');
});
await test('redact posts boxes, style and ticket',async()=>{
  const api=A.client('',async(url,o)=>{assert.equal(url,'/redact');assert.equal(o.body.get('ticket'),'abc-12345');assert.equal(o.body.get('style'),'blur');return json({file:'',verification:{passed:true}});});
  assert.equal((await api.redact(file,[],'blur',{ticket:'abc-12345'})).verification.passed,true);
});
await test('queue asks with ticket',async()=>{
  const api=A.client('',async(url,o)=>{assert.equal(url,'/queue?ticket=a%20b');assert.equal(o.method,'GET');return json({running:0,waiting:0});});
  await api.queue('a b');
});
await test('cancel is fire-and-forget keepalive',async()=>{
  let seen=null;const api=A.client('',async(url,o)=>{seen={url,o};return json({cancelled:true});});
  api.cancel('t-1');await new Promise(r=>setTimeout(r,0));assert.equal(seen.url,'/queue/cancel?ticket=t-1');assert.equal(seen.o.keepalive,true);
});
await test('server detail message surfaced with status',async()=>{
  const api=A.client('',async()=>new Response(JSON.stringify({detail:'이미지로 읽을 수 없는 파일입니다.'}),{status:400,headers:{'content-type':'application/json'}}));
  await assert.rejects(api.analyze(file),e=>e.status===400&&/읽을 수 없는/.test(e.message));
});
await test('cancelled request reports 409',async()=>{
  const api=A.client('',async()=>new Response(JSON.stringify({detail:'취소된 요청입니다.'}),{status:409,headers:{'content-type':'application/json'}}));
  await assert.rejects(api.analyze(file),e=>e.status===409);
});
await test('HTTP errors without body surfaced',async()=>{const api=A.client('',async()=>new Response('error',{status:500}));await assert.rejects(api.analyze(file),/HTTP 500/);});
await test('wrong content type rejected',async()=>{const api=A.client('',async()=>new Response('<html>',{headers:{'content-type':'text/html'}}));await assert.rejects(api.analyze(file),/JSON/);});
await test('request timeout surfaced',async()=>{const api=A.client('',(_,o)=>new Promise((res,rej)=>o.signal.addEventListener('abort',()=>rej(new DOMException('aborted','AbortError')))),10);await assert.rejects(api.analyze(file),/초과/);});
await test('cancel propagates AbortError',async()=>{const c=new AbortController();const api=A.client('',(_,o)=>new Promise((res,rej)=>{if(o.signal.aborted)rej(new DOMException('cancel','AbortError'));else o.signal.addEventListener('abort',()=>rej(new DOMException('cancel','AbortError')));}));const pending=api.analyze(file,{signal:c.signal});c.abort();await assert.rejects(pending,{name:'AbortError'});});
await test('network failure explained',async()=>{const api=A.client('',async()=>{throw new TypeError('fetch failed');});await assert.rejects(api.analyze(file),/서버에 연결할 수 없어요/);});
await test('tickets are unique',()=>{const s=new Set(Array.from({length:50},()=>A.newTicket()));assert.equal(s.size,50);assert.ok([...s].every(t=>/^[A-Za-z0-9-]{8,64}$/.test(t)));});
console.log('\n'+count+' geometry, report and API checks passed.');
