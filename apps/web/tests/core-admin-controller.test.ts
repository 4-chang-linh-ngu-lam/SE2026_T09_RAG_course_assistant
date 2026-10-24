import test from 'node:test';
import assert from 'node:assert/strict';
import type {CoreApiPort,CoreImportPreview,CoreImportReceipt} from '../src/lib/api/core-contract';
import {createCoreAdminController} from '../src/lib/core-admin-controller';
import {ApiError} from '../src/lib/api/errors';
const a='00000000-0000-4000-8000-000000000001',b='00000000-0000-4000-8000-000000000002';
const stamp='2026-10-22T12:00:00Z';
const preview:CoreImportPreview={valid:true,preview_id:a,expires_at:'2026-10-23T12:00:00Z',items:[{row:2,action:'CREATE',username:'synthetic',user_id:null}],errors:[]};
const receipt:CoreImportReceipt={preview_id:a,status:'COMPLETED',replayed:false,items:[{row:2,outcome:'CREATED',student:{id:b,school_id:a,email:null,username:'synthetic',display_name:null,status:'PENDING_VERIFICATION'},code:'synthetic-once',expires_at:stamp}]};
const request={id:a,user_id:b,type:'EXPORT' as const,reason:null,status:'PENDING' as const,resolution_note:null,created_at:stamp,updated_at:stamp};
function port(handle:(id:string,options:any)=>Promise<unknown>):CoreApiPort{return {request:handle} as unknown as CoreApiPort;}
function file(){const bytes=new TextEncoder().encode('username,display_name\nsynthetic,Học sinh\n');return {name:'students.csv',size:bytes.byteLength,arrayBuffer:async()=>bytes.buffer};}
const draft={email:' STAFF@Fixture.example.com ',roles:['LECTURER' as const],reason:'USER_REQUEST' as const};

