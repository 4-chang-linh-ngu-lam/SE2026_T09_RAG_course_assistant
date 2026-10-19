import { createIntelligencePort } from './intelligence';
import { auditedPort, readPreviewAudit } from './audit';
import { createDataRequestReview } from './data-request-review';
import { readLearningEvidence } from './evidence';
import { notifyAuthenticationLost } from '../../src/lib/auth-events';
import { createClassroomAdminPort, previewClassroomStore } from './classroom-admin';
import { recordLearningEvidence } from './evidence';
import { createPracticeAuthoringPort } from './practice-authoring';
import { previewAccountStore } from './accounts';
import { createAccountsPort } from './accounts';
import { createAssignmentPort } from './assignment';
import { createAssessmentPort } from './assessment';
import type { DataAdapter } from '../../src/lib/data/port';
import type {
  BookmarkItem,
  CalendarEvent,
  CitationItem,
  ClassDocumentGrant,
  ClassOverviewData,
  ClassSummary,
  DataRequest,
  DocumentCapabilityPolicy,
  DocumentFormat,
  DocumentItem,
  DocumentReaderModel,
  DocumentVersion,
  FeedComment,
  FeedPost,
  NotificationItem,
  PersonalNoteItem,
  TeacherTutorInstructionConfig,
  TutorConversation,
  TutorMessage,
  User,
  PracticeActivity,
  PracticeAnswer,
  PracticeAttemptDetail,
  PracticeQuestion,
  PracticeQuestionFeedback,
  PracticeResultDetail,
  PracticeResultQuestionItem,
  PublishedPracticeVersion,
  TeacherActivityItem,
  TeacherActivityListModel,
  TeacherPracticeEditorModel,
} from '../../src/lib/domain';
import { ApiError } from '../../src/lib/api/errors';
import {
  setMockAssessmentLock,
  isMockAssessmentLocked,
  getMockAssessmentLockInfo,
  clearMockAssessmentLocks,
} from './assessment-lock';
export { setMockAssessmentLock, isMockAssessmentLocked, clearMockAssessmentLocks };
import {
  classOverviewData,
  classes,
  documentCapabilityPolicy,
  fixtureCanary,
  historyData10A2,
  historyData9A1,
  initialBookmarks,
  initialCalendarEvents,
  initialFeedPosts,
  initialNotifications,
  initialPersonalNotes,
  initialPracticeActivities,
  initialPracticeAttempts,
  initialPracticeResults,
  initialPublishedPracticeVersions,
  initialTeacherActivities,
  initialTeacherPracticeEditors,
  initialTeacherTutorConfigs,
  initialTutorConversations,
  mockDocumentGrants,
  mockDocumentVersions,
  mockDocuments,
  mockReaderModels,
  previewDisplayDate,
  rows,
  schoolId,
  studentHomeOverview,
  teacherHomeOverview,
  users,
} from './fixtures';

if (process.env.NODE_ENV === 'production') throw new Error('Development fixtures cannot run in production');

let current: User | null = null;
let currentSessionRevision = -1;
let requests: DataRequest[] = [];
let feedPosts: FeedPost[] = structuredClone(initialFeedPosts);
let calendarEvents: CalendarEvent[] = structuredClone(initialCalendarEvents);
let notifications: NotificationItem[] = structuredClone(initialNotifications);

// Stage 2 stateful mock stores:
let documents: DocumentItem[] = structuredClone(mockDocuments);
let documentVersions: Record<string, DocumentVersion[]> = structuredClone(mockDocumentVersions);
let documentGrants: Record<string, ClassDocumentGrant[]> = structuredClone(mockDocumentGrants);
let personalNotes: PersonalNoteItem[] = structuredClone(initialPersonalNotes);
let bookmarks: BookmarkItem[] = structuredClone(initialBookmarks);

// Stage 3a stateful learning stores:
let practiceActivities: PracticeActivity[] = structuredClone(initialPracticeActivities);
let practiceAttempts: Record<string, PracticeAttemptDetail> = structuredClone(initialPracticeAttempts);
let practiceResults: Record<string, PracticeResultDetail> = structuredClone(initialPracticeResults);
let publishedPracticeVersions: Record<string, PublishedPracticeVersion> = structuredClone(initialPublishedPracticeVersions);
let teacherActivities: TeacherActivityItem[] = structuredClone(initialTeacherActivities);
let teacherPracticeEditors: Record<string, TeacherPracticeEditorModel> = structuredClone(initialTeacherPracticeEditors);


for (const result of Object.values(practiceResults)) {
  const match = result.completedAt.match(/^(\d{2})\/(\d{2})\/(\d{4})(?: (\d{2}):(\d{2}))?/);
  const at = match ? `${match[3]}-${match[2]}-${match[1]}T${match[4] ?? '00'}:${match[5] ?? '00'}:00+07:00` : result.completedAt;
  recordLearningEvidence({ id: result.attemptId, kind: 'PRACTICE', classId: result.classId, studentId: result.ownerUserId, resourceId: result.practiceId, studentHref: `/student/classes/${result.classId}/practice/${result.practiceId}/attempts/${result.attemptId}/result`, title: result.title, topic: practiceActivities.find(item => item.id === result.practiceId)?.topic ?? 'Luyện tập', occurredAt: at, gradeVersion: 1, score: result.score.correct, maxScore: Math.max(1, result.score.total) });
}

// Initialize tutor conversations keyed by `${userId}:${classId}` to guarantee actor isolation
const initialTutorStore: Record<string, TutorConversation[]> = {};
for (const [classId, convs] of Object.entries(initialTutorConversations)) {
  const studentId = users[0].id;
  initialTutorStore[`${studentId}:${classId}`] = structuredClone(convs);
}
let tutorConversations: Record<string, TutorConversation[]> = initialTutorStore;
let teacherTutorConfigs: Record<string, TeacherTutorInstructionConfig> = structuredClone(initialTeacherTutorConfigs);

type StreamEntry = { userId: string; classId: string; aborted: boolean };
const activeStreams = new Map<string, StreamEntry>();

function signedIn(): User {
  if (!current) throw new ApiError('UNAUTHENTICATED', 'Vui lòng đăng nhập.', 401);
  const latest = previewAccountStore.user(current.id);
  if (!latest || latest.status !== 'ACTIVE' || currentSessionRevision !== previewAccountStore.sessionRevision(current.id)) { current = null; currentSessionRevision = -1; notifyAuthenticationLost(); throw new ApiError('UNAUTHENTICATED', 'Phiên đăng nhập không còn hiệu lực.', 401); }
  current = latest;
  return current;
}

// All journeys read the same current enrollment and teaching assignments.
const getStudentActiveClassIds = (id: string) => previewClassroomStore.studentActiveClassIds(id);
const getStudentEndedClassIds = (id: string) => previewClassroomStore.studentEndedClassIds(id);
const getStudentArchivedClassIds = (id: string) => previewClassroomStore.studentArchivedClassIds(id);
const getTeacherAssignedClassIds = (id: string) => previewClassroomStore.teacherAssignedClassIds(id);

function requireClassInteraction(classId: string, actor: User, teacherOnly = false): ClassSummary {
  const cls = previewClassroomStore.getClass(classId);
  if (!cls) throw new ApiError('NOT_FOUND', 'Không tìm thấy lớp học.', 404);
  const assigned = actor.roles.includes('LECTURER') && Boolean(previewClassroomStore.teachingRole(actor.id, classId));
  const enrolled = !teacherOnly && actor.roles.includes('STUDENT') && getStudentActiveClassIds(actor.id).includes(classId);
  if (cls.status !== 'ACTIVE' || (!assigned && !enrolled)) throw new ApiError('FORBIDDEN', 'Bạn không còn quyền thao tác trong lớp học này.', 403);
  return cls;
}

// Sanitization helpers for dynamic recomputation of source accessibility on every returned note/bookmark
function sanitizeNoteForStudent(note: PersonalNoteItem): PersonalNoteItem {
  const cloned = structuredClone(note);
  const doc = documents.find(d => d.id === note.documentId);
  const cls = previewClassroomStore.getClass(note.classId);
  cloned.classStatus = cls?.status ?? 'ARCHIVED';
  cloned.className = cls?.name ?? cloned.className;
  const version = note.version ?? (documentGrants[note.documentId] ?? []).find(g => g.classId === note.classId)?.servingVersion;
  const isDocActiveAndGranted = Boolean(doc && version && previewContext.sourceAccessible(note.userId ?? signedIn().id, note.classId, note.documentId, version));

  if (!isDocActiveAndGranted) {
    cloned.isSourceAccessible = false;
    cloned.sourceQuote = undefined;
  } else {
    cloned.isSourceAccessible = true;
  }
  return cloned;
}

function sanitizeBookmarkForStudent(bm: BookmarkItem): BookmarkItem {
  const cloned = structuredClone(bm);
  const doc = documents.find(d => d.id === bm.documentId);
  cloned.className = previewClassroomStore.getClass(bm.classId)?.name ?? cloned.className;
  const version = bm.version ?? (documentGrants[bm.documentId] ?? []).find(g => g.classId === bm.classId)?.servingVersion;
  const isDocActiveAndGranted = Boolean(doc && version && previewContext.sourceAccessible(bm.userId ?? signedIn().id, bm.classId, bm.documentId, version));
  cloned.isSourceAccessible = isDocActiveAndGranted;
  return cloned;
}

function currentDocumentView(doc: DocumentItem, actor: User): DocumentItem {
  const value = structuredClone(doc);
  if (doc.ownerId !== actor.id) delete value.sharedClasses;
  else value.sharedClasses = value.sharedClasses?.map(grant => ({ ...grant, className: previewClassroomStore.getClass(grant.classId)?.name ?? grant.className }));
  return value;
}
function getTeacherClassSummary(cls: ClassSummary, userId: string): ClassSummary {
  const cloned = previewClassroomStore.getClass(cls.id) ?? structuredClone(cls);
  delete cloned.membershipStatus;
  const role = previewClassroomStore.teachingRole(userId, cls.id);
  if (role) cloned.teachingRole = role; else delete cloned.teachingRole;
  return cloned;
}

function getClassPrimaryTeacherName(classId: string): string {
  const cls = classes.find(c => c.id === classId);
  return cls?.teacherName ?? 'Giáo viên phụ trách';
}

function getAvailableClassSources(classId: string): { id: string; title: string; version: number; isReady: boolean }[] {
  const sources: { id: string; title: string; version: number; isReady: boolean }[] = [];
  for (const doc of documents) {
    const grants = documentGrants[doc.id] ?? [];
    const grant = grants.find(g => g.classId === classId && g.isShared);
    if (grant) {
      const vers = documentVersions[doc.id] ?? [];
      const servingVer = vers.find(v => v.versionNumber === grant.servingVersion);
      const isReady = Boolean(servingVer && servingVer.status === 'READY');
      sources.push({
        id: doc.id,
        title: doc.title,
        version: grant.servingVersion,
        isReady,
      });
    }
  }
  return sources;
}

function sanitizeQuestionSource<T extends PracticeQuestion | PracticeResultQuestionItem | PracticeQuestionFeedback>(
  item: T,
  classId: string,
  userId: string
): T {
  const cloned = structuredClone(item);
  if (!cloned.sourceRef) {
    if (cloned.sourceReference !== undefined) {
      cloned.sourceReference = undefined;
    }
    return cloned;
  }

  const isAccessible = previewContext.sourceAccessible(userId, classId, cloned.sourceRef.documentId, cloned.sourceRef.versionNumber);

  cloned.sourceRef.isAccessible = isAccessible;
  if (!isAccessible) {
    cloned.sourceRef.displayText = 'Tài liệu không còn khả dụng';
    cloned.sourceReference = undefined;
  }
  return cloned;
}

function validatePracticeAnswer(
  question: PracticeQuestion,
  answer: PracticeAnswer,
  options: { requireComplete?: boolean }
): void {
  if (answer.questionId !== question.id) {
    throw new ApiError('VALIDATION_ERROR', 'ID câu hỏi không khớp với câu trả lời.', 400);
  }

  if (question.type === 'single_choice') {
    if (answer.multipleChoiceValues !== undefined || answer.trueFalseValues !== undefined || answer.shortAnswerValue !== undefined) {
      throw new ApiError('VALIDATION_ERROR', 'Hình dạng câu trả lời không khớp với loại câu hỏi trắc nghiệm một đáp án.', 400);
    }
    if (answer.singleChoiceValue !== undefined) {
      if (typeof answer.singleChoiceValue !== 'string') {
        throw new ApiError('VALIDATION_ERROR', 'Giá trị lựa chọn phải là chuỗi ký tự.', 400);
      }
      if (answer.singleChoiceValue.length > 0) {
        const optionExists = question.options.some(o => o.id === answer.singleChoiceValue);
        if (!optionExists) {
          throw new ApiError('VALIDATION_ERROR', 'Lựa chọn không tồn tại trong câu hỏi này.', 400);
        }
      }
    }
    if (options.requireComplete) {
      if (!answer.singleChoiceValue || answer.singleChoiceValue.trim().length === 0) {
        throw new ApiError('VALIDATION_ERROR', 'Vui lòng chọn một đáp án.', 400);
      }
    }
  } else if (question.type === 'multiple_choice') {
    if (answer.singleChoiceValue !== undefined || answer.trueFalseValues !== undefined || answer.shortAnswerValue !== undefined) {
      throw new ApiError('VALIDATION_ERROR', 'Hình dạng câu trả lời không khớp với loại câu hỏi trắc nghiệm nhiều đáp án.', 400);
    }
    if (answer.multipleChoiceValues !== undefined) {
      if (!Array.isArray(answer.multipleChoiceValues)) {
        throw new ApiError('VALIDATION_ERROR', 'Giá trị lựa chọn phải là mảng.', 400);
      }
      const uniqueVals = new Set(answer.multipleChoiceValues);
      if (uniqueVals.size !== answer.multipleChoiceValues.length) {
        throw new ApiError('VALIDATION_ERROR', 'Không được chứa các lựa chọn trùng lặp.', 400);
      }
      for (const val of answer.multipleChoiceValues) {
        if (typeof val !== 'string' || !question.options.some(o => o.id === val)) {
          throw new ApiError('VALIDATION_ERROR', 'Tồn tại lựa chọn không thuộc câu hỏi này.', 400);
        }
      }
    }
    if (options.requireComplete) {
      if (!answer.multipleChoiceValues || answer.multipleChoiceValues.length === 0) {
        throw new ApiError('VALIDATION_ERROR', 'Vui lòng chọn ít nhất một đáp án.', 400);
      }
    }
  } else if (question.type === 'true_false') {
    if (answer.singleChoiceValue !== undefined || answer.multipleChoiceValues !== undefined || answer.shortAnswerValue !== undefined) {
      throw new ApiError('VALIDATION_ERROR', 'Hình dạng câu trả lời không khớp với loại câu hỏi đúng sai.', 400);
    }
    if (answer.trueFalseValues !== undefined) {
      if (typeof answer.trueFalseValues !== 'object' || answer.trueFalseValues === null || Array.isArray(answer.trueFalseValues)) {
        throw new ApiError('VALIDATION_ERROR', 'Giá trị đúng/sai phải là đối tượng theo từng nhận định.', 400);
      }
      for (const [stId, val] of Object.entries(answer.trueFalseValues)) {
        if (!question.statements.some(st => st.id === stId)) {
          throw new ApiError('VALIDATION_ERROR', `Nhận định "${stId}" không tồn tại trong câu hỏi này.`, 400);
        }
        if (typeof val !== 'boolean') {
          throw new ApiError('VALIDATION_ERROR', 'Giá trị nhận định phải là boolean (Đúng hoặc Sai).', 400);
        }
      }
    }
    if (options.requireComplete) {
      if (!answer.trueFalseValues) {
        throw new ApiError('VALIDATION_ERROR', 'Vui lòng trả lời các mệnh đề Đúng/Sai.', 400);
      }
      const allStatementsAnswered = question.statements.every(
        st => typeof answer.trueFalseValues?.[st.id] === 'boolean'
      );
      if (!allStatementsAnswered) {
        throw new ApiError('VALIDATION_ERROR', 'Vui lòng hoàn thành toàn bộ các mệnh đề Đúng/Sai trước khi kiểm tra.', 400);
      }
    }
  } else if (question.type === 'short_answer') {
    if (answer.singleChoiceValue !== undefined || answer.multipleChoiceValues !== undefined || answer.trueFalseValues !== undefined) {
      throw new ApiError('VALIDATION_ERROR', 'Hình dạng câu trả lời không khớp với loại câu hỏi trả lời ngắn.', 400);
    }
    if (answer.shortAnswerValue !== undefined) {
      if (typeof answer.shortAnswerValue !== 'string') {
        throw new ApiError('VALIDATION_ERROR', 'Câu trả lời ngắn phải là chuỗi ký tự.', 400);
      }
    }
    if (options.requireComplete) {
      if (!answer.shortAnswerValue || answer.shortAnswerValue.trim().length === 0) {
        throw new ApiError('VALIDATION_ERROR', 'Vui lòng nhập câu trả lời ngắn.', 400);
      }
    }
  }
}

