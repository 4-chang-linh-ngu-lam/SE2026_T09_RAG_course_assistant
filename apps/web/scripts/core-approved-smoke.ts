import assert from 'node:assert/strict';
import {randomBytes,randomUUID} from 'node:crypto';
import {readFile,writeFile} from 'node:fs/promises';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {createLiveCoreApi} from '../src/lib/data/live-core';
import {createLiveClassroomSocial} from '../src/lib/data/live-classroom-social';
import {createLiveCoreAudit} from '../src/lib/data/live-core-audit';
import {createCoreAdminController} from '../src/lib/core-admin-controller';
import {createCoreManagementController,coreManagementRoutes} from '../src/lib/core-management-controller';
import {CoreManagementView} from '../src/features/administration/core-management-views';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {CoreStaffInviteView,CoreImportView,CoreDataRequestsView} from '../src/features/administration/core-admin-views';
import {getRoute} from '../src/config/routes';
import type {RouteParams} from '../src/lib/domain';
import {coreDecoders,type CoreApiPort,type CoreOperation,type CoreOptions} from '../src/lib/api/core-contract';
import {ApiError} from '../src/lib/api/errors';
if(process.env.CORE_SECURITY_TEST_MODE!=='synthetic')throw new Error('Dedicated synthetic fixture required');
function required(name:string){const value=process.env[name];if(!value)throw new Error('Missing synthetic fixture configuration');return value;}
const web=new URL(required('CORE_SECURITY_WEB_URL'));
if(web.protocol!=='http:'||!['localhost','127.0.0.1','[::1]'].includes(web.hostname)||web.username||web.password||web.pathname!=='/'||web.search||web.hash)throw new Error('Local fixture required');
const mailPath=required('CORE_SECURITY_MAIL_PATH'),reason='USER_REQUEST' as const;
const covered=new Set<CoreOperation>(),renderedViews=new Set<string>(),managementViews=new Set<string>();let phase='startup',passed=0;
const noRenderCommand=()=>{throw new Error('Rendering must not invoke a command');};
function pass(label:string){passed++;console.log('PASS '+label);}
function client(){
  let cookie='';
  const fetcher:typeof fetch=async(input,init={})=>{
    const path=String(input);assert.ok(path.startsWith('/api/v1/'));const headers=new Headers(init.headers);
    if((init.method??'GET')!=='GET')headers.set('Origin',web.origin);
    if(path.startsWith('/api/v1/auth/')&&cookie)headers.set('Cookie',cookie);
    const response=await fetch(web.origin+path,{...init,headers});
    for(const value of response.headers.getSetCookie())cookie=/Max-Age=0(?:;|$)/i.test(value)?'':value.split(';',1)[0];
    return response;
  };
  const session=createLiveCoreSession({fetcher,onLost(){}}),api=createLiveCoreApi(session);
  return {session,api,workspace:createLiveClassroomSocial(session,api)};
}
async function call<K extends CoreOperation>(api:CoreApiPort,id:K,options:CoreOptions<K>){phase='operation:'+id;const value=await api.request(id,options);covered.add(id);return value;}
const rejected=(status:number)=>(error:unknown)=>error instanceof ApiError&&error.status===status&&error.outcome==='rejected';
async function invitationLink(email:string){
  for(let attempt=0;attempt<40;attempt++){
    let raw='';try{raw=await readFile(mailPath,'utf8');}catch{}
    for(const line of raw.trim().split(/\r?\n/).filter(Boolean).reverse()){
      const message=JSON.parse(line);if(!message.recipients.includes(email))continue;
      const value=String(message.message).split(/\r?\n/).find(line=>line.startsWith(web.origin+'/staff/invitation#'));
      if(value){const link=new URL(value);assert.equal(link.origin,web.origin);assert.equal(link.pathname,'/staff/invitation');assert.equal(link.search,'');assert.ok(new URLSearchParams(link.hash.slice(1)).get('token'));return link;}
    }
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('Synthetic TLS email not received');
}
async function main(){try{
  phase='production Admin page availability';
  for(const routeId of ['a.staffInvite','a.importNew','a.dataRequests']){
    const page=await fetch(web.origin+getRoute(routeId).path,{signal:AbortSignal.timeout(15000),redirect:'manual'});assert.equal(page.status,200);
    await page.arrayBuffer();
  }
  const admin=client();const adminUser=await admin.session.identity.login({email:required('CORE_SECURITY_ADMIN_EMAIL'),password:required('CORE_SECURITY_ADMIN_PASSWORD')});
  const trackedAdmin:CoreApiPort={request:(id,options)=>call(admin.api,id,options)};
  const adminForms=createCoreAdminController(trackedAdmin,()=>admin.session.getActorId()===adminUser.id);
  phase='staff TLS invitation/status/roles';
  const suffix=randomUUID().replaceAll('-',''),email=`core.${suffix}@fixture.example.com`,password=randomBytes(32).toString('hex');
  await adminForms.invite({email,roles:['LECTURER'],reason});
  const staff=adminForms.getState().staff;assert.ok(staff);assert.equal(staff.status,'PENDING_VERIFICATION');
  const staffHtml=renderToStaticMarkup(React.createElement(CoreStaffInviteView,{state:adminForms.getState(),onSubmit:noRenderCommand}));assert.ok(staffHtml.includes(staff.id));assert.ok(staffHtml.includes(email));renderedViews.add('staff');
  const teacher=client();phase='staff invitation acceptance';const teacherLink=await invitationLink(email);await teacher.session.identity.acceptInvitation(new URLSearchParams(teacherLink.hash.slice(1)).get('token')!,password);
  await teacher.session.identity.login({email,password});
  await call(admin.api,'setUserStatus',{userId:staff.id,body:{status:'LOCKED'},reason});
  await assert.rejects(teacher.api.request('classes',{}),rejected(401));
  await call(admin.api,'setUserStatus',{userId:staff.id,body:{status:'ACTIVE'},reason});
  await call(admin.api,'setUserRoles',{userId:staff.id,body:{roles:['LECTURER']},reason});
  const teacherUser=await teacher.session.identity.login({email,password});assert.deepEqual(teacherUser.roles,['LECTURER']);
  pass('staff invitation delivered through verified synthetic TLS SMTP; lock revokes access and roles/status stay separate');

  phase='Classroom roster/enrollment/transfer/lifecycle';
  async function student(){
    const username='core.'+randomUUID().replaceAll('-',''),password=randomBytes(32).toString('hex');
    const issued=await admin.session.identity.createStudent(username,'Synthetic Core Student'),value=client();
    await value.session.identity.activate({username,activation_code:issued.code,new_password:password});
    const user=await value.session.identity.login({username,password});return {...value,user,credentials:{username,password}};
  }
  const studentA=await student(),studentB=await student();
  const course=await call(admin.api,'createCourse',{body:{code:'C'+suffix.slice(0,12),name:'Synthetic Course'}});
  const homeA=await call(admin.api,'createHomeroom',{body:{name:'A'+suffix,academic_year:'2026-2027',grade_level:9}});
  const homeB=await call(admin.api,'createHomeroom',{body:{name:'B'+suffix,academic_year:'2026-2027',grade_level:9}});
  const body={course_id:course.id,academic_year:'2026-2027',semester:'1',grade_level:9,enrollment_mode:'MANUAL' as const,primary_lecturer_id:staff.id};
  const klass=await call(admin.api,'createClass',{body:{...body,name:'A'+suffix,homeroom_class_id:homeA.id}});
  const other=await call(admin.api,'createClass',{body:{...body,name:'B'+suffix,homeroom_class_id:homeB.id}});
  const classId=klass.id;
  await call(admin.api,'setTeachers',{classId,body:{primary_lecturer_id:staff.id,assisting_lecturer_ids:[]},reason});
  const roster=await call(admin.api,'setRoster',{homeroomId:homeA.id,body:{student_ids:[studentA.user.id]},reason});assert.equal(roster.roster_version,homeA.roster_version+1);
  const preview=await call(admin.api,'previewEnrollment',{classId});assert.ok(preview.add_student_ids.includes(studentA.user.id));
  await call(admin.api,'setEnrollmentMode',{classId,body:{mode:'AUTO',expected_class_version:preview.class_version,expected_roster_version:preview.roster_version},reason});
  await call(admin.api,'syncEnrollment',{classId,reason});
  const transferred=await call(admin.api,'transferHomeroom',{homeroomId:homeA.id,studentId:studentA.user.id,body:{destination_homeroom_id:homeB.id},reason});assert.equal(transferred.homeroom_class_id,homeB.id);
  await assert.rejects(studentA.api.request('classDetail',{classId}),rejected(404));
  await call(admin.api,'setEnrollmentMode',{classId,body:{mode:'MANUAL'},reason});
  await call(admin.api,'addMember',{classId,body:{student_id:studentA.user.id},reason});
  await call(admin.api,'addMember',{classId,body:{student_id:studentB.user.id},reason});
  const member=await call(admin.api,'transferMember',{classId,studentId:studentB.user.id,body:{destination_class_id:other.id},reason});assert.equal(member.class_id,other.id);
  await call(admin.api,'endMember',{classId,studentId:studentA.user.id,reason});
  await call(admin.api,'addMember',{classId,body:{student_id:studentA.user.id},reason});
  assert.ok((await call(admin.api,'classes',{})).items.some(value=>value.id===classId));
  assert.equal((await call(admin.api,'classDetail',{classId})).id,classId);
  assert.deepEqual((await call(admin.api,'classMembers',{classId})).map(value=>value.student_id),[studentA.user.id]);
  await call(admin.api,'archiveClass',{classId,reason});
  await assert.rejects(studentA.api.request('createPost',{classId,body:{body:'denied while archived'}}),rejected(409));
  await call(admin.api,'restoreClass',{classId,reason});
  await assert.rejects(studentA.api.request('setRoster',{homeroomId:homeA.id,body:{student_ids:[]},reason}),rejected(403));
  pass('17 Classroom operations use real versions, roster, AUTO/MANUAL transitions, both transfers and archive/restore');

  phase='Social posts/comments/scopes';
  const post=await call(studentA.api,'createPost',{classId,body:{body:'Synthetic post'}});
  await call(studentA.api,'updatePost',{classId,postId:post.id,body:{body:'Synthetic updated post'}});
  assert.ok((await call(studentA.api,'posts',{classId})).items.some(value=>value.id===post.id));
  const comment=await call(teacher.api,'createComment',{classId,postId:post.id,body:{body:'Synthetic teacher comment'}});
  await call(teacher.api,'updateComment',{classId,postId:post.id,commentId:comment.id,body:{body:'Synthetic edited comment'}});
  assert.equal((await call(studentA.api,'comments',{classId,postId:post.id})).items[0].id,comment.id);
  await assert.rejects(studentA.api.request('updateComment',{classId,postId:post.id,commentId:comment.id,body:{body:'not author'}}),rejected(403));
  await assert.rejects(teacher.api.request('comments',{classId:other.id,postId:post.id}),rejected(404));
  await assert.rejects(admin.api.request('posts',{classId}),rejected(404));
  const feed=await studentA.workspace.load('s.feed',{classId});assert.equal(feed.kind,'ready');if(feed.kind==='ready'){assert.equal(feed.feedPosts?.[0].comments[0].id,comment.id);assert.equal(feed.feedPosts?.[0].authorRole,undefined);}
  const teacherFeed=await teacher.workspace.load('t.feed',{classId});assert.equal(teacherFeed.kind,'ready');if(teacherFeed.kind==='ready')assert.equal(teacherFeed.classSummary?.isAssignedTeacher,true);
  await call(teacher.api,'deleteComment',{classId,postId:post.id,commentId:comment.id});
  await call(studentA.api,'deletePost',{classId,postId:post.id});
  pass('8 Social operations, parent scope, author edit and separate moderation; live workspace does not invent author roles');

  phase='Calendar teacher/Student/origin';
  const event=await call(teacher.api,'createEvent',{classId,body:{title:'Synthetic event',description:'original',starts_at:'2026-10-22T12:00:00Z',ends_at:'2026-10-22T13:00:00Z'}});
  await call(teacher.api,'updateEvent',{classId,eventId:event.id,body:{title:'Synthetic edited',description:null}});
  const events=await call(studentA.api,'calendar',{classId,query:{from:'2026-10-22T00:00:00Z',to:'2026-10-23T00:00:00Z'}});assert.equal(events.items[0].description,null);
  await assert.rejects(studentA.api.request('createEvent',{classId,body:{title:'denied',starts_at:event.starts_at,ends_at:event.ends_at}}),rejected(403));
  const calendar=await teacher.workspace.load('t.calendar',{classId});assert.equal(calendar.kind,'ready');if(calendar.kind==='ready')assert.equal(calendar.calendarEvents?.[0].readOnly,false);
  const global=await studentA.workspace.load('account.calendar',{});assert.equal(global.kind,'ready');
  await call(teacher.api,'deleteEvent',{classId,eventId:event.id});
  pass('4 Calendar operations preserve timestamps, nullable description and teacher-only writes; class/global workspaces read live');

  phase='approved Admin read models and management screens';
  assert.ok((await call(admin.api,'courses',{limit:100})).items.some(value=>value.id===course.id));
  const years=await call(admin.api,'academicYears',{limit:100});const year=years.items.find(value=>value.id===klass.academic_year_id);assert.ok(year);assert.equal(year.label,'2026-2027');
  assert.ok((await call(admin.api,'semesters',{yearId:year.id,limit:100})).items.some(value=>value.id===klass.semester_id&&value.name==='1'));
  assert.ok((await call(admin.api,'homerooms',{limit:100})).items.some(value=>value.id===homeB.id));
  const currentRoster=await call(admin.api,'roster',{homeroomId:homeB.id});assert.ok(currentRoster.student_ids.includes(studentA.user.id));
  assert.ok((await call(admin.api,'teachingAssignments',{classId})).some(value=>value.lecturer_id===staff.id&&value.role==='PRIMARY'&&value.ended_at===null));
  const firstUsers=await call(admin.api,'adminUsers',{limit:1});assert.equal(firstUsers.items.length,1);assert.ok(firstUsers.next_cursor);
  assert.equal((await call(admin.api,'adminUser',{userId:staff.id})).roles[0],'LECTURER');
  await assert.rejects(studentA.api.request('adminUsers',{}),rejected(403));
  await assert.rejects(teacher.api.request('courses',{}),rejected(403));
  for(const routeId of coreManagementRoutes){
    const params:RouteParams=routeId==='a.account'?{userId:studentA.user.id}:routeId==='a.homeroom'?{homeroomId:homeB.id}:['a.classSettings','a.enrollment','a.lifecycle'].includes(routeId)?{classId}:{};
    const management=createCoreManagementController(trackedAdmin,{routeId,params,schoolId:adminUser.school_id!,isCurrentActor:()=>admin.session.getActorId()===adminUser.id,issueCode:admin.session.identity.issueCode});
    await management.load();assert.equal(management.getState().loaded,true);assert.equal(management.getState().issue,null);
    if(routeId==='a.enrollment'){
      await management.previewEnrollment();const actualPreview=management.getState().preview;assert.ok(actualPreview);
      await management.command('setEnrollmentMode',{classId,body:{mode:'AUTO',expected_class_version:actualPreview.class_version,expected_roster_version:actualPreview.roster_version},reason});
      assert.equal(management.getState().klass?.enrollment_mode,'AUTO');
      await management.command('setEnrollmentMode',{classId,body:{mode:'MANUAL'},reason});assert.equal(management.getState().klass?.enrollment_mode,'MANUAL');
    }
    const html=renderToStaticMarkup(React.createElement(CoreManagementView,{routeId,params,state:management.getState(),onReload:noRenderCommand,onAcknowledgeUnknown:noRenderCommand,onCommand:noRenderCommand,onPreview:noRenderCommand,onIssueCode:noRenderCommand,onClearCode:noRenderCommand}));
    assert.ok(html.length>200);managementViews.add(routeId);
    const path=getRoute(routeId).path.replace(/:(\w+)/g,(_,key:string)=>params[key as keyof typeof params]??'');
    const page=await fetch(web.origin+path,{signal:AbortSignal.timeout(15000),redirect:'manual'});assert.equal(page.status,200);await page.arrayBuffer();
    management.dispose();
  }
  pass('8 scoped Admin reads and 10 management routes render real HTTP state; AUTO preview/confirm reloads authoritative versions');

  phase='Admin audit and policy-pending requests';
  const request=await studentA.session.identity.createRequest('EXPORT','Synthetic request');
  await adminForms.loadRequests();assert.ok(adminForms.getState().requests.some(value=>value.id===request.id));
  await adminForms.selectRequest(request.id);assert.equal(adminForms.getState().selected?.user_id,studentA.user.id);
  await adminForms.resolve({status:'COMPLETED',identity_verified:true,resolution_note:'POLICY_PENDING',reason});
  const review=adminForms.getState().selected;assert.ok(review);
  assert.equal(review.status,'IN_REVIEW');assert.equal(review.resolution_note,'POLICY_PENDING');
  const requestHtml=renderToStaticMarkup(React.createElement(CoreDataRequestsView,{state:adminForms.getState(),onReload:noRenderCommand,onSelect:noRenderCommand,onResolve:noRenderCommand}));assert.ok(requestHtml.includes(request.id));assert.ok(requestHtml.includes('Đang xem xét'));renderedViews.add('requests');
  const audit=await call(admin.api,'auditEvents',{query:{actor_id:adminUser.id,action:'ADMIN_CREATE_CLASS'}});assert.ok(audit.items.length>0);
  const auditPage=await createLiveCoreAudit(admin.session,admin.api).load('a.audit',{});
  assert.equal(auditPage.kind,'audit');if(auditPage.kind==='audit')assert.ok(auditPage.items.some(value=>value.action==='ADMIN_CREATE_CLASS'&&value.actorName===adminUser.id));
  await assert.rejects(studentA.api.request('auditEvents',{}),rejected(403));
  pass('live Admin audit screen/filters and data-request review preserve actual IN_REVIEW/POLICY_PENDING');

  phase='CSV import preview/confirmation/replay';
  const csv=`username,display_name\nimport.${suffix},Synthetic Import\n`;
  await adminForms.previewFile(new File([csv],'students.csv',{type:'text/csv'}));
  const imported=adminForms.getState().preview;assert.ok(imported);assert.equal(imported.valid,true);assert.ok(imported.preview_id);
  await adminForms.confirmImport(reason);const receipt=adminForms.getState().receipt;assert.ok(receipt);assert.equal(receipt.replayed,false);assert.ok(receipt.items[0].code);
  const importActions={onPreview:noRenderCommand,onConfirm:noRenderCommand,onReconfirm:noRenderCommand,onClearCodes:noRenderCommand};
  const importHtml=renderToStaticMarkup(React.createElement(CoreImportView,{state:adminForms.getState(),...importActions}));assert.ok(importHtml.includes(receipt.items[0].code));renderedViews.add('import');
  const replay=await call(admin.api,'confirmImport',{body:{preview_id:imported.preview_id!},reason});assert.equal(replay.replayed,true);assert.equal(replay.items[0].code,null);
  const replayHtml=renderToStaticMarkup(React.createElement(CoreImportView,{state:{...adminForms.getState(),receipt:replay},...importActions}));assert.equal(replayHtml.includes(receipt.items[0].code),false);
  const invalid=await call(admin.api,'previewImport',{body:{format:'CSV',content_base64:Buffer.from('username,display_name\nbad@email,Invalid\n').toString('base64')}});assert.equal(invalid.valid,false);assert.ok(invalid.errors.length);
  pass('real CSV preview/row errors and durable import confirm; replay never discloses activation code again');
  assert.deepEqual([...covered].sort(),Object.keys(coreDecoders).sort());
  assert.equal(renderedViews.size,3);
  adminForms.dispose();assert.equal(adminForms.getState().receipt,null);
  if(process.env.CORE_BROWSER_FIXTURE_PATH){
    // The AUTO impact test deliberately ended this membership. Start the UI
    // journey with an explicit current MANUAL enrollment, not a guessed grant.
    const currentMembers=await call(admin.api,'classMembers',{classId});
    if(!currentMembers.some(member=>member.student_id===studentA.user.id&&member.status==='ACTIVE'))await call(admin.api,'addMember',{classId,body:{student_id:studentA.user.id},reason});
    const invitationEmail=`browser.invitation.${suffix}@fixture.example.com`,invitationPassword=randomBytes(32).toString('hex');
    await call(admin.api,'createStaff',{body:{email:invitationEmail,roles:['LECTURER']},reason});
    const invitationUrl=(await invitationLink(invitationEmail)).toString();
    await writeFile(process.env.CORE_BROWSER_FIXTURE_PATH,JSON.stringify({
      web:web.origin,classId,className:klass.name,studentId:studentA.user.id,
      student:studentA.credentials,teacher:{email,password},
      invitation:{url:invitationUrl,email:invitationEmail,password:invitationPassword},
    }),{mode:0o600});
  }
  await teacher.session.identity.logout();await studentA.session.identity.logout();await studentB.session.identity.logout();await admin.session.identity.logout();
  console.log(JSON.stringify({passed,coreOperations:covered.size,adminViewsRendered:renderedViews.size,managementViewsRendered:managementViews.size,fixture:'synthetic',authenticatedHttp:true,browserInteraction:false,syntheticTlsSmtp:true}));
}catch(error){
  console.error(JSON.stringify({phase,passed,code:error instanceof ApiError?error.code:'CHECK_FAILED',status:error instanceof ApiError?error.status:undefined}));process.exitCode=1;
}}
void main();
