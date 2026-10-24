import test from 'node:test';
import assert from 'node:assert/strict';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {createLiveNotifications} from '../src/lib/data/live-notifications';
import {decodeNotificationPage,decodeNotificationRead} from '../src/lib/api/notification-decoders';
import {createCoreProxy} from '../src/lib/api/proxy';
import {isImplementedOperation} from '../src/lib/api/operations';
import {ApiError} from '../src/lib/api/errors';

const actor='00000000-0000-4000-8000-000000000001', one='00000000-0000-4000-8000-000000000011',two='00000000-0000-4000-8000-000000000012';
const cursor='AAAAAAAAQACAAAAAAAAAEQ';
const row=(id=one,read=false,type='SOCIAL_POST_CREATED')=>({id,read,type,created_at:'2026-10-22T00:00:00+00:00',payload_json:{class_id:one,targetHref:'https://untrusted.example',title:'<script>untrusted</script>',user_id:two}});
const page=(items:unknown[]=[row()],unread_count=1,next_cursor:string|null=null)=>({items,unread_count,next_cursor});
function harness(run:(path:string,init:RequestInit)=>Response|Promise<Response>) {
  const calls:string[]=[];
  const session=createLiveCoreSession({onLost(){},fetcher:(async(input,init={})=>{
    const path=String(input);calls.push(path);
    if(path.endsWith('/auth/login')||path.endsWith('/auth/refresh'))return Response.json({access_token:'synthetic',token_type:'bearer',expires_in:600});
    if(path.endsWith('/users/me'))return Response.json({id:actor,email:null,username:'synthetic',school_id:actor,display_name:null,roles:['STUDENT'],status:'ACTIVE'});
    if(path.endsWith('/auth/logout'))return new Response(null,{status:204});
    return run(path,init);
  }) as typeof fetch});
  return {session,notifications:createLiveNotifications(session),calls,login:()=>session.identity.login({username:'synthetic',password:'synthetic'})};
}
test('notification wire decoder supplies only safe presentation and current actor ownership',()=>{
  for(const type of ['SOCIAL_POST_CREATED','unrecognized','__proto__']){
    const result=decodeNotificationPage(page([row(one,false,type)]),actor);
    assert.equal(result.items[0].userId,actor);assert.equal(result.items[0].targetHref,undefined);assert.equal(result.items[0].classId,undefined);
    assert.ok(!JSON.stringify(result).includes('untrusted'));assert.equal(result.items[0].category,type==='SOCIAL_POST_CREATED'?'CLASS':'SYSTEM');
  }
});
test('notification wire decoder rejects malformed fields, cursor and duplicate IDs',()=>{
  for(const value of [page([row()],-1),page([row()],1.5),page([row()],1,'bad'),page([{...row(),read:'false'}]),page([{...row(),payload_json:[]}]),page([{...row(),created_at:'invalid'}]),page([{...row(),id:'bad'}]),page([row(),row()])])assert.throws(()=>decodeNotificationPage(value,actor),ApiError);
});

