import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { adapter as mockAdapter, resetStage3aMockStores } from '../dev/mocks/adapter';
import { adapter as liveAdapter } from '../src/lib/data/live';
import { ApiError } from '../src/lib/api/errors';
import { inspectSource } from '../scripts/boundary-policy.mjs';
import { SaveController, isAnswerComplete } from '../src/features/learning/lib/save-controller';
import type { PracticeAnswer, PracticeAttemptDetail } from '../src/lib/domain';
import { reconcileAttemptDraft, areAnswersEqual, areAnswerMapsEqual } from '../src/features/learning/lib/draft-reconciliation';
import { draftStore, getAttemptDraft, setAttemptDraft, clearAttemptDraft } from '../src/lib/draft-store';

const STUDENT_LOGIN = { username: 'minh.anh10a1', password: 'ValidPassword123!' };
const SECOND_STUDENT_LOGIN = { username: 'quan.tran10a1', password: 'ValidPassword123!' };
const TEACHER1_LOGIN = { email: 'ha.nguyen@lumi.example', password: 'ValidPassword123!' };
const TEACHER2_LOGIN = { email: 'minh.tran@lumi.example', password: 'ValidPassword123!' };

const CLASS_101_ID = '00000000-0000-4000-8000-000000000101';
const CLASS_104_ID = '00000000-0000-4000-8000-000000000104';
const PRACTICE_ID = 'prac-dinh-truc';
const ATTEMPT_ID = 'attempt-dt-001';
const RESULT_ATTEMPT_ID = 'attempt-hist-10q-2';

