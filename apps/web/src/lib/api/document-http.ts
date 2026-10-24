import {ApiError} from './errors';
import {documentOperations,documentPath,documentQueryKeys,type DocumentOperation,type DocumentParams} from './document-operations';
export type DocumentOptions=DocumentParams&{body?:unknown;fileBody?:FormData;idempotencyKey?:string;query?:Record<string,string|number|undefined>;signal?:AbortSignal};
export function createDocumentHttpClient(getToken:()=>string|null,fetcher:typeof fetch=fetch){
  return async function request(operation:DocumentOperation,options:DocumentOptions={}):Promise<unknown>{
    const [method,,status]=documentOperations[operation];const mutation=method!=='GET';
    let path:string;try{path=documentPath(operation,options);}catch{throw new ApiError('VALIDATION_ERROR','Định danh tài liệu không hợp lệ.',422);}
    const query=new URLSearchParams();for(const [key,value]of Object.entries(options.query??{})){
      if(value===undefined)continue;if(!documentQueryKeys(operation).includes(key))throw new ApiError('VALIDATION_ERROR','Bộ lọc tài liệu chưa được hỗ trợ.',422);query.set(key,String(value));
    }
    const headers=new Headers({Accept:'application/json'}),token=getToken();if(token)headers.set('Authorization',`Bearer ${token}`);
    if(options.idempotencyKey)headers.set('Idempotency-Key',options.idempotencyKey);
    if(options.body!==undefined)headers.set('Content-Type','application/json');
    const timeout=AbortSignal.timeout(options.fileBody?120000:30000),signal=options.signal?AbortSignal.any([timeout,options.signal]):timeout;
    try{
      const response=await fetcher(`/api/document/v1${path}${query.size?'?'+query:''}`,{method,headers,credentials:'omit',cache:'no-store',signal,body:options.fileBody??(options.body===undefined?undefined:JSON.stringify(options.body))});
      const correlation=response.headers.get('X-Correlation-ID')??undefined,outcome=mutation&&(response.ok||response.status>=500)?'unknown':'rejected';
      if(response.ok&&response.status!==status)throw new ApiError('CONTRACT_MISMATCH','Phản hồi tài liệu chưa đúng trạng thái xác nhận.',response.status,outcome,correlation);
      if(response.ok&&(operation==='classFile'||operation==='ownerFile'))return response.blob();
      let value:unknown;try{value=await response.json();}catch{throw new ApiError('INVALID_RESPONSE','Phản hồi tài liệu chưa hợp lệ.',response.status,outcome,correlation);}
      if(!response.ok){const row=value as {error?:{code?:string;message?:string}};throw new ApiError(typeof row?.error?.code==='string'?row.error.code:'REQUEST_FAILED',typeof row?.error?.message==='string'?row.error.message:'Chưa thể hoàn tất yêu cầu tài liệu.',response.status,outcome,correlation);}
      return value;
    }catch(error){if(error instanceof ApiError)throw error;throw new ApiError('CONNECTION_ERROR','Chưa kết nối được dịch vụ tài liệu.',0,mutation?'unknown':'rejected');}
  };
}
