import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveAccounts } from '../src/lib/data/live-accounts';
import { createLiveClassroomAdminPort } from '../src/lib/data/live-classroom-admin';
import { createLiveIdentitySession } from '../src/lib/data/live-identity';
import { createLiveIntelligencePort } from '../src/lib/data/live-intelligence';

const ids = {
  admin: '00000000-0000-4000-8000-000000000001',
  teacher: '00000000-0000-4000-8000-000000000002',
  student: '00000000-0000-4000-8000-000000000003',
  student2: '00000000-0000-4000-8000-000000000004',
  course: '00000000-0000-4000-8000-000000000005',
  year: '00000000-0000-4000-8000-000000000006',
  semester: '00000000-0000-4000-8000-000000000007',
  homeroom: '00000000-0000-4000-8000-000000000008',
  klass: '00000000-0000-4000-8000-000000000009',
};

function user(id: string, roles: string[], username: string | null, displayName: string, status = 'ACTIVE') {
  return {
    id, email: roles.includes('STUDENT') ? null : `${displayName.toLowerCase().replaceAll(' ', '.')}@example.com`,
    username, school_id: '00000000-0000-4000-8000-000000000010', display_name: displayName,
    status, roles, revision: 1, created_at: '2026-10-01T00:00:00Z', email_verified: true,
    activation_required: false, last_admin: roles.includes('ADMIN'), invitation_expires_at: null,
    invitation_delivery_status: null,
  };
}

function harness(options: { loseImportResponse?: boolean } = {}) {
  const calls: { path: string; method: string; body?: unknown; headers: Headers }[] = [];
  let importStatus: 'PREVIEW' | 'COMPLETED' = 'PREVIEW';
  let confirmCalls = 0;
  const actor = { id: ids.admin, email: 'admin@example.com', username: null, school_id: '00000000-0000-4000-8000-000000000010', display_name: 'Admin', roles: ['ADMIN'], status: 'ACTIVE' };
  const klass = { id: ids.klass, school_id: actor.school_id, academic_year_id: ids.year, semester_id: ids.semester, course_id: ids.course, homeroom_class_id: ids.homeroom, name: 'Toán 9A', grade_level: 9, enrollment_mode: 'MANUAL', status: 'ACTIVE', version: 5, teaching_role: null };
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'https://web.example');
    const path = url.pathname;
    const method = String(init?.method ?? 'GET');
    const headers = new Headers(init?.headers);
    let body: unknown;
    if (init?.body) body = JSON.parse(String(init.body));
    calls.push({ path, method, body, headers });
    if (path === '/api/v1/auth/login') return Response.json({ token_type: 'bearer', access_token: 'access-test', expires_in: 900 });
    if (path === '/api/v1/users/me') return Response.json(actor);
    if (path === '/api/v1/admin/users') return Response.json({ items: [user(ids.admin, ['ADMIN'], null, 'Admin'), user(ids.teacher, ['LECTURER'], null, 'Teacher'), user(ids.student, ['STUDENT'], 'student.one', 'Student One'), user(ids.student2, ['STUDENT'], 'student.two', 'Student Two', 'LOCKED')], next_cursor: null });
    if (path === '/api/v1/admin/audit-events') return Response.json({ items: [{ id: '00000000-0000-4000-8000-000000000030', actor_id: ids.admin, action: 'ADMIN_SET_MANUAL_ROSTER', target_type: 'CLASS', target_id: ids.klass, correlation_id: '00000000-0000-4000-8000-000000000031', metadata_json: { reason_code: 'USER_REQUEST' }, occurred_at: '2026-10-29T01:00:00Z' }], next_cursor: 'opaque-cursor' });
    if (path === '/api/v1/admin/catalog') return Response.json({ courses: [{ id: ids.course, code: 'MATH', name: 'Toán', school_id: actor.school_id }], academic_years: [{ id: ids.year, school_id: actor.school_id, label: '2026-2027' }], semesters: [{ id: ids.semester, academic_year_id: ids.year, name: '1' }], homerooms: [{ id: ids.homeroom, school_id: actor.school_id, academic_year_id: ids.year, name: '9A', grade_level: 9, roster_version: 3, student_count: 1 }], grades: [9] });
    if (path === '/api/v1/classes') return Response.json({ items: [klass], next_cursor: null });
    if (path === `/api/v1/admin/classes/${ids.klass}/management`) return Response.json({ subject_class: klass, teaching_assignments: [{ id: '00000000-0000-4000-8000-000000000011', class_id: ids.klass, lecturer_id: ids.teacher, role: 'PRIMARY', assigned_at: '2026-10-01T00:00:00Z', ended_at: null }], members: [{ id: '00000000-0000-4000-8000-000000000012', class_id: ids.klass, student_id: ids.student, source: 'MANUAL', status: 'ACTIVE', joined_at: '2026-10-01T00:00:00Z', ended_at: null }] });
    if (path === `/api/v1/admin/homeroom-classes/${ids.homeroom}/roster`) return Response.json({ homeroom_class_id: ids.homeroom, student_ids: [ids.student, ids.student2], roster_version: 3 });
    if (path === `/api/v1/admin/classes/${ids.klass}/members` && method === 'PUT') return Response.json({ subject_class: klass, teaching_assignments: [], members: [] });
    if (path === `/api/v1/admin/homeroom-classes/${ids.homeroom}/roster` && method === 'PUT') return Response.json({ homeroom_class_id: ids.homeroom, student_ids: (body as { student_ids: string[] }).student_ids, roster_version: 4 });
    if (path === '/api/v1/admin/students/imports/preview') return Response.json({ valid: true, preview_id: '00000000-0000-4000-8000-000000000020', expires_at: '2026-10-29T01:00:00Z', items: [{ row: 2, action: 'CREATE', username: 'new.student', user_id: null }], errors: [] });
    if (path === '/api/v1/admin/students/imports/confirm' && method === 'POST') {
      confirmCalls++;
      importStatus = 'COMPLETED';
      if (options.loseImportResponse) throw new TypeError('connection dropped after commit');
      return Response.json({ preview_id: '00000000-0000-4000-8000-000000000020', status: 'COMPLETED', replayed: false, items: [{ row: 2, outcome: 'CREATED', student: { id: ids.student2, username: 'new.student' }, code: 'one-time-activation-code', expires_at: '2026-10-30T00:00:00Z' }] });
    }
    if (path === '/api/v1/admin/students/imports/00000000-0000-4000-8000-000000000020') return Response.json({ preview_id: '00000000-0000-4000-8000-000000000020', status: importStatus, expires_at: importStatus === 'PREVIEW' ? '2026-10-29T01:00:00Z' : null, items: importStatus === 'COMPLETED' ? [{ row: 2, outcome: 'CREATED', user_id: ids.student2 }] : [{ row: 2, action: 'CREATE', username: 'new.student', user_id: null }] });
    return Response.json({ error: { code: 'NOT_FOUND', message: 'not found' } }, { status: 404 });
  }) as typeof fetch;
  const session = createLiveIdentitySession({ fetcher, onLost() {} });
  return { session, calls, get confirmCalls() { return confirmCalls; } };
}