test('1. live adapter rejects all learning calls honestly with 503 UNAVAILABLE', { timeout: 10000 }, async () => {
  await assert.rejects(
    () => liveAdapter.learning.startPracticeAttempt({ classId: CLASS_101_ID, practiceId: PRACTICE_ID, intent: 'start' }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.checkPracticeAnswer({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      questionId: 'q1',
      answer: { questionId: 'q1', singleChoiceValue: 'A' },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.savePracticeDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      answers: {},
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.finishPracticeAttempt({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.createPracticeDraft({
      classId: CLASS_101_ID,
      title: 'Draft',
      topic: 'Topic',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.savePracticeEditorDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      title: 'Draft',
      topic: 'Topic',
      questions: [],
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.reviewEditorQuestion({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      questionId: 'q1',
      approved: true,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.learning.publishPractice({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
});

test('2. preview adapter: student practice isolation, peer attempt/result read and mutation denial', { timeout: 10000 }, async () => {
  resetStage3aMockStores();

  // Login as Student 1 (Minh Anh) - owner of attempt-dt-001 and attempt-hist-10q-2
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Student 1 can load practice list, attempt, and result
  const list1 = await mockAdapter.workspace.load('s.practice', { classId: CLASS_101_ID });
  assert.equal(list1.kind, 'ready');

  const attempt1 = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: ATTEMPT_ID,
  });
  assert.equal(attempt1.kind, 'ready');
  assert.equal(attempt1.practiceAttempt?.attemptId, ATTEMPT_ID);

  const result1 = await mockAdapter.workspace.load('s.practiceResult', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: RESULT_ATTEMPT_ID,
  });
  assert.equal(result1.kind, 'ready');
  assert.equal(result1.practiceResult?.attemptId, RESULT_ATTEMPT_ID);

  // Login as Student 2 (Quan Tran) - peer student in the same class (CLASS_101_ID)
  await mockAdapter.identity.login(SECOND_STUDENT_LOGIN);

  // Peer student CANNOT read Student 1's attempt (Probe Check 3)
  const peerAttemptLoad = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: ATTEMPT_ID,
  });
  assert.equal(peerAttemptLoad.kind, 'unavailable');

  // Peer student CANNOT read Student 1's result (Probe Check 4)
  const peerResultLoad = await mockAdapter.workspace.load('s.practiceResult', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: RESULT_ATTEMPT_ID,
  });
  assert.equal(peerResultLoad.kind, 'unavailable');

  // Peer student CANNOT save draft on Student 1's attempt (Probe Check 5)
  await assert.rejects(
    () => mockAdapter.learning.savePracticeDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      answers: {
        q1: { questionId: 'q1', singleChoiceValue: 'A' },
      },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Peer student CANNOT finish Student 1's attempt (Probe Check 6)
  await assert.rejects(
    () => mockAdapter.learning.finishPracticeAttempt({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Peer student CANNOT check answer on Student 1's attempt
  await assert.rejects(
    () => mockAdapter.learning.checkPracticeAnswer({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      questionId: 'q1',
      answer: { questionId: 'q1', singleChoiceValue: 'A' },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
});

test('3. preview adapter: teacher practice editor cross-class read and mutation denial', { timeout: 10000 }, async () => {
  resetStage3aMockStores();

  // Student cannot access teacher practice editor
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const studentEditorLoad = await mockAdapter.workspace.load('t.practiceEditor', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
  });
  assert.equal(studentEditorLoad.kind, 'unavailable');

  await assert.rejects(
    () => mockAdapter.learning.publishPractice({ classId: CLASS_101_ID, practiceId: PRACTICE_ID }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Login as Teacher 1 (Ha Nguyen - teaches CLASS_101_ID)
  await mockAdapter.identity.login(TEACHER1_LOGIN);

  // Teacher can read editor for class 101
  const teacherEditorLoad = await mockAdapter.workspace.load('t.practiceEditor', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
  });
  assert.equal(teacherEditorLoad.kind, 'ready');
  assert.equal(teacherEditorLoad.teacherPracticeEditor?.practiceId, PRACTICE_ID);

  // Cross-class editor read denial (Probe Check 7):
  const crossClassEditorLoad = await mockAdapter.workspace.load('t.practiceEditor', {
    classId: CLASS_104_ID,
    practiceId: PRACTICE_ID,
  });
  assert.equal(crossClassEditorLoad.kind, 'unavailable');

  // Cross-class editor mutation denial (Probe Check 8):
  await assert.rejects(
    () => mockAdapter.learning.savePracticeEditorDraft({
      classId: CLASS_104_ID,
      practiceId: PRACTICE_ID,
      title: 'Cross Class Save',
      topic: 'Topic',
      questions: [],
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  await assert.rejects(
    () => mockAdapter.learning.reviewEditorQuestion({
      classId: CLASS_104_ID,
      practiceId: PRACTICE_ID,
      questionId: 'q1',
      approved: true,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  await assert.rejects(
    () => mockAdapter.learning.publishPractice({
      classId: CLASS_104_ID,
      practiceId: PRACTICE_ID,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
});

test('4. runtime validation: save and check reject invalid questions, options, and incomplete true-false', { timeout: 10000 }, async () => {
  resetStage3aMockStores();
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // 1. Save rejects unknown question ID (flows-probe check 8)
  await assert.rejects(
    () => mockAdapter.learning.savePracticeDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      answers: {
        'unknown-question-id': { questionId: 'unknown-question-id', singleChoiceValue: 'A' },
      },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 400
  );

  // 2. Save rejects option outside the question (flows-probe check 9)
  await assert.rejects(
    () => mockAdapter.learning.savePracticeDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      answers: {
        q1: { questionId: 'q1', singleChoiceValue: 'NON_EXISTENT_OPTION' },
      },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 400
  );

  // 3. Save rejects key != answer.questionId
  await assert.rejects(
    () => mockAdapter.learning.savePracticeDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      answers: {
        q1: { questionId: 'q2', singleChoiceValue: 'A' },
      },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 400
  );

  // 4. Check rejects answer for a different question (flows-probe check 10)
  await assert.rejects(
    () => mockAdapter.learning.checkPracticeAnswer({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      questionId: 'q1',
      answer: { questionId: 'q2', singleChoiceValue: 'A' },
    }),
    (err: unknown) => err instanceof ApiError && err.status === 400
  );

  // 5. Check rejects incomplete true-false answer (flows-probe check 11)
  // q3 in attempt-dt-001 has 4 statements: a, b, c, d
  await assert.rejects(
    () => mockAdapter.learning.checkPracticeAnswer({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: ATTEMPT_ID,
      questionId: 'q3',
      answer: { questionId: 'q3', trueFalseValues: { a: true } }, // missing b, c, d
    }),
    (err: unknown) => err instanceof ApiError && err.status === 400
  );

  // 6. Save allows valid partial true-false
  const partialSaveRes = await mockAdapter.learning.savePracticeDraft({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: ATTEMPT_ID,
    answers: {
      q3: { questionId: 'q3', trueFalseValues: { a: true } },
    },
  });
  assert.ok(partialSaveRes.savedAt);
});

test('5. editor sources resolve to real granted class documents; revoked or unready sources are redacted', { timeout: 10000 }, async () => {
  resetStage3aMockStores();
  await mockAdapter.identity.login(TEACHER1_LOGIN);

  const editorLoad = await mockAdapter.workspace.load('t.practiceEditor', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
  });
  assert.equal(editorLoad.kind, 'ready');
  assert.ok(editorLoad.teacherPracticeEditor);

  const sources = editorLoad.teacherPracticeEditor.availableClassSources;
  // Class 101 has 3 granted active documents
  assert.equal(sources.length, 3);
  const docIds = sources.map(s => s.id);
  assert.ok(docIds.includes('doc-1-ham-so-bac-hai'));
  assert.ok(docIds.includes('doc-2-do-thi-parabol'));
  assert.ok(docIds.includes('doc-4-tom-tat-dai-so'));

  // 1. Valid granted READY source is accessible with sourceReference intact
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const attemptLoad = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: ATTEMPT_ID,
  });
  assert.equal(attemptLoad.kind, 'ready');
  const q1 = attemptLoad.practiceAttempt?.questions[0];
  assert.equal(q1?.sourceRef?.isAccessible, true);
  assert.ok(q1?.sourceReference);

  // 2. Canonical fixture RESULT_ATTEMPT_ID has typed sourceRef, so sourceReference remains intact:
  const resultLoad = await mockAdapter.workspace.load('s.practiceResult', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: RESULT_ATTEMPT_ID,
  });
  assert.equal(resultLoad.kind, 'ready');
  assert.equal(resultLoad.practiceResult?.questions[0].sourceRef?.isAccessible, true);

  // Assert redaction protection on question with display-only sourceReference but NO sourceRef:
  await mockAdapter.identity.login(TEACHER1_LOGIN);
  const untypedDraft = await mockAdapter.learning.createPracticeDraft({
    classId: CLASS_101_ID,
    title: 'Bài tập kiểm tra nguồn không định kiểu',
    topic: 'Kiểm tra nguồn',
  });
  await mockAdapter.learning.savePracticeEditorDraft({
    classId: CLASS_101_ID,
    practiceId: untypedDraft.practiceId,
    questions: [
      {
        id: 'q-display-only-src',
        type: 'single_choice',
        prompt: 'Câu hỏi với sourceReference hiển thị nhưng không có typed sourceRef',
        topic: 'Kiểm tra',
        points: 1,
        options: [
          { id: 'A', label: 'A', text: 'Đáp án A' },
          { id: 'B', label: 'B', text: 'Đáp án B' },
        ],
        correctOptionId: 'A',
        sourceReference: 'SGK Toán 10 · Trang 45',
        sourceRef: undefined,
      },
    ],
  });
  await mockAdapter.learning.reviewEditorQuestion({
    classId: CLASS_101_ID,
    practiceId: untypedDraft.practiceId,
    questionId: 'q-display-only-src',
    approved: true,
  });
  await mockAdapter.learning.publishPractice({
    classId: CLASS_101_ID,
    practiceId: untypedDraft.practiceId,
  });

  await mockAdapter.identity.login(STUDENT_LOGIN);
  const startUntyped = await mockAdapter.learning.startPracticeAttempt({
    classId: CLASS_101_ID,
    practiceId: untypedDraft.practiceId,
    intent: 'start',
  });
  const untypedAttemptLoad = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: untypedDraft.practiceId,
    attemptId: startUntyped.attemptId,
  });
  assert.equal(untypedAttemptLoad.kind, 'ready');
  const qUntyped = untypedAttemptLoad.practiceAttempt!.questions[0];
  assert.equal(qUntyped.sourceRef, undefined);
  assert.equal(qUntyped.sourceReference, undefined, 'Untyped source reference without typed sourceRef must be redacted on Student read');

  // 3. Teacher creates questions referencing a non-ready version (v3 status FAILED) and an ungranted document (doc-6)
  await mockAdapter.identity.login(TEACHER1_LOGIN);
  const unreadyDraft = await mockAdapter.learning.createPracticeDraft({
    classId: CLASS_101_ID,
    title: 'Bài tập kiểm tra nguồn',
    topic: 'Kiểm tra nguồn',
  });
  await mockAdapter.learning.savePracticeEditorDraft({
    classId: CLASS_101_ID,
    practiceId: unreadyDraft.practiceId,
    questions: [
      {
        id: 'q-failed-ver',
        type: 'single_choice',
        prompt: 'Câu hỏi với tài liệu phiên bản FAILED',
        topic: 'Kiểm tra',
        points: 1,
        options: [
          { id: 'A', label: 'A', text: 'Đáp án A' },
          { id: 'B', label: 'B', text: 'Đáp án B' },
        ],
        correctOptionId: 'A',
        sourceReference: 'Hàm số bậc hai_v3_draft.pdf · Trang 1',
        sourceRef: {
          documentId: 'doc-1-ham-so-bac-hai',
          documentTitle: 'Hàm số bậc hai_v3_draft.pdf',
          versionNumber: 3, // Version 3 status is FAILED in mockDocumentVersions
          locator: 'Trang 1',
          displayText: 'Hàm số bậc hai_v3_draft.pdf',
        },
      },
      {
        id: 'q-revoked-doc',
        type: 'single_choice',
        prompt: 'Câu hỏi với tài liệu đã thu hồi quyền',
        topic: 'Kiểm tra',
        points: 1,
        options: [
          { id: 'A', label: 'A', text: 'Đáp án A' },
          { id: 'B', label: 'B', text: 'Đáp án B' },
        ],
        correctOptionId: 'A',
        sourceReference: 'Đề cương hình học kỳ I.pdf · Trang 1',
        sourceRef: {
          documentId: 'doc-6-de-cuong-hinh-hoc', // Revoked / not shared with class 101
          documentTitle: 'Đề cương hình học kỳ I.pdf',
          versionNumber: 1,
          locator: 'Trang 1',
          displayText: 'Đề cương hình học kỳ I.pdf',
        },
      },
    ],
  });
  await mockAdapter.learning.reviewEditorQuestion({
    classId: CLASS_101_ID,
    practiceId: unreadyDraft.practiceId,
    questionId: 'q-failed-ver',
    approved: true,
  });
  await mockAdapter.learning.reviewEditorQuestion({
    classId: CLASS_101_ID,
    practiceId: unreadyDraft.practiceId,
    questionId: 'q-revoked-doc',
    approved: true,
  });
  await mockAdapter.learning.publishPractice({
    classId: CLASS_101_ID,
    practiceId: unreadyDraft.practiceId,
  });

  // Student starts attempt on this new practice: unready/ungranted sources must be redacted
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const startUnready = await mockAdapter.learning.startPracticeAttempt({
    classId: CLASS_101_ID,
    practiceId: unreadyDraft.practiceId,
    intent: 'start',
  });
  const unreadyAttemptLoad = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: unreadyDraft.practiceId,
    attemptId: startUnready.attemptId,
  });
  assert.equal(unreadyAttemptLoad.kind, 'ready');
  const [sanitizedQFailedVer, sanitizedQRevokedDoc] = unreadyAttemptLoad.practiceAttempt!.questions;

  // Failed version: isAccessible is false, displayText is updated, sourceReference is cleared
  assert.equal(sanitizedQFailedVer.sourceRef?.isAccessible, false);
  assert.equal(sanitizedQFailedVer.sourceRef?.displayText, 'Tài liệu không còn khả dụng');
  assert.equal(sanitizedQFailedVer.sourceReference, undefined);

  // Revoked/ungranted doc: isAccessible is false, displayText is updated, sourceReference is cleared
  assert.equal(sanitizedQRevokedDoc.sourceRef?.isAccessible, false);
  assert.equal(sanitizedQRevokedDoc.sourceRef?.displayText, 'Tài liệu không còn khả dụng');
  assert.equal(sanitizedQRevokedDoc.sourceReference, undefined);
});

test('6. teacher editor: saving new question cannot forge review; explicit review required', { timeout: 10000 }, async () => {
  resetStage3aMockStores();
  await mockAdapter.identity.login(TEACHER1_LOGIN);

  // Create new draft
  const draft = await mockAdapter.learning.createPracticeDraft({
    classId: CLASS_101_ID,
    title: 'Khảo sát nâng cao',
    topic: 'Hàm số bậc hai',
  });

  // Save new question with forged isReviewed: true
  const saveRes = await mockAdapter.learning.savePracticeEditorDraft({
    classId: CLASS_101_ID,
    practiceId: draft.practiceId,
    title: 'Khảo sát nâng cao',
    topic: 'Hàm số bậc hai',
    questions: [
      {
        id: 'q-new-1',
        type: 'single_choice',
        prompt: 'Hàm số y = x^2 đồng biến trên khoảng nào?',
        topic: 'Hàm số bậc hai',
        points: 1,
        isReviewed: true, // Forged review flag in save input!
        options: [
          { id: 'opt-1a', label: 'A', text: '(-∞; 0)' },
          { id: 'opt-1b', label: 'B', text: '(0; +∞)' },
        ],
        correctOptionId: 'opt-1b',
        explanation: 'Với a = 1 > 0, hàm số đồng biến trên (0; +∞).',
      },
    ],
  });

  // Save must NEVER grant review on new question
  assert.equal(saveRes.reviewedCount, 0, 'New question saved with isReviewed: true must still have reviewedCount 0');
  assert.equal(saveRes.canPublish, false, 'canPublish must remain false');

  // Publishing must be rejected
  await assert.rejects(
    () => mockAdapter.learning.publishPractice({
      classId: CLASS_101_ID,
      practiceId: draft.practiceId,
    }),
    (err: unknown) => err instanceof ApiError && err.status === 400
  );

  // Explicit approval via reviewEditorQuestion
  const reviewRes = await mockAdapter.learning.reviewEditorQuestion({
    classId: CLASS_101_ID,
    practiceId: draft.practiceId,
    questionId: 'q-new-1',
    approved: true,
  });
  assert.equal(reviewRes.reviewedCount, 1);
  assert.equal(reviewRes.canPublish, true);

  // Publishing succeeds
  const pubRes = await mockAdapter.learning.publishPractice({
    classId: CLASS_101_ID,
    practiceId: draft.practiceId,
  });
  assert.equal(pubRes.success, true);
  assert.ok(pubRes.publishedVersionId);

  // Repeated publish with no new draft returns same already-confirmed version
  const repeatPub = await mockAdapter.learning.publishPractice({
    classId: CLASS_101_ID,
    practiceId: draft.practiceId,
  });
  assert.equal(repeatPub.publishedVersionId, pubRes.publishedVersionId);
});

test('7. editing published practice starts unreviewed draft; attempts retain immutable snapshot', { timeout: 10000 }, async () => {
  resetStage3aMockStores();
  await mockAdapter.identity.login(TEACHER1_LOGIN);

  // prac-dinh-truc is initially published with 4 questions
  const editorBefore = await mockAdapter.workspace.load('t.practiceEditor', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
  });
  assert.equal(editorBefore.kind, 'ready');
  assert.equal(editorBefore.teacherPracticeEditor?.isDraft, false);

  // Teacher edits prompt of q1
  const modifiedQuestions = structuredClone(editorBefore.teacherPracticeEditor!.questions);
  modifiedQuestions[0].prompt = 'Hàm số nào sau đây chắc chắn là hàm số bậc hai một ẩn?';

  await mockAdapter.learning.savePracticeEditorDraft({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    questions: modifiedQuestions,
  });

  // Editor must now be in draft mode
  const editorAfter = await mockAdapter.workspace.load('t.practiceEditor', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
  });
  assert.equal(editorAfter.kind, 'ready');
  assert.equal(editorAfter.teacherPracticeEditor?.isDraft, true);

  // Existing student attempt retains its original pinned question snapshot
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const studentAttempt = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: ATTEMPT_ID,
  });
  assert.equal(studentAttempt.kind, 'ready');
  assert.equal(studentAttempt.practiceAttempt?.questions[0].prompt, 'Hàm số nào sau đây là hàm số bậc hai?');
});

test('8. primary teacher metadata derives from actual class; student attempt has no teachingRole', { timeout: 10000 }, async () => {
  resetStage3aMockStores();
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Class 101: Primary teacher is Nguyễn Thu Hà
  const start101 = await mockAdapter.learning.startPracticeAttempt({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    intent: 'retry',
  });
  const attempt101 = await mockAdapter.workspace.load('s.practiceAttempt', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: start101.attemptId,
  });
  assert.equal(attempt101.kind, 'ready');
  assert.equal(attempt101.practiceAttempt?.primaryTeacherName, 'Nguyễn Thu Hà');
  assert.equal(attempt101.practiceAttempt?.teachingRole, undefined, 'Student read model must not have teachingRole');
});

test('9. finish attempt scoring, duration, and result verification through workspace', { timeout: 10000 }, async () => {
  resetStage3aMockStores();
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Start new attempt via retry
  const startResult = await mockAdapter.learning.startPracticeAttempt({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    intent: 'retry',
  });
  const newAttemptId = startResult.attemptId;

  // Answer q1 correctly (A) and q2 incorrectly (D)
  await mockAdapter.learning.savePracticeDraft({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: newAttemptId,
    answers: {
      q1: { questionId: 'q1', singleChoiceValue: 'A' },
      q2: { questionId: 'q2', multipleChoiceValues: ['D'] },
    },
  });

  // Finish attempt
  const finishRes = await mockAdapter.learning.finishPracticeAttempt({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: newAttemptId,
  });
  assert.equal(finishRes.attemptId, newAttemptId);
  assert.ok(finishRes.resultHref);

  // Load confirmed result through workspace
  const resultData = await mockAdapter.workspace.load('s.practiceResult', {
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: newAttemptId,
  });
  assert.equal(resultData.kind, 'ready');
  assert.ok(resultData.practiceResult);
  assert.equal(resultData.practiceResult.score.total, 4);
  assert.equal(resultData.practiceResult.score.correct, 1);
  assert.equal(resultData.practiceResult.score.percentage, 25);
  assert.equal(resultData.practiceResult.correctCount, 1);
  assert.ok(resultData.practiceResult.durationMinutes >= 0);
  assert.equal(resultData.practiceResult.questions.length, 4);

  // Repeated finish is idempotent
  const repeatFinish = await mockAdapter.learning.finishPracticeAttempt({
    classId: CLASS_101_ID,
    practiceId: PRACTICE_ID,
    attemptId: newAttemptId,
  });
  assert.equal(repeatFinish.attemptId, newAttemptId);

  // Attempt is completed, further draft saves or checks are rejected
  await assert.rejects(
    () => mockAdapter.learning.savePracticeDraft({
      classId: CLASS_101_ID,
      practiceId: PRACTICE_ID,
      attemptId: newAttemptId,
      answers: {},
    }),
    (err: unknown) => err instanceof ApiError && err.status === 409
  );
});

test('10. boundary checks: zero fixture leakage, hardcoded UUIDs, or boundary violations in stage3a product code', { timeout: 10000 }, () => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const filesToCheck = [
    'src/lib/domain.ts',
    'src/lib/data/port.ts',
    'src/lib/data/live.ts',
    'src/features/learning/views/student-practice-list-view.tsx',
    'src/features/learning/views/student-practice-attempt-view.tsx',
    'src/features/learning/views/student-practice-result-view.tsx',
    'src/features/learning/components/question-renderer.tsx',
    'src/features/learning/lib/save-controller.ts',
  ];

  for (const relPath of filesToCheck) {
    const fullPath = join(root, relPath);
    const content = readFileSync(fullPath, 'utf8');
    const violations = inspectSource(relPath, content);
    assert.deepEqual(violations, [], `Boundary violation in ${relPath}: ${violations.join(', ')}`);
  }
});

function createDeferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test('11. SaveController: serialization, coalescing, and old ACK while newer pending', async () => {
  const calls: Record<string, PracticeAnswer>[] = [];
  const deferredSaves: Array<ReturnType<typeof createDeferred<{ savedAt: string }>>> = [];
  const statusHistory: string[] = [];

  const controller = new SaveController({
    saveFn: (answers) => {
      calls.push(answers);
      const d = createDeferred<{ savedAt: string }>();
      deferredSaves.push(d);
      return d.promise;
    },
    onStatusChange: (status) => {
      statusHistory.push(status);
    },
  });

  // 1. First edit triggers save immediately
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'A' } });
  assert.equal(calls.length, 1);
  assert.equal(controller.isSaving(), true);
  assert.equal(controller.hasQueuedEdits(), false);
  assert.equal(statusHistory[statusHistory.length - 1], 'saving');

  // 2. Concurrent edits while first save is in flight coalesce
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'B' } });
  assert.equal(calls.length, 1);
  assert.equal(controller.hasQueuedEdits(), true);

  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'C' } });
  assert.equal(calls.length, 1);
  assert.equal(controller.hasQueuedEdits(), true);

  // 3. Resolve first save (old ACK) while newer edits are pending
  deferredSaves[0].resolve({ savedAt: '12:00:00' });
  await deferredSaves[0].promise;
  await Promise.resolve();
  await Promise.resolve();

  // Crucial: Old ACK MUST NOT announce 'saved' while newer edit is pending!
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1], { q1: { questionId: 'q1', singleChoiceValue: 'C' } });
  assert.equal(controller.isSaving(), true);
  // Status must NOT have announced saved for the older payload while 'C' was pending
  assert.notEqual(statusHistory[statusHistory.length - 2], 'saved');

  // 4. Resolve second save (latest ACK)
  deferredSaves[1].resolve({ savedAt: '12:00:01' });
  await deferredSaves[1].promise;
  await Promise.resolve();
  await Promise.resolve();

  // Now all edits ACKed -> status is 'saved'
  assert.equal(controller.isSaving(), false);
  assert.equal(controller.hasQueuedEdits(), false);
  assert.equal(statusHistory[statusHistory.length - 1], 'saved');
  assert.deepEqual(controller.getLastSavedAnswers(), { q1: { questionId: 'q1', singleChoiceValue: 'C' } });

  controller.dispose();
});

