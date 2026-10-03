// 화면 정적 검사: 문법, 요소 참조, 자산, 파일 형식 판별, 샘플 문서, 반응형.
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const [app,api,html,css]=await Promise.all(['app.js','api.js','index.html','styles.css'].map(file=>readFile(path.join(root,'dist',file),'utf8')));
const checks=(()=>{
const results = [];
function check(name, condition) { if (!condition) throw new Error(name); results.push(name); }
new Function(app);new Function(api);
check('JavaScript syntax', true);
const ids = Array.from(html.matchAll(/\bid="([^"]+)"/g), m => m[1]);
check('Unique HTML element IDs', new Set(ids).size === ids.length);
const staticSelectors = Array.from(app.matchAll(/\$\('#([a-zA-Z][\w-]*)'\)/g), m=>m[1]);
check('All static element references exist', staticSelectors.every(id=>ids.includes(id)));
const symbols = Array.from(html.matchAll(/<symbol id="([^"]+)"/g),m=>m[1]);
check('SVG references resolve', Array.from(html.matchAll(/<use href="#([^"]+)"/g),m=>m[1]).every(id=>symbols.includes(id)));
check('No remote assets required', Array.from(html.matchAll(/(?:src|href)="([^"]+)"/g),m=>m[1]).every(url=>!/^https?:/.test(url)));
// 서버 통신은 api.js 한 곳에서만. 브라우저 저장은 가리는 방식 기억(pl.maskStyle) 하나뿐.
check('Network access only through api.js', !/\bfetch\s*\(|XMLHttpRequest|sendBeacon/.test(app));
check('Browser storage only for mask style', !/sessionStorage|indexedDB/.test(app) && Array.from(app.matchAll(/localStorage\.(?:get|set)Item\('([^']+)'/g),m=>m[1]).every(k=>k==='pl.maskStyle'));
check('No client-side masking of the saved file', !/filter\s*=\s*'blur|imageSmoothingEnabled\s*=\s*false/.test(app));
check('Old demo modes removed', !/connectionDialog|scenarioSelect|demoPanel|data-style="pixel"/.test(html+app));
const sniffSource = app.slice(app.indexOf('  function sniffType'), app.indexOf('  function placeholder'));
const sniffType = new Function(sniffSource + ';return sniffType;')();
check('JPEG signature', sniffType(new Uint8Array([255,216,255,224])) === 'image/jpeg');
check('PNG signature', sniffType(new Uint8Array([137,80,78,71,13,10,26,10])) === 'image/png');
check('WebP signature', sniffType(new Uint8Array([82,73,70,70,16,0,0,0,87,69,66,80])) === 'image/webp');
check('HEIC signature', sniffType(new Uint8Array([0,0,0,24,102,116,121,112,104,101,105,99])) === 'image/heic');
check('Reject other ISO-BMFF (mp4)', sniffType(new Uint8Array([0,0,0,24,102,116,121,112,105,115,111,109])) === null);
check('Reject SVG/non-image input', sniffType(new Uint8Array(Array.from('<svg><script>bad()</script></svg>', c => c.charCodeAt(0)))) === null);
const normalizeSource=app.slice(app.indexOf('  function normalizeRegion'),app.indexOf('  function addRegion'));
const normalizeRegion=new Function('clamp',normalizeSource+';return normalizeRegion;')((v,min,max)=>Math.min(max,Math.max(min,v)));
const edge=normalizeRegion({x:2,y:-1,w:4,h:.00001});
check('Region geometry stays inside image',edge.x===0&&edge.y===0&&edge.w===1&&edge.h>=.008);
const shiftSource=app.slice(app.indexOf('  function shiftPoly'),app.indexOf('  // 코드로 그린 가상 문서'));
const shiftPoly=new Function(shiftSource+';return shiftPoly;')();
const moved={poly:[[.1,.1],[.2,.1],[.2,.2]]};shiftPoly(moved,.05,-.05);
check('Moving a tilted region moves its outline',Math.abs(moved.poly[0][0]-.15)<1e-12&&Math.abs(moved.poly[2][1]-.15)<1e-12);
const context={beginPath(){},roundRect(){},fill(){},stroke(){},fillRect(){},fillText(){},save(){},restore(){},translate(){},scale(){},moveTo(){},lineTo(){}};
const fakeDocument={createElement:()=>({width:0,height:0,getContext:()=>context})};
const fixtureSource=app.slice(app.indexOf('  function rounded'),app.indexOf('  function initializeThumbnails'));
const makeFixture=new Function('document','fixtures',fixtureSource+';return makeFixture;')(fakeDocument,new Map());
for(const key of ['parcel','student','mixed']) {
  const f=makeFixture(key);
  check('Sample '+key+' has valid image dimensions',f.image.width===1440&&f.image.height===1000);
  check('Sample '+key+' has no predefined results (real analysis)',!('regions' in f));
}
check('Responsive breakpoints included',css.includes('@media(max-width:580px)')&&css.includes('@media(max-width:820px)'));
check('Reduced motion honored',css.includes('prefers-reduced-motion:reduce'));
check('Severity styles defined',['.risk-tag.sev-review','.region-box.sev-review','.region-box.poly polygon','.queue-badge'].every(s=>css.includes(s)));
return results;

})();
for(const check of checks) console.log('PASS '+check);
console.log('\n'+checks.length+' checks passed. Browser visual and download testing must be performed separately.');
