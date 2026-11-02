'use strict';
(() => {
  // Privacy Lens 서버 통신. 화면과 같은 주소에서 나오므로 서버 주소 설정이 없다.
  //   POST /analyze          사진 원본 + 번호표 (+ 개발자 모드 판단 설정) → 분석 결과(JSON)
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

  // 개발자 콘솔(F12) 출력. LLM 판단을 쓰면 서버가 공급자와 주고받은 요청·응답(llm_trace, 키는 끝 4글자만)을
  // 응답에 실어 보낸다. 사진 속 글자(OCR 원문)가 들어 있으니 콘솔에만 찍고 어디에도 저장하지 않는다.
  function logTrace(route,trace,out=globalThis.console) {
    if(!out || !Array.isArray(trace) || !trace.length)return;
    for(const t of trace){
      const head='[Privacy Lens] LLM '+(t.kind==='models'?'모델 목록':'판단')+' · '+t.provider+(t.model?' · '+t.model:'')
        +' · '+(t.ok?'성공':'실패')+(t.status?' (HTTP '+t.status+')':'')+(Number.isFinite(t.elapsed_ms)?' · '+t.elapsed_ms+'ms':'')+' ← '+route;
      (out.groupCollapsed||out.log).call(out,head);
      out.log('요청',{method:t.method,url:t.url,headers:t.headers,body:t.request});
      if(t.error)out.warn('오류',t.error);
      out.log('응답',t.response);
      const text=replyText(t);
      if(text)out.log('모델이 쓴 글',text);
      out.groupEnd?.();
    }
  }
  // 공급자별 응답에서 모델이 쓴 글만 꺼내 읽기 쉽게
  function replyText(t) {
    const r=t.response;
    if(!r || typeof r!=='object' || t.kind!=='judge')return '';
    try {
      if(t.provider==='anthropic')return r.content.filter(b=>b.type==='text').map(b=>b.text).join('');
      if(t.provider==='gemini')return r.candidates[0].content.parts.map(p=>p.text||'').join('');
      if(t.provider==='ollama')return r.message.content;
      return r.choices[0].message.content;
    } catch { return ''; }
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
          try{const data=await response.json();detail=typeof data.detail==='string'?data.detail.slice(0,200):'';logTrace(route,data.llm_trace);}catch{}
          const error=new Error(detail || (response.status===413?'사진이 너무 커요. 더 작은 사진으로 시도해 주세요.':'서버 처리에 실패했어요. (HTTP '+response.status+')'));
          error.status=response.status;
          if(response.status!==409)globalThis.console?.warn('[Privacy Lens] '+(init.method||'GET')+' '+route+' 실패 (HTTP '+response.status+')',error.message);
          throw error;
        }
        if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('서버가 JSON 대신 다른 형식을 반환했습니다.');
        const data=await response.json();
        logTrace(route,data?.llm_trace||data?.report?.llm_trace);
        return data;
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
      // judge: 개발자 모드의 LLM 설정(JSON 문자열, API 키 포함). 규칙 기반이면 undefined 라 보내지 않는다.
      analyze(image,{ticket,judge,signal}={}) {
        return request('/analyze',{method:'POST',body:form(image,{ticket,judge})},signal);
      },
      // 개발자 모드: 고른 공급자에서 쓸 수 있는 모델 이름. 사진은 보내지 않는다.
      models(judge,{signal}={}) {
        const body=new FormData();body.append('judge',judge);
        return request('/llm/models',{method:'POST',body},signal);
      },
      preview(image,boxes,style,{signal}={}) {
        return request('/redact/preview',{method:'POST',body:form(image,{boxes,style})},signal);
      },
      redact(image,boxes,style,{ticket,judge,signal}={}) {
        return request('/redact',{method:'POST',body:form(image,{boxes,style,ticket,judge})},signal);
      },
      // 진행 상태(SSE). 이벤트마다 onEvent(종류, 상태). 끝(done)·번호표 없음(gone)·연결 실패(error)면 스스로 닫는다.
      // EventSource 를 못 쓰는 환경이면 null — 화면은 /queue 폴링의 progress 로 같은 값을 받는다.
      progress(ticket,onEvent,EventSourceImpl=globalThis.EventSource) {
        if(!ticket||typeof EventSourceImpl!=='function')return null;
        let source;
        try{source=new EventSourceImpl(base+'/progress?ticket='+encodeURIComponent(ticket));}catch{return null;}
        let closed=false;
        const close=()=>{if(!closed){closed=true;source.close();}};
        const relay=(type,raw)=>{if(closed)return;let data=null;try{data=raw?JSON.parse(raw):null;}catch{}onEvent(type,data);};
        source.addEventListener('progress',e=>relay('progress',e.data));
        source.addEventListener('done',e=>{relay('done',e.data);close();});
        source.addEventListener('gone',()=>{relay('gone',null);close();});
        // 끊기면 브라우저가 다시 붙지만, 아예 못 여는 경우(서버가 /progress 를 모름 등)는 폴링으로 넘긴다
        source.onerror=()=>{if(source.readyState===2){relay('error',null);close();}};
        return {close};
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
  globalThis.PrivacyLensAPI=Object.freeze({client,newTicket,logTrace});
})();
