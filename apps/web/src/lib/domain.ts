export type Role = 'STUDENT' | 'LECTURER' | 'ADMIN';
export type User = { id: string; email: string | null; username: string | null; school_id: string | null; display_name: string | null; roles: Role[]; status: 'ACTIVE' | 'PENDING_VERIFICATION' | 'LOCKED' };
export type Login = { username: string; password: string; email?: never } | { email: string; password: string; username?: never };
export type DataRequestType = 'ACCESS' | 'EXPORT' | 'CORRECTION' | 'DELETE';
export type DataRequest = { id: string; user_id: string; type: DataRequestType; reason: string | null; status: 'PENDING' | 'IN_REVIEW' | 'COMPLETED' | 'REJECTED'; resolution_note: string | null; created_at: string; updated_at: string };
export type Page<T> = { items: T[]; next_cursor: string | null };
export type IssuedCode = { student: Pick<User, 'id' | 'email' | 'username' | 'school_id' | 'status'>; purpose: 'ACTIVATION' | 'PASSWORD_RESET'; code: string; expires_at: string };

// Frontend view models, NOT unapproved service payloads.
export type ClassSummary = {
  id: string;
  code: string;
  name: string;
  status: 'ACTIVE' | 'ARCHIVED';
  metadata: string;
  teachingRole?: 'PRIMARY' | 'ASSISTING';
  isAssignedTeacher?:boolean; // Known assignment, role label absent from Core ClassResponse.
  teacherName?: string;
  studentCount?: number;
  membershipStatus?: 'ACTIVE' | 'ENDED';
};

export type FeedComment = {
  id: string;
  postId: string;
  authorId: string;
  authorName: string;
  authorRole?: 'TEACHER' | 'STUDENT';
  authorClass?: string;
  content: string;
  createdAt: string;
  updatedAt?: string;
  canDelete?: boolean;
};

export type FeedPost = {
  id: string;
  classId: string;
  authorId: string;
  authorName: string;
  authorRole?: 'TEACHER' | 'STUDENT';
  authorAvatar?: string;
  title?: string;
  content: string;
  createdAt: string;
  updatedAt?: string;
  isAnnouncement?: boolean;
  canEdit?: boolean;
  canDelete?: boolean;
  comments: FeedComment[];
};

export type CalendarEvent = {
  id: string;
  classId?: string;
  className?: string;
  title: string;
  description?: string;
  category: 'CLASS' | 'ASSIGNMENT' | 'EXAM' | 'OTHER';
  start: string; // e.g. "2026-10-16T07:00:00" or time string
  end?: string;
  date: string; // YYYY-MM-DD
  timeRange?: string; // e.g. "07:00 – 09:15"
  readOnly?: boolean; // Learning deadlines are projected read-only
  teacherName?: string;
  location?: string;
  href?: string;
};

export type NotificationItem = {
  id: string;
  userId: string;
  title: string;
  content: string;
  category: 'MATERIAL' | 'ASSIGNMENT' | 'EXAM' | 'CLASS' | 'SYSTEM';
  categoryLabel?: string;
  createdAt: string;
  isRead: boolean;
  classId?: string;
  className?: string;
  targetHref?: string;
  targetLabel?: string;
  targetKind?: 'post' | 'class' | 'calendar' | 'document';
  documentId?: string;
  postId?: string;
  commentId?: string;
};

export type TutorSuggestionItem = {
  classId: string;
  prompt: string;
};

export type StudentHomeOverview = {
  activeClasses: ClassSummary[];
  upcomingTasks: {
    id: string;
    type: 'ASSIGNMENT' | 'EXAM' | 'MATERIAL';
    title: string;
    className: string;
    dueDetail: string;
    daysLeftLabel: string;
    badgeStyle?: string;
    href: string;
    actionLabel: string;
  }[];
  recentStudies: {
    id: string;
    type: 'MATERIAL' | 'PRACTICE';
    title: string;
    className: string;
    progressText: string;
    progressPercent: number;
    href: string;
    actionLabel: string;
    extraNote?: string;
  }[];
  tutorSuggestions: TutorSuggestionItem[];
};

