import test from 'node:test';
import assert from 'node:assert/strict';
import {createCoreManagementController,type CoreManagementRoute} from '../src/lib/core-management-controller';
import {ApiError} from '../src/lib/api/errors';
import {coreDecoders,decodeAdminUser,type CoreApiPort} from '../src/lib/api/core-contract';
import {operationPath,queryKeys} from '../src/lib/api/operations';
import type {IssuedCode} from '../src/lib/domain';
const id='00000000-0000-4000-8000-000000000001',school='00000000-0000-4000-8000-000000000002',other='00000000-0000-4000-8000-000000000003';
const account={id,school_id:school,email:null,username:'student',display_name:null,status:'ACTIVE',roles:['STUDENT']};
const klass={id,school_id:school,academic_year_id:other,semester_id:other,course_id:other,homeroom_class_id:other,name:'Actual',grade_level:9,enrollment_mode:'MANUAL',status:'ACTIVE',version:4};
const preview={class_id:id,target_mode:'AUTO',class_version:4,roster_version:7,add_student_ids:[],end_student_ids:[]};
function harness(routeId:CoreManagementRoute='a.account',issueCode?:(id:string,verified:boolean)=>Promise<IssuedCode>){
  let actor=true,override:((operation:string,options:unknown)=>Promise<unknown>)|undefined;
  const calls:{operation:string;options:unknown}[]=[];
  const api={request:async(operation:string,options:unknown)=>{
    calls.push({operation,options});if(override)return override(operation,options);
    if(operation==='adminUser')return account;
    if(operation==='adminUsers')return {items:[account],next_cursor:null};
    if(operation==='classes')return {items:[klass],next_cursor:null};
    if(operation==='classDetail')return klass;
    if(operation==='classMembers'||operation==='teachingAssignments')return [];
    if(operation==='previewEnrollment')return preview;
    return {items:[],next_cursor:null};
  }} as unknown as CoreApiPort;
  const controller=createCoreManagementController(api,{routeId,params:{userId:id,classId:routeId==='a.enrollment'?id:''},schoolId:school,isCurrentActor:()=>actor,issueCode});
  return {controller,calls,actor:(value:boolean)=>{actor=value;},override:(value:typeof override)=>{override=value;}};
}
test('new reads accept only existing path/query contract and account decoder strips secrets without inventing roles',()=>{
  assert.equal(operationPath('semesters',{yearId:id}),`/admin/academic-years/${id}/semesters`);
  assert.throws(()=>operationPath('semesters',{yearId:'../users'}));
  assert.deepEqual(queryKeys('adminUsers'),['cursor','limit']);assert.deepEqual(queryKeys('roster'),[]);
  assert.deepEqual(decodeAdminUser({...account,roles:[],password_hash:'private',session_version:8}),{...account,roles:[]});
  assert.throws(()=>decodeAdminUser({...account,roles:['ADMIN','ADMIN']}));
  assert.throws(()=>decodeAdminUser({...account,roles:['OWNER']}));
  assert.throws(()=>coreDecoders.semesters({items:[{id,academic_year_id:other,name:'1'}],next_cursor:'bad'}));
});
test('account status and role writes are separate; each reloads authoritative reads and no revision is fabricated',async()=>{
  const h=harness();await h.controller.load();
  await h.controller.command('setUserStatus',{userId:id,body:{status:'LOCKED'},reason:'USER_REQUEST'});
  assert.deepEqual(h.calls.map(call=>call.operation),['adminUsers','adminUser','setUserStatus','adminUsers','adminUser']);
  assert.equal(h.controller.getState().account?.status,'ACTIVE'); // authoritative fixture, never optimistic LOCKED
  await h.controller.command('setUserRoles',{userId:id,body:{roles:['LECTURER']},reason:'ADMIN_INTERVENTION'});
  assert.equal(h.controller.getState().unknown,false);assert.equal('revision'in h.controller.getState(),false);
});

