import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {createLiveCoreApi} from '../src/lib/data/live-core';
import {createLiveDocument} from '../src/lib/data/live-document';
import {decodeNotificationPage} from '../src/lib/api/notification-decoders';
import {notificationTarget} from '../src/lib/notification-target';
import {ApiError} from '../src/lib/api/errors';
import type {WorkspaceData} from '../src/lib/domain';

if(process.env.CORE_SECURITY_TEST_MODE!=='synthetic')throw new Error('Synthetic fixture required');
function required(name:string){const value=process.env[name];if(!value)throw new Error('Missing fixture configuration');return value;}
const fixture=JSON.parse(readFileSync(required('CORE_BROWSER_FIXTURE_PATH'),'utf8'));
const web=new URL(required('CORE_SECURITY_WEB_URL'));
if(web.protocol!=='http:'||!['localhost','127.0.0.1'].includes(web.hostname)||web.origin!==fixture.web)throw new Error('Local synthetic fixture required');
let phase='startup',passed=0;
function pass(label:string){passed++;console.log('PASS '+label);}
function client(){
  let cookie='';
  const fetcher:typeof fetch=async(input,init={})=>{
    const path=String(input);assert.ok(path.startsWith('/api/v1/')||path.startsWith('/api/document/v1/'));
    const headers=new Headers(init.headers);if((init.method??'GET')!=='GET')headers.set('Origin',web.origin);
    if(path.startsWith('/api/v1/auth/')&&cookie)headers.set('Cookie',cookie);
    const response=await fetch(web.origin+path,{...init,headers});
    for(const value of response.headers.getSetCookie())cookie=/Max-Age=0(?:;|$)/i.test(value)?'':value.split(';',1)[0];
    return response;
  };
  const session=createLiveCoreSession({fetcher,onLost(){}}),api=createLiveCoreApi(session);
  return {session,api,documents:createLiveDocument(session,api)};
}
function ready(value:WorkspaceData){assert.equal(value.kind,'ready');if(value.kind!=='ready')throw new Error('Workspace not ready');return value;}
const status=(value:number)=>(error:unknown)=>error instanceof ApiError&&error.status===value;
async function until<T>(work:()=>Promise<T>,accept:(value:T)=>boolean,timeout=30000){const end=Date.now()+timeout;while(Date.now()<end){const value=await work();if(accept(value))return value;await new Promise(resolve=>setTimeout(resolve,250));}throw new Error('Processing/delivery not confirmed');}