export type TeacherHomeOverview = {
  termLabel?: string;
  assignedClasses: ClassSummary[];
  recentDiscussions: {
    id: string;
    studentName: string;
    className: string;
    classId: string;
    createdAt: string;
    content: string;
  }[];
  todaySchedule: CalendarEvent[];
  stats?: {
    totalClasses: number;
    totalStudents: number;
    pendingGrading: number;
  };
};

export type ClassOverviewData = {
  summary: ClassSummary;
  announcement?: {
    id: string;
    authorName: string;
    authorRole: string;
    authorInitials: string;
    timeAgo: string;
    title: string;
    content: string;
    deadlineNotice?: string;
  };
  recentMaterials: {
    id: string;
    title: string;
    format: DocumentFormat;
    detail: string;
    href: string;
    sourceMeta?: string;
  }[];
  upcomingActivities: {
    id: string;
    type: 'ASSIGNMENT' | 'PRACTICE' | 'EXAM';
    title: string;
    dueDetail: string;
    badgeLabel: string;
    badgeStyle: string;
    href: string;
    actionLabel: string;
    isOfficial?: boolean;
    duration?: string;
  }[];
};

export type HistoryClassData = {
  summary: ClassSummary;
  historyNotice: string;
  conversations: {
    id: string;
    title: string;
    date: string;
    preview: string;
    messages: {
      role: 'user' | 'assistant';
      content: string;
      timestamp: string;
    }[];
  }[];
  notes?: {
    id: string;
    title: string;
    date: string;
    content: string;
  }[];
};

// Stage 2: Document, Library, Reader, Notes and AI Tutor View Models
export type DocumentFormat = 'PDF' | 'PPTX' | 'DOCX' | 'TXT' | 'MD';
export type ProcessingStatus = 'READY' | 'PROCESSING' | 'PENDING' | 'FAILED';

export type DocumentCapabilityPolicy = {
  maxSizeBytes: number; // e.g. 52428800 (50MB)
  allowedExtensions: string[];
  allowedMimeTypes: string[];
};

export type DocumentItem = {
  id: string;
  title: string;
  description?: string;
  format: DocumentFormat;
  currentVersion: number;
  servingVersion?: number;
  revision?: number;
  grantRevision?: number;
  processingStatus: ProcessingStatus;
  processingError?: string;
  ownerId: string;
  ownerName: string;
  createdAt: string;
  updatedAt: string;
  locatorCountLabel?: string; // e.g. "12 trang", "18 slide", "4 mục", "5 mục"
  pageCount?: number;
  slideCount?: number;
  sectionCount?: number;
  sharedClassCount?: number;
  sharedClasses?: { classId: string; className: string; grantedAt: string }[];
  isBookmarked?: boolean;
  canManageSource?: boolean; // true if logged-in teacher is owner
  canRevokeGrant?: boolean; // true if teacher has grant permission in class (Rule O1)
};

export type DocumentVersion = {
  versionNumber: number;
  filename: string;
  fileSizeFormatted: string;
  uploadedAt: string;
  status: ProcessingStatus;
  errorMessage?: string;
  isServing?: boolean;
  generation?: number;
};

export type ClassDocumentGrant = {
  classId: string;
  className: string;
  classCode: string;
  isShared: boolean;
  grantedAt?: string;
  servingVersion: number;
  classStatus?: ClassSummary['status'];
  revision?: number;
};

export type PersonalNoteItem = {
  id: string;
  userId?: string;
  documentId: string;
  documentTitle: string;
  documentFormat: DocumentFormat;
  version?: number;
  classId: string;
  className: string;
  classStatus?: 'ACTIVE' | 'ARCHIVED';
  revision?: number;
  locatorId?: string;
  sourceAccess?: 'ALLOWED' | 'REVOKED' | 'UNAVAILABLE';
  clientRequestId?: string;
  locator: string; // e.g. "Trang 3", "Slide 5", "Mục 2"
  pageNumber?: number;
  sourceQuote?: string;
  isSourceAccessible: boolean;
  noteText: string;
  updatedAt: string;
  isArchivedClassEditable?: boolean; // Rule O2
};

