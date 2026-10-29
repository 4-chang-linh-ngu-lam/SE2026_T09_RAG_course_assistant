import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveCore } from '../src/lib/data/live-core';
import { createLiveIdentitySession } from '../src/lib/data/live-identity';

const actorId = '00000000-0000-4000-8000-000000000001';
const classId = '00000000-0000-4000-8000-000000000002';
const postId = '00000000-0000-4000-8000-000000000003';

function harness() {
  const calls: { path: string; method: string; authorization: string | null }[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'https://web.example');
    const method = String(init?.method ?? 'GET');
    const headers = new Headers(init?.headers);
    calls.push({ path: `${url.pathname}${url.search}`, method, authorization: headers.get('Authorization') });
    if (url.pathname === '/api/v1/auth/login') return Response.json({ token_type: 'bearer', access_token: 'access-test', expires_in: 900 });
    if (url.pathname === '/api/v1/users/me') return Response.json({ id: actorId, email: 'student@example.com', username: null, school_id: '00000000-0000-4000-8000-000000000004', display_name: 'Học sinh', roles: ['STUDENT'], status: 'ACTIVE' });
    if (url.pathname === '/api/v1/classes') return Response.json({ items: [{ id: classId, school_id: '00000000-0000-4000-8000-000000000004', academic_year_id: '00000000-0000-4000-8000-000000000005', semester_id: '00000000-0000-4000-8000-000000000006', course_id: '00000000-0000-4000-8000-000000000007', homeroom_class_id: null, name: 'Toán 9A', grade_level: 9, enrollment_mode: 'AUTO', status: 'ACTIVE', version: 1 }], next_cursor: null });
    if (url.pathname === `/api/v1/classes/${classId}`) return Response.json({ id: classId, school_id: '00000000-0000-4000-8000-000000000004', academic_year_id: '00000000-0000-4000-8000-000000000005', semester_id: '00000000-0000-4000-8000-000000000006', course_id: '00000000-0000-4000-8000-000000000007', homeroom_class_id: null, name: 'Toán 9A', grade_level: 9, enrollment_mode: 'AUTO', status: 'ACTIVE', version: 1 });
    if (url.pathname === `/api/v1/classes/${classId}/posts`) return Response.json({ items: [{ id: postId, class_id: classId, author: { id: actorId, display_name: 'Học sinh' }, body: 'Bài viết thật từ Core', created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-28T10:00:00Z' }], next_cursor: null });
    if (url.pathname === `/api/v1/classes/${classId}/posts/${postId}/comments`) return Response.json({ items: [{ id: '00000000-0000-4000-8000-000000000008', post_id: postId, author: { id: actorId, display_name: 'Học sinh' }, body: 'Bình luận Core', created_at: '2026-10-28T10:01:00Z', updated_at: '2026-10-28T10:01:00Z' }], next_cursor: null });
    if (url.pathname === '/api/v1/notifications') return Response.json({ items: [], unread_count: 7, next_cursor: null });
    if (url.pathname === '/api/v1/notifications/read-all' && method === 'POST') return new Response(null, { status: 204 });
    return Response.json({ error: { code: 'NOT_FOUND', message: 'not found' } }, { status: 404 });
  }) as typeof fetch;
  const session = createLiveIdentitySession({ fetcher, onLost() {} });
  return { session, core: createLiveCore(session), calls };
}

test('live workspace decodes class feed and comments from documented Core operations', async () => {
  const { session, core, calls } = harness();
  await session.identity.login({ email: 'student@example.com', password: 'test-password' });
  const result = await core.workspace.load('s.feed', { classId });
  assert.equal(result.kind, 'ready');
  if (result.kind !== 'ready') return;
  assert.equal(result.classSummary?.name, 'Toán 9A');
  assert.equal(result.feedPosts?.[0].content, 'Bài viết thật từ Core');
  assert.equal(result.feedPosts?.[0].authorRole, undefined);
  assert.equal(result.feedPosts?.[0].canEdit, true);
  assert.equal(result.feedPosts?.[0].comments[0].content, 'Bình luận Core');
  assert.ok(calls.every(call => call.method === 'POST' || call.authorization === 'Bearer access-test'));
});

test('teacher workspaces limit mixed Admin/Lecturer accounts to currently assigned classes', async () => {
  const assignedClassId = classId;
  const unassignedClassId = '00000000-0000-4000-8000-000000000009';
  const socialClassIds: string[] = [];
  const actor = { id: actorId, email: 'admin@example.com', username: null, school_id: '00000000-0000-4000-8000-000000000004', display_name: 'Admin & teacher', roles: ['ADMIN', 'LECTURER'], status: 'ACTIVE' };
  const classRow = (id: string, name: string, teachingRole: 'PRIMARY' | 'ASSISTING' | null) => ({
    id, school_id: actor.school_id, academic_year_id: '00000000-0000-4000-8000-000000000005', semester_id: '00000000-0000-4000-8000-000000000006', course_id: '00000000-0000-4000-8000-000000000007', homeroom_class_id: null, name, grade_level: 9, enrollment_mode: 'AUTO', status: 'ACTIVE', version: 1, teaching_role: teachingRole,
  });
  const fetcher = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'https://web.example');
    if (url.pathname === '/api/v1/auth/login') return Response.json({ token_type: 'bearer', access_token: 'access-test', expires_in: 900 });
    if (url.pathname === '/api/v1/users/me') return Response.json(actor);
    if (url.pathname === '/api/v1/classes') return Response.json({ items: [classRow(assignedClassId, 'Toán 9A', 'PRIMARY'), classRow(unassignedClassId, 'Văn 9B', null)], next_cursor: null });
    if (url.pathname.endsWith('/calendar') || url.pathname.endsWith('/posts')) {
      const pathClassId = url.pathname.split('/')[4];
      socialClassIds.push(pathClassId);
      if (pathClassId === unassignedClassId) return Response.json({ error: { code: 'NOT_FOUND', message: 'not found' } }, { status: 404 });
      return Response.json({ items: [], next_cursor: null });
    }
    return Response.json({ error: { code: 'NOT_FOUND', message: 'not found' } }, { status: 404 });
  }) as typeof fetch;
  const session = createLiveIdentitySession({ fetcher, onLost() {} });
  await session.identity.login({ email: 'admin@example.com', password: 'test-password' });
  const core = createLiveCore(session);

  const home = await core.workspace.load('t.home', {});
  assert.equal(home.kind, 'ready');
  if (home.kind !== 'ready') return;
  assert.deepEqual(home.classes?.map(klass => klass.id), [assignedClassId]);
  assert.deepEqual(home.teacherHome?.assignedClasses.map(klass => klass.id), [assignedClassId]);
  assert.deepEqual(socialClassIds, [assignedClassId, assignedClassId]);

  const list = await core.workspace.load('t.classes', {});
  assert.equal(list.kind, 'ready');
  if (list.kind === 'ready') assert.deepEqual(list.classes?.map(klass => klass.id), [assignedClassId]);
});

