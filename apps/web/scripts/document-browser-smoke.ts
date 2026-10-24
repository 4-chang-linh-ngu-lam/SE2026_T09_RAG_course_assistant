import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname,join,resolve,sep} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

async function main(){
  if(process.env.CORE_SECURITY_TEST_MODE!=='synthetic')throw new Error('Synthetic fixture required');
  function required(name:string){const value=process.env[name];if(!value)throw new Error('Missing synthetic browser configuration');return value;}
  const fixture=JSON.parse(await readFile(required('CORE_BROWSER_FIXTURE_PATH'),'utf8'));
  const web=new URL(required('CORE_SECURITY_WEB_URL'));
  assert.equal(fixture.web,web.origin);assert.ok(web.protocol==='http:'&&['localhost','127.0.0.1'].includes(web.hostname));
  const directory=await mkdtemp(join(tmpdir(),'lumi-document-browser-'));
  const browser=spawn(required('CORE_BROWSER_EXECUTABLE'),['--headless=new','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',`--user-data-dir=${directory}`,'--no-first-run','--no-default-browser-check','--disable-sync','--disable-background-networking','about:blank'],{stdio:'ignore',windowsHide:true});
  let spawnFailed=false;browser.on('error',()=>{spawnFailed=true;});
  let phase='startup',lastAction='startup',passed=0,exceptions=0,lastPage:Cdp|undefined,root:Cdp|undefined;
  const connections:Cdp[]=[];
  class Cdp{
    socket:WebSocket;next=0;interceptUpload=false;intercepted=false;interceptNote=false;noteIntercepted=false;
    pending=new Map<number,{resolve:(value:any)=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}>();
    constructor(url:string){this.socket=new WebSocket(url);this.socket.addEventListener('message',event=>{
      const value=JSON.parse(String(event.data));
      if(value.id){const pending=this.pending.get(value.id);if(!pending)return;clearTimeout(pending.timer);this.pending.delete(value.id);value.error?pending.reject(new Error('CDP failed')):pending.resolve(value.result);}
      if(value.method==='Runtime.exceptionThrown')exceptions++;
      if(value.method==='Fetch.requestPaused'){
        const request=value.params;
        const path=new URL(request.request.url).pathname;
        const loseUpload=this.interceptUpload&&!this.intercepted&&request.request.method==='POST'&&path==='/api/document/v1/documents'&&request.responseStatusCode===201;
        const loseNote=this.interceptNote&&!this.noteIntercepted&&request.request.method==='PATCH'&&/^\/api\/document\/v1\/notes\/[a-f0-9-]+$/.test(path)&&request.responseStatusCode===200;
        const lose=loseUpload||loseNote;if(loseUpload)this.intercepted=true;if(loseNote)this.noteIntercepted=true;
        void this.send(lose?'Fetch.failRequest':'Fetch.continueRequest',lose?{requestId:request.requestId,errorReason:'ConnectionClosed'}:{requestId:request.requestId}).catch(()=>{});
      }
    });}
    async ready(){await new Promise<void>((resolve,reject)=>{this.socket.addEventListener('open',()=>resolve(),{once:true});this.socket.addEventListener('error',()=>reject(new Error('Browser connection failed')),{once:true});});return this;}
    send(method:string,params:Record<string,unknown>={}):Promise<any>{const id=++this.next;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('CDP timeout'));},20000);this.pending.set(id,{resolve,reject,timer});this.socket.send(JSON.stringify({id,method,params}));});}
    close(){for(const item of this.pending.values()){clearTimeout(item.timer);item.reject(new Error('Browser closed'));}this.pending.clear();this.socket.close();}
  }
  async function until(work:()=>Promise<boolean>,timeout=35000){const end=Date.now()+timeout;while(Date.now()<end){try{if(await work())return;}catch(error){if(!(error instanceof Error)||error.message!=='CDP failed')throw error;}await delay(120);}throw new Error('Browser condition timed out');}
  async function evaluate(page:Cdp,expression:string){lastPage=page;const result=await page.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error('Browser evaluation failed');return result.result.value;}
  async function visible(page:Cdp,selector:string){return Boolean(await evaluate(page,`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return e&&e.getClientRects().length>0;})()`));}
  async function click(page:Cdp,selector:string){lastAction='click:'+selector;await until(async()=>Boolean(await evaluate(page,`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return e&&e.getClientRects().length>0&&!e.matches(':disabled');})()`)));await evaluate(page,`document.querySelector(${JSON.stringify(selector)}).click()`);}
  async function button(page:Cdp,label:string){lastAction='button:'+label;const target=`[...document.querySelectorAll('button')].find(e=>e.textContent.trim()===${JSON.stringify(label)}&&e.getClientRects().length>0&&!e.matches(':disabled'))`;await until(async()=>Boolean(await evaluate(page,`Boolean(${target})`)));await evaluate(page,`(${target}).click()`);}
  async function text(page:Cdp,value:string){lastAction='wait text';await until(async()=>Boolean(await evaluate(page,`document.body.innerText.includes(${JSON.stringify(value)})`)));}
  async function fill(page:Cdp,selector:string,value:string){lastAction='fill:'+selector;await until(()=>visible(page,selector));await evaluate(page,`(()=>{const e=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(e instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);}
  async function file(page:Cdp,selector:string,path:string){await until(()=>visible(page,selector));const document=await page.send('DOM.getDocument');const {nodeId}=await page.send('DOM.querySelector',{nodeId:document.root.nodeId,selector});assert.ok(nodeId);await page.send('DOM.setFileInputFiles',{nodeId,files:[path]});}
  async function navigate(page:Cdp,path:string){lastAction='navigate';const target=new URL(path,web.origin);assert.equal(target.origin,web.origin);const result=await page.send('Page.navigate',{url:target.toString()});await until(async()=>{if(result.loaderId&&(await page.send('Page.getFrameTree')).frameTree.frame.loaderId!==result.loaderId)return false;return Boolean(await evaluate(page,`location.pathname===${JSON.stringify(target.pathname)}&&document.readyState==='complete'`));});}
  async function focus(page:Cdp){await page.send('Page.bringToFront');await evaluate(page,"window.dispatchEvent(new Event('focus'))");}
  async function screenshot(page:Cdp,name:string){await writeFile(join(required('CORE_BROWSER_ARTIFACT_DIR'),name),Buffer.from((await page.send('Page.captureScreenshot',{format:'png'})).data,'base64'));}
  function pass(label:string){passed++;console.log('PASS '+label);}
  try{
    let port=0,socket='';await until(async()=>{if(spawnFailed)throw new Error('Chrome start failed');try{const lines=(await readFile(join(directory,'DevToolsActivePort'),'utf8')).trim().split(/\r?\n/);port=Number(lines[0]);socket=lines[1];return Boolean(port&&socket);}catch{return false;}});
    root=await new Cdp(`ws://127.0.0.1:${port}${socket}`).ready();connections.push(root);
    async function page(){const {browserContextId}=await root!.send('Target.createBrowserContext');const {targetId}=await root!.send('Target.createTarget',{url:'about:blank',browserContextId});const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();const tab=targets.find((item:{id:string})=>item.id===targetId);assert.ok(tab);const page=await new Cdp(tab.webSocketDebuggerUrl).ready();connections.push(page);await page.send('Page.enable');await page.send('Runtime.enable');await page.send('Network.enable');await page.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});return page;}
    async function login(page:Cdp,input:{email?:string;username?:string;password:string}){await navigate(page,'/login');await until(()=>visible(page,'#identifier'));if(input.email)await click(page,'#tab-staff');await fill(page,'#identifier',input.email??input.username!);await fill(page,'#password',input.password);await click(page,'form button[type="submit"]');await until(async()=>Boolean(await evaluate(page,"location.pathname!=='/login'&&Boolean(document.querySelector('.page-heading'))")));}
    const teacher=await page(),student=await page();await login(teacher,fixture.teacher);await login(student,fixture.student);
    const suffix=Date.now().toString(36),title='Browser Document '+suffix,updated=title+' updated';
    const source='Browser source quotation '+suffix,handwriting='Private handwritten note '+suffix;
    const sourceFile=join(directory,'source.md'),badFile=join(directory,'broken.md');await writeFile(sourceFile,source+'\n\nSecond real section');await writeFile(badFile,Buffer.from([255,0,254]));

    phase='Teacher actual file upload and metadata persistence';
    await navigate(teacher,'/teacher/library');await click(teacher,'#ux-doc-open-upload');await file(teacher,'#ux-doc-file',sourceFile);await fill(teacher,'#ux-doc-title',title);await click(teacher,'#ux-doc-upload');
    await until(async()=>Boolean(await evaluate(teacher,`[...document.querySelectorAll('a.library-title-link')].some(e=>e.textContent.includes(${JSON.stringify(title)}))`)));
    const detailPath=await evaluate(teacher,`[...document.querySelectorAll('a.library-title-link')].find(e=>e.textContent.includes(${JSON.stringify(title)})).getAttribute('href')`);assert.match(detailPath,/^\/teacher\/library\/[a-f0-9-]+$/);
    const documentId=detailPath.split('/').pop();await navigate(teacher,detailPath);await until(()=>visible(teacher,'.lumi-source-badge-serving'));
    await button(teacher,'Sửa tên và mô tả');await fill(teacher,'#document-metadata-title',updated);await fill(teacher,'#document-metadata-description','Browser metadata');await button(teacher,'Lưu thông tin');await text(teacher,updated);await navigate(teacher,detailPath);await text(teacher,updated);
    pass('Teacher uploads real file, worker publishes READY, metadata survives full reload');

    phase='Class grant and Student reader with private quoted note';
    await click(teacher,'#ux-doc-open-share');const label=`[...document.querySelectorAll('.lumi-source-share-item')].find(e=>e.querySelector('.lumi-source-share-class-name')?.textContent===${JSON.stringify(fixture.className)})`;await until(async()=>Boolean(await evaluate(teacher,`Boolean(${label})`)));await evaluate(teacher,`(${label}).querySelector('input').click()`);await click(teacher,'#ux-doc-confirm-share');await until(()=>visible(teacher,'.lumi-source-btn-revoke'));
    await navigate(student,`/student/classes/${fixture.classId}/documents`);await text(student,updated);await navigate(student,`/student/classes/${fixture.classId}/documents/${documentId}`);await text(student,source);
    await evaluate(student,`(()=>{const p=document.querySelector('.page-paragraph'),range=document.createRange();range.selectNodeContents(p);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);p.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));})()`);await click(student,'#reader-capture-quote');await until(()=>visible(student,'.reader-quote-composer blockquote'));
    await fill(student,'#newNoteInput',handwriting);await button(student,'Lưu ghi chú');await until(async()=>Boolean(await evaluate(student,`[...document.querySelectorAll('.note-user-text')].some(e=>e.textContent===${JSON.stringify(handwriting)})`)));await button(student,'Đánh dấu');await button(student,'Đã đánh dấu');await button(student,'Đánh dấu');await text(student,'Đã đánh dấu');
    await navigate(student,`/student/classes/${fixture.classId}/documents/${documentId}`);await text(student,handwriting);await text(student,'Đã đánh dấu');await until(()=>visible(student,'.reader-note-item .note-quote-box'));await screenshot(student,'document-reader-desktop.png');
    await button(student,'Sửa');await fill(student,'#editNoteTextarea',handwriting+' edited');student.interceptNote=true;await student.send('Fetch.enable',{patterns:[{urlPattern:web.origin+'/api/document/v1/notes/*',requestStage:'Response'}]});await button(student,'Lưu thay đổi');await until(async()=>student.noteIntercepted);await until(()=>visible(student,'dialog[open] [data-document-reconcile]'));await screenshot(student,'document-note-edit-unknown.png');await student.send('Fetch.disable');await click(student,'dialog[open] [data-document-reconcile]');await until(async()=>!(await visible(student,'dialog[open]')));await text(student,handwriting+' edited');
    await navigate(student,'/student/notes');await text(student,handwriting);assert.equal(await evaluate(student,"new URL(document.querySelector('.note-card .note-doc-title-link').href).searchParams.get('version')"),'1');await navigate(student,`/student/classes/${fixture.classId}/documents/${documentId}`);await text(student,handwriting);
    pass('Class grant, real reader, quote/bookmark persistence and lost note-edit response reconciled inside its dialog');

    phase='Reader mobile accessibility and viewport';
    await student.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await focus(student);assert.equal(await evaluate(student,'document.documentElement.scrollWidth<=innerWidth'),true);await click(student,'button[aria-label="Mở ghi chú cá nhân"]');await text(student,handwriting);await screenshot(student,'document-reader-mobile.png');
    await student.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await student.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    await student.send('Emulation.setDeviceMetricsOverride',{width:320,height:740,deviceScaleFactor:1,mobile:true});assert.equal(await evaluate(student,'document.documentElement.scrollWidth<=innerWidth'),true);
    pass('Reader and personal notes open at 390px and 320px without page overflow');

    phase='Failed v2 preserves current serving source';
    await focus(teacher);await click(teacher,'#ux-doc-upload-version');await file(teacher,'#ux-doc-version-file-input',badFile);await button(teacher,'Tải lên phiên bản');await until(()=>visible(teacher,'.lumi-source-failure-card'));assert.equal(await evaluate(teacher,"document.querySelector('.lumi-source-badge-serving').textContent.includes('v1')"),true);await screenshot(teacher,'document-source-failed-version.png');
    pass('Invalid newer file shows failure and keeps v1 serving in source management UI');

    phase='Current permission revoke and retained personal handwriting';
    await click(teacher,'.lumi-source-btn-revoke');await click(teacher,'#ux-doc-revoke');await until(async()=>!(await visible(teacher,'.lumi-source-btn-revoke')));await focus(student);await text(student,'Không thể mở tài liệu học tập');assert.equal(await evaluate(student,`Boolean(document.querySelector('.page-paragraph'))||document.body.innerText.includes(${JSON.stringify(source)})`),false);
    await navigate(student,'/student/notes');await text(student,handwriting);assert.equal(await evaluate(student,`document.body.innerText.includes(${JSON.stringify(source)})`),false);assert.equal(await evaluate(student,"Boolean(document.querySelector('.note-card .note-doc-title-link,.bookmark-card .note-doc-title-link'))"),false);assert.equal(await evaluate(student,'document.documentElement.scrollWidth<=innerWidth'),true);assert.equal(await evaluate(student,"[...document.querySelectorAll('.note-card button,.note-card a,.notes-toolbar input')].every(e=>e.getBoundingClientRect().right<=innerWidth&&e.getBoundingClientRect().left>=0)"),true);await screenshot(student,'document-notes-revoked-mobile.png');
    pass('Open Reader loses source after revoke; own notes retain handwriting and hide the source quote');

    phase='Lost upload response and durable receipt reconciliation';
    await navigate(teacher,'/teacher/library');await click(teacher,'#ux-doc-open-upload');await file(teacher,'#ux-doc-file',sourceFile);const lostTitle='Lost response '+suffix;await fill(teacher,'#ux-doc-title',lostTitle);teacher.interceptUpload=true;await teacher.send('Fetch.enable',{patterns:[{urlPattern:web.origin+'/api/document/v1/documents',requestStage:'Response'}]});await click(teacher,'#ux-doc-upload');await until(async()=>teacher.intercepted);await text(teacher,'Chưa xác định');await teacher.send('Fetch.disable');await button(teacher,'Đối soát upload đã gửi');await until(async()=>!(await visible(teacher,'dialog[open]')));await navigate(teacher,'/teacher/library');await text(teacher,lostTitle);assert.equal(await evaluate(teacher,`[...document.querySelectorAll('a.library-title-link')].filter(e=>e.textContent.includes(${JSON.stringify(lostTitle)})).length`),1);
    assert.equal(exceptions,0);assert.equal(await evaluate(teacher,'localStorage.length+sessionStorage.length'),0);
    pass('Response lost after upload commit stays unknown; receipt confirms one document without duplicate submit');
    console.log(JSON.stringify({passed,fixture:'synthetic',authenticatedHttp:true,documentService:true,browserInteraction:true,uncaughtExceptions:exceptions,viewports:[1440,390,320]}));
  }catch(error){if(lastPage)try{await screenshot(lastPage,'document-browser-failure.png');}catch{}console.error(JSON.stringify({phase,lastAction,passed,code:'DOCUMENT_BROWSER_FAILED',kind:error instanceof Error?error.message:'Unknown'}));process.exitCode=1;}
  finally{if(root)try{await root.send('Browser.close');}catch{}for(const item of connections)item.close();if(browser.exitCode===null){browser.kill();await Promise.race([new Promise(resolve=>browser.once('close',resolve)),delay(5000)]);}const owned=resolve(directory);assert.equal(dirname(owned),resolve(tmpdir()));assert.ok(owned.startsWith(resolve(tmpdir())+sep+'lumi-document-browser-'));await rm(owned,{recursive:true,force:true,maxRetries:10,retryDelay:200});}
}
void main().catch(()=>{console.error('FAIL Document browser fixture startup or cleanup');process.exitCode=1;});
