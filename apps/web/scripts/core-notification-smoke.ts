import assert from 'node:assert/strict';
import {randomBytes,randomUUID} from 'node:crypto';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {createLiveNotifications} from '../src/lib/data/live-notifications';
import {createNotificationReadController,type NotificationReadController,type NotificationSnapshotRequest} from '../src/lib/notification-read-controller';
import {ApiError} from '../src/lib/api/errors';
import type {WorkspaceData} from '../src/lib/domain';

// Run only against a freshly seeded, disposable local fixture. This provisions
// synthetic accounts, enrolls them and creates posts to exercise the real worker.
if(process.env.CORE_SECURITY_TEST_MODE!=='synthetic')throw new Error('Dedicated synthetic fixture required');
function required(name:string):string {const value=process.env[name];if(!value)throw new Error('Synthetic fixture configuration required');return value;}
function local(name:string) {const url=new URL(required(name));if(url.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(url.hostname)||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw new Error('Local fixture origin required');return url.origin;}
const web=local('CORE_SECURITY_WEB_URL'),core=local('CORE_SECURITY_API_URL');
const email=required('CORE_SECURITY_ADMIN_EMAIL'),password=required('CORE_SECURITY_ADMIN_PASSWORD');
type Jar={cookie:string};
class Transport {
  paths:string[]=[];bearer:string|null=null;dropRead=false;dropAll=false;
  constructor(private jar:Jar={cookie:''}){}
  fetch:typeof fetch=async(input,init={})=>{
    const path=String(input);assert.ok(path.startsWith('/api/v1/'));
    const headers=new Headers(init.headers),method=init.method??'GET';
    if(headers.has('Authorization'))this.bearer=headers.get('Authorization');
    if(method!=='GET')headers.set('Origin',web);
    if(path.startsWith('/api/v1/auth/')&&this.jar.cookie)headers.set('Cookie',this.jar.cookie);
    this.paths.push(method+' '+path);
    const response=await fetch(web+path,{...init,headers});
    for(const value of response.headers.getSetCookie()) {
      assert.match(value,/HttpOnly/i);assert.match(value,/Path=\/api\/v1\/auth/i);assert.match(value,/SameSite=lax/i);
      const pair=value.split(';',1)[0];this.jar.cookie=/Max-Age=0(?:;|$)/i.test(value)?'':pair;
    }
    if(response.ok&&((this.dropRead&&path.endsWith('/read'))||(this.dropAll&&path.endsWith('/read-all')))){
      this.dropRead=false;this.dropAll=false;await response.body?.cancel();throw new TypeError('Synthetic lost mutation response');
    }
    return response;
  };
}
const make=(transport:Transport,now?:()=>number)=>{const session=createLiveCoreSession({fetcher:transport.fetch,onLost(){},now});return {session,inbox:createLiveNotifications(session)};};
async function direct(path:string,transport:Transport,body?:unknown) {
  const headers=new Headers({'X-Admin-Reason':'USER_REQUEST'});if(transport.bearer)headers.set('Authorization',transport.bearer);
  if(body!==undefined)headers.set('Content-Type','application/json');
  return fetch(core+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
}
function ready(value:WorkspaceData) {assert.equal(value.kind,'ready');if(value.kind!=='ready')throw new Error('Inbox unavailable');return value;}
async function waitInbox(inbox:ReturnType<typeof createLiveNotifications>,minimum:number) {
  for(let index=0;index<60;index++) {const value=ready(await inbox.load());if((value.notificationUnreadCount??0)>=minimum)return value;await new Promise(done=>setTimeout(done,500));}
  throw new Error('Worker delivery timed out');
}
let phase='startup';const checks:string[]=[];const pass=(label:string)=>{checks.push(label);console.log('PASS '+label);};
async function main() {try {
  phase='provision';const adminTransport=new Transport(),admin=make(adminTransport);
  await admin.session.identity.login({email,password});
  async function student() {
    const username='notification.smoke.'+randomUUID().replaceAll('-',''),studentPassword=randomBytes(32).toString('hex');
    const code=await admin.session.identity.createStudent(username,'Synthetic Notification Student');
    const transport=new Transport(),client=make(transport);
    await client.session.identity.activate({username,activation_code:code.code,new_password:studentPassword});
    const actor=await client.session.identity.login({username,password:studentPassword});
    return {...client,transport,actor,credentials:{username,password:studentPassword}};
  }
  const a=await student(),b=await student();
  const classes=await direct('/api/v1/classes',adminTransport);assert.equal(classes.status,200);
  const list=await classes.json() as {items:{id:string;enrollment_mode:string;status:string}[]};
  const klass=list.items.find(item=>item.enrollment_mode==='MANUAL'&&item.status==='ACTIVE');assert.ok(klass);
  for(const actor of [a.actor,b.actor])assert.equal((await direct('/api/v1/admin/classes/'+klass.id+'/members',adminTransport,{student_id:actor.id})).status,201);
  await waitInbox(b.inbox,1);await a.inbox.port.markAllAsRead();await b.inbox.port.markAllAsRead();
  pass('synthetic enrollment produces recipient-scoped inbox entries through the actual worker');

  phase='worker pagination';
  for(let index=0;index<101;index++)assert.equal((await direct('/api/v1/classes/'+klass.id+'/posts',a.transport,{body:'Synthetic notification integration '+index})).status,201);
  const first=await waitInbox(b.inbox,101);assert.equal(first.notificationUnreadCount,101);assert.ok(first.notifications!.length>=101);
  assert.ok(b.transport.paths.some(path=>path.includes('/notifications?cursor=')));
  assert.ok(first.notifications!.every(item=>item.userId===b.actor.id&&!item.targetHref));
  pass('101 worker deliveries cross a real cursor boundary; server unread count and safe presentation are preserved');

  phase='recipient ownership';const firstId=first.notifications![0].id;
  await assert.rejects(a.inbox.port.markAsRead(firstId),(error:unknown)=>error instanceof ApiError&&error.status===404);
  await b.inbox.port.markAsRead(firstId);
  const afterOne=ready(await b.inbox.load());assert.equal(afterOne.notificationUnreadCount,100);assert.equal(afterOne.notifications!.find(item=>item.id===firstId)?.isRead,true);
  pass('foreign recipient cannot acknowledge an ID; owner acknowledgement matches the actual persisted row');

  phase='unknown one reconciliation';let controller:NotificationReadController;let reconciliation=Promise.resolve();
  const receive=(ticket:NotificationSnapshotRequest)=>{reconciliation=b.inbox.load().then(value=>{const snapshot=ready(value);controller.receiveSnapshot(snapshot.notifications??[],ticket,snapshot.notificationUnreadCount);});return reconciliation;};
  controller=createNotificationReadController({actorId:b.actor.id,markOne:id=>b.inbox.port.markAsRead(id),markAll:()=>b.inbox.port.markAllAsRead(),reload:receive});
  controller.receiveSnapshot(afterOne.notifications??[],undefined,afterOne.notificationUnreadCount);
  const secondId=afterOne.notifications!.find(item=>!item.isRead)!.id;
  b.transport.dropRead=true;assert.equal(await controller.markOne(secondId),'unknown');assert.equal(controller.getState().items.find(item=>item.id===secondId)?.isRead,false);
  assert.equal(await controller.retry(),'ignored');controller.reconcile();await reconciliation;
  assert.equal(controller.getState().issue,null);assert.equal(controller.getState().unreadCount,99);
  assert.equal(b.transport.paths.filter(path=>path==='PATCH /api/v1/notifications/'+secondId+'/read').length,1);
  pass('lost mark-one response is reconciled by a fresh GET, with no replay or optimistic read receipt');

  phase='unknown all reconciliation';
  assert.equal((await direct('/api/v1/classes/'+klass.id+'/posts',b.transport,{body:'Synthetic other recipient delivery'})).status,201);
  const aUnread=(await waitInbox(a.inbox,1)).notificationUnreadCount;
  controller.receiveSnapshot([],undefined,99); // Global unread count may include rows not currently rendered.
  b.transport.dropAll=true;assert.equal(await controller.markAll(),'unknown');controller.reconcile();await reconciliation;
  assert.equal(controller.getState().issue,null);assert.equal(controller.getState().unreadCount,0);assert.equal(ready(await a.inbox.load()).notificationUnreadCount,aUnread);controller.dispose();
  pass('lost mark-all response reconciles to server state and preserves another recipient inbox');

  phase='shared cookie actor binding';
  for(const operation of ['load','logoutAll'] as const){
    const jar={cookie:''},oldTransport=new Transport(jar),newTransport=new Transport(jar);let now=Date.now();
    const old=make(oldTransport,()=>now),current=make(newTransport);
    await old.session.identity.login(a.credentials);await current.session.identity.login(b.credentials);now+=901000;
    await assert.rejects(operation==='load'?old.inbox.load():old.session.identity.logoutAll(),(error:unknown)=>error instanceof ApiError&&error.code==='SESSION_CHANGED');
    assert.equal(oldTransport.paths.some(path=>path.startsWith('GET /api/v1/notifications')||path==='POST /api/v1/auth/logout-all'),false);
    await current.session.identity.requests();
  }
  pass('a cookie changed by another tab cannot switch the inbox actor or revoke the other actor sessions');

  phase='revocation';await admin.session.identity.issueCode(b.actor.id,true);
  await assert.rejects(b.inbox.load(),(error:unknown)=>error instanceof ApiError&&error.status===401);assert.equal(b.session.getActorId(),null);
  assert.equal(ready(await a.inbox.load()).notificationUnreadCount,aUnread);
  pass('Core revocation clears the shared Web identity and leaves another recipient session valid');
  await a.session.identity.logout();await admin.session.identity.logout();
  console.log(JSON.stringify({passed:checks.length,fixture:'synthetic',authenticatedHttp:true,browserInteraction:false}));
}catch(error){console.error(JSON.stringify({phase,code:error instanceof ApiError?error.code:'CHECK_FAILED',status:error instanceof ApiError?error.status:undefined}));process.exitCode=1;}}
void main();