test('notification acknowledgements use UUID identity across letter case; duplicate variants are rejected',()=>{
  const lettered='abcdefab-cdef-4abc-8def-abcdefabcdef';
  assert.doesNotThrow(()=>decodeNotificationRead({id:lettered,read:true},lettered.toUpperCase()));
  assert.equal(decodeNotificationPage(page([row(lettered.toUpperCase())]),actor).items[0].id,lettered);
  assert.throws(()=>decodeNotificationPage(page([row(lettered),row(lettered.toUpperCase())]),actor),ApiError);
});
test('live inbox traverses cursor pages and retains the server global unread count',async()=>{
  const h=harness((path,init)=>{
    assert.equal(new Headers(init.headers).get('Authorization'),'Bearer synthetic');
    const query=new URL(path,'http://local').searchParams;assert.equal(query.get('limit'),'100');
    return Response.json(query.has('cursor')?page([row(two)],7):page([row()],8,cursor));
  });
  await h.login();const result=await h.notifications.load();assert.equal(result.kind,'ready');
  if(result.kind==='ready'){assert.equal(result.notifications?.length,2);assert.equal(result.notificationUnreadCount,7);}
  assert.equal(h.calls.filter(path=>path.includes('/notifications')).length,2);
  assert.ok(h.calls.at(-1)?.includes('cursor='+cursor));
});
test('live inbox fails closed on repeated cursors or duplicate cross-page rows',async()=>{
  for(const duplicate of [true,false]){
    let reads=0;const h=harness(()=>Response.json(page([row(reads++===0||duplicate?one:two)],2,cursor)));
    await h.login();await assert.rejects(h.notifications.load(),(e:unknown)=>e instanceof ApiError&&e.code==='CONTRACT_MISMATCH');
    assert.equal(reads,2);
  }
});
test('mark-one/all use exact contracted verbs and reject an acknowledgement for another row',async()=>{
  const writes:string[]=[];
  const h=harness((path,init)=>{
    writes.push(init.method+' '+path);assert.equal(init.body,undefined);
    if(path.endsWith('/read-all'))return new Response(null,{status:204});
    return Response.json({id:two,read:true});
  });
  await h.login();await assert.rejects(h.notifications.port.markAsRead(one),(e:unknown)=>e instanceof ApiError&&e.outcome==='unknown');
  await h.notifications.port.markAllAsRead();
  assert.deepEqual(writes,['PATCH /api/v1/notifications/'+one+'/read','POST /api/v1/notifications/read-all']);
});
test('401 clears the shared Identity session; rejected and unknown writes are not replayed',async()=>{
  for(const status of [401,404,503]){
    let writes=0;const h=harness(()=>{writes++;return Response.json({error:{code:'FAILED',message:'Synthetic failure'}},{status});});
    await h.login();await assert.rejects(h.notifications.port.markAsRead(one),(e:unknown)=>e instanceof ApiError&&e.status===status&&e.outcome===(status>=500?'unknown':'rejected'));
    assert.equal(writes,1);assert.equal(h.session.getActorId(),status===401?null:actor);
    if(status===401)assert.equal(await h.session.identity.restore(),null);
  }
});
test('aborting an inbox load does not publish partial rows or sign out the actor',async()=>{
  const h=harness((_path,init)=>new Promise<Response>((_resolve,reject)=>init.signal?.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true})));
  await h.login();const controller=new AbortController();const load=h.notifications.load(controller.signal);controller.abort();
  await assert.rejects(load,(e:unknown)=>e instanceof ApiError&&e.outcome==='rejected');assert.equal(h.session.getActorId(),actor);
});
test('late inbox data from a prior session is discarded after logout',async()=>{
  let resolve!:(response:Response)=>void;const gate=new Promise<Response>(done=>{resolve=done;});
  const h=harness(()=>gate);await h.login();const load=h.notifications.load();await h.session.identity.logout();
  resolve(Response.json(page()));await assert.rejects(load,(e:unknown)=>e instanceof ApiError&&e.code==='SESSION_CHANGED');
});
test('only approved notification routes and pagination enter the proxy',async()=>{
  assert.equal(isImplementedOperation('GET','/notifications'),true);assert.equal(isImplementedOperation('PATCH','/notifications/'+one+'/read'),true);
  for(const [method,path]of [['DELETE','/notifications/'+one],['PATCH','/notifications/bad/read'],['GET','/notifications/'+one],['GET','/documents'],['GET','/internal/v1/classes/'+one+'/access']])assert.equal(isImplementedOperation(method,path),false);
  const proxy=createCoreProxy(()=> 'http://core:8000',(async(url,init)=>{
    const target=new URL(String(url));assert.equal(target.searchParams.get('cursor'),cursor);assert.equal(target.searchParams.get('limit'),'100');assert.equal(target.searchParams.has('user_id'),false);assert.equal(new Headers(init?.headers).has('X-Service-Key'),false);return Response.json(page());
  }) as typeof fetch);
  assert.equal((await proxy(new Request('http://local/api/v1/notifications?cursor='+cursor+'&limit=100&user_id='+two),['notifications'])).status,200);
});
