import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtemp,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname,join,resolve,sep} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {getRoute} from '../src/config/routes';

async function main(){
// Runs only against the runner's disposable fixture, with a fresh Chrome profile.
// CDP payloads, credentials, cookies and page text are never logged.
if(process.env.CORE_SECURITY_TEST_MODE!=='synthetic')throw new Error('Synthetic fixture required');
function required(name:string){const value=process.env[name];if(!value)throw new Error('Missing browser fixture configuration');return value;}
const fixture=JSON.parse(await readFile(required('CORE_BROWSER_FIXTURE_PATH'),'utf8'));
const web=new URL(required('CORE_SECURITY_WEB_URL'));
assert.equal(fixture.web,web.origin);
assert.ok(web.protocol==='http:'&&['localhost','127.0.0.1'].includes(web.hostname)&&web.pathname==='/'&&!web.search&&!web.hash&&!web.username&&!web.password);
const directory=await mkdtemp(join(tmpdir(),'lumi-core-browser-'));
const browser=spawn(required('CORE_BROWSER_EXECUTABLE'),['--headless=new','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',`--user-data-dir=${directory}`,'--no-first-run','--no-default-browser-check','--disable-sync','--disable-background-networking','about:blank'],{stdio:'ignore',windowsHide:true});
let spawnFailed=false;browser.on('error',()=>{spawnFailed=true;});
let phase='browser startup',passed=0,exceptionCount=0,lastAction='startup',lastPage:Cdp|undefined;
const connections:Cdp[]=[],responses:{method:string;path:string;status:number}[]=[];
const requestAuth=new Map<string,{present:boolean;fingerprint:string|null;iat:number|null;exp:number|null}>(),authDiagnostics:unknown[]=[];
class Cdp{
  socket:WebSocket;next=0;pending=new Map<number,{resolve:(value:any)=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}>();
  constructor(url:string){
    this.socket=new WebSocket(url);
    this.socket.addEventListener('message',event=>{
      const value=JSON.parse(String(event.data));
      if(value.id){const pending=this.pending.get(value.id);if(!pending)return;clearTimeout(pending.timer);this.pending.delete(value.id);value.error?pending.reject(new Error('CDP command failed')):pending.resolve(value.result);}
      if(value.method==='Runtime.exceptionThrown')exceptionCount++;
      if(value.method==='Network.requestWillBeSent'){
        const request=value.params.request,entry=Object.entries(request.headers).find(([name])=>name.toLowerCase()==='authorization'),credential=entry?String(entry[1]):'';
        let iat:number|null=null,exp:number|null=null;try{const claims=JSON.parse(Buffer.from(credential.split('.')[1],'base64url').toString());iat=claims.iat;exp=claims.exp;}catch{}
        requestAuth.set(value.params.requestId,{present:Boolean(credential),fingerprint:credential?createHash('sha256').update(credential).digest('hex').slice(0,12):null,iat,exp});
      }
      if(value.method==='Network.responseReceived'){
        const response=value.params.response,url=new URL(response.url);
        if(url.origin===web.origin&&url.pathname.startsWith('/api/v1/')){
          responses.push({method:value.params.type,path:url.pathname,status:response.status});
          authDiagnostics.push({path:url.pathname,status:response.status,...requestAuth.get(value.params.requestId),serverDate:response.headers.Date??response.headers.date??null});
        }
      }
    });
  }
  async ready(){await new Promise<void>((resolve,reject)=>{this.socket.addEventListener('open',()=>resolve(),{once:true});this.socket.addEventListener('error',()=>reject(new Error('Browser connection failed')),{once:true});});return this;}
  send(method:string,params:Record<string,unknown>={}):Promise<any>{
    const id=++this.next;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('CDP command timeout'));},20000);this.pending.set(id,{resolve,reject,timer});this.socket.send(JSON.stringify({id,method,params}));});
  }
  close(){for(const pending of this.pending.values()){clearTimeout(pending.timer);pending.reject(new Error('Browser closed'));}this.pending.clear();this.socket.close();}
}
async function until(work:()=>Promise<boolean>,timeout=20000){const deadline=Date.now()+timeout;while(Date.now()<deadline){try{if(await work())return;}catch(error){if(!(error instanceof Error)||error.message!=='CDP command failed')throw error;}await delay(100);}throw new Error('Browser condition timed out');}
async function evaluate(page:Cdp,expression:string){const result=await page.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error('Browser evaluation failed');return result.result.value;}
async function visible(page:Cdp,selector:string){return Boolean(await evaluate(page,`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return e&&e.getClientRects().length>0;})()`));}
async function fill(page:Cdp,selector:string,value:string){lastPage=page;lastAction='fill:'+selector;await until(()=>visible(page,selector));await evaluate(page,`(()=>{const e=document.querySelector(${JSON.stringify(selector)});const p=e instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:e instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);}
async function click(page:Cdp,selector:string){lastPage=page;lastAction='click:'+selector;await until(async()=>Boolean(await evaluate(page,`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return e&&e.getClientRects().length>0&&!e.matches(':disabled');})()`)));await evaluate(page,`document.querySelector(${JSON.stringify(selector)}).click()`);}
async function button(page:Cdp,text:string){lastPage=page;lastAction='button:'+text;const expression=`[...document.querySelectorAll('button')].find(e=>e.textContent.trim()===${JSON.stringify(text)}&&e.getClientRects().length>0&&!e.matches(':disabled'))`;await until(async()=>Boolean(await evaluate(page,`Boolean(${expression})`)));await evaluate(page,`(${expression}).click()`);}
async function text(page:Cdp,value:string){lastPage=page;lastAction='wait text';await until(async()=>Boolean(await evaluate(page,`document.body.innerText.includes(${JSON.stringify(value)})`)));}
async function navigate(page:Cdp,path:string){lastPage=page;lastAction='navigate';await page.send('Page.navigate',{url:web.origin+path});await until(async()=>Boolean(await evaluate(page,`location.pathname===${JSON.stringify(path.split('?')[0])}&&document.readyState==='complete'`)));}
function pass(label:string){passed++;console.log('PASS '+label);}
let root:Cdp|undefined;
try{
  let port=0,browserSocket='';
  await until(async()=>{if(spawnFailed)throw new Error('Browser failed to start');try{const lines=(await readFile(join(directory,'DevToolsActivePort'),'utf8')).trim().split(/\r?\n/);port=Number(lines[0]);browserSocket=lines[1];return Boolean(port&&browserSocket);}catch{return false;}});
  root=await new Cdp(`ws://127.0.0.1:${port}${browserSocket}`).ready();connections.push(root);
  async function page(){
    const {browserContextId}=await root!.send('Target.createBrowserContext');
    const {targetId}=await root!.send('Target.createTarget',{url:'about:blank',browserContextId});
    const tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const target=tabs.find((tab:{id:string})=>tab.id===targetId);assert.ok(target);
    const result=await new Cdp(target.webSocketDebuggerUrl).ready();connections.push(result);
    await result.send('Page.enable');await result.send('Runtime.enable');await result.send('Network.enable');
    await result.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});return result;
  }
  async function login(page:Cdp,input:{username?:string;email?:string;password:string}){
    await navigate(page,'/login');await until(()=>visible(page,'#identifier'));
    if(input.email)await click(page,'#tab-staff');
    await fill(page,'#identifier',input.email??input.username!);await fill(page,'#password',input.password);
    await click(page,'form button[type="submit"]');
    await until(async()=>Boolean(await evaluate(page,"location.pathname!=='/login'&&Boolean(document.querySelector('.page-heading'))")));
  }
  phase='Admin login and catalog submit';
  const admin=await page();await login(admin,{email:required('CORE_SECURITY_ADMIN_EMAIL'),password:required('CORE_SECURITY_ADMIN_PASSWORD')});
  await navigate(admin,getRoute('a.catalog').path);await until(()=>visible(admin,'#course-code-input'));
  const suffix=Date.now().toString(36),courseName='Browser Course '+suffix;
  await fill(admin,'#course-code-input','BROWSER'+suffix);await fill(admin,'#course-name-input',courseName);await button(admin,'Tạo môn học');
  await text(admin,courseName);await until(async()=>await evaluate(admin,"document.querySelector('#course-name-input').value===''"));
  await navigate(admin,getRoute('a.catalog').path);await text(admin,courseName);
  pass('Admin login, hydrated course form, confirmed save and persistence after full reload');

  phase='Student home and class navigation';
  const student=await page();await login(student,fixture.student);await text(student,fixture.className);
  await click(student,`a[href="/student/classes/${fixture.classId}/overview"]`);await text(student,'Bảng tin lớp');
  await navigate(student,`/student/classes/${fixture.classId.toUpperCase()}/overview`);await text(student,'Bảng tin lớp');
  await click(student,`a[href="/student/classes/${fixture.classId}/feed"]`);await until(()=>visible(student,'#feed-new-post'));
  const post='Browser post '+suffix;await fill(student,'#feed-new-post',post);await button(student,'Đăng bài viết');await text(student,post);
  await fill(student,'.feed-reply-box input','Browser comment '+suffix);await button(student,'Gửi');await text(student,'Browser comment '+suffix);
  await click(student,'button[aria-label="Sửa bình luận"]');await fill(student,'dialog[open] textarea','Browser edited '+suffix);await button(student,'Lưu bình luận');await text(student,'Browser edited '+suffix);
  await navigate(student,`/student/classes/${fixture.classId}/feed`);await text(student,post);await text(student,'Browser edited '+suffix);
  const cookies=await student.send('Network.getCookies',{urls:[web.origin+'/api/v1/auth/refresh']});assert.ok(cookies.cookies.some((cookie:{name:string;httpOnly:boolean})=>cookie.name==='refresh_token'&&cookie.httpOnly));
  assert.equal(await evaluate(student,'localStorage.length+sessionStorage.length'),0);
  pass('Student home/overview, uppercase UUID, post/comment edit and HttpOnly session restore in real browser');

  phase='Unknown mutation and explicit read reconciliation';
  await student.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await fill(student,'#feed-new-post','Offline synthetic post');await button(student,'Đăng bài viết');await text(student,'Chưa xác định kết quả thao tác.');
  await student.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await button(student,'Tải lại bảng tin');await until(()=>visible(student,'#feed-new-post'));
  await until(async()=>!(await evaluate(student,"document.body.innerText.includes('Chưa xác định kết quả thao tác.')")));
  assert.equal(await evaluate(student,"Boolean(document.querySelector('.feed-composer-card [role=alert]'))"),false);
  assert.equal(await evaluate(student,"[...document.querySelectorAll('.feed-post-content')].some(e=>e.textContent.includes('Offline synthetic post'))"),false);
  await student.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate(student,'document.documentElement.scrollWidth<=window.innerWidth'),true);
  await writeFile(join(required('CORE_BROWSER_ARTIFACT_DIR'),'student-feed-mobile.png'),Buffer.from((await student.send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await navigate(student,'/admin/accounts');await text(student,'Bạn không có quyền mở nội dung này');
  pass('Offline write remains unknown without replay, fresh GET reconciles; mobile feed and forbidden Admin route');

  phase='Teacher calendar UI';
  const teacher=await page();await login(teacher,fixture.teacher);await text(teacher,fixture.className);
  phase='Teacher overview reload';
  await navigate(teacher,`/teacher/classes/${fixture.classId.toUpperCase()}/overview`);await text(teacher,'Lịch lớp');
  phase='Teacher calendar create';
  await click(teacher,`a[href="/teacher/classes/${fixture.classId}/calendar"]`);await button(teacher,'Thêm sự kiện lớp');
  const event='Browser event '+suffix;await fill(teacher,'#evt-title',event);await fill(teacher,'#evt-time','07:00 – 08:00');await button(teacher,'Lưu sự kiện');await text(teacher,event);
  phase='Teacher calendar edit';
  await button(teacher,'Chỉnh sửa');await fill(teacher,'#edit-title',event+' edited');await button(teacher,'Cập nhật');await text(teacher,event+' edited');
  phase='Teacher calendar reload';
  await navigate(teacher,`/teacher/classes/${fixture.classId}/calendar`);await text(teacher,event+' edited');
  assert.equal(await evaluate(teacher,"(()=>{const grid=document.querySelector('.cal-month-grid'),cells=[...grid.children];return getComputedStyle(grid).display==='grid'&&getComputedStyle(grid).gridTemplateColumns.split(' ').length===7&&cells[0].getBoundingClientRect().top===cells[6].getBoundingClientRect().top&&cells[7].getBoundingClientRect().top>cells[0].getBoundingClientRect().top;})()"),true);
  await writeFile(join(required('CORE_BROWSER_ARTIFACT_DIR'),'teacher-calendar-desktop.png'),Buffer.from((await teacher.send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  pass('Teacher home/overview and calendar create/edit survive full browser reload');

  phase='Admin account status form and revoked Student session';
  await navigate(admin,getRoute('a.account').path.replace(':userId',fixture.studentId));await until(()=>visible(admin,'#user-status-select'));
  await fill(admin,'#user-status-select','LOCKED');await fill(admin,'#status-reason-select','USER_REQUEST');await button(admin,'Cập nhật trạng thái');await text(admin,'Đã cập nhật và tải lại dữ liệu hiện hành.');
  await navigate(student,`/student/classes/${fixture.classId}/feed`);await text(student,'Đăng nhập để tiếp tục');
  await fill(admin,'#user-status-select','ACTIVE');await button(admin,'Cập nhật trạng thái');await text(admin,'Đã cập nhật và tải lại dữ liệu hiện hành.');
  await until(async()=>responses.filter(response=>response.path.endsWith('/status')&&response.status===204).length>=2);
  assert.equal(exceptionCount,0);assert.ok(responses.some(response=>response.path.endsWith('/status')&&response.status===204));
  pass('Admin status form uses 204 acknowledgement/current reload and lock revokes the open browser session');
  console.log(JSON.stringify({passed,fixture:'synthetic',authenticatedHttp:true,browserInteraction:true,uncaughtExceptions:exceptionCount,viewports:[1440,390]}));
}catch{
  if(lastPage)try{await writeFile(join(required('CORE_BROWSER_ARTIFACT_DIR'),'browser-failure.png'),Buffer.from((await lastPage.send('Page.captureScreenshot',{format:'png'})).data,'base64'));}catch{}
  console.error(JSON.stringify({phase,lastAction,passed,code:'BROWSER_CHECK_FAILED',recentHttp:authDiagnostics.slice(-15)}));process.exitCode=1;
}finally{
  if(root){try{await root.send('Browser.close');}catch{}}
  for(const connection of connections)connection.close();
  if(browser.exitCode===null){browser.kill();await Promise.race([new Promise(resolve=>browser.once('close',resolve)),delay(5000)]);}
  const owned=resolve(directory);assert.equal(dirname(owned),resolve(tmpdir()));assert.ok(owned.startsWith(resolve(tmpdir())+sep+'lumi-core-browser-'));
  await rm(owned,{recursive:true,force:true,maxRetries:10,retryDelay:200});
}
}
void main().catch(()=>{console.error('FAIL browser fixture startup/cleanup');process.exitCode=1;});
