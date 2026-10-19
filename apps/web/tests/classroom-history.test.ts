import test from 'node:test';
import assert from 'node:assert/strict';
import { projectClassAssignmentHistory, projectClassMemberEpisodes, projectHomeroomRosterHistory } from '../src/lib/classroom-history';
import { createPreviewClassroomStore } from '../dev/mocks/classroom-admin';
import { createPreviewAccountStore } from '../dev/mocks/accounts';
import { classes, users } from '../dev/mocks/fixtures';
import type { ClassroomAdminWorkspace, ClassroomAudit } from '../src/lib/classroom-admin';
const uid = (suffix: string) => `00000000-0000-4000-8000-${suffix.padStart(12, '0')}`;
function snapshot(): ClassroomAdminWorkspace { return createPreviewClassroomStore(structuredClone(classes), createPreviewAccountStore(users)).workspace(uid('13'), {}); }
function event(id: string, resourceId: string, action: string, at: string, actorId = uid('13')): ClassroomAudit { return { id, resourceId, action, actorId, at, reason: 'ADMIN_INTERVENTION' }; }

test('assignment history filters exact authorized class and actual actions, sorted by recorded time', () => {
  const data = snapshot();
  data.auditEvents = [
    event('old', uid('101'), 'CLASS_CREATE', '2026-10-01T00:00:00Z'),
    event('other', uid('104'), 'CLASS_SETTINGS', '2026-10-15T00:00:00Z'),
    event('roster', uid('101'), 'ENROLLMENT_SYNC', '2026-10-16T00:00:00Z'),
    event('latest', uid('101'), 'CLASS_SETTINGS', '2026-10-17T00:00:00Z', uid('12')),
  ];
  const projected = projectClassAssignmentHistory(data, uid('101'));
  assert.deepEqual(projected.map(item => item.id), ['latest', 'old']);
  assert.equal(projected[0].at, '2026-10-17T00:00:00Z');
  assert.equal(projected[0].actorName, 'Nguyễn Thu Hà');
  assert.equal(projected[1].actorName, undefined); // Current teachers list does not contain the Admin actor.
  assert.equal(projected[0].statusLabel, undefined);
  assert.deepEqual(projectClassAssignmentHistory(data, 'not-returned'), []);
  assert.equal(data.auditEvents.length, 4);
});

test('homeroom transfer history does not infer destination or invent transferred students', () => {
  const data = snapshot();
  data.auditEvents = [event('transfer', 'homeroom-10a1', 'HOMEROOM_TRANSFER', '2026-10-17T00:00:00Z'), event('class-change', uid('101'), 'CLASS_SETTINGS', '2026-10-17T00:00:00Z')];
  const source = projectHomeroomRosterHistory(data, 'homeroom-10a1');
  assert.equal(source.length, 1);
  assert.ok(source[0].detail.includes('chưa cung cấp lớp đích'));
  assert.deepEqual(projectHomeroomRosterHistory(data, 'homeroom-10a2'), []);
  assert.deepEqual(projectHomeroomRosterHistory(data, 'unknown'), []);
});

test('membership episodes preserve ended then active entries without fabricated timestamps or actor names', () => {
  const data = snapshot(); const value = data.classes.find(subjectClass => subjectClass.summary.id === uid('101'))!;
  value.members = [ { userId: uid('11'), status: 'ENDED', source: 'AUTO' }, { userId: uid('11'), status: 'ACTIVE', source: 'MANUAL' }, { userId: 'outside-snapshot', status: 'ACTIVE', source: 'OVERRIDE' } ];
  const result = projectClassMemberEpisodes(data, uid('101'));
  assert.equal(result.length, 2); assert.notEqual(result[0].id, result[1].id);
  assert.equal(result[0].statusLabel, 'Đã kết thúc ghi danh'); assert.equal(result[1].statusLabel, 'Đang ghi danh');
  assert.ok(result.every(item => !Object.hasOwn(item, 'at') && !Object.hasOwn(item, 'actorName')));
  assert.deepEqual(projectClassMemberEpisodes(data, 'unknown'), []);
});

test('invalid audit time and unavailable actor display data stay absent instead of being synthesized', () => {
  const data = snapshot();
  data.auditEvents = [event('invalid-time', uid('101'), 'CLASS_SETTINGS', 'not-a-date', uid('11'))];
  const value = projectClassAssignmentHistory(data, uid('101'))[0];
  assert.ok(!Object.hasOwn(value, 'at')); assert.ok(!Object.hasOwn(value, 'actorName'));
  assert.ok(value.detail.includes('Điều chỉnh của quản trị viên'));
});
