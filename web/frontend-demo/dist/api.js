'use strict';
(() => {
  function client(baseUrl,fetchImpl=globalThis.fetch.bind(globalThis),timeoutMs=45000) {
    const base=PrivacyLensCore.normalizeEndpoint(baseUrl);
    async function request(route,body,signal,parse) {
      const controller=new AbortController();
      let timedOut=false;
      const abort=()=>controller.abort();
      if(signal?.aborted)controller.abort();else signal?.addEventListener('abort',abort,{once:true});
      const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
      try {
        const response=await fetchImpl(base+route,{method:'POST',body,signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error'});
        if(!response.ok) {
          let detail='';
          try{const data=await response.json();detail=typeof data.error?.message==='string'?data.error.message.slice(0,180):'';}catch{}
          throw new Error(detail || (response.status===413?'서버가 사진 크기를 처리하지 못했어요. 사진을 줄여 주세요.':'서버 처리에 실패했어요. (HTTP '+response.status+')'));
        }
        return await parse(response);
      } catch(error) {
        if(timedOut)throw new Error('서버 응답 시간이 초과됐어요. 잠시 후 다시 시도하거나 직접 편집해 주세요.');
        if(controller.signal.aborted)throw new DOMException('요청 취소','AbortError');
        if(error instanceof TypeError)throw new Error('서버에 연결할 수 없어요. 주소, 서버 실행 상태, CORS 설정을 확인해 주세요.');
        throw error;
      } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);}
    }
    return {
      async analyze(image,{signal}={}) {
        const form=new FormData();form.append('image',image,'input.png');
        return request('/api/analyze',form,signal,async response=>{
          if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('분석 서버가 JSON 대신 다른 형식을 반환했습니다.');
          return response.json();
        });
      },
      async redact(image,payload,{signal}={}) {
        const form=new FormData();form.append('image',image,'input.png');form.append('request',JSON.stringify(payload));
        return request('/api/redact',form,signal,async response=>{
        if(!(response.headers.get('content-type')||'').includes('image/png'))throw new Error('처리 서버가 PNG 이미지를 반환하지 않았습니다.');
        const blob=await response.blob();
        if(!blob.size || blob.size>128*1024*1024)throw new Error('서버에서 받은 파일 크기가 올바르지 않습니다.');
        const bytes=new Uint8Array(await blob.slice(0,8).arrayBuffer());
        if(![137,80,78,71,13,10,26,10].every((b,i)=>bytes[i]===b))throw new Error('서버 응답이 올바른 PNG 파일이 아닙니다.');
        return blob;
        });
      }
    };
  }
  globalThis.PrivacyLensAPI=Object.freeze({client});
})();