export type BookmarkItem = {
  id: string;
  userId?: string;
  documentId: string;
  documentTitle: string;
  documentFormat: DocumentFormat;
  version?: number;
  classId: string;
  className: string;
  locator: string;
  pageNumber?: number;
  createdAt: string;
  isSourceAccessible: boolean;
  locatorId?: string;
  sourceAccess?: 'ALLOWED' | 'REVOKED' | 'UNAVAILABLE';
};

export type DocumentDiagram =
  | { kind: 'parabola'; title: string; direction: 'UP' | 'DOWN'; vertexLabel: string; axisLabel: string }
  | { kind: 'variation'; title: string; xLabels: [string, string, string]; extremumLabel: string; directions: ['UP' | 'DOWN', 'UP' | 'DOWN'] };

export type DocumentReaderModel = {
  document: DocumentItem;
  servingVersion: number;
  viewingVersion?: number;
  locatorLabel?: 'Trang' | 'Slide' | 'Mục';
  bookmarks?: {version:number;locatorId:string}[];
  isSourceAccessible: boolean;
  revokedReason?: string;
  outline: { id: string; label: string; pageNumber: number }[];
  currentPage: number;
  totalPages: number;
  pageContents?: {
    pageNumber: number;
    title: string;
    diagramType?: 'parabola' | 'variation_table' | 'formula_list' | 'text_section';
    diagrams?: DocumentDiagram[];
    paragraphs: string[];
    formulas?: string[];
  }[];
  notes: PersonalNoteItem[];
};

export type TutorMode = 'QUICK_QA' | 'STEP_BY_STEP';

export type CitationItem = {
  id: string;
  documentId: string;
  documentTitle: string;
  version?: number;
  locator: string;
  pageNumber?: number;
  excerpt: string;
  readerHref: string;
  isAccessible: boolean;
};

export type TutorMessage = {
  id: string;
  conversationId: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  stepNumber?: number;
  totalSteps?: number;
  pedagogicalHint?: string;
  knowledgeType?: 'CLASS_SOURCE' | 'GENERAL_KNOWLEDGE';
  citations?: CitationItem[];
  isStreaming?: boolean;
  isFailed?: boolean;
  isIncomplete?: boolean;
};

export type TutorConversation = {
  id: string;
  userId?: string;
  classId: string;
  title: string;
  updatedAt: string;
  preview: string;
  messages: TutorMessage[];
};

export type StudentTutorWorkspaceData = {
  classSummary: ClassSummary;
  conversations: TutorConversation[];
  activeConversationId: string | null;
  isOfficialAssessmentActive: boolean; // Rule D6
  assessmentTitle?: string;
  assessmentHref?: string;
  classHasSources: boolean; // AI01 state
  citations: CitationItem[];
  quickNotes: PersonalNoteItem[];
};

export type TeacherTutorInstructionConfig = {
  classId: string;
  instructions: string;
  updatedAt: string;
  maxChars: number;
  disclaimer: string;
};

// Stage 3 Learning Domain Types
export type LearningSourceReference = {
  documentId: string;
  documentTitle: string;
  versionNumber: number;
  locator: string;
  displayText: string;
  isAccessible?: boolean;
  pageNumber?: number;
};

export type QuestionType = 'single_choice' | 'multiple_choice' | 'true_false' | 'short_answer';

export type SingleChoiceOption = { id: string; label: string; text: string };
export type SingleChoiceQuestion = {
  id: string;
  type: 'single_choice';
  prompt: string;
  options: SingleChoiceOption[];
  correctOptionId?: string; // stripped from student attempt snapshot
  explanation?: string;
  sourceReference?: string;
  sourceRef?: LearningSourceReference;
  points?: number;
  topic?: string;
  isReviewed?: boolean;
};