test('staff form normalizes only wire fields and guards double submit before an actual acknowledgement',async()=>{
  let release!:()=>void,calls=0;const gate=new Promise<void>(resolve=>release=resolve);
  const controller=createCoreAdminController(port(async(id,options)=>{calls++;assert.equal(id,'createStaff');assert.deepEqual(options.body,{email:'staff@fixture.example.com',roles:['LECTURER']});assert.equal(options.reason,'USER_REQUEST');await gate;return receipt.items[0].student;}),()=>true);
  const first=controller.invite(draft);await controller.invite(draft);assert.equal(calls,1);assert.equal(controller.getState().staff,null);
  release();await first;assert.equal(controller.getState().staff?.id,b);assert.equal(controller.getState().busy,false);
});
test('unknown staff submission is never repeated or turned into fake invitation code/status',async()=>{
  let calls=0;const controller=createCoreAdminController(port(async()=>{calls++;throw new ApiError('UPSTREAM_UNAVAILABLE','offline',503,'unknown','synthetic-correlation');}),()=>true);
  await controller.invite(draft);await controller.invite(draft);
  assert.equal(calls,1);assert.equal(controller.getState().unknown,'staff');assert.equal(controller.getState().staff,null);assert.equal(controller.getState().issue?.correlationId,'synthetic-correlation');
});
test('import uploads original bytes, validates size/extension before network, and keeps actual row errors',async()=>{
  let calls=0;const source=file();
  const controller=createCoreAdminController(port(async(id,options)=>{calls++;assert.equal(id,'previewImport');assert.equal(options.body.format,'CSV');assert.deepEqual(Buffer.from(options.body.content_base64,'base64'),Buffer.from(await source.arrayBuffer()));return {...preview,valid:false,preview_id:null,expires_at:null,errors:[{row:2,code:'INVALID_USERNAME'}]};}),()=>true);
  await controller.previewFile({...source,name:'bad.txt'});await controller.previewFile({...source,size:2_000_001});assert.equal(calls,0);
  await controller.previewFile(source);assert.equal(calls,1);assert.equal(controller.getState().preview?.valid,false);assert.equal(controller.getState().preview?.errors[0].code,'INVALID_USERNAME');
  await controller.confirmImport('USER_REQUEST');assert.equal(calls,1);
});
test('confirmed import codes remain volatile until handoff; ordinary repeat cannot erase them with replay null',async()=>{
  let confirms=0;const controller=createCoreAdminController(port(async id=>id==='previewImport'?preview:(confirms++,receipt)),()=>true);
  await controller.previewFile(file());await controller.confirmImport('USER_REQUEST');await controller.confirmImport('USER_REQUEST');
  assert.equal(confirms,1);assert.equal(controller.getState().receipt?.items[0].code,'synthetic-once');
  controller.clearCodes();assert.equal(controller.getState().receipt,null);assert.equal(controller.getState().preview,null);
});
test('unknown import requires deliberate re-confirmation of same preview/reason; replay never fabricates a code',async()=>{
  let confirms=0;const controller=createCoreAdminController(port(async(id,options)=>{
    if(id==='previewImport')return preview;confirms++;assert.equal(options.body.preview_id,a);
    if(confirms===1)throw new ApiError('CONNECTION_ERROR','offline',0,'unknown');
    return {...receipt,replayed:true,items:receipt.items.map(row=>({...row,code:null,expires_at:null}))};
  }),()=>true);
  await controller.previewFile(file());await controller.confirmImport('USER_REQUEST');await controller.confirmImport('USER_REQUEST');assert.equal(confirms,1);
  await controller.confirmImport('POLICY_VIOLATION',true);assert.equal(confirms,1);assert.equal(controller.getState().unknown,'confirm');
  await controller.confirmImport('USER_REQUEST',true);assert.equal(confirms,2);assert.equal(controller.getState().unknown,null);assert.equal(controller.getState().receipt?.replayed,true);assert.equal(controller.getState().receipt?.items[0].code,null);
});
test('data-request review displays actual IN_REVIEW/POLICY_PENDING and does not invent completed processing',async()=>{
  let mutations=0;const controller=createCoreAdminController(port(async(id,options)=>{
    if(id==='adminDataRequests')return {items:[request],next_cursor:null};if(id==='adminDataRequest')return request;
    mutations++;assert.equal(options.body.status,'COMPLETED');return {...request,status:'IN_REVIEW',resolution_note:'POLICY_PENDING'};
  }),()=>true);
  await controller.loadRequests();await controller.selectRequest(a);
  await controller.resolve({status:'COMPLETED',resolution_note:'POLICY_PENDING',identity_verified:false,reason:'USER_REQUEST'});assert.equal(mutations,0);
  await controller.resolve({status:'COMPLETED',resolution_note:'POLICY_PENDING',identity_verified:true,reason:'USER_REQUEST'});assert.equal(mutations,1);
  assert.equal(controller.getState().selected?.status,'IN_REVIEW');assert.equal(controller.getState().requests[0].resolution_note,'POLICY_PENDING');assert.equal('revision'in controller.getState().selected!,false);
});
test('unknown review only permits fresh reads for explicit reconciliation, without replaying its mutation',async()=>{
  let mutations=0,reads=0;const controller=createCoreAdminController(port(async id=>{
    if(id==='adminDataRequests')return {items:[request],next_cursor:null};if(id==='adminDataRequest'){reads++;return mutations?{...request,status:'IN_REVIEW',resolution_note:'POLICY_PENDING'}:request;}
    mutations++;throw new ApiError('CONNECTION_ERROR','offline',0,'unknown');
  }),()=>true);
  const input={status:'COMPLETED' as const,resolution_note:'POLICY_PENDING' as const,identity_verified:true,reason:'USER_REQUEST' as const};
  await controller.loadRequests();await controller.selectRequest(a);await controller.resolve(input);await controller.resolve(input);
  assert.equal(mutations,1);assert.equal(controller.getState().unknown,'resolve');
  await controller.loadRequests();assert.equal(mutations,1);assert.equal(reads,2);assert.equal(controller.getState().unknown,null);assert.equal(controller.getState().selected?.status,'IN_REVIEW');
});
test('actor changes/disposal discard late receipts and clear sensitive codes rather than installing them for a new actor',async()=>{
  let current=true,release!:()=>void;const gate=new Promise<void>(resolve=>release=resolve);
  const controller=createCoreAdminController(port(async id=>{if(id==='previewImport')return preview;await gate;return receipt;}),()=>current);
  await controller.previewFile(file());const pending=controller.confirmImport('USER_REQUEST');current=false;controller.dispose();release();await pending;
  assert.equal(controller.getState().receipt,null);assert.equal(controller.getState().preview,null);assert.equal(controller.getState().busy,false);
});
test('failed request selection cannot leave a different requester actionable',async()=>{
  let mutations=0;const controller=createCoreAdminController(port(async(id,options)=>{
    if(id==='adminDataRequest'){if(options.requestId===a)return request;throw new ApiError('NOT_FOUND','not found',404);}
    mutations++;return request;
  }),()=>true);
  await controller.selectRequest(a);assert.equal(controller.getState().selected?.id,a);
  await controller.selectRequest(b);assert.equal(controller.getState().selected,null);
  await controller.resolve({status:'IN_REVIEW',resolution_note:'VERIFICATION_IN_PROGRESS',reason:'USER_REQUEST'});assert.equal(mutations,0);
});
test('a definite read permission denial clears previously authorized rows and selected details',async()=>{
  let denied=false;const controller=createCoreAdminController(port(async id=>{
    if(denied)throw new ApiError('FORBIDDEN','forbidden',403);
    return id==='adminDataRequests'?{items:[request],next_cursor:null}:request;
  }),()=>true);
  await controller.loadRequests();await controller.selectRequest(a);assert.equal(controller.getState().requests.length,1);
  denied=true;await controller.loadRequests();assert.deepEqual(controller.getState().requests,[]);assert.equal(controller.getState().selected,null);assert.equal(controller.getState().loaded,false);
});
