import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {operations,operationPath,isImplementedOperation,successStatus} from '../src/lib/api/operations';
import {createCoreProxy} from '../src/lib/api/proxy';
import {createHttpClient} from '../src/lib/api/http';
import {coreDecoders,decodeClass,decodePost,decodeEvent} from '../src/lib/api/core-contract';
import {createLiveCoreApi} from '../src/lib/data/live-core';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {allCorePages,coreClassSummary,corePost} from '../src/lib/data/live-classroom-social';
import {ApiError} from '../src/lib/api/errors';
import {createLiveCoreAudit,coreAuditRecord} from '../src/lib/data/live-core-audit';
import type {CoreApiPort,CoreAudit} from '../src/lib/api/core-contract';
const a='00000000-0000-4000-8000-000000000001',b='00000000-0000-4000-8000-000000000002',c='00000000-0000-4000-8000-000000000003';
const time='2026-10-22T12:00:00Z';
const row={id:a,school_id:b,academic_year_id:b,semester_id:b,course_id:b,homeroom_class_id:null,name:'Class',grade_level:9,enrollment_mode:'MANUAL',status:'ACTIVE',version:1};
const profile={id:c,email:null,username:'synthetic',school_id:b,display_name:null,status:'ACTIVE' as const,roles:['STUDENT' as const]};

