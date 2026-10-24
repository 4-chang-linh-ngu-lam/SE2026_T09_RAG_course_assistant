import {CLIENT_CONTEXT_HEADER,verifyClientContext} from '../../../config/client-identity.mjs';
import {documentQueryKeys,matchDocumentOperation} from './document-operations';

const MAX_BODY=50*1024*1024+65536;
export function createDocumentProxy(getOrigin:()=>string|undefined,fetcher:typeof fetch=fetch,getWebOrigin:()=>string|undefined,getSecret:()=>string|undefined){
  return async(request:Request,parts:string[])=>{
    const correlation=crypto.randomUUID();
    const failure=(status:number,code:string,message:string)=>Response.json({error:{code,message},correlation_id:correlation},{status,headers:{'Cache-Control':'no-store','X-Correlation-ID':correlation}});
    const path='/'+parts.join('/'),operation=matchDocumentOperation(request.method,path);
    if(!operation||parts.some(p=>!p||p==='.'||p==='..'||/[\\/%]/.test(p)))return failure(404,'NOT_FOUND','Không tìm thấy nội dung.');
    let origin:URL,webOrigin:URL;const secret=getSecret();
    try{
      origin=new URL(getOrigin()??'');webOrigin=new URL(getWebOrigin()??'');
      for(const url of [origin,webOrigin])if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw new Error();
      if(!secret||secret.length<32)throw new Error();
    }catch{return failure(503,'CONFIGURATION_ERROR','Dịch vụ tài liệu chưa được cấu hình.');}
    if(request.method!=='GET'&&request.headers.get('Origin')!==webOrigin.origin)return failure(403,'FORBIDDEN','Yêu cầu không hợp lệ.');
    if(!verifyClientContext(request.headers.get(CLIENT_CONTEXT_HEADER),request.method,'/api/document/v1'+path,secret))return failure(403,'FORBIDDEN','Yêu cầu không hợp lệ.');
    const incoming=new URL(request.url),target=new URL('/api/v1'+path,origin);
    for(const key of incoming.searchParams.keys()){
      if(!documentQueryKeys(operation).includes(key)||incoming.searchParams.getAll(key).length!==1)return failure(422,'VALIDATION_ERROR','Bộ lọc chưa hợp lệ.');
      target.searchParams.set(key,incoming.searchParams.get(key)!);
    }
    const headers=new Headers({Accept:operation.endsWith('File')?'application/octet-stream':'application/json','X-Correlation-ID':correlation});
    for(const key of ['authorization','content-type','idempotency-key']){const value=request.headers.get(key);if(value)headers.set(key,value);}
    if(!headers.get('authorization')?.startsWith('Bearer '))return failure(401,'UNAUTHENTICATED','Vui lòng đăng nhập.');
    const length=request.headers.get('Content-Length');if(length&&(!/^\d+$/.test(length)||Number(length)>MAX_BODY))return failure(413,'FILE_TOO_LARGE','Tệp vượt giới hạn tải lên.');
    let bytes=0,tooLarge=false;
    const body=request.method==='GET'?undefined:request.body?.pipeThrough(new TransformStream<Uint8Array,Uint8Array>({transform(chunk,controller){bytes+=chunk.byteLength;if(bytes>MAX_BODY){tooLarge=true;throw new Error('Body limit');}controller.enqueue(chunk);}}));
    try{
      const init:RequestInit&{duplex?:'half'}={method:request.method,headers,body,cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(120000),...(body?{duplex:'half' as const}:{})};
      const upstream=await fetcher(target,init);
      if(upstream.status>=300&&upstream.status<400)return failure(502,'UPSTREAM_ERROR','Phản hồi tài liệu chưa hợp lệ.');
      const responseHeaders=new Headers({'Cache-Control':'no-store','X-Correlation-ID':correlation,'X-Content-Type-Options':'nosniff'});
      for(const key of ['content-type','content-disposition']){const value=upstream.headers.get(key);if(value)responseHeaders.set(key,value);}
      let received=0;const stream=upstream.body?.pipeThrough(new TransformStream<Uint8Array,Uint8Array>({transform(chunk,controller){received+=chunk.byteLength;if(received>MAX_BODY)throw new Error('Response limit');controller.enqueue(chunk);}}));
      return new Response(stream??null,{status:upstream.status,headers:responseHeaders});
    }catch{return failure(tooLarge?413:503,tooLarge?'FILE_TOO_LARGE':'UPSTREAM_UNAVAILABLE',tooLarge?'Tệp vượt giới hạn tải lên.':'Chưa kết nối được dịch vụ tài liệu.');}
  };
}
