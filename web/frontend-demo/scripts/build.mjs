// 사용법
//   node scripts/build.mjs                                   privacy-lens.html (서버가 / 에서 내주는 한 파일)
//   node scripts/build.mjs --api https://api.example.org     + 정적 배포 폴더 site/ (index.html + dist/fonts)
//   node scripts/build.mjs --api <주소> --out <폴더>          정적 배포 폴더 위치를 바꾼다
// 정적 배포 폴더는 GitHub Pages·Netlify 같은 곳에 그대로 올린다. API 는 게이트웨이(run_gateway.py --no-front --cors <화면 주소>)
// 또는 엔진 서버(run_backend.py --cors <화면 주소>) 주소를 준다. https 화면에서는 API 도 https 여야 한다(브라우저 규칙).
import {readFile,writeFile,mkdir,copyFile,readdir,rm} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
const root=new URL('../',import.meta.url);

function option(name){const i=process.argv.indexOf(name);if(i<0)return null;const v=process.argv[i+1];if(!v||v.startsWith('--'))throw new Error(name+' 뒤에 값이 필요합니다.');return v;}
export function apiOrigin(raw){
  let u;try{u=new URL(String(raw).trim());}catch{throw new Error('API 주소가 올바르지 않습니다: '+raw);}
  if(!/^https?:$/.test(u.protocol)||!u.host||u.search||u.hash||u.username||u.password)throw new Error('API 주소는 http(s)://호스트[/경로] 형식이어야 합니다: '+raw);
  return u.origin+u.pathname.replace(/\/+$/,'');
}
// <head> 바로 뒤에, </ 를 끊어서 넣는다(화면 스크립트보다 먼저 실행된다)
export function pageWithApi(page,api){
  const tag='<script>globalThis.PRIVACY_LENS_API='+JSON.stringify(api).replaceAll('</','<\\/')+';</script>';
  const i=page.indexOf('<head>');if(i<0)throw new Error('<head> 가 없습니다.');
  return page.slice(0,i+6)+tag+page.slice(i+6);
}
// 옵션을 먼저 확인한다(잘못된 주소면 아무것도 쓰지 않는다). 다른 스크립트가 함수만 가져다 쓸 때는 빌드하지 않는다.
const main=import.meta.url===pathToFileURL(process.argv[1]??'').href;
let apiRaw=null,outRaw=null;
if(main){
  try{
    apiRaw=option('--api');outRaw=option('--out');
    if(outRaw!==null&&apiRaw===null)throw new Error('--out 은 --api 와 함께 씁니다.');
    if(apiRaw!==null)apiRaw=apiOrigin(apiRaw);
  }catch(e){console.error('[오류] '+e.message);process.exit(2);}
}
if(main){
let html=await readFile(new URL('dist/index.html',root),'utf8');
const sources=[];
for(const name of ['core.js','api.js','samples.js','app.js']){const js=await readFile(new URL('dist/'+name,root),'utf8');new Function(js);html=html.replace('<script src="'+name+'" defer></script>','');sources.push(js);}
for(const name of ['styles.css']){const css=await readFile(new URL('dist/'+name,root),'utf8');html=html.replace('<link rel="stylesheet" href="'+name+'">',()=>'<style>\n'+css.replaceAll('url(fonts/','url(dist/fonts/')+'\n</style>');}
const bundle=sources.join('\n');
html=html.replace('</body>',()=>'<script>\n'+bundle+'\n</script>\n</body>');
// A replacement callback preserves literal dollar signs in selector helpers.
if(!html.includes('<script>\n'+bundle+'\n</script>'))throw new Error('Standalone script differs from source.');
await writeFile(new URL('privacy-lens.html',root),html);
console.log('Created standalone privacy-lens.html');

if(apiRaw!==null){
  const api=apiRaw;
  const out=path.resolve(outRaw??fileURLToPath(new URL('site/',root)));
  const fonts=fileURLToPath(new URL('dist/fonts/',root));
  await rm(out,{recursive:true,force:true});
  await mkdir(path.join(out,'dist','fonts'),{recursive:true});
  await writeFile(path.join(out,'index.html'),pageWithApi(html,api));
  for(const f of await readdir(fonts))if(/\.(woff2|txt)$/.test(f))await copyFile(path.join(fonts,f),path.join(out,'dist','fonts',f));
  await writeFile(path.join(out,'.nojekyll'),'');
  console.log('Created static site '+out+' (API '+api+')');
  const local=/^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(api+'/');
  if(api.startsWith('http:')&&!local)console.log('  [주의] API 가 http 입니다. 화면을 https 로 올리면 브라우저가 요청을 막습니다(mixed content).');
  console.log('  API 서버에 화면 주소를 허용해 두세요:  python run_gateway.py --no-front --cors <화면 주소> ...');
}
}
