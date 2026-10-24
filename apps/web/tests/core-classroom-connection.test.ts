import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createLiveClassroomSocial,allCorePages} from '../src/lib/data/live-classroom-social';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {createLiveCoreApi} from '../src/lib/data/live-core';
import {socialAccess} from '../src/lib/social-access';
import {canonicalParams,resourceParamsKey} from '../src/lib/route-load-plan';
import {getRoute} from '../src/config/routes';
import {ClassOverviewFeature} from '../src/features/classroom/class-overview';
import {TeacherOverviewFeature} from '../src/features/classroom/teacher-overview';
import {StudentClassesFeature} from '../src/features/classroom/student-classes';
import {TeacherClassesFeature} from '../src/features/classroom/teacher-classes';
import {ApiError} from '../src/lib/api/errors';

// tsx preserves the repository's classic JSX runtime for the standalone render harness.
(globalThis as typeof globalThis&{React:typeof React}).React=React;

const id='abcdefab-1234-4000-8000-123456abcdef',school='00000000-0000-4000-8000-000000000001',userId='00000000-0000-4000-8000-000000000002';
const klass={id,school_id:school,academic_year_id:school,semester_id:school,course_id:school,homeroom_class_id:null,name:'Actual Core Class',grade_level:9,enrollment_mode:'MANUAL',status:'ACTIVE',version:1};
async function connected(role:'STUDENT'|'LECTURER'='STUDENT'){
  const calls:string[]=[];
  const session=createLiveCoreSession({onLost(){},fetcher:async(input)=>{
    const path=String(input);calls.push(path);
    if(path.endsWith('/login'))return Response.json({access_token:'synthetic',token_type:'bearer',expires_in:900});
    if(path.endsWith('/users/me'))return Response.json({id:userId,email:null,username:'synthetic',display_name:null,school_id:school,status:'ACTIVE',roles:[role]});
    if(path.includes('/classes?'))return Response.json({items:[klass],next_cursor:null});
    if(path.endsWith('/classes/'+id))return Response.json(klass);
    throw new Error('Unexpected operation');
  }});
  await session.identity.login({username:'synthetic',password:'synthetic-only'});
  return {workspace:createLiveClassroomSocial(session,createLiveCoreApi(session)),calls};
}

test('Core home and overview read real scoped classes without inventing other-service summaries',async()=>{
  for(const role of ['STUDENT','LECTURER'] as const){
    const h=await connected(role),prefix=role==='STUDENT'?'s':'t';
    assert.equal(h.workspace.supports(prefix+'.home'),true);
    const home=await h.workspace.load(prefix+'.home',{});
    assert.equal(home.kind,'ready');if(home.kind!=='ready')throw new Error('Expected data');
    assert.equal(home.classes?.[0].id,id);assert.equal(home.coreClassroom,true);
    assert.equal(home.studentHome,undefined);assert.equal(home.teacherHome,undefined);
    const overview=await h.workspace.load(prefix+'.overview',{classId:id.toUpperCase()});
    assert.equal(overview.kind,'ready');if(overview.kind!=='ready')throw new Error('Expected data');
    assert.equal(overview.classSummary?.id,id);assert.equal(overview.classOverview,undefined);
    assert.equal(socialAccess({roles:[role],status:'ACTIVE'},overview.classSummary,id.toUpperCase()).participate,true);
    const html=renderToStaticMarkup(React.createElement(role==='STUDENT'?ClassOverviewFeature:TeacherOverviewFeature,{route:getRoute(prefix+'.overview'),data:overview,reload(){}}));
    assert.ok(html.includes('Actual Core Class'));assert.ok(html.includes('/'+(role==='STUDENT'?'student':'teacher')+'/classes/'+id+'/feed'));
    assert.ok(html.includes('đang chờ kết nối'));assert.equal(html.includes('Chưa có tài liệu nào được đăng tải'),false);
    assert.equal(h.calls.some(path=>path.includes('/posts')||path.includes('/admin/')),false);
  }
});

