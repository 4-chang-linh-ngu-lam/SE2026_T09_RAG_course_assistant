import type {DataRequest,DataRequestType,Page} from './domain';
import {ApiError,errorMessage} from './api/errors';
import {draftStore} from './draft-store';

export type RequestIssue={message:string;correlationId?:string};
export type RequestMutation='idle'|'submitting'|'confirmed'|'rejected'|'unknown';
type Intent={type:DataRequestType;reason:string};
type Cached={draft:Intent;mutation:RequestMutation;intent?:Intent;issue?:RequestIssue;operation?:number;confirmed:DataRequest[]};
export type DataRequestsState={draft:Intent;mutation:RequestMutation;submittedIntent?:Intent;mutationIssue?:RequestIssue;items:DataRequest[];loaded:boolean;listBusy:boolean;listError?:RequestIssue;nextCursor:string|null;lastConfirmedRequest?:DataRequest};
type Dependencies={actorId:string;listRequests(cursor?:string):Promise<Page<DataRequest>>;createRequest(type:DataRequestType,reason?:string):Promise<DataRequest>};
let operationSequence=0;
const types:DataRequestType[]=['ACCESS','EXPORT','CORRECTION','DELETE'];
function issue(error:unknown):RequestIssue{return {message:errorMessage(error),...(error instanceof ApiError&&error.correlationId?.trim()?{correlationId:error.correlationId.trim()}:{})};}
function unique(items:DataRequest[],actorId:string){return [...new Map(items.filter(r=>r.user_id===actorId).map(r=>[r.id,r])).values()];}

/** No list heuristic can establish whether a timed-out POST committed. Only its exact ACK can. */
export function createDataRequestController(deps:Dependencies){
 const epoch=draftStore.epoch,key=`${deps.actorId}:identity:data-request-state`;
 let cached=draftStore.get<Cached>(key)??{draft:{type:'ACCESS',reason:''},mutation:'idle',confirmed:[]};
 if(cached.mutation==='submitting')cached={...cached,mutation:'unknown',issue:{message:'Yêu cầu đã được gửi nhưng chưa nhận được xác nhận. Cần xác minh kết quả.'}};
 let state:DataRequestsState={draft:cached.draft,mutation:cached.mutation,submittedIntent:cached.intent,mutationIssue:cached.issue,items:cached.confirmed,loaded:false,listBusy:false,nextCursor:null,lastConfirmedRequest:cached.confirmed[0]};
 let disposed=false,listGeneration=0;const listeners=new Set<()=>void>(),seenCursors=new Set<string>();
 const active=()=>!disposed&&epoch===draftStore.epoch;
 function emit(patch:Partial<DataRequestsState>){if(!active())return;state={...state,...patch};listeners.forEach(l=>l());}
 function persist(next:Cached){if(epoch!==draftStore.epoch)return;cached=next;draftStore.set(key,next);}
 persist(cached);
 function adoptExactReceipt(){
  const stored=draftStore.get<Cached>(key);
  if(!stored||epoch!==draftStore.epoch)return;
  cached=stored;
  emit({draft:stored.draft,mutation:stored.mutation,submittedIntent:stored.intent,mutationIssue:stored.issue,lastConfirmedRequest:stored.confirmed[0]});
 }
 function edit(patch:Partial<Intent>){
  if(!active()||state.mutation==='submitting'||state.mutation==='unknown')return;
  const draft={...state.draft,...patch};persist({...cached,draft,mutation:'idle',issue:undefined});emit({draft,mutation:'idle',mutationIssue:undefined});
 }
 async function load(append:boolean){
  if(!active())return;
  if(append&&(state.listBusy||!state.nextCursor))return;
  adoptExactReceipt();
  const cursor=append?state.nextCursor!:undefined,id=++listGeneration;
  if(!append)seenCursors.clear();
  emit({listBusy:true,listError:undefined});
  try{
   const page=await deps.listRequests(cursor);
   if(!active()||id!==listGeneration)return;
   adoptExactReceipt();
   if(cursor)seenCursors.add(cursor);
   const repeated=page.next_cursor!==null&&seenCursors.has(page.next_cursor);
   emit({items:unique([...cached.confirmed,...(append?state.items:[]),...page.items],deps.actorId),loaded:true,nextCursor:repeated?null:page.next_cursor,listError:repeated?{message:'Danh sách trả về vị trí lặp. Hãy tải lại danh sách để kiểm tra.'}:undefined});
  }catch(error){if(active()&&id===listGeneration)emit({listError:issue(error)});}
  finally{if(active()&&id===listGeneration)emit({listBusy:false});}
 }
 async function submit(){
  if(!active()||state.mutation==='submitting'||state.mutation==='unknown')return 'ignored' as const;
  const intent={type:state.draft.type,reason:state.draft.reason.trim()};
  if(!types.includes(intent.type)||intent.reason.length>10000){emit({mutation:'rejected',mutationIssue:{message:'Loại yêu cầu hoặc nội dung không hợp lệ (tối đa 10.000 ký tự).'}});return 'rejected' as const;}
  const operation=++operationSequence;
  persist({...cached,intent,operation,mutation:'submitting',issue:undefined});emit({mutation:'submitting',submittedIntent:intent,mutationIssue:undefined});
  try{
   const receipt=await deps.createRequest(intent.type,intent.reason||undefined);
   if(receipt.user_id!==deps.actorId||!receipt.id)throw new ApiError('INVALID_RECEIPT','Chưa xác minh được phản hồi tạo yêu cầu.',0,'unknown');
   const current=draftStore.get<Cached>(key);
   if(epoch!==draftStore.epoch||current?.operation!==operation)return 'ignored' as const;
   // A late ACK from this exact promise may safely update the same actor/session's cache after unmount.
   persist({...current,draft:{type:intent.type,reason:''},mutation:'confirmed',issue:undefined,confirmed:unique([receipt,...current.confirmed],deps.actorId)});
   emit({draft:cached.draft,mutation:'confirmed',mutationIssue:undefined,lastConfirmedRequest:receipt,items:unique([receipt,...state.items.filter(r=>r.id!==receipt.id)],deps.actorId)});
   return 'confirmed' as const;
  }catch(error){
   const current=draftStore.get<Cached>(key);
   if(epoch!==draftStore.epoch||current?.operation!==operation)return 'ignored' as const;
   const mutation=error instanceof ApiError&&error.outcome==='rejected'?'rejected':'unknown';
   const mutationIssue=issue(error);persist({...current,mutation,issue:mutationIssue});emit({mutation,mutationIssue});return mutation;
  }
 }
 return {getState:()=>state,subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener);};},setDraftType(type:DataRequestType){if(types.includes(type))edit({type});},setDraftReason(reason:string){edit({reason});},refreshList:()=>load(false),loadMore:()=>load(true),submit,dispose(){disposed=true;listGeneration++;listeners.clear();}};
}
