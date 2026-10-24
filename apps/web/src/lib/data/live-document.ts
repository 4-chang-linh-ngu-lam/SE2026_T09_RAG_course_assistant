import type {DataAdapter} from './port';
import type {createLiveCoreSession} from './live-identity';
import type {CoreApiPort} from '../api/core-contract';
import type {BookmarkItem,ClassSummary,DocumentItem,DocumentVersion,PersonalNoteItem,RouteParams,WorkspaceData} from '../domain';
import type {DocumentOptions} from '../api/document-http';
import type {DocumentOperation} from '../api/document-operations';
import {ApiError} from '../api/errors';
import {decodeMutation} from '../api/decoders';
import {decodeBookmark,decodeCapabilities,decodeContent,decodeDocument,decodeGrant,decodeNote,decodeReceipt,decodeVersion,docBool,docData,docInt,docPage,docRecord,documentMismatch} from '../api/document-decoders';
import {allCorePages,coreClassSummary} from './live-classroom-social';
import {canonicalResourceId} from '../api/operations';

type Session=Pick<ReturnType<typeof createLiveCoreSession>,'documentAuthenticated'|'getActorId'>;
export function createLiveDocument(session:Session,core:CoreApiPort){
  const call=(id:DocumentOperation,options:DocumentOptions={},mutation=false)=>session.documentAuthenticated(request=>request(id,options),mutation);
  const revision=(value:number|undefined)=>{if(!Number.isSafeInteger(value)||Number(value)<0)throw new ApiError('STALE_DOCUMENT','Hãy tải lại để lấy phiên bản xác nhận hiện tại.',409);return value!;};
  async function pages<T>(operation:DocumentOperation,decode:(value:unknown)=>T,options:DocumentOptions={}):Promise<T[]>{
    const rows:T[]=[],seen=new Set<string>();let cursor:string|undefined;
    do{
      const page=docPage(await call(operation,{...options,query:{...options.query,limit:100,...(cursor?{cursor}:{})}}),decode);
      rows.push(...page.items);
      if(page.nextCursor&&(!page.items.length||seen.has(page.nextCursor)||seen.size>=99))documentMismatch();
      cursor=page.nextCursor??undefined;if(cursor)seen.add(cursor);
    }while(cursor);
    return rows;
  }
  function ownedDocument(value:unknown,expectedId?:string){const item=decodeDocument(value);if(item.ownerId!==session.getActorId()||!item.canManageSource||expectedId&&item.id!==expectedId.toLowerCase())documentMismatch();return item;}
  async function detail(documentId:string,signal?:AbortSignal){return ownedDocument(docData(await call('detail',{documentId,signal})),documentId);}
  const postRead=async<T>(run:()=>Promise<T>)=>{try{return await run();}catch(error){if(error instanceof ApiError)error.outcome='unknown';throw error;}};
  async function content(documentId:string,version:number,classId?:string,signal?:AbortSignal){
    const result:ReturnType<typeof decodeContent>['pages']=[],seen=new Set<string>();let cursor:string|undefined,total=0,label:'Trang'|'Slide'|'Mục'='Mục';
    do{
      const page=decodeContent(await call(classId?'classContent':'ownerContent',{documentId,version,classId,signal,query:{limit:100,...(cursor?{cursor}:{})}}),documentId,version);
      if(total&&total!==page.total)documentMismatch();total=page.total;label=page.label;result.push(...page.pages);
      if(page.nextCursor&&(!page.pages.length||seen.has(page.nextCursor)||seen.size>=99))documentMismatch();
      cursor=page.nextCursor??undefined;if(cursor)seen.add(cursor);
    }while(cursor);
    if(result.length!==total||result.some((page,i)=>page.pageNumber!==i+1))documentMismatch();
    return {pages:result,total,label};
  }
  const supported=new Set(['t.library','t.libraryDocument','t.documents','s.documents','s.reader','s.notes']);
  async function load(routeId:string,params:RouteParams,signal?:AbortSignal):Promise<WorkspaceData>{
    const actor=session.getActorId();if(!actor)throw new ApiError('SESSION_CHANGED','Vui lòng đăng nhập lại.',401);
    const deadline=AbortSignal.timeout(30000),bounded=signal?AbortSignal.any([signal,deadline]):deadline;
    const check=()=>{if(actor!==session.getActorId())throw new ApiError('SESSION_CHANGED','Phiên đăng nhập đã thay đổi.',401);if(bounded.aborted)throw new ApiError('CONNECTION_ERROR','Đã dừng tải tài liệu.',0);};
    const capabilities=decodeCapabilities(await call('capabilities',{signal:bounded}));check();
    const base={kind:'ready' as const,capabilityPolicy:capabilities.policy};
    if(routeId==='t.library')return {...base,libraryDocuments:await pages('documents',value=>ownedDocument(value),{signal:bounded})};
    if(routeId==='t.libraryDocument'){
      const documentId=canonicalResourceId(params.documentId);
      const document=await detail(documentId,bounded);
      const versions=await pages('versions',decodeVersion,{documentId,signal:bounded});
      const raw=await pages('grants',value=>decodeGrant(value,documentId),{documentId,signal:bounded});
      check();return {...base,sourceDocumentDetail:{document,versions,shareableClasses:capabilities.classes,grants:raw.map(grant=>{
        const class_=capabilities.classes.find(item=>item.id===grant.classId);
        return {classId:grant.classId,className:class_?.name??grant.classId,classCode:class_?.code??'',isShared:grant.active,grantedAt:grant.grantedAt,servingVersion:document.servingVersion??0,classStatus:class_?.status,revision:grant.revision};
      })}};
    }
    if(routeId==='s.notes'){
      const classes=await allCorePages(cursor=>core.request('classes',{cursor,limit:100,signal:bounded}),bounded);check();
      // These labels do not grant source access. Document has already checked each note/bookmark.
      const labels:ClassSummary[]=classes.map(row=>({id:row.id,name:row.name,status:row.status,code:'',metadata:''}));
      const notes=await pages('notes',value=>decodeNote(value,labels),{signal:bounded});
      const bookmarks=await pages('bookmarks',value=>decodeBookmark(value,labels),{signal:bounded});check();
      return {...base,studentNotes:notes,studentBookmarks:bookmarks};
    }
    const classId=canonicalResourceId(params.classId),klass=await core.request('classDetail',{classId,signal:bounded});check();
    const classSummary:ClassSummary=capabilities.classes.find(item=>item.id===classId)??{id:klass.id,name:klass.name,status:klass.status,code:'',metadata:''};
    if(routeId==='t.documents'||routeId==='s.documents'){
      const docs=await pages('classDocuments',value=>decodeDocument(value,classId),{classId,signal:bounded});
      const bookmarks=routeId==='s.documents'?await pages('bookmarks',value=>decodeBookmark(value,[classSummary]),{query:{class_id:classId},signal:bounded}):[];check();
      return {...base,classSummary,classDocuments:docs.map(doc=>({...doc,isBookmarked:bookmarks.some(b=>b.documentId===doc.id&&b.version===doc.currentVersion&&b.pageNumber===1)}))};
    }
    const documentId=canonicalResourceId(params.documentId);
    const notes=await pages('notes',value=>decodeNote(value,[classSummary]),{signal:bounded,query:{class_id:classId,document_id:documentId}});
    let doc:DocumentItem;
    try{doc=decodeDocument(docData(await call('classDocument',{classId,documentId,signal:bounded})),classId);if(doc.id!==documentId)documentMismatch();}
    catch(error){
      if(!(error instanceof ApiError)||error.status!==403||!notes.length)throw error;
      check();return {kind:'unavailable',message:'Bạn không còn quyền mở nguồn này. Chữ tự viết vẫn được giữ trong Sổ tay / Ghi chú cá nhân; phần trích dẫn đã được che.'};
    }
    if(!doc.servingVersion)return {kind:'unavailable',message:'Nguồn đang chờ xử lý. Bạn có thể quay lại danh sách và tải lại trạng thái.'};
    const version=params.version?Number(params.version):doc.servingVersion;if(!Number.isSafeInteger(version)||version<=0)throw new ApiError('VALIDATION_ERROR','Phiên bản không hợp lệ.',422);
    const source=await content(documentId,version,classId,bounded);
    const bookmarks=await pages('bookmarks',value=>decodeBookmark(value,[classSummary]),{signal:bounded,query:{class_id:classId,document_id:documentId}});check();
    const currentPage=Math.max(1,Math.min(Number(params.page)||1,source.total));
    return {...base,classSummary,readerModel:{document:{...doc,isBookmarked:bookmarks.some(b=>b.version===version&&b.pageNumber===currentPage)},servingVersion:doc.servingVersion,viewingVersion:version,locatorLabel:source.label,bookmarks:bookmarks.map(item=>({version:item.version!,locatorId:item.locatorId!})),isSourceAccessible:true,outline:source.pages.map(p=>({id:String(p.pageNumber),label:p.title,pageNumber:p.pageNumber})),currentPage,totalPages:source.total,pageContents:source.pages,notes:notes.filter(n=>n.version===version)}};
  }
  const port:DataAdapter['document']={
    async uploadDocument(input){
      if(!input.file||!input.requestId)throw new ApiError('VALIDATION_ERROR','Cần tệp gốc và mã upload.',422);
      const body=new FormData();body.set('file',input.file);body.set('title',input.title);body.set('description',input.description??'');
      const receipt=decodeMutation(value=>decodeReceipt(value,input.requestId!),await call('upload',{fileBody:body,idempotencyKey:input.requestId},true));
      return postRead(()=>detail(receipt.documentId));
    },
    async uploadVersion(documentId,input){
      if(!input.file||!input.requestId)throw new ApiError('VALIDATION_ERROR','Cần tệp gốc và mã upload.',422);
      const body=new FormData();body.set('file',input.file);
      const receipt=decodeMutation(value=>decodeReceipt(value,input.requestId!),await call('uploadVersion',{documentId,fileBody:body,idempotencyKey:input.requestId},true));
      return postRead(async()=>{const versions=await pages('versions',decodeVersion,{documentId});const version=versions.find(v=>v.versionNumber===receipt.version);return version??documentMismatch();});
    },
    async retryProcessing(documentId,number){
      const versions=await pages('versions',decodeVersion,{documentId});const version=number?versions.find(v=>v.versionNumber===number):versions[0];if(!version)documentMismatch();
      decodeMutation(value=>decodeVersion(docData(value)),await call('retry',{documentId,version:version.versionNumber,body:{expected_generation:version.generation}},true));
      return postRead(()=>detail(documentId));
    },
    async shareDocument(documentId,classIds,expectedRevision){const result=await call('share',{documentId,body:{class_ids:classIds,expected_revision:revision(expectedRevision)}},true);decodeMutation(value=>{const rows=docData(value);if(!Array.isArray(rows)||rows.length!==classIds.length)documentMismatch();for(const row of rows){const grant=decodeGrant(row,documentId);if(!grant.active||!classIds.includes(grant.classId))documentMismatch();}},result);},
    async revokeShare(documentId,classId,expectedRevision){decodeMutation(value=>{const grant=decodeGrant(docData(value),documentId);if(grant.classId!==classId||grant.active)documentMismatch();},await call('revoke',{documentId,classId,body:{expected_revision:revision(expectedRevision)}},true));},
    async deleteDocument(documentId,expectedRevision,count){if(count===undefined)throw new ApiError('VALIDATION_ERROR','Cần xác nhận số lớp bị ảnh hưởng.',422);decodeMutation(value=>{const row=docRecord(docData(value));if(row.id!==documentId||row.deleted!==true)documentMismatch();},await call('delete',{documentId,body:{expected_revision:revision(expectedRevision),confirmed_shared_class_count:count}},true));},
    async previewClassSource(input){const doc=decodeDocument(docData(await call('classDocument',{classId:input.classId,documentId:input.documentId,signal:input.signal})),input.classId);if(doc.id!==input.documentId.toLowerCase())documentMismatch();const source=await content(input.documentId,input.version,input.classId,input.signal);return {documentId:doc.id,classId:input.classId,title:doc.title,version:input.version,totalPages:source.total,pages:source.pages,locatorLabel:source.label};},
    async saveNote(input){
      if(!input.id&&!input.clientRequestId)throw new ApiError('VALIDATION_ERROR','Cần mã yêu cầu để lưu ghi chú không trùng.',422);
      const result=await call(input.id?'editNote':'createNote',{documentId:input.documentId,classId:input.classId,noteId:input.id,body:input.id?{note_text:input.noteText,expected_revision:revision(input.expectedRevision)}:{version:input.version,locator_id:input.locatorId??String(input.pageNumber??Number(input.locator.match(/\d+/)?.[0])),note_text:input.noteText,source_quote:input.sourceQuote??null,client_request_id:input.clientRequestId??crypto.randomUUID()}},true);
      return decodeMutation(value=>{const note=decodeNote(docData(value));if(note.documentId!==input.documentId||note.classId!==input.classId||input.id&&note.id!==input.id)documentMismatch();return note;},result);
    },
    async deleteNote(noteId,expectedRevision){decodeMutation(value=>{const row=docRecord(docData(value));if(row.id!==noteId||row.deleted!==true)documentMismatch();},await call('deleteNote',{noteId,body:{expected_revision:revision(expectedRevision)}},true));},
    async toggleBookmark(documentId,classId,locator,version,desired){
      const doc=decodeDocument(docData(await call('classDocument',{documentId,classId})),classId),number=version??doc.servingVersion;if(!number)throw new ApiError('SOURCE_PENDING','Nguồn chưa xử lý thành công.',409);
      const locatorId=String(Number(locator?.match(/\d+/)?.[0]??1));
      let bookmarked=desired;if(bookmarked===undefined){const values=await pages('bookmarks',value=>decodeBookmark(value),{query:{document_id:documentId,class_id:classId}});bookmarked=!values.some(b=>b.version===number&&b.locatorId===locatorId);}
      return decodeMutation(value=>{const row=docRecord(docData(value));if(docBool(row.bookmarked)!==bookmarked)documentMismatch();return {bookmarked:row.bookmarked as boolean};},await call('setBookmark',{documentId,classId,version:number,locatorId,body:{bookmarked}},true));
    },
    async removeBookmark(bookmarkId){decodeMutation(value=>{const row=docRecord(docData(value));if(row.id!==bookmarkId||row.deleted!==true)documentMismatch();},await call('deleteBookmark',{bookmarkId},true));},
    async uploadReceipt(requestId){return decodeReceipt(await call('receipt',{requestId}),requestId);},
    async download(documentId,version,classId){const result=await call(classId?'classFile':'ownerFile',{documentId,version,classId});if(!(result instanceof Blob))documentMismatch();return result;},
    async updateMetadata(documentId,title,description,expectedRevision){return decodeMutation(value=>decodeDocument(docData(value)),await call('edit',{documentId,body:{title,description,expected_revision:revision(expectedRevision)}},true));},
  };
  return {port,load,supports:(routeId:string)=>supported.has(routeId)};
}