test('live archived class cards open available Core overview instead of uncontracted personal history/grading',async()=>{
  const h=await connected('LECTURER'),data=await h.workspace.load('t.classes',{});
  if(data.kind!=='ready'||!data.classes)throw new Error('Expected classes');
  const archived={...data,classes:data.classes.map(row=>({...row,status:'ARCHIVED' as const}))};
  const html=renderToStaticMarkup(React.createElement(TeacherClassesFeature,{route:getRoute('t.classes'),data:archived,reload(){}}));
  assert.ok(html.includes(`/teacher/classes/${id}/overview`));assert.equal(html.includes('Xem bài đã nộp'),false);
  // Student's archive tab is interactive; the initial active tab correctly hides archived rows.
  const studentHtml=renderToStaticMarkup(React.createElement(StudentClassesFeature,{route:getRoute('s.classes'),data,reload(){}}));
  assert.ok(studentHtml.includes(`/student/classes/${id}/overview`));
});

test('resource keys canonicalize UUID case while preserving opaque query/filter values and preview IDs',()=>{
  assert.equal(resourceParamsKey('s.feed',{classId:id}),resourceParamsKey('s.feed',{classId:id.toUpperCase()}));
  assert.deepEqual(JSON.parse(canonicalParams({classId:id.toUpperCase(),cursor:'ABc',filter:id.toUpperCase(),postId:'Preview-A'})),{classId:id,cursor:'ABc',filter:id.toUpperCase(),postId:'Preview-A'});
  assert.equal(socialAccess({roles:['STUDENT'],status:'ACTIVE'},{id:'preview-A',code:'',name:'',metadata:'',status:'ACTIVE',membershipStatus:'ACTIVE'},'preview-a').participate,false);
});

test('pagination rejects repeated UUIDs even when the next page changes their letter case',async()=>{
  let page=0;
  await assert.rejects(allCorePages(async()=>++page===1?{items:[{id}],next_cursor:'AAAAAAAAAAAAAAAAAAAAAA'}:{items:[{id:id.toUpperCase()}],next_cursor:null},new AbortController().signal),error=>error instanceof ApiError&&error.code==='CONTRACT_MISMATCH');
});

test('deleted post during comment fan-out is skipped only after rechecking current class content access',async()=>{
  for(const revoked of [false,true]){
    let postReads=0;
    const second='abcdefab-1234-4000-8000-123456abcdea';
    const session=createLiveCoreSession({onLost(){},fetcher:async(input)=>{
      const url=new URL(String(input),'http://local'),path=url.pathname;
      if(path.endsWith('/login'))return Response.json({access_token:'synthetic',token_type:'bearer',expires_in:900});
      if(path.endsWith('/users/me'))return Response.json({id:userId,email:null,username:'synthetic',display_name:null,school_id:school,status:'ACTIVE',roles:['STUDENT']});
      if(path.endsWith('/classes/'+id))return Response.json(klass);
      if(path.endsWith('/posts')){
        if(++postReads>1){assert.equal(url.searchParams.get('limit'),'1');return revoked?Response.json({error:{code:'NOT_FOUND',message:'Not found'}},{status:404}):Response.json({items:[],next_cursor:null});}
        const items=[id,second].map(postId=>({id:postId,class_id:id,author:{id:userId,display_name:null},body:'Synthetic post',created_at:'2026-10-23T00:00:00Z',updated_at:'2026-10-23T00:00:00Z'}));
        return Response.json({items,next_cursor:null});
      }
      if(path.endsWith('/posts/'+id+'/comments'))return Response.json({error:{code:'NOT_FOUND',message:'Not found'}},{status:404});
      if(path.endsWith('/posts/'+second+'/comments'))return Response.json({items:[],next_cursor:null});
      throw new Error('Unexpected operation');
    }});
    await session.identity.login({username:'synthetic',password:'synthetic-only'});
    const workspace=createLiveClassroomSocial(session,createLiveCoreApi(session));
    if(revoked)await assert.rejects(workspace.load('s.feed',{classId:id}),error=>error instanceof ApiError&&error.status===404);
    else {const data=await workspace.load('s.feed',{classId:id});assert.equal(data.kind,'ready');if(data.kind==='ready'){assert.deepEqual(data.feedPosts?.map(post=>post.id),[second]);assert.match(data.feedPosts![0].authorName,/^Thành viên /);}}
    assert.equal(postReads,2);
  }
});
