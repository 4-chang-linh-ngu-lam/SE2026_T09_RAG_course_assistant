import type {CoreApiPort,CoreImportPreview,CoreImportReceipt,CoreOptions,CoreUser} from './api/core-contract';
import type {AdminReason} from './api/operations';
import type {DataRequest} from './domain';
import {adminReasons} from './api/operations';
import {ApiError,errorMessage} from './api/errors';
import {allCorePages} from './data/live-classroom-social';

export type StaffDraft=CoreOptions<'createStaff'>['body']&{reason:AdminReason};
export type ResolutionDraft=CoreOptions<'resolveDataRequest'>['body']&{reason:AdminReason};
type Operation='staff'|'preview'|'confirm'|'resolve'|'read';
export type CoreAdminState={
  busy:boolean;unknown:Exclude<Operation,'read'>|null;issue:{message:string;correlationId?:string}|null;
  staff:CoreUser|null;filename:string|null;preview:CoreImportPreview|null;receipt:CoreImportReceipt|null;
  requests:DataRequest[];selected:DataRequest|null;loaded:boolean;
};
const initial=():CoreAdminState=>({busy:false,unknown:null,issue:null,staff:null,filename:null,preview:null,receipt:null,requests:[],selected:null,loaded:false});
function invalid(message:string):never{throw new ApiError('VALIDATION_ERROR',message,422);}
function reason(value:AdminReason){if(!adminReasons.includes(value))invalid('Chọn mã lý do hợp lệ.');}

export function createCoreAdminController(api:CoreApiPort,isCurrentActor:()=>boolean){
  let state=initial(),active=true,uncertainRequestId:string|null=null,pendingImportReason:AdminReason|null=null;
  const listeners=new Set<()=>void>(),abort=new AbortController();
  const current=()=>active&&isCurrentActor();
  const publish=(patch:Partial<CoreAdminState>)=>{if(current()){state={...state,...patch};for(const listener of listeners)listener();}};
  const check=()=>{if(!current())throw new ApiError('SESSION_CHANGED','Phiên đăng nhập đã thay đổi.',401);};
  async function run(operation:Operation,work:()=>Promise<void>,allowUnknown=false){
    if(!current()||state.busy||state.unknown&&!allowUnknown)return;
    publish({busy:true,issue:null});
    try{await work();}
    catch(error){
      if(operation==='resolve'&&!(error instanceof ApiError&&error.outcome==='unknown'))uncertainRequestId=null;
      publish({issue:{message:errorMessage(error),...(error instanceof ApiError&&error.correlationId?{correlationId:error.correlationId}:{})},
        ...(operation==='read'&&error instanceof ApiError&&[401,403].includes(error.status)?{requests:[],selected:null,loaded:false}:{}),
        ...(operation!=='read'&&error instanceof ApiError&&error.outcome==='unknown'?{unknown:operation}:{})});
    }finally{publish({busy:false});}
  }
  return {
    getState:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener);};},
    dispose(){active=false;abort.abort();listeners.clear();state=initial();},
    clearCodes(){if(!current()||state.busy||state.unknown)return;pendingImportReason=null;publish({receipt:null,preview:null,filename:null});},
    invite(input:StaffDraft){return run('staff',async()=>{
      reason(input.reason);
      if(!input.email.trim()||input.email.length>320||!input.roles.length||input.roles.some(role=>role!=='ADMIN'&&role!=='LECTURER')||new Set(input.roles).size!==input.roles.length)invalid('Nhập email và chọn vai trò staff hợp lệ.');
      publish({staff:null});
      const staff=await api.request('createStaff',{body:{email:input.email.trim().toLowerCase(),roles:input.roles},reason:input.reason,signal:abort.signal});
      check();publish({staff});
    });},
    previewFile(file:Pick<File,'name'|'size'|'arrayBuffer'>){return run('preview',async()=>{
      if(state.receipt)invalid('Xác nhận đã bàn giao mã trước khi chọn tệp khác.');
      const format=/\.csv$/i.test(file.name)?'CSV':/\.xlsx$/i.test(file.name)?'XLSX':invalid('Chọn tệp CSV UTF-8 hoặc XLSX.');
      if(file.size<1||file.size>2_000_000)invalid('Tệp phải có dữ liệu và không vượt quá 2.000.000 byte.');
      publish({filename:file.name,preview:null,receipt:null});
      const bytes=new Uint8Array(await file.arrayBuffer());check();
      if(bytes.byteLength!==file.size)invalid('Kích thước tệp đã thay đổi. Chọn lại tệp.');
      let binary='';for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
      const preview=await api.request('previewImport',{body:{format,content_base64:btoa(binary)},signal:abort.signal});
      check();publish({preview});
    });},
    confirmImport(adminReason:AdminReason,reconfirm=false){return run('confirm',async()=>{
      reason(adminReason);
      if(state.receipt)return;
      const preview=state.preview;
      if(!preview?.valid||!preview.preview_id||!preview.expires_at)invalid('Cần bản xem trước hợp lệ trước khi xác nhận.');
      // A deliberate re-confirm uses the same durable preview receipt. It may
      // finish the import; it is never presented as a read-only status check.
      if(state.unknown&&(!reconfirm||state.unknown!=='confirm'))return;
      if(reconfirm&&pendingImportReason!==adminReason)invalid('Giữ nguyên lý do của lần xác nhận chưa rõ kết quả.');
      pendingImportReason=adminReason;
      const receipt=await api.request('confirmImport',{body:{preview_id:preview.preview_id},reason:adminReason,signal:abort.signal});
      check();publish({receipt,unknown:null});
    },reconfirm&&state.unknown==='confirm');},
    loadRequests(){return run('read',async()=>{
      const bounded=AbortSignal.any([abort.signal,AbortSignal.timeout(15000)]);
      const requests=await allCorePages(cursor=>{check();return api.request('adminDataRequests',{cursor,limit:100,signal:bounded});},bounded);
      check();
      const selectedId=uncertainRequestId??state.selected?.id;
      const selected=selectedId?await api.request('adminDataRequest',{requestId:selectedId,signal:bounded}):null;
      check();publish({requests:requests.map(row=>row.id===selected?.id?selected:row),selected,loaded:true,...(state.unknown==='resolve'?{unknown:null}:{})});
      uncertainRequestId=null;
    },true);},
    selectRequest(requestId:string){return run('read',async()=>{
      if(state.unknown)return;
      // Never leave the previous request actionable while selecting another.
      publish({selected:null});
      const selected=await api.request('adminDataRequest',{requestId,signal:abort.signal});check();publish({selected});
    });},
    resolve(input:ResolutionDraft){return run('resolve',async()=>{
      reason(input.reason);const selected=state.selected;
      if(!selected)invalid('Chọn yêu cầu cần xem xét.');
      if(input.status!=='IN_REVIEW'&&!input.identity_verified)invalid('Cần xác nhận đã kiểm tra danh tính trước quyết định cuối.');
      uncertainRequestId=selected.id;
      const response=await api.request('resolveDataRequest',{requestId:selected.id,body:{status:input.status,resolution_note:input.resolution_note,identity_verified:input.identity_verified},reason:input.reason,signal:abort.signal});
      check();uncertainRequestId=null;
      publish({selected:response,requests:state.requests.map(row=>row.id===response.id?response:row)});
    });},
  };
}
export type CoreAdminController=ReturnType<typeof createCoreAdminController>;