export type MultipleChoiceOption = { id: string; label: string; text: string };
export type MultipleChoiceQuestion = {
  id: string;
  type: 'multiple_choice';
  prompt: string;
  options: MultipleChoiceOption[];
  correctOptionIds?: string[]; // stripped from student attempt snapshot
  explanation?: string;
  sourceReference?: string;
  sourceRef?: LearningSourceReference;
  points?: number;
  topic?: string;
  isReviewed?: boolean;
};

export type TrueFalseStatement = { id: string; label: string; text: string; isCorrect?: boolean };
export type TrueFalseQuestion = {
  id: string;
  type: 'true_false';
  prompt: string;
  statements: TrueFalseStatement[];
  explanation?: string;
  sourceReference?: string;
  sourceRef?: LearningSourceReference;
  points?: number;
  topic?: string;
  isReviewed?: boolean;
};

export type ShortAnswerQuestion = {
  id: string;
  type: 'short_answer';
  prompt: string;
  expectedAnswer?: string; // stripped from student attempt snapshot
  manualGradingRequired?: boolean;
  explanation?: string;
  sourceReference?: string;
  sourceRef?: LearningSourceReference;
  points?: number;
  topic?: string;
  isReviewed?: boolean;
  isAiProposed?: boolean;
};

export type PracticeQuestion =
  | SingleChoiceQuestion
  | MultipleChoiceQuestion
  | TrueFalseQuestion
  | ShortAnswerQuestion;

export type PracticeAnswer = {
  questionId: string;
  singleChoiceValue?: string;
  multipleChoiceValues?: string[];
  trueFalseValues?: Record<string, boolean>;
  shortAnswerValue?: string;
};

export type PracticeQuestionFeedback = {
  questionId: string;
  isCorrect: boolean;
  feedbackTitle: string;
  explanation: string;
  sourceReference?: string;
  sourceRef?: LearningSourceReference;
  pedagogicalHint?: string;
};

export type PracticeHistoryItem = {
  attemptId: string;
  practiceId: string;
  practiceTitle: string;
  attemptNumber: number;
  completedAt: string;
  score: { correct: number; total: number; percentage: number };
  durationMinutes: number;
  resultHref: string;
};

export type PracticeActivity = {
  id: string;
  classId: string;
  title: string;
  topic: string;
  questionCount: number;
  status: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED';
  publishedVersionId: string;
  publishedVersionNumber: number;
  lastCompletedAt?: string;
  lastScore?: { correct: number; total: number; percentage: number };
  activeAttemptId?: string;
  latestResultAttemptId?: string;
  currentQuestionIndex?: number;
  totalAttempts?: number;
  history?: PracticeHistoryItem[];
  activeAttemptVersionNumber?: number;
  activeAttemptQuestionCount?: number;
};

export type PracticeAttemptDetail = {
  attemptId: string;
  practiceId: string;
  classId: string;
  ownerUserId: string;
  publishedVersionId: string;
  publishedVersionNumber: number;
  className: string;
  title: string;
  topic: string;
  teachingRole?: 'PRIMARY' | 'ASSISTING';
  primaryTeacherName: string;
  questions: PracticeQuestion[];
  savedAnswers: Record<string, PracticeAnswer>;
  checkedFeedbacks: Record<string, PracticeQuestionFeedback>;
  lastSavedAt: string;
  startedAt: string;
  currentQuestionIndex: number;
  isCompleted: boolean;
  completedAt?: string;
};

export type PracticeResultQuestionItem = {
  id: string;
  questionNumber: number;
  prompt: string;
  type: QuestionType;
  studentAnswerText: string;
  correctAnswerText: string;
  isCorrect: boolean;
  explanation: string;
  sourceReference?: string;
  sourceRef?: LearningSourceReference;
};