function validateQuestionForPublication(q: PracticeQuestion): void {
  if (!q.id || !q.id.trim()) {
    throw new ApiError('VALIDATION_ERROR', 'Mã câu hỏi không được để trống.', 400);
  }
  if (!q.prompt || !q.prompt.trim()) {
    throw new ApiError('VALIDATION_ERROR', 'Nội dung câu hỏi không được để trống.', 400);
  }
  if (!q.topic || !q.topic.trim()) {
    throw new ApiError('VALIDATION_ERROR', 'Chủ đề câu hỏi không được để trống.', 400);
  }
  if (typeof q.points !== 'number' || !Number.isFinite(q.points) || q.points <= 0) {
    throw new ApiError('VALIDATION_ERROR', 'Điểm số câu hỏi phải lớn hơn 0.', 400);
  }
  if (q.type === 'single_choice') {
    if (!Array.isArray(q.options) || q.options.length < 2) {
      throw new ApiError('VALIDATION_ERROR', 'Câu hỏi trắc nghiệm một đáp án phải có ít nhất 2 lựa chọn.', 400);
    }
    const optIds = new Set<string>();
    for (const opt of q.options) {
      if (!opt.id || !opt.id.trim() || !opt.text || !opt.text.trim()) {
        throw new ApiError('VALIDATION_ERROR', 'Lựa chọn không được để trống ID hoặc nội dung.', 400);
      }
      if (optIds.has(opt.id)) {
        throw new ApiError('VALIDATION_ERROR', 'Các lựa chọn trong câu hỏi không được trùng ID.', 400);
      }
      optIds.add(opt.id);
    }
    if (!q.correctOptionId || !optIds.has(q.correctOptionId)) {
      throw new ApiError('VALIDATION_ERROR', 'Đáp án đúng của câu hỏi trắc nghiệm không hợp lệ.', 400);
    }
  } else if (q.type === 'multiple_choice') {
    if (!Array.isArray(q.options) || q.options.length < 2) {
      throw new ApiError('VALIDATION_ERROR', 'Câu hỏi trắc nghiệm nhiều đáp án phải có ít nhất 2 lựa chọn.', 400);
    }
    const optIds = new Set<string>();
    for (const opt of q.options) {
      if (!opt.id || !opt.id.trim() || !opt.text || !opt.text.trim()) {
        throw new ApiError('VALIDATION_ERROR', 'Lựa chọn không được để trống ID hoặc nội dung.', 400);
      }
      if (optIds.has(opt.id)) {
        throw new ApiError('VALIDATION_ERROR', 'Các lựa chọn trong câu hỏi không được trùng ID.', 400);
      }
      optIds.add(opt.id);
    }
    if (!Array.isArray(q.correctOptionIds) || q.correctOptionIds.length === 0 || !q.correctOptionIds.every(id => optIds.has(id))) {
      throw new ApiError('VALIDATION_ERROR', 'Danh sách đáp án đúng của câu hỏi trắc nghiệm không hợp lệ.', 400);
    }
  } else if (q.type === 'true_false') {
    if (!Array.isArray(q.statements) || q.statements.length < 1) {
      throw new ApiError('VALIDATION_ERROR', 'Câu hỏi Đúng/Sai phải có ít nhất 1 mệnh đề.', 400);
    }
    const stIds = new Set<string>();
    for (const st of q.statements) {
      if (!st.id || !st.id.trim() || !st.text || !st.text.trim()) {
        throw new ApiError('VALIDATION_ERROR', 'Mệnh đề không được để trống ID hoặc nội dung.', 400);
      }
      if (stIds.has(st.id)) {
        throw new ApiError('VALIDATION_ERROR', 'Các mệnh đề không được trùng ID.', 400);
      }
      stIds.add(st.id);
      if (typeof st.isCorrect !== 'boolean') {
        throw new ApiError('VALIDATION_ERROR', 'Mệnh đề Đúng/Sai phải có giá trị đúng hoặc sai xác định.', 400);
      }
    }
  } else if (q.type === 'short_answer') {
    if (!q.expectedAnswer || !q.expectedAnswer.trim()) {
      throw new ApiError('VALIDATION_ERROR', 'Câu hỏi tự luận ngắn phải có đáp án mong đợi.', 400);
    }
  } else {
    throw new ApiError('VALIDATION_ERROR', 'Loại câu hỏi không được hỗ trợ.', 400);
  }
}

async function learningCalendar(user: User, onlyClassId?: string): Promise<CalendarEvent[]> {
  const ids = onlyClassId ? [onlyClassId] : user.roles.includes('STUDENT') ? getStudentActiveClassIds(user.id) : getTeacherAssignedClassIds(user.id).filter(id => classes.find(cls => cls.id === id)?.status === 'ACTIVE');
  const events = await Promise.all(ids.map(async classId => [...await assessmentPort.listCalendarEvents(classId), ...await assignmentPort.listCalendarEvents(classId)]));
  return events.flat();
}
const eventDate = (value: string) => new Date(value).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short', timeStyle: 'short' });
async function makeClassOverview(cls: ClassSummary, actor: User): Promise<ClassOverviewData> {
  const events = (await learningCalendar(actor, cls.id)).filter(event => Date.parse(event.end ?? event.start) >= Date.now()).sort((a,b) => Date.parse(a.start)-Date.parse(b.start));
  const post = feedPosts.find(item => item.classId === cls.id && item.isAnnouncement);
  return {
    summary: structuredClone(cls),
    announcement: post ? { id: post.id, authorName: post.authorName, authorRole: 'Giáo viên', authorInitials: post.authorAvatar ?? 'GV', timeAgo: eventDate(post.updatedAt ?? post.createdAt), title: post.title ?? 'Thông báo lớp', content: post.content } : undefined,
    recentMaterials: documents.flatMap(doc => { const grant = (documentGrants[doc.id] ?? []).find(item => item.classId === cls.id && item.isShared); if (!grant || !previewContext.sourceAccessible(actor.id, cls.id, doc.id, grant.servingVersion)) return []; return [{ id: doc.id, title: doc.title, format: doc.format, detail: `Phiên bản ${grant.servingVersion} · Sẵn sàng`, href: actor.roles.includes('LECTURER') ? `/teacher/classes/${cls.id}/documents` : `/student/classes/${cls.id}/documents/${doc.id}?version=${grant.servingVersion}` }]; }).slice(0,4),
    upcomingActivities: events.slice(0,4).map(event => ({ id: event.id, type: event.category === 'EXAM' ? 'EXAM' : 'ASSIGNMENT', title: event.title, dueDetail: eventDate(event.start), badgeLabel: event.category === 'EXAM' ? 'Kiểm tra chính thức' : 'Bài tập', badgeStyle: '', href: event.href!, actionLabel: 'Xem chi tiết', isOfficial: event.category === 'EXAM' })),
  };
}
async function makeStudentHome(user: User, studentClasses: ClassSummary[]): Promise<typeof studentHomeOverview> {
  const events = (await learningCalendar(user)).filter(event => Date.parse(event.end ?? event.start) >= Date.now()).sort((a,b) => Date.parse(a.start)-Date.parse(b.start));
  const attempts = Object.values(practiceAttempts).filter(item => item.ownerUserId === user.id && !item.isCompleted && studentClasses.some(cls => cls.id === item.classId));
  return {
    activeClasses: structuredClone(studentClasses),
    upcomingTasks: events.slice(0,4).map(event => ({ id: event.id, type: event.category === 'EXAM' ? 'EXAM' : 'ASSIGNMENT', title: event.title, className: event.className ?? '', dueDetail: `${event.category === 'EXAM' ? 'Mở đề' : 'Hạn nộp'}: ${eventDate(event.start)}`, daysLeftLabel: Date.parse(event.start) <= Date.now() ? 'Đang mở' : `Còn ${Math.ceil((Date.parse(event.start)-Date.now())/86400000)} ngày`, href: event.href!, actionLabel: 'Xem chi tiết' })),
    recentStudies: attempts.map(attempt => { const count = Object.keys(attempt.savedAnswers).length, total = attempt.questions.length; return { id: attempt.attemptId, type: 'PRACTICE', title: attempt.title, className: classes.find(cls => cls.id === attempt.classId)?.name ?? '', progressText: `Đã lưu ${count}/${total} câu`, progressPercent: total ? count/total*100 : 0, href: `/student/classes/${attempt.classId}/practice/${attempt.practiceId}/attempts/${attempt.attemptId}`, actionLabel: 'Tiếp tục luyện tập', extraNote: `Câu đang xem: ${attempt.currentQuestionIndex + 1}` }; }),
    tutorSuggestions: structuredClone(studentHomeOverview.tutorSuggestions.filter(item => studentClasses.some(cls => cls.id === item.classId))),
  };
}
async function teacherMetrics(user: User, classId: string) {
  const queue = await assignmentPort.load('t.gradingQueue', { classId });
  const events = await learningCalendar(user, classId), now = Date.now();
  return {
    pendingGrading: queue.kind === 'queue' ? queue.items.filter(item => !item.graded).length + queue.appeals.filter(item => item.status === 'OPEN').length + queue.proposals.filter(item => item.status === 'PENDING').length : 0,
    openActivities: events.filter(event => event.category === 'ASSIGNMENT' ? Date.parse(event.start) >= now : Date.parse(event.start) <= now && Date.parse(event.end ?? event.start) >= now).length + practiceActivities.filter(item => item.classId === classId).length,
  };
}
const projectedNotificationReads = new Set<string>();
async function actorNotifications(user: User): Promise<NotificationItem[]> {
  const base = notifications.filter(item => item.userId === user.id && !['ASSIGNMENT','EXAM'].includes(item.category));
  if (!user.roles.includes('STUDENT')) return structuredClone(base);
  const published: NotificationItem[] = [];
  for (const event of readPreviewAudit().filter(item => item.action.endsWith('_PUBLISHED') && item.classId && getStudentActiveClassIds(user.id).includes(item.classId))) {
    let title = '', href = '', category: NotificationItem['category'] = 'CLASS';
    try {
      if (event.resourceType === 'assessment') { const page = await assessmentPort.load('s.assessment', { classId: event.classId!, assessmentId: event.resourceId }); if (page.kind !== 'ready' || page.page.type !== 'detail') continue; title = page.page.assessment.title; category = 'EXAM'; href = `/student/classes/${event.classId}/assessments/${event.resourceId}`; }
      else if (event.resourceType === 'assignment') { const page = await assignmentPort.load('s.assignment', { classId: event.classId!, assignmentId: event.resourceId }); if (page.kind !== 'detail') continue; title = page.assignment.title; category = 'ASSIGNMENT'; href = `/student/classes/${event.classId}/assignments/${event.resourceId}`; }
      else if (event.resourceType === 'practice') { const item = practiceActivities.find(row => row.id === event.resourceId && row.classId === event.classId); if (!item) continue; title = item.title; href = `/student/classes/${event.classId}/practice`; }
      else continue;
    } catch { continue; }
    const id = `published:${event.id}`;
    published.push({ id, userId: user.id, title: `Hoạt động mới: ${title}`, content: 'Giáo viên đã xác nhận công bố hoạt động trong lớp.', category, createdAt: event.at, isRead: projectedNotificationReads.has(id), classId: event.classId, className: classes.find(cls => cls.id === event.classId)?.name, targetHref: href, targetLabel: 'Xem hoạt động' });
  }
  const results = readLearningEvidence(new Date().toISOString()).filter(item => item.studentId === user.id && item.kind !== 'PRACTICE' && item.studentHref).map(item => { const id = `grade:${item.kind}:${item.id}:v${item.gradeVersion}`; return { id, userId: user.id, title: `Kết quả đã công bố: ${item.title}`, content: `Phiên bản điểm ${item.gradeVersion} đã được xác nhận.`, category: (item.kind === 'ASSESSMENT' ? 'EXAM' : 'ASSIGNMENT') as NotificationItem['category'], createdAt: item.occurredAt, isRead: projectedNotificationReads.has(id), classId: item.classId, className: classes.find(cls => cls.id === item.classId)?.name, targetHref: item.studentHref, targetLabel: 'Xem kết quả của tôi' }; });
  return [...structuredClone(base), ...published, ...results].sort((a,b) => Date.parse(b.createdAt)-Date.parse(a.createdAt));
}

const previewContext: import('./context').PreviewContext = {
  actor() {
    const actor = signedIn();
    if (actor.status !== 'ACTIVE') throw new ApiError('FORBIDDEN', 'Tài khoản hiện không hoạt động.', 403);
    return structuredClone(actor);
  },
  classSummary: id => previewClassroomStore.getClass(id),
  studentMembership(userId, classId) {
    if (getStudentActiveClassIds(userId).includes(classId)) return 'ACTIVE';
    if (getStudentEndedClassIds(userId).includes(classId) || getStudentArchivedClassIds(userId).includes(classId)) return 'ENDED';
    return null;
  },
  activeStudentIds: classId => previewClassroomStore.activeStudentIds(classId),
  teachingRole: (userId, classId) => previewClassroomStore.teachingRole(userId, classId),
  sources: getAvailableClassSources,
  sourceAccessible(userId, classId, documentId, version) {
    const cls = classes.find(c => c.id === classId);
    const allowed = getStudentActiveClassIds(userId).includes(classId) || getTeacherAssignedClassIds(userId).includes(classId);
    return Boolean(cls?.status === 'ACTIVE' && allowed && documents.some(d => d.id === documentId)
      && (documentGrants[documentId] ?? []).some(g => g.classId === classId && g.isShared)
      && (documentVersions[documentId] ?? []).some(v => v.versionNumber === version && v.status === 'READY'));
  },
  now: () => Date.now(),
};

const assessmentPort = auditedPort(createAssessmentPort(previewContext), previewContext, 'assessment', ['createDraft','saveDraft','reviewQuestion','propose','decide','newVersion','start','submit','proposeGrade','approveGrade','appeal','applyGradeCorrection']);
const assignmentPort = auditedPort(createAssignmentPort(previewContext, assessmentPort), previewContext, 'assignment', ['createDraft','setRecipients','submit','saveDraft','grade','appeal','propose','decide']);

