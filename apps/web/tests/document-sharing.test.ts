import test from 'node:test';
import assert from 'node:assert/strict';
import {adapter} from '../dev/mocks/adapter';
import {ApiError} from '../src/lib/api/errors';
import {documentGrantConfirmed,newShareTargets} from '../src/lib/document-sharing';
import type {WorkspaceData,ClassSummary} from '../src/lib/domain';
const owner={email:'ha.nguyen@lumi.example',password:'ValidPassword123!'};
const assistant={email:'minh.tran@lumi.example',password:'ValidPassword123!'};
const C1='00000000-0000-4000-8000-000000000101',C2='00000000-0000-4000-8000-000000000102',OTHER='00000000-0000-4000-8000-000000000104',ARCHIVED='00000000-0000-4000-8000-000000000199';
async function fresh(){await adapter.identity.login(owner);return adapter.document.uploadDocument({name:'first-share.pdf',size:4096,type:'application/pdf',title:'First share regression'});}
async function detail(id:string){const data=await adapter.workspace.load('t.libraryDocument',{documentId:id});assert.equal(data.kind,'ready');if(data.kind!=='ready'||!data.sourceDocumentDetail)throw Error('Missing source');return data.sourceDocumentDetail;}
test('LF-101 first share discovers assigned active classes independently of empty grants',async()=>{
 const doc=await fresh(),data=await detail(doc.id);
 assert.equal(data.grants.length,0);
 const ids=data.shareableClasses!.map(c=>c.id);
 assert.ok(ids.includes(C1));assert.ok(ids.includes(C2));assert.ok(!ids.includes(OTHER));assert.ok(!ids.includes(ARCHIVED));
 await adapter.document.shareDocument(doc.id,[C1,C2]);
 const after=await detail(doc.id);assert.equal(after.grants.filter(g=>g.isShared).length,2);
 assert.ok(after.grants.every(g=>g.servingVersion===1&&g.classStatus==='ACTIVE'));
});
test('LF-101 batch validation is atomic, deduplicates and cannot share outside assignment',async()=>{
 const doc=await fresh();
 await assert.rejects(()=>adapter.document.shareDocument(doc.id,[C1,OTHER]),(e:unknown)=>e instanceof ApiError&&e.status===403);
 assert.equal((await detail(doc.id)).grants.length,0);
 await assert.rejects(()=>adapter.document.shareDocument(doc.id,[ARCHIVED]),(e:unknown)=>e instanceof ApiError&&e.status===403);
 await assert.rejects(()=>adapter.document.shareDocument(doc.id,[]));
 await adapter.document.shareDocument(doc.id,[C1,C1]);await adapter.document.shareDocument(doc.id,[C1]);
 assert.equal((await detail(doc.id)).grants.length,1);
});
test('LF-101 regrant follows latest READY version and refreshes target metadata',async()=>{
 const doc=await fresh();await adapter.document.shareDocument(doc.id,[C1]);await adapter.document.revokeShare(doc.id,C1);
 await adapter.document.uploadVersion(doc.id,{name:'next.pdf',size:1234,type:'application/pdf'});
 await adapter.document.uploadVersion(doc.id,{name:'fail.pdf',size:1234,type:'application/pdf'});
 await adapter.document.shareDocument(doc.id,[C1]);assert.equal((await detail(doc.id)).grants[0].servingVersion,2);
});
test('LF-102 revoke affects exact class only; assistant can revoke but cannot manage foreign source',async()=>{
 const doc=await fresh();await adapter.document.shareDocument(doc.id,[C1,C2]);
 await adapter.identity.login(assistant);await adapter.document.revokeShare(doc.id,C1);
 await assert.rejects(()=>adapter.document.uploadVersion(doc.id,{name:'other.pdf',size:1234,type:'application/pdf'}),(e:unknown)=>e instanceof ApiError&&e.status===403);
 await assert.rejects(()=>adapter.document.deleteDocument(doc.id),(e:unknown)=>e instanceof ApiError&&e.status===403);
 await adapter.identity.login(owner);const after=await detail(doc.id);
 assert.equal(after.grants.find(g=>g.classId===C1)?.isShared,false);assert.equal(after.grants.find(g=>g.classId===C2)?.isShared,true);
 await assert.rejects(()=>adapter.document.revokeShare(doc.id,ARCHIVED),(e:unknown)=>e instanceof ApiError&&e.status===403);
});
test('LF-101/102 only new eligible class selections are additive targets',()=>{
 const classes=[{id:'active',status:'ACTIVE'},{id:'shared',status:'ACTIVE'},{id:'archived',status:'ARCHIVED'}] as ClassSummary[];
 const grants=[{classId:'shared',className:'Shared',classCode:'S',servingVersion:1,isShared:true}];
 assert.deepEqual(newShareTargets(['active','active','shared','archived','foreign'],classes,grants),['active']);
 assert.deepEqual(newShareTargets(['active'],[],grants),[]);
});
test('LF-102 unknown reconciliation requires exact target state; negative/partial/read failure stays unknown',()=>{
 const document={id:'doc',title:'T',format:'PDF' as const,currentVersion:1,processingStatus:'READY' as const,ownerId:'owner',ownerName:'Owner',createdAt:'2026-10-20',updatedAt:'2026-10-20'};
 const data={kind:'ready',sourceDocumentDetail:{document,versions:[],grants:[{classId:'a',className:'A',classCode:'A',servingVersion:1,isShared:true},{classId:'b',className:'B',classCode:'B',servingVersion:1,isShared:false}]}} as WorkspaceData;
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['a'],shared:true},data),true);
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['a','b'],shared:true},data),false);
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['b'],shared:false},data),true);
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['a'],shared:false},data),false);
 assert.equal(documentGrantConfirmed({documentId:'other',classIds:['b'],shared:false},data),false);
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['b'],shared:false},{kind:'unavailable',message:'Offline'}),false);
 const classData:WorkspaceData={kind:'ready',classSummary:{id:'a',name:'A',code:'A',metadata:'',status:'ACTIVE'},classDocuments:[]};
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['a'],shared:false,classRoute:'a'},classData),true);
 assert.equal(documentGrantConfirmed({documentId:'doc',classIds:['b'],shared:false,classRoute:'b'},classData),false);
});
