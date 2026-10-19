import type { PracticeAnswer, PracticeAttemptDetail, PracticeQuestionFeedback } from '@/lib/domain';
import type { ScopedPracticeAttemptDraft } from '@/lib/draft-store';

export function areAnswersEqual(a?: PracticeAnswer, b?: PracticeAnswer): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.questionId !== b.questionId) return false;

  // Single choice
  const aSc = a.singleChoiceValue ?? undefined;
  const bSc = b.singleChoiceValue ?? undefined;
  if (aSc !== bSc) return false;

  // Short answer
  const aSa = (a.shortAnswerValue ?? '').trim();
  const bSa = (b.shortAnswerValue ?? '').trim();
  if (aSa !== bSa) return false;

  // Multiple choice
  const aMulti = a.multipleChoiceValues ?? [];
  const bMulti = b.multipleChoiceValues ?? [];
  if (aMulti.length !== bMulti.length) return false;
  const aSorted = [...aMulti].sort();
  const bSorted = [...bMulti].sort();
  for (let i = 0; i < aSorted.length; i++) {
    if (aSorted[i] !== bSorted[i]) return false;
  }

  // True / False
  const aTf = a.trueFalseValues ?? {};
  const bTf = b.trueFalseValues ?? {};
  const aKeys = Object.keys(aTf);
  const bKeys = Object.keys(bTf);
  if (aKeys.length !== bKeys.length) return false;
  for (const k of aKeys) {
    if (aTf[k] !== bTf[k]) return false;
  }

  return true;
}

export function areAnswerMapsEqual(
  a?: Record<string, PracticeAnswer> | null,
  b?: Record<string, PracticeAnswer> | null
): boolean {
  if (a === b) return true;
  if (!a || !b) {
    const aEmpty = !a || Object.keys(a).length === 0;
    const bEmpty = !b || Object.keys(b).length === 0;
    return aEmpty && bEmpty;
  }
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const k of aKeys) {
    if (!areAnswersEqual(a[k], b[k])) return false;
  }
  return true;
}

export type ReconcileDraftInput = {
  actorId: string;
  classId: string;
  practiceId: string;
  attempt: PracticeAttemptDetail;
  draft: ScopedPracticeAttemptDraft | null;
};

export type ReconcileDraftResult = {
  answers: Record<string, PracticeAnswer>;
  lastAckedAnswers: Record<string, PracticeAnswer>;
  lastAckedAt: string;
  ackStatus: 'saved' | 'pending' | 'error' | 'unknown';
  isBlocked: boolean;
  blockedReason?: string;
  sentSnapshot?: Record<string, PracticeAnswer>;
  feedbacks: Record<string, PracticeQuestionFeedback>;
  checkedSnapshots: Record<string, PracticeAnswer>;
  lastVisitedQuestionIndex: number;
  hasUnsavedEdits: boolean;
};

