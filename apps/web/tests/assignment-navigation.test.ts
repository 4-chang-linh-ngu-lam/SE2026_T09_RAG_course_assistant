import test from 'node:test';
import assert from 'node:assert/strict';
import { submissionResultHref } from '../src/lib/assignment';
import { safeReturnTo } from '../src/lib/navigation';

const submission = { id: 'submission-1', classId: 'class-1', assignmentId: 'assignment-1', resultId: 'result-1' };

test('staff submission history opens an assigned-grading route accepted by the Lecturer route guard', () => {
  const href = submissionResultHref(submission, 'teacher');
  assert.equal(safeReturnTo(href, ['LECTURER'], '/teacher'), href);
  assert.equal(safeReturnTo(href, ['STUDENT'], '/student'), '/student');
  assert.ok(href.endsWith('/submissions/submission-1/grade'));
});

test('learner submission history retains the own-result route without granting staff-only access', () => {
  const href = submissionResultHref(submission, 'student');
  assert.equal(safeReturnTo(href, ['STUDENT'], '/student'), href);
  assert.equal(safeReturnTo(href, ['LECTURER'], '/teacher'), '/teacher');
  assert.equal(submissionResultHref({ ...submission, resultId: 'result/with?query' }, 'student'), '/student/history/results/result%2Fwith%3Fquery');
});
