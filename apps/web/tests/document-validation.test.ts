import test from 'node:test';
import assert from 'node:assert/strict';
import {documentFileError,documentFileSelection} from '../src/lib/document-upload';
import {documentVersionState} from '../src/lib/document-versions';
import {adapter} from '../dev/mocks/adapter';
import type {DocumentCapabilityPolicy,DocumentVersion} from '../src/lib/domain';
const policy:DocumentCapabilityPolicy={maxSizeBytes:1024*1024,allowedExtensions:['.pdf','.txt','.md'],allowedMimeTypes:[]};
const good={name:'source.PDF',size:1024,type:'application/pdf'};
test('LF-103 valid to invalid or canceled choice clears file and validates empty/format/size/policy',()=>{
 let selected=documentFileSelection(good,policy);assert.equal(selected.file,good);assert.equal(selected.error,null);
 for(const invalid of [{...good,size:0},{...good,size:policy.maxSizeBytes+1},{...good,name:'bad.exe'},{...good,name:'no-extension'}]){
  selected=documentFileSelection(invalid,policy);assert.equal(selected.file,null);assert.ok(selected.error);
 }
 assert.equal(documentFileSelection(good,undefined).file,null);
 assert.deepEqual(documentFileSelection(null,policy),{file:null,error:null});
 assert.equal(documentFileError({...good,size:policy.maxSizeBytes},policy),null);
});
test('LF-103 both adapter uploads reject empty and unsupported files without creating a new version',async()=>{
 await adapter.identity.login({email:'ha.nguyen@lumi.example',password:'ValidPassword123!'});
 await assert.rejects(()=>adapter.document.uploadDocument({...good,size:0,title:'Empty source'}));
 const doc=await adapter.document.uploadDocument({...good,title:'Version validation'});
 for(const bad of [{...good,size:0},{...good,name:'bad.exe'},{...good,size:60*1024*1024}])await assert.rejects(()=>adapter.document.uploadVersion(doc.id,bad));
 const data=await adapter.workspace.load('t.libraryDocument',{documentId:doc.id});if(data.kind!=='ready')throw Error('missing source');assert.equal(data.sourceDocumentDetail?.versions.length,1);
});
function v(num:number,status:DocumentVersion['status'],isServing=false):DocumentVersion{return {versionNumber:num,status,isServing,filename:`v${num}.pdf`,fileSizeFormatted:'1KB',uploadedAt:'2026-10-20'};}
test('LF-104 historical failure never becomes current failure after a higher READY version',()=>{
 const rows=[v(2,'FAILED'),v(9,'READY'),v(1,'READY',true),v(3,'FAILED')],copy=structuredClone(rows);
 const state=documentVersionState(rows);assert.equal(state.failed,null);assert.equal(state.serving?.versionNumber,9);assert.equal(state.latest?.versionNumber,9);assert.deepEqual(state.ordered.map(v=>v.versionNumber),[9,3,2,1]);assert.deepEqual(rows,copy);
});
test('LF-104 latest replacement failure keeps serving READY; retry is the exact numeric version',()=>{
 const state=documentVersionState([v(3,'FAILED'),v(1,'FAILED'),v(2,'READY',true)]);assert.equal(state.failed?.versionNumber,3);assert.equal(state.serving?.versionNumber,2);
 for(const status of ['PENDING','PROCESSING'] as const){const pending=documentVersionState([v(3,'FAILED'),v(2,'READY'),v(4,status)]);assert.equal(pending.failed,null);assert.equal(pending.latest?.status,status);assert.equal(pending.serving?.versionNumber,2);}
 const onlyFailed=documentVersionState([v(1,'FAILED')]);assert.equal(onlyFailed.serving,null);assert.equal(onlyFailed.failed?.versionNumber,1);
 assert.deepEqual(documentVersionState([]),{ordered:[],latest:null,serving:null,failed:null});
});