export function reconcileAttemptDraft(input: ReconcileDraftInput): ReconcileDraftResult {
  const { actorId, classId, practiceId, attempt, draft } = input;
  const serverAnswers = structuredClone(attempt.savedAnswers ?? {});
  const serverLastSavedAt = attempt.lastSavedAt ?? '';

  // Validate pinned context strictly
  const isDraftMatching = Boolean(
    draft &&
    draft.pinnedContext &&
    draft.pinnedContext.actorId === actorId &&
    draft.pinnedContext.classId === classId &&
    draft.pinnedContext.practiceId === practiceId &&
    draft.pinnedContext.attemptId === attempt.attemptId &&
    draft.pinnedContext.version === attempt.publishedVersionNumber
  );

  // Fallback / Initial if no matching draft exists
  if (!isDraftMatching || !draft) {
    const initialFeedbacks: Record<string, PracticeQuestionFeedback> = {};
    if (attempt.checkedFeedbacks) {
      for (const [qid, fb] of Object.entries(attempt.checkedFeedbacks)) {
        if (serverAnswers[qid]) {
          initialFeedbacks[qid] = fb;
        }
      }
    }

    return {
      answers: serverAnswers,
      lastAckedAnswers: serverAnswers,
      lastAckedAt: serverLastSavedAt,
      ackStatus: 'saved',
      isBlocked: false,
      feedbacks: initialFeedbacks,
      checkedSnapshots: structuredClone(serverAnswers),
      lastVisitedQuestionIndex: Math.max(
        0,
        Math.min(attempt.currentQuestionIndex ?? 0, Math.max(0, (attempt.questions?.length ?? 1) - 1))
      ),
      hasUnsavedEdits: false,
    };
  }

  // Sanitize local draft answers against valid questions
  const validQuestionsMap = new Map((attempt.questions ?? []).map(q => [q.id, q]));
  const sanitizedLocalAnswers: Record<string, PracticeAnswer> = {};
  for (const [qid, ans] of Object.entries(draft.localAnswers ?? {})) {
    const q = validQuestionsMap.get(qid);
    if (q && ans.questionId === qid) {
      sanitizedLocalAnswers[qid] = structuredClone(ans);
    }
  }

  const localAnswers = { ...serverAnswers, ...sanitizedLocalAnswers };
  const confirmedAnswers = draft.confirmedAnswers ? structuredClone(draft.confirmedAnswers) : serverAnswers;
  const sentSnapshot = draft.sentSnapshot ? structuredClone(draft.sentSnapshot) : undefined;

  let ackStatus: 'saved' | 'pending' | 'error' | 'unknown' = draft.ackStatus ?? 'saved';
  let isBlocked = false;
  let blockedReason: string | undefined = undefined;
  let lastAckedAnswers = confirmedAnswers;
  let lastAckedAt = draft.lastSavedAt || serverLastSavedAt;

  // Check whether authoritative read has incorporated local edits or sent snapshot
  if (areAnswerMapsEqual(serverAnswers, localAnswers)) {
    // Everything local is already confirmed by server read
    ackStatus = 'saved';
    isBlocked = false;
    lastAckedAnswers = serverAnswers;
    lastAckedAt = serverLastSavedAt || lastAckedAt;
  } else if (draft.ackStatus === 'error') {
    // Known rejected write (validation or server error)
    // Keep known rejected/error as distinct blocked-but-explicitly-retryable state when latest local differs from authority, even if sentSnapshot exists.
    ackStatus = 'error';
    isBlocked = true;
    blockedReason =
      draft.lastErrorMessage || 'Lưu bài trước đó thất bại. Vui lòng kiểm tra lại câu trả lời và thử lưu lại.';
    lastAckedAnswers = serverAnswers;
  } else if (sentSnapshot) {
    // A save payload was sent to the server (either unknown or pending in-flight when left/disposed)
    if (areAnswerMapsEqual(serverAnswers, sentSnapshot)) {
      // The sent write has been confirmed by the authoritative read!
      lastAckedAnswers = serverAnswers;
      lastAckedAt = serverLastSavedAt;
      if (areAnswerMapsEqual(serverAnswers, localAnswers)) {
        ackStatus = 'saved';
        isBlocked = false;
      } else {
        // Newer local edits exist beyond the confirmed sent snapshot
        ackStatus = 'pending';
        isBlocked = false;
      }
    } else {
      // The server does NOT reflect the sent snapshot; uncertain sent write!
      // Must stay BLOCKED and never automatically retry mutation.
      ackStatus = 'unknown';
      isBlocked = true;
      blockedReason =
        'Chưa xác định được kết quả lưu trước đó lên máy chủ. Câu trả lời của bạn được giữ an toàn trong phiên làm việc hiện tại.';
      lastAckedAnswers = serverAnswers;
    }
  } else if (draft.ackStatus === 'unknown') {
    // Unknown outcome without a sent snapshot cannot authorize retry
    ackStatus = 'unknown';
    isBlocked = true;
    blockedReason =
      'Chưa xác định được kết quả lưu trước đó lên máy chủ. Câu trả lời của bạn được giữ an toàn trong phiên làm việc hiện tại.';
    lastAckedAnswers = serverAnswers;
  } else {
    // Fresh known-unsent local edits (no sentSnapshot was ever dispatched)
    ackStatus = 'pending';
    isBlocked = false;
    lastAckedAnswers = serverAnswers;
  }

  // Restore feedbacks only when answer equals the checked snapshot
  const restoredFeedbacks: Record<string, PracticeQuestionFeedback> = {};
  const checkedSnapshots: Record<string, PracticeAnswer> = {
    ...(draft.checkedAnswerSnapshots ?? {}),
  };

  // Seed checked snapshots from server attempt if available
  if (attempt.checkedFeedbacks) {
    for (const [qid, fb] of Object.entries(attempt.checkedFeedbacks)) {
      const curAns = localAnswers[qid];
      const srvAns = serverAnswers[qid];
      if (curAns && srvAns && areAnswersEqual(curAns, srvAns)) {
        restoredFeedbacks[qid] = fb;
        checkedSnapshots[qid] = srvAns;
      }
    }
  }

  // Restore draft feedbacks that match checkedAnswerSnapshots
  if (draft.checkedFeedbacks && draft.checkedAnswerSnapshots) {
    for (const [qid, fb] of Object.entries(draft.checkedFeedbacks)) {
      const snap = draft.checkedAnswerSnapshots[qid];
      const curAns = localAnswers[qid];
      if (curAns && snap && areAnswersEqual(curAns, snap)) {
        restoredFeedbacks[qid] = fb;
      }
    }
  }

  const maxIdx = Math.max(0, (attempt.questions?.length ?? 1) - 1);
  const targetIndex =
    typeof draft.lastVisitedQuestionIndex === 'number'
      ? draft.lastVisitedQuestionIndex
      : attempt.currentQuestionIndex ?? 0;
  const lastVisitedQuestionIndex = Math.max(0, Math.min(targetIndex, maxIdx));

  const hasUnsavedEdits = !areAnswerMapsEqual(lastAckedAnswers, localAnswers);

  return {
    answers: localAnswers,
    lastAckedAnswers,
    lastAckedAt,
    ackStatus,
    isBlocked,
    blockedReason,
    sentSnapshot,
    feedbacks: restoredFeedbacks,
    checkedSnapshots,
    lastVisitedQuestionIndex,
    hasUnsavedEdits,
  };
}