test('live Classroom Admin loads Core DTOs and atomically replaces a MANUAL roster with revision guard', async () => {
  const h = harness();
  await h.session.identity.login({ email: 'admin@example.com', password: 'test-password' });
  const classroom = createLiveClassroomAdminPort(h.session);
  const loaded = await classroom.load('a.enrollment', { classId: ids.klass });
  assert.equal(loaded.subjectClass?.summary.name, 'Toán 9A');
  assert.equal(loaded.subjectClass?.summary.studentCount, 1);
  assert.deepEqual(loaded.subjectClass?.members.map(item => item.userId), [ids.student]);
  assert.equal(loaded.students.find(item => item.id === ids.student2)?.status, 'LOCKED');
  assert.equal(loaded.historyAvailable, false);
  const preview = await classroom.previewEnrollment({ classId: ids.klass, revision: 5, mode: 'MANUAL', studentIds: [ids.student, ids.student2] });
  assert.deepEqual(preview.addedIds, [ids.student2]);
  const applied = await classroom.confirmEnrollment({ previewId: preview.id, reason: 'ADMIN_INTERVENTION' });
  assert.equal(applied.status, 'APPLIED');
  const write = h.calls.find(call => call.path === `/api/v1/admin/classes/${ids.klass}/members` && call.method === 'PUT');
  assert.deepEqual(write?.body, { student_ids: [ids.student, ids.student2], expected_class_version: 5 });
  assert.equal(write?.headers.get('X-Admin-Reason'), 'ADMIN_INTERVENTION');
  assert.ok(write?.headers.get('Idempotency-Key'));
});

