import { createLiveIdentity } from '../src/lib/data/live-identity';
import test from 'node:test';
import assert from 'node:assert/strict';
import { adapter as mockAdapter } from '../dev/mocks/adapter';
import { adapter as liveAdapter } from '../src/lib/data/live';
import { ApiError } from '../src/lib/api/errors';
import { matchRoute, canOpenRoute, safeReturnTo } from '../src/lib/navigation';
import { getRoute } from '../src/config/routes';
import {
  getDaysInMonth,
  getStartDayOfWeek,
  generateCalendarGrid,
  generateWeekDays,
  getInitialCalendarState,
  getRoleAwareEventHref,
} from '../src/lib/calendar';
import { inspectSource } from '../scripts/boundary-policy.mjs';

const STUDENT_LOGIN = { username: 'minh.anh10a1', password: 'ValidPassword123!' };
const TEACHER_LOGIN = { email: 'ha.nguyen@lumi.example', password: 'ValidPassword123!' };

test('staff invitation uses reset contract; approved Social writes require a confirmed session', async () => {
  const sent: {url: string; method: string | undefined; body: unknown}[] = [];
  const identity = createLiveIdentity({ fetcher: (async (url, init) => { sent.push({ url: String(url), method: init?.method, body: JSON.parse(String(init?.body)) }); return new Response(null, { status: 204 }); }) as typeof fetch });
  await identity.acceptInvitation('token-123', 'NewPass123456!');
  assert.deepEqual(sent, [{ url: '/api/v1/auth/password/reset', method: 'POST', body: { token: 'token-123', new_password: 'NewPass123456!' } }]);
  await assert.rejects(
    () => liveAdapter.social.createPost('class-1', 'Test content'),
    (err: unknown) => err instanceof ApiError && err.status === 401 && err.code === 'SESSION_UNCONFIRMED'
  );
  await assert.rejects(
    () => liveAdapter.social.updatePost('class-1', 'post-1', 'Updated content'),
    (err: unknown) => err instanceof ApiError && err.status === 401 && err.code === 'SESSION_UNCONFIRMED'
  );
  await assert.rejects(
    () => liveAdapter.calendar.createEvent({
      classId:'00000000-0000-4000-8000-000000000001',
      title: 'Họp phụ huynh',
      category: 'CLASS',
      date: '2026-10-20',
      start: '2026-10-20T08:00:00Z',
      end:'2026-10-20T09:00:00Z',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 401 && err.code === 'SESSION_UNCONFIRMED'
  );
});

test('preview adapter: actor authentication and class-scoped permissions for feed', async () => {
  // Login as student
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Student can post to enrolled active class 101
  const post = await mockAdapter.social.createPost(
    '00000000-0000-4000-8000-000000000101',
    'Em thưa cô phần bài tập này làm trên giấy hay nộp trực tuyến ạ?'
  );
  assert.ok(post.id);
  assert.equal(post.authorRole, 'STUDENT');

  // Author can update own post
  const updated = await mockAdapter.social.updatePost(
    '00000000-0000-4000-8000-000000000101',
    post.id,
    'Em thưa cô câu hỏi đã được sửa nội dung rõ hơn.'
  );
  assert.equal(updated.content, 'Em thưa cô câu hỏi đã được sửa nội dung rõ hơn.');

  // Student cannot post to un-enrolled class 102
  await assert.rejects(
    () => mockAdapter.social.createPost('00000000-0000-4000-8000-000000000102', 'Xin chào'),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Student cannot post to archived class 199
  await assert.rejects(
    () => mockAdapter.social.createPost('00000000-0000-4000-8000-000000000199', 'Hỏi bài lớp cũ'),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Empty post rejected
  await assert.rejects(
    () => mockAdapter.social.createPost('00000000-0000-4000-8000-000000000101', '   '),
    (err: unknown) => err instanceof ApiError && err.code === 'VALIDATION_ERROR'
  );
});

test('preview adapter: calendar role checks and read-only deadline immutability', async () => {
  // Student cannot create calendar events
  await mockAdapter.identity.login(STUDENT_LOGIN);
  await assert.rejects(
    () => mockAdapter.calendar.createEvent({
      title: 'Tự học',
      category: 'CLASS',
      date: '2026-10-21',
      start: '2026-10-21T07:00:00Z',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Switch to teacher
  await mockAdapter.identity.login(TEACHER_LOGIN);

  // Teacher can create calendar event for assigned class
  const created = await mockAdapter.calendar.createEvent({
    classId: '00000000-0000-4000-8000-000000000101',
    title: 'Tiết thực hành đồ thị Parabol',
    category: 'CLASS',
    date: '2026-10-22',
    start: '2026-10-22T07:00:00Z',
    end: '2026-10-22T09:15:00Z',
  });
  assert.ok(created.id);

  // Invalid time range (start >= end) rejected
  await assert.rejects(
    () => mockAdapter.calendar.createEvent({
      classId: '00000000-0000-4000-8000-000000000101',
      title: 'Lỗi giờ',
      category: 'CLASS',
      date: '2026-10-22',
      start: '2026-10-22T10:00:00Z',
      end: '2026-10-22T09:00:00Z',
    }),
    (err: unknown) => err instanceof ApiError && err.code === 'VALIDATION_ERROR'
  );

  // Read-only learning deadline cannot be updated or deleted
  await assert.rejects(
    () => mockAdapter.calendar.updateEvent('00000000-0000-4000-8000-000000000101', 'cal-2', { title: 'Đổi hạn nộp' }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
  await assert.rejects(
    () => mockAdapter.calendar.deleteEvent('00000000-0000-4000-8000-000000000101', 'cal-2'),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
});

test('preview adapter: notification recipient isolation and mark-as-read', async () => {
  // Login as student
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const studentData = await mockAdapter.workspace.load('account.notifications', {});
  assert.equal(studentData.kind, 'ready');
  if (studentData.kind === 'ready') {
    // All returned notifications belong to the current student
    const notifs = studentData.notifications ?? [];
    assert.ok(notifs.length > 0);
    assert.ok(notifs.every(n => n.userId === '00000000-0000-4000-8000-000000000011'));
    // Ensure foreign notification is not in student's notifications list
    assert.ok(!notifs.some(n => n.id === 'notif-foreign-teacher'));
  }

  // Student cannot mark another user's existing notification as read (throws 403 FORBIDDEN)
  await assert.rejects(
    () => mockAdapter.notifications.markAsRead('notif-foreign-teacher'),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Unknown notification ID explicitly rejects with 404 NOT_FOUND
  await assert.rejects(
    () => mockAdapter.notifications.markAsRead('notif-foreign-id'),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );

  // markAllAsRead only marks current student's notifications, leaves foreign notification unread
  await mockAdapter.notifications.markAllAsRead();

  // Login as teacher and verify foreign notification is still unread
  await mockAdapter.identity.login(TEACHER_LOGIN);
  const teacherData = await mockAdapter.workspace.load('account.notifications', {});
  assert.equal(teacherData.kind, 'ready');
  if (teacherData.kind === 'ready') {
    const foreignNotif = (teacherData.notifications ?? []).find(n => n.id === 'notif-foreign-teacher');
    assert.ok(foreignNotif, 'Teacher should have foreign notification');
    assert.equal(foreignNotif?.isRead, false, 'Foreign notification must remain unread after student markAllAsRead');
  }
});

test('preview adapter: class overview targets are scoped strictly to the requested class', async () => {
  await mockAdapter.identity.login(STUDENT_LOGIN);

  const overview101 = await mockAdapter.workspace.load('s.overview', {
    classId: '00000000-0000-4000-8000-000000000101',
  });
  assert.equal(overview101.kind, 'ready');
  if (overview101.kind === 'ready') {
    const overview = overview101.classOverview;
    assert.ok(overview);
    assert.equal(overview?.summary.id, '00000000-0000-4000-8000-000000000101');
    assert.ok((overview?.recentMaterials?.length ?? 0) > 0);
    // Ensure all materials and activities point to class 101, not a leaked hardcoded class ID
    for (const mat of overview?.recentMaterials ?? []) {
      assert.ok(mat.href.includes('00000000-0000-4000-8000-000000000101'));
    }
    for (const act of overview?.upcomingActivities ?? []) {
      assert.ok(act.href.includes('00000000-0000-4000-8000-000000000101'));
    }
  }

  // Student accessing active Literature class 103 gets Literature-scoped overview without Math materials leak
  const overview103 = await mockAdapter.workspace.load('s.overview', {
    classId: '00000000-0000-4000-8000-000000000103',
  });
  assert.equal(overview103.kind, 'ready');
  if (overview103.kind === 'ready') {
    const overview = overview103.classOverview;
    assert.ok(overview);
    assert.equal(overview?.summary.id, '00000000-0000-4000-8000-000000000103');
    // Math materials must NOT leak into Literature class
    assert.equal(overview?.recentMaterials?.length, 0);
    assert.equal(overview?.upcomingActivities?.length, 0);
  }

  // Student accessing un-enrolled class 102 returns unavailable
  const overview102 = await mockAdapter.workspace.load('s.overview', {
    classId: '00000000-0000-4000-8000-000000000102',
  });
  assert.equal(overview102.kind, 'unavailable');

  // Teacher accessing assisting class 102 gets 10A2 overview without 10A1 Math materials leak
  await mockAdapter.identity.login(TEACHER_LOGIN);
  const teacher102 = await mockAdapter.workspace.load('t.overview', {
    classId: '00000000-0000-4000-8000-000000000102',
  });
  assert.equal(teacher102.kind, 'ready');
  if (teacher102.kind === 'ready') {
    assert.equal(teacher102.classOverview?.summary.id, '00000000-0000-4000-8000-000000000102');
    const documents102 = await mockAdapter.workspace.load('t.documents', { classId: '00000000-0000-4000-8000-000000000102' });
    assert.equal(documents102.kind, 'ready');
    if (documents102.kind === 'ready') assert.deepEqual(teacher102.classOverview?.recentMaterials.map(item => item.id).sort(), documents102.classDocuments?.filter(item => item.processingStatus === 'READY').map(item => item.id).sort());
    assert.ok(teacher102.classOverview?.recentMaterials.every(item => item.href.includes('00000000-0000-4000-8000-000000000102')));
  }

  // Student accessing active class in history returns unavailable
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const historyActive = await mockAdapter.workspace.load('s.history', {
    classId: '00000000-0000-4000-8000-000000000101',
  });
  assert.equal(historyActive.kind, 'unavailable');

  // Student accessing valid archived history class 199 succeeds
  const history199 = await mockAdapter.workspace.load('s.history', {
    classId: '00000000-0000-4000-8000-000000000199',
  });
  assert.equal(history199.kind, 'ready');
});

test('navigation: role matching and safe return guard', () => {
  const loginRoute = getRoute('auth.login');
  assert.ok(canOpenRoute(loginRoute, []));
  assert.ok(canOpenRoute(loginRoute, ['STUDENT']));

  const studentHomeRoute = getRoute('s.home');
  assert.ok(canOpenRoute(studentHomeRoute, ['STUDENT']));
  assert.ok(!canOpenRoute(studentHomeRoute, ['LECTURER']));

  const teacherHomeRoute = getRoute('t.home');
  assert.ok(canOpenRoute(teacherHomeRoute, ['LECTURER']));
  assert.ok(!canOpenRoute(teacherHomeRoute, ['STUDENT']));

  // safeReturnTo rejects external and protocol-relative URLs
  assert.equal(safeReturnTo('https://malicious.example.com', ['STUDENT'], '/student'), '/student');
  assert.equal(safeReturnTo('//malicious.example.com', ['STUDENT'], '/student'), '/student');
  assert.equal(safeReturnTo('javascript:alert(1)', ['STUDENT'], '/student'), '/student');
  assert.equal(safeReturnTo('/student/classes', ['STUDENT'], '/student'), '/student/classes');
});

test('calendar helper: date calculations for leap year, 6-week month, rollover, and title/cell agreement', () => {
  // February leap vs non-leap year
  assert.equal(getDaysInMonth(2024, 2), 29); // 2024 is leap
  assert.equal(getDaysInMonth(2025, 2), 28); // 2025 is non-leap
  assert.equal(getDaysInMonth(2026, 2), 28); // 2026 is non-leap

  // Weekday alignment: Oct 1, 2026 is Thursday (Monday index 3)
  assert.equal(getStartDayOfWeek(2026, 10), 3);

  // 6-week month: August 2026 has 31 days and starts on Saturday (Monday index 5)
  // 5 leading days + 31 days = 36 slots -> requires 42 cells (6 full weeks)
  assert.equal(getStartDayOfWeek(2026, 8), 5);
  const aug2026Grid = generateCalendarGrid(2026, 8, '2026-08-15');
  assert.equal(aug2026Grid.length, 42);
  assert.equal(aug2026Grid[0].dateString, '2026-07-27');
  assert.equal(aug2026Grid[0].inMonth, false);
  assert.equal(aug2026Grid[5].dateString, '2026-08-01');
  assert.equal(aug2026Grid[5].inMonth, true);
  assert.equal(aug2026Grid[35].dateString, '2026-08-31');
  assert.equal(aug2026Grid[35].inMonth, true);
  assert.equal(aug2026Grid[41].dateString, '2026-09-06');
  assert.equal(aug2026Grid[41].inMonth, false);

  // Year rollover: December 2026 grid rolls into January 2027
  const dec2026Grid = generateCalendarGrid(2026, 12);
  const trailingJan = dec2026Grid.filter(c => c.dateString.startsWith('2027-01'));
  assert.ok(trailingJan.length > 0);
  assert.equal(trailingJan[0].dateString, '2027-01-01');

  // Year rollover: January 2027 grid rolls from December 2026
  const jan2027Grid = generateCalendarGrid(2027, 1);
  const leadingDec = jan2027Grid.filter(c => c.dateString.startsWith('2026-12'));
  assert.ok(leadingDec.length > 0);

  // Title / cell agreement: October 2026
  const oct2026Grid = generateCalendarGrid(2026, 10, '2026-10-16');
  const inMonthCells = oct2026Grid.filter(c => c.inMonth);
  assert.equal(inMonthCells.length, 31);
  for (let i = 0; i < 31; i++) {
    const expectedDay = i + 1;
    const expectedStr = `2026-10-${expectedDay < 10 ? '0' + expectedDay : expectedDay}`;
    assert.equal(inMonthCells[i].dayNumber, expectedDay);
    assert.equal(inMonthCells[i].dateString, expectedStr);
  }
  const todayCell = oct2026Grid.find(c => c.dateString === '2026-10-16');
  assert.ok(todayCell?.isToday);

  // Week days generation
  const weekCells = generateWeekDays('2026-10-16', '2026-10-16');
  assert.equal(weekCells.length, 7);
  assert.equal(weekCells[0].dateString, '2026-10-12'); // Monday
  assert.equal(weekCells[6].dateString, '2026-10-18'); // Sunday
  assert.equal(weekCells[4].isToday, true); // Friday 16th

  // Initial state helper
  const parsedPreview = getInitialCalendarState('2026-10-16');
  assert.equal(parsedPreview.year, 2026);
  assert.equal(parsedPreview.month, 10);
  assert.equal(parsedPreview.todayDate, '2026-10-16');

  // Role-aware event hrefs: map wrong-role learning activity source to safe teacher activities
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assignments', 'LECTURER'),
    '/teacher/classes/101/activities'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/overview', 'STUDENT'),
    '/student/classes/101/overview'
  );

  // Full detail and editor paths
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assignments/assignment-1', 'LECTURER'),
    '/teacher/classes/101/activities'
  );
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assessments/assessment-1', 'LECTURER'),
    '/teacher/classes/101/activities'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/assignments/assignment-1/edit', 'STUDENT'),
    '/student/classes/101/overview'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/assessments/assessment-1/edit', 'STUDENT'),
    '/student/classes/101/overview'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/activities', 'STUDENT'),
    '/student/classes/101/overview'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/grading', 'STUDENT'),
    '/student/classes/101/overview'
  );

  // Class mismatch checks
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assignments/assignment-1', 'LECTURER', '102'),
    undefined
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/overview', 'STUDENT', '102'),
    undefined
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/activities', 'LECTURER', '102'),
    undefined
  );
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assignments', 'STUDENT', '102'),
    undefined
  );
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assignments/assignment-1', 'LECTURER', '101'),
    '/teacher/classes/101/activities'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/overview', 'STUDENT', '101'),
    '/student/classes/101/overview'
  );

  // Unknown, external, protocol-relative URLs
  assert.equal(getRoleAwareEventHref('https://example.com/test', 'LECTURER'), undefined);
  assert.equal(getRoleAwareEventHref('http://example.com/test', 'STUDENT'), undefined);
  assert.equal(getRoleAwareEventHref('//example.com/test', 'LECTURER'), undefined);
  assert.equal(getRoleAwareEventHref('javascript:alert(1)', 'STUDENT'), undefined);
  assert.equal(getRoleAwareEventHref('/unknown/route', 'LECTURER'), undefined);
  assert.equal(getRoleAwareEventHref('/student/classes/101/unknown-action', 'LECTURER'), undefined);
  assert.equal(getRoleAwareEventHref(undefined, 'LECTURER'), undefined);
  assert.equal(getRoleAwareEventHref('', 'STUDENT'), undefined);

  // Same-role preservation
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/activities', 'LECTURER'),
    '/teacher/classes/101/activities'
  );
  assert.equal(
    getRoleAwareEventHref('/teacher/classes/101/assignments/assignment-1/edit', 'LECTURER'),
    '/teacher/classes/101/assignments/assignment-1/edit'
  );
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/assignments/assignment-1', 'STUDENT'),
    '/student/classes/101/assignments/assignment-1'
  );
  assert.equal(
    getRoleAwareEventHref('/student/classes/101/overview', 'STUDENT'),
    '/student/classes/101/overview'
  );
  assert.equal(
    getRoleAwareEventHref('/calendar', 'LECTURER'),
    '/calendar'
  );
  assert.equal(
    getRoleAwareEventHref('/calendar', 'STUDENT'),
    '/calendar'
  );
});

test('preview adapter: teacher can update and delete editable events, while read-only and unauthorized mutations are rejected', async () => {
  // Login as teacher
  await mockAdapter.identity.login(TEACHER_LOGIN);

  // Create editable event
  const created = await mockAdapter.calendar.createEvent({
    classId: '00000000-0000-4000-8000-000000000101',
    title: 'Sự kiện kiểm thử sửa/xóa',
    category: 'CLASS',
    date: '2026-10-25',
    start: '2026-10-25T08:00:00Z',
    end: '2026-10-25T10:00:00Z',
    timeRange: '08:00 – 10:00',
    description: 'Nội dung ban đầu',
  });
  assert.ok(created.id);
  assert.equal(created.start, '2026-10-25T08:00:00Z');
  assert.equal(created.end, '2026-10-25T10:00:00Z');

  // Teacher can update the event
  await assert.rejects(() => mockAdapter.calendar.updateEvent('00000000-0000-4000-8000-000000000102', created.id, {title:'Wrong class'}), (error: unknown) => error instanceof ApiError && error.status === 404);
  await assert.rejects(() => mockAdapter.calendar.deleteEvent('00000000-0000-4000-8000-000000000102', created.id), (error: unknown) => error instanceof ApiError && error.status === 404);
  const updated = await mockAdapter.calendar.updateEvent(created.classId!, created.id, {
    title: 'Sự kiện đã cập nhật',
    description: 'Nội dung mới sau khi sửa',
    start: '2026-10-25T08:30:00Z',
    end: '2026-10-25T10:30:00Z',
    timeRange: '08:30 – 10:30',
  });
  assert.equal(updated.title, 'Sự kiện đã cập nhật');
  assert.equal(updated.description, 'Nội dung mới sau khi sửa');
  assert.equal(updated.timeRange, '08:30 – 10:30');
  assert.equal(updated.start, '2026-10-25T08:30:00Z');
  assert.equal(updated.end, '2026-10-25T10:30:00Z');

  // Student cannot update teacher event
  await mockAdapter.identity.login(STUDENT_LOGIN);
  await assert.rejects(
    () => mockAdapter.calendar.updateEvent(created.classId!, created.id, { title: 'Học sinh sửa trái phép' }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Student cannot delete teacher event
  await assert.rejects(
    () => mockAdapter.calendar.deleteEvent(created.classId!, created.id),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Switch back to teacher and delete the event
  await mockAdapter.identity.login(TEACHER_LOGIN);
  await mockAdapter.calendar.deleteEvent(created.classId!, created.id);

  // Attempting to delete or update again throws 404 NOT_FOUND
  await assert.rejects(
    () => mockAdapter.calendar.deleteEvent(created.classId!, created.id),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );
  await assert.rejects(
    () => mockAdapter.calendar.updateEvent(created.classId!, created.id, { title: 'Không tồn tại' }),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );
});

test('boundary policy: inspectSource catches inline fixture values in product code', () => {
  // Concrete UUID in product source is rejected
  const uuidCode = `export const id = '00000000-0000-4000-8000-000000000101';`;
  assert.ok(inspectSource('src/test-uuid.ts', uuidCode).length > 0);

  // Exact fixture class ID fallback is rejected
  const classIdCode = `const classId = summary?.id ?? '10A1';`;
  assert.ok(inspectSource('src/test-class.tsx', classIdCode).length > 0);

  // Fixed ISO business date in runtime is rejected
  const isoDateCode = `const [date, setDate] = useState('2026-10-16');`;
  assert.ok(inspectSource('src/test-date.tsx', isoDateCode).length > 0);

  // Literal school-year label in JSX is rejected
  const schoolYearCode = `return <span>Học kỳ I 2026–2027</span>;`;
  assert.ok(inspectSource('src/test-year.tsx', schoolYearCode).length > 0);

  // Static calendar year/month defaults is rejected
  const staticCalCode = `const [state, setState] = useState({ year: 2026, month: 10 });`;
  assert.ok(inspectSource('src/test-cal.tsx', staticCalCode).length > 0);

  // Placeholder and examples are permitted
  const validPlaceholderCode = `<input placeholder="Ví dụ: 10A1" value={name} />`;
  assert.equal(inspectSource('src/test-valid.tsx', validPlaceholderCode).length, 0);

  // Clean dynamic code passes with zero violations
  const validDynamicCode = `export function getYear() { return new Date().getFullYear(); }`;
  assert.equal(inspectSource('src/test-dynamic.ts', validDynamicCode).length, 0);
});