test('12. SaveController: flush waits for all in-flight and queued saves to resolve', async () => {
  const deferredSaves: Array<ReturnType<typeof createDeferred<{ savedAt: string }>>> = [];

  const controller = new SaveController({
    saveFn: () => {
      const d = createDeferred<{ savedAt: string }>();
      deferredSaves.push(d);
      return d.promise;
    },
  });

  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'A' } });
  assert.equal(deferredSaves.length, 1);

  let flushed = false;
  const flushPromise = controller.flush().then(() => {
    flushed = true;
  });

  // Queue another edit while first is in-flight
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'B' } });
  assert.equal(flushed, false);

  // Resolve first save
  deferredSaves[0].resolve({ savedAt: '12:00:00' });
  await deferredSaves[0].promise;
  await Promise.resolve();
  await Promise.resolve();

  // Flush must STILL be pending because second edit is now in flight!
  assert.equal(flushed, false);
  assert.equal(deferredSaves.length, 2);

  // Resolve second save (latest ACK)
  deferredSaves[1].resolve({ savedAt: '12:00:01' });
  await flushPromise;
  assert.equal(flushed, true);

  controller.dispose();
});

test('13. SaveController: unknown outcome blocks queued writes, retains draft, flush rejects, and disposal cancels', async () => {
  let receivedOutcome: string | null = null;
  let receivedStatus: string | null = null;
  const deferredSaves: Array<ReturnType<typeof createDeferred<{ savedAt: string }>>> = [];
  const calls: Record<string, PracticeAnswer>[] = [];

  const controller = new SaveController({
    saveFn: (answers) => {
      calls.push(answers);
      const d = createDeferred<{ savedAt: string }>();
      deferredSaves.push(d);
      return d.promise;
    },
    onStatusChange: (status) => {
      receivedStatus = status;
    },
    onError: (_err, outcome) => {
      receivedOutcome = outcome;
    },
  });

  // 1. Start first save
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'A' } });
  assert.equal(calls.length, 1);

  // Queue a second edit while first is in-flight
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'B' } });

  const flushPromise = controller.flush();

  // First save fails with unknown outcome ApiError
  const apiError = new ApiError('NETWORK_ERR', 'Mạng gián đoạn', 500, 'unknown');
  deferredSaves[0].reject(apiError);

  // Flush MUST reject on error/unknown outcome (cannot resolve successfully!)
  await assert.rejects(flushPromise, (err: unknown) => err === apiError);

  await Promise.resolve();
  await Promise.resolve();

  assert.equal(receivedStatus, 'error');
  assert.equal(receivedOutcome, 'unknown');
  assert.equal(controller.isBlocked(), true);

  // Crucial: Controller MUST NOT blind retry or send queued write B while in blocked/error state!
  assert.equal(calls.length, 1);

  // Pending draft must be retained
  assert.deepEqual(controller.getPendingAnswers(), { q1: { questionId: 'q1', singleChoiceValue: 'B' } });

  // Calling flush while blocked must immediately reject
  await assert.rejects(() => controller.flush(), (err: unknown) => err === apiError);

  // Calling queueSave while blocked does not trigger automatic save
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'C' } });
  assert.equal(calls.length, 1);
  assert.deepEqual(controller.getPendingAnswers(), { q1: { questionId: 'q1', singleChoiceValue: 'C' } });

  // 2. Disposal cancels future queued operations and rejects flush
  const deferredLate = createDeferred<{ savedAt: string }>();
  let lateStatusCalled = false;
  const controller2 = new SaveController({
    saveFn: () => deferredLate.promise,
    onStatusChange: () => { lateStatusCalled = true; },
  });

  controller2.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'A' } });
  controller2.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'B' } });
  const flushPromise2 = controller2.flush();

  controller2.dispose();

  // Disposal MUST reject flush, NOT resolve it
  await assert.rejects(flushPromise2, /disposed/i);

  // After disposal, late callbacks are suppressed
  lateStatusCalled = false;
  deferredLate.resolve({ savedAt: '12:00:00' });
  await deferredLate.promise;
  await Promise.resolve();
  assert.equal(lateStatusCalled, false);
  assert.equal(controller2.hasQueuedEdits(), false);
});

