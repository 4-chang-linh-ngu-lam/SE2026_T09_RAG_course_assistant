import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';

type Page = {socket: WebSocket; send(method: string, params?: Record<string, unknown>): Promise<any>};
type Paused = {requestId: string; request: {method: string}};
type Browser<T extends Page> = {
  page(): Promise<T>;
  navigate(page: T, path: string): Promise<void>;
  fill(page: T, selector: string, value: string): Promise<void>;
  click(page: T, selector: string): Promise<void>;
  button(page: T, label: string): Promise<void>;
  text(page: T, value: string): Promise<void>;
  visible(page: T, selector: string): Promise<boolean>;
  evaluate(page: T, expression: string): Promise<any>;
  until(work: () => Promise<boolean>): Promise<void>;
  phase(value: string): void;
  pass(value: string): void;
};

async function intercept(page: Page, urlPattern: string, handle: (request: Paused) => Promise<void>) {
  let failure: unknown;
  const listener = (event: MessageEvent) => {
    const message = JSON.parse(String(event.data));
    if (message.method === 'Fetch.requestPaused') void handle(message.params).catch(error => { failure = error; });
  };
  page.socket.addEventListener('message', listener);
  await page.send('Fetch.enable', {patterns: [{urlPattern, requestStage: 'Request'}]});
  return async () => {
    await page.send('Fetch.disable');
    page.socket.removeEventListener('message', listener);
    if (failure) throw failure;
  };
}