test('approved 63 routes/statuses exactly cover implemented public OpenAPI, excluding register/health/internal',()=>{
  const schema=JSON.parse(readFileSync(new URL('./contracts/core-approved-openapi.json',import.meta.url),'utf8'));
  const paths=schema.paths??schema;const expected=new Set<string>();
  for(const [path,value]of Object.entries(paths))for(const method of Object.keys(value as object)){
    if(!['get','post','patch','put','delete'].includes(method)||!path.startsWith('/api/v1/')||path==='/api/v1/auth/register')continue;
    expected.add(method.toUpperCase()+' '+path.replaceAll(/\{[^}]+\}/g,':id').slice('/api/v1'.length));
  }
  const actual=new Set(Object.values(operations).map(([method,path])=>method+' '+path.replaceAll(/:\w+/g,':id')));
  assert.equal(actual.size,63);assert.equal(Object.keys(coreDecoders).length,46);assert.deepEqual(actual,expected);
  assert.equal(Object.keys(successStatus).length,63);
});
test('nested resource paths require every UUID and reject traversal, suffixes and unmatched methods',()=>{
  assert.equal(operationPath('deleteComment',{classId:a,postId:b,commentId:c}),`/classes/${a}/posts/${b}/comments/${c}`);
  for(const value of ['../auth/login',a+'/x',a+'?x=1','bad'])assert.throws(()=>operationPath('deleteComment',{classId:a,postId:b,commentId:value}));
  assert.throws(()=>operationPath('deleteComment',{classId:a,postId:b}));
  assert.equal(isImplementedOperation('DELETE',`/classes/${a}/posts/${b}/comments/${c}`),true);
  assert.equal(isImplementedOperation('PUT',`/classes/${a}/posts/${b}`),false);
  assert.equal(isImplementedOperation('GET',`/internal/v1/classes/${a}/access`),false);
});
test('proxy forwards only operation filters/reason enums and strips service/idempotency metadata',async()=>{
  let url='',headers=new Headers(),calls=0;
  const proxy=createCoreProxy(()=> 'http://core',(async(u,init)=>{url=String(u);headers=new Headers(init?.headers);calls++;return Response.json({});}) as typeof fetch);
  await proxy(new Request('http://local/api/v1/admin/audit-events?actor_id='+a+'&action=ADMIN_CREATE_CLASS&since='+encodeURIComponent(time)+'&user_id='+b),['admin','audit-events']);
  assert.equal(new URL(url).searchParams.get('actor_id'),a);assert.equal(new URL(url).searchParams.has('user_id'),false);
  await proxy(new Request(`http://local/api/v1/admin/classes/${a}/teaching-assignments`,{method:'PUT',headers:{Origin:'http://local','X-Admin-Reason':'USER_REQUEST','Idempotency-Key':b,'X-Service-Key':'spoof'},body:'{}'}),['admin','classes',a,'teaching-assignments']);
  assert.equal(headers.get('X-Admin-Reason'),'USER_REQUEST');assert.equal(headers.has('Idempotency-Key'),false);assert.equal(headers.has('X-Service-Key'),false);
  const before=calls;
  assert.equal((await proxy(new Request(`http://local/api/v1/admin/users/${a}/status`,{method:'PATCH',headers:{Origin:'http://local','X-Admin-Reason':'free text'}}),['admin','users',a,'status'])).status,400);
  assert.equal(calls,before);
});
test('HTTP client rejects unknown filters/invalid resources without network; read/write error semantics persist',async()=>{
  let calls=0;
  const client=createHttpClient(()=>null,(async()=>{calls++;return Response.json({error:{code:'DENIED',message:'Denied'}},{status:403});}) as typeof fetch);
  await assert.rejects(client('classes',{query:{user_id:a}}),e=>e instanceof ApiError&&e.status===422);
  await assert.rejects(client('createPost',{classId:'bad',body:{body:'x'}}),e=>e instanceof ApiError&&e.status===422);
  assert.equal(calls,0);
  await assert.rejects(client('createPost',{classId:a,body:{body:'x'}}),e=>e instanceof ApiError&&e.status===403&&e.outcome==='rejected');assert.equal(calls,1);
});
test('wire decoders reject invalid scope/date/cursor and do not fabricate role, email or class code',()=>{
  assert.equal(decodeClass(row).id,a);
  assert.throws(()=>decodeClass({...row,grade_level:5}));assert.throws(()=>decodeClass({...row,version:0}));
  const post=decodePost({id:a,class_id:b,author:{id:c,display_name:null,email:'must-not-escape'},body:'<b>text</b>',created_at:time,updated_at:time});
  const model=corePost(post);assert.equal(model.authorRole,undefined);assert.equal('email'in post.author,false);assert.equal(model.content,'<b>text</b>');
  const summary=coreClassSummary(decodeClass(row),profile,true);assert.equal(summary.code,'');assert.equal(summary.teachingRole,undefined);assert.equal(summary.membershipStatus,'ACTIVE');
  assert.throws(()=>coreDecoders.posts({items:[],next_cursor:'invalid'}));
  assert.throws(()=>decodeEvent({id:a,class_id:b,title:'x',description:null,starts_at:time,ends_at:time,origin:'CORE',external_ref:null}));
});
test('pagination aborts loops, duplicate rows and repeated cursors without returning partial success',async()=>{
  const signal=new AbortController().signal,cursor='AAAAAAAAAAAAAAAAAAAAAA';let count=0;
  await assert.rejects(allCorePages(async()=>({items:[{id:a}],next_cursor:cursor}),signal),e=>e instanceof ApiError&&e.code==='CONTRACT_MISMATCH');
  const aborted=new AbortController();aborted.abort();await assert.rejects(allCorePages(async()=>{count++;return {items:[],next_cursor:null};},aborted.signal));assert.equal(count,0);
});
test('receipt with wrong resource is unknown and never retried; unconfirmed actor cannot invoke Core',async()=>{
  let calls=0;
  const session=createLiveCoreSession({onLost(){},fetcher:(async(input)=>{
    const path=String(input);if(path.endsWith('/auth/login'))return Response.json({access_token:'synthetic',token_type:'bearer',expires_in:900});
    if(path.endsWith('/users/me'))return Response.json(profile);
    calls++;return Response.json({id:b,class_id:a,author:{id:c,display_name:null},body:'x',created_at:time,updated_at:time});
  }) as typeof fetch});
  const api=createLiveCoreApi(session);
  await assert.rejects(api.request('posts',{classId:a}),e=>e instanceof ApiError&&e.code==='SESSION_UNCONFIRMED');assert.equal(calls,0);
  await session.identity.login({username:'synthetic',password:'test-only-password'});
  await assert.rejects(api.request('updatePost',{classId:a,postId:c,body:{body:'x'}}),e=>e instanceof ApiError&&e.outcome==='unknown');assert.equal(calls,1);
});
test('Core audit uses actual actor IDs and safe reason codes, without fabricating staff names or exposing metadata',()=>{
  const row:CoreAudit={id:a,actor_id:b,action:'ADMIN_CREATE_CLASS',target_type:'class',target_id:c,correlation_id:a,metadata_json:{reason_code:'USER_REQUEST',arbitrary:'must not escape'},occurred_at:time};
  const mapped=coreAuditRecord(row);
  assert.equal(mapped.actorName,b);assert.equal(mapped.actorId,b);assert.equal(mapped.reason,'Theo yêu cầu người dùng');
  assert.equal('metadata_json'in mapped,false);assert.equal(JSON.stringify(mapped).includes('must not escape'),false);
  assert.equal(coreAuditRecord({...row,actor_id:null,metadata_json:{reason_code:'toString'}}).reason,'Chưa có lý do được công bố');
});
test('audit loader isolates Core reads, rejects stale actors and aborts instead of returning partial data',async()=>{
  let actor:string|null=a,calls=0;const controller=new AbortController();
  const api={request:async()=>{calls++;actor=b;return {items:[],next_cursor:null};}} as unknown as CoreApiPort;
  const port=createLiveCoreAudit({getActorId:()=>actor},api);
  await assert.rejects(port.load('a.reports',{}),e=>e instanceof ApiError&&e.code==='CAPABILITY_UNAVAILABLE');assert.equal(calls,0);
  await assert.rejects(port.load('a.audit',{}),e=>e instanceof ApiError&&e.code==='SESSION_CHANGED');assert.equal(calls,1);
  actor=null;await assert.rejects(port.load('a.audit',{}),e=>e instanceof ApiError&&e.code==='SESSION_UNCONFIRMED');assert.equal(calls,1);
  actor=a;controller.abort();await assert.rejects(port.load('a.audit',{},undefined,controller.signal));assert.equal(calls,1);
  const ready=createLiveCoreAudit({getActorId:()=>a},{request:async()=>({items:[],next_cursor:null})} as unknown as CoreApiPort);
  assert.deepEqual(await ready.load('a.audit',{}),{kind:'audit',items:[]});
});
test('membership receipts must match the student and transfer destination; UUID comparisons ignore case',async()=>{
  let value:unknown={id:a,class_id:b,student_id:c,source:'MANUAL',status:'ACTIVE',joined_at:time,ended_at:null};
  const session={getActorId:()=>a,authenticated:async(work:(request:()=>Promise<unknown>)=>Promise<unknown>)=>work(async()=>value)} as unknown as Parameters<typeof createLiveCoreApi>[0];
  const api=createLiveCoreApi(session);
  await assert.rejects(api.request('addMember',{classId:b,body:{student_id:a},reason:'USER_REQUEST'}),e=>e instanceof ApiError&&e.outcome==='unknown');
  await assert.rejects(api.request('transferMember',{classId:a,studentId:c,body:{destination_class_id:c},reason:'USER_REQUEST'}),e=>e instanceof ApiError&&e.outcome==='unknown');
  value={...row,id:'abcdef00-0000-4000-8000-000000000001'};
  assert.equal((await api.request('classDetail',{classId:'ABCDEF00-0000-4000-8000-000000000001'})).id,'abcdef00-0000-4000-8000-000000000001');
});
