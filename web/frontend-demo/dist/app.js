'use strict';
(() => {
  // 화면 동작. 분석·판정·가림·검증은 전부 Privacy Lens 서버가 한다(api.js).
  // 이 파일은 사진 표시, 결과 목록, 영역 편집, 대기열 표시만 맡는다.
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const icon = name => '<svg aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const escapeHTML = text => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const clone = value => JSON.parse(JSON.stringify(value));
  const Core=PrivacyLensCore, Api=PrivacyLensAPI, api=Api.client();
  const state = { source:null, file:null, phase:'empty', regions:[], focused:null, editing:null, history:[], mode:'original', style:'blur', compare:50, drawing:false,
    sample:false, sampleKey:null, width:0, height:0, name:'', bytes:0, serverImage:false, condition:'full', analysisStatus:'idle', groups:[], gps:[], issues:[],
    backend:'', elapsedMs:0, zoom:1, loadToken:0, exportToken:0, exportUrl:null, nextId:1, toastTimer:null,
    requestController:null, requestSerial:0, saving:false, saveError:'', ticket:null, previewState:'none', previewSeq:0 };
  try { const saved=localStorage.getItem('pl.maskStyle'); if(Core.STYLES.includes(saved)) state.style=saved; } catch(_) {}
  const canvas = $('#photoCanvas');
  const ctx = canvas.getContext('2d');
  const protectedCanvas = document.createElement('canvas');   // 서버가 그려 준 가림 미리보기
  const protectedContext = protectedCanvas.getContext('2d');
  let gesture = null, downloadBlob = null, dialogReturnFocus = null, previewTimer = null, queueTimer = null;
  const fixtures = new Map();
  // 이미지 불러오기. img.decode() 는 탭이 가려져 있으면 끝나지 않는다(Chromium).
  // 미리보기를 만드는 동안 다른 탭으로 가면 화면이 멈춰서 onload 로 기다린다.
  function loadImage(src) {
    return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('decode'));image.src=src;});
  }

  function notify(message, error = false) {
    clearTimeout(state.toastTimer);
    $('#toastText').textContent = message;
    $('#toast').classList.toggle('error', error);
    $('#toast').classList.add('visible');
    state.toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 4300);
  }
  function setStep(step) {
    [1, 2, 3].forEach(index => {
      const item = $('#step' + index);
      item.classList.toggle('current', index === step);
      item.classList.toggle('done', index < step);
      if (index === step) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
      $('.step-number', item).innerHTML = index < step ? icon('check') : String(index);
    });
  }
  function showDialog(id) {
    const dialog = document.getElementById(id);
    if (!dialog || dialog.open) return;
    dialogReturnFocus = document.activeElement;
    dialog.showModal();
  }
  function closeDialog(dialog) {
    dialog.close();
    if (dialogReturnFocus && document.contains(dialogReturnFocus)) dialogReturnFocus.focus();
  }
  // 영역이 바뀌면 가림 미리보기를 다시 받아야 한다.
  function invalidate() {
    state.previewState='stale'; state.exportToken++;
    if (state.source && state.phase === 'review') setStep(2);
    if (state.mode !== 'original') schedulePreview();
  }
  function pushHistory() {
    state.history.push(clone(state.regions));
    if (state.history.length > 35) state.history.shift();
    $('#undoButton').disabled = false;
  }
  function releaseExport() {
    state.exportToken++;
    if (state.exportUrl) URL.revokeObjectURL(state.exportUrl);
    state.exportUrl = null;
    downloadBlob = null;
    $('#exportPreview').removeAttribute('src');
  }
  function reset() {
    cancelRequests();state.zoom=1;state.analysisStatus='idle';state.issues=[];state.groups=[];state.gps=[];state.backend='';
    state.loadToken++;state.exportToken++;releaseExport();
    Object.assign(state,{source:null,file:null,phase:'empty',regions:[],history:[],focused:null,editing:null,drawing:false,sample:false,sampleKey:null,serverImage:false,nextId:1,mode:'original',previewState:'none'});
    gesture = null;
    canvas.width = canvas.height = 1;
    protectedCanvas.width = protectedCanvas.height = 1;
    $('#fileInput').value = '';
    $('#emptyState').classList.remove('hidden');
    $('#imageState').classList.add('hidden');
    $('#changePhoto').classList.add('hidden');
    $('#fileInfo').classList.remove('hidden');
    $('#editorTitle').textContent = '사진 작업 공간';
    $('#regionLayer').replaceChildren();
    $('#undoButton').disabled = true;
    setStep(1);
    syncDrawing();syncPanels();$('#saveState').classList.add('hidden');
  }
  function normalizeRegion(region) {
    const w = clamp(Number(region.w) || .1, .008, 1);
    const h = clamp(Number(region.h) || .1, .008, 1);
    return { ...region, x: clamp(Number(region.x) || 0, 0, 1 - w), y: clamp(Number(region.y) || 0, 0, 1 - h), w, h };
  }
  function addRegion(rect) {
    if (!state.source || state.phase === 'scanning') return;
    pushHistory();
    const number = state.nextId++;
    // 직접 그린 영역은 사용자가 가리겠다고 고른 것이라 바로 선택된다.
    const region = normalizeRegion({ id: 'custom-' + number, x: rect.x, y: rect.y, w: rect.w, h: rect.h, label: '직접 지정한 영역 ' + number, reason: '직접 선택한 영역이에요. 크기와 위치를 조절해 충분히 가려 주세요.', text: '', kind: 'manual', type: 'CUSTOM', poly: null, enabled: true });
    state.regions.push(region);
    state.focused = state.editing = region.id;
    state.drawing = false;
    invalidate();
    syncDrawing();
    render();
    notify('가릴 영역을 추가했어요. 테두리를 끌어 위치를 조절할 수 있어요.');
  }
  // 영역을 옮기면 기울어진 외곽선도 같이 옮긴다. 크기를 바꾸면 외곽선은 의미가 없어 사각형이 된다.
  function shiftPoly(region, dx, dy) {
    if (region.poly && (dx || dy)) region.poly = region.poly.map(([x, y]) => [x + dx, y + dy]);
  }

  // 코드로 그린 가상 문서. 실제 사진이나 실제 개인정보가 아니다. 서버로 실제 분석한다.
  function rounded(c, x, y, w, h, r, fill, stroke) {
    c.beginPath();
    c.roundRect(x, y, w, h, r);
    if (fill) { c.fillStyle = fill; c.fill(); }
    if (stroke) { c.strokeStyle = stroke; c.lineWidth = 1.5; c.stroke(); }
  }
  function write(c, text, x, y, size, color = '#26392f', weight = 400) {
    c.fillStyle = color;
    c.font = weight + ' ' + size + 'px "Malgun Gothic", sans-serif';
    c.fillText(text, x, y);
  }
  function barcode(c, x, y, w, h) {
    c.fillStyle = '#243d32';
    let offset = 0;
    for (let i = 0; offset < w; i++) {
      const stripe = 1 + ((i * 7 + 3) % 4);
      c.fillRect(x + offset, y, Math.min(stripe, w - offset), h);
      offset += stripe + 2 + i % 3;
    }
  }
  function parcelDocument(c, x, y, scale = 1) {
    c.save(); c.translate(x, y); c.scale(scale, scale);
    rounded(c, 0, 0, 1050, 610, 14, '#fffefa', '#d7ddcd');
    rounded(c, 0, 0, 1050, 96, [14,14,0,0], '#314e3b');
    write(c, 'LENS DELIVERY', 35, 59, 29, '#eef7df', 700);
    write(c, '가상 택배 송장', 770, 59, 24, '#d4e4c2', 400);
    write(c, '운송장번호 6012-3456-7890', 35, 145, 22, '#79896e', 600);
    barcode(c, 660, 117, 350, 39);
    c.strokeStyle = '#e3e7db'; c.beginPath(); c.moveTo(35, 177); c.lineTo(1015, 177); c.stroke();
    write(c, '받는 분', 38, 230, 22, '#7c8871');
    write(c, '김렌즈', 208, 230, 32, '#23372d', 600);
    write(c, '연락처', 600, 230, 22, '#7c8871');
    write(c, '010-0000-0000', 740, 230, 27, '#23372d', 500);
    write(c, '배송지', 38, 316, 22, '#7c8871');
    write(c, '가상시 안심구 렌즈로 123', 208, 314, 29, '#23372d', 600);
    write(c, '프라이버시 아파트 101동 202호', 208, 359, 25, '#4b5b41');
    c.beginPath(); c.moveTo(35, 400); c.lineTo(1015, 400); c.stroke();
    write(c, '품목', 38, 454, 22, '#7c8871'); write(c, '무선 헤드폰 / 1개', 208, 454, 25, '#617053');
    write(c, '고객센터', 38, 513, 22, '#7c8871'); write(c, '1588-0000', 208, 513, 24, '#617053');
    write(c, 'SYNTHETIC DATA  ·  실제 수신인과 주소가 아닙니다', 38, 576, 17, '#9ba58e');
    c.restore();
  }
  function studentDocument(c, x, y, scale = 1) {
    c.save(); c.translate(x,y); c.scale(scale, scale);
    rounded(c,0,0,720,445,24,'#fffefa','#d5dfcc');
    rounded(c,0,0,720,107,[24,24,0,0],'#bcccab');
    write(c,'LENS UNIVERSITY',35,47,22,'#3e5930',700);
    write(c,'가상대학교',35,81,20,'#557446',500);
    write(c,'STUDENT ID',510,62,18,'#5f794f',600);
    rounded(c,37,146,154,193,10,'#e9efdf');
    write(c,'DEMO',61,234,30,'#a0b68b',700);
    write(c,'가상 학생',73,268,15,'#9aac88');
    write(c,'성명 이안심',235,195,39,'#29482f',700);
    write(c,'학번  2026000123',235,252,25,'#647b52');
    write(c,'정보보안학과',235,297,25,'#647b52');
    barcode(c,236,340,406,31);
    write(c,'SAMPLE ONLY  /  교육용 가상 정보',37,410,17,'#a0ad90');
    c.restore();
  }
  function screenDocument(c,x,y,scale=1) {
    c.save();c.translate(x,y);c.scale(scale,scale);
    rounded(c,0,0,620,420,15,'#fbfcf8','#d3ddca');
    rounded(c,0,0,620,63,[15,15,0,0],'#dce5d2');
    write(c,'PROJECT NOTE',26,40,19,'#577247',650);
    write(c,'팀 연락처',31,121,22,'#7f916e');
    write(c,'lens@example.com',31,168,28,'#364f2a',600);
    write(c,'일상의 안전한 공유를 위한',31,245,22,'#96a288');
    write(c,'프라이버시 렌즈 프로젝트',31,283,22,'#96a288');
    write(c,'SAMPLE  /  가상 화면 문서',31,379,17,'#a0ad90');
    c.restore();
  }
  function makeFixture(key) {
    if (fixtures.has(key)) return fixtures.get(key);
    const image = document.createElement('canvas'); image.width = 1440; image.height = 1000;
    const c = image.getContext('2d');
    c.fillStyle = key === 'student' ? '#e8eddf' : '#edece3'; c.fillRect(0,0,1440,1000);
    write(c,'PRIVACY LENS  /  SAMPLE DOCUMENT',65,75,18,'#929e83',600);
    write(c,'실제 개인정보가 없는 테스트 이미지',65,115,20,'#7e8d6f');
    write(c,'2026',1300,75,18,'#9ba68e');
    if(key === 'parcel') parcelDocument(c,195,235);
    else if(key === 'student') studentDocument(c,245,260,1.32);
    else { parcelDocument(c,65,230,.76); studentDocument(c,920,240,.62); screenDocument(c,920,595,.72); }
    write(c,'SYNTHETIC DATA',65,945,16,'#a0aa93',500);
    write(c,'사진 속 위험 영역 확인을 위한 데모 문서',935,945,16,'#9ca78e');
    const fixture = {image};fixtures.set(key,fixture);return fixture;
  }
  function initializeThumbnails() {
    ['parcel','student','mixed'].forEach(key => {
      const fixture = makeFixture(key);
      const thumb = $('#thumb-' + key);
      thumb.getContext('2d').drawImage(fixture.image,0,0,thumb.width,thumb.height);
    });
  }

  function sniffType(bytes) {
    if(bytes[0]===255 && bytes[1]===216 && bytes[2]===255) return 'image/jpeg';
    if(bytes[0]===137 && bytes[1]===80 && bytes[2]===78 && bytes[3]===71 && bytes[4]===13 && bytes[5]===10 && bytes[6]===26 && bytes[7]===10) return 'image/png';
    if(bytes[0]===82 && bytes[1]===73 && bytes[2]===70 && bytes[3]===70 && bytes[8]===87 && bytes[9]===69 && bytes[10]===66 && bytes[11]===80) return 'image/webp';
    // HEIC/HEIF: 'ftyp' 상자 + 상표. 브라우저 대부분은 못 열지만 서버는 연다(pillow-heif).
    if(bytes[4]===102 && bytes[5]===116 && bytes[6]===121 && bytes[7]===112) {
      const brand=String.fromCharCode(...bytes.slice(8,12));
      if(['heic','heix','hevc','heim','heis','mif1','msf1'].includes(brand)) return 'image/heic';
    }
    return null;
  }
  function placeholder() {
    const c=document.createElement('canvas');c.width=1200;c.height=900;
    const g=c.getContext('2d');g.fillStyle='#f0efeb';g.fillRect(0,0,1200,900);
    write(g,'HEIC 사진',80,400,44,'#4a4741',600);
    write(g,'이 브라우저는 미리 보지 못해요. 분석하면 서버가 만든 미리보기로 바뀌어요.',80,470,26,'#6b675f');
    return c;
  }
  async function loadFile(file) {
    if(!file) return;
    if(file.size > 20*1024*1024) { notify('20 MB 이하의 사진을 선택해 주세요.', true); return; }
    const token = ++state.loadToken;
    let objectUrl;
    try {
      const buffer = await file.arrayBuffer();
      if(token !== state.loadToken) return;
      const type = sniffType(new Uint8Array(buffer));
      if(!type) throw new Error('JPG, PNG, WEBP, HEIC 사진만 선택할 수 있어요.');
      let frozen=null;
      try {
        objectUrl = URL.createObjectURL(new Blob([buffer],{type}));
        const image = await loadImage(objectUrl);
        if(token !== state.loadToken) return;
        if(image.naturalWidth*image.naturalHeight > 24e6 || image.naturalWidth > 16384 || image.naturalHeight > 16384) throw new Error('사진 크기가 너무 커요. 24 MP 이하, 한 변 16,384 px 이하로 줄여 주세요.');
        // 브라우저는 EXIF 방향을 반영해 그린다. 서버도 같은 방향으로 보정하므로 좌표가 맞는다.
        frozen = document.createElement('canvas');
        frozen.width=image.naturalWidth;frozen.height=image.naturalHeight;
        frozen.getContext('2d').drawImage(image,0,0);
      } catch(error) {
        if(type!=='image/heic') throw error;
        frozen=null;
      }
      cancelRequests();
      const serverImage=!frozen;
      if(serverImage) frozen=placeholder();
      Object.assign(state,{source:frozen,file,width:frozen.width,height:frozen.height,name:file.name,bytes:file.size,sample:false,sampleKey:null,serverImage,
        regions:[],history:[],focused:null,editing:null,nextId:1,mode:'original',phase:'ready',drawing:false,zoom:1,analysisStatus:'idle',issues:[],groups:[],gps:[],backend:'',previewState:'none'});
      releaseExport();showImage();render();
      notify(serverImage?'HEIC 사진이에요. 분석하면 서버가 만든 미리보기를 보여 드려요.':'사진이 준비됐어요. 분석하거나 직접 가릴 영역을 지정하세요.');
    } catch(error) {
      if(token === state.loadToken) notify(error.message && !/decode/i.test(error.message) ? error.message : '손상되었거나 지원되지 않는 사진이에요. 다른 파일을 선택해 주세요.',true);
    } finally {
      if(objectUrl) URL.revokeObjectURL(objectUrl);
      $('#fileInput').value='';
    }
  }
  function loadSample(key) {
    if(!['parcel','student','mixed'].includes(key))return;
    state.loadToken++;cancelRequests();releaseExport();
    const fixture=makeFixture(key);
    Object.assign(state,{source:fixture.image,file:null,width:fixture.image.width,height:fixture.image.height,
      name:{parcel:'sample_delivery.png',student:'sample_student_id.png',mixed:'sample_documents.png'}[key],bytes:0,sample:true,sampleKey:key,serverImage:false,
      regions:[],history:[],focused:null,editing:null,nextId:1,mode:'original',drawing:false,phase:'ready',analysisStatus:'idle',issues:[],groups:[],gps:[],backend:'',zoom:1,previewState:'none'});
    showImage();render();layoutCanvas(false);
    beginAnalysis();
  }
  // 서버로 보낼 파일. 샘플은 화면에 그린 그림을 PNG 로 만든다.
  async function uploadFile() {
    if(state.file) return state.file;
    const blob=await imageBlob(state.source);
    state.file=new File([blob],state.name||'image.png',{type:'image/png'});
    return state.file;
  }
  // 서버가 보정한 사진과 크기가 다르면(HEIC, 브라우저가 EXIF 방향을 반영하지 않은 경우)
  // 서버 미리보기를 화면 사진으로 쓴다. 그래야 서버 좌표와 정확히 겹친다.
  async function adoptServerImage(b64,width,height) {
    const image=await loadImage('data:image/jpeg;base64,'+b64);
    const c=document.createElement('canvas');c.width=width;c.height=height;
    c.getContext('2d').drawImage(image,0,0,width,height);
    Object.assign(state,{source:c,width,height,serverImage:true});
    showImage();
  }

  function showImage() {
    canvas.width=protectedCanvas.width=state.width;canvas.height=protectedCanvas.height=state.height;
    $('#emptyState').classList.add('hidden');$('#imageState').classList.remove('hidden');
    $('#changePhoto').classList.remove('hidden');$('#fileInfo').classList.add('hidden');
    $('#editorTitle').textContent=state.name;$('#editorTitle').title=state.name;
    $('#imageDimensions').textContent=state.width.toLocaleString()+' × '+state.height.toLocaleString()+' px'+(state.bytes?' · '+(state.bytes/1024/1024).toFixed(1)+' MB':' · 가상 데이터');
    $('#undoButton').disabled=!state.history.length;
    syncDrawing();syncPanels();layoutCanvas(false);
  }

  /* ---------- 가림 미리보기 ----------
     서버가 저장할 때와 같은 함수로 가린 축소본을 받아 '가림 결과'·'전후 비교'에 쓴다.
     화면에서 따로 흉내 내면 미리 본 것과 저장된 것이 달라질 수 있다. */
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer=setTimeout(renderPreview,250);
  }
  async function renderPreview() {
    if(!state.source || state.phase!=='review') return;
    const seq=++state.previewSeq;
    state.previewState='loading';renderImage();
    try {
      const file=await uploadFile();
      const data=await api.preview(file,Core.boxes(state),state.style);
      if(seq!==state.previewSeq) return;
      const image=await loadImage('data:image/jpeg;base64,'+data.preview);
      if(seq!==state.previewSeq) return;
      protectedContext.clearRect(0,0,state.width,state.height);
      protectedContext.drawImage(image,0,0,state.width,state.height);
      state.previewState='ready';
    } catch(error) {
      if(seq!==state.previewSeq) return;
      state.previewState='error';notify('가림 미리보기를 만들지 못했어요. '+(error.message||''),true);
    }
    renderImage();
  }
  function renderImage() {
    if(!state.source) return;
    ctx.clearRect(0,0,state.width,state.height);
    const showProtected=state.mode!=='original'&&state.previewState==='ready';
    ctx.drawImage(showProtected?protectedCanvas:state.source,0,0,state.width,state.height);
    if(showProtected && state.mode==='compare') {
      const split=state.width*state.compare/100;
      ctx.save();ctx.beginPath();ctx.rect(0,0,split,state.height);ctx.clip();ctx.drawImage(state.source,0,0,state.width,state.height);ctx.restore();
      ctx.fillStyle='#fff';ctx.fillRect(split-1.5,0,3,state.height);
      ctx.beginPath();ctx.arc(split,state.height/2,Math.max(10,state.width*.018),0,Math.PI*2);ctx.fill();
      const s=Math.max(4,state.width*.004);ctx.strokeStyle='#ef5a1c';ctx.lineWidth=Math.max(2,state.width*.0012);
      ctx.beginPath();ctx.moveTo(split-s,state.height/2-s);ctx.lineTo(split-s,state.height/2+s);ctx.moveTo(split+s,state.height/2-s);ctx.lineTo(split+s,state.height/2+s);ctx.stroke();
    }
    const waiting=state.mode!=='original'&&state.previewState!=='ready';
    $('#canvasCaption').textContent=state.mode==='original'?'ORIGINAL · 위험 영역':waiting?(state.previewState==='error'?'PREVIEW · 만들지 못했어요':'PREVIEW · 서버에서 만드는 중'):state.mode==='protected'?'PROTECTED · 저장될 모습':'BEFORE / AFTER';
    $('#regionLayer').classList.toggle('hidden',state.mode!=='original' || state.phase==='scanning');
    if(state.mode==='original')declutterTags();  // 가려져 있던 동안에는 크기를 잴 수 없었다
    $('#compareControl').classList.toggle('hidden',state.mode!=='compare');
    $$('[data-view]').forEach(button=>{const active=button.dataset.view===state.mode;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));button.disabled=state.phase!=='review';});
  }
  function renderBoxes() {
    const layer=$('#regionLayer');layer.replaceChildren();
    state.regions.forEach((r,i)=>{
      const box=document.createElement('button');
      box.className='region-box'+(!r.enabled?' unselected':'')+(state.focused===r.id?' focused':'')+(r.severity?' sev-'+r.severity:'')+(r.certainty&&r.certainty!=='read'?' cert-'+r.certainty:'')+(r.poly?' poly':'');
      box.dataset.id=r.id;
      box.setAttribute('aria-pressed',String(state.focused===r.id));
      box.setAttribute('aria-label',r.label+' 영역. 방향키로 이동, Alt와 방향키로 크기 조절');
      box.title=r.label+' · 끌어서 이동, 모서리를 끌어 크기 조절';
      box.style.left=(r.x*100)+'%';box.style.top=(r.y*100)+'%';box.style.width=(r.w*100)+'%';box.style.height=(r.h*100)+'%';
      if(r.poly) {
        // 기울어진 글자는 실제 외곽선을 그린다. 가릴 때도 이 모양을 쓴다.
        const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),poly=document.createElementNS(ns,'polygon');
        svg.setAttribute('viewBox','0 0 100 100');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
        poly.setAttribute('points',r.poly.map(([x,y])=>((x-r.x)/r.w*100).toFixed(2)+','+((y-r.y)/r.h*100).toFixed(2)).join(' '));
        svg.append(poly);box.append(svg);
      }
      const label=document.createElement('span'),num=document.createElement('b'),name=document.createElement('span');num.textContent=String(i+1).padStart(2,'0');name.className='name';name.textContent=r.label;label.append(num,name);box.append(label);
      const handle=document.createElement('i');handle.className='resize-handle';handle.dataset.resize='true';box.append(handle);
      layer.append(box);
    });
    declutterTags();
  }
  // 사진 위 번호표가 서로 겹치면 뒤에 놓일 것을 숨긴다(박스에 마우스를 올리거나 고르면 보인다).
  // 실제 OCR 은 줄 단위 작은 상자를 촘촘히 내서, 번호표가 서로 덮여 읽을 수 없었다.
  // 고른(focus) 박스가 먼저, 그다음 목록 순서(심각도 높은 순).
  function declutterTags() {
    const tags=$$('.region-box>span',$('#regionLayer'));
    tags.forEach(t=>t.classList.remove('tag-hidden'));
    const order=tags.slice().sort((a,b)=>Number(b.parentElement.classList.contains('focused'))-Number(a.parentElement.classList.contains('focused')));
    const placed=[];
    order.forEach(tag=>{
      const r=tag.getBoundingClientRect();
      if(!r.width)return;
      if(placed.some(p=>r.left<p.right-1&&p.left<r.right-1&&r.top<p.bottom-1&&p.top<r.bottom-1))tag.classList.add('tag-hidden');
      else placed.push(r);
    });
  }
  function metadataText() {
    if(state.sample) return '샘플 문서 · 촬영 메타데이터 없음';
    if(state.gps.length) return state.gps[0].message+' — 저장하면 자동으로 제거돼요.';
    if(state.analysisStatus==='idle'||state.analysisStatus==='manual') return '저장할 때 위치·기기·촬영 시각 등 원본 메타데이터를 모두 빼요.';
    return '사진 파일에서 위치정보가 발견되지 않았어요. 저장할 때 다른 메타데이터도 모두 빼요.';
  }
  function severityTag(r) {
    if(r.kind==='manual') return '<span class="risk-tag manual">직접 추가</span>';
    return '<span class="risk-tag sev-'+escapeHTML(r.severity)+'">'+escapeHTML(Core.SEVERITY[r.severity]||'검토 권장')+'</span>';
  }
  function renderList() {
    const list=$('#regionList'),active=document.activeElement;
    const focusId=active?.closest('[data-region]')?.dataset.region,focusAction=active?.dataset.action,focusCoordinate=active?.dataset.coordinate,focusType=active?.dataset.regionType;
    if(!state.regions.length) {
      list.innerHTML='<div class="empty-regions">'+icon('scan')+'<p>'+(state.analysisStatus==='empty'?'탐지된 영역이 없어요.<br>안전하다는 뜻은 아니에요. 사진을 확인하고<br>놓친 부분은 직접 추가해 주세요.':'현재 지정한 영역이 없어요.<br>‘영역 추가’로 가릴 부분을 선택해 주세요.')+'</p></div>';return;
    }
    list.innerHTML=state.regions.map((r,index)=>{
      const focused=state.focused===r.id,detail=state.editing===r.id,title=escapeHTML(r.label),px=Core.toPixels(r,state.width,state.height);
      // 내용을 다 읽은 항목은 인식된 문자열이 그 증거라 따로 쓰지 않는다. 박스 선 모양에도 드러난다.
      const cert=r.kind!=='manual'&&r.certainty&&r.certainty!=='read'?'<span class="cert-label">'+escapeHTML(r.certaintyLabel||'')+'</span>':'';
      return '<div class="region-item'+(focused?' selected-detail':'')+(detail?' editing':'')+'" data-region="'+escapeHTML(r.id)+'">'+
        '<div class="region-item-top"><input type="checkbox" data-action="toggle" '+(r.enabled?'checked ':'')+'aria-label="'+title+' 가리기"><button class="region-item-name" data-action="focus" aria-pressed="'+focused+'"><span class="row-number">'+String(index+1).padStart(2,'0')+'</span>'+title+'</button>'+cert+severityTag(r)+'</div>'+
        '<p class="region-item-description">'+escapeHTML(r.reason)+'</p><div class="region-item-meta">'+(r.text?'<code>'+escapeHTML(r.text)+'</code>':'<span></span>')+'<span class="region-actions"><button class="text-button" data-action="edit" aria-expanded="'+detail+'">'+(detail?'수정 닫기':'유형 · 좌표 수정')+'</button><button class="region-delete" data-action="delete" aria-label="'+title+' 삭제">'+icon('trash')+'</button></span></div>'+
        (detail?'<div class="region-detail"><label class="type-label">개인정보 유형<select data-region-type="true" aria-label="'+title+' 개인정보 유형">'+Object.entries(Core.TYPES).map(([key,label])=>'<option value="'+key+'" '+(r.type===key?'selected':'')+'>'+label+'</option>').join('')+'</select></label><div class="coordinate-title">원본 좌표 <span>'+state.width+' × '+state.height+' px'+(r.poly?' · 기울어진 외곽선':'')+'</span></div><div class="coordinate-editor" aria-label="원본 픽셀 좌표">'+[['x','왼쪽',px.x],['y','위쪽',px.y],['w','너비',px.width],['h','높이',px.height]].map(([key,label,value])=>'<label>'+label+'<input type="number" min="'+(['w','h'].includes(key)?1:0)+'" max="'+(['x','w'].includes(key)?state.width:state.height)+'" step="1" value="'+value+'" data-coordinate="'+key+'" aria-label="'+title+' '+label+' 픽셀">px</label>').join('')+'</div></div>':'')+'</div>';
    }).join('');
    if(focusId) {
      const row=Array.from(list.children).find(el=>el.dataset.region===focusId);
      const target=row && (focusCoordinate?$('[data-coordinate="'+focusCoordinate+'"]',row):focusType?$('[data-region-type]',row):focusAction?$('[data-action="'+focusAction+'"]',row):null);
      target?.focus({preventScroll:true});
    }
  }

  function renderReview() {
    const count=state.regions.length,selected=state.regions.filter(r=>r.enabled).length;
    const serious=state.regions.filter(r=>r.severity==='cover'||r.severity==='review').length;
    $('#resultCount').textContent=count;$('#selectedCount').textContent=selected;
    $('#resultTitle').textContent=state.analysisStatus==='empty'?'탐지된 영역이 없어요':state.analysisStatus==='manual'?'직접 가릴 정보를 선택해요':state.analysisStatus==='partial'?'일부 정보를 확인해 주세요':'확인이 필요한 정보';
    $('#reviewKicker').textContent=state.analysisStatus==='manual'?'MANUAL':Core.CONDITIONS[state.condition]||'';
    $('#reviewSubtitle').textContent=state.analysisStatus==='manual'?'직접 추가한 영역만 가려집니다. 사진 전체를 확인해 주세요.':'가림 권장 · 검토 권장 '+serious+'건. 기본으로 아무것도 고르지 않았어요. 가릴 항목을 고르세요.';
    $('#riskSummary').classList.toggle('safe',count>0&&selected===count);
    $('#riskSummaryText').textContent=count===0?'탐지 결과가 없어도 개인정보가 없다는 뜻은 아니에요.':selected===count?selected+'개 영역을 가리도록 선택했어요.':selected?(count-selected)+'개 영역은 가리지 않아요.':'아직 가릴 영역을 고르지 않았어요.';
    $('#selectAll').textContent=count>0&&selected===count?'모두 해제':'모두 선택';$('#selectAll').disabled=count===0||state.saving;
    $('#saveLabel').textContent=selected?'선택한 '+selected+'곳 가리고 저장':'메타데이터만 지우고 저장';
    $('#undoButton').disabled=!state.history.length||state.phase!=='review';
    $$('.style-options button').forEach(button=>{const on=button.dataset.style===state.style;button.classList.toggle('selected',on);button.setAttribute('aria-pressed',String(on));});
    $('#styleHint').textContent=state.style==='solid'?'선택한 영역을 검은색으로 완전히 덮어요.':'흐린 유리처럼 덮어요. 글자 위에 블러를 거는 게 아니라 주변 색으로 먼저 지운 뒤 흐리게 해서, 원래 글자를 되살릴 수 없어요.';
    $('.metadata-box p').textContent=metadataText();
    const notices=state.groups.map(g=>'함께 노출됨 · '+g).concat(state.issues);
    $('#partialNotice').classList.toggle('hidden',!notices.length);$('#partialNotice').replaceChildren(...notices.map(text=>{const p=document.createElement('p');p.textContent=text;return p;}));
    renderList();
  }

  function render() { renderImage();renderBoxes();renderReview();syncPanels(); }

  function syncDrawing() {
    $('#canvasWrap').classList.toggle('drawing',state.drawing);
    $('#drawHint').classList.toggle('hidden',!state.drawing);
    $('#drawPreview').classList.add('hidden');
    $('#addRegion').setAttribute('aria-pressed',String(state.drawing));
    if(state.drawing) {
      state.mode='original';renderImage();
      $('#toolHint').textContent='사진을 드래그해서 가릴 부분을 선택하세요.';
    } else $('#toolHint').textContent='놓친 곳은 직접 추가할 수 있어요.';
  }
  function point(event) { return Core.screenPoint(event.clientX,event.clientY,$('#canvasWrap').getBoundingClientRect()); }

  function moveGesture(event) {
    if(!gesture || event.pointerId!==gesture.pointerId) return;
    const p=point(event);
    if(gesture.type==='draw') {
      const rect={x:Math.min(gesture.start.x,p.x),y:Math.min(gesture.start.y,p.y),w:Math.abs(p.x-gesture.start.x),h:Math.abs(p.y-gesture.start.y)};
      gesture.rect=rect;
      const preview=$('#drawPreview');preview.classList.remove('hidden');Object.assign(preview.style,{left:rect.x*100+'%',top:rect.y*100+'%',width:rect.w*100+'%',height:rect.h*100+'%'});
    } else {
      const r=state.regions.find(r=>r.id===gesture.id);if(!r)return;
      const dx=p.x-gesture.start.x,dy=p.y-gesture.start.y;
      if(Math.abs(dx)+Math.abs(dy)>.003 && !gesture.changed) {pushHistory();gesture.changed=true;}
      if(!gesture.changed)return;
      if(gesture.type==='resize') {r.w=clamp(gesture.original.w+dx,.008,1-r.x);r.h=clamp(gesture.original.h+dy,.008,1-r.y);r.poly=null;}
      else {const bx=r.x,by=r.y;r.x=clamp(gesture.original.x+dx,0,1-r.w);r.y=clamp(gesture.original.y+dy,0,1-r.h);shiftPoly(r,r.x-bx,r.y-by);}
      invalidate();
      renderBoxes();
    }
  }
  function endGesture(event,cancelled=false) {
    if(!gesture || event.pointerId!==gesture.pointerId)return;
    const g=gesture;gesture=null;
    const wrap=$('#canvasWrap');if(wrap.hasPointerCapture(event.pointerId))wrap.releasePointerCapture(event.pointerId);
    $('#drawPreview').classList.add('hidden');
    if(g.type==='draw') {
      if(!cancelled && g.rect && g.rect.w>.008 && g.rect.h>.008) addRegion(g.rect);
      else if(!cancelled)notify('조금 더 넓은 영역을 드래그해 주세요.');
    } else {
      if(cancelled && g.changed) {
        state.regions=state.history.pop() || state.regions;invalidate();
      }
      render();if(!g.changed)focusRegion(g.id,'photo');
    }
  }

  /* ---------- 대기열 ----------
     OCR 은 서버에서 한 번에 하나씩 돈다. 분석·저장 요청마다 번호표를 붙여 보내고,
     기다리는 동안 '앞에 몇 건, 약 몇 초'를 보여 준다. 다른 사진을 넣거나 취소하거나
     창을 닫으면 기다리던 요청을 뺀다. */
  function renderQueue(s) {
    const badge=$('#queueBadge');badge.classList.remove('busy','ready');
    if(!s.engine_ready){$('#queueText').textContent='OCR 엔진 준비 중';badge.classList.add('busy');}
    else if(s.running+s.waiting===0){$('#queueText').textContent='대기열 비어 있음';badge.classList.add('ready');}
    else {$('#queueText').textContent='처리 중 '+s.running+' · 대기 '+s.waiting;badge.classList.add('busy');}
    badge.title=$('#queueText').textContent;
    if(!state.ticket || !s.state) return;
    const eta=s.eta_s!=null?' · 약 '+s.eta_s+'초':'';
    const text=s.state==='waiting'?'대기 '+s.ahead+'건'+eta:s.state==='running'?(s.engine_ready?(state.saving?'가리고 다시 검사하는 중':'검사하는 중'):'OCR 엔진 준비 중 (서버를 켠 뒤 처음 한 번, 1~2분)'):'사진을 올리는 중';
    if(state.phase==='scanning') {
      $('#scanPercent').textContent=s.state==='waiting'?'대기 '+s.ahead+'건':s.state==='running'?'검사 중':'올리는 중';
      $('#scanModeLabel').textContent=text;
      $('#scanTask1').classList.add('active');
      $('#scanTask2').classList.toggle('active',s.state==='running');
    }
    if(state.saving) $('#saveStateText').textContent=s.state==='waiting'?'대기 중 — 앞에 '+s.ahead+'건'+eta:text;
  }
  async function pollQueue() {
    clearTimeout(queueTimer);
    try { renderQueue(await api.queue(state.ticket)); } catch(_) { /* 다음 차례에 다시 묻는다 */ }
    if(state.ticket || document.visibilityState==='visible') queueTimer=setTimeout(pollQueue,state.ticket?1000:4000);
  }
  const pollSoon=()=>{clearTimeout(queueTimer);queueTimer=setTimeout(pollQueue,150);};

  async function prepareExport() {
    if(!state.source||state.phase!=='review'||state.saving)return;
    const token=++state.exportToken,serial=++state.requestSerial;
    state.saving=true;state.saveError='';$('#cancelExport').classList.remove('hidden');
    $('#saveState').classList.remove('hidden');$('#saveStateText').textContent='사진을 올리는 중';syncPanels();
    const boxes=Core.boxes(state),ticket=Api.newTicket();
    state.ticket=ticket;state.requestController=new AbortController();pollSoon();
    let candidateUrl;
    try {
      const file=await uploadFile();
      if(serial!==state.requestSerial)return;
      const data=await api.redact(file,boxes,state.style,{ticket,signal:state.requestController.signal});
      if(token!==state.exportToken||serial!==state.requestSerial)return;
      const bytes=Uint8Array.from(atob(data.file),c=>c.charCodeAt(0));
      const blob=new Blob([bytes],{type:'image/jpeg'});
      candidateUrl=URL.createObjectURL(blob);
      const check=await loadImage(candidateUrl);
      if(check.naturalWidth!==state.width||check.naturalHeight!==state.height)throw new Error('저장된 사진의 크기가 원본과 달라요. 다시 시도해 주세요.');
      if(token!==state.exportToken||serial!==state.requestSerial)return;
      if(state.exportUrl)URL.revokeObjectURL(state.exportUrl);
      downloadBlob=blob;state.exportUrl=candidateUrl;candidateUrl=null;$('#exportPreview').src=state.exportUrl;
      showVerdict(data.verification,boxes.length);
      showDialog('exportDialog');
    } catch(error) {
      if(serial===state.requestSerial && error.name!=='AbortError' && error.status!==409) {state.saveError=error.message||'저장하지 못했어요. 다시 시도해 주세요.';notify(state.saveError,true);}
    } finally {
      if(candidateUrl)URL.revokeObjectURL(candidateUrl);
      if(serial===state.requestSerial){state.saving=false;state.requestController=null;state.ticket=null;$('#saveState').classList.toggle('hidden',!state.saveError);$('#saveStateText').textContent=state.saveError;$('#cancelExport').classList.toggle('hidden',!!state.saveError);syncPanels();pollSoon();}
    }
  }
  // 서버가 결과 파일을 실제로 다시 읽어 검사한 결과. 통과 기준은 '선택한 영역마다 다시
  // 탐지되는 것이 없고 위치정보가 남지 않음'이다.
  function showVerdict(v,selected) {
    $('#exportOrigin').textContent='Privacy Lens 서버 처리 · 결과 파일을 다시 검사함';
    $('#exportRegionCount').textContent=selected?selected+'개 영역 · '+(state.style==='solid'?'검은색':'흐리게'):'가린 영역 없음';
    $('#exportMetadata').textContent=v.had_gps?(v.gps_removed?'위치정보 제거됨':'위치정보 남아 있음'):'원본 메타데이터 제외';
    const warning=$('#exportWarning');warning.dataset.state=v.passed?'pass':'fail';
    const rest=v.remaining_count?' 선택하지 않은 곳에 검토할 항목이 '+v.remaining_count+'건 남아 있어요.':'';
    const lines=[];
    if(v.passed) lines.push((selected?'가린 '+selected+'곳을 다시 검사했고 남은 내용이 없어요.':'메타데이터를 지웠어요.')+(v.had_gps?' 위치정보도 제거했어요.':'')+rest+' 공유 전에 사진 전체를 한 번 더 확인해 주세요.');
    else if(!v.gps_removed) lines.push('결과 파일에서 위치정보가 다시 탐지됐어요. 이 파일은 올리지 마세요.');
    else {lines.push('가린 영역 근처에서 '+v.leaked_count+'건이 다시 탐지됐어요. 영역을 더 넓게 지정해 보세요.');(v.leaked||[]).slice(0,5).forEach(f=>lines.push('· '+String(f.message||'')));}
    warning.replaceChildren(...lines.map(t=>{const p=document.createElement('p');p.textContent=t;return p;}));
  }

  function download() {
    if(!downloadBlob)return;
    const url=URL.createObjectURL(downloadBlob);
    const a=document.createElement('a');
    const base=state.name.replace(/\.[^/.]+$/,'').replace(/[<>:"/\\|?*\x00-\x1F]/g,'_').slice(0,90) || 'photo';
    a.href=url;a.download=base+'-privacy-lens.jpg';document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);
    closeDialog($('#exportDialog'));setStep(3);state.mode='protected';renderImage();if(state.previewState!=='ready')schedulePreview();
    notify('다운로드를 요청했어요. 브라우저의 다운로드 목록을 확인하세요.');
  }

  function cancelRequests() {
    if(state.ticket) api.cancel(state.ticket);
    state.ticket=null;state.requestSerial++;state.requestController?.abort();state.requestController=null;state.saving=false;state.previewSeq++;clearTimeout(previewTimer);
  }
  function imageBlob(source) {
    return new Promise((resolve,reject)=>source.toBlob(blob=>blob?resolve(blob):reject(new Error('사진을 PNG로 만들지 못했어요. 더 작은 사진으로 시도해 주세요.')),'image/png'));
  }
  function syncPanels() {
    const phase=state.phase;
    document.body.classList.toggle('has-photo',!!state.source);
    const mapping={welcomePanel:'empty',readyPanel:'ready',scanningPanel:'scanning',failurePanel:'failed',reviewPanel:'review'};
    Object.entries(mapping).forEach(([id,value])=>$('#'+id).classList.toggle('hidden',phase!==value));
    $('#scanOverlay').classList.toggle('hidden',phase!=='scanning');
    $('#addRegion').disabled=phase!=='review';
    $('#saveButton').disabled=phase!=='review'||state.saving;
    $('#imageState').inert=state.saving;
    $('#regionList').inert=state.saving;$('.redaction-settings').inert=state.saving;
    $('#payloadButton').disabled=!state.source||phase!=='review'||state.saving;
    $('#analyzeButton').disabled=!state.source||state.saving;
    $('#manualButton').disabled=state.serverImage&&state.analysisStatus==='idle';
    $('#conditionSelect').disabled=phase==='scanning'||state.saving;
    $('#readyDescription').textContent=state.serverImage&&state.analysisStatus==='idle'?'이 형식은 브라우저가 미리 보지 못해요. 분석하면 서버가 만든 미리보기로 바뀌어요.':'사진을 Privacy Lens 서버로 보내 글자를 읽고 개인정보를 판정해요. 서버는 사진을 디스크에 저장하지 않아요.';
    $('#readyFileInfo').textContent=state.width+' × '+state.height+' px';
    $('#sourceBadge').textContent=state.backend||(state.sample?'가상 샘플':'분석 전');
    const text=phase==='ready'?'미리보기 준비 완료':phase==='scanning'?'서버가 검사하는 중':phase==='failed'?'분석 실패 · 다시 시도하거나 직접 편집':state.analysisStatus==='partial'?'분석 완료 · 흐린 글자 확인 필요':state.analysisStatus==='empty'?'분석 완료 · 탐지 결과 없음':state.analysisStatus==='manual'?'수동 편집 · 자동 분석 안 함':'분석 완료';
    const took=state.elapsedMs&&phase==='review'&&state.analysisStatus!=='manual'?' · '+(state.elapsedMs/1000).toFixed(1)+'초':'';
    $('#analysisNoticeText').textContent=text+took;$('#analysisNoticeText').title=text+took;
    $('#analysisNotice').dataset.state=phase==='failed'?'error':state.analysisStatus==='partial'?'warning':'normal';
    if(phase==='ready')setStep(1);
    else if(phase==='scanning'||phase==='failed')setStep(2);
    $('#zoomOut').disabled=!state.source||state.zoom<=.5;$('#zoomIn').disabled=!state.source||state.zoom>=4;
  }
  function startManual() {
    cancelRequests();state.phase='review';state.analysisStatus='manual';state.issues=[];state.groups=[];state.mode='original';
    invalidate();render();setStep(2);notify('직접 편집 모드예요. 가릴 부분을 추가해 주세요.');
  }
  async function beginAnalysis() {
    if(!state.source||state.saving)return;
    cancelRequests();
    Object.assign(state,{regions:[],history:[],focused:null,editing:null,issues:[],groups:[],gps:[],mode:'original',phase:'scanning',analysisStatus:'running',drawing:false,previewState:'none'});
    syncDrawing();render();
    $('#scanningPanel').classList.add('server-analysis');
    $('#scanPercent').textContent='올리는 중';$('#scanModeLabel').textContent=Core.CONDITIONS[state.condition];
    [1,2,3].forEach(i=>$('#scanTask'+i).classList.remove('active'));
    const serial=++state.requestSerial,ticket=Api.newTicket();
    state.ticket=ticket;state.requestController=new AbortController();pollSoon();
    try {
      const file=await uploadFile();
      if(serial!==state.requestSerial)return;
      const data=await api.analyze(file,{mode:state.condition,ticket,signal:state.requestController.signal});
      if(serial!==state.requestSerial)return;
      $('#scanTask3').classList.add('active');
      const result=Core.fromReport(data.report);
      if(state.serverImage || result.width!==state.width || result.height!==state.height) await adoptServerImage(data.preview,result.width,result.height);
      if(serial!==state.requestSerial)return;
      Object.assign(state,{regions:result.regions,groups:result.groups,gps:result.gps,backend:result.backend,elapsedMs:result.elapsedMs,
        issues:result.partial?['일부 영역은 글자가 흐려 내용을 확인하지 못했어요. 점선 영역을 확대해서 직접 확인해 주세요.']:[],
        analysisStatus:result.regions.length?(result.partial?'partial':'completed'):'empty',phase:'review',focused:result.regions[0]?.id||null});
      invalidate();render();setStep(2);
      notify(result.regions.length?result.regions.length+'개 항목을 찾았어요. 가릴 항목을 고르세요.':'탐지된 항목이 없어요. 사진을 직접 확인해 주세요.');
    } catch(error) {if(serial===state.requestSerial && error.name!=='AbortError' && error.status!==409)analysisFailure(error.message);}
    finally {if(serial===state.requestSerial){state.requestController=null;state.ticket=null;pollSoon();}}
  }
  function analysisFailure(message) {
    state.phase='failed';state.analysisStatus='failed';$('#failureMessage').textContent=message;
    render();notify('분석하지 못했어요. 재시도하거나 직접 편집할 수 있어요.',true);
  }
  function layoutCanvas(preserve=true) {
    if(!state.source)return;
    const viewport=$('#canvasStage'),wrap=$('#canvasWrap'),sizer=$('#canvasSizer');
    const width=Math.max(120,viewport.clientWidth-32),height=Math.max(180,viewport.clientHeight-32);
    const fit=Math.min(width/state.width,height/state.height,1);
    const oldRect=wrap.getBoundingClientRect(),vp=viewport.getBoundingClientRect();
    const center=preserve&&oldRect.width?Core.screenPoint(vp.left+viewport.clientWidth/2,vp.top+viewport.clientHeight/2,oldRect):{x:.5,y:.5};
    const w=state.width*fit*state.zoom,h=state.height*fit*state.zoom;
    const sw=Math.max(width,w),sh=Math.max(height,h);
    sizer.style.width=sw+'px';sizer.style.height=sh+'px';
    wrap.style.width=w+'px';wrap.style.height=h+'px';wrap.style.maxWidth='none';
    viewport.scrollLeft=(sw-w)/2+w*center.x-width/2;viewport.scrollTop=(sh-h)/2+h*center.y-height/2;
    $('#zoomValue').textContent=Math.round(state.zoom*100)+'%';
    $('#zoomValue').title='화면 맞춤 대비 확대 비율 · 실제 원본 대비 '+Math.round(fit*state.zoom*100)+'%';
    $('#zoomOut').disabled=state.zoom<=.5;$('#zoomIn').disabled=state.zoom>=4;
    declutterTags();
  }
  function zoomTo(value) {state.zoom=clamp(value,.5,4);layoutCanvas();}
  function focusRegion(id,origin='list') {
    const r=state.regions.find(r=>r.id===id);if(!r)return;
    state.focused=id;state.mode='original';render();
    if(origin==='list') {
      const box=$$('.region-box').find(el=>el.dataset.id===id),viewport=$('#canvasStage');
      if(box){const b=box.getBoundingClientRect(),v=viewport.getBoundingClientRect();viewport.scrollLeft+=b.left+b.width/2-v.left-viewport.clientWidth/2;viewport.scrollTop+=b.top+b.height/2-v.top-viewport.clientHeight/2;}
    } else {
      const row=$$('.region-item').find(el=>el.dataset.region===id);
      if(row){const list=$('#regionList');list.scrollTop=row.offsetTop-list.offsetTop;}
    }
  }
  function openPayload() {
    if(!state.source)return;
    const payload=Core.payload(state);$('#payloadJson').textContent=JSON.stringify(payload,null,2);
    $('#payloadSummary').textContent='선택한 '+payload.boxes.length+'개 영역 · 원본 '+state.width+' × '+state.height+' px · 이미지 데이터와 인식된 글자는 들어 있지 않아요.';
    showDialog('payloadDialog');
  }
  function savePayload() {
    const blob=new Blob([JSON.stringify(Core.payload(state),null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='privacy-lens-regions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);notify('영역 JSON 다운로드를 요청했어요.');
  }

  function applyCoordinateInput(input,commit=false) {
    const row=input.closest('[data-region]'),key=input.dataset.coordinate;
    const region=state.regions.find(r=>r.id===row?.dataset.region);
    if(!region||!key)return;
    const value=Number(input.value);
    if(input.value===''||!Number.isFinite(value)){if(commit)renderList();return;}
    const box=Core.toPixels(region,state.width,state.height),v=Math.round(value);
    if(key==='x')box.x=clamp(v,0,state.width-box.width);
    if(key==='y')box.y=clamp(v,0,state.height-box.height);
    if(key==='w')box.width=clamp(v,1,state.width-box.x);
    if(key==='h')box.height=clamp(v,1,state.height-box.y);
    const next=Core.fromPixels(box,state.width,state.height);
    if(['x','y','w','h'].some(k=>region[k]!==next[k])){
      if(!input.dataset.historySaved){pushHistory();input.dataset.historySaved='true';}
      if(key==='w'||key==='h')region.poly=null;else shiftPoly(region,next.x-region.x,next.y-region.y);
      Object.assign(region,next);invalidate();renderImage();renderBoxes();
    }
    if(commit)renderReview();
  }

  $$('[data-dialog]').forEach(button=>button.addEventListener('click',()=>showDialog(button.dataset.dialog)));
  $$('[data-close]').forEach(button=>button.addEventListener('click',()=>closeDialog(button.closest('dialog'))));
  $$('dialog').forEach(dialog=>{
    dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom)closeDialog(dialog);}});
    dialog.addEventListener('close',()=>{if(dialog.id==='exportDialog')releaseExport();});
  });
  $('#workspaceNav').addEventListener('click',()=>{$('#workspace').scrollIntoView({behavior:'smooth',block:'start'});});
  $('#changePhoto').addEventListener('click',()=>{reset();notify('새 사진이나 샘플을 선택해 주세요.');});
  $('#fileInput').addEventListener('change',event=>loadFile(event.target.files[0]));
  $('#dropzone').addEventListener('click',()=>$('#fileInput').click());
  $('#dropzone').addEventListener('keydown',event=>{if(event.key==='Enter' || event.key===' '){event.preventDefault();$('#fileInput').click();}});
  ['dragenter','dragover'].forEach(name=>$('#dropzone').addEventListener(name,event=>{event.preventDefault();$('#dropzone').classList.add('dragover');}));
  $('#dropzone').addEventListener('dragleave',event=>{if(!$('#dropzone').contains(event.relatedTarget))$('#dropzone').classList.remove('dragover');});
  $('#dropzone').addEventListener('drop',event=>{event.preventDefault();$('#dropzone').classList.remove('dragover');if(event.dataTransfer.files.length>1)notify('한 번에 한 장씩 편집해요. 첫 번째 사진을 불러올게요.');loadFile(event.dataTransfer.files[0]);});
  document.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
  document.addEventListener('drop',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
  $$('[data-sample]').forEach(button=>button.addEventListener('click',()=>loadSample(button.dataset.sample)));
  $('#cancelScan').addEventListener('click',()=>{cancelRequests();state.phase='ready';state.analysisStatus='idle';render();notify('분석 요청을 취소했어요. 다시 시작할 수 있어요.');});
  $$('[data-view]').forEach(button=>button.addEventListener('click',()=>{state.mode=button.dataset.view;state.drawing=false;syncDrawing();renderImage();if(state.mode!=='original'&&state.previewState!=='ready'&&state.previewState!=='loading')schedulePreview();}));
  $('#compareSlider').addEventListener('input',event=>{state.compare=Number(event.target.value);renderImage();});
  $$('[data-style]').forEach(button=>button.addEventListener('click',()=>{
    state.style=button.dataset.style;try{localStorage.setItem('pl.maskStyle',state.style);}catch(_){}
    state.mode='protected';state.drawing=false;syncDrawing();invalidate();render();
  }));
  $('#selectAll').addEventListener('click',()=>{if(!state.regions.length)return;pushHistory();const all=state.regions.every(r=>r.enabled);state.regions.forEach(r=>r.enabled=!all);invalidate();render();});
  $('#regionList').addEventListener('click',event=>{
    const control=event.target.closest('[data-action]');if(!control || control.dataset.action==='toggle')return;
    const row=control.closest('[data-region]');const region=state.regions.find(r=>r.id===row.dataset.region);if(!region)return;
    if(control.dataset.action==='delete') {pushHistory();state.regions=state.regions.filter(r=>r.id!==region.id);if(state.focused===region.id)state.focused=null;invalidate();render();notify('영역을 삭제했어요. 되돌리기로 복원할 수 있어요.');}
    if(control.dataset.action==='focus') focusRegion(region.id);
    if(control.dataset.action==='edit') {state.editing=state.editing===region.id?null:region.id;focusRegion(region.id);}
  });
  $('#regionList').addEventListener('change',event=>{
    const row=event.target.closest('[data-region]');if(!row)return;
    const region=state.regions.find(r=>r.id===row.dataset.region);if(!region)return;
    if(event.target.dataset.action==='toggle') {pushHistory();region.enabled=event.target.checked;invalidate();render();}
    if(event.target.dataset.regionType){pushHistory();region.type=event.target.value;invalidate();render();}
    if(event.target.dataset.coordinate)applyCoordinateInput(event.target,true);
  });
  $('#regionList').addEventListener('input',event=>{if(event.target.dataset.coordinate)applyCoordinateInput(event.target);});
  $('#addRegion').addEventListener('click',()=>{state.drawing=!state.drawing;syncDrawing();});
  $('#cancelDraw').addEventListener('click',()=>{state.drawing=false;syncDrawing();});
  $('#centerRegion').addEventListener('click',()=>addRegion({x:.35,y:.4,w:.3,h:.2}));
  $('#undoButton').addEventListener('click',()=>{if(!state.history.length)return;state.regions=state.history.pop();if(!state.regions.some(r=>r.id===state.focused))state.focused=null;invalidate();render();notify('이전 영역 설정으로 되돌렸어요.');});
  $('#canvasWrap').addEventListener('pointerdown',event=>{
    if(!state.source || state.phase!=='review' || state.mode!=='original' || event.button!==0)return;
    const wrap=$('#canvasWrap'),p=point(event);
    if(state.drawing) {event.preventDefault();gesture={type:'draw',start:p,pointerId:event.pointerId};wrap.setPointerCapture(event.pointerId);return;}
    const box=event.target.closest('.region-box');if(!box)return;
    event.preventDefault();
    const region=state.regions.find(r=>r.id===box.dataset.id);if(!region)return;
    state.focused=region.id;renderReview();
    $$('.region-box').forEach(el=>el.classList.toggle('focused',el.dataset.id===region.id));
    gesture={type:event.target.dataset.resize?'resize':'move',id:region.id,start:p,original:clone(region),changed:false,pointerId:event.pointerId};
    wrap.setPointerCapture(event.pointerId);
  });
  $('#canvasWrap').addEventListener('pointermove',moveGesture);
  $('#canvasWrap').addEventListener('pointerup',event=>endGesture(event));
  $('#canvasWrap').addEventListener('pointercancel',event=>endGesture(event,true));
  $('#regionLayer').addEventListener('keydown',event=>{
    const box=event.target.closest('.region-box');if(!box)return;
    const r=state.regions.find(r=>r.id===box.dataset.id);if(!r)return;
    if(event.key==='Enter' || event.key===' '){event.preventDefault();focusRegion(r.id,'photo');return;}
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
    event.preventDefault();pushHistory();
    const amount = event.shiftKey ? .001 : .01;
    if(event.altKey){if(event.key==='ArrowLeft')r.w-=amount;if(event.key==='ArrowRight')r.w+=amount;if(event.key==='ArrowUp')r.h-=amount;if(event.key==='ArrowDown')r.h+=amount;r.w=clamp(r.w,.008,1-r.x);r.h=clamp(r.h,.008,1-r.y);r.poly=null;}
    else{const bx=r.x,by=r.y;if(event.key==='ArrowLeft')r.x-=amount;if(event.key==='ArrowRight')r.x+=amount;if(event.key==='ArrowUp')r.y-=amount;if(event.key==='ArrowDown')r.y+=amount;r.x=clamp(r.x,0,1-r.w);r.y=clamp(r.y,0,1-r.h);shiftPoly(r,r.x-bx,r.y-by);}
    state.focused=r.id;invalidate();render();$$('.region-box').find(el=>el.dataset.id===r.id)?.focus({preventScroll:true});
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && state.drawing){state.drawing=false;gesture=null;syncDrawing();}});
  $('#saveButton').addEventListener('click',prepareExport);
  $('#downloadButton').addEventListener('click',download);
  // 서버가 실제로 찾는 항목(pipeline/kr_patterns.py, metadata.py)
  const targets=[['id','이름','받는분·성명 같은 라벨 바로 뒤'],['box','연락처','휴대전화 · 유선 · 이메일. 대표번호는 참고로'],['pin','주소','도로명주소 · 동·호수'],['lock','주민등록번호','체크섬 · 2020년 이후 형식'],['file','카드번호','Luhn 검증'],['box','운송장번호','운송장 라벨 옆 긴 숫자'],['file','차량번호','실제 번호판 글자만'],['grid','QR · 바코드','안의 내용까지 검사, 링크는 열지 않음'],['pin','위치정보','사진 파일의 GPS 좌표']];
  $('#targetsGrid').innerHTML=targets.map(([symbol,label,detail])=>'<div class="target-tile">'+icon(symbol)+'<h3>'+label+'</h3><p>'+detail+'</p></div>').join('');

  $('#analyzeButton').addEventListener('click',()=>beginAnalysis());
  $('#manualButton').addEventListener('click',startManual);$('#failureManual').addEventListener('click',startManual);
  $('#retryAnalysis').addEventListener('click',()=>beginAnalysis());
  $('#conditionSelect').addEventListener('change',event=>{state.condition=event.target.value;if(state.source&&(state.phase==='review'||state.phase==='failed')&&state.analysisStatus!=='manual')beginAnalysis();});
  $('#zoomIn').addEventListener('click',()=>zoomTo(state.zoom+.25));$('#zoomOut').addEventListener('click',()=>zoomTo(state.zoom-.25));
  $('#zoomFit').addEventListener('click',()=>{state.zoom=1;layoutCanvas(false);});
  new ResizeObserver(()=>layoutCanvas()).observe($('#canvasStage'));
  $('#payloadButton').addEventListener('click',openPayload);$('#downloadPayload').addEventListener('click',savePayload);
  $('#cancelExport').addEventListener('click',()=>{cancelRequests();state.exportToken++;$('#saveState').classList.add('hidden');syncPanels();notify('저장 요청을 취소했어요. 편집 내용은 유지돼요.');});
  $('.brand').addEventListener('click',event=>{event.preventDefault();reset();});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')pollSoon();});
  window.addEventListener('pagehide',()=>{if(state.ticket)api.cancel(state.ticket);});

  initializeThumbnails();
  setStep(1);syncPanels();pollQueue();
})();