const requestReview = createDataRequestReview({
  context: previewContext, schoolId, records: () => requests, user: id => previewAccountStore.user(id),
  snapshot(userId) {
    return { profile: previewAccountStore.user(userId), learningResults: readLearningEvidence(new Date(previewContext.now()).toISOString()).filter(item => item.studentId === userId).map(({ teacherHref: _teacherHref, ...item }) => item), personalNotes: { notes: personalNotes.filter(item => item.userId === userId).map(sanitizeNoteForStudent), bookmarks: bookmarks.filter(item => item.userId === userId).map(sanitizeBookmarkForStudent) } };
  },
});
const intelligencePort = createIntelligencePort(previewContext, {
  schoolId, classes: () => previewClassroomStore.allClasses(),
  studentName: id => { const user = previewAccountStore.user(id); return user?.display_name ?? user?.username ?? 'Học sinh'; },
  ...requestReview,
  async readAudit() {
    const actor = signedIn();
    const classroom = previewClassroomStore.auditEvents(actor.id).map(item => ({ ...item, actorName: previewAccountStore.user(item.actorId)?.display_name ?? 'Quản trị viên', resourceType: 'CLASSROOM' }));
    return [...readPreviewAudit(), ...classroom].filter(item => previewAccountStore.user(item.actorId)?.school_id === actor.school_id);
  },
});

