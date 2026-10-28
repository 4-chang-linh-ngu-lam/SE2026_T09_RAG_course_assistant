import type { PersonalDataPort } from '../personal-data';
import type { IntelligencePort } from '../intelligence';
import type { ClassroomAdminPort } from '../classroom-admin';
import type { ClassSourcePreview } from '../document-preview';
import type { PracticeAuthoringPort } from '../practice-authoring';
import type { AccountsPort } from '../accounts';
import type { AssignmentPort } from '../assignment';
import type { AssessmentPort } from '../assessment';
import type {
  CalendarEvent,
  DataRequest,
  DataRequestType,
  DocumentItem,
  DocumentVersion,
  FeedComment,
  FeedPost,
  IssuedCode,
  Login,
  Page,
  PersonalNoteItem,
  PracticeAnswer,
  PracticeQuestion,
  PracticeQuestionFeedback,
  RouteParams,
  TeacherTutorInstructionConfig,
  TutorConversation,
  TutorMessage,
  TutorMode,
  User,
  WorkspaceData,
} from '../domain';

export interface DataAdapter {
  personalData: PersonalDataPort;
  practiceAuthoring: PracticeAuthoringPort;
  accounts: AccountsPort;
  assignment: AssignmentPort;
  assessment: AssessmentPort;
  readonly source: 'live' | 'mock';
  readonly fixtureSignature?: string;
  identity: {
    restore(): Promise<User | null>;
    login(input: Login): Promise<User>;
    logout(): Promise<void>;
    logoutAll(): Promise<void>;
    updateProfile(displayName: string | null): Promise<User>;
    activate(input: { username: string; activation_code: string; new_password: string }): Promise<void>;
    forgot(email: string): Promise<void>;
    reset(token: string, newPassword: string): Promise<void>;
    acceptInvitation(token: string, newPassword: string): Promise<void>;
    requests(cursor?: string): Promise<Page<DataRequest>>;
    createRequest(type: DataRequestType, reason?: string): Promise<DataRequest>;
    createStudent(username: string, displayName?: string): Promise<IssuedCode>;
    issueCode(userId: string, identityVerified: boolean): Promise<IssuedCode>;
  };
  social: {
    listPosts(classId: string, cursor?: string, signal?: AbortSignal): Promise<Page<FeedPost>>;
    listComments(classId: string, postId: string, cursor?: string, signal?: AbortSignal): Promise<Page<FeedComment>>;
    createPost(classId: string, content: string): Promise<FeedPost>;
    updatePost(classId: string, postId: string, content: string): Promise<FeedPost>;
    deletePost(classId: string, postId: string): Promise<void>;
    createComment(classId: string, postId: string, content: string): Promise<FeedComment>;
    deleteComment(classId: string, postId: string, commentId: string): Promise<void>;
  };
  calendar: {
    createEvent(event: Omit<CalendarEvent, 'id'>): Promise<CalendarEvent>;
    updateEvent(id: string, patch: Partial<CalendarEvent>, classId?: string): Promise<CalendarEvent>;
    deleteEvent(id: string, classId?: string): Promise<void>;
  };
  notifications: {
    markAsRead(id: string): Promise<void>;
    markAllAsRead(): Promise<void>;
  };
  document: {
    previewClassSource(input: {classId: string; documentId: string; version: number}): Promise<ClassSourcePreview>;
    uploadDocument(file: { name: string; size: number; type: string; title: string; description?: string }): Promise<DocumentItem>;
    uploadVersion(documentId: string, file: { name: string; size: number; type: string }): Promise<DocumentVersion>;
    retryProcessing(documentId: string, versionNumber?: number): Promise<DocumentItem>;
    shareDocument(documentId: string, classIds: string[]): Promise<void>;
    revokeShare(documentId: string, classId: string): Promise<void>;
    deleteDocument(documentId: string): Promise<void>;
    saveNote(input: { id?: string; documentId: string; classId: string; locator: string; noteText: string; version?: number; pageNumber?: number; sourceQuote?: string }): Promise<PersonalNoteItem>;
    deleteNote(noteId: string): Promise<void>;
    toggleBookmark(documentId: string, classId: string, locator?: string, version?: number): Promise<{ bookmarked: boolean }>;
  };
  tutor: {
    updateConfig(classId: string, instructions: string): Promise<TeacherTutorInstructionConfig>;
    createConversation(classId: string, title?: string): Promise<TutorConversation>;
    sendMessage(input: {
      classId: string;
      conversationId: string;
      content: string;
      mode: TutorMode;
      onChunk?: (chunk: string) => void;
      signal?: AbortSignal;
      isRetry?: boolean;
      retryUserMessageId?: string;
    }): Promise<TutorMessage>;
    stopStreaming(conversationId: string): Promise<void>;
  };
  learning: {
    startPracticeAttempt(input: {
      classId: string;
      practiceId: string;
      intent?: 'start' | 'resume' | 'retry';
    }): Promise<{ attemptId: string; href: string }>;
    checkPracticeAnswer(input: {
      classId: string;
      practiceId: string;
      attemptId: string;
      questionId: string;
      answer: PracticeAnswer;
    }): Promise<PracticeQuestionFeedback>;
    savePracticeDraft(input: {
      classId: string;
      practiceId: string;
      attemptId: string;
      answers: Record<string, PracticeAnswer>;
    }): Promise<{ savedAt: string }>;
    finishPracticeAttempt(input: {
      classId: string;
      practiceId: string;
      attemptId: string;
    }): Promise<{ resultHref: string; attemptId: string }>;
    createPracticeDraft(input: {
      classId: string;
      title: string;
      topic: string;
    }): Promise<{ practiceId: string; editHref: string }>;
    savePracticeEditorDraft(input: {
      classId: string;
      practiceId: string;
      title?: string;
      topic?: string;
      questions: PracticeQuestion[];
    }): Promise<{ savedAt: string; reviewedCount: number; canPublish: boolean }>;
    publishPractice(input: {
      classId: string;
      practiceId: string;
    }): Promise<{ success: boolean; practiceId: string; publishedVersionId: string }>;
    reviewEditorQuestion(input: {
      classId: string;
      practiceId: string;
      questionId: string;
      approved: boolean;
    }): Promise<{ reviewedCount: number; canPublish: boolean }>;
  };
  // Future domain extension ports:
  classroom: ClassroomAdminPort;
  administration?: unknown;
  intelligence: IntelligencePort;
  workspace: {
    load(routeId: string, params: RouteParams, signal?: AbortSignal): Promise<WorkspaceData>;
  };
}