export type PracticeResultDetail = {
  attemptId: string;
  practiceId: string;
  classId: string;
  ownerUserId: string;
  publishedVersionId: string;
  publishedVersionNumber: number;
  className?: string;
  title: string;
  attemptNumber: number;
  completedAt: string;
  startedAt?: string;
  durationMinutes: number;
  score: { correct: number; total: number; percentage: number };
  correctCount: number;
  incorrectCount: number;
  unansweredCount: number;
  studyTip?: string;
  questions: PracticeResultQuestionItem[];
};

export type PublishedPracticeVersion = {
  id: string;
  practiceId: string;
  classId: string;
  versionNumber: number;
  title: string;
  topic: string;
  questions: PracticeQuestion[];
  publishedAt: string;
  publishedByUserId: string;
};

export type TeacherActivityItem = {
  id: string;
  classId: string;
  resourceId: string;
  title: string;
  type: 'PRACTICE' | 'ASSESSMENT' | 'ASSIGNMENT';
  topic: string;
  status: 'PUBLISHED' | 'PENDING_APPROVAL' | 'DRAFT';
  dueOrTimeLabel: string;
  pendingGradingCount?: number;
  editHref?: string;
  submissionsHref?: string;
  notes?: string;
};

export type StudentPracticeListModel = {
  classId: string;
  className?: string;
  classSummary?: ClassSummary;
  activities: PracticeActivity[];
  completedHistoryCount?: number;
  history?: PracticeHistoryItem[];
};

export type TeacherActivityListModel = {
  classId?: string;
  className?: string;
  classSummary?: ClassSummary;
  activities: TeacherActivityItem[];
  teacherRoleLabel?: string;
  assignedClasses?: { id: string; name: string; isCurrent: boolean }[];
};

export type TeacherPracticeEditorModel = {
  practiceId: string;
  classId: string;
  className: string;
  title: string;
  topic: string;
  versionLabel: string;
  currentVersionNumber: number;
  isDraft: boolean;
  questions: PracticeQuestion[];
  reviewedCount: number;
  totalQuestions: number;
  canPublish: boolean;
  availableClassSources: { id: string; title: string; version: number; isReady: boolean }[];
};

export type WorkspaceData =
  | {
      kind: 'ready';
      coreClassroom?:true; // Core metadata only; other-service summaries are not loaded.
      classes?: ClassSummary[];
      classSummary?: ClassSummary;
      rows?: { id: string; title: string; detail: string; href?: string; status?: string }[];
      // Rich typed view models:
      studentHome?: StudentHomeOverview;
      teacherHome?: TeacherHomeOverview;
      classOverview?: ClassOverviewData;
      teacherMetrics?: { pendingGrading: number; openActivities: number };
      feedPosts?: FeedPost[];
      calendarEvents?: CalendarEvent[];
      notifications?: NotificationItem[];
      notificationUnreadCount?: number; // Core's global inbox count, independent of loaded rows.
      historyData?: HistoryClassData;
      displayDate?: string;
      // Stage 2 specific view models:
      libraryDocuments?: DocumentItem[];
      sourceDocumentDetail?: {
        document: DocumentItem;
        versions: DocumentVersion[];
        grants: ClassDocumentGrant[];
      shareableClasses?: ClassSummary[]; // Current assigned ACTIVE classes, independent of existing grants.
      };
      capabilityPolicy?: DocumentCapabilityPolicy;
      classDocuments?: DocumentItem[];
      readerModel?: DocumentReaderModel;
      studentNotes?: PersonalNoteItem[];
      studentBookmarks?: BookmarkItem[];
      tutorWorkspace?: StudentTutorWorkspaceData;
      teacherTutorConfig?: TeacherTutorInstructionConfig;
      // Stage 3 Learning view models:
      practiceList?: StudentPracticeListModel;
      practiceAttempt?: PracticeAttemptDetail;
      practiceResult?: PracticeResultDetail;
      teacherActivities?: TeacherActivityListModel;
      teacherPracticeEditor?: TeacherPracticeEditorModel;
    }
  | { kind: 'unavailable'; message: string }
  | { kind: 'empty'; message: string };

export type RouteParams = Record<string, string>;