async function main(){try{
  const teacher=client(),student=client(),admin=client();
  const teacherUser=await teacher.session.identity.login(fixture.teacher);
  const studentUser=await student.session.identity.login(fixture.student);
  await admin.session.identity.login({email:required('CORE_SECURITY_ADMIN_EMAIL'),password:required('CORE_SECURITY_ADMIN_PASSWORD')});
  phase='original multipart bytes, durable processing and download';
  const initial=ready(await teacher.documents.load('t.library',{}));assert.ok(initial.capabilityPolicy);assert.equal(initial.capabilityPolicy.maxSizeBytes,50*1024*1024);
  const file=new File(['Hello real document source\n\nSecond source section'],'source.md',{type:'text/markdown'}),requestId=randomUUID();
  const input={name:file.name,size:file.size,type:file.type,title:'Synthetic live document',description:'Actual byte fixture',file,requestId};
  const uploaded=await teacher.documents.port.uploadDocument(input);
  const replay=await teacher.documents.port.uploadDocument(input);assert.equal(replay.id,uploaded.id);
  assert.equal((await teacher.documents.port.uploadReceipt!(requestId)).documentId,uploaded.id);
  const documentId=uploaded.id;
  let detail=ready(await until(()=>teacher.documents.load('t.libraryDocument',{documentId}),value=>value.kind==='ready'&&value.sourceDocumentDetail?.versions[0]?.status==='READY')).sourceDocumentDetail!;
  assert.equal(detail.document.ownerId,teacherUser.id);assert.equal(detail.document.servingVersion,1);
  const downloaded=await teacher.documents.port.download!(documentId,1);assert.deepEqual(Buffer.from(await downloaded.arrayBuffer()),Buffer.from(await file.arrayBuffer()));
  await teacher.documents.port.updateMetadata!(documentId,'Updated live source','Confirmed metadata',detail.document.revision!);
  detail=ready(await teacher.documents.load('t.libraryDocument',{documentId})).sourceDocumentDetail!;assert.equal(detail.document.title,'Updated live source');
  pass('multipart bytes and hash-preserving original download, durable receipt replay and owner metadata');

  phase='class grant, student reader, notes and explicit bookmarks';
  await teacher.documents.port.shareDocument(documentId,[fixture.classId],detail.document.revision);
  const classDocs=ready(await student.documents.load('s.documents',{classId:fixture.classId}));assert.ok(classDocs.classDocuments?.some(doc=>doc.id===documentId));
  let reader=ready(await student.documents.load('s.reader',{classId:fixture.classId,documentId})).readerModel!;
  assert.equal(reader.locatorLabel,'Mục');assert.equal(reader.totalPages,2);assert.ok(reader.pageContents?.[0].paragraphs[0].includes('Hello real document source'));
  const note=await student.documents.port.saveNote({documentId,classId:fixture.classId,version:1,locator:'Mục 1',locatorId:'1',pageNumber:1,noteText:'My own handwritten fixture',sourceQuote:'Hello real document source',clientRequestId:randomUUID()});
  assert.equal(note.sourceQuote,'Hello real document source');assert.equal(note.isSourceAccessible,true);
  await student.documents.port.toggleBookmark(documentId,fixture.classId,'Mục 1',1,true);
  await student.documents.port.toggleBookmark(documentId,fixture.classId,'Mục 1',1,true);
  assert.equal(ready(await student.documents.load('s.notes',{})).studentBookmarks?.filter(item=>item.documentId===documentId).length,1);
  await assert.rejects(admin.documents.load('t.libraryDocument',{documentId}),status(403));
  pass('current class grant, real text reader/locators, private quoted notes and idempotent bookmark state');

  phase='failed newer version and fallback';
  const bad=new File([new Uint8Array([255,0,254])],'broken.md',{type:'text/markdown'});
  await teacher.documents.port.uploadVersion(documentId,{name:bad.name,size:bad.size,type:bad.type,file:bad,requestId:randomUUID()});
  detail=ready(await until(()=>teacher.documents.load('t.libraryDocument',{documentId}),value=>value.kind==='ready'&&value.sourceDocumentDetail?.versions[0]?.status==='FAILED')).sourceDocumentDetail!;
  assert.equal(detail.document.currentVersion,2);assert.equal(detail.document.servingVersion,1);
  reader=ready(await student.documents.load('s.reader',{classId:fixture.classId,documentId})).readerModel!;assert.equal(reader.servingVersion,1);
  await teacher.documents.port.retryProcessing(documentId,2);
  await until(()=>teacher.documents.load('t.libraryDocument',{documentId}),value=>value.kind==='ready'&&value.sourceDocumentDetail?.versions[0]?.status==='FAILED');
  pass('failed v2 and retry preserve the original file and serving v1');

  phase='immediate revoke and handwritten history redaction';
  detail=ready(await teacher.documents.load('t.libraryDocument',{documentId})).sourceDocumentDetail!;
  const grant=detail.grants.find(item=>item.classId===fixture.classId)!;
  await teacher.documents.port.revokeShare(documentId,fixture.classId,grant.revision);
  await assert.rejects(student.documents.port.download!(documentId,1,fixture.classId),status(403));
  await assert.rejects(student.documents.port.previewClassSource({documentId,classId:fixture.classId,version:1}),status(403));
  let personal=ready(await student.documents.load('s.notes',{})),saved=personal.studentNotes!.find(item=>item.id===note.id)!;
  assert.equal(saved.noteText,note.noteText);assert.equal(saved.sourceQuote,undefined);assert.equal(saved.isSourceAccessible,false);
  await assert.rejects(student.documents.port.saveNote({...saved,id:saved.id,locator:saved.locator,noteText:'denied edit',expectedRevision:saved.revision}),status(403));
  pass('revocation immediately denies original/source reads and redacts quotes while preserving own handwriting');

  phase='archived source-bound edits and current membership';
  detail=ready(await teacher.documents.load('t.libraryDocument',{documentId})).sourceDocumentDetail!;
  await teacher.documents.port.shareDocument(documentId,[fixture.classId],detail.document.revision);
  await admin.api.request('archiveClass',{classId:fixture.classId,reason:'USER_REQUEST'});
  personal=ready(await student.documents.load('s.notes',{}));saved=personal.studentNotes!.find(item=>item.id===note.id)!;
  const edited=await student.documents.port.saveNote({...saved,id:saved.id,locator:saved.locator,noteText:'Archived personal edit',expectedRevision:saved.revision});assert.equal(edited.noteText,'Archived personal edit');
  await student.documents.port.toggleBookmark(documentId,fixture.classId,'Mục 1',1,true);
  detail=ready(await teacher.documents.load('t.libraryDocument',{documentId})).sourceDocumentDetail!;
  await assert.rejects(teacher.documents.port.revokeShare(documentId,fixture.classId,detail.grants.find(item=>item.classId===fixture.classId)!.revision),status(403));
  await admin.api.request('restoreClass',{classId:fixture.classId,reason:'USER_REQUEST'});
  pass('ARCHIVED keeps permitted note/bookmark edits and denies grant changes; class restored afterward');

  phase='document events, scoped notifications, confirmed deletion and cleanup';
  const notifications=await until(()=>student.session.authenticated(async request=>decodeNotificationPage(await request('notifications',{limit:100}),studentUser.id)),page=>page.items.some(item=>item.documentId===documentId));
  const notification=notifications.items.find(item=>item.documentId===documentId)!;
  assert.ok(notificationTarget(notification,['STUDENT']).targetHref?.includes(documentId));
  detail=ready(await teacher.documents.load('t.libraryDocument',{documentId})).sourceDocumentDetail!;
  await assert.rejects(teacher.documents.port.deleteDocument(documentId,detail.document.revision,0),status(409));
  await teacher.documents.port.deleteDocument(documentId,detail.document.revision,1);
  personal=ready(await student.documents.load('s.notes',{}));saved=personal.studentNotes!.find(item=>item.id===note.id)!;
  assert.equal(saved.sourceQuote,undefined);await student.documents.port.deleteNote(saved.id,saved.revision);
  for(const bookmark of personal.studentBookmarks??[])if(bookmark.documentId===documentId)await student.documents.port.removeBookmark!(bookmark.id);
  assert.equal((await fetch(web.origin+'/api/document/v1/internal/v1/events')).status,404);
  await teacher.session.identity.logout();await student.session.identity.logout();await admin.session.identity.logout();
  pass('durable Document events reach Core notifications; deletion checks shared-class confirmation and preserves private history');
  console.log(JSON.stringify({passed,fixture:'synthetic',authenticatedHttp:true,documentService:true,browserInteraction:false}));
}catch(error){console.error(JSON.stringify({phase,passed,code:error instanceof ApiError?error.code:'CHECK_FAILED',status:error instanceof ApiError?error.status:undefined}));process.exitCode=1;}}
void main();
