import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLiveIdentity } from '../src/lib/data/live-identity';
import { ApiError } from '../src/lib/api/errors';
import { draftStore, setAttemptDraft, getAttemptDraft, type ScopedPracticeAttemptDraft } from '../src/lib/draft-store';
const user = (id = 'a') => ({ id, email: null, username: id, school_id: 'school', display_name: id, roles: ['STUDENT'], status: 'ACTIVE' });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const access = (id: string, expires_in = 1) => json({ access_token: id, token_type: 'bearer', expires_in });
const pending = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise<void>(resolve => setImmediate(resolve));
function fetcher(run: (path: string, init: RequestInit) => Promise<Response> | Response): typeof fetch { return ((url: string | URL | Request, init: RequestInit = {}) => Promise.resolve(run(String(url), init))) as typeof fetch; }

test('expired access token shares one refresh before concurrent protected reads', async () => {
  let now = 0, refreshes = 0; const gate = pending<Response>(); const seen: string[] = [];
  const identity = createLiveIdentity({ now: () => now, onLost() {}, fetcher: fetcher((path, init) => {
    if (path.endsWith('/login')) return access('first');
    if (path.endsWith('/refresh')) { refreshes++; return gate.promise; }
    seen.push(new Headers(init.headers).get('Authorization') ?? '');
    return path.endsWith('/me') ? json(user()) : json({ items: [], next_cursor: null });
  }) });
  await identity.login({ username: 'a', password: 'p' }); now = 1001;
  const a = identity.requests(), b = identity.requests(); await tick();
  assert.equal(refreshes, 1); gate.resolve(access('renewed')); await Promise.all([a, b]);
  assert.deepEqual(seen.slice(-2), ['Bearer renewed', 'Bearer renewed']);
});
test('late restore /me cannot install the previous actor after a newer login', async () => {
  const oldMe = pending<Response>(); let logins = 0;
  const identity = createLiveIdentity({ onLost() {}, fetcher: fetcher((path, init) => {
    if (path.endsWith('/refresh')) return access('old', 600);
    if (path.endsWith('/login')) { logins++; return access('new', 600); }
    if (path.endsWith('/me')) return new Headers(init.headers).get('Authorization') === 'Bearer old' ? oldMe.promise : json(user('new'));
    return json({ items: [], next_cursor: null });
  }) });
  const restore = identity.restore(); await tick();
  assert.equal((await identity.login({ username: 'new', password: 'p' })).id, 'new');
  oldMe.resolve(json(user('old'))); assert.equal(await restore, null);
  assert.equal((await identity.restore())?.id, 'new'); assert.equal(logins, 1);
});
test('credential cookie responses settle in order before a new login is sent', async () => {
  const refresh = pending<Response>(); const order: string[] = [];
  const identity = createLiveIdentity({ onLost() {}, fetcher: fetcher(path => {
    if (path.endsWith('/refresh')) { order.push('refresh'); return refresh.promise; }
    if (path.endsWith('/login')) { order.push('login'); return access('new', 600); }
    return json(user('new'));
  }) });
  const restoring = identity.restore(); await tick(); const login = identity.login({ username: 'new', password: 'p' }); await tick();
  assert.deepEqual(order, ['refresh']); refresh.resolve(access('old', 600));
  assert.equal(await restoring, null); assert.equal((await login).id, 'new'); assert.deepEqual(order, ['refresh', 'login']);
});
test('ambiguous login allows explicit session check to probe the refresh cookie', async () => {
  let refreshes = 0;
  const identity = createLiveIdentity({ onLost() {}, fetcher: fetcher(path => {
    if (path.endsWith('/login')) throw new TypeError('connection lost after request');
    if (path.endsWith('/refresh')) { refreshes++; return access('reconciled', 600); }
    if (path.endsWith('/me')) return json(user('reconciled'));
    return json({ items: [], next_cursor: null });
  }) });
  await assert.rejects(identity.login({ username: 'a', password: 'p' }),
    (error: unknown) => error instanceof ApiError && error.outcome === 'unknown');
  assert.equal((await identity.restore())?.id, 'reconciled');
  assert.equal(refreshes, 1);
});
test('protected 401 invalidates once and never retries a mutation', async () => {
  let losses = 0, mutations = 0;
  const identity = createLiveIdentity({ onLost() { losses++; }, fetcher: fetcher(path => {
    if (path.endsWith('/login')) return access('first', 600);
    if (path.endsWith('/me')) return json(user());
    mutations++; return json({ error: { code: 'UNAUTHENTICATED', message: 'Expired' } }, 401);
  }) });
  await identity.login({ username: 'a', password: 'p' });
  await assert.rejects(identity.createRequest('EXPORT'), (error: unknown) => error instanceof ApiError && error.status === 401);
  assert.equal(losses, 1); assert.equal(mutations, 1); assert.equal(await identity.restore(), null);
});
test('logout completion does not clear a newer login', async () => {
  const gate = pending<Response>(); let logins = 0;
  const identity = createLiveIdentity({ onLost() {}, fetcher: fetcher((path, init) => {
    if (path.endsWith('/login')) return access(++logins === 1 ? 'old' : 'new', 600);
    if (path.endsWith('/logout')) return gate.promise;
    if (path.endsWith('/me')) return json(user(new Headers(init.headers).get('Authorization') === 'Bearer new' ? 'new' : 'old'));
    return json({ items: [], next_cursor: null });
  }) });
  await identity.login({ username: 'old', password: 'p' }); const logout = identity.logout(); await tick();
  const login = identity.login({ username: 'new', password: 'p' }); gate.resolve(new Response(null, { status: 204 }));
  await logout; assert.equal((await login).id, 'new'); assert.equal((await identity.restore())?.id, 'new');
});
test('an acknowledged mutation from an old session reports unknown instead of updating the next actor', async () => {
  const gate = pending<Response>(); let logins = 0;
  const identity = createLiveIdentity({ onLost() {}, fetcher: fetcher((path, init) => {
    if (path.endsWith('/login')) return access(++logins === 1 ? 'old' : 'new', 600);
    if (path.endsWith('/me') && init.method === 'PATCH') return gate.promise;
    return json(user('new'));
  }) });
  await identity.login({ username: 'old', password: 'p' }); const mutation = identity.updateProfile('Old edit'); await tick();
  await identity.login({ username: 'new', password: 'p' }); gate.resolve(json(user('old')));
  await assert.rejects(mutation, (error: unknown) => error instanceof ApiError && error.code === 'SESSION_CHANGED' && error.outcome === 'unknown');
});
test('session loss and same-actor relogin cannot resurrect delayed practice drafts', () => {
  draftStore.bindActor('actor'); const epoch = draftStore.epoch;
  const draft: ScopedPracticeAttemptDraft = { pinnedContext: { actorId: 'actor', classId: 'class', practiceId: 'practice', attemptId: 'attempt', version: 1 }, lastVisitedQuestionIndex: 1, localAnswers: {}, confirmedAnswers: {}, checkedFeedbacks: {}, checkedAnswerSnapshots: {}, ackStatus: 'pending', updatedAt: 0 };
  setAttemptDraft(draft, epoch); assert.ok(getAttemptDraft('actor', 'class', 'practice', 'attempt', 1));
  draftStore.bindActor(null); setAttemptDraft(draft, epoch); assert.equal(getAttemptDraft('actor', 'class', 'practice', 'attempt', 1), null);
  draftStore.bindActor('actor'); setAttemptDraft(draft, epoch); assert.equal(getAttemptDraft('actor', 'class', 'practice', 'attempt', 1), null);
  setAttemptDraft(draft, draftStore.epoch); assert.ok(getAttemptDraft('actor', 'class', 'practice', 'attempt', 1));
});
