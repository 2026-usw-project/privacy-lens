import {readFile,writeFile} from 'node:fs/promises';
const root=new URL('../',import.meta.url);
let html=await readFile(new URL('dist/index.html',root),'utf8');
const sources=[];
for(const name of ['core.js','api.js','app.js']){const js=await readFile(new URL('dist/'+name,root),'utf8');new Function(js);html=html.replace('<script src="'+name+'" defer></script>','');sources.push(js);}
for(const name of ['styles.css','workspace.css']){const css=await readFile(new URL('dist/'+name,root),'utf8');html=html.replace('<link rel="stylesheet" href="'+name+'">',()=>'<style>\n'+css+'\n</style>');}
const bundle=sources.join('\n');
html=html.replace('</body>',()=>'<script>\n'+bundle+'\n</script>\n</body>');
// A replacement callback preserves literal dollar signs in selector helpers.
if(!html.includes('<script>\n'+bundle+'\n</script>'))throw new Error('Standalone script differs from source.');
await writeFile(new URL('privacy-lens.html',root),html);
console.log('Created standalone privacy-lens.html');