export const adapter: DataAdapter = {
  source: 'mock',
  personalData: { async download(requestId) { const actor = signedIn(); const request = requests.find(item => item.id === requestId && item.user_id === actor.id); if (!request) throw new ApiError('NOT_FOUND', 'Không tìm thấy bản sao thuộc tài khoản của bạn.', 404); return requestReview.downloadRequest!(requestId); } },
  practiceAuthoring: createPracticeAuthoringPort({
    context: previewContext,
    learning: () => adapter.learning,
    async read(scope) {
      const data = await adapter.workspace.load('t.practiceEditor', scope);
      if (data.kind !== 'ready' || !data.teacherPracticeEditor) throw new ApiError('UNAVAILABLE', data.kind === 'ready' ? 'Không tìm thấy bài luyện tập.' : data.message, 403);
      return data.teacherPracticeEditor;
    },
  }),
  classroom: createClassroomAdminPort(previewContext),
  intelligence: intelligencePort,
  accounts: auditedPort(createAccountsPort(previewContext), previewContext, 'account', ['updateAccount','assignLegacyUsername','inviteStaff','revokeInvitation','resendInvitation','confirmImport']),
  assignment: assignmentPort,
  assessment: assessmentPort,
  fixtureSignature: fixtureCanary,
  identity: {
    async restore() { if (!current) return null; try { return structuredClone(signedIn()); } catch { current = null; return null; } },
    async login(input) { current = previewAccountStore.login(input); currentSessionRevision = previewAccountStore.sessionRevision(current.id); return structuredClone(current); },
    async logout() { current = null; currentSessionRevision = -1; },
    async logoutAll() { if (current) previewAccountStore.revokeSessions(current.id); current = null; currentSessionRevision = -1; },
    async updateProfile(name) { current = previewAccountStore.updateProfile(signedIn().id, name); return structuredClone(current); },
    async activate(input) { previewAccountStore.activate(input); },
    async forgot(email) { previewAccountStore.forgot(email); },
    async reset(token, password) { previewAccountStore.reset(token, password); },
    async acceptInvitation(token, password) { previewAccountStore.acceptInvitation(token, password); },
    async requests() {
      const user = signedIn();
      return { items: structuredClone(requests.filter(x => x.user_id === user.id)), next_cursor: null };
    },
    async createRequest(type, reason) {
      const item: DataRequest = {
        id: crypto.randomUUID(),
        user_id: signedIn().id,
        type,
        reason: reason ?? null,
        status: 'PENDING',
        resolution_note: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      requests = [item, ...requests];
      return structuredClone(item);
    },
    async createStudent(username, displayName) { return previewAccountStore.createStudent(signedIn().id, username, displayName); },
    async issueCode(userId, identityVerified) { return previewAccountStore.issueCode(signedIn().id, userId, identityVerified); },
  },
  social: {
    async createPost(classId, content) {
      const user = signedIn();
      if (!content.trim()) throw new ApiError('VALIDATION_ERROR', 'Nội dung bài viết không được để trống.');

      const targetClass = classes.find(c => c.id === classId);
      if (!targetClass) throw new ApiError('NOT_FOUND', 'Lớp học không tồn tại.', 404);
      if (targetClass.status === 'ARCHIVED') {
        throw new ApiError('FORBIDDEN', 'Lớp học đã lưu trữ, không thể đăng bài viết mới.', 403);
      }

      const isTeacher = user.roles.includes('LECTURER');
      if (isTeacher) {
        if (!getTeacherAssignedClassIds(user.id).includes(classId)) {
          throw new ApiError('FORBIDDEN', 'Bạn không được phân công giảng dạy lớp này.', 403);
        }
      } else {
        if (!getStudentActiveClassIds(user.id).includes(classId)) {
          throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp này.', 403);
        }
      }

      const newPost: FeedPost = {
        id: 'post-' + crypto.randomUUID(),
        classId,
        authorId: user.id,
        authorName: user.display_name ?? user.username ?? user.email ?? 'Người dùng',
        authorRole: isTeacher ? 'TEACHER' : 'STUDENT',
        authorAvatar: (user.display_name ?? 'ND').split(' ').slice(-2).map(x => x[0]).join(''),
        content: content.trim(),
        createdAt: new Date().toISOString(),
        isAnnouncement: isTeacher,
        comments: [],
      };
      feedPosts = [newPost, ...feedPosts];
      return structuredClone(newPost);
    },
    async updatePost(classId, postId, content) {
      const user = signedIn();
      requireClassInteraction(classId, user);
      if (!content.trim()) throw new ApiError('VALIDATION_ERROR', 'Nội dung bài viết không được để trống.');

      const targetClass = classes.find(c => c.id === classId);
      if (!targetClass) throw new ApiError('NOT_FOUND', 'Lớp học không tồn tại.', 404);
      if (targetClass.status === 'ARCHIVED') {
        throw new ApiError('FORBIDDEN', 'Lớp học đã lưu trữ, không thể chỉnh sửa bài viết.', 403);
      }

      const postIndex = feedPosts.findIndex(p => p.id === postId && p.classId === classId);
      if (postIndex === -1) throw new ApiError('NOT_FOUND', 'Không tìm thấy bài viết.', 404);

      const target = feedPosts[postIndex];
      const isTeacher = user.roles.includes('LECTURER');
      if (!isTeacher && target.authorId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền chỉnh sửa bài viết này.', 403);
      }

      const updated: FeedPost = {
        ...target,
        content: content.trim(),
        updatedAt: new Date().toISOString(),
      };
      feedPosts[postIndex] = updated;
      return structuredClone(updated);
    },
    async deletePost(classId, postId) {
      const user = signedIn();
      requireClassInteraction(classId, user);
      const target = feedPosts.find(p => p.id === postId && p.classId === classId);
      if (!target) throw new ApiError('NOT_FOUND', 'Không tìm thấy bài viết.', 404);
      const isTeacher = user.roles.includes('LECTURER');
      if (!isTeacher && target.authorId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền xóa bài viết này.', 403);
      }
      feedPosts = feedPosts.filter(p => p.id !== postId);
    },
    async createComment(classId, postId, content) {
      const user = signedIn();
      if (!content.trim()) throw new ApiError('VALIDATION_ERROR', 'Nội dung phản hồi không được để trống.');

      const targetClass = classes.find(c => c.id === classId);
      if (!targetClass) throw new ApiError('NOT_FOUND', 'Lớp học không tồn tại.', 404);
      if (targetClass.status === 'ARCHIVED') {
        throw new ApiError('FORBIDDEN', 'Lớp học đã lưu trữ, không thể phản hồi.', 403);
      }

      const post = feedPosts.find(p => p.id === postId && p.classId === classId);
      if (!post) throw new ApiError('NOT_FOUND', 'Không tìm thấy bài viết.', 404);

      const isTeacher = user.roles.includes('LECTURER');
      if (isTeacher) {
        if (!getTeacherAssignedClassIds(user.id).includes(classId)) {
          throw new ApiError('FORBIDDEN', 'Bạn không được phân công giảng dạy lớp này.', 403);
        }
      } else {
        if (!getStudentActiveClassIds(user.id).includes(classId)) {
          throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp này.', 403);
        }
      }

      const newComment: FeedComment = {
        id: 'comm-' + crypto.randomUUID(),
        postId,
        authorId: user.id,
        authorName: user.display_name ?? user.username ?? user.email ?? 'Người dùng',
        authorRole: isTeacher ? 'TEACHER' : 'STUDENT',
        authorClass: !isTeacher ? targetClass.code : undefined,
        content: content.trim(),
        createdAt: new Date().toISOString(),
      };
      post.comments.push(newComment);
      return structuredClone(newComment);
    },
    async deleteComment(classId, postId, commentId) {
      const user = signedIn();
      requireClassInteraction(classId, user);
      const post = feedPosts.find(p => p.id === postId && p.classId === classId);
      if (!post) throw new ApiError('NOT_FOUND', 'Không tìm thấy bài viết.', 404);
      const comment = post.comments.find(c => c.id === commentId);
      if (!comment) throw new ApiError('NOT_FOUND', 'Không tìm thấy bình luận.', 404);
      const isTeacher = user.roles.includes('LECTURER');
      if (!isTeacher && comment.authorId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền xóa bình luận này.', 403);
      }
      post.comments = post.comments.filter(c => c.id !== commentId);
    },
  },
  calendar: {
    async createEvent(event) {
      const user = signedIn();
      if (!user.roles.includes('LECTURER')) throw new ApiError('FORBIDDEN', 'Ch? gi?o vi?n ???c ph?n c?ng m?i c? quy?n t?o s? ki?n.', 403);
      if (!event.classId) throw new ApiError('VALIDATION_ERROR', 'Chọn lớp được phân công để tạo sự kiện.', 422);
      requireClassInteraction(event.classId, user, true);
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên phụ trách mới có quyền tạo sự kiện lịch.', 403);
      }
      if (!event.title.trim()) throw new ApiError('VALIDATION_ERROR', 'Tiêu đề sự kiện không được để trống.');

      if (event.classId) {
        const cls = classes.find(c => c.id === event.classId);
        if (!cls) throw new ApiError('NOT_FOUND', 'Lớp học không tồn tại.', 404);
        if (cls.status === 'ARCHIVED') {
          throw new ApiError('FORBIDDEN', 'Lớp học đã lưu trữ, không thể thêm sự kiện lịch.', 403);
        }
        if (!getTeacherAssignedClassIds(user.id).includes(event.classId)) {
          throw new ApiError('FORBIDDEN', 'Bạn không được phân công giảng dạy lớp này.', 403);
        }
      }

      if (event.start && event.end && new Date(event.start) >= new Date(event.end)) {
        throw new ApiError('VALIDATION_ERROR', 'Thời gian bắt đầu phải trước thời gian kết thúc.');
      }

      const newEvent: CalendarEvent = {
        ...event,
        id: 'cal-' + crypto.randomUUID(),
      };
      calendarEvents = [...calendarEvents, newEvent];
      return structuredClone(newEvent);
    },
    async updateEvent(id, patch) {
      const user = signedIn();
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên phụ trách mới có quyền chỉnh sửa sự kiện lịch.', 403);
      }
      const existing = calendarEvents.find(e => e.id === id);
      if (!existing) throw new ApiError('NOT_FOUND', 'Không tìm thấy sự kiện.', 404);
      if (!existing.classId) throw new ApiError('FORBIDDEN', 'Sự kiện chung của nhà trường ở chế độ chỉ đọc.', 403);
      requireClassInteraction(existing.classId, user, true);

      if (existing.readOnly || existing.category === 'ASSIGNMENT' || existing.category === 'EXAM') {
        throw new ApiError('FORBIDDEN', 'Hạn nộp và lịch kiểm tra từ phân hệ học tập ở chế độ chỉ đọc, không thể chỉnh sửa từ lịch.', 403);
      }

      if (existing.classId) {
        const cls = classes.find(c => c.id === existing.classId);
        if (cls?.status === 'ARCHIVED') {
          throw new ApiError('FORBIDDEN', 'Lớp học đã lưu trữ, không thể sửa sự kiện.', 403);
        }
      }

      const mergedStart = patch.start ?? existing.start;
      const mergedEnd = patch.end ?? existing.end;
      if (mergedStart && mergedEnd && new Date(mergedStart) >= new Date(mergedEnd)) {
        throw new ApiError('VALIDATION_ERROR', 'Thời gian bắt đầu phải trước thời gian kết thúc.');
      }

      // Safe update: prevent changing id, classId, or category
      const updated: CalendarEvent = {
        ...existing,
        ...patch,
        id: existing.id,
        classId: existing.classId,
        category: existing.category,
      };

      const idx = calendarEvents.findIndex(e => e.id === id);
      calendarEvents[idx] = updated;
      return structuredClone(updated);
    },
    async deleteEvent(id) {
      const user = signedIn();
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên phụ trách mới có quyền xóa sự kiện lịch.', 403);
      }
      const existing = calendarEvents.find(e => e.id === id);
      if (!existing) throw new ApiError('NOT_FOUND', 'Không tìm thấy sự kiện.', 404);
      if (!existing.classId) throw new ApiError('FORBIDDEN', 'Sự kiện chung của nhà trường ở chế độ chỉ đọc.', 403);
      requireClassInteraction(existing.classId, user, true);

      if (existing.readOnly || existing.category === 'ASSIGNMENT' || existing.category === 'EXAM') {
        throw new ApiError('FORBIDDEN', 'Không thể xóa các mốc thời gian học tập chỉ đọc.', 403);
      }

      calendarEvents = calendarEvents.filter(e => e.id !== id);
    },
  },
  notifications: {
    async markAsRead(id) {
      const user = signedIn();
      const foreign = notifications.find(item => item.id === id && item.userId !== user.id);
      if (foreign) throw new ApiError('FORBIDDEN', 'Kh?ng c? quy?n thao t?c tr?n th?ng b?o c?a ng??i kh?c.', 403);
      const notif = (await actorNotifications(user)).find(n => n.id === id);
      if (!notif) {
        throw new ApiError('NOT_FOUND', 'Không tìm thấy thông báo.', 404);
      }
      if (notif.userId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Không có quyền thao tác trên thông báo của người khác.', 403);
      }
      projectedNotificationReads.add(id);
      const original = notifications.find(item => item.id === id && item.userId === user.id);
      if (original) original.isRead = true;
    },
    async markAllAsRead() {
      const user = signedIn();
      for (const n of await actorNotifications(user)) {
        if (n.userId === user.id) {
          projectedNotificationReads.add(n.id);
          const original = notifications.find(item => item.id === n.id); if (original) original.isRead = true;
        }
      }
    },
  },
  document: {
    async previewClassSource(input) {
      const user = signedIn();
      if (!user.roles.includes('LECTURER') || !previewContext.teachingRole(user.id, input.classId) || !previewContext.sourceAccessible(user.id, input.classId, input.documentId, input.version)) throw new ApiError('FORBIDDEN', 'Nguồn không còn được chia sẻ hoặc bạn không được phân công trong lớp.', 403);
      const doc = documents.find(d => d.id === input.documentId);
      const content = mockReaderModels[input.documentId];
      if (!doc || !content || (content.viewingVersion ?? content.servingVersion) !== input.version || !content.pageContents?.length) throw new ApiError('UNAVAILABLE', 'Nội dung đọc của phiên bản này chưa sẵn sàng.', 503);
      return { documentId: doc.id, classId: input.classId, title: doc.title, version: input.version, totalPages: content.totalPages, pages: structuredClone(content.pageContents) };
    },
    async uploadDocument(file) {
      const user = signedIn();
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên mới có quyền tải lên tài liệu.', 403);
      }
      if (!file.title?.trim()) {
        throw new ApiError('VALIDATION_ERROR', 'Tiêu đề tài liệu không được để trống.');
      }
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!documentCapabilityPolicy.allowedExtensions.includes(ext)) {
        throw new ApiError('VALIDATION_ERROR', `Định dạng tệp ${ext} không được hỗ trợ. Vui lòng chọn PDF, PPTX, DOCX, TXT hoặc MD.`);
      }
      if (file.size > documentCapabilityPolicy.maxSizeBytes) {
        throw new ApiError('VALIDATION_ERROR', 'Kích thước tệp vượt quá giới hạn 50MB cho phép.');
      }
      const format: DocumentFormat = ext === '.pdf' ? 'PDF' : ext === '.pptx' ? 'PPTX' : ext === '.docx' ? 'DOCX' : ext === '.txt' ? 'TXT' : 'MD';
      const docId = 'doc-' + crypto.randomUUID();
      const newDoc: DocumentItem = {
        id: docId,
        title: file.title.trim(),
        description: file.description?.trim(),
        format,
        currentVersion: 1,
        processingStatus: 'READY',
        ownerId: user.id,
        ownerName: user.display_name ?? 'Giáo viên',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        sharedClassCount: 0,
        sharedClasses: [],
        locatorCountLabel: '1 trang',
      };
      documents.unshift(newDoc);
      documentVersions[docId] = [
        {
          versionNumber: 1,
          filename: file.name,
          fileSizeFormatted: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
          uploadedAt: 'Hôm nay',
          status: 'READY',
          isServing: true,
        },
      ];
      documentGrants[docId] = [];
      return structuredClone(newDoc);
    },
    async uploadVersion(documentId, file) {
      const user = signedIn();
      const doc = documents.find(d => d.id === documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      if (doc.ownerId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Chỉ chủ sở hữu tài liệu mới có quyền tải lên phiên bản mới.', 403);
      }
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!documentCapabilityPolicy.allowedExtensions.includes(ext)) {
        throw new ApiError('VALIDATION_ERROR', `Định dạng tệp ${ext} không được hỗ trợ.`);
      }
      if (file.size > documentCapabilityPolicy.maxSizeBytes) {
        throw new ApiError('VALIDATION_ERROR', 'Kích thước tệp vượt quá giới hạn dung lượng cho phép.');
      }
      const vers = documentVersions[documentId] ?? [];
      const maxVer = vers.length > 0 ? Math.max(...vers.map(v => v.versionNumber)) : doc.currentVersion;
      const nextVer = maxVer + 1;
      const isFailed = file.name.toLowerCase().includes('draft') || file.name.toLowerCase().includes('fail');
      const version: DocumentVersion = {
        versionNumber: nextVer,
        filename: file.name,
        fileSizeFormatted: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
        uploadedAt: 'Vừa xong',
        status: isFailed ? 'FAILED' : 'READY',
        errorMessage: isFailed ? 'Lỗi phân tích cú pháp font vector tại trang 4.' : undefined,
        isServing: !isFailed,
      };
      if (!isFailed) {
        for (const v of vers) {
          v.isServing = false;
        }
        doc.currentVersion = nextVer;
        doc.updatedAt = new Date().toISOString();
        const grants = documentGrants[documentId] ?? [];
        for (const g of grants) {
          g.servingVersion = nextVer;
        }
      }
      documentVersions[documentId] = [version, ...vers];
      return structuredClone(version);
    },
    async retryProcessing(documentId, versionNumber) {
      const user = signedIn();
      const doc = documents.find(d => d.id === documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      if (doc.ownerId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Chỉ chủ sở hữu mới có quyền thao tác trên tài liệu này.', 403);
      }
      const vers = documentVersions[documentId] ?? [];
      const targetVer = versionNumber ? vers.find(v => v.versionNumber === versionNumber) : vers[0];
      if (!targetVer) throw new ApiError('NOT_FOUND', 'Không tìm thấy phiên bản tài liệu.', 404);
      targetVer.status = 'READY';
      targetVer.errorMessage = undefined;

      // Consistent single serving version among READY versions:
      const readyVersions = vers.filter(v => v.status === 'READY');
      const maxReadyVer = Math.max(...readyVersions.map(v => v.versionNumber));
      for (const v of vers) {
        v.isServing = (v.versionNumber === maxReadyVer);
      }
      doc.currentVersion = maxReadyVer;
      doc.processingStatus = 'READY';
      const grants = documentGrants[documentId] ?? [];
      for (const g of grants) {
        g.servingVersion = maxReadyVer;
      }
      return structuredClone(doc);
    },
    async shareDocument(documentId, classIds) {
      const user = signedIn();
      const doc = documents.find(d => d.id === documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      if (doc.ownerId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Chỉ chủ sở hữu tài liệu nguồn mới có quyền cấp quyền chia sẻ cho lớp.', 403);
      }
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      for (const cid of classIds) {
        const cls = classes.find(c => c.id === cid);
        if (!cls) {
          throw new ApiError('NOT_FOUND', `Lớp học ${cid} không tồn tại.`, 404);
        }
        if (cls.status === 'ARCHIVED') {
          throw new ApiError('FORBIDDEN', 'Không thể chia sẻ tài liệu vào lớp học đã lưu trữ.', 403);
        }
        if (!allowedClassIds.includes(cid)) {
          throw new ApiError('FORBIDDEN', 'Bạn không được phân công giảng dạy lớp học này.', 403);
        }
      }
      const existing = documentGrants[documentId] ?? [];
      for (const cid of classIds) {
        const cls = classes.find(c => c.id === cid);
        if (!cls) continue;
        const grant = existing.find(g => g.classId === cid);
        if (grant) {
          grant.isShared = true;
        } else {
          existing.push({
            classId: cid,
            className: cls.name,
            classCode: cls.code,
            isShared: true,
            grantedAt: 'Hôm nay',
            servingVersion: doc.currentVersion,
          });
        }
      }
      documentGrants[documentId] = existing;
      doc.sharedClasses = existing.filter(g => g.isShared).map(g => ({ classId: g.classId, className: g.className, grantedAt: g.grantedAt ?? 'Hôm nay' }));
      doc.sharedClassCount = doc.sharedClasses.length;
    },
    async revokeShare(documentId, classId) {
      const user = signedIn();
      const doc = documents.find(d => d.id === documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      const isOwner = doc.ownerId === user.id;
      const isAssigned = allowedClassIds.includes(classId);
      if (!isOwner && !isAssigned) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền thu hồi tài liệu này trong lớp.', 403);
      }
      const existing = documentGrants[documentId] ?? [];
      const grant = existing.find(g => g.classId === classId);
      if (grant) {
        grant.isShared = false;
      }
      doc.sharedClasses = existing.filter(g => g.isShared).map(g => ({ classId: g.classId, className: g.className, grantedAt: g.grantedAt ?? 'Hôm nay' }));
      doc.sharedClassCount = doc.sharedClasses.length;
    },
    async deleteDocument(documentId) {
      const user = signedIn();
      const doc = documents.find(d => d.id === documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      if (doc.ownerId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Chỉ chủ sở hữu mới có quyền xóa tài liệu nguồn.', 403);
      }
      documents = documents.filter(d => d.id !== documentId);
      delete documentVersions[documentId];
      delete documentGrants[documentId];
    },
    async saveNote(input) {
      const user = signedIn();
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có sổ tay ghi chú và dấu trang cá nhân.', 403);
      }
      if (!input.noteText?.trim()) {
        throw new ApiError('VALIDATION_ERROR', 'Nội dung ghi chú không được để trống.');
      }
      if (input.id) {
        const existing = personalNotes.find(n => n.id === input.id && n.userId === user.id);
        if (!existing) throw new ApiError('NOT_FOUND', 'Không tìm thấy ghi chú cá nhân của bạn.', 404);
        existing.noteText = input.noteText.trim();
        existing.updatedAt = 'Vừa xong';
        return sanitizeNoteForStudent(existing);
      }
      const doc = documents.find(d => d.id === input.documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      const cls = classes.find(c => c.id === input.classId);
      if (!cls) throw new ApiError('NOT_FOUND', 'Lớp học không tồn tại.', 404);
      if (cls.status === 'ARCHIVED' || cls.membershipStatus === 'ENDED') {
        throw new ApiError('FORBIDDEN', 'Không thể tạo ghi chú mới trong lớp học đã kết thúc hoặc lưu trữ.', 403);
      }
      if (!getStudentActiveClassIds(user.id).includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp học này.', 403);
      }
      const grant = (documentGrants[doc.id] ?? []).find(g => g.classId === input.classId && g.isShared);
      if (!grant) {
        throw new ApiError('FORBIDDEN', 'Tài liệu không được chia sẻ trong lớp học này.', 403);
      }
      const capturedVersion = input.version ?? grant.servingVersion ?? doc.currentVersion;
      const pageNum = input.pageNumber ?? (input.locator?.match(/\d+/)?.[0] ? parseInt(input.locator.match(/\d+/)![0], 10) : undefined);
      const newNote: PersonalNoteItem = {
        id: 'note-' + crypto.randomUUID(),
        userId: user.id,
        documentId: input.documentId,
        documentTitle: doc.title,
        documentFormat: doc.format,
        version: capturedVersion,
        classId: input.classId,
        className: cls.name,
        classStatus: cls.status,
        locator: input.locator,
        pageNumber: pageNum,
        sourceQuote: input.sourceQuote,
        isSourceAccessible: true,
        noteText: input.noteText.trim(),
        updatedAt: 'Vừa xong',
      };
      personalNotes.unshift(newNote);
      return sanitizeNoteForStudent(newNote);
    },
    async deleteNote(noteId) {
      const user = signedIn();
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có sổ tay ghi chú.', 403);
      }
      const note = personalNotes.find(n => n.id === noteId);
      if (!note) throw new ApiError('NOT_FOUND', 'Không tìm thấy ghi chú.', 404);
      if (note.userId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền xóa ghi chú của người khác.', 403);
      }
      personalNotes = personalNotes.filter(n => n.id !== noteId);
    },
    async toggleBookmark(documentId, classId, locator, version) {
      const user = signedIn();
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có dấu trang cá nhân.', 403);
      }
      const doc = documents.find(d => d.id === documentId);
      if (!doc) throw new ApiError('NOT_FOUND', 'Tài liệu không tồn tại.', 404);
      const cls = classes.find(c => c.id === classId);
      if (!cls) throw new ApiError('NOT_FOUND', 'Lớp học không tồn tại.', 404);
      const grant = (documentGrants[documentId] ?? []).find(g => g.classId === classId && g.isShared);
      if (!grant) {
        throw new ApiError('FORBIDDEN', 'Tài liệu không được chia sẻ trong lớp học này.', 403);
      }
      const idx = bookmarks.findIndex(b => b.documentId === documentId && b.classId === classId && b.userId === user.id);
      if (idx >= 0) {
        bookmarks.splice(idx, 1);
        return { bookmarked: false };
      }
      const capturedVersion = version ?? grant.servingVersion ?? doc.currentVersion;
      const pageNum = locator?.match(/\d+/)?.[0] ? parseInt(locator.match(/\d+/)![0], 10) : 1;
      const newBm: BookmarkItem = {
        id: 'bm-' + crypto.randomUUID(),
        userId: user.id,
        documentId,
        documentTitle: doc.title,
        documentFormat: doc.format,
        version: capturedVersion,
        classId,
        className: cls.name,
        locator: locator ?? 'Trang 1',
        pageNumber: pageNum,
        createdAt: 'Hôm nay',
        isSourceAccessible: true,
      };
      bookmarks.unshift(newBm);
      return { bookmarked: true };
    },
  },
  tutor: {
    async updateConfig(classId, instructions) {
      const user = signedIn();
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên mới có quyền cấu hình chỉ dẫn trợ lý.', 403);
      }
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      if (!allowedClassIds.includes(classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không được phân công giảng dạy lớp học này.', 403);
      }
      if (instructions.length > 2000) {
        throw new ApiError('VALIDATION_ERROR', 'Chỉ dẫn không được vượt quá 2000 ký tự.');
      }
      const conf: TeacherTutorInstructionConfig = {
        classId,
        instructions: instructions.trim(),
        updatedAt: 'Vừa xong',
        maxChars: 2000,
        disclaimer: 'Cấu hình chỉ dẫn sư phạm này được áp dụng cho Lumi khi giải đáp cho học sinh lớp này. Giáo viên không thể xem các đoạn hội thoại hoặc câu hỏi riêng tư của học sinh.',
      };
      teacherTutorConfigs[classId] = conf;
      return structuredClone(conf);
    },
    async createConversation(classId, title) {
      const user = signedIn();
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có thể trò chuyện với Trợ lý AI.', 403);
      }
      const activeClassIds = getStudentActiveClassIds(user.id);
      if (!activeClassIds.includes(classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh đang học của lớp này.', 403);
      }
      if (isMockAssessmentLocked(user.id, classId)) {
        throw new ApiError('FORBIDDEN', 'Khóa tương tác AI: Bạn đang có bài kiểm tra hoặc đánh giá chính thức đang diễn ra trong lớp học này.', 403);
      }
      const convId = 'conv-' + crypto.randomUUID();
      const newConv: TutorConversation = {
        id: convId,
        userId: user.id,
        classId,
        title: title?.trim() || 'Cuộc trò chuyện mới',
        updatedAt: 'Vừa xong',
        preview: 'Chưa có tin nhắn',
        messages: [],
      };
      const key = `${user.id}:${classId}`;
      const list = tutorConversations[key] ?? [];
      list.unshift(newConv);
      tutorConversations[key] = list;
      return structuredClone(newConv);
    },
    async sendMessage(input) {
      const user = signedIn();
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có thể trò chuyện với Trợ lý AI.', 403);
      }
      if (!input.content?.trim()) {
        throw new ApiError('VALIDATION_ERROR', 'Tin nhắn không được để trống.');
      }
      const activeClassIds = getStudentActiveClassIds(user.id);
      if (!activeClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp học này.', 403);
      }
      if (isMockAssessmentLocked(user.id, input.classId)) {
        throw new ApiError('FORBIDDEN', 'Khóa tương tác AI: Bạn đang có bài kiểm tra hoặc đánh giá chính thức đang diễn ra trong lớp học này.', 403);
      }
      const key = `${user.id}:${input.classId}`;
      const convList = tutorConversations[key] ?? [];
      const conv = convList.find(c => c.id === input.conversationId);
      if (!conv) {
        throw new ApiError('NOT_FOUND', 'Cuộc trò chuyện không tồn tại.', 404);
      }

      // Enforce one send per conversation
      const currentStream = activeStreams.get(conv.id);
      if (currentStream && !currentStream.aborted) {
        throw new ApiError('CONFLICT', 'Đang có câu trả lời đang truyền tải trong cuộc trò chuyện này.', 409);
      }

      // Retry deduplication vs intentional repeated question
      const lastMsg = conv.messages[conv.messages.length - 1];
      const isRetry = input.isRetry === true || (lastMsg && lastMsg.role === 'user' && lastMsg.content === input.content.trim());

      if (!isRetry) {
        const userMsg: TutorMessage = {
          id: 'msg-' + crypto.randomUUID(),
          conversationId: conv.id,
          role: 'user',
          content: input.content.trim(),
          timestamp: '14:20',
        };
        conv.messages.push(userMsg);
        conv.preview = input.content.trim().slice(0, 40);
        conv.updatedAt = 'Vừa xong';
      }

      // Grounding check
      const classGrantsList = documents.filter(d => (documentGrants[d.id] ?? []).some(g => g.classId === input.classId && g.isShared));
      const hasSources = classGrantsList.length > 0;
      const contentLower = input.content.toLowerCase();
      const isRefusal = contentLower.includes('ngoài lề') || contentLower.includes('không có') || contentLower.includes('chơi game') || contentLower.includes('thời tiết');

      let responseText = '';
      let knowledgeType: 'CLASS_SOURCE' | 'GENERAL_KNOWLEDGE' = 'CLASS_SOURCE';
      let citations: CitationItem[] = [];

      if (!hasSources) {
        knowledgeType = 'GENERAL_KNOWLEDGE';
        responseText = `Hiện tại lớp chưa có tài liệu chia sẻ về chủ đề này. Dưới đây là kiến thức nền tảng chung: ${input.content}`;
        citations = [];
      } else if (isRefusal) {
        knowledgeType = 'GENERAL_KNOWLEDGE';
        responseText = 'Mình chưa tìm thấy căn cứ về chủ đề này trong tài liệu hiện có của lớp, nên chưa thể trích dẫn cho bạn theo quy định học tập.';
        citations = [];
      } else {
        knowledgeType = 'CLASS_SOURCE';
        const primaryDoc = classGrantsList[0];
        const grant = (documentGrants[primaryDoc.id] ?? []).find(g => g.classId === input.classId && g.isShared)!;
        const servingVer = grant.servingVersion ?? primaryDoc.currentVersion;
        responseText = `Dựa vào tài liệu "${primaryDoc.title}", để giải quyết câu hỏi này, em chú ý khảo sát các tính chất trọng tâm và áp dụng định lý từng bước.`;
        citations = [
          {
            id: 'cite-' + crypto.randomUUID(),
            documentId: primaryDoc.id,
            documentTitle: primaryDoc.title,
            version: servingVer,
            locator: 'Trang 3',
            pageNumber: 3,
            excerpt: 'Trục đối xứng là đường thẳng x = -b / (2a). Đỉnh I có tọa độ I(-b/(2a); -Δ/(4a)).',
            readerHref: `/student/classes/${input.classId}/documents/${primaryDoc.id}?version=${servingVer}&page=3`,
            isAccessible: true,
          },
        ];
      }

      // True asynchronous streaming simulation with AbortSignal & cancellation support
      const streamControl: StreamEntry = { userId: user.id, classId: input.classId, aborted: false };
      activeStreams.set(conv.id, streamControl);

      const chunkSize = Math.max(1, Math.ceil(responseText.length / 4));
      let streamedLength = 0;
      let isCancelled = false;

      while (streamedLength < responseText.length) {
        if (input.signal?.aborted || streamControl.aborted) {
          isCancelled = true;
          break;
        }

        streamedLength = Math.min(responseText.length, streamedLength + chunkSize);
        input.onChunk?.(responseText.slice(0, streamedLength));

        // True async yield
        await new Promise(r => setTimeout(r, 20));

        // State check after each yield
        if (input.signal?.aborted || streamControl.aborted) {
          isCancelled = true;
          break;
        }
        if (!current || current.id !== user.id) {
          isCancelled = true;
          break;
        }
        if (isMockAssessmentLocked(user.id, input.classId)) {
          isCancelled = true;
          break;
        }
        const currentGrants = documentGrants[classGrantsList[0]?.id] ?? [];
        if (hasSources && !currentGrants.some(g => g.classId === input.classId && g.isShared)) {
          isCancelled = true;
          break;
        }
      }

      activeStreams.delete(conv.id);

      const assistantMsg: TutorMessage = {
        id: 'msg-' + crypto.randomUUID(),
        conversationId: conv.id,
        role: 'assistant',
        content: isCancelled ? responseText.slice(0, streamedLength) : responseText,
        timestamp: '14:21',
        stepNumber: input.mode === 'STEP_BY_STEP' ? 1 : undefined,
        totalSteps: input.mode === 'STEP_BY_STEP' ? 3 : undefined,
        pedagogicalHint: input.mode === 'STEP_BY_STEP' ? 'Em hãy tính hoành độ đỉnh x trước nhé!' : undefined,
        knowledgeType,
        citations: isCancelled ? [] : citations, // No citations for incomplete/stopped text
        isIncomplete: isCancelled,
      };
      conv.messages.push(assistantMsg);
      conv.updatedAt = 'Vừa xong';
      return structuredClone(assistantMsg);
    },
    async stopStreaming(conversationId) {
      const user = signedIn();
      const stream = activeStreams.get(conversationId);
      if (stream) {
        if (stream.userId !== user.id) {
          throw new ApiError('FORBIDDEN', 'Bạn không có quyền dừng câu trả lời của người khác.', 403);
        }
        stream.aborted = true;
      }
    },
  },
  learning: {
    async startPracticeAttempt(input) {
      const user = signedIn();
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có thể bắt đầu lượt làm bài luyện tập.', 403);
      }
      const activeClassIds = getStudentActiveClassIds(user.id);
      if (!activeClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp học này.', 403);
      }
      const practice = practiceActivities.find(p => p.id === input.practiceId && p.classId === input.classId);
      if (!practice) {
        throw new ApiError('NOT_FOUND', 'Bài luyện tập không tồn tại trong lớp học này.', 404);
      }
      if (isMockAssessmentLocked(user.id, input.classId)) {
        throw new ApiError('FORBIDDEN', 'Khóa tương tác kiểm tra đang kích hoạt trong lớp học này.', 403);
      }

      // Resume intent: check if user already has an active in-progress attempt
      if (input.intent === 'resume') {
        const existing = Object.values(practiceAttempts).find(
          a => a.practiceId === input.practiceId && a.classId === input.classId && a.ownerUserId === user.id && !a.isCompleted
        );
        if (existing) {
          const href = `/student/classes/${input.classId}/practice/${input.practiceId}/attempts/${existing.attemptId}`;
          return { attemptId: existing.attemptId, href };
        }
      }

      // Start or Retry intent: create a new attempt from immutable published version snapshot
      const publishedVer = publishedPracticeVersions[practice.publishedVersionId];
      if (!publishedVer || publishedVer.classId !== input.classId || publishedVer.practiceId !== input.practiceId) {
        throw new ApiError('NOT_FOUND', 'Không tìm thấy phiên bản xuất bản hợp lệ cho bài luyện tập này.', 404);
      }
      const questionsSnapshot = publishedVer.questions;

      const newAttemptId = 'attempt-' + crypto.randomUUID();
      const cls = classes.find(c => c.id === input.classId);

      const newAttempt: PracticeAttemptDetail = {
        attemptId: newAttemptId,
        practiceId: input.practiceId,
        classId: input.classId,
        ownerUserId: user.id,
        publishedVersionId: practice.publishedVersionId,
        publishedVersionNumber: practice.publishedVersionNumber,
        className: cls?.name ?? 'Lớp học',
        title: practice.title,
        topic: practice.topic,
        primaryTeacherName: getClassPrimaryTeacherName(input.classId),
        questions: structuredClone(questionsSnapshot),
        savedAnswers: {},
        checkedFeedbacks: {},
        lastSavedAt: 'Vừa xong',
        startedAt: new Date().toISOString(),
        currentQuestionIndex: 0,
        isCompleted: false,
      };

      practiceAttempts[newAttemptId] = newAttempt;
      practice.status = 'IN_PROGRESS';
      practice.activeAttemptId = newAttemptId;

      const href = `/student/classes/${input.classId}/practice/${input.practiceId}/attempts/${newAttemptId}`;
      return { attemptId: newAttemptId, href };
    },

    async checkPracticeAnswer(input) {
      const user = signedIn();
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có thể kiểm tra đáp án luyện tập.', 403);
      }
      const activeClassIds = getStudentActiveClassIds(user.id);
      if (!activeClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp học này.', 403);
      }
      const attempt = practiceAttempts[input.attemptId];
      if (!attempt) {
        throw new ApiError('NOT_FOUND', 'Lượt làm bài không tồn tại.', 404);
      }
      // Actor and resource relations validation
      if (attempt.ownerUserId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền thao tác trên lượt làm bài của học sinh khác.', 403);
      }
      if (attempt.classId !== input.classId) {
        throw new ApiError('FORBIDDEN', 'Bài luyện tập không thuộc lớp học này.', 403);
      }
      if (attempt.practiceId !== input.practiceId) {
        throw new ApiError('FORBIDDEN', 'Lượt làm bài không thuộc bài luyện tập này.', 403);
      }
      if (attempt.isCompleted) {
        throw new ApiError('CONFLICT', 'Lượt làm bài đã hoàn thành, không thể kiểm tra lại đáp án.', 409);
      }

      if (input.questionId !== input.answer.questionId) {
        throw new ApiError('VALIDATION_ERROR', 'ID câu hỏi kiểm tra không khớp với câu trả lời.', 400);
      }

      const question = attempt.questions.find(q => q.id === input.questionId);
      if (!question) {
        throw new ApiError('NOT_FOUND', 'Câu hỏi không tồn tại trong bài luyện tập này.', 404);
      }

      validatePracticeAnswer(question, input.answer, { requireComplete: true });

      let isCorrect = false;
      if (question.type === 'single_choice') {
        isCorrect = input.answer.singleChoiceValue === question.correctOptionId;
      } else if (question.type === 'multiple_choice') {
        const correctSet = new Set(question.correctOptionIds ?? []);
        const selectedSet = new Set(input.answer.multipleChoiceValues ?? []);
        isCorrect = correctSet.size === selectedSet.size && [...correctSet].every(id => selectedSet.has(id));
      } else if (question.type === 'true_false') {
        const userAnswers = input.answer.trueFalseValues ?? {};
        isCorrect = question.statements.length > 0 && question.statements.every(st => userAnswers[st.id] === st.isCorrect);
      } else if (question.type === 'short_answer') {
        const userText = (input.answer.shortAnswerValue ?? '').trim().toLowerCase();
        const expText = (question.expectedAnswer ?? '').trim().toLowerCase();
        isCorrect = userText.length > 0 && (userText === expText || userText === 'x=' + expText || userText === 'x = ' + expText);
      }

      const rawFeedback: PracticeQuestionFeedback = {
        questionId: question.id,
        isCorrect,
        feedbackTitle: isCorrect
          ? 'Kiểm tra kết quả tức thời: Lựa chọn của bạn hoàn toàn chính xác!'
          : 'Kiểm tra kết quả tức thời: Câu trả lời chưa chính xác.',
        explanation: question.explanation ?? '',
        sourceReference: question.sourceReference,
        sourceRef: question.sourceRef,
        pedagogicalHint: question.sourceRef
          ? `Dựa vào tài liệu "${question.sourceRef.documentTitle}", hãy lưu ý phương pháp biến đổi và công thức tại ${question.sourceRef.locator}.`
          : 'Hãy chú ý công thức xác định toạ độ đỉnh và điều kiện của hệ số a.',
      };

      const feedback = sanitizeQuestionSource(rawFeedback, input.classId, user.id);

      attempt.savedAnswers[question.id] = structuredClone(input.answer);
      attempt.checkedFeedbacks[question.id] = structuredClone(feedback);
      attempt.lastSavedAt = 'Vừa xong';

      return structuredClone(feedback);
    },

    async savePracticeDraft(input) {
      const user = signedIn();
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có thể lưu bản nháp luyện tập.', 403);
      }
      const activeClassIds = getStudentActiveClassIds(user.id);
      if (!activeClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp học này.', 403);
      }
      const attempt = practiceAttempts[input.attemptId];
      if (!attempt) {
        throw new ApiError('NOT_FOUND', 'Lượt làm bài không tồn tại.', 404);
      }
      // Actor and resource relations validation
      if (attempt.ownerUserId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền thao tác trên lượt làm bài của học sinh khác.', 403);
      }
      if (attempt.classId !== input.classId) {
        throw new ApiError('FORBIDDEN', 'Bài luyện tập không thuộc lớp học này.', 403);
      }
      if (attempt.practiceId !== input.practiceId) {
        throw new ApiError('FORBIDDEN', 'Lượt làm bài không thuộc bài luyện tập này.', 403);
      }
      if (attempt.isCompleted) {
        throw new ApiError('CONFLICT', 'Bài luyện tập đã hoàn thành, không thể lưu thêm bản nháp.', 409);
      }

      // Shared runtime validation for all answers
      for (const [qid, newAns] of Object.entries(input.answers)) {
        if (qid !== newAns.questionId) {
          throw new ApiError('VALIDATION_ERROR', 'Khoá câu hỏi trong bản ghi không khớp với answer.questionId.', 400);
        }
        const q = attempt.questions.find(item => item.id === qid);
        if (!q) {
          throw new ApiError('VALIDATION_ERROR', `Câu hỏi "${qid}" không tồn tại trong bài luyện tập này.`, 400);
        }
        validatePracticeAnswer(q, newAns, { requireComplete: false });
      }

      // Saving changed answers invalidates old checked feedback for those answers
      for (const [qid, newAns] of Object.entries(input.answers)) {
        const existingAns = attempt.savedAnswers[qid];
        if (existingAns && JSON.stringify(existingAns) !== JSON.stringify(newAns)) {
          delete attempt.checkedFeedbacks[qid];
        }
        attempt.savedAnswers[qid] = structuredClone(newAns);
      }
      attempt.lastSavedAt = 'Vừa xong';

      return { savedAt: 'Vừa xong' };
    },

    async finishPracticeAttempt(input) {
      const user = signedIn();
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('STUDENT')) {
        throw new ApiError('FORBIDDEN', 'Chỉ học sinh mới có thể hoàn thành bài luyện tập.', 403);
      }
      const activeClassIds = getStudentActiveClassIds(user.id);
      if (!activeClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không thuộc danh sách học sinh của lớp học này.', 403);
      }
      const attempt = practiceAttempts[input.attemptId];
      if (!attempt) {
        throw new ApiError('NOT_FOUND', 'Lượt làm bài không tồn tại.', 404);
      }
      // Actor and resource relations validation
      if (attempt.ownerUserId !== user.id) {
        throw new ApiError('FORBIDDEN', 'Bạn không có quyền nộp bài của học sinh khác.', 403);
      }
      if (attempt.classId !== input.classId) {
        throw new ApiError('FORBIDDEN', 'Bài luyện tập không thuộc lớp học này.', 403);
      }
      if (attempt.practiceId !== input.practiceId) {
        throw new ApiError('FORBIDDEN', 'Lượt làm bài không thuộc bài luyện tập này.', 403);
      }

      // Idempotent repeated finish: return confirmed result without duplicate mutation
      if (attempt.isCompleted && practiceResults[input.attemptId]) {
        const resultHref = `/student/classes/${input.classId}/practice/${input.practiceId}/attempts/${input.attemptId}/result`;
        return { resultHref, attemptId: input.attemptId };
      }

      // Score all saved answers against the pinned snapshot
      let correctCount = 0;
      let incorrectCount = 0;
      let unansweredCount = 0;
      const resultQuestions: PracticeResultQuestionItem[] = [];

      for (let i = 0; i < attempt.questions.length; i++) {
        const q = attempt.questions[i];
        const saved = attempt.savedAnswers[q.id];
        let isCorrect = false;
        let studentText = '(Chưa trả lời)';
        let correctText = '';

        if (q.type === 'single_choice') {
          const opt = q.options.find(o => o.id === q.correctOptionId);
          correctText = opt ? `${opt.label}. ${opt.text}` : '';
          if (saved?.singleChoiceValue) {
            const userOpt = q.options.find(o => o.id === saved.singleChoiceValue);
            studentText = userOpt ? `${userOpt.label}. ${userOpt.text}` : saved.singleChoiceValue;
            isCorrect = saved.singleChoiceValue === q.correctOptionId;
          }
        } else if (q.type === 'multiple_choice') {
          const correctSet = new Set(q.correctOptionIds ?? []);
          correctText = q.options.filter(o => correctSet.has(o.id)).map(o => `${o.label}. ${o.text}`).join('; ');
          if (saved?.multipleChoiceValues && saved.multipleChoiceValues.length > 0) {
            const selectedSet = new Set(saved.multipleChoiceValues);
            studentText = q.options.filter(o => selectedSet.has(o.id)).map(o => `${o.label}. ${o.text}`).join('; ');
            isCorrect = correctSet.size === selectedSet.size && [...correctSet].every(id => selectedSet.has(id));
          }
        } else if (q.type === 'true_false') {
          correctText = q.statements.map(st => `${st.label}: ${st.isCorrect ? 'Đúng' : 'Sai'}`).join(' · ');
          if (saved?.trueFalseValues && Object.keys(saved.trueFalseValues).length > 0) {
            studentText = q.statements.map(st => {
              const userVal = saved?.trueFalseValues?.[st.id];
              const labelVal = userVal === true ? 'Đúng' : userVal === false ? 'Sai' : '(Chưa chọn)';
              return `${st.label}: ${labelVal}`;
            }).join(' · ');
            isCorrect = q.statements.every(st => saved.trueFalseValues?.[st.id] === st.isCorrect);
          }
        } else if (q.type === 'short_answer') {
          correctText = q.expectedAnswer ?? '';
          if (saved?.shortAnswerValue && saved.shortAnswerValue.trim().length > 0) {
            studentText = saved.shortAnswerValue.trim();
            const userNorm = studentText.toLowerCase();
            const expNorm = correctText.toLowerCase();
            isCorrect = userNorm === expNorm || userNorm === 'x=' + expNorm || userNorm === 'x = ' + expNorm;
          }
        }

        const hasAnswer = saved && (
          !!saved.singleChoiceValue ||
          (saved.multipleChoiceValues && saved.multipleChoiceValues.length > 0) ||
          (saved.trueFalseValues && Object.keys(saved.trueFalseValues).length > 0) ||
          (saved.shortAnswerValue && saved.shortAnswerValue.trim().length > 0)
        );

        if (!hasAnswer) {
          unansweredCount++;
        } else if (isCorrect) {
          correctCount++;
        } else {
          incorrectCount++;
        }

        const rawResultItem: PracticeResultQuestionItem = {
          id: 'res-' + q.id,
          questionNumber: i + 1,
          prompt: q.prompt,
          type: q.type,
          studentAnswerText: studentText,
          correctAnswerText: correctText,
          isCorrect,
          explanation: q.explanation ?? '',
          sourceReference: q.sourceReference,
          sourceRef: q.sourceRef,
        };

        resultQuestions.push(sanitizeQuestionSource(rawResultItem, input.classId, user.id));
      }

      const total = attempt.questions.length;
      const percentage = Math.round((correctCount / Math.max(1, total)) * 100);
      const completedAtTime = new Date();
      const completedAtStr = `${completedAtTime.getDate().toString().padStart(2, '0')}/${(completedAtTime.getMonth() + 1).toString().padStart(2, '0')}/${completedAtTime.getFullYear()} ${completedAtTime.getHours().toString().padStart(2, '0')}:${completedAtTime.getMinutes().toString().padStart(2, '0')}`;
      const startedTime = new Date(attempt.startedAt).getTime();
      const elapsedMs = Math.max(0, completedAtTime.getTime() - startedTime);
      const durationMinutes = Math.max(0, Math.round((elapsedMs / 60000) * 10) / 10);

      const res: PracticeResultDetail = {
        attemptId: input.attemptId,
        practiceId: input.practiceId,
        classId: input.classId,
        ownerUserId: user.id,
        publishedVersionId: attempt.publishedVersionId,
        publishedVersionNumber: attempt.publishedVersionNumber,
        className: attempt.className,
        title: attempt.title,
        attemptNumber: 1,
        completedAt: completedAtStr,
        startedAt: attempt.startedAt,
        durationMinutes,
        score: { correct: correctCount, total, percentage },
        correctCount,
        incorrectCount,
        unansweredCount,
        studyTip: percentage >= 80
          ? 'Kết quả rất tốt! Em hãy tiếp tục duy trì phong độ và thử thách các bài tập nâng cao.'
          : 'Dành 5 phút xem lại bảng tóm tắt công thức hoặc hỏi trợ lý Lumi để giải tỏa các băn khoăn về dấu của hệ số a và b.',
        questions: resultQuestions,
      };

      practiceResults[input.attemptId] = res;
      recordLearningEvidence({ id: res.attemptId, kind: 'PRACTICE', classId: res.classId, studentId: user.id, resourceId: res.practiceId, studentHref: `/student/classes/${res.classId}/practice/${res.practiceId}/attempts/${res.attemptId}/result`, title: res.title, topic: practiceActivities.find(item => item.id === res.practiceId)?.topic ?? 'Luyện tập', occurredAt: completedAtTime.toISOString(), gradeVersion: 1, score: correctCount, maxScore: Math.max(1, total) });
      attempt.isCompleted = true;
      attempt.completedAt = completedAtStr;

      // Update student's practice activity status and history
      const act = practiceActivities.find(p => p.id === input.practiceId && p.classId === input.classId);
      if (act) {
        act.status = 'COMPLETED';
        act.lastCompletedAt = completedAtStr.split(' ')[0];
        act.lastScore = { correct: correctCount, total, percentage };
        act.latestResultAttemptId = input.attemptId;
        act.totalAttempts = (act.totalAttempts ?? 0) + 1;
        res.attemptNumber = act.totalAttempts;
        if (!act.history) act.history = [];
        act.history.unshift({
          attemptId: input.attemptId,
          practiceId: input.practiceId,
          practiceTitle: act.title,
          attemptNumber: act.totalAttempts,
          completedAt: completedAtStr,
          score: { correct: correctCount, total, percentage },
          durationMinutes,
          resultHref: `/student/classes/${input.classId}/practice/${input.practiceId}/attempts/${input.attemptId}/result`,
        });
      }

      const resultHref = `/student/classes/${input.classId}/practice/${input.practiceId}/attempts/${input.attemptId}/result`;
      return { resultHref, attemptId: input.attemptId };
    },

    async createPracticeDraft(input) {
      const user = signedIn();
      requireClassInteraction(input.classId, user, true);
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên mới có thể khởi tạo bài luyện tập.', 403);
      }
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      if (!allowedClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không được phân công giảng dạy lớp học này.', 403);
      }
      const newPracticeId = 'prac-' + crypto.randomUUID();
      const cls = classes.find(c => c.id === input.classId);

      const newEditor: TeacherPracticeEditorModel = {
        practiceId: newPracticeId,
        classId: input.classId,
        className: cls?.name ?? 'Lớp học',
        title: input.title.trim(),
        topic: input.topic.trim(),
        versionLabel: `Bản nháp mới: ${input.title.trim()}`,
        currentVersionNumber: 1,
        isDraft: true,
        questions: [],
        reviewedCount: 0,
        totalQuestions: 0,
        canPublish: false,
        availableClassSources: getAvailableClassSources(input.classId),
      };

      teacherPracticeEditors[newPracticeId] = newEditor;

      teacherActivities.unshift({
        id: 'act-' + crypto.randomUUID(),
        classId: input.classId,
        resourceId: newPracticeId,
        title: input.title.trim(),
        type: 'PRACTICE',
        topic: input.topic.trim(),
        status: 'DRAFT',
        dueOrTimeLabel: 'Bản nháp',
        editHref: `/teacher/classes/${input.classId}/practice/${newPracticeId}/edit`,
        notes: 'Bản nháp bài luyện tập mới.',
      });

      return {
        practiceId: newPracticeId,
        editHref: `/teacher/classes/${input.classId}/practice/${newPracticeId}/edit`,
      };
    },

    async savePracticeEditorDraft(input) {
      const user = signedIn();
      requireClassInteraction(input.classId, user, true);
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên mới có thể chỉnh sửa bài luyện tập.', 403);
      }
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      if (!allowedClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không được phân công dạy lớp học này.', 403);
      }
      const editor = teacherPracticeEditors[input.practiceId];
      if (!editor) {
        throw new ApiError('NOT_FOUND', 'Bài luyện tập không tồn tại.', 404);
      }
      // Cross-class editor save denial (Supervisor check 8)
      if (editor.classId !== input.classId) {
        throw new ApiError('FORBIDDEN', 'Bài luyện tập không thuộc lớp học được chỉ định.', 403);
      }

      // Editing a published question must start a new unreviewed draft without mutating existing published snapshot
      if (!editor.isDraft) {
        editor.isDraft = true;
        editor.currentVersionNumber += 1;
        editor.versionLabel = `Bản nháp phiên bản ${editor.currentVersionNumber}: ${editor.title}`;
        const actRow = teacherActivities.find(
          a => a.type === 'PRACTICE' && a.classId === input.classId && a.resourceId === input.practiceId
        );
        if (actRow) {
          actRow.status = 'DRAFT';
          actRow.dueOrTimeLabel = 'Bản nháp';
        }
      }

      if (input.title) editor.title = input.title;
      if (input.topic) editor.topic = input.topic;

      // Question edits: Save must NEVER grant review on new questions or substantive edits.
      // Retain only previously stored human review when substantive content is unchanged.
      if (input.questions) {
        const prevMap = new Map(editor.questions.map(q => [q.id, q]));
        const updatedQuestions = input.questions.map(q => {
          const prev = prevMap.get(q.id);
          let isReviewed = false;
          if (prev && prev.isReviewed) {
            const prevSub = { ...prev, isReviewed: undefined };
            const qSub = { ...q, isReviewed: undefined };
            if (JSON.stringify(prevSub) === JSON.stringify(qSub)) {
              isReviewed = true;
            }
          }
          return { ...q, isReviewed };
        });
        editor.questions = updatedQuestions;
        editor.totalQuestions = updatedQuestions.length;
        editor.reviewedCount = updatedQuestions.filter(q => q.isReviewed).length;
        editor.canPublish =
          editor.reviewedCount === editor.totalQuestions &&
          editor.totalQuestions > 0 &&
          editor.questions.every(q => {
            try {
              validateQuestionForPublication(q);
              return true;
            } catch {
              return false;
            }
          });
      }

      // Sync activity row in teacherActivities by resourceId
      const act = teacherActivities.find(
        a => a.type === 'PRACTICE' && a.classId === input.classId && a.resourceId === input.practiceId
      );
      if (act) {
        if (input.title) act.title = input.title;
        if (input.topic) act.topic = input.topic;
      }

      return {
        savedAt: 'Vừa xong',
        reviewedCount: editor.reviewedCount,
        canPublish: editor.canPublish,
      };
    },

    async reviewEditorQuestion(input) {
      const user = signedIn();
      requireClassInteraction(input.classId, user, true);
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên mới có thể duyệt câu hỏi.', 403);
      }
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      if (!allowedClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không được phân công dạy lớp học này.', 403);
      }
      const editor = teacherPracticeEditors[input.practiceId];
      if (!editor) {
        throw new ApiError('NOT_FOUND', 'Bài luyện tập không tồn tại.', 404);
      }
      // Cross-class editor check (Supervisor check 8)
      if (editor.classId !== input.classId) {
        throw new ApiError('FORBIDDEN', 'Bài luyện tập không thuộc lớp học được chỉ định.', 403);
      }
      const question = editor.questions.find(q => q.id === input.questionId);
      if (!question) {
        throw new ApiError('NOT_FOUND', 'Câu hỏi không tồn tại.', 404);
      }

      if (input.approved) {
        validateQuestionForPublication(question);
        question.isReviewed = true;
      } else {
        question.isReviewed = false;
      }

      editor.reviewedCount = editor.questions.filter(q => q.isReviewed).length;
      editor.canPublish =
        editor.reviewedCount === editor.questions.length &&
        editor.questions.length > 0 &&
        editor.questions.every(q => {
          try {
            validateQuestionForPublication(q);
            return true;
          } catch {
            return false;
          }
        });

      return {
        reviewedCount: editor.reviewedCount,
        canPublish: editor.canPublish,
      };
    },

    async publishPractice(input) {
      const user = signedIn();
      requireClassInteraction(input.classId, user, true);
      if (user.status !== 'ACTIVE') {
        throw new ApiError('FORBIDDEN', 'Tài khoản của bạn hiện không hoạt động.', 403);
      }
      if (!user.roles.includes('LECTURER')) {
        throw new ApiError('FORBIDDEN', 'Chỉ giáo viên mới có thể xuất bản bài luyện tập.', 403);
      }
      const allowedClassIds = getTeacherAssignedClassIds(user.id);
      if (!allowedClassIds.includes(input.classId)) {
        throw new ApiError('FORBIDDEN', 'Bạn không được phân công dạy lớp học này.', 403);
      }
      const editor = teacherPracticeEditors[input.practiceId];
      if (!editor) {
        throw new ApiError('NOT_FOUND', 'Bài luyện tập không tồn tại.', 404);
      }
      // Cross-class editor check (Supervisor check 8)
      if (editor.classId !== input.classId) {
        throw new ApiError('FORBIDDEN', 'Bài luyện tập không thuộc lớp học được chỉ định.', 403);
      }

      // Repeated publish with no new draft: return existing already-confirmed version
      if (!editor.isDraft) {
        const existingVerId = `ver-${editor.practiceId}-${editor.currentVersionNumber}`;
        if (publishedPracticeVersions[existingVerId]) {
          return {
            success: true,
            practiceId: editor.practiceId,
            publishedVersionId: existingVerId,
          };
        }
      }

      // Validation before publication
      if (editor.questions.length === 0) {
        throw new ApiError('VALIDATION_ERROR', 'Bài luyện tập phải có ít nhất một câu hỏi trước khi xuất bản.', 400);
      }
      const idSet = new Set(editor.questions.map(q => q.id));
      if (idSet.size !== editor.questions.length) {
        throw new ApiError('VALIDATION_ERROR', 'Mỗi câu hỏi phải có mã định danh duy nhất.', 400);
      }
      for (const q of editor.questions) {
        validateQuestionForPublication(q);
        if (q.sourceRef && !previewContext.sourceAccessible(user.id, input.classId, q.sourceRef.documentId, q.sourceRef.versionNumber)) throw new ApiError('FORBIDDEN', 'Nguồn của câu hỏi không còn khả dụng. Hãy kiểm tra lại trước khi công bố.', 403);
      }
      if (!editor.questions.every(q => q.isReviewed)) {
        throw new ApiError('VALIDATION_ERROR', 'Tất cả câu hỏi phải được giáo viên duyệt trước khi xuất bản.', 400);
      }

      const nextVerNum = editor.currentVersionNumber;
      const publishedVerId = `ver-${editor.practiceId}-${nextVerNum}`;
      const publishedVer: PublishedPracticeVersion = {
        id: publishedVerId,
        practiceId: editor.practiceId,
        classId: editor.classId,
        versionNumber: nextVerNum,
        title: editor.title,
        topic: editor.topic,
        questions: structuredClone(editor.questions),
        publishedAt: new Date().toISOString(),
        publishedByUserId: user.id,
      };

      publishedPracticeVersions[publishedVerId] = publishedVer;
      editor.isDraft = false;
      editor.versionLabel = `Phiên bản ${nextVerNum} (Đã xuất bản)`;
      editor.currentVersionNumber = nextVerNum;

      // Update Teacher Activities row by resourceId
      const act = teacherActivities.find(
        a => a.type === 'PRACTICE' && a.classId === input.classId && a.resourceId === input.practiceId
      );
      if (act) {
        act.status = 'PUBLISHED';
        act.dueOrTimeLabel = 'Không đặt hạn';
        act.title = editor.title;
        act.topic = editor.topic;
      } else {
        teacherActivities.unshift({
          id: 'act-' + crypto.randomUUID(),
          classId: editor.classId,
          resourceId: editor.practiceId,
          title: editor.title,
          type: 'PRACTICE',
          topic: editor.topic,
          status: 'PUBLISHED',
          dueOrTimeLabel: 'Không đặt hạn',
          editHref: `/teacher/classes/${editor.classId}/practice/${editor.practiceId}/edit`,
          submissionsHref: `/teacher/classes/${editor.classId}/practice/${editor.practiceId}/edit`,
          notes: 'Bài luyện tập đã xuất bản.',
        });
      }

      // Synchronize Student practice activities list
      let studentAct = practiceActivities.find(p => p.id === editor.practiceId && p.classId === editor.classId);
      if (studentAct) {
        studentAct.title = editor.title;
        studentAct.topic = editor.topic;
        studentAct.questionCount = editor.questions.length;
        studentAct.publishedVersionId = publishedVerId;
        studentAct.publishedVersionNumber = nextVerNum;
      } else {
        practiceActivities.push({
          id: editor.practiceId,
          classId: editor.classId,
          title: editor.title,
          topic: editor.topic,
          questionCount: editor.questions.length,
          status: 'NOT_STARTED',
          publishedVersionId: publishedVerId,
          publishedVersionNumber: nextVerNum,
          totalAttempts: 0,
          history: [],
        });
      }

      return {
        success: true,
        practiceId: editor.practiceId,
        publishedVersionId: publishedVerId,
      };
    },
  },
  workspace: {
    async load(routeId, params) {
      const user = signedIn();
      const isStudent = user.roles.includes('STUDENT');
      const isTeacher = user.roles.includes('LECTURER');

      // Validate class access if route has classId
      let summary: ClassSummary | undefined;
      if (params.classId) {
        summary = classes.find(x => x.id === params.classId);
        if (!summary) {
          return { kind: 'unavailable', message: 'Lớp học không tồn tại trong hệ thống.' };
        }

        summary = routeId.startsWith('t.') ? getTeacherClassSummary(summary, user.id) : structuredClone(summary);
        if (routeId.startsWith('s.')) summary.membershipStatus = getStudentActiveClassIds(user.id).includes(params.classId) ? 'ACTIVE' : 'ENDED';

        // Student class access checks
        if (isStudent && routeId.startsWith('s.')) {
          if (routeId === 's.history' && getStudentActiveClassIds(user.id).includes(params.classId)) return { kind: 'unavailable', message: 'L?p h?c ?ang ho?t ??ng. H?y m? t?ng quan l?p ?? ti?p t?c h?c.' };
          if (['s.history', 's.historyResult', 's.examResult', 's.receipt', 's.practiceResult'].includes(routeId)) {
            if (!getStudentActiveClassIds(user.id).includes(params.classId) && !getStudentEndedClassIds(user.id).includes(params.classId) && !getStudentArchivedClassIds(user.id).includes(params.classId)) {
              return { kind: 'unavailable', message: 'Bạn không có dữ liệu lưu trữ lịch sử cho lớp học này.' };
            }
          } else {
            if (summary.status === 'ARCHIVED') {
              return { kind: 'unavailable', message: 'Lớp học đã lưu trữ, các tương tác trực tiếp đã đóng.' };
            }
            if (!getStudentActiveClassIds(user.id).includes(params.classId)) {
              return { kind: 'unavailable', message: 'Bạn không thuộc danh sách học sinh của lớp học này.' };
            }
          }
        }

        // Teacher class access checks
        if (isTeacher && routeId.startsWith('t.')) {
          if (summary.status === 'ARCHIVED' && !['t.examGrading', 't.assignmentGrading', 't.gradingQueue', 't.correction', 't.correctionApproval'].includes(routeId)) {
            return { kind: 'unavailable', message: 'Lớp học đã lưu trữ trong kho lưu trữ học vụ.' };
          }
          if (!getTeacherAssignedClassIds(user.id).includes(params.classId)) {
            return { kind: 'unavailable', message: 'Bạn không được phân công giảng dạy lớp học này.' };
          }
        }
      }

      // Student Home & Classes
      if (routeId === 's.home') {
        const studentClasses = classes.filter(c => getStudentActiveClassIds(user.id).includes(c.id));
        return {
          kind: 'ready',
          classes: structuredClone(studentClasses),
          studentHome: await makeStudentHome(user, studentClasses),
        };
      }
      if (routeId === 's.classes') {
        const activeIds = getStudentActiveClassIds(user.id);
        const endedIds = getStudentEndedClassIds(user.id);
        const archivedIds = getStudentArchivedClassIds(user.id);
        const studentClasses = classes
          .filter(c => activeIds.includes(c.id) || endedIds.includes(c.id) || archivedIds.includes(c.id))
          .map(c => {
            const copy = structuredClone(c);
            if (endedIds.includes(c.id)) {
              copy.membershipStatus = 'ENDED';
            } else if (activeIds.includes(c.id)) {
              copy.membershipStatus = 'ACTIVE';
            }
            return copy;
          });
        return {
          kind: 'ready',
          classes: studentClasses,
        };
      }
      if (routeId === 's.overview') {
        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          classOverview: summary ? await makeClassOverview(summary, user) : undefined,
        };
      }

      // Teacher Home & Classes
      if (routeId === 't.home') {
        const assignedIds = getTeacherAssignedClassIds(user.id);
        const assigned = classes.filter(c => assignedIds.includes(c.id)).map(c => getTeacherClassSummary(c, user.id));
        return {
          kind: 'ready',
          classes: structuredClone(assigned),
          teacherHome: {
            ...structuredClone(teacherHomeOverview), assignedClasses: structuredClone(assigned),
            recentDiscussions: structuredClone(teacherHomeOverview.recentDiscussions.filter(item => assignedIds.includes(item.classId))),
            todaySchedule: structuredClone(calendarEvents.filter(item => item.classId && assignedIds.includes(item.classId) && item.date === previewDisplayDate)),
            stats: { totalClasses: assigned.length, totalStudents: new Set(assigned.flatMap(cls => previewClassroomStore.activeStudentIds(cls.id))).size, pendingGrading: (await Promise.all(assigned.filter(cls => cls.status === 'ACTIVE').map(cls => teacherMetrics(user, cls.id)))).reduce((total, metrics) => total + metrics.pendingGrading, 0) },
          },
        };
      }
      if (routeId === 't.classes') {
        const assignedIds = getTeacherAssignedClassIds(user.id);
        const assigned = classes.filter(c => assignedIds.includes(c.id)).map(c => getTeacherClassSummary(c, user.id));
        return {
          kind: 'ready',
          classes: structuredClone(assigned),
        };
      }
      if (routeId === 't.overview') {
        return {
          kind: 'ready',
          teacherMetrics: summary ? await teacherMetrics(user, summary.id) : undefined,
          classSummary: summary ? getTeacherClassSummary(summary, user.id) : undefined,
          classOverview: summary ? await makeClassOverview(summary, user) : undefined,
        };
      }

      // Feed
      if (routeId === 's.feed' || routeId === 't.feed') {
        const posts = params.classId
          ? feedPosts.filter(p => p.classId === params.classId)
          : feedPosts;
        return {
          kind: 'ready',
          classSummary: summary ? (isTeacher ? getTeacherClassSummary(summary, user.id) : structuredClone(summary)) : undefined,
          feedPosts: structuredClone(posts),
        };
      }

      // Calendar
      if (routeId === 'account.calendar') {
        const allowedClassIds = isStudent
          ? getStudentActiveClassIds(user.id)
          : isTeacher
          ? getTeacherAssignedClassIds(user.id)
          : [];
        const userEvents = [...calendarEvents.filter(e => !['ASSIGNMENT','EXAM'].includes(e.category) && (!e.classId || (allowedClassIds.includes(e.classId) && classes.find(cls => cls.id === e.classId)?.status === 'ACTIVE'))), ...await learningCalendar(user)];
        const assigned = isTeacher
          ? classes.filter(c => getTeacherAssignedClassIds(user.id).includes(c.id)).map(c => getTeacherClassSummary(c, user.id))
          : undefined;
        return {
          kind: 'ready',
          classes: assigned ? structuredClone(assigned) : undefined,
          calendarEvents: structuredClone(userEvents),
          displayDate: previewDisplayDate,
        };
      }
      if (routeId === 's.calendar' || routeId === 't.calendar') {
        const events = [...calendarEvents.filter(e => !['ASSIGNMENT','EXAM'].includes(e.category) && (!e.classId || e.classId === params.classId)), ...await learningCalendar(user, params.classId)];
        return {
          kind: 'ready',
          classSummary: summary ? (isTeacher ? getTeacherClassSummary(summary, user.id) : structuredClone(summary)) : undefined,
          calendarEvents: structuredClone(events),
          displayDate: previewDisplayDate,
        };
      }

      // Notifications (Only for current user!)
      if (routeId === 'account.notifications') {
        const userNotifs = await actorNotifications(user);
        return {
          kind: 'ready',
          notifications: structuredClone(userNotifs),
        };
      }

      // History (S08a vs S08b)
      if (routeId === 's.history') {
        const histData = params.classId === '00000000-0000-4000-8000-000000000102'
          ? historyData10A2
          : historyData9A1;
        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          historyData: structuredClone(histData),
        };
      }

      // Stage 2: Teacher Library (D01, D02)
      if (routeId === 't.library') {
        if (!isTeacher) {
          return { kind: 'unavailable', message: 'Chỉ giáo viên mới có quyền xem thư viện tài liệu.' };
        }
        const userDocs = documents.filter(d => d.ownerId === user.id);
        return {
          kind: 'ready',
          libraryDocuments: userDocs.map(doc => currentDocumentView(doc, user)),
          capabilityPolicy: structuredClone(documentCapabilityPolicy),
        };
      }

      // Stage 2: Teacher Library Document Detail & Versions (D03, D04, D05, D06)
      if (routeId === 't.libraryDocument') {
        if (!isTeacher) {
          return { kind: 'unavailable', message: 'Chỉ giáo viên mới có quyền xem chi tiết tài liệu thư viện.' };
        }
        const doc = documents.find(d => d.id === params.documentId);
        if (!doc) {
          return { kind: 'empty', message: 'Không tìm thấy tài liệu trong thư viện cá nhân.' };
        }
        if (doc.ownerId !== user.id) {
          return { kind: 'unavailable', message: 'Bạn không có quyền truy cập tài liệu này.' };
        }
        const vers = documentVersions[doc.id] ?? [];
        const grants = documentGrants[doc.id] ?? [];
        return {
          kind: 'ready',
          sourceDocumentDetail: {
            document: currentDocumentView(doc, user),
            versions: structuredClone(vers),
            grants: grants.map(grant => { const cls = previewClassroomStore.getClass(grant.classId); return { ...structuredClone(grant), className: cls?.name ?? grant.className, classCode: cls?.code ?? grant.classCode }; }),
          },
          capabilityPolicy: structuredClone(documentCapabilityPolicy),
        };
      }

      // Stage 2: Teacher Class Documents (D07)
      if (routeId === 't.documents') {
        const classDocs = documents
          .filter(d => (documentGrants[d.id] ?? []).some(g => g.classId === params.classId && g.isShared))
          .map(d => ({
            ...currentDocumentView(d, user),
            currentVersion: (documentGrants[d.id] ?? []).find(g => g.classId === params.classId && g.isShared)!.servingVersion,
            processingStatus: (documentVersions[d.id] ?? []).find(v => v.versionNumber === (documentGrants[d.id] ?? []).find(g => g.classId === params.classId && g.isShared)!.servingVersion)?.status ?? d.processingStatus,
            canManageSource: d.ownerId === user.id, // Only owner can manage source under Rule O1
            canRevokeGrant: true, // Both primary and assisting can revoke share from class under Rule O1
          }));
        return {
          kind: 'ready',
          classSummary: summary ? getTeacherClassSummary(summary, user.id) : undefined,
          classDocuments: structuredClone(classDocs),
          capabilityPolicy: structuredClone(documentCapabilityPolicy),
        };
      }

      // Stage 2: Teacher Class Tutor Config (D08)
      if (routeId === 't.tutor') {
        const conf = teacherTutorConfigs[params.classId] ?? {
          classId: params.classId,
          instructions: '',
          updatedAt: 'Chưa có cấu hình',
          maxChars: 2000,
          disclaimer: 'Cấu hình chỉ dẫn sư phạm này được áp dụng cho Lumi khi giải đáp cho học sinh lớp này. Giáo viên không thể xem các đoạn hội thoại hoặc câu hỏi riêng tư của học sinh.',
        };
        return {
          kind: 'ready',
          classSummary: summary ? getTeacherClassSummary(summary, user.id) : undefined,
          teacherTutorConfig: structuredClone(conf),
        };
      }

      // Stage 2: Student Class Documents (base-e93071d9)
      if (routeId === 's.documents') {
        const classDocs = documents
          .filter(d => (documentGrants[d.id] ?? []).some(g => g.classId === params.classId && g.isShared))
          .map(d => ({
            ...currentDocumentView(d, user),
            currentVersion: (documentGrants[d.id] ?? []).find(g => g.classId === params.classId && g.isShared)!.servingVersion,
            processingStatus: (documentVersions[d.id] ?? []).find(v => v.versionNumber === (documentGrants[d.id] ?? []).find(g => g.classId === params.classId && g.isShared)!.servingVersion)?.status ?? d.processingStatus,
            isBookmarked: bookmarks.some(b => b.documentId === d.id && b.classId === params.classId && b.userId === user.id),
          }));
        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          classDocuments: structuredClone(classDocs),
          capabilityPolicy: structuredClone(documentCapabilityPolicy),
        };
      }

      // Stage 2: Student Reader (base-41d6544a, base-ae547183, SH_R02)
      if (routeId === 's.reader') {
        if (!isStudent) {
          return { kind: 'unavailable', message: 'Chỉ học sinh mới có quyền xem tài liệu học tập.' };
        }
        const doc = documents.find(d => d.id === params.documentId);
        const ownNotes = personalNotes.filter(n => n.userId === user.id && n.documentId === params.documentId);

        if (!doc) {
          if (ownNotes.length > 0) {
            // Reconstruct minimal metadata from student's own stored note
            const sample = ownNotes[0];
            const reconstructedDoc: DocumentItem = {
              id: params.documentId,
              title: sample.documentTitle,
              format: sample.documentFormat,
              currentVersion: sample.version ?? 1,
              processingStatus: 'READY',
              ownerId: '',
              ownerName: 'Giáo viên',
              createdAt: '',
              updatedAt: '',
            };
            return {
              kind: 'ready',
              classSummary: summary ? structuredClone(summary) : undefined,
              readerModel: {
                document: reconstructedDoc,
                servingVersion: sample.version ?? 1,
                isSourceAccessible: false,
                revokedReason: 'Tài liệu nguồn đã bị xóa khỏi hệ thống. Bạn vẫn có thể xem lại các ghi chú cá nhân đã lưu.',
                outline: [],
                currentPage: 1,
                totalPages: 0,
                notes: ownNotes.map(sanitizeNoteForStudent),
              },
            };
          }
          return { kind: 'unavailable', message: 'Tài liệu không tồn tại hoặc đã bị xóa.' };
        }

        const isGranted = Boolean((documentGrants[doc.id] ?? []).some(g => g.classId === params.classId && g.isShared));

        if (!isGranted) {
          // Revoked source state (base-ae547183): unmount viewer, hide source excerpts, keep own notes!
          return {
            kind: 'ready',
            classSummary: summary ? structuredClone(summary) : undefined,
            readerModel: {
              document: currentDocumentView(doc, user),
              servingVersion: doc.currentVersion,
              isSourceAccessible: false,
              revokedReason: 'Nguồn tài liệu không còn khả dụng trong lớp học này do giáo viên đã thu hồi quyền chia sẻ hoặc tài liệu đã bị xóa.',
              outline: [],
              currentPage: 1,
              totalPages: 0,
              notes: ownNotes.map(sanitizeNoteForStudent),
            },
          };
        }

        // Validate version existence and READY status
        const grant = (documentGrants[doc.id] ?? []).find(g => g.classId === params.classId && g.isShared)!;
        const vers = documentVersions[doc.id] ?? [];
        const reqVer = params.version ? Number(params.version) : grant.servingVersion;
        const verObj = vers.find(v => v.versionNumber === reqVer);

        if (!verObj || verObj.status !== 'READY') {
          return { kind: 'unavailable', message: `Phiên bản v${reqVer} không tồn tại hoặc chưa sẵn sàng phục vụ.` };
        }

        const model = mockReaderModels[doc.id];
        const totalPages = model?.totalPages ?? doc.pageCount ?? 1;
        const reqPage = params.page ? Number(params.page) : 1;

        if (isNaN(reqPage) || reqPage < 1 || (totalPages > 0 && reqPage > totalPages)) {
          return { kind: 'unavailable', message: `Trang ${params.page} nằm ngoài phạm vi tài liệu (1 - ${totalPages}).` };
        }

        let readerData: DocumentReaderModel;
        if (model && reqVer === grant.servingVersion) {
          readerData = {
            ...structuredClone(model),
            document: currentDocumentView(doc, user),
            servingVersion: grant.servingVersion,
            viewingVersion: reqVer,
            currentPage: reqPage,
            isSourceAccessible: true,
            notes: ownNotes.map(sanitizeNoteForStudent),
          };
        } else {
          // Honest preview for older versions or non-mocked formats without cloning math body
          readerData = {
            document: currentDocumentView(doc, user),
            servingVersion: grant.servingVersion,
            viewingVersion: reqVer,
            currentPage: reqPage,
            totalPages,
            outline: [{ id: `sec-v${reqVer}`, label: `Phiên bản v${reqVer} - Trang ${reqPage}`, pageNumber: reqPage }],
            pageContents: [
              {
                pageNumber: reqPage,
                title: `${doc.title} (Phiên bản v${reqVer})`,
                diagramType: 'text_section',
                paragraphs: [
                  reqVer !== grant.servingVersion
                    ? `Nội dung xem trước chi tiết của phiên bản cũ (v${reqVer}) hiện không khả dụng trong bộ nhớ đệm. Vui lòng xem phiên bản đang phục vụ chính thức (v${grant.servingVersion}).`
                    : 'Nội dung xem trước của tệp tin này đang được đồng bộ hóa trong phiên xem thử.',
                ],
              },
            ],
            isSourceAccessible: true,
            notes: ownNotes.map(sanitizeNoteForStudent),
          };
        }

        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          readerModel: readerData,
        };
      }

      // Stage 2: Student AI Tutor (base-5d1ab390, AI01, AI02, AI03, AI04, AI05, SH_R03)
      if (routeId === 's.tutor') {
        const convList = tutorConversations[`${user.id}:${params.classId}`] ?? [];
        const hasSources = documents.some(d => (documentGrants[d.id] ?? []).some(g => g.classId === params.classId && g.isShared));
        const isExam = isMockAssessmentLocked(user.id, params.classId);
        const lockInfo = getMockAssessmentLockInfo(user.id, params.classId);

        let activeConvId: string | null = convList[0]?.id ?? null;
        if (params.conversationId) {
          const found = convList.find(c => c.id === params.conversationId);
          activeConvId = found ? found.id : null;
        }

        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          tutorWorkspace: {
            classSummary: structuredClone(summary!),
            conversations: structuredClone(convList),
            activeConversationId: activeConvId,
            isOfficialAssessmentActive: isExam,
            assessmentTitle: lockInfo?.title ?? 'Kiểm tra 45 phút: Hàm số bậc hai',
            assessmentHref: `/student/classes/${params.classId}/assessments`,
            classHasSources: hasSources,
            citations: [], // No hardcoded default doc1 citations!
            quickNotes: personalNotes
              .filter(n => n.userId === user.id && n.classId === params.classId)
              .map(sanitizeNoteForStudent),
          },
        };
      }

      // Stage 2: Student Notes & Bookmarks (S07)
      if (routeId === 's.notes') {
        if (!isStudent) {
          return { kind: 'unavailable', message: 'Chỉ học sinh mới có quyền truy cập sổ tay ghi chú và dấu trang.' };
        }
        return {
          kind: 'ready',
          studentNotes: personalNotes.filter(n => n.userId === user.id).map(sanitizeNoteForStudent),
          studentBookmarks: bookmarks.filter(b => b.userId === user.id).map(sanitizeBookmarkForStudent),
        };
      }

      // Stage 3a: Student Practice List (CP01-variant)
      // Stage 3a: Student Practice Hub (CP01-variant)
      if (routeId === 's.practice') {
        if (!isStudent) {
          return { kind: 'unavailable', message: 'Chỉ học sinh mới có quyền xem danh sách luyện tập.' };
        }
        const activeClassIds = getStudentActiveClassIds(user.id);
        if (!activeClassIds.includes(params.classId)) {
          return { kind: 'unavailable', message: 'Bạn không thuộc danh sách học sinh của lớp học này.' };
        }
        const classActs = practiceActivities
          .filter(a => a.classId === params.classId)
          .map(a => {
            const act = structuredClone(a);
            // Derive actor-scoped status and history
            const userAttempt = Object.values(practiceAttempts).find(
              att => att.practiceId === act.id && att.classId === params.classId && att.ownerUserId === user.id && !att.isCompleted
            );
            const userResults = Object.values(practiceResults).filter(
              r => r.practiceId === act.id && r.classId === params.classId && r.ownerUserId === user.id
            );
            if (userAttempt) {
              act.status = 'IN_PROGRESS';
              act.activeAttemptId = userAttempt.attemptId;
              act.currentQuestionIndex = userAttempt.currentQuestionIndex;
              act.activeAttemptVersionNumber = userAttempt.publishedVersionNumber;
              act.activeAttemptQuestionCount = userAttempt.questions.length;
            } else if (userResults.length > 0) {
              act.status = 'COMPLETED';
              const latest = userResults[userResults.length - 1];
              act.latestResultAttemptId = latest.attemptId;
              act.lastScore = latest.score;
              act.lastCompletedAt = latest.completedAt.split(' ')[0];
              act.totalAttempts = userResults.length;
            } else {
              act.status = 'NOT_STARTED';
              act.activeAttemptId = undefined;
              act.latestResultAttemptId = undefined;
              act.lastScore = undefined;
              act.totalAttempts = 0;
            }
            act.history = userResults.map(r => ({
              attemptId: r.attemptId,
              practiceId: r.practiceId,
              practiceTitle: r.title,
              attemptNumber: r.attemptNumber,
              completedAt: r.completedAt,
              score: r.score,
              durationMinutes: r.durationMinutes,
              resultHref: `/student/classes/${params.classId}/practice/${r.practiceId}/attempts/${r.attemptId}/result`,
            }));
            return act;
          });
        const completedCount = classActs.filter(a => a.status === 'COMPLETED').length;
        const allUserHistory = classActs.flatMap(a => a.history ?? []);
        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          practiceList: {
            classId: params.classId,
            className: summary?.name ?? '',
            classSummary: summary ? structuredClone(summary) : undefined,
            activities: classActs,
            completedHistoryCount: allUserHistory.length,
            history: allUserHistory,
          },
        };
      }

      // Stage 3a: Student Practice Attempt (LS01)
      if (routeId === 's.practiceAttempt') {
        if (!isStudent) {
          return { kind: 'unavailable', message: 'Chỉ học sinh mới có quyền làm bài luyện tập.' };
        }
        const activeClassIds = getStudentActiveClassIds(user.id);
        if (!activeClassIds.includes(params.classId)) {
          return { kind: 'unavailable', message: 'Bạn không thuộc danh sách học sinh của lớp học này.' };
        }
        const attempt = practiceAttempts[params.attemptId];
        if (!attempt) {
          return { kind: 'empty', message: 'Không tìm thấy lượt làm bài luyện tập này.' };
        }
        // Strict ownership check (Supervisor check 3)
        if (attempt.ownerUserId !== user.id) {
          return { kind: 'unavailable', message: 'Bạn không có quyền truy cập lượt làm bài của học sinh khác.' };
        }
        // Resource relation check
        if (attempt.classId !== params.classId || attempt.practiceId !== params.practiceId) {
          return { kind: 'unavailable', message: 'Lượt làm bài không thuộc lớp học hoặc bài luyện tập này.' };
        }
        const sanitizedQuestions = attempt.questions.map(q => sanitizeQuestionSource(q, params.classId, user.id));
        const sanitizedFeedbacks: Record<string, PracticeQuestionFeedback> = {};
        if (attempt.checkedFeedbacks) {
          for (const [qid, fb] of Object.entries(attempt.checkedFeedbacks)) {
            sanitizedFeedbacks[qid] = sanitizeQuestionSource(fb, params.classId, user.id);
          }
        }
        const sanitizedAttempt = {
          ...attempt,
          className: summary?.name ?? attempt.className,
          primaryTeacherName: getClassPrimaryTeacherName(params.classId),
          questions: sanitizedQuestions,
          checkedFeedbacks: sanitizedFeedbacks,
        };
        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          practiceAttempt: structuredClone(sanitizedAttempt),
        };
      }

      // Stage 3a: Student Practice Result (base-2ff2012c)
      if (routeId === 's.practiceResult') {
        if (!isStudent) {
          return { kind: 'unavailable', message: 'Chỉ học sinh mới có quyền xem kết quả luyện tập.' };
        }
        const activeClassIds = getStudentActiveClassIds(user.id);
        const endedClassIds = getStudentEndedClassIds(user.id);
        if (!activeClassIds.includes(params.classId) && !endedClassIds.includes(params.classId) && !getStudentArchivedClassIds(user.id).includes(params.classId)) {
          return { kind: 'unavailable', message: 'Bạn không thuộc danh sách học sinh của lớp học này.' };
        }
        const res = practiceResults[params.attemptId];
        if (!res) {
          return { kind: 'empty', message: 'Không tìm thấy kết quả của lượt làm bài luyện tập này.' };
        }
        // Strict ownership check (Supervisor check 4)
        if (res.ownerUserId !== user.id) {
          return { kind: 'unavailable', message: 'Bạn không có quyền truy cập kết quả của học sinh khác.' };
        }
        // Resource relation check
        if (res.classId !== params.classId || res.practiceId !== params.practiceId) {
          return { kind: 'unavailable', message: 'Kết quả không thuộc lớp học hoặc bài luyện tập này.' };
        }
        const sanitizedQuestions = res.questions.map(q => sanitizeQuestionSource(q, params.classId, user.id));
        const sanitizedResult = {
          ...res,
          className: summary?.name ?? res.className,
          questions: sanitizedQuestions,
        };
        return {
          kind: 'ready',
          classSummary: summary ? structuredClone(summary) : undefined,
          practiceResult: structuredClone(sanitizedResult),
        };
      }

      // Stage 3a: Teacher Activities Hub (LT01)
      if (routeId === 't.activities') {
        if (!isTeacher) {
          return { kind: 'unavailable', message: 'Chỉ giáo viên mới có quyền xem trung tâm hoạt động học tập.' };
        }
        const allowedClassIds = getTeacherAssignedClassIds(user.id);
        if (!allowedClassIds.includes(params.classId)) {
          return { kind: 'unavailable', message: 'Bạn không được phân công giảng dạy lớp học này.' };
        }
        const classActs = teacherActivities.filter(a => a.classId === params.classId);
        const teacherSummary = summary ? getTeacherClassSummary(summary, user.id) : undefined;
        const teacherAssignedClasses = classes
          .filter(c => allowedClassIds.includes(c.id))
          .map(c => ({
            id: c.id,
            name: c.name,
            isCurrent: c.id === params.classId,
          }));
        return {
          kind: 'ready',
          classSummary: teacherSummary,
          teacherActivities: {
            classId: params.classId,
            className: summary?.name ?? '',
            classSummary: teacherSummary,
            teacherRoleLabel: teacherSummary?.teachingRole === 'ASSISTING' ? 'Giáo viên phối hợp' : 'Giáo viên chính',
            assignedClasses: teacherAssignedClasses,
            activities: structuredClone(classActs),
          },
        };
      }

      // Stage 3a: Teacher Practice Editor (LT02)
      if (routeId === 't.practiceEditor') {
        if (!isTeacher) {
          return { kind: 'unavailable', message: 'Chỉ giáo viên mới có quyền chỉnh sửa bài luyện tập.' };
        }
        const allowedClassIds = getTeacherAssignedClassIds(user.id);
        if (!allowedClassIds.includes(params.classId)) {
          return { kind: 'unavailable', message: 'Bạn không được phân công giảng dạy lớp học này.' };
        }
        const editor = teacherPracticeEditors[params.practiceId];
        if (!editor) {
          return { kind: 'empty', message: 'Không tìm thấy bài luyện tập để chỉnh sửa.' };
        }
        // Cross-class editor check (Supervisor check 7)
        if (editor.classId !== params.classId) {
          return { kind: 'unavailable', message: 'Bài luyện tập không thuộc lớp học này.' };
        }
        const clonedEditor = structuredClone(editor);
        clonedEditor.className = summary?.name ?? editor.className;
        clonedEditor.availableClassSources = getAvailableClassSources(editor.classId);
        return {
          kind: 'ready',
          classSummary: summary ? getTeacherClassSummary(summary, user.id) : undefined,
          teacherPracticeEditor: clonedEditor,
        };
      }

      // These features own their typed payloads; the shell still receives the
      // same currently authorized class summary used by every tab in the journey.
      if (summary && ['s.progress','s.assessments','s.assessment','s.examAttempt','s.receipt','s.examResult','s.assignments','s.assignment','t.analytics','t.studentAnalytics','t.assessmentEditor','t.assessmentApproval','t.examGrading','t.assignmentEditor','t.gradingQueue','t.assignmentGrading','t.correction','t.correctionApproval'].includes(routeId)) return { kind: 'ready', classSummary: structuredClone(summary) };

      // Preserved legacy workspace routes
      if (['a.classes'].includes(routeId)) return { kind: 'ready', classes: structuredClone(classes) };

      return { kind: 'empty', message: 'Chưa có nội dung cho trang này trong bộ xem thử.' };
    },
  },
};

export function resetStage3aMockStores(): void {
  practiceActivities = structuredClone(initialPracticeActivities);
  practiceAttempts = structuredClone(initialPracticeAttempts);
  practiceResults = structuredClone(initialPracticeResults);
  publishedPracticeVersions = structuredClone(initialPublishedPracticeVersions);
  teacherActivities = structuredClone(initialTeacherActivities);
  teacherPracticeEditors = structuredClone(initialTeacherPracticeEditors);
}


// These wrappers observe acknowledged writes; they do not introduce retries.
adapter.learning = auditedPort(adapter.learning, previewContext, 'practice', ['createPracticeDraft','savePracticeEditorDraft','reviewEditorQuestion','publishPractice']);
adapter.document = auditedPort(adapter.document, previewContext, 'document', ['uploadDocument','uploadVersion','retryProcessing','shareDocument','revokeShare','deleteDocument']);
adapter.social = auditedPort(adapter.social, previewContext, 'social', ['createPost','updatePost','deletePost','createComment','deleteComment']);
adapter.calendar = auditedPort(adapter.calendar, previewContext, 'calendar', ['createEvent','updateEvent','deleteEvent']);
