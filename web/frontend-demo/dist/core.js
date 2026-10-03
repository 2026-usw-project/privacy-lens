'use strict';
(() => {
  const clamp = (n,min,max) => Math.min(max,Math.max(min,n));
  const TYPES = { NAME:'이름',PHONE:'연락처',ADDRESS:'주소',STUDENT_ID:'학번',ORGANIZATION:'소속',EMAIL:'이메일',BARCODE:'QR·바코드',DOCUMENT:'문서',UNKNOWN:'판독 필요',CUSTOM:'직접 지정' };
  function dimensions(width,height) {
    if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>24000000) throw new Error('잘못된 원본 이미지 크기입니다.');
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
    if(!box || ![box.x,box.y,box.width,box.height].every(Number.isFinite) || box.x<0 || box.y<0 || box.width<=0 || box.height<=0 || box.x+box.width>width || box.y+box.height>height) throw new Error('서버가 이미지 범위를 벗어난 영역을 반환했습니다.');
    return {x:box.x/width,y:box.y/height,w:box.width/width,h:box.height/height};
  }
  function screenPoint(clientX,clientY,rect) {
    if(!rect || rect.width<=0 || rect.height<=0)throw new Error('사진 표시 크기가 올바르지 않습니다.');
    return {x:clamp((clientX-rect.left)/rect.width,0,1),y:clamp((clientY-rect.top)/rect.height,0,1)};
  }
  function validateResult(data,width,height) {
    dimensions(width,height);
    if(!data || data.coordinate_space!=='oriented_original_pixels' || data.width!==width || data.height!==height) throw new Error('서버 좌표 기준 또는 해상도가 사진과 다릅니다. 팀 서버의 이미지 방향·크기를 확인해 주세요.');
    if(!['completed','partial'].includes(data.status) || !Array.isArray(data.regions) || data.regions.length>300)throw new Error('서버의 탐지 결과 형식이 올바르지 않습니다.');
    const ids=new Set();
    const regions=data.regions.map((r,i)=>{
      if(!r || typeof r.id!=='string' || !r.id || r.id.length>80 || ids.has(r.id))throw new Error('서버 영역 ID가 없거나 중복되었습니다.');
      ids.add(r.id);
      const box=fromPixels(r.bbox,width,height);
      const type=Object.hasOwn(TYPES,r.type)?r.type:'UNKNOWN';
      return {...box,id:r.id,type,label:String(r.label||TYPES[type]).slice(0,100),reason:String(r.evidence||'이미지를 직접 확인해 주세요.').slice(0,600),text:r.ocr_status==='failed'?'글자 판독 실패':String(r.text_preview||'인식 영역').slice(0,100),ocrStatus:r.ocr_status==='failed'?'failed':'ok',kind:r.ocr_status==='failed'?'uncertain':'high',enabled:true};
    });
    return {regions,warnings:Array.isArray(data.warnings)?data.warnings.slice(0,10).map(x=>String(x).slice(0,300)):[],status:data.status,analysisId:typeof data.analysis_id==='string'?data.analysis_id.slice(0,120):null};
  }
  function payload(state) {
    dimensions(state.width,state.height);
    return {schema_version:'1.0',coordinate_space:'oriented_original_pixels',image:{width:state.width,height:state.height},analysis_id:state.analysisId||null,regions:state.regions.filter(r=>r.enabled).map(r=>({id:r.id,type:r.type||'CUSTOM',bbox:toPixels(r,state.width,state.height)})),redaction:{style:state.style,strength:state.strength,color:'#223a2d'},remove_metadata:true,output_format:'png'};
  }
  function normalizeEndpoint(input) {
    const url=new URL(input);
    const local=['localhost','127.0.0.1','[::1]'].includes(url.hostname);
    if(url.protocol!=='https:' && !(url.protocol==='http:'&&local)) throw new Error('HTTPS 주소 또는 로컬 개발 서버 주소를 입력해 주세요.');
    if(url.username||url.password||url.search||url.hash)throw new Error('주소에 비밀번호·쿼리·해시를 포함하지 마세요.');
    return url.href.replace(/\/$/,'');
  }
  globalThis.PrivacyLensCore=Object.freeze({TYPES,toPixels,fromPixels,screenPoint,validateResult,payload,normalizeEndpoint});
})();
