import type {BookmarkItem,ClassSummary,DocumentCapabilityPolicy,DocumentFormat,DocumentItem,DocumentVersion,PersonalNoteItem,ProcessingStatus} from '../domain';
import {ApiError} from './errors';
import {resourceUuid} from './operations';

export function documentMismatch():never{throw new ApiError('CONTRACT_MISMATCH','Phản hồi tài liệu không khớp hợp đồng. Hãy tải lại.');}
export function docRecord(value:unknown):Record<string,unknown>{return value&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:documentMismatch();}
export function docData(value:unknown){return docRecord(value).data;}
export function docText(value:unknown,max=10000):string{if(typeof value!=='string')return documentMismatch();if(value.length<=max)return value;let count=0;for(const _character of value){if(++count>max)return documentMismatch();}return value;}
export function docId(value:unknown){const id=docText(value,36);return resourceUuid.test(id)?id.toLowerCase():documentMismatch();}
export function docInt(value:unknown,min=0,max=Number.MAX_SAFE_INTEGER):number{return Number.isSafeInteger(value)&&Number(value)>=min&&Number(value)<=max?Number(value):documentMismatch();}
export function docBool(value:unknown):boolean{return typeof value==='boolean'?value:documentMismatch();}
function date(value:unknown){const text=docText(value,64);return /(?:Z|[+-]\d{2}:\d{2})$/.test(text)&&Number.isFinite(Date.parse(text))?text:documentMismatch();}
function format(value:unknown):DocumentFormat{return ['PDF','PPTX','DOCX','TXT','MD'].includes(String(value))?value as DocumentFormat:documentMismatch();}
function status(value:unknown):ProcessingStatus{return ['PENDING','PROCESSING','READY','FAILED'].includes(String(value))?value as ProcessingStatus:documentMismatch();}
const nullableNumber=(value:unknown)=>value===null?undefined:docInt(value,1);
const nullableText=(value:unknown,max=10000)=>value===null?undefined:docText(value,max);
export function docPage<T>(value:unknown,decode:(row:unknown)=>T){
  const row=docRecord(value),meta=docRecord(row.meta);if(!Array.isArray(row.data)||row.data.length>100)documentMismatch();
  const cursor=meta.next_cursor===null?null:docText(meta.next_cursor,512);if(cursor==='')documentMismatch();
  return {items:row.data.map(decode),nextCursor:cursor};
}
export function decodeCapabilities(value:unknown):{policy:DocumentCapabilityPolicy;classes:ClassSummary[]}{
  const row=docRecord(docData(value));
  if(!Array.isArray(row.allowed_extensions)||!Array.isArray(row.allowed_mime_types)||!Array.isArray(row.assigned_classes)||row.reader_mode!=='extracted_text'||row.supports_ocr!==false)documentMismatch();
  const extensions=row.allowed_extensions.map(value=>docText(value,8));if(extensions.some(value=>!['.pdf','.pptx','.docx','.txt','.md'].includes(value))||extensions.length!==5||new Set(extensions).size!==5)documentMismatch();
  const classes=row.assigned_classes.map(value=>{const item=docRecord(value);if(!['ACTIVE','ARCHIVED'].includes(String(item.status))||!['PRIMARY','ASSISTING'].includes(String(item.teaching_role)))documentMismatch();return {id:docId(item.id),name:docText(item.name,200),code:'',metadata:'',status:item.status as ClassSummary['status'],teachingRole:item.teaching_role as ClassSummary['teachingRole'],isAssignedTeacher:true};});
  if(new Set(classes.map(c=>c.id)).size!==classes.length)documentMismatch();
  return {policy:{maxSizeBytes:docInt(row.max_file_size_bytes,1,50*1024*1024),allowedExtensions:extensions,allowedMimeTypes:row.allowed_mime_types.map(value=>docText(value,200))},classes};
}
export function decodeDocument(value:unknown,classId?:string):DocumentItem{
  const row=docRecord(value),serving=nullableNumber(row.serving_version);
  const currentVersion=classId?(serving??0):docInt(row.latest_version,1);
  if(classId&&docId(row.class_id)!==classId.toLowerCase())documentMismatch();
  const count=row.locator_count===undefined||row.locator_count===null?undefined:docInt(row.locator_count,1,5000);
  const kind=row.locator_kind;if(count!==undefined&&!['PAGE','SLIDE','SECTION'].includes(String(kind)))documentMismatch();
  return {id:docId(row.id),title:docText(row.title,200),description:docText(row.description,4000),format:format(row.format),currentVersion,servingVersion:serving,
    processingStatus:status(row.latest_status),processingError:row.processing_error===undefined?undefined:nullableText(row.processing_error,1000),ownerId:docId(row.owner_id),ownerName:docText(row.owner_name,200),createdAt:date(row.created_at),updatedAt:date(row.updated_at),canManageSource:docBool(row.can_manage_source),
    ...(classId?{grantRevision:docInt(row.grant_revision,1),canRevokeGrant:docBool(row.can_revoke_grant)}:{revision:docInt(row.revision,1),sharedClassCount:docInt(row.shared_class_count)}),
    ...(count===undefined?{}:{locatorCountLabel:`${count} ${kind==='PAGE'?'trang':kind==='SLIDE'?'slide':'mục'}`,pageCount:kind==='PAGE'?count:undefined,slideCount:kind==='SLIDE'?count:undefined,sectionCount:kind==='SECTION'?count:undefined})};
}
export function decodeVersion(value:unknown):DocumentVersion{
  const row=docRecord(value),bytes=docInt(row.file_size_bytes,1,50*1024*1024);
  return {versionNumber:docInt(row.version_number,1),filename:docText(row.filename,255),fileSizeFormatted:`${(bytes/1024/1024).toFixed(2)} MiB`,uploadedAt:date(row.uploaded_at),status:status(row.status),errorMessage:nullableText(row.error_message,1000),isServing:docBool(row.is_serving),generation:docInt(row.generation)};
}
export function decodeGrant(value:unknown,documentId:string){
  const row=docRecord(value);if(docId(row.document_id)!==documentId.toLowerCase())documentMismatch();
  return {id:docId(row.id),classId:docId(row.class_id),schoolId:docId(row.school_id),active:docBool(row.is_active),revision:docInt(row.revision,1),grantedAt:date(row.granted_at)};
}
function sourceState(value:unknown):'ALLOWED'|'REVOKED'|'UNAVAILABLE'{return ['ALLOWED','REVOKED','UNAVAILABLE'].includes(String(value))?value as 'ALLOWED'|'REVOKED'|'UNAVAILABLE':documentMismatch();}
function personal(value:unknown,classes:ClassSummary[]){
  const row=docRecord(value),classId=docId(row.class_id),class_=classes.find(item=>item.id===classId),state=sourceState(row.source_access),locatorId=docText(row.locator_id,16);
  if(!/^[1-9][0-9]{0,3}$/.test(locatorId))documentMismatch();
  return {row,shared:{id:docId(row.id),documentId:docId(row.document_id),documentTitle:docText(row.document_title,200),documentFormat:format(row.document_format),version:docInt(row.version,1),classId,className:class_?.name??docText(row.class_name,200),locator:docText(row.locator_label,100),locatorId,pageNumber:Number(locatorId),isSourceAccessible:state==='ALLOWED',sourceAccess:state},class_};
}
export function decodeNote(value:unknown,classes:ClassSummary[]=[]):PersonalNoteItem{
  const {row,shared,class_}=personal(value,classes);const quote=nullableText(row.source_quote,2000);if(shared.sourceAccess!=='ALLOWED'&&quote!==undefined)documentMismatch();
  return {...shared,classStatus:class_?.status,revision:docInt(row.revision,1),clientRequestId:docId(row.client_request_id),noteText:docText(row.note_text,10000),sourceQuote:quote,updatedAt:date(row.updated_at),isArchivedClassEditable:class_?.status==='ARCHIVED'&&shared.isSourceAccessible};
}
export function decodeBookmark(value:unknown,classes:ClassSummary[]=[]):BookmarkItem{const {row,shared}=personal(value,classes);return {...shared,createdAt:date(row.created_at)};}
export function decodeReceipt(value:unknown,requestId:string){const row=docRecord(docData(value));if(docId(row.request_id)!==requestId.toLowerCase())documentMismatch();status(row.status);return {documentId:docId(row.document_id),version:docInt(row.version_number,1)};}
export function decodeContent(value:unknown,documentId:string,version:number){
  const row=docRecord(docData(value));if(docId(row.document_id)!==documentId.toLowerCase()||docInt(row.version,1)!==version||!Array.isArray(row.locators)||row.locators.length>100)documentMismatch();
  if(!['PAGE','SLIDE','SECTION'].includes(String(row.locator_kind)))documentMismatch();
  const pages=row.locators.map(value=>{const item=docRecord(value),number=docInt(item.number,1,5000);if(docText(item.id,16)!==String(number))documentMismatch();return {pageNumber:number,title:docText(item.title,200),paragraphs:[docText(item.text,8*1024*1024)]};});
  return {pages,total:docInt(row.total_locators,1,5000),label:(row.locator_kind==='PAGE'?'Trang':row.locator_kind==='SLIDE'?'Slide':'Mục') as 'Trang'|'Slide'|'Mục',nextCursor:row.next_cursor===null?null:docText(row.next_cursor,16),format:format(row.format)};
}