test('live homeroom roster preview confirms with Core roster version', async () => {
  const h = harness();
  await h.session.identity.login({ email: 'admin@example.com', password: 'test-password' });
  const classroom = createLiveClassroomAdminPort(h.session);
  const loaded = await classroom.load('a.homeroom', { homeroomId: ids.homeroom });
  const room = loaded.homeroom!;
  const preview = await classroom.previewHomeroomRoster({ homeroomId: room.id, revision: room.revision, studentIds: [ids.student] });
  assert.deepEqual(preview.endedIds, [ids.student2]);
  await classroom.confirmHomeroomRoster({ previewId: preview.id, reason: 'USER_REQUEST' });
  const write = h.calls.find(call => call.path === `/api/v1/admin/homeroom-classes/${ids.homeroom}/roster` && call.method === 'PUT');
  assert.deepEqual(write?.body, { student_ids: [ids.student], expected_roster_version: 3 });
  assert.equal(write?.headers.get('X-Admin-Reason'), 'USER_REQUEST');
});

test('live Admin audit reads Core pages without enabling deferred data-request fulfillment', async () => {
  const h = harness();
  await h.session.identity.login({ email: 'admin@example.com', password: 'test-password' });
  const intelligence = createLiveIntelligencePort(h.session);
  const audit = await intelligence.load('a.audit', {}, {});
  assert.equal(audit.kind, 'audit');
  if (audit.kind !== 'audit') return;
  assert.equal(audit.items[0].action, 'ADMIN_SET_MANUAL_ROSTER');
  assert.equal(audit.items[0].actorName, 'Quản trị viên');
  assert.equal(audit.items[0].reason, 'USER_REQUEST');
  assert.equal(audit.nextCursor, 'opaque-cursor');
  await assert.rejects(() => intelligence.load('a.dataRequests', {}, {}));
});

test('live import consumes only explicit columns and activation code is never restored from adapter cache', async () => {
  const h = harness();
  await h.session.identity.login({ email: 'admin@example.com', password: 'test-password' });
  const accounts = createLiveAccounts(h.session);
  const file = { filename: 'students.csv', format: 'CSV' as const, headers: ['user', 'name'], contentBase64: 'YQ==', rows: [{ rowNumber: 2, cells: ['new.student', 'New Student'] }] };
  const job = await accounts.previewImport({ file, mapping: { username: 0, displayName: 1 } });
  const previewRequest = h.calls.find(call => call.path === '/api/v1/admin/students/imports/preview');
  assert.deepEqual(previewRequest?.body, { format: 'CSV', content_base64: 'YQ==', username_header: 'user', display_name_header: 'name', user_id_header: null });
  const visible = await accounts.load('a.import', { importId: job.id });
  assert.equal(visible.importJob?.canConfirm, true);
  const result = await accounts.confirmImport({ importId: job.id, revision: 1, reason: 'ADMIN_INTERVENTION' });
  assert.equal(result.rows[0].activationCode, 'one-time-activation-code');
  assert.equal(result.createdCount, 1);
  const reloaded = await accounts.load('a.import', { importId: job.id });
  assert.equal(reloaded.importJob?.rows[0].activationCode, undefined);
});

test('unknown import outcome is reconciled with a read-only status endpoint, never re-confirmed', async () => {
  const h = harness({ loseImportResponse: true });
  await h.session.identity.login({ email: 'admin@example.com', password: 'test-password' });
  const accounts = createLiveAccounts(h.session);
  const file = { filename: 'students.csv', format: 'CSV' as const, headers: ['username'], contentBase64: 'YQ==', rows: [{ rowNumber: 2, cells: ['new.student'] }] };
  const job = await accounts.previewImport({ file, mapping: { username: 0, displayName: null } });
  await assert.rejects(() => accounts.confirmImport({ importId: job.id, revision: 1, reason: 'ADMIN_INTERVENTION' }));
  const reconciled = await accounts.reconcileImport(job.id);
  assert.equal(reconciled.status, 'COMPLETED');
  assert.equal(reconciled.replayed, true);
  assert.equal(reconciled.rows[0].activationCode, undefined);
  assert.equal(h.confirmCalls, 1);
  assert.ok(h.calls.some(call => call.path.endsWith('/admin/students/imports/00000000-0000-4000-8000-000000000020') && call.method === 'GET'));
});
