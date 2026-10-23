import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {CoreManagementView,type CoreManagementViewProps} from '../src/features/administration/core-management-views';
import {createCoreManagementController} from '../src/lib/core-management-controller';
import {createLiveClassroomSocial} from '../src/lib/data/live-classroom-social';
import type {CoreApiPort,CoreAdminUser,CoreClass} from '../src/lib/api/core-contract';
const id='00000000-0000-4000-8000-000000000001',school='00000000-0000-4000-8000-000000000002',other='00000000-0000-4000-8000-000000000003';
const user:CoreAdminUser={id,email:null,username:'actual',school_id:school,display_name:null,status:'ACTIVE',roles:['STUDENT']};
const klass:CoreClass={id,school_id:school,academic_year_id:other,semester_id:other,course_id:other,homeroom_class_id:other,name:'Source',grade_level:9,enrollment_mode:'MANUAL',status:'ACTIVE',version:2};
const empty=createCoreManagementController({} as CoreApiPort,{routeId:'a.accounts',params:{},schoolId:school,isCurrentActor:()=>true}).getState();
const noCommand=()=>{throw new Error('Render must not mutate');};
function view(routeId:CoreManagementViewProps['routeId'],patch:Partial<typeof empty>={},params:CoreManagementViewProps['params']={classId:id,homeroomId:id}){
  return renderToStaticMarkup(React.createElement(CoreManagementView,{routeId,params,state:{...empty,loaded:true,klass,users:[user],...patch},onReload:noCommand,onAcknowledgeUnknown:noCommand,onCommand:noCommand,onPreview:noCommand,onIssueCode:noCommand,onClearCode:noCommand}));
}

test('homeroom route accepts uppercase UUIDs supported by the API',()=>{
  const homeId='abcdefab-cdef-4abc-8def-abcdefabcdef';
  const html=view('a.homeroom',{homerooms:[{id:homeId,school_id:school,academic_year_id:other,name:'Actual homeroom',grade_level:9,roster_version:4}],roster:{homeroom_class_id:homeId,student_ids:[],roster_version:4}},{homeroomId:homeId.toUpperCase()});
  assert.ok(html.includes('Actual homeroom'));
  assert.equal(html.includes('Không tìm thấy lớp hành chính với mã'),false);
});

test('enrollment without a linked homeroom explains and disables AUTO preview',()=>{
  const html=view('a.enrollment',{klass:{...klass,homeroom_class_id:null}});
  assert.ok(html.includes('Lớp chưa liên kết lớp hành chính'));
  assert.match(html,/disabled=""[^>]*>Xem trước tác động ghi danh/);
});
test('transfer UI offers only active MANUAL destinations in same course/year/semester',()=>{
  const html=view('a.enrollment',{classes:[{...klass,id:other,name:'Valid destination'},{...klass,id:school,name:'Wrong course',course_id:school},{...klass,id:school,name:'Wrong semester',semester_id:school},{...klass,id:school,name:'Auto destination',enrollment_mode:'AUTO'},{...klass,id:school,name:'Archived destination',status:'ARCHIVED'}]});
  assert.ok(html.includes('Valid destination'));
  for(const label of ['Wrong course','Wrong semester','Auto destination','Archived destination'])assert.equal(html.includes(label),false);
});
test('whole roster replacement keeps missing account identifiers visible and checked',()=>{
  const html=view('a.homeroom',{homerooms:[{id,school_id:school,academic_year_id:other,name:'Home',grade_level:9,roster_version:4}],roster:{homeroom_class_id:id,student_ids:[other],roster_version:4}});
  assert.ok(html.includes(`Giữ học sinh ${other}`));assert.ok(html.includes('checked=""'));assert.ok(html.includes('thay thế toàn bộ'));
});
test('current ineligible assignments stay visible and block save until explicitly replaced/removed',()=>{
  const locked:CoreAdminUser={...user,id:other,status:'LOCKED',roles:['LECTURER']};
  const html=view('a.classSettings',{users:[locked],teachers:[{id,lecturer_id:other,class_id:id,role:'PRIMARY',assigned_at:'2026-10-23T00:00:00Z',ended_at:null}]});
  assert.ok(html.includes('Cần thay giáo viên đủ điều kiện'));assert.match(html,/disabled=""[^>]*>Cập nhật phân công giáo viên/);
});
test('one-time code appears only in provided receipt and unknown actions require user reconciliation',()=>{
  const receipt={student:user,purpose:'PASSWORD_RESET' as const,code:'synthetic-only-code',expires_at:'2026-10-23T12:00:00Z'};
  const html=view('a.account',{account:user,issued:receipt});assert.ok(html.includes(receipt.code));assert.ok(html.includes('readOnly=""'));
  assert.equal(view('a.account',{account:user}).includes(receipt.code),false);
  const unknown=view('a.accounts',{unknown:true,reconciled:false});assert.ok(unknown.includes('Tải lại dữ liệu để đối chiếu'));assert.equal(unknown.includes('Tôi đã đối chiếu dữ liệu'),false);
  assert.ok(view('a.accounts',{unknown:true,reconciled:true}).includes('Tôi đã đối chiếu dữ liệu'));
});
test('live comment edit port forwards the exact parent/resource and maps actual response',async()=>{
  let captured:unknown;
  const api={request:async(operation:string,options:unknown)=>{captured={operation,options};return {id:school,post_id:other,author:{id,display_name:null},body:'Actual edit',created_at:'2026-10-23T00:00:00Z',updated_at:'2026-10-23T00:00:01Z'};}} as unknown as CoreApiPort;
  const port=createLiveClassroomSocial({} as Parameters<typeof createLiveClassroomSocial>[0],api);
  const edited=await port.social.updateComment(id,other,school,'Actual edit');
  assert.deepEqual(captured,{operation:'updateComment',options:{classId:id,postId:other,commentId:school,body:{body:'Actual edit'}}});assert.equal(edited.content,'Actual edit');assert.equal(edited.authorRole,undefined);
});