test('AUTO preview without a homeroom stays local and manual enrollment remains usable',async()=>{
  const h=harness('a.enrollment');
  h.override(async op=>{
    if(op==='classDetail')return {...klass,homeroom_class_id:null};
    if(op==='classMembers'||op==='teachingAssignments')return [];
    return {items:[],next_cursor:null};
  });
  await h.controller.load();await h.controller.previewEnrollment();
  assert.equal(h.calls.some(call=>call.operation==='previewEnrollment'),false);
  assert.match(h.controller.getState().issue?.message??'',/chưa liên kết lớp hành chính/);
  assert.equal(h.controller.getState().needsReload,false);
  assert.equal(h.controller.getState().unknown,false);
  await h.controller.command('addMember',{classId:id,body:{student_id:other},reason:'ADMIN_INTERVENTION'});
  assert.equal(h.calls.filter(call=>call.operation==='addMember').length,1);
});
test('unknown mutation blocks replay through refresh until explicit reviewed acknowledgement',async()=>{
  const h=harness();await h.controller.load();
  h.override(async op=>{if(op==='setUserStatus')throw new ApiError('CONNECTION_ERROR','Unknown',0,'unknown');return op==='adminUser'?account:{items:[account],next_cursor:null};});
  await h.controller.command('setUserStatus',{userId:id,body:{status:'LOCKED'},reason:'USER_REQUEST'});
  assert.equal(h.controller.getState().unknown,true);
  h.controller.acknowledgeUnknown();assert.equal(h.controller.getState().unknown,true);
  await h.controller.command('setUserStatus',{userId:id,body:{status:'LOCKED'},reason:'USER_REQUEST'});
  assert.equal(h.calls.filter(call=>call.operation==='setUserStatus').length,1);
  await h.controller.load();assert.equal(h.controller.getState().unknown,true);assert.equal(h.controller.getState().reconciled,true);
  h.controller.acknowledgeUnknown();assert.equal(h.controller.getState().unknown,false);
});
test('stale actor and disposal suppress response publication and further network activity',async()=>{
  const h=harness();let finish!:(value:unknown)=>void;
  const response=new Promise(resolve=>{finish=resolve;});h.override(()=>response);
  const pending=h.controller.load();h.actor(false);finish(account);await pending;
  assert.equal(h.controller.getState().loaded,false);const count=h.calls.length;
  await h.controller.load();assert.equal(h.calls.length,count);
  h.controller.dispose();assert.equal(h.controller.getState().account,null);
});
test('wrong school fails closed and changed resource cannot be mutated',async()=>{
  const h=harness();h.override(async op=>op==='adminUser'?{...account,school_id:other}:{items:[account],next_cursor:null});
  await h.controller.load();assert.equal(h.controller.getState().loaded,false);assert.equal(h.controller.getState().needsReload,true);
  h.override(undefined);await h.controller.load();
  await h.controller.command('setUserRoles',{userId:other,body:{roles:['ADMIN']},reason:'USER_REQUEST'});
  assert.equal(h.calls.some(call=>call.operation==='setUserRoles'),false);
});
test('confirmed write with failed reload retains receipt message and blocks subsequent writes until fresh read',async()=>{
  const h=harness();await h.controller.load();
  h.override(async op=>{if(op==='setUserStatus')return undefined;throw new ApiError('UNAVAILABLE','Down',503);});
  await h.controller.command('setUserStatus',{userId:id,body:{status:'LOCKED'},reason:'USER_REQUEST'});
  assert.equal(h.controller.getState().unknown,false);assert.equal(h.controller.getState().needsReload,true);assert.match(h.controller.getState().notice!,/đã xác nhận/);
  assert.equal(h.controller.getState().acknowledgement?.operation,'setUserStatus');
  await h.controller.command('setUserRoles',{userId:id,body:{roles:['ADMIN']},reason:'USER_REQUEST'});
  assert.equal(h.calls.some(call=>call.operation==='setUserRoles'),false);
});
test('AUTO requires exact server preview versions; refresh invalidates preview',async()=>{
  const h=harness('a.enrollment');await h.controller.load();
  await h.controller.command('setEnrollmentMode',{classId:id,body:{mode:'AUTO',expected_class_version:4,expected_roster_version:7},reason:'USER_REQUEST'});
  assert.equal(h.calls.some(call=>call.operation==='setEnrollmentMode'),false);
  await h.controller.load();await h.controller.previewEnrollment();assert.equal(h.controller.getState().preview?.roster_version,7);
  await h.controller.command('setEnrollmentMode',{classId:id,body:{mode:'AUTO',expected_class_version:4,expected_roster_version:8},reason:'USER_REQUEST'});
  assert.equal(h.calls.some(call=>call.operation==='setEnrollmentMode'),false);
  await h.controller.load();await h.controller.previewEnrollment();
  await h.controller.command('setEnrollmentMode',{classId:id,body:{mode:'AUTO',expected_class_version:4,expected_roster_version:7},reason:'USER_REQUEST'});
  assert.equal(h.calls.filter(call=>call.operation==='setEnrollmentMode').length,1);assert.equal(h.controller.getState().preview,null);
});
test('failed permissions clear selected account and rows',async()=>{
  const h=harness();await h.controller.load();h.override(async()=>{throw new ApiError('DENIED','Denied',403);});
  await h.controller.load();assert.equal(h.controller.getState().account,null);assert.deepEqual(h.controller.getState().users,[]);assert.equal(h.controller.getState().loaded,false);
});
test('late issued code after actor change is discarded and wrong student receipt stays hidden/unknown',async()=>{
  const receipt:IssuedCode={student:{id,email:null,username:'student',school_id:school,status:'ACTIVE'},purpose:'PASSWORD_RESET',code:'synthetic-only',expires_at:'2026-10-23T12:00:00Z'};
  let finish!:(value:IssuedCode)=>void;
  const h=harness('a.account',()=>new Promise(resolve=>{finish=resolve;}));await h.controller.load();
  const pending=h.controller.issueCode(true);h.actor(false);finish(receipt);await pending;assert.equal(h.controller.getState().issued,null);
  const bad=harness('a.account',async()=>({...receipt,student:{...receipt.student,id:other}}));await bad.controller.load();await bad.controller.issueCode(true);
  assert.equal(bad.controller.getState().issued,null);assert.equal(bad.controller.getState().unknown,true);
  const valid=harness('a.account',async()=>receipt);await valid.controller.load();await valid.controller.issueCode(false);assert.equal(valid.controller.getState().issued,null);
  await valid.controller.load();await valid.controller.issueCode(true);assert.equal(valid.controller.getState().issued?.code,receipt.code);
  valid.controller.clearCode();assert.equal(valid.controller.getState().issued,null);
});
test('catalog load never publishes partial pages or cross-year semester data',async()=>{
  const h=harness('a.catalog');h.override(async(op,options)=>{
    if(op==='academicYears')return {items:[{id:other,school_id:school,label:'2026'}],next_cursor:null};
    if(op==='semesters')return {items:[{id,academic_year_id:id,name:'Wrong year'}],next_cursor:null};
    if(op==='adminUsers'&&!(options as {cursor?:string}).cursor)return {items:[account],next_cursor:'AAAAAAAAAAAAAAAAAAAAAA'};
    if(op==='adminUsers')throw new ApiError('UNAVAILABLE','Page down',503);
    return {items:[],next_cursor:null};
  });
  await h.controller.load();assert.equal(h.controller.getState().loaded,false);assert.deepEqual(h.controller.getState().users,[]);
  h.override(async op=>op==='academicYears'?{items:[{id:other,school_id:school,label:'2026'}],next_cursor:null}:op==='semesters'?{items:[{id,academic_year_id:id,name:'Wrong year'}],next_cursor:null}:{items:[],next_cursor:null});
  await h.controller.load();assert.equal(h.controller.getState().loaded,false);assert.deepEqual(h.controller.getState().semesters,[]);
});
test('permission loss after confirmed write clears account while preserving confirmation and reload barrier',async()=>{
  const h=harness();await h.controller.load();h.override(async op=>{if(op==='setUserRoles')return account;throw new ApiError('UNAUTHENTICATED','Revoked',401);});
  await h.controller.command('setUserRoles',{userId:id,body:{roles:['ADMIN']},reason:'USER_REQUEST'});
  assert.equal(h.controller.getState().account,null);assert.deepEqual(h.controller.getState().users,[]);assert.equal(h.controller.getState().loaded,false);
  assert.equal(h.controller.getState().unknown,false);assert.equal(h.controller.getState().needsReload,true);assert.match(h.controller.getState().notice!,/đã xác nhận/);
  assert.equal(h.controller.getState().acknowledgement?.operation,'setUserRoles');
});

