import assert from 'node:assert/strict';
import {randomBytes, randomUUID} from 'node:crypto';
import {createLiveIdentity} from '../src/lib/data/live-identity';
import {ApiError} from '../src/lib/api/errors';

// Explicit opt-in: this creates synthetic accounts/requests and revokes sessions
// in a dedicated local test fixture. Never point it at an operational database.
if (process.env.CORE_SECURITY_TEST_MODE !== 'synthetic') throw new Error('Dedicated synthetic fixture required');
function localOrigin(name: string) {
  const value = new URL(process.env[name] ?? '');
  if (value.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(value.hostname) || value.username || value.password || value.pathname !== '/' || value.search || value.hash) throw new Error('Local test origin required');
  return value.origin;
}
const web = localOrigin('CORE_SECURITY_WEB_URL'), core = localOrigin('CORE_SECURITY_API_URL');
function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error('Synthetic fixture credentials required');
  return value;
}
const email = required('CORE_SECURITY_ADMIN_EMAIL');
const password = required('CORE_SECURITY_ADMIN_PASSWORD');
const checks: string[] = [];
let phase = 'startup';
const confirmed = (label: string) => { checks.push(label); console.log('PASS ' + label); };

class SessionTransport {
  private cookie = '';
  bearer: string | null = null;
  paths: string[] = [];
  rotations = 0;
  dropLoginResponse = false;
  readonly fetch: typeof fetch = async (input, init = {}) => {
    const path = String(input);
    assert.ok(path.startsWith('/api/v1/'));
    const headers = new Headers(init.headers);
    if (headers.get('Authorization')) this.bearer = headers.get('Authorization');
    if (!['GET', 'HEAD'].includes(init.method ?? 'GET')) headers.set('Origin', web);
    if (path.startsWith('/api/v1/auth/') && this.cookie) headers.set('Cookie', this.cookie);
    this.paths.push(path);
    const response = await fetch(web + path, {...init, headers});
    for (const value of response.headers.getSetCookie()) {
      assert.match(value, /HttpOnly/i);
      assert.match(value, /Path=\/api\/v1\/auth/i);
      assert.match(value, /SameSite=lax/i);
      const pair = value.split(';', 1)[0];
      if (pair === 'refresh_token=' || /Max-Age=0(?:;|$)/i.test(value)) this.cookie = '';
      else { if (this.cookie && pair !== this.cookie) this.rotations++; this.cookie = pair; }
    }
    if (path.endsWith('/auth/login') && response.ok && this.dropLoginResponse) {
      this.dropLoginResponse = false;
      await response.body?.cancel();
      throw new TypeError('Synthetic lost response after receiving cookie');
    }
    return response;
  };
}
function identity(transport: SessionTransport, now?: () => number) {
  return createLiveIdentity({fetcher: transport.fetch, onLost() {}, now});
}
async function direct(path: string, bearer: string | null) {
  return fetch(core + path, {headers: bearer ? {Authorization: bearer} : {}, signal: AbortSignal.timeout(15000)});
}
function expectStatus(response: Response, status: number) {
  if (response.status !== status) throw new Error('Unexpected HTTP status ' + response.status + ', expected ' + status);
}