test('14. isAnswerComplete: correctly verifies completion across all 4 question types with matching ID and shape', () => {
  // Single choice: question must have options, answer must match option ID
  const singleQ = {
    type: 'single_choice' as const,
    id: 'q1',
    prompt: '',
    options: [
      { id: 'opt-a', label: 'A', text: 'Opt A' },
      { id: 'opt-b', label: 'B', text: 'Opt B' },
    ],
  };
  assert.equal(isAnswerComplete(singleQ, undefined), false);
  assert.equal(isAnswerComplete(singleQ, { questionId: 'q1', singleChoiceValue: '' }), false);
  assert.equal(isAnswerComplete(singleQ, { questionId: 'wrong-id', singleChoiceValue: 'opt-a' }), false);
  assert.equal(isAnswerComplete(singleQ, { questionId: 'q1', singleChoiceValue: 'non-existent' }), false);
  assert.equal(isAnswerComplete(singleQ, { questionId: 'q1', singleChoiceValue: 'opt-a' }), true);

  // Multiple choice: question must have options, answer must have valid option IDs
  const multiQ = {
    type: 'multiple_choice' as const,
    id: 'q2',
    prompt: '',
    options: [
      { id: 'opt-a', label: 'A', text: 'Opt A' },
      { id: 'opt-b', label: 'B', text: 'Opt B' },
    ],
  };
  assert.equal(isAnswerComplete(multiQ, undefined), false);
  assert.equal(isAnswerComplete(multiQ, { questionId: 'q2', multipleChoiceValues: [] }), false);
  assert.equal(isAnswerComplete(multiQ, { questionId: 'wrong-id', multipleChoiceValues: ['opt-a'] }), false);
  assert.equal(isAnswerComplete(multiQ, { questionId: 'q2', multipleChoiceValues: ['non-existent'] }), false);
  assert.equal(isAnswerComplete(multiQ, { questionId: 'q2', multipleChoiceValues: ['opt-a'] }), true);
  assert.equal(isAnswerComplete(multiQ, { questionId: 'q2', multipleChoiceValues: ['opt-a', 'opt-b'] }), true);

  // True / False: statements must all be answered with boolean
  const tfQ = {
    type: 'true_false' as const,
    id: 'q3',
    prompt: '',
    statements: [
      { id: 's1', label: 'a', text: 'St 1' },
      { id: 's2', label: 'b', text: 'St 2' },
    ],
  };
  assert.equal(isAnswerComplete(tfQ, undefined), false);
  assert.equal(isAnswerComplete(tfQ, { questionId: 'wrong-id', trueFalseValues: { s1: true, s2: false } }), false);
  assert.equal(isAnswerComplete(tfQ, { questionId: 'q3', trueFalseValues: { s1: true } }), false);
  assert.equal(isAnswerComplete(tfQ, { questionId: 'q3', trueFalseValues: { s1: true, s2: false } }), true);

  // Short answer: trimmed non-empty string
  const saQ = { type: 'short_answer' as const, id: 'q4', prompt: '' };
  assert.equal(isAnswerComplete(saQ, undefined), false);
  assert.equal(isAnswerComplete(saQ, { questionId: 'wrong-id', shortAnswerValue: '1' }), false);
  assert.equal(isAnswerComplete(saQ, { questionId: 'q4', shortAnswerValue: '   ' }), false);
  assert.equal(isAnswerComplete(saQ, { questionId: 'q4', shortAnswerValue: '1' }), true);
});

