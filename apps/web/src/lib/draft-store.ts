import type { PracticeAnswer, PracticeQuestionFeedback } from './domain';

// Volatile memory-only draft store. Never persisted in localStorage/sessionStorage.
// Cleared on logout, actor change, or session invalidation.

export type StructuredDraftKey = {
  actorId: string;
  scope: 'tutor' | 'reader-note' | 'note-edit' | 'tutor-config' | 'practice-attempt' | 'practice-editor';
  classId?: string;
  documentId?: string;
  resourceId?: string;
  version?: number;
  locator?: string;
  conversationId?: string;
};

export type DraftKey = string | StructuredDraftKey;

let activeActor: string | null | undefined;
let sessionEpoch = 0;
const drafts = new Map<string, { content: unknown; updatedAt: number }>();

export function formatDraftKey(key: StructuredDraftKey): string {
  return [
    key.actorId,
    key.scope,
    key.classId ?? '',
    key.documentId ?? key.resourceId ?? '',
    key.version !== undefined ? String(key.version) : '',
    key.locator ?? '',
    key.conversationId ?? '',
  ].join(':');
}

function resolveKey(key: DraftKey): string {
  if (typeof key === 'string') return key;
  return formatDraftKey(key);
}

function draftActor(key: string): string | undefined {
  const parts = key.split(':');
  return ['tutor', 'practice-attempt', 'practice-list', 'teacher-activities'].includes(parts[0]) ? parts[1] : parts[0];
}
function canUseDraft(key: string): boolean { return activeActor === undefined || (activeActor !== null && draftActor(key) === activeActor); }

export const draftStore = {
  get epoch(): number { return sessionEpoch; },
  bindActor(actorId: string | null): void {
    if (activeActor === actorId) return;
    activeActor = actorId; sessionEpoch++; drafts.clear();
  },
  get<T = string>(key: DraftKey): T | null {
    const k = resolveKey(key);
    if (!canUseDraft(k)) return null;
    const item = drafts.get(k);
    if (!item) return null;
    return item.content as T;
  },

  find<T = unknown>(predicate: (key: string, value: unknown) => boolean): T | null {
    for (const [k, item] of Array.from(drafts.entries())) {
      if (canUseDraft(k) && predicate(k, item.content)) {
        return item.content as T;
      }
    }
    return null;
  },

  set<T = string>(key: DraftKey, value: T): void {
    const k = resolveKey(key);
    if (!canUseDraft(k)) return;
    if (typeof value === 'string' && !value.trim()) {
      drafts.delete(k);
    } else {
      drafts.set(k, { content: value, updatedAt: Date.now() });
    }
  },

  remove(key: DraftKey): void {
    const k = resolveKey(key);
    drafts.delete(k);
  },

  clearForActor(actorId: string): void {
    for (const k of Array.from(drafts.keys())) {
      if (draftActor(k) === actorId) {
        drafts.delete(k);
      }
    }
  },

  clearAll(): void {
    drafts.clear();
  },
};

// Backward-compatible string-key helpers:
export function getVolatileDraft(scopeKey: string): string | null {
  return draftStore.get<string>(scopeKey);
}

export function setVolatileDraft(scopeKey: string, content: string): void {
  draftStore.set<string>(scopeKey, content);
}

export function clearVolatileDraft(scopeKey: string): void {
  draftStore.remove(scopeKey);
}

export function clearAllVolatileDrafts(): void {
  draftStore.clearAll();
}

// Typed helpers for Tutor and Learning features
export function formatTutorDraftKey(userId: string, classId: string, convId?: string): string {
  return `tutor:${userId}:${classId}:${convId ?? 'new'}`;
}

export function setTutorDraft(userId: string, classId: string, content: string, convId?: string): void {
  draftStore.set<string>(formatTutorDraftKey(userId, classId, convId), content);
}

export function getTutorDraft(userId: string, classId: string, convId?: string): string | null {
  const val = draftStore.get<unknown>(formatTutorDraftKey(userId, classId, convId));
  if (typeof val === 'string') return val;
  return null;
}

export type ScopedPracticeAttemptDraft = {
  pinnedContext: {
    actorId: string;
    classId: string;
    practiceId: string;
    attemptId: string;
    version: number;
  };
  lastVisitedQuestionIndex: number;
  localAnswers: Record<string, PracticeAnswer>;
  confirmedAnswers: Record<string, PracticeAnswer>;
  sentSnapshot?: Record<string, PracticeAnswer>;
  checkedFeedbacks: Record<string, PracticeQuestionFeedback>;
  checkedAnswerSnapshots: Record<string, PracticeAnswer>;
  ackStatus: 'saved' | 'pending' | 'error' | 'unknown';
  lastSavedAt?: string;
  lastErrorMessage?: string;
  updatedAt: number;
};

export function formatAttemptDraftKey(
  actorId: string,
  classId: string,
  practiceId: string,
  attemptId: string,
  version: number
): string {
  return `practice-attempt:${actorId}:${classId}:${practiceId}:${attemptId}:v${version}`;
}

export function getAttemptDraft(
  actorId: string,
  classId: string,
  practiceId: string,
  attemptId: string,
  version?: number
): ScopedPracticeAttemptDraft | null {
  if (version !== undefined) {
    const key = formatAttemptDraftKey(actorId, classId, practiceId, attemptId, version);
    const draft = draftStore.get<ScopedPracticeAttemptDraft>(key);
    if (
      draft &&
      draft.pinnedContext &&
      draft.pinnedContext.actorId === actorId &&
      draft.pinnedContext.classId === classId &&
      draft.pinnedContext.practiceId === practiceId &&
      draft.pinnedContext.attemptId === attemptId &&
      draft.pinnedContext.version === version
    ) {
      return structuredClone(draft);
    }
    // Explicit version miss MUST return null, never fall back to another version
    return null;
  }

  const prefix = `practice-attempt:${actorId}:${classId}:${practiceId}:${attemptId}:v`;
  const found = draftStore.find<ScopedPracticeAttemptDraft>((key, val) => {
    if (key.startsWith(prefix) && val && typeof val === 'object') {
      const d = val as ScopedPracticeAttemptDraft;
      return (
        d.pinnedContext?.actorId === actorId &&
        d.pinnedContext?.classId === classId &&
        d.pinnedContext?.practiceId === practiceId &&
        d.pinnedContext?.attemptId === attemptId
      );
    }
    return false;
  });
  return found ? structuredClone(found) : null;
}

export function setAttemptDraft(draft: ScopedPracticeAttemptDraft, expectedEpoch = draftStore.epoch): void {
  if (expectedEpoch !== draftStore.epoch) return;
  const key = formatAttemptDraftKey(
    draft.pinnedContext.actorId,
    draft.pinnedContext.classId,
    draft.pinnedContext.practiceId,
    draft.pinnedContext.attemptId,
    draft.pinnedContext.version
  );
  draftStore.set<ScopedPracticeAttemptDraft>(key, structuredClone(draft));
}

export function clearAttemptDraft(
  actorId: string,
  classId: string,
  practiceId: string,
  attemptId: string,
  version?: number
): void {
  if (version !== undefined) {
    draftStore.remove(formatAttemptDraftKey(actorId, classId, practiceId, attemptId, version));
  }
  const prefix = `practice-attempt:${actorId}:${classId}:${practiceId}:${attemptId}:v`;
  for (const k of Array.from(drafts.keys())) {
    if (k.startsWith(prefix)) {
      draftStore.remove(k);
    }
  }
}

export function formatPracticeListDraftKey(actorId: string, classId: string): string {
  return `practice-list:${actorId}:${classId}`;
}
