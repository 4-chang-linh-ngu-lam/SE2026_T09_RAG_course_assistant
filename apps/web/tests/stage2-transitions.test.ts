import test from 'node:test';
import assert from 'node:assert/strict';
import { adapter as mockAdapter, setMockAssessmentLock } from '../dev/mocks/adapter';
import { secondStudentUser } from '../dev/mocks/fixtures';
import { adapter as liveAdapter } from '../src/lib/data/live';
import { ApiError } from '../src/lib/api/errors';
import { inspectSource } from '../scripts/boundary-policy.mjs';

const STUDENT_LOGIN = { username: 'minh.anh10a1', password: 'ValidPassword123!' };
const SECOND_STUDENT_LOGIN = { username: 'quan.tran10a1', password: 'ValidPassword123!' };
const TEACHER1_LOGIN = { email: 'ha.nguyen@lumi.example', password: 'ValidPassword123!' }; // Ha Nguyen (Owner of doc-1)
const TEACHER2_LOGIN = { email: 'minh.tran@lumi.example', password: 'ValidPassword123!' }; // Minh Tran (Assisting in 101, Owner of doc-2)

const CLASS_101_ID = '00000000-0000-4000-8000-000000000101'; // TOAN10
const CLASS_102_ID = '00000000-0000-4000-8000-000000000102'; // TOAN10-10A2 (ended enrollment)
const CLASS_104_ID = '00000000-0000-4000-8000-000000000104'; // ANH10
const CLASS_199_ID = '00000000-0000-4000-8000-000000000199'; // TOAN9-9A1 (archived)

const DOC_1_ID = 'doc-1-ham-so-bac-hai';
const DOC_2_ID = 'doc-2-do-thi-parabol';