test('permission failure during reconciliation never erases an unknown mutation',async()=>{
  const h=harness();await h.controller.load();
  h.override(async()=>{throw new ApiError('CONNECTION_ERROR','Unknown',0,'unknown');});
  await h.controller.command('setUserStatus',{userId:id,body:{status:'LOCKED'},reason:'USER_REQUEST'});
  h.override(async()=>{throw new ApiError('DENIED','Denied',403);});await h.controller.load();
  assert.equal(h.controller.getState().unknown,true);assert.equal(h.controller.getState().reconciled,false);
  assert.equal(h.controller.getState().account,null);
  h.override(undefined);await h.controller.load();
  await h.controller.command('setUserStatus',{userId:id,body:{status:'LOCKED'},reason:'USER_REQUEST'});
  assert.equal(h.calls.filter(call=>call.operation==='setUserStatus').length,1);
  h.controller.acknowledgeUnknown();assert.equal(h.controller.getState().unknown,false);
});

test('definite validation rejection permits correction without requiring an unrelated reload',async()=>{
  const h=harness();await h.controller.load();
  h.override(async()=>{throw new ApiError('VALIDATION_ERROR','Invalid field',422);});
  await h.controller.command('setUserRoles',{userId:id,body:{roles:[]},reason:'USER_REQUEST'});
  assert.equal(h.controller.getState().needsReload,false);assert.equal(h.controller.getState().unknown,false);
  h.override(undefined);
  await h.controller.command('setUserRoles',{userId:id,body:{roles:['LECTURER']},reason:'USER_REQUEST'});
  assert.equal(h.calls.filter(call=>call.operation==='setUserRoles').length,2);
  assert.equal(h.controller.getState().issue,null);
});
