import test from 'node:test';
import assert from 'node:assert/strict';
import { operationalTeachingOverview, teachingWorkload } from '../src/lib/classroom-presentation';
import type { ClassSummary } from '../src/lib/domain';

const classes: ClassSummary[] = [
  { id: 'class-a', code: 'A', name: 'Class A', status: 'ACTIVE', metadata: '', studentCount: 20 },
  { id: 'class-b', code: 'B', name: 'Class B', status: 'ACTIVE', metadata: '', studentCount: 20 },
];

test('teacher dashboard never fabricates missing grading counts or sums overlapping class rosters', () => {
  assert.deepEqual(teachingWorkload(classes), { totalClasses: 2, totalStudents: null, pendingGrading: null });
  assert.deepEqual(teachingWorkload([]), { totalClasses: 0, totalStudents: null, pendingGrading: null });
});

test('teacher dashboard preserves confirmed zero metrics and authoritative aggregate counts', () => {
  assert.deepEqual(teachingWorkload(classes, { totalClasses: 0, totalStudents: 0, pendingGrading: 0 }), {
    totalClasses: 0, totalStudents: 0, pendingGrading: 0,
  });
  assert.deepEqual(teachingWorkload(classes, { totalClasses: 3, totalStudents: 21, pendingGrading: 4 }), {
    totalClasses: 3, totalStudents: 21, pendingGrading: 4,
  });
});

test('operational Teacher Home excludes archived and unassigned class actions while preserving general events', () => {
  const assigned: ClassSummary[] = [classes[0], { ...classes[1], status: 'ARCHIVED' }];
  const event = { id: 'active', title: 'Lesson', description: '', category: 'CLASS' as const, start: '2026-10-22T07:00:00', date: '2026-10-22', classId: 'class-a' };
  const discussion = { id: 'active', classId: 'class-a', studentName: 'Student', className: 'Class A', createdAt: '', content: 'Question' };
  const overview = {
    todaySchedule: [event, { ...event, id: 'archived', classId: 'class-b' }, { ...event, id: 'unassigned', classId: 'other-class' }, { ...event, id: 'general', classId: undefined }],
    recentDiscussions: [discussion, { ...discussion, id: 'archived', classId: 'class-b' }, { ...discussion, id: 'unassigned', classId: 'other-class' }],
  };
  const result = operationalTeachingOverview(assigned, overview);
  assert.deepEqual(result.schedule.map(item => item.id), ['active', 'general']);
  assert.deepEqual(result.discussions.map(item => item.id), ['active']);
  assert.equal(overview.todaySchedule.length, 4);
  assert.equal(overview.recentDiscussions.length, 3);
});

test('operational Teacher Home fails closed when class scope is absent without hiding archive cards or inventing activity', () => {
  assert.deepEqual(operationalTeachingOverview(classes), { schedule: [], discussions: [] });
  assert.deepEqual(operationalTeachingOverview([], { todaySchedule: [], recentDiscussions: [{ id: 'old', classId: 'class-a', studentName: '', className: '', createdAt: '', content: '' }] }), { schedule: [], discussions: [] });
  assert.equal(classes.length, 2);
});