test('15. reconcileAttemptDraft: pure reconciliation for mount-after-null, pending/unknown remount, explicit reconciliation, and revision guarding', () => {
  const dummyAttempt: PracticeAttemptDetail = {
    attemptId: 'att-1',
    practiceId: 'prac-1',
    classId: 'cls-1',
    ownerUserId: 'user-1',
    publishedVersionId: 'ver-1',
    publishedVersionNumber: 1,
    className: '10A1',
    title: 'Hàm số',
    topic: 'Toán',
    primaryTeacherName: 'Thầy Nam',
    questions: [
      { id: 'q1', type: 'single_choice', prompt: 'Q1', options: [{ id: 'opt-a', label: 'A', text: 'A' }, { id: 'opt-b', label: 'B', text: 'B' }] },
      { id: 'q2', type: 'single_choice', prompt: 'Q2', options: [{ id: 'opt-c', label: 'C', text: 'C' }] },
    ],
    savedAnswers: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-a' },
    },
    checkedFeedbacks: {
      q1: { questionId: 'q1', isCorrect: true, feedbackTitle: 'Đúng', explanation: 'Đúng rồi' },
    },
    lastSavedAt: '10:00:00',
    startedAt: '09:50:00',
    currentQuestionIndex: 0,
    isCompleted: false,
  };

  // 1. Mount after null (no draft): restores server attempt cleanly
  const resNoDraft = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: dummyAttempt,
    draft: null,
  });
  assert.equal(resNoDraft.ackStatus, 'saved');
  assert.equal(resNoDraft.isBlocked, false);
  assert.deepEqual(resNoDraft.answers, dummyAttempt.savedAnswers);
  assert.deepEqual(resNoDraft.lastAckedAnswers, dummyAttempt.savedAnswers);
  assert.equal(resNoDraft.lastAckedAt, '10:00:00');
  assert.equal(resNoDraft.hasUnsavedEdits, false);
  assert.equal(resNoDraft.feedbacks.q1?.isCorrect, true);

  // 2. Pending remount from disposed write: restores local pending edits, ackStatus='pending', isBlocked=false
  const pendingDraft = {
    pinnedContext: { actorId: 'user-1', classId: 'cls-1', practiceId: 'prac-1', attemptId: 'att-1', version: 1 },
    lastVisitedQuestionIndex: 1,
    localAnswers: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
      q2: { questionId: 'q2', singleChoiceValue: 'opt-c' },
    },
    confirmedAnswers: dummyAttempt.savedAnswers,
    checkedFeedbacks: {},
    checkedAnswerSnapshots: {},
    ackStatus: 'pending' as const,
    lastSavedAt: '10:00:00',
    updatedAt: Date.now(),
  };
  const resPending = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: dummyAttempt,
    draft: pendingDraft,
  });
  assert.equal(resPending.ackStatus, 'pending');
  assert.equal(resPending.isBlocked, false);
  assert.equal(resPending.hasUnsavedEdits, true);
  assert.deepEqual(resPending.answers, pendingDraft.localAnswers);
  assert.deepEqual(resPending.lastAckedAnswers, dummyAttempt.savedAnswers);
  assert.equal(resPending.lastVisitedQuestionIndex, 1);

  // 2b. Pending draft with unconfirmed sentSnapshot: must stay BLOCKED unknown (Check 4 of reconcile probe)
  const pendingWithSentDraft = {
    ...pendingDraft,
    sentSnapshot: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
    },
    ackStatus: 'pending' as const,
  };
  const resPendingSentUnconfirmed = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: dummyAttempt, // dummyAttempt has opt-a!
    draft: pendingWithSentDraft,
  });
  assert.equal(resPendingSentUnconfirmed.ackStatus, 'unknown');
  assert.equal(resPendingSentUnconfirmed.isBlocked, true);
  assert.match(resPendingSentUnconfirmed.blockedReason ?? '', /Chưa xác định/i);
  assert.deepEqual(resPendingSentUnconfirmed.answers, pendingWithSentDraft.localAnswers);

  // When server later confirms sentSnapshot, pending draft with sentSnapshot unblocks
  const resPendingSentConfirmed = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: {
      ...dummyAttempt,
      savedAnswers: { q1: { questionId: 'q1', singleChoiceValue: 'opt-b' } },
      lastSavedAt: '10:05:00',
    },
    draft: pendingWithSentDraft,
  });
  assert.equal(resPendingSentConfirmed.ackStatus, 'pending'); // q2 is still a newer local edit!
  assert.equal(resPendingSentConfirmed.isBlocked, false);
  assert.deepEqual(resPendingSentConfirmed.lastAckedAnswers, { q1: { questionId: 'q1', singleChoiceValue: 'opt-b' } });

  // 3. Unknown remount: server read does NOT match sentSnapshot -> stays blocked, no automatic retry
  const unknownDraft = {
    pinnedContext: { actorId: 'user-1', classId: 'cls-1', practiceId: 'prac-1', attemptId: 'att-1', version: 1 },
    lastVisitedQuestionIndex: 0,
    localAnswers: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
    },
    confirmedAnswers: dummyAttempt.savedAnswers,
    sentSnapshot: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
    },
    checkedFeedbacks: {},
    checkedAnswerSnapshots: {},
    ackStatus: 'unknown' as const,
    lastSavedAt: '10:00:00',
    updatedAt: Date.now(),
  };
  const resUnknown = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: dummyAttempt, // dummyAttempt.savedAnswers still has opt-a!
    draft: unknownDraft,
  });
  assert.equal(resUnknown.ackStatus, 'unknown');
  assert.equal(resUnknown.isBlocked, true);
  assert.match(resUnknown.blockedReason ?? '', /Chưa xác định/i);
  assert.deepEqual(resUnknown.answers, unknownDraft.localAnswers); // Local edits retained!
  assert.deepEqual(resUnknown.lastAckedAnswers, dummyAttempt.savedAnswers);

  // 4. Explicit reconciliation: authoritative server read DOES match sentSnapshot -> unblocks and establishes ACK
  const updatedServerAttempt: PracticeAttemptDetail = {
    ...dummyAttempt,
    savedAnswers: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
    },
    lastSavedAt: '10:05:00',
  };
  const resReconciled = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: updatedServerAttempt,
    draft: unknownDraft,
  });
  assert.equal(resReconciled.ackStatus, 'saved');
  assert.equal(resReconciled.isBlocked, false);
  assert.deepEqual(resReconciled.answers, updatedServerAttempt.savedAnswers);
  assert.deepEqual(resReconciled.lastAckedAnswers, updatedServerAttempt.savedAnswers);
  assert.equal(resReconciled.lastAckedAt, '10:05:00');

  // 4b. Known rejected write with sentSnapshot: remains error (NOT unknown) with preserved latest local answers
  const errorDraft = {
    pinnedContext: { actorId: 'user-1', classId: 'cls-1', practiceId: 'prac-1', attemptId: 'att-1', version: 1 },
    lastVisitedQuestionIndex: 0,
    localAnswers: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
    },
    confirmedAnswers: dummyAttempt.savedAnswers,
    sentSnapshot: {
      q1: { questionId: 'q1', singleChoiceValue: 'opt-b' },
    },
    checkedFeedbacks: {},
    checkedAnswerSnapshots: {},
    ackStatus: 'error' as const,
    lastErrorMessage: 'Lỗi máy chủ khi lưu bài',
    lastSavedAt: '10:00:00',
    updatedAt: Date.now(),
  };
  const resError = reconcileAttemptDraft({
    actorId: 'user-1',
    classId: 'cls-1',
    practiceId: 'prac-1',
    attempt: dummyAttempt, // dummyAttempt has opt-a!
    draft: errorDraft,
  });
  assert.equal(resError.ackStatus, 'error');
  assert.equal(resError.isBlocked, true);
  assert.equal(resError.blockedReason, 'Lỗi máy chủ khi lưu bài');
  assert.deepEqual(resError.answers, errorDraft.localAnswers); // Local edits retained!
  assert.deepEqual(resError.lastAckedAnswers, dummyAttempt.savedAnswers);

  // 5. Answer equality helpers
  assert.equal(areAnswersEqual({ questionId: 'q1', singleChoiceValue: 'A' }, { questionId: 'q1', singleChoiceValue: 'A' }), true);
  assert.equal(areAnswersEqual({ questionId: 'q1', singleChoiceValue: 'A' }, { questionId: 'q1', singleChoiceValue: 'B' }), false);
  assert.equal(areAnswersEqual({ questionId: 'q1', multipleChoiceValues: ['A', 'B'] }, { questionId: 'q1', multipleChoiceValues: ['B', 'A'] }), true);
  assert.equal(areAnswersEqual({ questionId: 'q1', multipleChoiceValues: ['A'] }, { questionId: 'q1', multipleChoiceValues: ['A', 'B'] }), false);
  assert.equal(areAnswersEqual({ questionId: 'q1', trueFalseValues: { s1: true } }, { questionId: 'q1', trueFalseValues: { s1: true } }), true);
  assert.equal(areAnswersEqual({ questionId: 'q1', trueFalseValues: { s1: true } }, { questionId: 'q1', trueFalseValues: { s1: false } }), false);
});

