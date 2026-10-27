import { test } from 'node:test';
import assert from 'node:assert/strict';
import { adapter } from '../dev/mocks/adapter';
import { createDataRequestReview } from '../dev/mocks/data-request-review';
import type { PreviewContext } from '../dev/mocks/context';
import type { DataRequest, User } from '../src/lib/domain';
import { ApiError } from '../src/lib/api/errors';
const classId = '00000000-0000-4000-8000-000000000101';
const studentId = '00000000-0000-4000-8000-000000000011';
test('self-loading class features receive the same authorized class header context', async () => {
  await adapter.identity.login({ username: 'minh.anh10a1', password: 'preview' });
  for (const route of ['s.progress','s.assessments','s.assignment']) {
    const page = await adapter.workspace.load(route, { classId });
    assert.equal(page.kind, 'ready');
    if (page.kind === 'ready') { assert.equal(page.classSummary?.id, classId); assert.equal(page.classSummary?.studentCount, 2); assert.equal(page.classSummary?.membershipStatus, 'ACTIVE'); assert.equal(page.classSummary?.teachingRole, undefined); }
  }
  await adapter.identity.login({ email: 'minh.tran@lumi.example', password: 'preview' });
  const teacher = await adapter.workspace.load('t.analytics', { classId });
  assert.equal(teacher.kind, 'ready');
  if (teacher.kind === 'ready') assert.equal(teacher.classSummary?.teachingRole, 'ASSISTING');
});
test('confirmed enrollment removal immediately updates home, teacher totals and source privacy across ports', async () => {
  await adapter.identity.login({ username: 'minh.anh10a1', password: 'preview' });
  const post = await adapter.social.createPost(classId, 'A current student post');
  await adapter.identity.login({ email: 'nam.pham@lumi.example', password: 'preview' });
  const workspace = await adapter.classroom.load('a.enrollment', { classId });
  const subject = workspace.subjectClass!;
  const preview = await adapter.classroom.previewEnrollment({ classId, revision: subject.revision, mode: 'MANUAL', studentIds: subject.members.filter(item => item.status === 'ACTIVE' && item.userId !== studentId).map(item => item.userId) });
  await adapter.classroom.confirmEnrollment({ previewId: preview.id, reason: 'ADMIN_INTERVENTION' });
  await adapter.identity.login({ username: 'minh.anh10a1', password: 'preview' });
  const home = await adapter.workspace.load('s.home', {});
  assert.equal(home.kind, 'ready');
  if (home.kind === 'ready') { assert.ok(!home.studentHome?.activeClasses.some(item => item.id === classId)); assert.ok(!home.studentHome?.upcomingTasks.some(item => item.href.includes(classId))); }
  await assert.rejects(adapter.social.updatePost(classId, post.id, 'No longer authorized'), (error: unknown) => error instanceof ApiError && error.status === 403);
  const notes = await adapter.workspace.load('s.notes', {});
  if (notes.kind === 'ready') for (const note of notes.studentNotes?.filter(item => item.classId === classId) ?? []) { assert.equal(note.isSourceAccessible, false); assert.equal(note.sourceQuote, undefined); }
  await adapter.identity.login({ email: 'ha.nguyen@lumi.example', password: 'preview' });
  const teacher = await adapter.workspace.load('t.home', {});
  assert.equal(teacher.kind, 'ready');
  if (teacher.kind === 'ready') { assert.equal(teacher.teacherHome?.assignedClasses.find(item => item.id === classId)?.studentCount, 1); assert.equal(teacher.classes?.find(item => item.id === classId)?.studentCount, 1); }
});
test('personal data copy requires saved verified scope and actual bytes; completion cannot widen or bypass it', async () => {
  const makeUser = (id: string, roles: User['roles']): User => ({ id, roles, email: null, username: id, display_name: id, school_id: 'school', status: 'ACTIVE' });
  let actor = makeUser('admin', ['ADMIN']);
  const owner = makeUser('owner', ['STUDENT']);
  const records: DataRequest[] = [{ id: 'request', user_id: 'owner', type: 'EXPORT', reason: null, status: 'PENDING', resolution_note: null, created_at: '2026-10-16T00:00:00Z', updated_at: '2026-10-16T00:00:00Z' }];
  const context: PreviewContext = { actor: () => actor, classSummary: () => undefined, studentMembership: () => null, activeStudentIds: () => [], teachingRole: () => null, sources: () => [], sourceAccessible: () => false, now: () => Date.parse('2026-10-19T00:00:00Z') };
  const port = createDataRequestReview({ context, schoolId: 'school', records: () => records, user: id => id === owner.id ? owner : null, snapshot: () => ({ profile: { display_name: 'Owner' }, learningResults: [{ id: 'own-confirmed-grade' }], personalNotes: [] }) });
  const scope = [{ category: 'PROFILE', action: 'EXPORT' as const, reason: 'Verified profile copy' }];
  let row = (await port.listRequests!())[0];
  await assert.rejects(port.updateRequest!({ id: row.id, expectedRevision: row.revision, status: 'COMPLETED', identityVerified: true, resolution: 'Not actually processed', classifications: scope }));
  row = await port.updateRequest!({ id: row.id, expectedRevision: row.revision, status: 'IN_REVIEW', identityVerified: true, resolution: 'Identity checked', classifications: scope });
  row = await port.processRequest!({ id: row.id, expectedRevision: row.revision, verificationNote: 'Identity checked', classifications: scope });
  assert.equal(row.processingStatus, 'READY');
  const file = await port.downloadRequest!(row.id), body = JSON.parse(new TextDecoder().decode(file.bytes));
  assert.equal(file.type, 'application/json'); assert.deepEqual(body.data, { profile: { display_name: 'Owner' } });
  await assert.rejects(port.updateRequest!({ id: row.id, expectedRevision: row.revision, status: 'COMPLETED', identityVerified: true, resolution: 'Changed after processing', classifications: [{ ...scope[0], category: 'PERSONAL_NOTES' }] }));
  row = await port.updateRequest!({ id: row.id, expectedRevision: row.revision, status: 'COMPLETED', identityVerified: true, resolution: 'Exact copy prepared', classifications: scope });
  assert.equal(records[0].status, 'COMPLETED'); actor = owner;
  assert.deepEqual((await port.downloadRequest!(row.id)).bytes, file.bytes);
  actor = makeUser('peer', ['STUDENT']); await assert.rejects(port.downloadRequest!(row.id), (error: unknown) => error instanceof ApiError && error.status === 403);
});
