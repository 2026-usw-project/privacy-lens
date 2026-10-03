'use strict';
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const icon = name => '<svg aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const escapeHTML = text => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const clone = value => JSON.parse(JSON.stringify(value));
  const state = { source: null, phase: 'empty', regions: [], focused: null, history: [], mode: 'original', style: 'pixel', strength: 80, compare: 50, drawing: false, sample: false, sampleKey: null, width: 0, height: 0, name: '', bytes: 0, metadata: null, timer: null, loadToken: 0, exportToken: 0, exportUrl: null, nextId: 1, toastTimer: null };
  const canvas = $('#photoCanvas');
  const ctx = canvas.getContext('2d');
  const protectedCanvas = document.createElement('canvas');
  const protectedContext = protectedCanvas.getContext('2d');
  let protectedDirty = true;
  let gesture = null;
  let downloadBlob = null;
  let dialogReturnFocus = null;
  const fixtures = new Map();
  const Core=PrivacyLensCore;
  Object.assign(state,{connection:'demo',endpoint:'',analysisStatus:'idle',analysisId:null,scenario:'normal',zoom:1,guided:false,demoProgress:{},issues:[],requestController:null,requestSerial:0,saving:false,saveError:'',editing:null});

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
  function invalidate() { protectedDirty = true; state.exportToken++; if (state.source && state.phase === 'review') setStep(2); }
  function pushHistory() {
    state.history.push(clone(state.regions));
    if (state.history.length > 35) state.history.shift();
    $('#undoButton').disabled = false;
  }
  function stopScan() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }
  function releaseExport() {
    state.exportToken++;
    if (state.exportUrl) URL.revokeObjectURL(state.exportUrl);
    state.exportUrl = null;
    downloadBlob = null;
    $('#exportPreview').removeAttribute('src');
  }
  function reset() {
    stopScan();cancelRequests();state.zoom=1;state.analysisStatus='idle';state.guided=false;state.issues=[];
    state.loadToken++;
    state.exportToken++;
    releaseExport();
    state.source = null;
    state.phase = 'empty';
    state.regions = [];
    state.history = [];
    state.focused = null;
    state.drawing = false;
    state.sampleKey = null;
    state.nextId = 1;
    state.mode = 'original';
    gesture = null;
    canvas.width = canvas.height = 1;
    protectedCanvas.width = protectedCanvas.height = 1;
    $('#fileInput').value = '';
    $('#emptyState').classList.remove('hidden');
    $('#imageState').classList.add('hidden');
    $('#welcomePanel').classList.remove('hidden');
    $('#scanningPanel').classList.add('hidden');
    $('#reviewPanel').classList.add('hidden');
    $('#changePhoto').classList.add('hidden');
    $('#fileInfo').classList.remove('hidden');
    $('#editorTitle').textContent = '사진 작업 공간';
    $('#regionLayer').replaceChildren();
    $('#undoButton').disabled = true;
    $('#addRegion').disabled = false;
    setStep(1);
    syncDrawing();syncPanels();updateGuide();$('#saveState').classList.add('hidden');
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
    const region = normalizeRegion({ id: 'custom-' + number, x: rect.x, y: rect.y, w: rect.w, h: rect.h, label: '직접 지정한 영역 ' + number, reason: '직접 선택한 정보예요. 크기와 위치를 조절해 충분히 가려 주세요.', text: '수동 지정', kind: 'manual', type: 'CUSTOM', ocrStatus: 'ok', enabled: true });
    state.regions.push(region);state.demoProgress.added=true;
    state.focused = state.editing = region.id;
    state.drawing = false;
    invalidate();
    syncDrawing();
    render();
    notify('가릴 영역을 추가했어요. 테두리를 끌어 위치를 조절할 수 있어요.');
  }

  // Synthetic document fixtures, not real photographs or real personal information.
  // These canvases are functional OCR/detection test documents used by the demo.
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
    write(c, 'DEMO-0000-2026', 35, 145, 22, '#79896e', 600);
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
    write(c, '배송 메모', 38, 513, 22, '#7c8871'); write(c, '문 앞에 놓아 주세요.', 208, 513, 24, '#617053');
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
    write(c,'이안심',235,195,39,'#29482f',700);
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
    if(key==='portrait'){const base=makeFixture('parcel');const image=document.createElement('canvas');image.width=900;image.height=1400;const c=image.getContext('2d');c.fillStyle='#e8eddf';c.fillRect(0,0,900,1400);write(c,'PORTRAIT SAMPLE',42,88,30,'#657a53',600);write(c,'세로 이미지 · 좌표 확인용',42,137,24,'#879a75');c.drawImage(base.image,30,260,840,840*1000/1440);const regions=base.regions.map(r=>({...r,id:'portrait-'+r.id,x:(30+r.x*840)/900,y:(260+r.y*840*1000/1440)/1400,w:r.w*840/900,h:r.h*840*1000/1440/1400}));const fixture={image,regions};fixtures.set(key,fixture);return fixture;}
    const image = document.createElement('canvas'); image.width = 1440; image.height = 1000;
    const c = image.getContext('2d');
    c.fillStyle = key === 'student' ? '#e8eddf' : '#edece3'; c.fillRect(0,0,1440,1000);
    write(c,'PRIVACY LENS  /  SAMPLE DOCUMENT',65,75,18,'#929e83',600);
    write(c,'실제 개인정보가 없는 테스트 이미지',65,115,20,'#7e8d6f');
    write(c,'2026',1300,75,18,'#9ba68e');
    const regions = [];
    function region(id,label,reason,text,x,y,w,h,kind='high') {
      regions.push({id,label,reason,text,x:x/1440,y:y/1000,w:w/1440,h:h/1000,kind,enabled:true});
    }
    if(key === 'parcel') {
      parcelDocument(c,195,235);
      region('name','받는 사람 이름','이름이 주소와 함께 노출되면 특정인을 식별할 수 있어요.','김○○',392,424,166,63);
      region('phone','휴대전화 번호','공개된 연락처는 원치 않는 연락에 이용될 수 있어요.','010-****-0000',925,424,304,63);
      region('address','상세 배송 주소','집 주소와 동·호수가 드러나면 거주 위치를 알 수 있어요.','가상시 안심구 · 상세 주소',392,512,813,96);
    } else if(key === 'student') {
      studentDocument(c,245,260,1.32);
      region('student-name','학생 이름','이름과 소속 학교가 함께 공개될 수 있어요.','이○○',245+226*1.32,260+151*1.32,290*1.32,59*1.32);
      region('student-id','학번 · 소속 학과','학번과 소속은 개인을 구분하는 단서가 될 수 있어요.','2026****** · 정보보안학과',245+226*1.32,260+223*1.32,414*1.32,92*1.32);
      region('student-code','학생증 바코드','바코드에 식별 정보가 포함될 수 있어 함께 가려 주세요.','학생증 식별 코드',245+226*1.32,260+332*1.32,430*1.32,51*1.32);
    } else {
      parcelDocument(c,65,230,.76);
      studentDocument(c,920,240,.62);
      screenDocument(c,920,595,.72);
      region('mixed-name','송장 · 이름과 연락처','작게 보이는 송장에도 수신인의 정보가 담겨 있어요.','이름 · 휴대전화',65+194*.76,230+187*.76,830*.76,63*.76);
      region('mixed-address','송장 · 상세 주소','배경 문서의 주소도 거주 위치를 노출할 수 있어요.','가상시 안심구 · 상세 주소',65+194*.76,230+277*.76,830*.76,100*.76);
      region('mixed-student','학생증 · 이름과 학번','학생증을 확대하면 이름과 학번을 확인할 수 있어요.','이름 · 학번 · 학과',920+219*.62,240+145*.62,454*.62,238*.62);
      region('mixed-school','학생증 · 학교 이름','학교 이름이 개인의 소속을 드러낼 수 있어요.','가상대학교',920+28*.62,240+18*.62,420*.62,71*.62);
      region('mixed-email','화면 문서 · 이메일','작은 화면에 적힌 이메일도 개인을 연결하는 단서예요.','l***@example.com',920+21*.72,595+130*.72,560*.72,60*.72);
    }
    write(c,'SYNTHETIC DATA',65,945,16,'#a0aa93',500);
    write(c,'사진 속 위험 영역 확인을 위한 데모 문서',935,945,16,'#9ca78e');
    const fixture = {image, regions};fixtures.set(key,fixture);return fixture;
  }
  function initializeThumbnails() {
    ['parcel','student','mixed'].forEach(key => {
      const fixture = makeFixture(key);
      const thumb = $('#thumb-' + key);
      thumb.getContext('2d').drawImage(fixture.image,0,0,thumb.width,thumb.height);
    });
  }

  // Header-only metadata inspection. No location values or personal text are extracted.
  function inspectMetadata(buffer, type) {
    const bytes = new Uint8Array(buffer);
    const info = { exif: false, gps: false, camera: false, date: false, status: 'unknown' };
    if(type !== 'image/jpeg') { info.status = 'unsupported'; return info; }
    try {
      const view = new DataView(buffer);
      let offset = 2;
      while(offset + 4 <= bytes.length) {
        if(bytes[offset] !== 255) break;
        const marker = bytes[offset+1];
        if(marker === 218 || marker === 217) break;
        if(marker === 0 || marker === 255) { offset++; continue; }
        if(marker >= 208 && marker <= 215) { offset += 2; continue; }
        const size = view.getUint16(offset+2);
        if(size < 2 || offset + 2 + size > bytes.length) break;
        const start = offset + 4;
        const end = offset + 2 + size;
        if(marker === 225 && size >= 16 && bytes[start] === 69 && bytes[start+1] === 120 && bytes[start+2] === 105 && bytes[start+3] === 102 && bytes[start+4] === 0 && bytes[start+5] === 0) {
          info.exif = true;
          const base = start + 6;
          const order = view.getUint16(base);
          if(order !== 0x4949 && order !== 0x4d4d) { offset = end; continue; }
          const le = order === 0x4949;
          if(view.getUint16(base+2,le)!==42) { offset=end; continue; }
          const visited = new Set();
          function readIFD(relative, depth = 0) {
            const pos = base + relative;
            if(depth > 2 || visited.has(pos) || relative < 8 || pos + 2 > end) return;
            visited.add(pos);
            const count = Math.min(view.getUint16(pos,le),512);
            for(let i=0;i<count;i++) {
              const entry = pos + 2 + i*12;
              if(entry+12>end) return;
              const tag = view.getUint16(entry,le);
              if(tag===0x8825 && view.getUint32(entry+8,le)>0) info.gps = true;
              if(tag===0x010f || tag===0x0110) info.camera = true;
              if(tag===0x0132 || tag===0x9003 || tag===0x9004) info.date = true;
              if(tag===0x8769) readIFD(view.getUint32(entry+8,le),depth+1);
            }
          }
          readIFD(view.getUint32(base+4,le));
        }
        offset = end;
      }
      info.status = 'checked';
    } catch (_) { info.status = 'partial'; }
    return info;
  }
  function sniffType(bytes) {
    if(bytes[0]===255 && bytes[1]===216 && bytes[2]===255) return 'image/jpeg';
    if(bytes[0]===137 && bytes[1]===80 && bytes[2]===78 && bytes[3]===71 && bytes[4]===13 && bytes[5]===10 && bytes[6]===26 && bytes[7]===10) return 'image/png';
    if(bytes[0]===82 && bytes[1]===73 && bytes[2]===70 && bytes[3]===70 && bytes[8]===87 && bytes[9]===69 && bytes[10]===66 && bytes[11]===80) return 'image/webp';
    return null;
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
      if(!type) throw new Error('JPG, PNG, WEBP 사진만 선택할 수 있어요.');
      const metadata = inspectMetadata(buffer,type);
      objectUrl = URL.createObjectURL(new Blob([buffer],{type}));
      const image = new Image();
      image.src = objectUrl;
      await image.decode();
      if(token !== state.loadToken) return;
      if(!image.naturalWidth || !image.naturalHeight) throw new Error('사진을 읽을 수 없어요. 다른 파일을 선택해 주세요.');
      if(image.naturalWidth*image.naturalHeight > 24e6 || image.naturalWidth > 16384 || image.naturalHeight > 16384) throw new Error('사진 크기가 너무 커요. 24 MP 이하, 한 변 16,384 px 이하로 줄여 주세요.');
      // Freeze the decoded frame. Output has no dependency on an object URL or animation.
      const frozen = document.createElement('canvas');
      frozen.width=image.naturalWidth;frozen.height=image.naturalHeight;
      frozen.getContext('2d').drawImage(image,0,0);
      stopScan();cancelRequests();
      state.source=frozen;state.width=frozen.width;state.height=frozen.height;
      state.name=file.name;state.bytes=file.size;state.sample=false;state.sampleKey=null;state.metadata=metadata;
      state.regions=[];state.history=[];state.focused=null;state.nextId=1;state.mode='original';state.phase='ready';state.drawing=false;state.zoom=1;state.analysisStatus='idle';state.analysisId=null;state.issues=[];state.guided=false;
      releaseExport();invalidate();showImage();render();
      setConnectionCopy();notify('사진 미리보기가 준비됐어요. 분석 또는 직접 편집을 선택하세요.');
    } catch(error) {
      if(token === state.loadToken) notify(error.message && !/decode/i.test(error.message) ? error.message : '손상되었거나 지원되지 않는 사진이에요. 다른 파일을 선택해 주세요.',true);
    } finally {
      if(objectUrl) URL.revokeObjectURL(objectUrl);
      $('#fileInput').value='';
    }
  }
  function loadSample(key, options = {}) {
    if(!['parcel','student','mixed','portrait'].includes(key))return;
    state.loadToken++;stopScan();cancelRequests();releaseExport();
    const fixture=makeFixture(key);
    state.source=fixture.image;state.width=fixture.image.width;state.height=fixture.image.height;
    state.name={parcel:'sample_delivery.png',student:'sample_student_id.png',mixed:'sample_documents.png',portrait:'sample_portrait.png'}[key];
    state.bytes=0;state.sample=true;state.sampleKey=key;state.metadata=null;state.regions=[];state.history=[];state.focused=null;state.nextId=1;state.mode='original';state.drawing=false;state.phase='ready';state.analysisStatus='idle';state.analysisId=null;state.issues=[];state.zoom=1;
    state.guided=!!options.guided;state.demoProgress={};
    invalidate();showImage();render();layoutCanvas(false);
    if(options.auto)beginAnalysis();
  }

  function showImage() {
    canvas.width=protectedCanvas.width=state.width;canvas.height=protectedCanvas.height=state.height;
    $('#emptyState').classList.add('hidden');$('#imageState').classList.remove('hidden');
    $('#changePhoto').classList.remove('hidden');$('#fileInfo').classList.add('hidden');
    $('#editorTitle').textContent=state.name;$('#editorTitle').title=state.name;
    $('#imageDimensions').textContent=state.width.toLocaleString()+' × '+state.height.toLocaleString()+' px'+(state.bytes?' · '+(state.bytes/1024/1024).toFixed(1)+' MB':' · 가상 데이터');
    $('#saveLabel').textContent='가린 사진 저장하기';$('#undoButton').disabled=!state.history.length;
    syncDrawing();setConnectionCopy();syncPanels();layoutCanvas(false);
  }

  function drawProtected() {
    if(!state.source || !protectedDirty) return;
    const c=protectedContext;
    c.clearRect(0,0,state.width,state.height);
    c.drawImage(state.source,0,0,state.width,state.height);
    state.regions.filter(r=>r.enabled).forEach(r=>{
      const {x,y,width:w,height:h}=Core.toPixels(r,state.width,state.height);
      if(w<=0 || h<=0) return;
      if(state.style==='solid') { c.fillStyle='#1f1d1a';c.fillRect(x,y,w,h);return; }
      if(state.style==='blur' && 'filter' in c) {
        c.save();c.beginPath();c.rect(x,y,w,h);c.clip();
        c.filter='blur('+Math.max(12,Math.round(Math.min(state.width,state.height)*(.015+state.strength*.00045)))+'px)';
        c.drawImage(state.source,0,0,state.width,state.height);c.restore();return;
      }
      const block=Math.max(10,Math.round(Math.min(state.width,state.height)*(.012+state.strength*.00035)));
      const small=document.createElement('canvas');
      small.width=Math.max(1,Math.ceil(w/block));small.height=Math.max(1,Math.ceil(h/block));
      const sc=small.getContext('2d');sc.drawImage(state.source,x,y,w,h,0,0,small.width,small.height);
      c.save();c.imageSmoothingEnabled=false;c.drawImage(small,0,0,small.width,small.height,x,y,w,h);c.restore();
    });
    protectedDirty=false;
  }
  function renderImage() {
    if(!state.source) return;
    ctx.clearRect(0,0,state.width,state.height);
    if(state.mode==='original') {
      ctx.drawImage(state.source,0,0,state.width,state.height);
    } else {
      drawProtected();
      ctx.drawImage(protectedCanvas,0,0);
      if(state.mode==='compare') {
        const split=state.width*state.compare/100;
        ctx.save();ctx.beginPath();ctx.rect(0,0,split,state.height);ctx.clip();ctx.drawImage(state.source,0,0,state.width,state.height);ctx.restore();
        ctx.fillStyle='#fff';ctx.fillRect(split-1.5,0,3,state.height);
        ctx.beginPath();ctx.arc(split,state.height/2,Math.max(10,state.width*.018),0,Math.PI*2);ctx.fill();
        const s=Math.max(4,state.width*.004);ctx.strokeStyle='#ef5a1c';ctx.lineWidth=Math.max(2,state.width*.0012);
        ctx.beginPath();ctx.moveTo(split-s,state.height/2-s);ctx.lineTo(split-s,state.height/2+s);ctx.moveTo(split+s,state.height/2-s);ctx.lineTo(split+s,state.height/2+s);ctx.stroke();
      }
    }
    $('#canvasCaption').textContent={original:'ORIGINAL · 위험 영역',protected:'PROTECTED · 가림 결과',compare:'BEFORE / AFTER'}[state.mode];
    $('#regionLayer').classList.toggle('hidden',state.mode!=='original' || state.phase==='scanning');
    $('#compareControl').classList.toggle('hidden',state.mode!=='compare');
    $$('[data-view]').forEach(button=>{const active=button.dataset.view===state.mode;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));button.disabled=state.phase==='scanning';});
  }
  function renderBoxes() {
    const layer=$('#regionLayer');layer.replaceChildren();
    state.regions.forEach((r,i)=>{
      const box=document.createElement('button');
      box.className='region-box'+(!r.enabled?' unselected':'')+(state.focused===r.id?' focused':'');
      box.dataset.id=r.id;
      box.setAttribute('aria-pressed',String(state.focused===r.id));
      box.setAttribute('aria-label',r.label+' 영역. 방향키로 이동, Alt와 방향키로 크기 조절');
      box.title=r.label+' · 끌어서 이동, 모서리를 끌어 크기 조절';
      box.style.left=(r.x*100)+'%';box.style.top=(r.y*100)+'%';box.style.width=(r.w*100)+'%';box.style.height=(r.h*100)+'%';
      const label=document.createElement('span'),num=document.createElement('b'),name=document.createElement('span');num.textContent=String(i+1).padStart(2,'0');name.className='name';name.textContent=r.label;label.append(num,name);box.append(label);
      const handle=document.createElement('i');handle.className='resize-handle';handle.dataset.resize='true';box.append(handle);
      layer.append(box);
    });
  }
  function metadataText() {
    if(state.sample) return '샘플 문서 · 촬영 메타데이터 없음';
    const m=state.metadata;
    if(!m || m.status==='unsupported') return '이 형식의 원본 메타데이터는 검사하지 않았어요. 저장 시 새 이미지로 변환해요.';
    if(m.status==='partial') return '일부 메타데이터를 읽지 못했어요. 저장 파일에는 원본 정보를 복사하지 않아요.';
    if(!m.exif) return 'JPEG EXIF 태그가 확인되지 않았어요. 다른 종류의 숨은 정보는 검사하지 않아요.';
    const tags=[m.gps?'위치 태그':null,m.camera?'기기 태그':null,m.date?'촬영 시각 태그':null].filter(Boolean);
    return '원본 EXIF 감지'+(tags.length?' · '+tags.join(' · '):'')+' — 저장 시 제외';
  }
  function renderList() {
    const list=$('#regionList'),active=document.activeElement;
    const focusId=active?.closest('[data-region]')?.dataset.region,focusAction=active?.dataset.action,focusCoordinate=active?.dataset.coordinate,focusType=active?.dataset.regionType;
    if(!state.regions.length) {
      list.innerHTML='<div class="empty-regions">'+icon('scan')+'<p>'+(state.analysisStatus==='empty'?'탐지된 영역이 없어요.<br>안전하다는 뜻은 아니에요. 사진을 확인하고<br>놓친 부분은 직접 추가해 주세요.':'현재 지정한 영역이 없어요.<br>‘영역 추가’로 가릴 부분을 선택해 주세요.')+'</p></div>';return;
    }
    list.innerHTML=state.regions.map((r,index)=>{
      const focused=state.focused===r.id,detail=state.editing===r.id,title=escapeHTML(r.label),px=Core.toPixels(r,state.width,state.height);
      return '<div class="region-item'+(focused?' selected-detail':'')+(detail?' editing':'')+'" data-region="'+escapeHTML(r.id)+'">'+
        '<div class="region-item-top"><input type="checkbox" data-action="toggle" '+(r.enabled?'checked ':'')+'aria-label="'+title+' 가리기"><button class="region-item-name" data-action="focus" aria-pressed="'+focused+'"><span class="row-number">'+String(index+1).padStart(2,'0')+'</span>'+title+'</button><span class="risk-tag'+(r.kind==='manual'?' manual':'')+'">'+(r.ocrStatus==='failed'?'판독 실패':r.kind==='manual'?'직접 추가':Core.TYPES[r.type]||'문서')+'</span></div>'+
        '<p class="region-item-description">'+escapeHTML(r.reason)+'</p><div class="region-item-meta"><code>'+escapeHTML(r.text)+'</code><span class="region-actions"><button class="text-button" data-action="edit" aria-expanded="'+detail+'">'+(detail?'수정 닫기':'유형 · 좌표 수정')+'</button><button class="region-delete" data-action="delete" aria-label="'+title+' 삭제">'+icon('trash')+'</button></span></div>'+
        (detail?'<div class="region-detail"><label class="type-label">개인정보 유형<select data-region-type="true" aria-label="'+title+' 개인정보 유형">'+Object.entries(Core.TYPES).map(([key,label])=>'<option value="'+key+'" '+(r.type===key?'selected':'')+'>'+label+'</option>').join('')+'</select></label><div class="coordinate-title">원본 좌표 <span>'+state.width+' × '+state.height+' px</span></div><div class="coordinate-editor" aria-label="원본 픽셀 좌표">'+[['x','왼쪽',px.x],['y','위쪽',px.y],['w','너비',px.width],['h','높이',px.height]].map(([key,label,value])=>'<label>'+label+'<input type="number" min="'+(['w','h'].includes(key)?1:0)+'" max="'+(['x','w'].includes(key)?state.width:state.height)+'" step="1" value="'+value+'" data-coordinate="'+key+'" aria-label="'+title+' '+label+' 픽셀">px</label>').join('')+'</div></div>':'')+'</div>';
    }).join('');
    if(focusId) {
      const row=Array.from(list.children).find(el=>el.dataset.region===focusId);
      const target=row && (focusCoordinate?$('[data-coordinate="'+focusCoordinate+'"]',row):focusType?$('[data-region-type]',row):focusAction?$('[data-action="'+focusAction+'"]',row):null);
      target?.focus({preventScroll:true});
    }
  }

  function renderReview() {
    const count=state.regions.length,selected=state.regions.filter(r=>r.enabled).length;
    $('#resultCount').textContent=count;$('#selectedCount').textContent=selected;
    $('#resultTitle').textContent=state.analysisStatus==='partial'?'일부 정보를 확인해 주세요':state.analysisStatus==='empty'?'탐지된 영역이 없어요':state.analysisStatus==='manual'?'직접 가릴 정보를 선택해요':'확인이 필요한 정보';
    $('#reviewKicker').textContent=state.sample?'SAMPLE':state.analysisStatus==='manual'?'MANUAL':'SERVER';
    $('#reviewSubtitle').textContent=state.analysisStatus==='manual'?'직접 추가한 영역만 가려집니다. 사진 전체를 확인해 주세요.':state.sample?'샘플 시뮬레이션 결과예요. 번호로 사진 속 박스를 찾아요.':'팀 서버의 분석 결과예요. 놓치거나 잘못 분류한 정보가 있다면 수정해 주세요.';
    $('#riskSummary').classList.toggle('safe',count>0&&selected===count);
    $('#riskSummaryText').textContent=count===0?'탐지 결과가 없어도 개인정보가 없다는 뜻은 아니에요.':selected===count?selected+'개 영역을 가리도록 선택했어요.':(count-selected)+'개 영역이 가림에서 제외되어 있어요.';
    $('#selectAll').textContent=count>0&&selected===count?'전체 해제':'전체 선택';$('#selectAll').disabled=count===0||state.saving;
    $('#saveLabel').textContent=state.connection==='server'&&!state.sample?'최종 영역 전송 · 저장':selected?'가린 사진 저장하기':'촬영 정보 없이 저장하기';
    $('#undoButton').disabled=!state.history.length||state.phase!=='review';
    $('#strength').disabled=state.style==='solid';$('#strengthValue').textContent=state.style==='solid'?'완전 가림':state.strength+'%';
    $$('.style-options button').forEach(button=>{const selected=button.dataset.style===state.style;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));});
    $('#styleHint').textContent=state.style==='solid'?'선택한 영역을 불투명한 색으로 완전히 덮어요.':'민감한 정보에는 완전히 덮는 단색 가림을 권장해요.';
    $('.metadata-box p').textContent=metadataText();
    $('#partialNotice').classList.toggle('hidden',!state.issues.length);$('#partialNotice').textContent=state.issues.join(' ');
    $('#serverSaveNotice').classList.toggle('hidden',state.connection!=='server'||state.sample);
    $('#serverSaveNotice').textContent='사진과 최종 선택 영역을 '+state.endpoint+' 로 전송합니다.';
    renderList();
  }

  function render() { renderImage();renderBoxes();renderReview();syncPanels();updateGuide(); }

  function syncDrawing() {
    $('#canvasWrap').classList.toggle('drawing',state.drawing);
    $('#drawHint').classList.toggle('hidden',!state.drawing);
    $('#drawPreview').classList.add('hidden');
    $('#addRegion').setAttribute('aria-pressed',String(state.drawing));
    if(state.drawing) {
      state.mode='original';renderImage();
      $('#toolHint').textContent='사진을 드래그해서 가릴 부분을 선택하세요.';
    } else $('#toolHint').textContent='가릴 부분을 직접 추가할 수 있어요.';
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
      if(gesture.type==='resize') {r.w=clamp(gesture.original.w+dx,.008,1-r.x);r.h=clamp(gesture.original.h+dy,.008,1-r.y);}
      else {r.x=clamp(gesture.original.x+dx,0,1-r.w);r.y=clamp(gesture.original.y+dy,0,1-r.h);}
      invalidate();
      const box=$$('.region-box').find(b=>b.dataset.id===r.id);
      if(box)Object.assign(box.style,{left:r.x*100+'%',top:r.y*100+'%',width:r.w*100+'%',height:r.h*100+'%'});
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
  async function prepareExport() {
    if(!state.source||state.phase!=='review'||state.saving)return;
    const token=++state.exportToken,serial=++state.requestSerial;
    state.saving=true;state.saveError='';state.lastPayload=Core.payload(state);$('#cancelExport').classList.remove('hidden');
    $('#saveState').classList.remove('hidden');$('#saveStateText').textContent=state.connection==='server'&&!state.sample?'최종 영역을 서버에 전송하고 있어요…':'저장할 PNG를 만들고 있어요…';syncPanels();
    let candidateUrl;
    try {
      let blob;
      if(state.connection==='server'&&!state.sample) {
        state.requestController=new AbortController();
        const input=await imageBlob(state.source);
        if(serial!==state.requestSerial)return;
        blob=await PrivacyLensAPI.client(state.endpoint).redact(input,state.lastPayload,{signal:state.requestController.signal});
      } else {drawProtected();blob=await imageBlob(protectedCanvas);}
      if(token!==state.exportToken||serial!==state.requestSerial)return;
      candidateUrl=URL.createObjectURL(blob);
      const check=new Image();check.src=candidateUrl;await check.decode();
      if(check.naturalWidth!==state.width||check.naturalHeight!==state.height)throw new Error('저장 이미지의 크기가 원본과 달라요. 서버의 좌표·출력 크기를 확인해 주세요.');
      if(token!==state.exportToken||serial!==state.requestSerial)return;
      if(state.exportUrl)URL.revokeObjectURL(state.exportUrl);
      downloadBlob=blob;state.exportUrl=candidateUrl;candidateUrl=null;$('#exportPreview').src=state.exportUrl;
      const selected=state.lastPayload.regions.length,excluded=state.regions.length-selected;
      $('#exportRegionCount').textContent=selected+'개 영역';
      $('#exportOrigin').textContent=state.connection==='server'&&!state.sample?'팀 서버 처리 파일':'브라우저 처리 파일';
      $('#exportMetadata').textContent=state.connection==='server'&&!state.sample?'서버에 제거 요청':'원본 정보 제외';
      $('#exportWarning').textContent=!selected?'가림 영역이 없어 사진 내용이 그대로 저장됩니다. 촬영 메타데이터만 제외합니다.':(excluded?excluded+'개 영역은 가리지 않아요. ':'')+(state.style==='solid'?'선택한 부분을 단색으로 덮었어요. ':'블러·모자이크는 일부 정보가 드러날 수 있어요. ')+'공유 전에 사진 전체를 확인해 주세요.';
      showDialog('exportDialog');state.demoProgress.preview=true;updateGuide();
    } catch(error) {
      if(serial===state.requestSerial && error.name!=='AbortError') {state.saveError=error.message||'저장하지 못했어요. 다시 시도해 주세요.';notify(state.saveError,true);}
    } finally {
      if(candidateUrl)URL.revokeObjectURL(candidateUrl);
      if(serial===state.requestSerial){state.saving=false;state.requestController=null;$('#saveState').classList.toggle('hidden',!state.saveError);$('#saveStateText').textContent=state.saveError;$('#cancelExport').classList.toggle('hidden',!!state.saveError);syncPanels();}
    }
  }

  function download() {
    if(!downloadBlob)return;
    const url=URL.createObjectURL(downloadBlob);
    const a=document.createElement('a');
    const base=state.name.replace(/\.[^/.]+$/,'').replace(/[<>:"/\\|?*\x00-\x1F]/g,'_').slice(0,90) || 'photo';
    a.href=url;a.download=base+'-privacy-lens.png';document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);
    closeDialog($('#exportDialog'));setStep(3);state.mode='protected';state.demoProgress.downloaded=true;renderImage();updateGuide();
    notify('PNG 다운로드를 요청했어요. 브라우저의 다운로드 목록을 확인하세요.');
  }


  function cancelRequests() {
    state.requestSerial++;state.requestController?.abort();state.requestController=null;state.saving=false;
  }
  function imageBlob(source) {
    return new Promise((resolve,reject)=>source.toBlob(blob=>blob?resolve(blob):reject(new Error('사진을 PNG로 만들지 못했어요. 더 작은 사진으로 시도해 주세요.')),'image/png'));
  }
  function inferType(r) {
    const s=r.id+' '+r.label;
    if(/email|이메일/.test(s))return 'EMAIL';
    if(/address|주소/.test(s))return 'ADDRESS';
    if(/phone|연락처|전화/.test(s))return 'PHONE';
    if(/code|바코드/.test(s))return 'BARCODE';
    if(/student-id|학번/.test(s))return 'STUDENT_ID';
    if(/school|학교|소속/.test(s))return 'ORGANIZATION';
    if(/name|이름/.test(s))return 'NAME';
    return 'DOCUMENT';
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
    $('#connectionButton').disabled=state.saving||phase==='scanning';
    $('#payloadButton').disabled=!state.source||phase!=='review'||state.saving;
    $('#analyzeButton').disabled=!state.sample&&state.connection!=='server';
    $('#analyzeButton').textContent=state.sample?'샘플 분석 시작':state.connection==='server'?'팀 서버로 분석하기':'AI 서버를 연결해 주세요';
    $('#readyDescription').textContent=state.sample?'파일 미리보기를 확인한 뒤 샘플 분석을 시작하세요. 시연 상황을 바꾸어 예외 상태도 살펴볼 수 있어요.':state.connection==='server'?'사진을 '+state.endpoint+' 에 보내 분석합니다. 원본 방향과 크기를 맞춘 PNG로 전송해요.':'AI 서버가 아직 연결되지 않았어요. 사진을 확인하고 직접 가릴 영역을 지정할 수 있어요.';
    $('#readyFileInfo').textContent=state.width+' × '+state.height+' px';
    $('#sourceBadge').textContent=state.sample?'샘플 시뮬레이션':state.analysisStatus==='manual'?'내 사진 · 수동 편집':state.connection==='server'?'팀 서버 모드':'파일 미리보기';
    const text=phase==='ready'?'미리보기 준비 완료':phase==='scanning'?(state.sample?'샘플 분석 진행 중':'팀 서버 응답을 기다리는 중'):phase==='failed'?'분석 실패 · 재시도하거나 직접 편집할 수 있어요':state.analysisStatus==='partial'?'분석 완료 · 일부 글자는 직접 확인해 주세요':state.analysisStatus==='empty'?'분석 완료 · 탐지 결과 없음':state.analysisStatus==='manual'?'수동 편집 · AI 분석을 수행하지 않았어요':'분석 완료 · 결과를 확인하고 수정해 주세요';
    $('#analysisNoticeText').textContent=text;$('#analysisNotice').dataset.state=phase==='failed'?'error':state.analysisStatus==='partial'?'warning':'normal';
    $('#canvasCaption').textContent={original:'ORIGINAL · 위험 영역',protected:'PROTECTED · 가림 결과',compare:'BEFORE / AFTER'}[state.mode];
    if(phase==='ready')setStep(1);
    else if(phase==='scanning'||phase==='failed')setStep(2);
    $('#zoomOut').disabled=!state.source||state.zoom<=.5;$('#zoomIn').disabled=!state.source||state.zoom>=4;
    $('#runScenario').disabled=state.saving;
  }
  function setConnectionCopy() {
    const server=state.connection==='server';
    $('#connectionButton').textContent=server?'팀 서버 연결 설정':'데모 · 서버 미연결';
    $('#privacyTitle').textContent=server?'선택한 서버로만.':'이 사진은, 여기서만.';
    $('#privacyDescription').textContent=server?'분석·저장 버튼을 누르면 사진을 설정한 팀 서버로 전송해요.':'사진을 서버에 보내지 않고 이 브라우저에서 처리해요.';
    $('#privacyMode').textContent=server?'팀 서버 모드':'로컬 처리 데모';
    $('#networkLabel').textContent=server&&!state.sample?'팀 서버 전송 모드':'서버 전송 없음';
    $('#footerPrivacy').textContent=server?'샘플은 로컬 처리 · 내 사진은 선택한 서버로 전송':'원본 전송 없이, 내 기기에서 편집해요.';
  }
  function startManual() {
    stopScan();cancelRequests();state.phase='review';state.analysisStatus='manual';state.issues=[];state.mode='original';
    invalidate();render();setStep(2);notify('직접 편집 모드예요. 가릴 부분을 추가해 주세요.');
  }
  async function beginAnalysis(retry=false) {
    if(!state.source||state.saving)return;
    stopScan();cancelRequests();state.regions=[];state.history=[];state.focused=null;state.issues=[];state.mode='original';state.phase='scanning';state.analysisStatus='running';state.drawing=false;
    if(retry&&state.sample&&$('#scenarioSelect').value==='failed')$('#scenarioSelect').value='normal';
    state.scenario=$('#scenarioSelect').value;invalidate();syncDrawing();render();
    $('#scanProgress').style.width='0%';$('#scanPercent').textContent=state.sample?'0%':'분석 요청 중';
    $('#scanningPanel').classList.toggle('server-analysis',!state.sample);
    $('#scanModeLabel').textContent=state.sample?'샘플 시뮬레이션':'팀 서버에서 처리';
    if(state.sample) {
      const start=performance.now(),duration=window.matchMedia('(prefers-reduced-motion: reduce)').matches?900:2400;
      const update=()=>{
        const progress=clamp((performance.now()-start)/duration,0,1);
        $('#scanProgress').style.width=progress*100+'%';$('#scanPercent').textContent=Math.round(progress*100)+'%';
        [1,2,3].forEach(i=>$('#scanTask'+i).classList.toggle('active',progress>=(i-1)/3));
        if(progress<1)return;
        stopScan();
        if(state.scenario==='failed'){analysisFailure('샘플 분석 요청 시간이 초과된 상황입니다. 재시도하면 정상 결과로 복구됩니다.');return;}
        let regions=clone(makeFixture(state.sampleKey).regions).map(r=>({...r,type:inferType(r),ocrStatus:'ok'}));
        state.analysisStatus='completed';
        if(state.scenario==='empty'){regions=[];state.analysisStatus='empty';}
        if(state.scenario==='partial') {
          const last=regions.at(-1);last.type='UNKNOWN';last.kind='uncertain';last.ocrStatus='failed';last.text='글자 판독 실패';last.reason='영역은 찾았지만 작거나 흐린 글자를 읽지 못한 시연 상황이에요. 확대해서 확인하고 가릴지 결정해 주세요.';
          state.analysisStatus='partial';state.issues=['일부 글자를 읽지 못했어요. ‘판독 실패’ 항목은 기본으로 가림 선택되어 있습니다. 확대해서 직접 확인해 주세요.'];
        }
        if(state.scenario==='correction'){
          regions=regions.slice(0,-1);
          regions.push({id:'demo-false-positive',type:'NAME',x:.04,y:.044,w:.62,h:.043,label:'오탐 · SAMPLE 문구',reason:'이 샘플의 제목이 이름으로 잘못 분류된 상황입니다. 개인정보가 아니므로 삭제해 보세요.',text:'SAMPLE DOCUMENT',kind:'high',ocrStatus:'ok',enabled:true});
          state.issues=['수정 시연: SAMPLE 문구는 오탐입니다. 마지막 누락 정보는 ‘영역 추가’로 직접 지정해 보세요.'];
        }
        state.regions=regions;state.phase='review';state.focused=regions[0]?.id||null;invalidate();render();setStep(2);notify('샘플 분석 완료. '+regions.length+'개 영역을 확인해 주세요.');
      };
      state.timer=setInterval(update,40);update();return;
    }
    if(state.connection!=='server'){startManual();return;}
    const serial=++state.requestSerial;state.requestController=new AbortController();
    try {
      $('#scanProgress').style.width='55%';
      const input=await imageBlob(state.source);
      if(serial!==state.requestSerial)return;
      const response=await PrivacyLensAPI.client(state.endpoint).analyze(input,{signal:state.requestController.signal});
      if(serial!==state.requestSerial)return;
      const result=Core.validateResult(response,state.width,state.height);
      state.regions=result.regions;state.analysisId=result.analysisId;state.issues=result.warnings;
      state.analysisStatus=result.status==='partial'?'partial':result.regions.length?'completed':'empty';
      if(result.regions.some(r=>r.ocrStatus==='failed')) {state.analysisStatus='partial';if(!state.issues.length)state.issues=['일부 글자를 읽지 못했어요. 판독 실패 영역을 직접 확인해 주세요.'];}
      state.phase='review';state.focused=state.regions[0]?.id||null;invalidate();render();setStep(2);notify('서버 분석 결과를 불러왔어요.');
    } catch(error) {if(serial===state.requestSerial && error.name!=='AbortError')analysisFailure(error.message);}
    finally {if(serial===state.requestSerial)state.requestController=null;}
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
  }
  function zoomTo(value) {state.zoom=clamp(value,.5,4);layoutCanvas();}
  function focusRegion(id,origin='list') {
    const r=state.regions.find(r=>r.id===id);if(!r)return;
    state.focused=id;state.mode='original';state.demoProgress.inspected=true;render();
    if(origin==='list') {
      const box=$$('.region-box').find(el=>el.dataset.id===id),viewport=$('#canvasStage');
      if(box){const b=box.getBoundingClientRect(),v=viewport.getBoundingClientRect();viewport.scrollLeft+=b.left+b.width/2-v.left-viewport.clientWidth/2;viewport.scrollTop+=b.top+b.height/2-v.top-viewport.clientHeight/2;}
    } else {
      const row=$$('.region-item').find(el=>el.dataset.region===id);
      if(row){const list=$('#regionList');list.scrollTop=row.offsetTop-list.offsetTop;}
    }
    updateGuide();
  }
  function updateGuide() {
    $('#guidedDemo').classList.toggle('hidden',!state.guided);
    if(!state.guided)return;
    const p=state.demoProgress;
    const steps=[['inspected','결과와 근거 확인'],['deleted','SAMPLE 오탐 삭제'],['added','누락 이메일 추가'],['preview','전후 비교 · 미리보기'],['downloaded','PNG 다운로드']];
    const current=steps.find(([key])=>!p[key]);
    $('#demoStepLabel').textContent=current?current[1]:'시연 완료! 다시 시작해 반복 연습할 수 있어요.';
    $('#demoChecklist').innerHTML=steps.map(([key,label],i)=>'<li class="'+(p[key]?'done':current?.[0]===key?'current':'')+'"><span>'+(p[key]?icon('check'):i+1)+'</span>'+label+'</li>').join('');
  }
  function openPayload() {
    if(!state.source)return;
    const payload=Core.payload(state);$('#payloadJson').textContent=JSON.stringify(payload,null,2);
    $('#payloadSummary').textContent='선택한 '+payload.regions.length+'개 영역 · 원본 '+state.width+' × '+state.height+' px · 이미지 데이터와 OCR 원문은 JSON에 포함하지 않아요.';
    showDialog('payloadDialog');
  }
  function savePayload() {
    const blob=new Blob([JSON.stringify(Core.payload(state),null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='privacy-lens-regions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);notify('최종 영역 JSON 다운로드를 요청했어요.');
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
      Object.assign(region,next);invalidate();renderImage();renderBoxes();
    }
    if(commit)renderReview();
  }

  // Demo stays local. Team API calls require an explicitly chosen server mode.
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
  $('#cancelScan').addEventListener('click',()=>{stopScan();cancelRequests();state.phase='ready';state.analysisStatus='cancelled';render();notify('분석 요청을 취소했어요. 다시 시작할 수 있어요.');});
  $$('[data-view]').forEach(button=>button.addEventListener('click',()=>{state.mode=button.dataset.view;state.drawing=false;syncDrawing();renderImage();}));
  $('#compareSlider').addEventListener('input',event=>{state.compare=Number(event.target.value);renderImage();});
  $$('[data-style]').forEach(button=>button.addEventListener('click',()=>{state.style=button.dataset.style;state.mode='protected';state.drawing=false;syncDrawing();invalidate();render();}));
  $('#strength').addEventListener('input',event=>{state.strength=Number(event.target.value);$('#strengthValue').textContent=state.strength+'%';state.mode='protected';state.drawing=false;syncDrawing();invalidate();renderImage();});
  $('#selectAll').addEventListener('click',()=>{if(!state.regions.length)return;pushHistory();const all=state.regions.every(r=>r.enabled);state.regions.forEach(r=>r.enabled=!all);invalidate();render();});
  $('#regionList').addEventListener('click',event=>{
    const control=event.target.closest('[data-action]');if(!control || control.dataset.action==='toggle')return;
    const row=control.closest('[data-region]');const region=state.regions.find(r=>r.id===row.dataset.region);if(!region)return;
    if(control.dataset.action==='delete') {if(region.id==='demo-false-positive')state.demoProgress.deleted=true;pushHistory();state.regions=state.regions.filter(r=>r.id!==region.id);if(state.focused===region.id)state.focused=null;invalidate();render();notify('영역을 삭제했어요. 되돌리기로 복원할 수 있어요.');}
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
    if(!state.source || state.phase==='scanning' || state.mode!=='original' || event.button!==0)return;
    const wrap=$('#canvasWrap'),p=point(event);
    if(state.drawing) {event.preventDefault();gesture={type:'draw',start:p,pointerId:event.pointerId};wrap.setPointerCapture(event.pointerId);return;}
    const box=event.target.closest('.region-box');if(!box)return;
    event.preventDefault();
    const region=state.regions.find(r=>r.id===box.dataset.id);if(!region)return;
    state.focused=region.id;state.demoProgress.inspected=true;renderReview();updateGuide();
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
    if(event.altKey){if(event.key==='ArrowLeft')r.w-=amount;if(event.key==='ArrowRight')r.w+=amount;if(event.key==='ArrowUp')r.h-=amount;if(event.key==='ArrowDown')r.h+=amount;r.w=clamp(r.w,.008,1-r.x);r.h=clamp(r.h,.008,1-r.y);}
    else{if(event.key==='ArrowLeft')r.x-=amount;if(event.key==='ArrowRight')r.x+=amount;if(event.key==='ArrowUp')r.y-=amount;if(event.key==='ArrowDown')r.y+=amount;r.x=clamp(r.x,0,1-r.w);r.y=clamp(r.y,0,1-r.h);}
    state.focused=r.id;invalidate();render();$$('.region-box').find(el=>el.dataset.id===r.id)?.focus({preventScroll:true});
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && state.drawing){state.drawing=false;gesture=null;syncDrawing();}});
  $('#saveButton').addEventListener('click',prepareExport);
  $('#downloadButton').addEventListener('click',download);
  const targets=[['box','택배 송장','이름 · 주소 · 연락처'],['id','학생증','이름 · 학교 · 학번'],['monitor','모니터 화면','이메일 · 대화 · 문서'],['id','신분증','식별 번호 · 이름'],['file','금융 문서','계좌 · 거래 내역'],['file','의료 문서','이름 · 진료 정보'],['file','영수증','매장 · 결제 정보'],['file','명함','연락처 · 소속'],['grid','QR · 바코드','연결된 식별 정보']];
  $('#targetsGrid').innerHTML=targets.map(([symbol,label,detail])=>'<div class="target-tile">'+icon(symbol)+'<h3>'+label+'</h3><p>'+detail+'</p></div>').join('');

  $('#analyzeButton').addEventListener('click',()=>beginAnalysis());
  $('#manualButton').addEventListener('click',startManual);$('#failureManual').addEventListener('click',startManual);
  $('#retryAnalysis').addEventListener('click',()=>beginAnalysis(true));
  $('#zoomIn').addEventListener('click',()=>zoomTo(state.zoom+.25));$('#zoomOut').addEventListener('click',()=>zoomTo(state.zoom-.25));
  $('#zoomFit').addEventListener('click',()=>{state.zoom=1;layoutCanvas(false);});
  new ResizeObserver(()=>layoutCanvas()).observe($('#canvasStage'));
  function toggleDemoPanel(open) {$('#demoPanel').classList.toggle('hidden',!open);$('#demoToggle').setAttribute('aria-expanded',String(open));}
  $('#demoToggle').addEventListener('click',()=>toggleDemoPanel($('#demoPanel').classList.contains('hidden')));
  $('#runScenario').addEventListener('click',()=>{toggleDemoPanel(false);loadSample(state.sampleKey||'mixed',{auto:true});});
  $('#portraitSample').addEventListener('click',()=>{toggleDemoPanel(false);loadSample('portrait');});
  $('#startDemo').addEventListener('click',()=>{toggleDemoPanel(false);$('#scenarioSelect').value='correction';loadSample('mixed',{auto:true,guided:true});});
  $('#endDemo').addEventListener('click',()=>{state.guided=false;updateGuide();});
  $('#payloadButton').addEventListener('click',openPayload);$('#downloadPayload').addEventListener('click',savePayload);
  $('#connectionButton').addEventListener('click',()=>{$('[name="connectionMode"][value="'+state.connection+'"]').checked=true;$('#endpointInput').value=state.endpoint;$('#connectionError').textContent='';showDialog('connectionDialog');});
  $('#connectionForm').addEventListener('submit',event=>{
    event.preventDefault();
    try {
      const mode=$('[name="connectionMode"]:checked').value;
      const endpoint=mode==='server'?Core.normalizeEndpoint($('#endpointInput').value.trim()):state.endpoint;
      if(mode==='server'&&!$('#serverConsent').checked)throw new Error('팀 서버 전송 안내를 확인해 주세요.');
      state.connection=mode;state.endpoint=endpoint;setConnectionCopy();syncPanels();if(state.source)renderReview();closeDialog($('#connectionDialog'));notify(mode==='server'?'팀 서버 모드로 설정했어요. 아직 사진은 전송하지 않았어요.':'브라우저 데모 모드로 설정했어요.');
    } catch(error){$('#connectionError').textContent=error.message;}
  });
  $('#cancelExport').addEventListener('click',()=>{cancelRequests();state.exportToken++;$('#saveState').classList.add('hidden');syncPanels();notify('저장 요청을 취소했어요. 편집 내용은 유지돼요.');});
  $('.brand').addEventListener('click',event=>{event.preventDefault();reset();});

  initializeThumbnails();
  setStep(1);setConnectionCopy();syncPanels();
})();
