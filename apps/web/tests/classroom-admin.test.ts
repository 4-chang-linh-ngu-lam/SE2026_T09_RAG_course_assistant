import test from 'node:test';
import assert from 'node:assert/strict';
import { createPreviewClassroomStore } from '../dev/mocks/classroom-admin';
import { createPreviewAccountStore } from '../dev/mocks/accounts';
import { classes, users, schoolId } from '../dev/mocks/fixtures';
import type { User } from '../src/lib/domain';
import { ApiError } from '../src/lib/api/errors';
const uid = (suffix: string) => `00000000-0000-4000-8000-${suffix.padStart(12, '0')}`;
const admin = uid('13'), student = uid('11'), peer = uid('21'), ha = uid('12'), minh = uid('14'), cid = uid('101');
const reason = 'ADMIN_INTERVENTION' as const;
const rejected = (code: string) => (error: unknown) => error instanceof ApiError && error.code === code;
function setup() { const foreign: User = { id: 'foreign', email: null, username: 'foreign', school_id: 'other-school', roles: ['STUDENT'], status: 'ACTIVE', display_name: 'Foreign' }; const identity = createPreviewAccountStore([...users, foreign]); const backing = structuredClone(classes); const store = createPreviewClassroomStore(backing, identity, () => 1_700_000_000_000); return { identity, backing, store }; }
test('class summaries and role queries share actual roster/assignments and backing object reference', () => {
  const { store, backing } = setup();
  assert.equal(store.getClass(cid)?.studentCount, 2); assert.equal(backing.find(value => value.id === cid)?.studentCount, 2);
  assert.equal(store.teachingRole(ha, cid), 'PRIMARY'); assert.equal(store.teachingRole(minh, cid), 'ASSISTING');
  assert.equal(store.teachingRole(ha, uid('102')), 'ASSISTING'); assert.equal(store.teachingRole(minh, uid('104')), 'PRIMARY');
  assert.deepEqual(store.studentActiveClassIds('new-user'), []); assert.deepEqual(store.studentEndedClassIds(student), [uid('102')]);
  assert.ok(store.studentArchivedClassIds(student).includes(uid('199')));
});
test('Admin-only scope; multi-role administrator can manage class without teaching assignment', () => {
  const { store, identity } = setup();
  assert.throws(() => store.workspace(student, {}), rejected('FORBIDDEN')); assert.throws(() => store.workspace(ha, { classId: cid }), rejected('FORBIDDEN'));
  identity.updateAccount(admin, { userId: admin, revision: 1, roles: ['ADMIN', 'LECTURER'], status: 'ACTIVE', reason: 'Add role' });
  assert.equal(store.teachingRole(admin, cid), null); assert.equal(store.workspace(admin, { classId: cid }).subjectClass?.summary.id, cid);
  assert.throws(() => store.previewEnrollment(admin, { classId: cid, revision: 1, mode: 'MANUAL', studentIds: ['foreign'] }), rejected('VALIDATION_ERROR'));
});
test('homeroom roster preview is distinct from applied counts and syncs only AUTO', () => {
  const { store } = setup(); const room = store.workspace(admin, { homeroomId: 'homeroom-10a1' }).homeroom!;
  const preview = store.previewHomeroomRoster(admin, { homeroomId: room.id, revision: room.revision, studentIds: [peer] });
  assert.equal(preview.currentCount, 2); assert.equal(preview.projectedCount, 1); assert.equal(store.getClass(cid)?.studentCount, 2);
  store.confirmHomeroomRoster(admin, { previewId: preview.id, reason });
  assert.equal(store.getClass(cid)?.studentCount, 1); assert.ok(!store.studentActiveClassIds(student).includes(cid)); assert.ok(store.studentEndedClassIds(student).includes(cid));
  assert.ok(store.studentActiveClassIds(student).includes(uid('103'))); assert.ok(store.studentActiveClassIds(student).includes(uid('104')));
  store.confirmHomeroomRoster(admin, { previewId: preview.id, reason }); assert.equal(store.getClass(cid)?.studentCount, 1);
});
test('transfer validates same-year/grade, updates both AUTO rooms and retains enrollment history', () => {
  const { store } = setup(); const room = store.workspace(admin, { homeroomId: 'homeroom-10a1' }).homeroom!;
  assert.throws(() => store.previewHomeroomRoster(admin, { homeroomId: room.id, revision: room.revision, studentIds: [student], destinationHomeroomId: 'homeroom-9a1' }), rejected('VALIDATION_ERROR'));
  const preview = store.previewHomeroomRoster(admin, { homeroomId: room.id, revision: room.revision, studentIds: [student], destinationHomeroomId: 'homeroom-10a2' });
  store.confirmHomeroomRoster(admin, { previewId: preview.id, reason });
  assert.ok(store.studentEndedClassIds(student).includes(cid)); assert.ok(store.studentActiveClassIds(student).includes(uid('102')));
  const target = store.workspace(admin, { classId: uid('102') }).subjectClass!;
  assert.equal(target.members.filter(member => member.userId === student).length, 2); assert.equal(target.members.filter(member => member.userId === student && member.status === 'ACTIVE').length, 1);
});
test('AUTO overrides survive source roster changes; stale preview is rejected and reconcile never repeats', () => {
  const { store, identity } = setup(); const created = identity.createStudent(admin, 'pending-without-enrollment');
  assert.deepEqual(store.studentActiveClassIds(created.student.id), []);
  const cls = store.workspace(admin, { classId: cid }).subjectClass!;
  const preview = store.previewEnrollment(admin, { classId: cid, revision: cls.revision, mode: 'AUTO', manualIncludes: [created.student.id], manualExcludes: [student] });
  assert.equal(preview.projectedCount, 2); store.confirmEnrollment(admin, { previewId: preview.id, reason });
  assert.equal(store.reconcileEnrollment(admin, preview.id).status, 'APPLIED'); assert.ok(store.activeStudentIds(cid).includes(created.student.id));
  assert.equal(identity.user(created.student.id)?.status, 'PENDING_VERIFICATION');
  const room = store.workspace(admin, { homeroomId: 'homeroom-10a1' }).homeroom!;
  const roomPreview = store.previewHomeroomRoster(admin, { homeroomId: room.id, revision: room.revision, studentIds: [student] });
  store.confirmHomeroomRoster(admin, { previewId: roomPreview.id, reason });
  assert.deepEqual(store.activeStudentIds(cid), [created.student.id]);
  const latest = store.workspace(admin, { classId: cid }).subjectClass!;
  const stalePreview = store.previewEnrollment(admin, { classId: cid, revision: latest.revision, mode: 'MANUAL', studentIds: [student] });
  store.saveClassSettings(admin, { classId: cid, revision: latest.revision, name: latest.summary.name, primaryTeacherId: ha, assistingTeacherIds: [minh], reason });
  assert.throws(() => store.confirmEnrollment(admin, { previewId: stalePreview.id, reason }), rejected('CONFLICT'));
});
test('Primary replacement is atomic/eligible; removed teacher no longer assigned', () => {
  const { store } = setup(); const cls = store.workspace(admin, { classId: cid }).subjectClass!;
  assert.throws(() => store.saveClassSettings(admin, { classId: cid, revision: cls.revision, name: cls.summary.name, primaryTeacherId: '', assistingTeacherIds: [], reason }), rejected('VALIDATION_ERROR'));
  store.saveClassSettings(admin, { classId: cid, revision: cls.revision, name: cls.summary.name, primaryTeacherId: minh, assistingTeacherIds: [], reason });
  assert.equal(store.teachingRole(ha, cid), null); assert.equal(store.teachingRole(minh, cid), 'PRIMARY'); assert.equal(store.getClass(cid)?.teacherName, 'Trần Đức Minh');
});
test('archive mutates same class object, restore respects current AUTO scope and never revives ended membership', () => {
  const { store, backing } = setup(); const cls = store.workspace(admin, { classId: cid }).subjectClass!;
  assert.throws(() => store.changeLifecycle(admin, { classId: cid, revision: cls.revision, status: 'ARCHIVED', confirmation: 'wrong', reason }), rejected('VALIDATION_ERROR'));
  store.changeLifecycle(admin, { classId: cid, revision: cls.revision, status: 'ARCHIVED', confirmation: cls.summary.name, reason });
  assert.equal(backing.find(value => value.id === cid)?.status, 'ARCHIVED'); assert.ok(!store.studentActiveClassIds(student).includes(cid)); assert.ok(store.studentArchivedClassIds(student).includes(cid));
  const archived = store.workspace(admin, { classId: cid }).subjectClass!;
  assert.throws(() => store.previewEnrollment(admin, { classId: cid, revision: archived.revision, mode: 'MANUAL', studentIds: [] }), rejected('VALIDATION_ERROR'));
  const room = store.workspace(admin, { homeroomId: 'homeroom-10a1' }).homeroom!;
  const preview = store.previewHomeroomRoster(admin, { homeroomId: room.id, revision: room.revision, studentIds: [peer] }); store.confirmHomeroomRoster(admin, { previewId: preview.id, reason });
  store.changeLifecycle(admin, { classId: cid, revision: archived.revision, status: 'ACTIVE', confirmation: archived.summary.name, reason });
  assert.ok(!store.studentActiveClassIds(student).includes(cid)); assert.ok(store.studentEndedClassIds(student).includes(cid)); assert.ok(store.studentActiveClassIds(peer).includes(cid));
});
test('catalog and newly created classes use actual references and minimal audited reason', () => {
  const { store, backing } = setup();
  const room = store.createHomeroom(admin, { name: '10A3', grade: 10, yearId: 'year-current', reason });
  const created = store.createClass(admin, { name: 'Toán 10 — 10A3', courseId: 'course-toan10', yearId: 'year-current', semesterId: 'term-current', grade: 10, homeroomId: room.id, mode: 'AUTO', primaryTeacherId: ha, assistingTeacherIds: [], reason });
  assert.equal(created.summary.studentCount, 0); assert.ok(backing.some(value => value.id === created.summary.id));
  const entry = store.saveCatalog(admin, { kind: 'COURSE', name: 'Lịch sử 10', grade: 10, reason }); assert.ok(entry.id);
  assert.ok(store.auditEvents(admin).some(event => event.action === 'CATALOG_SAVE' && event.reason === reason));
  assert.throws(() => store.auditEvents(student), rejected('FORBIDDEN'));
  assert.ok(store.workspace(admin, {}).students.every(user => user.school_id === schoolId));
});