test('live notification workspace preserves Core unread count and read-all uses the real endpoint', async () => {
  const { session, core, calls } = harness();
  await session.identity.login({ email: 'student@example.com', password: 'test-password' });
  const result = await core.workspace.load('account.notifications', {});
  assert.equal(result.kind, 'ready');
  if (result.kind !== 'ready') return;
  assert.equal(result.notificationUnreadCount, 7);
  await core.notifications.markAllAsRead();
  assert.ok(calls.some(call => call.path.startsWith('/api/v1/notifications/read-all') && call.method === 'POST'));
});

test('live notification workspace consumes all Core pages and retains the total unread count', async () => {
  const pages: string[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'https://web.example');
    const method = String(init?.method ?? 'GET');
    const headers = new Headers(init?.headers);
    if (url.pathname === '/api/v1/auth/login') return Response.json({ token_type: 'bearer', access_token: 'access-test', expires_in: 900 });
    if (url.pathname === '/api/v1/users/me') return Response.json({ id: actorId, email: 'student@example.com', username: null, school_id: '00000000-0000-4000-8000-000000000004', display_name: 'Học sinh', roles: ['STUDENT'], status: 'ACTIVE' });
    if (url.pathname === '/api/v1/classes') return Response.json({ items: [], next_cursor: null });
    if (url.pathname === '/api/v1/notifications') {
      const cursor = url.searchParams.get('cursor') ?? '';
      pages.push(cursor);
      const item = (id: string) => ({ id, type: 'UNKNOWN_EVENT', payload_json: {}, read: false, created_at: '2026-10-29T10:00:00Z' });
      return cursor
        ? Response.json({ items: [item('00000000-0000-4000-8000-000000000013')], unread_count: 3, next_cursor: null })
        : Response.json({ items: [item('00000000-0000-4000-8000-000000000014')], unread_count: 3, next_cursor: 'cursor-2' });
    }
    if (method === 'POST') return new Response(null, { status: 204 });
    return Response.json({ error: { code: 'NOT_FOUND', message: 'not found' } }, { status: 404 });
  }) as typeof fetch;
  const session = createLiveIdentitySession({ fetcher, onLost() {} });
  await session.identity.login({ email: 'student@example.com', password: 'test-password' });
  const core = createLiveCore(session);
  const result = await core.workspace.load('account.notifications', {});
  assert.equal(result.kind, 'ready');
  if (result.kind !== 'ready') return;
  assert.equal(result.notifications?.length, 2);
  assert.equal(result.notificationUnreadCount, 3);
  assert.deepEqual(pages, ['', 'cursor-2']);
});