test('16. DraftStore invariants: explicit version miss returns null, unversioned clear removes all versions of attempt and preserves retries', () => {
  draftStore.clearAll();

  // Set version 1 and version 2 for attempt-1
  setAttemptDraft({
    pinnedContext: { actorId: 'u1', classId: 'c1', practiceId: 'p1', attemptId: 'att-1', version: 1 },
    lastVisitedQuestionIndex: 2,
    localAnswers: {},
    confirmedAnswers: {},
    checkedFeedbacks: {},
    checkedAnswerSnapshots: {},
    ackStatus: 'saved',
    updatedAt: Date.now(),
  });
  setAttemptDraft({
    pinnedContext: { actorId: 'u1', classId: 'c1', practiceId: 'p1', attemptId: 'att-1', version: 2 },
    lastVisitedQuestionIndex: 3,
    localAnswers: {},
    confirmedAnswers: {},
    checkedFeedbacks: {},
    checkedAnswerSnapshots: {},
    ackStatus: 'saved',
    updatedAt: Date.now(),
  });
  // Set distinct retry attempt-2
  setAttemptDraft({
    pinnedContext: { actorId: 'u1', classId: 'c1', practiceId: 'p1', attemptId: 'att-2', version: 1 },
    lastVisitedQuestionIndex: 1,
    localAnswers: {},
    confirmedAnswers: {},
    checkedFeedbacks: {},
    checkedAnswerSnapshots: {},
    ackStatus: 'saved',
    updatedAt: Date.now(),
  });

  // Verify explicit version lookup
  assert.equal(getAttemptDraft('u1', 'c1', 'p1', 'att-1', 1)?.lastVisitedQuestionIndex, 2);
  assert.equal(getAttemptDraft('u1', 'c1', 'p1', 'att-1', 2)?.lastVisitedQuestionIndex, 3);
  // Version miss MUST return null (never fall back to v1 or v2)
  assert.equal(getAttemptDraft('u1', 'c1', 'p1', 'att-1', 3), null);

  // Clearing att-1 removes every version of att-1
  clearAttemptDraft('u1', 'c1', 'p1', 'att-1');
  assert.equal(getAttemptDraft('u1', 'c1', 'p1', 'att-1', 1), null);
  assert.equal(getAttemptDraft('u1', 'c1', 'p1', 'att-1', 2), null);

  // Preserves distinct retry att-2!
  assert.equal(getAttemptDraft('u1', 'c1', 'p1', 'att-2', 1)?.lastVisitedQuestionIndex, 1);

  draftStore.clearAll();
});