export async function coreP2BrowserRegressions<T extends Page>(
  browser: Browser<T>,
  teacher: T,
  fixture: {classId: string; student: {username: string; password: string}},
  web: string,
) {
  const {navigate, fill, click, button, text, visible, evaluate, until, pass} = browser;
  const suffix = randomUUID().slice(0,8);

  browser.phase('P2 profile response must preserve newer edits');
  await navigate(teacher,'/account');
  await until(() => visible(teacher,'#display-name'));
  let paused: string | null = null, hold = true;
  const releaseProfile = await intercept(teacher,web+'/api/v1/users/me',async request => {
    if (request.request.method === 'PATCH' && hold) { hold = false; paused = request.requestId; }
    else await teacher.send('Fetch.continueRequest',{requestId:request.requestId});
  });
  const firstName = 'Browser saved A '+suffix, nextName = 'Browser draft B '+suffix;
  try {
    await fill(teacher,'#display-name',firstName);
    await button(teacher,'Lưu thay đổi');
    await until(async () => paused !== null);
    await fill(teacher,'#display-name',nextName);
    await teacher.send('Fetch.continueRequest',{requestId:paused});
    paused = null;
    await until(async () => Boolean(await evaluate(teacher,"document.querySelector('#display-name').value==="+JSON.stringify(nextName)+"&&![...document.querySelectorAll('form button')].find(e=>e.textContent.trim()==='Lưu thay đổi').disabled")));
    assert.equal(await evaluate(teacher,"Boolean(document.querySelector('.notice.success'))"),false);
    await button(teacher,'Lưu thay đổi');
    await text(teacher,'Đã lưu thông tin.');
  } finally { await releaseProfile(); }
  await navigate(teacher,'/account');
  await until(async () => await evaluate(teacher,"document.querySelector('#display-name')?.value==="+JSON.stringify(nextName)));
  pass('P2 profile: ACK for A preserves draft B without a false success; explicit save B persists after reload');

  browser.phase('P2 ambiguous login must unlock only after confirmed sign-out');
  const login = await browser.page();
  await navigate(login,'/login');
  await until(() => visible(login,'#identifier'));
  await fill(login,'#identifier',fixture.student.username);
  await fill(login,'#password',fixture.student.password);
  await login.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await click(login,'form button[type="submit"]');
  await until(() => visible(login,'#login-session-check'));
  await click(login,'#login-session-check');
  await until(async () => await evaluate(login,"document.querySelector('#login-session-check')?.disabled===false"));
  assert.equal(await evaluate(login,"document.querySelector('form button[type=submit]').disabled"),true);
  await login.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await click(login,'#login-session-check');
  await until(async () => await evaluate(login,"!document.querySelector('#login-session-check')&&!document.querySelector('form button[type=submit]').disabled"));
  assert.equal(await evaluate(login,'location.pathname'),'/login');
  await click(login,'form button[type="submit"]');
  await until(async () => await evaluate(login,"location.pathname!=='/login'&&Boolean(document.querySelector('.page-heading'))"));
  pass('P2 login: unavailable reconciliation keeps submit locked; confirmed signed-out unlocks explicit retry in the same form');

  browser.phase('P2 multi-day calendar in month, list and week');
  const dates = await evaluate(teacher,`(() => {
    const now=new Date(), y=now.getFullYear(), m=now.getMonth();
    const next=new Date(y,m+1,1), prefix=next.getFullYear()+'-'+String(next.getMonth()+1).padStart(2,'0');
    return {start:new Date(y,m+1,0,14).toISOString(),end:new Date(y,m+1,2,9).toISOString(),midnight:next.toISOString(),prefix};
  })()`);
  const title = 'Browser multi-day '+suffix, cutoff = 'Browser ends at midnight '+suffix;
  const row = {id:randomUUID(),class_id:fixture.classId,title,description:null,starts_at:dates.start,ends_at:dates.end,origin:'CORE',external_ref:null};
  // Only this UI regression supplies synthetic calendar receipts. Auth/class reads
  // remain live; the earlier calendar group verifies real create/edit persistence.
  const releaseCalendar = await intercept(teacher,web+`/api/v1/classes/${fixture.classId}/calendar*`,async request => {
    await teacher.send('Fetch.fulfillRequest',{
      requestId:request.requestId,responseCode:200,
      responseHeaders:[{name:'Content-Type',value:'application/json'},{name:'Cache-Control',value:'no-store'}],
      body:Buffer.from(JSON.stringify({items:[row,{...row,id:randomUUID(),title:cutoff,ends_at:dates.midnight}],next_cursor:null})).toString('base64'),
    });
  });
  try {
    await navigate(teacher,`/teacher/classes/${fixture.classId}/calendar`);
    await text(teacher,title);
    await click(teacher,'button[aria-label="Tháng sau"]');
    await button(teacher,'Danh sách');
    await until(async () => await evaluate(teacher,"document.querySelectorAll('.cal-list-item').length===1"));
    assert.equal(await evaluate(teacher,"document.querySelector('.cal-list-item').textContent.includes("+JSON.stringify(title)+")"),true);
    await button(teacher,'Tháng');
    for (const day of [1,2]) {
      assert.equal(await evaluate(teacher,`[...document.querySelectorAll('.cal-month-grid .cal-day-cell.in-month')].find(e=>e.querySelector('.cal-day-num').textContent.trim()===${JSON.stringify(String(day))})?.textContent.includes(${JSON.stringify(title)})`),true);
    }
    await evaluate(teacher,`[...document.querySelectorAll('.cal-month-grid .cal-day-cell.in-month')].find(e=>e.querySelector('.cal-day-num').textContent.trim()==='2').querySelector('.cal-event-pill').click()`);
    await button(teacher,'Tuần');
    assert.equal(await evaluate(teacher,"document.querySelector('.cal-month-grid .cal-day-cell.selected')?.querySelector('.cal-day-num').textContent.trim()"),'2');
    assert.equal(await evaluate(teacher,"document.querySelector('.cal-month-grid .cal-day-cell.selected')?.textContent.includes("+JSON.stringify(title)+")"),true);
  } finally { await releaseCalendar(); }
  pass('P2 calendar: spanning event appears on both next-month days, in the list and selected week; midnight cutoff excluded');
}
