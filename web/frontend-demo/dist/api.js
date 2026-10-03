'use strict';
(() => {
  // Privacy Lens 서버 통신. 화면과 같은 주소에서 나오므로 서버 주소 설정이 없다.
  //   POST /analyze          사진 원본 + 판정 조건 + 번호표 → 분석 결과(JSON)
  //   POST /redact/preview   가린 모습 축소본(JSON, base64 JPEG). OCR 이 없어 대기열을 거치지 않는다
  //   POST /redact           가린 사진(JSON, base64 JPEG) + 다시 검사한 결과
  //   GET  /queue            대기열 상태. 번호표를 주면 내 앞에 몇 건인지
  //   POST /queue/cancel     기다리던 요청 빼기
  // 사진은 '원본 파일'을 그대로 보낸다. 브라우저에서 다시 그려 보내면 위치정보(EXIF)가
  // 사라져 서버가 GPS 를 찾지 못하고, 방향 보정도 서버가 직접 한다.
  const TIMEOUT_MS = 10 * 60 * 1000;  // 엔진 준비(1~2분) + 대기열까지 기다린다

  function newTicket() {
    return globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID()
      : Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  function client(base='', fetchImpl=globalThis.fetch.bind(globalThis), timeoutMs=TIMEOUT_MS) {
    async function request(route,init,signal) {
      const controller=new AbortController();
      let timedOut=false;
      const abort=()=>controller.abort();
      if(signal?.aborted)controller.abort();else signal?.addEventListener('abort',abort,{once:true});
      const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
      try {
        const response=await fetchImpl(base+route,{credentials:'same-origin',cache:'no-store',redirect:'error',...init,signal:controller.signal});
        if(!response.ok) {
          let detail='';
          try{const data=await response.json();detail=typeof data.detail==='string'?data.detail.slice(0,200):'';}catch{}
          const error=new Error(detail || (response.status===413?'사진이 너무 커요. 더 작은 사진으로 시도해 주세요.':'서버 처리에 실패했어요. (HTTP '+response.status+')'));
          error.status=response.status;
          throw error;
        }
        if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('서버가 JSON 대신 다른 형식을 반환했습니다.');
        return await response.json();
      } catch(error) {
        if(timedOut)throw new Error('서버 응답 시간이 초과됐어요. 잠시 후 다시 시도해 주세요.');
        if(controller.signal.aborted)throw new DOMException('요청 취소','AbortError');
        if(error instanceof TypeError)throw new Error('서버에 연결할 수 없어요. 서버가 켜져 있는지 확인해 주세요.');
        throw error;
      } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);}
    }
    function form(image,fields) {
      const body=new FormData();
      body.append('image',image,image.name||'image.png');
      Object.entries(fields).forEach(([k,v])=>{if(v!==undefined&&v!==null)body.append(k,typeof v==='string'?v:JSON.stringify(v));});
      return body;
    }
    return {
      analyze(image,{mode='full',ticket,signal}={}) {
        return request('/analyze',{method:'POST',body:form(image,{mode,ticket})},signal);
      },
      preview(image,boxes,style,{signal}={}) {
        return request('/redact/preview',{method:'POST',body:form(image,{boxes,style})},signal);
      },
      redact(image,boxes,style,{ticket,signal}={}) {
        return request('/redact',{method:'POST',body:form(image,{boxes,style,ticket})},signal);
      },
      queue(ticket,{signal}={}) {
        return request('/queue'+(ticket?'?ticket='+encodeURIComponent(ticket):''),{method:'GET'},signal);
      },
      // 창을 닫는 중에도 나가도록 keepalive. 응답은 기다리지 않는다.
      cancel(ticket) {
        if(!ticket)return;
        try{fetchImpl(base+'/queue/cancel?ticket='+encodeURIComponent(ticket),{method:'POST',keepalive:true,credentials:'same-origin'}).catch(()=>{});}catch{}
      }
    };
  }
  globalThis.PrivacyLensAPI=Object.freeze({client,newTicket});
})();