test('17. SaveController: getLastSavedAnswers returns deep copy protecting internal ACK snapshot', async () => {
  const controller = new SaveController({
    saveFn: async () => ({ savedAt: '10:00:00' }),
  });
  controller.queueSave({ q1: { questionId: 'q1', singleChoiceValue: 'A' } });
  await controller.flush();
  const ack1 = controller.getLastSavedAnswers();
  assert.ok(ack1);
  assert.equal(ack1.q1.singleChoiceValue, 'A');
  // Mutating the returned object
  ack1.q1.singleChoiceValue = 'MUTATED';
  // Must NOT mutate internal ACK snapshot!
  const ack2 = controller.getLastSavedAnswers();
  assert.equal(ack2?.q1.singleChoiceValue, 'A');
  controller.dispose();
});

test('18. Practice Attempt lifecycle: in-flight save across navigation/remount, finish fail-closed guard, and volatile draft unmount persistence', async () => {
  draftStore.clearAll();

  const user = { id: 'u1' };
  const classId = 'c1';
  const practiceId = 'p1';
  const attemptId = 'att-1';
  const version = 1;

  // 1. In-flight save when leaving / unmounting:
  // When save starts, sentSnapshot is recorded.
  let sentSnapshot: Record<string, PracticeAnswer> | undefined;
  const deferredSave = createDeferred<{ savedAt: string }>();

  const controller = new SaveController({
    saveFn: async (answers) => {
      sentSnapshot = answers;
      // Persist immediate sentSnapshot
      setAttemptDraft({
        pinnedContext: { actorId: user.id, classId, practiceId, attemptId, version },
        lastVisitedQuestionIndex: 1,
        localAnswers: answers,
        confirmedAnswers: { q1: { questionId: 'q1', singleChoiceValue: 'A' } },
        sentSnapshot: answers,
        checkedFeedbacks: {},
        checkedAnswerSnapshots: {},
        ackStatus: 'pending',
        updatedAt: Date.now(),
      });
      return deferredSave.promise;
    },
  });

  // User selects option D for q2
  const edits = {
    q1: { questionId: 'q1', singleChoiceValue: 'A' },
    q2: { questionId: 'q2', singleChoiceValue: 'D' },
  };
  controller.queueSave(edits);

  assert.equal(controller.isSaving(), true);
  assert.deepEqual(sentSnapshot, edits);

  // Now user navigates away (Leave) while save is still in flight:
  // Unmount effect captures in-flight state and persists draft with ackStatus = 'unknown'
  if (controller.isSaving()) {
    setAttemptDraft({
      pinnedContext: { actorId: user.id, classId, practiceId, attemptId, version },
      lastVisitedQuestionIndex: 1,
      localAnswers: edits,
      confirmedAnswers: { q1: { questionId: 'q1', singleChoiceValue: 'A' } },
      sentSnapshot: edits,
      checkedFeedbacks: {},
      checkedAnswerSnapshots: {},
      ackStatus: 'unknown',
      updatedAt: Date.now(),
    });
  }
  controller.dispose();

  // 2. User returns (remounts) while backend has NOT yet acknowledged the save (still old answers)
  const draftOnRemount = getAttemptDraft(user.id, classId, practiceId, attemptId, version);
  assert.ok(draftOnRemount);
  assert.equal(draftOnRemount.ackStatus, 'unknown');
  assert.deepEqual(draftOnRemount.sentSnapshot, edits);

  const serverAttemptOld: PracticeAttemptDetail = {
    attemptId,
    practiceId,
    classId,
    ownerUserId: user.id,
    publishedVersionId: 'v1',
    publishedVersionNumber: version,
    className: '10A1',
    title: 'Hàm số',
    topic: 'Toán',
    primaryTeacherName: 'Thầy Nam',
    questions: [
      { id: 'q1', type: 'single_choice', prompt: 'Q1', options: [{ id: 'A', label: 'A', text: 'A' }] },
      { id: 'q2', type: 'single_choice', prompt: 'Q2', options: [{ id: 'D', label: 'D', text: 'D' }] },
    ],
    savedAnswers: { q1: { questionId: 'q1', singleChoiceValue: 'A' } },
    checkedFeedbacks: {},
    lastSavedAt: '10:00:00',
    startedAt: '09:50:00',
    currentQuestionIndex: 1,
    isCompleted: false,
  };

  const reconciledOnRemount = reconcileAttemptDraft({
    actorId: user.id,
    classId,
    practiceId,
    attempt: serverAttemptOld,
    draft: draftOnRemount,
  });

  // CRITICAL: Must be blocked, ackStatus unknown! Finish MUST NOT be permitted.
  assert.equal(reconciledOnRemount.isBlocked, true);
  assert.equal(reconciledOnRemount.ackStatus, 'unknown');

  // Verify finish guard blocks completion when isBlocked is true or ackStatus is unknown
  let finishCalled = false;
  const finishGuard = async (status: string, blocked: boolean, lastAcked: Record<string, PracticeAnswer>, local: Record<string, PracticeAnswer>) => {
    if (blocked || status === 'unknown' || status === 'error') {
      return { ok: false, reason: 'blocked_or_unknown' };
    }
    if (!areAnswerMapsEqual(lastAcked, local)) {
      return { ok: false, reason: 'unacked_answers' };
    }
    finishCalled = true;
    return { ok: true };
  };

  const finishAttempt1 = await finishGuard(
    reconciledOnRemount.ackStatus,
    reconciledOnRemount.isBlocked,
    reconciledOnRemount.lastAckedAnswers,
    reconciledOnRemount.answers
  );
  assert.equal(finishAttempt1.ok, false);
  assert.equal(finishAttempt1.reason, 'blocked_or_unknown');
  assert.equal(finishCalled, false);

  // 3. Status check / authoritative reload returns confirmed write:
  const serverAttemptAcked: PracticeAttemptDetail = {
    ...serverAttemptOld,
    savedAnswers: edits,
    lastSavedAt: '10:01:00',
  };

  const reconciledAfterAck = reconcileAttemptDraft({
    actorId: user.id,
    classId,
    practiceId,
    attempt: serverAttemptAcked,
    draft: draftOnRemount,
  });

  // Now reconciled is unblocked and saved!
  assert.equal(reconciledAfterAck.isBlocked, false);
  assert.equal(reconciledAfterAck.ackStatus, 'saved');
  assert.deepEqual(reconciledAfterAck.lastAckedAnswers, edits);

  // Finish guard now allows finish
  const finishAttempt2 = await finishGuard(
    reconciledAfterAck.ackStatus,
    reconciledAfterAck.isBlocked,
    reconciledAfterAck.lastAckedAnswers,
    reconciledAfterAck.answers
  );
  assert.equal(finishAttempt2.ok, true);
  assert.equal(finishCalled, true);

  draftStore.clearAll();
});