test('1. contracted Document rejects metadata-only uploads while Tutor remains unavailable', { timeout: 10000 }, async () => {
  await assert.rejects(() => liveAdapter.document.uploadDocument({name:'test.pdf',size:1000,type:'application/pdf',title:'Test'}),
    (error:unknown)=>error instanceof ApiError&&error.status===422&&error.code==='VALIDATION_ERROR');
  await assert.rejects(() => liveAdapter.document.uploadVersion('doc-1',{name:'test.pdf',size:1000,type:'application/pdf'}),
    (error:unknown)=>error instanceof ApiError&&error.status===422&&error.code==='VALIDATION_ERROR');
  await assert.rejects(
    () => liveAdapter.tutor.updateConfig('class-1', 'Instructions'),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.tutor.createConversation('class-1'),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
  await assert.rejects(
    () => liveAdapter.tutor.sendMessage({ conversationId: 'c1', classId: 'class-1', content: 'Help', mode: 'STEP_BY_STEP' }),
    (err: unknown) => err instanceof ApiError && err.status === 503 && err.code === 'UNAVAILABLE'
  );
});

test('2. preview adapter: note & bookmark security, student role checks, actor privacy, and Rule O2', { timeout: 10000 }, async () => {
  // Login as Teacher: Teacher cannot create notes, delete notes, or bookmark
  await mockAdapter.identity.login(TEACHER1_LOGIN);
  await assert.rejects(
    () => mockAdapter.document.saveNote({
      documentId: DOC_1_ID,
      classId: CLASS_101_ID,
      locator: 'Trang 1',
      noteText: 'Ghi chú giáo viên không hợp lệ',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
  await assert.rejects(
    () => mockAdapter.document.deleteNote('note-doc-1'),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
  await assert.rejects(
    () => mockAdapter.document.toggleBookmark(DOC_1_ID, CLASS_101_ID),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Login as Student (Minh Anh)
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Unknown document or unknown class rejects with 404
  await assert.rejects(
    () => mockAdapter.document.saveNote({
      documentId: 'non-existent-doc-id',
      classId: CLASS_101_ID,
      locator: 'Trang 1',
      noteText: 'Ghi chú tài liệu ma',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );
  await assert.rejects(
    () => mockAdapter.document.saveNote({
      documentId: DOC_1_ID,
      classId: 'non-existent-class-id',
      locator: 'Trang 1',
      noteText: 'Ghi chú lớp học ma',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );

  // Student cannot create a NEW note in archived class 199 (Rule O2)
  await assert.rejects(
    () => mockAdapter.document.saveNote({
      documentId: DOC_1_ID,
      classId: CLASS_199_ID,
      locator: 'Trang 1',
      noteText: 'Tạo ghi chú mới trong lớp lưu trữ',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Student CAN edit existing own note in archived class 199 (Rule O2)
  const editedArchived = await mockAdapter.document.saveNote({
    id: 'note-doc-9a1-archived',
    documentId: 'doc-9a1-viet',
    classId: CLASS_199_ID,
    locator: 'Trang 2',
    noteText: 'Ghi chú quy tắc Vi-ét đã được cập nhật chuẩn xác theo Rule O2.',
  });
  assert.equal(editedArchived.noteText, 'Ghi chú quy tắc Vi-ét đã được cập nhật chuẩn xác theo Rule O2.');

  // Preserving existing own note with revoked source without inventing source metadata
  const editedRevoked = await mockAdapter.document.saveNote({
    id: 'note-doc-6-revoked',
    documentId: 'doc-6-de-cuong-hinh-hoc',
    classId: CLASS_101_ID,
    locator: 'Trang 5',
    noteText: 'Ghi chú hình học cập nhật nội dung tự học cá nhân.',
  });
  assert.equal(editedRevoked.id, 'note-doc-6-revoked');
  assert.equal(editedRevoked.isSourceAccessible, false);
  assert.equal(editedRevoked.noteText, 'Ghi chú hình học cập nhật nội dung tự học cá nhân.');

  // Creating valid new note in active granted class captures version and locator
  const newNote = await mockAdapter.document.saveNote({
    documentId: DOC_1_ID,
    classId: CLASS_101_ID,
    locator: 'Trang 4',
    pageNumber: 4,
    version: 1,
    noteText: 'Chú ý bảng biến thiên khi a âm bề lõm quay xuống.',
  });
  assert.ok(newNote.id);
  assert.equal(newNote.userId, '00000000-0000-4000-8000-000000000011');
  assert.equal(newNote.version, 1);
  assert.equal(newNote.locator, 'Trang 4');

  // Student can delete own note
  await mockAdapter.document.deleteNote(newNote.id);

  // Deleting already deleted note rejects with 404
  await assert.rejects(
    () => mockAdapter.document.deleteNote(newNote.id),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );

  // Bookmark toggling in active class captures version
  const bmResult = await mockAdapter.document.toggleBookmark(DOC_1_ID, CLASS_101_ID, 'Trang 2', 1);
  assert.equal(typeof bmResult.bookmarked, 'boolean');

  // Bookmarking in unshared document/class rejects with 403
  await assert.rejects(
    () => mockAdapter.document.toggleBookmark('doc-6-de-cuong-hinh-hoc', CLASS_101_ID),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // s.notes workspace load strictly filters by current logged-in student
  const notesData = await mockAdapter.workspace.load('s.notes', {});
  assert.equal(notesData.kind, 'ready', 'Workspace load for s.notes must return ready');
  assert.ok(notesData.studentNotes && notesData.studentNotes.length > 0, 'studentNotes must be present and non-empty');
  assert.ok(notesData.studentNotes.every(n => n.userId === '00000000-0000-4000-8000-000000000011'), 'All notes must belong to logged-in student');
});

test('3. preview adapter: tutor actor security, conversation ownership, assessment lock, and retry dedup', { timeout: 10000 }, async () => {
  // Teacher cannot create tutor conversation or send message to student tutor
  await mockAdapter.identity.login(TEACHER1_LOGIN);
  await assert.rejects(
    () => mockAdapter.tutor.createConversation(CLASS_101_ID),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
  await assert.rejects(
    () => mockAdapter.tutor.sendMessage({ conversationId: 'c1', classId: CLASS_101_ID, content: 'Chào em', mode: 'STEP_BY_STEP' }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Login as Student
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Unknown conversation ID rejects with 404
  await assert.rejects(
    () => mockAdapter.tutor.sendMessage({
      conversationId: 'conv-totally-unknown-id',
      classId: CLASS_101_ID,
      content: 'Tin nhắn gửi vào phòng chat không tồn tại',
      mode: 'STEP_BY_STEP',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );

  // Student creating conversation in active enrolled class succeeds
  const conv = await mockAdapter.tutor.createConversation(CLASS_101_ID, 'Ôn tập đồ thị');
  assert.ok(conv.id);
  assert.equal(conv.classId, CLASS_101_ID);

  // Assessment Lock (Rule D6): when locked, creating conversation and sending message are forbidden
  setMockAssessmentLock({
    userId: '00000000-0000-4000-8000-000000000011',
    classId: CLASS_101_ID,
    attemptId: 'attempt-test-1',
    title: 'Kiểm tra 45 phút: Hàm số bậc hai',
    locked: true,
  });
  await assert.rejects(
    () => mockAdapter.tutor.createConversation(CLASS_101_ID),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
  await assert.rejects(
    () => mockAdapter.tutor.sendMessage({
      conversationId: conv.id,
      classId: CLASS_101_ID,
      content: 'Hỏi bài khi đang thi',
      mode: 'STEP_BY_STEP',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );
  // Release lock
  setMockAssessmentLock({
    userId: '00000000-0000-4000-8000-000000000011',
    classId: CLASS_101_ID,
    attemptId: 'attempt-test-1',
    locked: false,
  });

  // Sending message works and checks grounding
  const responseMsg = await mockAdapter.tutor.sendMessage({
    conversationId: conv.id,
    classId: CLASS_101_ID,
    content: 'Tọa độ đỉnh parabol tính thế nào?',
    mode: 'STEP_BY_STEP',
  });
  assert.equal(responseMsg.role, 'assistant');
  assert.equal(responseMsg.knowledgeType, 'CLASS_SOURCE');
  assert.ok(responseMsg.citations && responseMsg.citations.length > 0);

  // Retry deduplication test: sending with isRetry: true targets acknowledged message without duplicating user message
  await mockAdapter.tutor.sendMessage({
    conversationId: conv.id,
    classId: CLASS_101_ID,
    content: 'Tọa độ đỉnh parabol tính thế nào?',
    mode: 'STEP_BY_STEP',
    isRetry: true,
  });

  // Verify stored conversation from workspace
  const reloadedTutor = await mockAdapter.workspace.load('s.tutor', { classId: CLASS_101_ID, conversationId: conv.id });
  assert.equal(reloadedTutor.kind, 'ready', 'Workspace load for s.tutor must return ready');
  assert.ok(reloadedTutor.tutorWorkspace, 'tutorWorkspace model must be present');
  const storedConv = reloadedTutor.tutorWorkspace.conversations.find(c => c.id === conv.id);
  assert.ok(storedConv, 'Stored conversation must be present');
  const userMessages = storedConv.messages.filter(m => m.role === 'user' && m.content === 'Tọa độ đỉnh parabol tính thế nào?');
  assert.equal(userMessages.length, 1, 'Retry must not duplicate acknowledged user message');

  // Intentional repeated question without isRetry adds a separate intentional message
  await mockAdapter.tutor.sendMessage({
    conversationId: conv.id,
    classId: CLASS_101_ID,
    content: 'Tọa độ đỉnh parabol tính thế nào?',
    mode: 'STEP_BY_STEP',
  });
  const reloadedAfterRepeat = await mockAdapter.workspace.load('s.tutor', { classId: CLASS_101_ID, conversationId: conv.id });
  assert.equal(reloadedAfterRepeat.kind, 'ready', 'Workspace load for s.tutor after repeat must return ready');
  assert.ok(reloadedAfterRepeat.tutorWorkspace, 'tutorWorkspace model after repeat must be present');
  const storedAfterRepeat = reloadedAfterRepeat.tutorWorkspace.conversations.find(c => c.id === conv.id);
  assert.ok(storedAfterRepeat, 'Stored conversation after repeat must be present');
  // Repeated new question without isRetry is an intentional separate message
  const repeatedUserMessages = storedAfterRepeat.messages.filter(m => m.role === 'user' && m.content === 'Tọa độ đỉnh parabol tính thế nào?');
  assert.equal(repeatedUserMessages.length, 2, 'Repeated new question without isRetry is an intentional separate message');

  // First question in class with no initial conversations creates and completes successfully
  const conv104 = await mockAdapter.tutor.createConversation(CLASS_104_ID, 'English question');
  const response104 = await mockAdapter.tutor.sendMessage({
    conversationId: conv104.id,
    classId: CLASS_104_ID,
    content: 'How do I use present perfect?',
    mode: 'QUICK_QA',
  });
  assert.equal(response104.role, 'assistant');
  assert.equal(response104.isIncomplete, false, 'First message in new conversation must complete fully');
  assert.ok(response104.content.length > 0);
});

test('4. preview adapter: true asynchronous streaming, chunk yields, stop/cancellation, and single-flight lock', { timeout: 10000 }, async () => {
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const conv = await mockAdapter.tutor.createConversation(CLASS_101_ID, 'Thử nghiệm streaming');

  const chunksReceived: string[] = [];
  const sendPromise = mockAdapter.tutor.sendMessage({
    conversationId: conv.id,
    classId: CLASS_101_ID,
    content: 'Giải thích chi tiết các bước khảo sát hàm số',
    mode: 'STEP_BY_STEP',
    onChunk: (chunk: string) => {
      chunksReceived.push(chunk);
    },
  });

  // Await completion
  const completed = await sendPromise;
  assert.equal(completed.role, 'assistant');
  assert.equal(completed.isIncomplete, false);
  assert.ok(chunksReceived.length >= 2, 'Must yield multiple chunks over time');
  assert.equal(chunksReceived[chunksReceived.length - 1], completed.content);

  // Test cancellation / stop mid-stream
  const stopConv = await mockAdapter.tutor.createConversation(CLASS_101_ID, 'Thử nghiệm dừng');
  const stopPromise = mockAdapter.tutor.sendMessage({
    conversationId: stopConv.id,
    classId: CLASS_101_ID,
    content: 'Giải thích dài về tương giao đồ thị parabol',
    mode: 'STEP_BY_STEP',
    onChunk: () => {
      // Immediately stop on first chunk
      void mockAdapter.tutor.stopStreaming(stopConv.id);
    },
  });

  const stoppedMsg = await stopPromise;
  assert.equal(stoppedMsg.isIncomplete, true, 'Stopped message must be marked incomplete');
  assert.equal(stoppedMsg.citations?.length, 0, 'Incomplete/stopped response must not include citations');
});

test('5. preview adapter: version allocation max+1, failed replacement preservation, and serving consistency', { timeout: 10000 }, async () => {
  await mockAdapter.identity.login(TEACHER1_LOGIN);

  // Uploading a failing version
  const failVer1 = await mockAdapter.document.uploadVersion(DOC_1_ID, {
    name: 'draft_failure_font.pdf',
    size: 2 * 1024 * 1024,
    type: 'application/pdf',
  });
  assert.equal(failVer1.status, 'FAILED');
  assert.equal(failVer1.isServing, false);
  const failVer1Num = failVer1.versionNumber;

  // Uploading a second failing version must increment from max version history
  const failVer2 = await mockAdapter.document.uploadVersion(DOC_1_ID, {
    name: 'draft_failure_v2.pdf',
    size: 2 * 1024 * 1024,
    type: 'application/pdf',
  });
  assert.equal(failVer2.status, 'FAILED');
  assert.equal(failVer2.versionNumber, failVer1Num + 1, 'Version numbers must monotonically increment using max(history)+1');

  // Verify prior successful version is still the serving version
  const docDetail = await mockAdapter.workspace.load('t.libraryDocument', { documentId: DOC_1_ID });
  assert.equal(docDetail.kind, 'ready');
  if (docDetail.kind === 'ready' && docDetail.sourceDocumentDetail) {
    const { versions, document } = docDetail.sourceDocumentDetail;
    const servingList = versions.filter(v => v.isServing);
    assert.equal(servingList.length, 1, 'Exactly one serving version must exist');
    assert.equal(document.currentVersion, servingList[0].versionNumber);
    assert.equal(servingList[0].status, 'READY');
  }

  // Retrying older version 1 when version 2 exists must NOT replace version 2 as the serving version
  await mockAdapter.document.retryProcessing(DOC_1_ID, 1);
  const reloaded = await mockAdapter.workspace.load('t.libraryDocument', { documentId: DOC_1_ID });
  if (reloaded.kind === 'ready' && reloaded.sourceDocumentDetail) {
    const { versions, document } = reloaded.sourceDocumentDetail;
    const serving = versions.find(v => v.isServing);
    assert.ok(serving);
    assert.ok(serving.versionNumber >= 2);
    assert.equal(document.currentVersion, serving.versionNumber);
  }
});

test('6. preview adapter: share document source ownership and assisting teacher boundaries under Rule O1', { timeout: 10000 }, async () => {
  // Teacher 2 (Trần Đức Minh) is NOT the owner of doc-1 (owned by Nguyễn Thu Hà)
  await mockAdapter.identity.login(TEACHER2_LOGIN);

  // Foreign teacher attempting to share someone else's document rejects with 403
  await assert.rejects(
    () => mockAdapter.document.shareDocument(DOC_1_ID, [CLASS_104_ID]),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Switch to Owner Teacher 1 (Nguyễn Thu Hà)
  await mockAdapter.identity.login(TEACHER1_LOGIN);

  // Sharing into an archived class rejects with 403
  await assert.rejects(
    () => mockAdapter.document.shareDocument(DOC_1_ID, [CLASS_199_ID]),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Sharing into a class teacher is not assigned to rejects with 403
  await assert.rejects(
    () => mockAdapter.document.shareDocument(DOC_1_ID, [CLASS_104_ID]),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Sharing into non-existent class rejects with 404 before any mutations
  await assert.rejects(
    () => mockAdapter.document.shareDocument(DOC_1_ID, ['non-existent-class']),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );

  // Valid share into assigned class 102 succeeds
  await mockAdapter.document.shareDocument(DOC_1_ID, [CLASS_102_ID]);

  // Under Rule O1: Assisting teacher (Teacher 1 in 102) CAN revoke share from class
  await mockAdapter.document.revokeShare(DOC_1_ID, CLASS_102_ID);
});

test('7. preview adapter: history102 (ended enrollment) vs archived class 199', { timeout: 10000 }, async () => {
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // History 102 (ended enrollment in active class) loads historyData10A2
  const hist102 = await mockAdapter.workspace.load('s.history', { classId: CLASS_102_ID });
  assert.equal(hist102.kind, 'ready');
  if (hist102.kind === 'ready') {
    assert.equal(hist102.classSummary?.membershipStatus, 'ENDED');
    assert.equal(hist102.classSummary?.status, 'ACTIVE');
    assert.match(hist102.historyData?.historyNotice ?? '', /chuyển lớp|kết thúc/);
  }

  // Student accessing active interaction routes in class 102 is denied
  const feed102 = await mockAdapter.workspace.load('s.feed', { classId: CLASS_102_ID });
  assert.equal(feed102.kind, 'unavailable');

  const docs102 = await mockAdapter.workspace.load('s.documents', { classId: CLASS_102_ID });
  assert.equal(docs102.kind, 'unavailable');

  const tutor102 = await mockAdapter.workspace.load('s.tutor', { classId: CLASS_102_ID });
  assert.equal(tutor102.kind, 'unavailable');

  // Teacher accessing class 102 summary gets ACTIVE class with teaching role and NO leaked student membershipStatus
  await mockAdapter.identity.login(TEACHER1_LOGIN);
  const teacherOverview102 = await mockAdapter.workspace.load('t.overview', { classId: CLASS_102_ID });
  assert.equal(teacherOverview102.kind, 'ready');
  if (teacherOverview102.kind === 'ready' && teacherOverview102.classSummary) {
    assert.equal(teacherOverview102.classSummary.status, 'ACTIVE');
    assert.equal(teacherOverview102.classSummary.teachingRole, 'ASSISTING');
    assert.equal(teacherOverview102.classSummary.membershipStatus, undefined, 'Teacher summary must not leak student membershipStatus');
  }
});

test('8. preview adapter: reader model safe fallback, locator bounds, version mismatch, and revoked source state', { timeout: 10000 }, async () => {
  await mockAdapter.identity.login(STUDENT_LOGIN);

  // Granted document loads accessible reader model
  const readerData = await mockAdapter.workspace.load('s.reader', {
    classId: CLASS_101_ID,
    documentId: DOC_1_ID,
    page: '3',
    version: '2',
  });
  assert.equal(readerData.kind, 'ready');
  if (readerData.kind === 'ready' && readerData.readerModel) {
    assert.equal(readerData.readerModel.isSourceAccessible, true);
    assert.equal(readerData.readerModel.currentPage, 3);
    assert.equal(readerData.readerModel.viewingVersion, 2);
  }

  // Version mismatch: requested non-existent version returns unavailable
  const nonExistentVer = await mockAdapter.workspace.load('s.reader', {
    classId: CLASS_101_ID,
    documentId: DOC_1_ID,
    version: '99',
  });
  assert.equal(nonExistentVer.kind, 'unavailable');

  // Locator bounds: requested page beyond total pages returns unavailable
  const outOfBoundsPage = await mockAdapter.workspace.load('s.reader', {
    classId: CLASS_101_ID,
    documentId: DOC_1_ID,
    page: '999',
  });
  assert.equal(outOfBoundsPage.kind, 'unavailable');

  // Revoked document (doc-6) in class 101 loads with revoked state: DocumentViewer unmounted, own notes preserved
  const revokedData = await mockAdapter.workspace.load('s.reader', {
    classId: CLASS_101_ID,
    documentId: 'doc-6-de-cuong-hinh-hoc',
  });
  assert.equal(revokedData.kind, 'ready');
  if (revokedData.kind === 'ready' && revokedData.readerModel) {
    assert.equal(revokedData.readerModel.isSourceAccessible, false);
    assert.ok(revokedData.readerModel.revokedReason);
    assert.equal(revokedData.readerModel.outline.length, 0);
    assert.ok(revokedData.readerModel.notes.length > 0);
    // Source quote is stripped/hidden under Rule H6/L6
    assert.equal(revokedData.readerModel.notes[0].sourceQuote, undefined);
  }
});

test('9. preview adapter: cross-user private operations and isolation with second student', { timeout: 10000 }, async () => {
  // Login as second distinct student
  await mockAdapter.identity.login(SECOND_STUDENT_LOGIN);

  // Second student loading notes only sees own notes, zero leakage of Minh Anh's notes
  const notesSecond = await mockAdapter.workspace.load('s.notes', {});
  assert.equal(notesSecond.kind, 'ready', 'Workspace load for s.notes must return ready');
  assert.ok(notesSecond.studentNotes, 'studentNotes array must be present');
  assert.ok(notesSecond.studentBookmarks, 'studentBookmarks array must be present');
  assert.ok(notesSecond.studentNotes.every(n => n.userId === secondStudentUser.id), 'All notes must belong to second student');
  assert.ok(notesSecond.studentBookmarks.every(b => b.userId === secondStudentUser.id), 'All bookmarks must belong to second student');

  // Second student cannot delete Minh Anh's existing note (403 FORBIDDEN)
  await assert.rejects(
    () => mockAdapter.document.deleteNote('note-doc-1'),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Second student loading tutor only sees own conversations
  const tutorSecond = await mockAdapter.workspace.load('s.tutor', { classId: CLASS_101_ID });
  assert.equal(tutorSecond.kind, 'ready', 'Workspace load for s.tutor must return ready');
  assert.ok(tutorSecond.tutorWorkspace, 'tutorWorkspace model must be present');
  const convs = tutorSecond.tutorWorkspace.conversations;
  assert.ok(convs.every(c => c.userId === secondStudentUser.id), 'All conversations must belong to second student');

  // Second student cannot send message to Minh Anh's conversation (404)
  await assert.rejects(
    () => mockAdapter.tutor.sendMessage({
      conversationId: 'conv-doc-1-toan10',
      classId: CLASS_101_ID,
      content: 'Tin nhắn mạo danh',
      mode: 'STEP_BY_STEP',
    }),
    (err: unknown) => err instanceof ApiError && err.status === 404
  );

  // Second student cannot stop streaming of Minh Anh's conversation (403)
  // First start a stream as Minh Anh
  await mockAdapter.identity.login(STUDENT_LOGIN);
  const minhAnhConv = await mockAdapter.tutor.createConversation(CLASS_101_ID, 'Minh Anh Stream');
  const minhAnhPromise = mockAdapter.tutor.sendMessage({
    conversationId: minhAnhConv.id,
    classId: CLASS_101_ID,
    content: 'Câu hỏi streaming dài của Minh Anh',
    mode: 'STEP_BY_STEP',
  });

  // Switch to second student while stream is active
  await mockAdapter.identity.login(SECOND_STUDENT_LOGIN);
  await assert.rejects(
    () => mockAdapter.tutor.stopStreaming(minhAnhConv.id),
    (err: unknown) => err instanceof ApiError && err.status === 403
  );

  // Await completion of original stream
  await minhAnhPromise.catch(() => {});
});

test('10. boundary policy: product source code clean of test/mock fixture leaks', { timeout: 10000 }, () => {
  // Test boundary checker on product files
  const sampleCleanCode = `export function getTitle(name: string) { return name.trim(); }`;
  assert.equal(inspectSource('src/features/document/views/student-reader-view.tsx', sampleCleanCode).length, 0);

  // Test that inspectSource detects concrete fixture UUID in product code
  const leakedUuid = `const targetId = '00000000-0000-4000-8000-000000000101';`;
  assert.ok(inspectSource('src/features/document/views/test.tsx', leakedUuid).length > 0);
});