async function main() {
try {
  phase = 'login';
  expectStatus(await fetch(core + '/health/ready'), 200);
  expectStatus(await fetch(web + '/login'), 200);
  const adminTransport = new SessionTransport();
  let clock = Date.now();
  const admin = identity(adminTransport, () => clock);
  const adminUser = await admin.login({email, password});
  assert.ok(adminUser.roles.includes('ADMIN'));
  const otherAdminTransport = new SessionTransport(), otherAdmin = identity(otherAdminTransport);
  await otherAdmin.login({email, password});
  confirmed('staff login/profile through signed Web proxy and HttpOnly cookie contract');

  phase = 'student provisioning and ownership';
  const username = 'security.smoke.' + randomUUID().replaceAll('-', '');
  let studentPassword = randomBytes(32).toString('hex');
  const issued = await admin.createStudent(username, 'Synthetic Security Student');
  assert.ok(issued.purpose === 'ACTIVATION' && issued.code.length > 0);
  const studentTransport = new SessionTransport(), student = identity(studentTransport);
  await student.activate({username, activation_code: issued.code, new_password: studentPassword});
  const studentUser = await student.login({username, password: studentPassword});
  assert.equal(studentUser.id, issued.student.id);
  await assert.rejects(student.createStudent('security.denied.' + randomUUID().replaceAll('-', '')), (e: unknown) => e instanceof ApiError && e.status === 403);
  const request = await student.createRequest('CORRECTION', 'Synthetic security check');
  assert.equal(request.user_id, studentUser.id);
  assert.ok((await student.requests()).items.some(item => item.id === request.id));
  assert.ok((await admin.requests()).items.every(item => item.user_id === adminUser.id));
  const forgedOwner = await studentTransport.fetch('/api/v1/users/me/data-requests', {method: 'POST', headers: {Authorization: studentTransport.bearer!, 'Content-Type': 'application/json'}, body: JSON.stringify({type: 'EXPORT', user_id: adminUser.id})});
  expectStatus(forgedOwner, 422);
  confirmed('Student activation/login, Admin-only rejection and personal-data ownership');

  phase = 'class resource permission';
  const classesResponse = await direct('/api/v1/classes', adminTransport.bearer);
  expectStatus(classesResponse, 200);
  const classes = await classesResponse.json() as {items: {id: string}[]};
  assert.ok(classes.items.length > 0);
  expectStatus(await direct('/api/v1/classes/' + classes.items[0].id, studentTransport.bearer), 404);
  expectStatus(await direct('/api/v1/classes/' + classes.items[0].id + '/posts', adminTransport.bearer), 404);
  confirmed('unenrolled Student denied class access; Admin metadata role does not grant Social read');

  phase = 'unknown login reconciliation';
  const lostTransport = new SessionTransport(); lostTransport.dropLoginResponse = true;
  const recovered = identity(lostTransport);
  await assert.rejects(recovered.login({username, password: studentPassword}), (e: unknown) => e instanceof ApiError && e.outcome === 'unknown');
  assert.equal((await recovered.restore())?.id, studentUser.id);
  assert.equal(lostTransport.paths.filter(path => path.endsWith('/auth/login')).length, 1);
  assert.ok(lostTransport.rotations > 0);
  confirmed('lost login response reconciles the actual cookie actor with rotation and no login replay');

  phase = 'Student recovery revocation';
  const recovery = await admin.issueCode(studentUser.id, true);
  assert.equal(recovery.purpose, 'PASSWORD_RESET');
  await assert.rejects(student.requests(), (e: unknown) => e instanceof ApiError && e.status === 401);
  studentPassword = randomBytes(32).toString('hex');
  await student.reset(recovery.code, studentPassword);
  assert.equal((await student.login({username, password: studentPassword})).id, studentUser.id);
  confirmed('verified Student recovery revokes old access and accepts only the new password');

  phase = 'logout-all with expired local access';
  clock += 901_000;
  await admin.logoutAll();
  assert.ok(adminTransport.paths.slice(-3).join('|').endsWith('/api/v1/auth/refresh|/api/v1/users/me|/api/v1/auth/logout-all'));
  assert.ok(adminTransport.rotations > 0);
  await assert.rejects(otherAdmin.requests(), (e: unknown) => e instanceof ApiError && e.status === 401);
  assert.equal(await otherAdmin.restore(), null);
  assert.ok((await student.requests()).items.every(item => item.user_id === studentUser.id));
  confirmed('expired-access logout-all refreshes, revokes another actual session and preserves other users');

  phase = 'Origin and forged proxy metadata';
  const wrongOrigin = await fetch(web + '/api/v1/auth/login', {method: 'POST', headers: {Origin: 'http://invalid.example', 'Content-Type': 'application/json'}, body: '{}'});
  expectStatus(wrongOrigin, 403);
  const error = await wrongOrigin.json() as {error: {correlation_id: string}};
  assert.equal(error.error.correlation_id, wrongOrigin.headers.get('X-Correlation-ID'));
  const forged = await fetch(core + '/api/v1/auth/login', {method: 'POST', headers: {Origin: web, 'Content-Type': 'application/json', 'X-Lumi-Client-Context': 'forged'}, body: JSON.stringify({username, password: studentPassword})});
  expectStatus(forged, 403);
  const browserForgery = await fetch(web + '/api/v1/auth/login', {method: 'POST', headers: {Origin: web, 'Content-Type': 'application/json', 'X-Lumi-Client-Context': 'forged', 'X-Forwarded-For': '198.51.100.9'}, body: JSON.stringify({username, password: studentPassword})});
  expectStatus(browserForgery, 200);
  const blocked = await fetch(web + '/api/v1/admin/unknown'); expectStatus(blocked, 404);
  assert.ok(blocked.headers.get('X-Correlation-ID'));
  confirmed('Origin fails closed, Core rejects forged attestation, Node overwrites browser spoofing, allowlist remains closed');

  phase = 'rate limiting';
  for (let index = 0; index < 5; index++) {
    const denied = await fetch(web + '/api/v1/auth/login', {method: 'POST', headers: {Origin: web, 'Content-Type': 'application/json'}, body: JSON.stringify({username: 'security.invalid.' + randomUUID().replaceAll('-', ''), password: 'synthetic-invalid'})});
    expectStatus(denied, 401);
  }
  const limited = await fetch(web + '/api/v1/auth/login', {method: 'POST', headers: {Origin: web, 'Content-Type': 'application/json'}, body: JSON.stringify({username, password: studentPassword})});
  expectStatus(limited, 429); assert.ok(limited.headers.get('Retry-After'));
  confirmed('actual signed client remains rate limited after five failed login attempts');
  await student.logout();
  console.log(JSON.stringify({passed: checks.length, fixture: 'synthetic', authenticatedHttp: true, browserInteraction: false}));
} catch (error) {
  // Never print assertion payloads, request/response bodies, cookies or tokens.
  console.error(JSON.stringify({phase, code: error instanceof ApiError ? error.code : 'CHECK_FAILED', status: error instanceof ApiError ? error.status : undefined}));
  process.exitCode = 1;
}
}
void main();
