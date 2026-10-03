import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const [app,html,css]=await Promise.all(['app.js','index.html','styles.css'].map(file=>readFile(path.join(root,'dist',file),'utf8')));
const checks=(()=>{
const results = [];
function check(name, condition) { if (!condition) throw new Error(name); results.push(name); }
new Function(app);
check('JavaScript syntax', true);
const ids = Array.from(html.matchAll(/\bid="([^"]+)"/g), m => m[1]);
check('Unique HTML element IDs', new Set(ids).size === ids.length);
const staticSelectors = Array.from(app.matchAll(/\$\('#([a-zA-Z][\w-]*)'\)/g), m=>m[1]);
check('All static element references exist', staticSelectors.every(id=>ids.includes(id)));
const symbols = Array.from(html.matchAll(/<symbol id="([^"]+)"/g),m=>m[1]);
check('SVG references resolve', Array.from(html.matchAll(/<use href="#([^"]+)"/g),m=>m[1]).every(id=>symbols.includes(id)));
check('No remote assets required', Array.from(html.matchAll(/(?:src|href)="([^"]+)"/g),m=>m[1]).every(url=>!/^https?:/.test(url)));
check('Network access isolated from editor and no browser persistence', !/\bfetch\s*\(|XMLHttpRequest|sendBeacon|localStorage|sessionStorage/.test(app));
const metadataSource = app.slice(app.indexOf('  function inspectMetadata'), app.indexOf('  async function loadFile'));
const {inspectMetadata,sniffType} = new Function(metadataSource + ';return {inspectMetadata,sniffType};')();
check('JPEG signature', sniffType(new Uint8Array([255,216,255,224])) === 'image/jpeg');
check('PNG signature', sniffType(new Uint8Array([137,80,78,71,13,10,26,10])) === 'image/png');
check('WebP signature', sniffType(new Uint8Array([82,73,70,70,16,0,0,0,87,69,66,80])) === 'image/webp');
check('Reject SVG/non-image input', sniffType(new Uint8Array(Array.from('<svg><script>bad()</script></svg>', c => c.charCodeAt(0)))) === null);
function exifFixture(littleEndian) {
  const buffer = new ArrayBuffer(80);
  const v = new DataView(buffer), b = new Uint8Array(buffer);
  b.set([255,216,255,225]);v.setUint16(4,74);
  b.set([69,120,105,102,0,0],6);
  const base=12;
  v.setUint16(base,littleEndian?0x4949:0x4d4d);
  v.setUint16(base+2,42,littleEndian);v.setUint32(base+4,8,littleEndian);
  v.setUint16(base+8,3,littleEndian);
  [0x8825,0x010f,0x0132].forEach((tag,i)=>{const p=base+10+i*12;v.setUint16(p,tag,littleEndian);v.setUint16(p+2,4,littleEndian);v.setUint32(p+4,1,littleEndian);v.setUint32(p+8,50,littleEndian);});
  b.set([255,217],78);return buffer;
}
for(const le of [true,false]) {
  const info=inspectMetadata(exifFixture(le),'image/jpeg');
  check('EXIF GPS, camera, date tags ('+(le?'LE':'BE')+')',info.exif&&info.gps&&info.camera&&info.date&&info.status==='checked');
}
const fixture=exifFixture(true);
for(let length=0;length<fixture.byteLength;length++) inspectMetadata(fixture.slice(0,length),'image/jpeg');
check('Truncated EXIF does not throw',true);
const bad=exifFixture(true);new DataView(bad).setUint32(16,0xffffffff,true);
check('Out-of-bounds EXIF pointer handled',inspectMetadata(bad,'image/jpeg').exif);
check('Unsupported metadata formats reported',inspectMetadata(new ArrayBuffer(0),'image/png').status==='unsupported');
check('No EXIF reported for plain JPEG',!inspectMetadata(new Uint8Array([255,216,255,217]).buffer,'image/jpeg').exif);
const normalizeSource=app.slice(app.indexOf('  function normalizeRegion'),app.indexOf('  function addRegion'));
const normalizeRegion=new Function('clamp',normalizeSource+';return normalizeRegion;')((v,min,max)=>Math.min(max,Math.max(min,v)));
const edge=normalizeRegion({x:2,y:-1,w:4,h:.00001});
check('Region geometry stays inside image',edge.x===0&&edge.y===0&&edge.w===1&&edge.h>=.008);
const calls=[];
const context={beginPath(){},roundRect(){},fill(){},stroke(){},fillRect(){},fillText(){},save(){},restore(){},translate(){},scale(){},moveTo(){},lineTo(){}};
const fakeDocument={createElement:()=>({width:0,height:0,getContext:()=>context})};
const fixtureSource=app.slice(app.indexOf('  function rounded'),app.indexOf('  function initializeThumbnails'));
const makeFixture=new Function('document','fixtures',fixtureSource+';return makeFixture;')(fakeDocument,new Map());
for(const key of ['parcel','student','mixed']) {
  const f=makeFixture(key);
  check('Sample '+key+' has valid image dimensions',f.image.width===1440&&f.image.height===1000);
  check('Sample '+key+' regions are fully in bounds',f.regions.every(r=>r.x>=0&&r.y>=0&&r.w>0&&r.h>0&&r.x+r.w<=1&&r.y+r.h<=1));
  check('Sample '+key+' labels and explanations exist',f.regions.every(r=>r.label&&r.reason&&r.text&&r.enabled));
}
check('Responsive breakpoints included',css.includes('@media(max-width:580px)')&&css.includes('@media(max-width:820px)'));
check('Reduced motion honored',css.includes('prefers-reduced-motion:reduce'));
return results;

})();
for(const check of checks) console.log('PASS '+check);
console.log('\n'+checks.length+' checks passed. Browser visual and download testing must be performed separately.');
