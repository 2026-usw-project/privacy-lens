'use strict';
(() => {
  // 서버(Privacy Lens 2 백엔드) 결과를 화면 영역으로 바꾸고, 화면 선택을 서버 요청으로 바꾼다.
  // 화면은 0–1 비율 좌표를 쓰고, 서버와는 방향 보정된 원본 픽셀 좌표 {x, y, w, h, poly}로 주고받는다.
  const clamp = (n,min,max) => Math.min(max,Math.max(min,n));
  const TYPES = { NAME:'이름',PHONE:'전화번호',EMAIL:'이메일',ADDRESS:'주소',RRN:'주민등록번호',CARD:'카드번호',TRACKING:'운송장번호',PLATE:'차량번호',BIZ:'사업자번호',NUMBER:'긴 숫자',BARCODE:'QR·바코드',UNKNOWN:'판독 필요',CUSTOM:'직접 지정' };
  // 서버 탐지 종류(kind) → [화면 유형, 항목 이름]
  const KINDS = {
    name:['NAME','이름'],mobile:['PHONE','휴대전화번호'],landline:['PHONE','유선전화번호'],service_line:['PHONE','대표번호'],tollfree:['PHONE','무료상담번호'],
    email:['EMAIL','이메일 주소'],rrn:['RRN','주민등록번호'],rrn_unverified:['RRN','주민등록번호 형식'],card:['CARD','카드번호'],brn:['BIZ','사업자등록번호'],
    plate:['PLATE','차량번호'],address_road:['ADDRESS','도로명주소'],address_unit:['ADDRESS','동·호수'],tracking:['TRACKING','운송장번호'],
    long_digits:['NUMBER','긴 숫자'],qr:['BARCODE','QR코드'],barcode:['BARCODE','바코드']
  };
  const SEVERITY = { cover:'가림 권장',review:'검토 권장',info:'참고' };
  const CONDITIONS = { full:'문맥·결합',baseline:'심각도표',naive:'정규식만' };
  const STYLES = ['blur','solid'];
  const MAX_REGIONS = 300;

  function dimensions(width,height) {
    if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>60000000) throw new Error('잘못된 원본 이미지 크기입니다.');
  }
  function toPixels(region,width,height) {
    dimensions(width,height);
    if(![region.x,region.y,region.w,region.h].every(Number.isFinite))throw new Error('좌표는 숫자여야 합니다.');
    const x=clamp(Math.floor(region.x*width+1e-7),0,width-1);
    const y=clamp(Math.floor(region.y*height+1e-7),0,height-1);
    const right=clamp(Math.ceil((region.x+region.w)*width-1e-7),x+1,width);
    const bottom=clamp(Math.ceil((region.y+region.h)*height-1e-7),y+1,height);
    return {x,y,width:right-x,height:bottom-y};
  }
  function fromPixels(box,width,height) {
    dimensions(width,height);
    if(!box || ![box.x,box.y,box.width,box.height].every(Number.isFinite) || box.x<0 || box.y<0 || box.width<=0 || box.height<=0 || box.x+box.width>width || box.y+box.height>height) throw new Error('이미지 범위를 벗어난 영역입니다.');
    return {x:box.x/width,y:box.y/height,w:box.width/width,h:box.height/height};
  }
  function screenPoint(clientX,clientY,rect) {
    if(!rect || rect.width<=0 || rect.height<=0)throw new Error('사진 표시 크기가 올바르지 않습니다.');
    return {x:clamp((clientX-rect.left)/rect.width,0,1),y:clamp((clientY-rect.top)/rect.height,0,1)};
  }

  // 서버 상자 {x,y,w,h}(원본 픽셀)를 이미지 안으로 잘라 비율로. 비면 null.
  // QR 상자처럼 가장자리를 한두 화소 넘는 경우가 있어 거절하지 않고 자른다.
  function boxToRatio(box,width,height) {
    if(!box || ![box.x,box.y,box.w,box.h].every(Number.isFinite))return null;
    const x0=clamp(box.x,0,width),y0=clamp(box.y,0,height),x1=clamp(box.x+box.w,0,width),y1=clamp(box.y+box.h,0,height);
    if(x1-x0<1 || y1-y0<1)return null;
    return {x:x0/width,y:y0/height,w:(x1-x0)/width,h:(y1-y0)/height};
  }
  function polyToRatio(poly,width,height) {
    if(!Array.isArray(poly) || poly.length<3 || poly.length>16)return null;
    const points=poly.map(p=>[Number(p?.[0])/width,Number(p?.[1])/height]);
    return points.every(p=>p.every(Number.isFinite))?points:null;
  }

  // 서버 /analyze 의 report 를 화면 상태로.
  function fromReport(report) {
    if(!report || !Array.isArray(report.findings) || !Array.isArray(report.groups))throw new Error('서버의 분석 결과 형식이 올바르지 않습니다.');
    const {width,height}=report;
    dimensions(width,height);
    if(report.findings.length>MAX_REGIONS)throw new Error('서버가 너무 많은 영역을 반환했습니다.');
    const regions=[],gps=[];
    report.findings.forEach((f,i)=>{
      if(f.kind==='gps' || !f.box){ if(f.kind==='gps')gps.push({message:String(f.message||'').slice(0,200)}); return; }
      const box=boxToRatio(f.box,width,height);if(!box)return;
      const [type,label]=KINDS[f.kind]||['UNKNOWN','개인정보 후보'];
      const certainty=['read','partial','region'].includes(f.certainty)?f.certainty:'region';
      const severity=Object.hasOwn(SEVERITY,f.severity)?f.severity:'review';
      const host=typeof f.detail?.host==='string'?f.detail.host.slice(0,120):'';
      const text=f.evidence_text?String(f.evidence_text).slice(0,120):host?'링크 주소 '+host+' (열지 않았어요)':certainty==='region'?'내용을 확인하지 못했어요':'';
      regions.push({...box,id:'f'+i,kind:'detected',finding:String(f.kind),type,label,severity,certainty,
        certaintyLabel:String(f.certainty_label||''),reason:String(f.message||'').slice(0,600),text,
        poly:polyToRatio(f.box.poly,width,height),enabled:false});
    });
    return {width,height,regions,gps,
      groups:report.groups.map(g=>String(g.message||'').slice(0,300)).filter(Boolean),
      notes:Array.isArray(report.notes)?report.notes.map(String):[],
      backend:String(report.ocr_backend||'').slice(0,160),elapsedMs:Number(report.elapsed_ms)||0,
      partial:regions.some(r=>r.certainty!=='read')};
  }

  // 화면에서 고른 영역 → 서버 /redact 의 boxes. 기울어진 외곽선이 남아 있으면 같이 보낸다.
  function boxes(state) {
    dimensions(state.width,state.height);
    return state.regions.filter(r=>r.enabled).map(r=>{
      const p=toPixels(r,state.width,state.height);
      const out={x:p.x,y:p.y,w:p.width,h:p.height};
      if(r.poly)out.poly=r.poly.map(([x,y])=>[Math.round(x*state.width*10)/10,Math.round(y*state.height*10)/10]);
      return out;
    });
  }
  function payload(state) {
    return {image:{width:state.width,height:state.height},style:STYLES.includes(state.style)?state.style:'blur',boxes:boxes(state)};
  }

  globalThis.PrivacyLensCore=Object.freeze({TYPES,KINDS,SEVERITY,CONDITIONS,STYLES,toPixels,fromPixels,screenPoint,fromReport,boxes,payload});
})();
