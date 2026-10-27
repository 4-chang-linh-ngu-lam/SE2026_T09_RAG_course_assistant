'use client';
import { useState, useTransition, useRef, useEffect } from 'react';
import Link from 'next/link';
import {useGuardedRouter as useRouter} from '@/components/unsaved-changes';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData, PracticeAnswer, PracticeQuestionFeedback, PracticeAttemptDetail } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { draftStore, getAttemptDraft, setAttemptDraft, clearAttemptDraft } from '@/lib/draft-store';
import { StatePanel, Dialog, useUnsavedChanges } from '@/components/ui';
import { QuestionRenderer } from '../components/question-renderer';
import { SaveController, isAnswerComplete } from '../lib/save-controller';
import { areAnswersEqual, areAnswerMapsEqual, reconcileAttemptDraft } from '../lib/draft-reconciliation';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params: RouteParams;
  user: User;
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: 'Trắc nghiệm',
  multiple_choice: 'Nhiều ĐA',
  true_false: 'Đúng / Sai',
  short_answer: 'Trả lời ngắn',
};

export function StudentPracticeAttemptView({ data, reload, params, user }: Props) {
  const router = useRouter();
  const draftEpoch = useRef(draftStore.epoch).current;
  const [isPending, startTransition] = useTransition();

  const attempt = data?.kind === 'ready' ? data.practiceAttempt : undefined;

  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, PracticeAnswer>>({});
  const [feedbacks, setFeedbacks] = useState<Record<string, PracticeQuestionFeedback>>({});
  const [saveStatus, setSaveStatus] = useState<string>('Tự động lưu');
  const [showHint, setShowHint] = useState<boolean>(false);
  const [showLeaveModal, setShowLeaveModal] = useState<boolean>(false);
  const [showFinishModal, setShowFinishModal] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isCheckingSaveStatus, setIsCheckingSaveStatus] = useState<boolean>(false);
  const [isCheckingAnswer, setIsCheckingAnswer] = useState<boolean>(false);

  const saveControllerRef = useRef<SaveController | null>(null);
  const isMountedRef = useRef<boolean>(true);
  const answersRef = useRef<Record<string, PracticeAnswer>>({});
  const feedbacksRef = useRef<Record<string, PracticeQuestionFeedback>>({});
  const checkedSnapshotsRef = useRef<Record<string, PracticeAnswer>>({});
  const currentIndexRef = useRef<number>(0);
  const attemptRef = useRef<PracticeAttemptDetail | null>(null);
  const lastAckedAnswersRef = useRef<Record<string, PracticeAnswer>>({});
  const lastAckedAtRef = useRef<string>('');
  const sentSnapshotRef = useRef<Record<string, PracticeAnswer> | undefined>(undefined);
  const ackStatusRef = useRef<'saved' | 'pending' | 'error' | 'unknown'>('saved');
  const loadedAttemptScopeRef = useRef<string | null>(null);

  // Scope identity: tracks validated resource scope across harmless question query updates and reloads
  const scopeRef = useRef<{
    actorId: string;
    classId: string;
    practiceId: string;
    attemptId: string;
    version: number;
  } | null>(null);

  const finishGenerationRef = useRef(0);
  const checkAnswerGenerationRef = useRef(0);
  const checkStatusGenerationRef = useRef(0);

  const classId = params?.classId ?? attempt?.classId ?? '';
  const practiceId = params?.practiceId ?? attempt?.practiceId ?? '';
  const attemptId = params?.attemptId ?? attempt?.attemptId ?? '';

  const questions = attempt?.questions ?? [];
  const totalQuestions = questions.length;
  const currentQuestion = questions[currentIndex];
  useUnsavedChanges(Boolean(attempt) && (!areAnswerMapsEqual(answers, lastAckedAnswersRef.current) || ackStatusRef.current !== 'saved'), {queryKeys:['question']});

  const persistScopedDraft = (
    questionIdx: number,
    localAns: Record<string, PracticeAnswer>,
    currentFeedbacks: Record<string, PracticeQuestionFeedback>,
    newCheckedSnapshots?: Record<string, PracticeAnswer>,
    statusOverride?: 'saved' | 'pending' | 'error' | 'unknown',
    sentSnapshotOverride?: Record<string, PracticeAnswer>
  ) => {
    const curAttempt = attemptRef.current ?? attempt;
    if (!curAttempt) return;
    const existingDraft = getAttemptDraft(
      user.id,
      classId,
      practiceId,
      curAttempt.attemptId,
      curAttempt.publishedVersionNumber
    );

    const mergedSnapshots = {
      ...(existingDraft?.checkedAnswerSnapshots ?? {}),
      ...(checkedSnapshotsRef.current ?? {}),
      ...(newCheckedSnapshots ?? {}),
    };

    const isPendingEdits = !areAnswerMapsEqual(lastAckedAnswersRef.current, localAns);

    let ackStatus: 'saved' | 'pending' | 'error' | 'unknown';
    if (statusOverride) {
      ackStatus = statusOverride;
    } else if (saveControllerRef.current?.isBlocked()) {
      ackStatus = ackStatusRef.current === 'unknown' ? 'unknown' : 'error';
    } else if (isPendingEdits) {
      ackStatus = 'pending';
    } else {
      ackStatus = 'saved';
    }
    ackStatusRef.current = ackStatus;

    const currentSent = sentSnapshotOverride ?? sentSnapshotRef.current;

    setAttemptDraft({
      pinnedContext: {
        actorId: user.id,
        classId,
        practiceId,
        attemptId: curAttempt.attemptId,
        version: curAttempt.publishedVersionNumber,
      },
      lastVisitedQuestionIndex: questionIdx,
      localAnswers: structuredClone(localAns),
      confirmedAnswers: structuredClone(lastAckedAnswersRef.current),
      sentSnapshot: currentSent ? structuredClone(currentSent) : undefined,
      checkedFeedbacks: structuredClone(currentFeedbacks),
      checkedAnswerSnapshots: structuredClone(mergedSnapshots),
      ackStatus,
      lastSavedAt: lastAckedAtRef.current,
      lastErrorMessage: actionError ?? undefined,
      updatedAt: Date.now(),
    }, draftEpoch);
  };

  // True unmount cleanup: mark in-flight writes uncertain before disposal
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (saveControllerRef.current) {
        if (saveControllerRef.current.isSaving() && scopeRef.current) {
          // Mark volatile record uncertain with sentSnapshot + latest local + prior ACK before disposal
          const curScope = scopeRef.current;
          setAttemptDraft({
            pinnedContext: {
              actorId: curScope.actorId,
              classId: curScope.classId,
              practiceId: curScope.practiceId,
              attemptId: curScope.attemptId,
              version: curScope.version,
            },
            lastVisitedQuestionIndex: currentIndexRef.current,
            localAnswers: structuredClone(answersRef.current),
            confirmedAnswers: structuredClone(lastAckedAnswersRef.current),
            sentSnapshot: sentSnapshotRef.current ? structuredClone(sentSnapshotRef.current) : undefined,
            checkedFeedbacks: structuredClone(feedbacksRef.current),
            checkedAnswerSnapshots: structuredClone(checkedSnapshotsRef.current),
            ackStatus: 'unknown',
            lastSavedAt: lastAckedAtRef.current,
            updatedAt: Date.now(),
          }, draftEpoch);
        }
        saveControllerRef.current.dispose();
        saveControllerRef.current = null;
      }
    };
  }, []);

  // Dispose controller only when true actor or resource identity changes
  useEffect(() => {
    if (
      scopeRef.current &&
      (scopeRef.current.actorId !== user.id ||
        scopeRef.current.classId !== classId ||
        scopeRef.current.practiceId !== practiceId ||
        scopeRef.current.attemptId !== attemptId)
    ) {
      if (saveControllerRef.current) {
        saveControllerRef.current.dispose();
        saveControllerRef.current = null;
      }
      scopeRef.current = null;
      loadedAttemptScopeRef.current = null;
      sentSnapshotRef.current = undefined;
    }
  }, [user.id, classId, practiceId, attemptId]);

  // Initialize SaveController once validated full pinned scope arrives;
  // survive harmless query/reload null data without recreation
  useEffect(() => {
    if (!attempt) return;
    if (
      attempt.ownerUserId !== user.id ||
      attempt.classId !== classId ||
      attempt.practiceId !== practiceId ||
      attempt.attemptId !== attemptId
    ) {
      return;
    }

    // Only create if absent or version changed
    if (
      !saveControllerRef.current ||
      !scopeRef.current ||
      scopeRef.current.version !== attempt.publishedVersionNumber
    ) {
      if (saveControllerRef.current) {
        saveControllerRef.current.dispose();
      }

      scopeRef.current = {
        actorId: user.id,
        classId,
        practiceId,
        attemptId: attempt.attemptId,
        version: attempt.publishedVersionNumber,
      };

      const currentAttemptId = attempt.attemptId;
      const controller = new SaveController({
        saveFn: async queuedAnswers => {
          sentSnapshotRef.current = structuredClone(queuedAnswers);
          // Persist exact sentSnapshot when save starts
          persistScopedDraft(
            currentIndexRef.current,
            answersRef.current,
            feedbacksRef.current,
            undefined,
            'pending',
            queuedAnswers
          );
          const res = await adapter.learning.savePracticeDraft({
            classId,
            practiceId,
            attemptId: currentAttemptId,
            answers: queuedAnswers,
          });
          return res;
        },
        onAcknowledged: (confirmed, savedAt) => {
          if (!isMountedRef.current || scopeRef.current?.actorId !== user.id) return;
          lastAckedAnswersRef.current = confirmed;
          lastAckedAtRef.current = savedAt;
          sentSnapshotRef.current = undefined;
          persistScopedDraft(currentIndexRef.current, answersRef.current, feedbacksRef.current);
        },
        onStatusChange: (status, message) => {
          if (!isMountedRef.current) return;
          if (scopeRef.current?.actorId !== user.id) return;

          if (status === 'saving') {
            setSaveStatus('Đang lưu...');
          } else if (status === 'saved') {
            setSaveStatus(message ?? 'Đã lưu');
            if (saveControllerRef.current?.getLastSavedAnswers()) {
              lastAckedAnswersRef.current = saveControllerRef.current.getLastSavedAnswers()!;
            }
            if (message && message.startsWith('Đã lưu: ')) {
              lastAckedAtRef.current = message.replace('Đã lưu: ', '');
            }
            sentSnapshotRef.current = undefined;
            ackStatusRef.current = 'saved';
            persistScopedDraft(currentIndexRef.current, answersRef.current, feedbacksRef.current, undefined, 'saved');
          } else if (status === 'error') {
            setSaveStatus(message ?? 'Chưa thể lưu');
            ackStatusRef.current = 'error';
            persistScopedDraft(currentIndexRef.current, answersRef.current, feedbacksRef.current, undefined, 'error');
          }
        },
        onError: (err, outcome) => {
          if (!isMountedRef.current) return;
          if (scopeRef.current?.actorId !== user.id) return;

          if (outcome === 'unknown') {
            ackStatusRef.current = 'unknown';
            setActionError(
              'Chưa xác định được kết quả lưu lên máy chủ. Câu trả lời của bạn được giữ an toàn trong phiên làm việc hiện tại.'
            );
            persistScopedDraft(currentIndexRef.current, answersRef.current, feedbacksRef.current, undefined, 'unknown');
          } else {
            ackStatusRef.current = 'error';
            const msg = err instanceof Error ? err.message : 'Lỗi khi lưu bài';
            setActionError(msg);
            persistScopedDraft(currentIndexRef.current, answersRef.current, feedbacksRef.current, undefined, 'error');
          }
        },
      });

      saveControllerRef.current = controller;
    }
  }, [attempt, user.id, classId, practiceId, attemptId]);

  // Apply authoritative attempt and reconcile draft
  const applyAuthoritativeAttempt = (loadedAttempt: PracticeAttemptDetail) => {
    attemptRef.current = loadedAttempt;
    const existingDraft = getAttemptDraft(
      user.id,
      classId,
      practiceId,
      loadedAttempt.attemptId,
      loadedAttempt.publishedVersionNumber
    );

    const reconciled = reconcileAttemptDraft({
      actorId: user.id,
      classId,
      practiceId,
      attempt: loadedAttempt,
      draft: existingDraft,
    });

    // Retain any newer local edits that were typed in answersRef.current during read
    const mergedAnswers = {
      ...reconciled.answers,
      ...answersRef.current,
    };

    setAnswers(mergedAnswers);
    answersRef.current = mergedAnswers;
    setFeedbacks(reconciled.feedbacks);
    feedbacksRef.current = reconciled.feedbacks;
    checkedSnapshotsRef.current = reconciled.checkedSnapshots;

    lastAckedAnswersRef.current = reconciled.lastAckedAnswers;
    lastAckedAtRef.current = reconciled.lastAckedAt;
    sentSnapshotRef.current = reconciled.sentSnapshot;
    ackStatusRef.current = reconciled.ackStatus;

    let initialIndex = reconciled.lastVisitedQuestionIndex;
    const urlQuestion = params?.question;
    if (urlQuestion) {
      const parsed = parseInt(urlQuestion, 10) - 1;
      if (!isNaN(parsed) && parsed >= 0 && parsed < (loadedAttempt.questions?.length ?? 1)) {
        initialIndex = parsed;
      }
    }
    setCurrentIndex(initialIndex);
    currentIndexRef.current = initialIndex;

    if (typeof window !== 'undefined' && !urlQuestion) {
      const url = new URL(window.location.href);
      url.searchParams.set('question', String(initialIndex + 1));
      window.history.replaceState({ questionIndex: initialIndex }, '', url.toString());
    }

    if (saveControllerRef.current) {
      if (reconciled.isBlocked) {
        saveControllerRef.current.block(new Error(reconciled.blockedReason ?? 'Bị khóa do lưu trước đó'));
      } else {
        saveControllerRef.current.unblockAndReconcile(reconciled.lastAckedAnswers);
      }
    }

    if (reconciled.isBlocked) {
      setActionError(reconciled.blockedReason ?? 'Chưa xác định trạng thái lưu bài.');
      setSaveStatus(reconciled.ackStatus === 'unknown' ? 'Chưa rõ trạng thái lưu' : 'Lỗi khi lưu');
    } else if (reconciled.hasUnsavedEdits || !areAnswerMapsEqual(reconciled.lastAckedAnswers, mergedAnswers)) {
      setSaveStatus('Chưa lưu lên máy chủ');
      setActionError(null);
    } else {
      setSaveStatus(reconciled.lastAckedAt ? `Đã lưu: ${reconciled.lastAckedAt}` : 'Tự động lưu');
      setActionError(null);
    }
  };

  // Hydration effect: reconciles when scope is ready, updates question index on harmless query change
  useEffect(() => {
    if (!attempt) return;
    const currentScope = `${user.id}:${classId}:${practiceId}:${attempt.attemptId}:v${attempt.publishedVersionNumber}`;
    if (loadedAttemptScopeRef.current !== currentScope) {
      loadedAttemptScopeRef.current = currentScope;
      applyAuthoritativeAttempt(attempt);
    } else {
      const urlQuestion = params?.question;
      if (urlQuestion) {
        const parsed = parseInt(urlQuestion, 10) - 1;
        if (!isNaN(parsed) && parsed >= 0 && parsed < (attempt.questions?.length ?? 1)) {
          if (parsed !== currentIndexRef.current) {
            setCurrentIndex(parsed);
            currentIndexRef.current = parsed;
          }
        }
      }
    }
  }, [attempt, classId, practiceId, attemptId, user.id, params?.question]);

  // Read-only reconciliation check using existing workspace.load port
  const handleCheckSaveStatus = async () => {
    if (!attempt) return;
    const currentGen = ++checkStatusGenerationRef.current;
    const targetActorId = user.id;
    const targetClassId = classId;
    const targetPracticeId = practiceId;
    const targetAttemptId = attempt.attemptId;
    const targetVersion = attempt.publishedVersionNumber;

    setIsCheckingSaveStatus(true);
    setActionError(null);
    try {
      const res = await adapter.workspace.load('s.practiceAttempt', {
        classId: targetClassId,
        practiceId: targetPracticeId,
        attemptId: targetAttemptId,
      });

      // Scope and unmount guard
      if (
        !isMountedRef.current ||
        checkStatusGenerationRef.current !== currentGen ||
        user.id !== targetActorId ||
        classId !== targetClassId ||
        practiceId !== targetPracticeId ||
        attempt.attemptId !== targetAttemptId ||
        attempt.publishedVersionNumber !== targetVersion
      ) {
        return;
      }

      if (res.kind === 'ready' && res.practiceAttempt && res.practiceAttempt.attemptId === targetAttemptId) {
        applyAuthoritativeAttempt(res.practiceAttempt);
      } else {
        setActionError('Không thể tải trạng thái từ máy chủ.');
      }
    } catch (err: unknown) {
      if (
        !isMountedRef.current ||
        checkStatusGenerationRef.current !== currentGen ||
        attempt.attemptId !== targetAttemptId
      ) {
        return;
      }
      const msg = err instanceof Error ? err.message : 'Lỗi khi kết nối với máy chủ.';
      setActionError(msg);
    } finally {
      if (isMountedRef.current && checkStatusGenerationRef.current === currentGen) {
        setIsCheckingSaveStatus(false);
      }
    }
  };

  // Explicit retry for known rejected writes after validation
  const handleRetrySave = () => {
    if (!attempt || !saveControllerRef.current) return;
    setActionError(null);
    saveControllerRef.current.unblockAndReconcile(lastAckedAnswersRef.current);
    ackStatusRef.current = 'pending';
    saveControllerRef.current.queueSave(answersRef.current);
  };

  // Synchronize native Back/forward popstate
  useEffect(() => {
    const handlePopState = (e: PopStateEvent) => {
      let targetIdx = attempt?.currentQuestionIndex ?? 0;
      if (e.state && typeof e.state.questionIndex === 'number') {
        targetIdx = e.state.questionIndex;
      } else if (typeof window !== 'undefined') {
        const url = new URL(window.location.href);
        const qVal = url.searchParams.get('question');
        if (qVal) {
          const idx = parseInt(qVal, 10) - 1;
          if (!isNaN(idx)) {
            targetIdx = idx;
          }
        }
      }
      const clamped = Math.max(0, Math.min(targetIdx, Math.max(0, totalQuestions - 1)));
      setCurrentIndex(clamped);
      currentIndexRef.current = clamped;
      persistScopedDraft(clamped, answersRef.current, feedbacksRef.current);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [totalQuestions, attempt?.currentQuestionIndex]);

  const navigateToQuestion = (targetIndex: number) => {
    if (targetIndex < 0 || targetIndex >= totalQuestions || targetIndex === currentIndex) return;
    setCurrentIndex(targetIndex);
    currentIndexRef.current = targetIndex;
    persistScopedDraft(targetIndex, answers, feedbacks);

    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.set('question', String(targetIndex + 1));
      window.history.pushState({ questionIndex: targetIndex }, '', url.toString());
    }
  };

  if (!data) {
    return <StatePanel busy title="Đang tải bài luyện tập…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ làm bài luyện tập chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty' || !attempt) {
    return (
      <StatePanel
        title="Không tìm thấy bài luyện tập"
        message={data.kind === 'empty' ? data.message : 'Lượt làm bài không tồn tại.'}
      />
    );
  }

  if (attempt.isCompleted) {
    return (
      <StatePanel
        title="Lượt luyện tập đã hoàn thành"
        message="Lượt làm bài này đã được nộp và ghi nhận kết quả. Bạn có thể xem lại chi tiết điểm số và lời giải."
      >
        <Link
          href={`/student/classes/${classId}/practice/${practiceId}/attempts/${attemptId}/result`}
          className="button primary"
        >
          Xem kết quả luyện tập
        </Link>
      </StatePanel>
    );
  }

  const answeredCount = questions.filter(q => isAnswerComplete(q, answers[q.id])).length;

  const handleAnswerChange = (newAnswer: PracticeAnswer) => {
    const nextFeedbacks = { ...feedbacksRef.current };
    delete nextFeedbacks[newAnswer.questionId];
    setFeedbacks(nextFeedbacks);
    feedbacksRef.current = nextFeedbacks;

    const updated = {
      ...answersRef.current,
      [newAnswer.questionId]: newAnswer,
    };
    setAnswers(updated);
    answersRef.current = updated;
    setSaveStatus('Chưa lưu lên máy chủ');

    // Save to volatile draftStore immediately
    persistScopedDraft(currentIndexRef.current, updated, nextFeedbacks, undefined, 'pending');

    // Queue save via SaveController
    saveControllerRef.current?.queueSave(updated, currentQuestion?.type === 'short_answer' ? 200 : 0);
  };

  const handleCheckAnswer = () => {
    if (!currentQuestion || !attempt || !saveControllerRef.current) {
      setActionError('Chưa thể kiểm tra đáp án: phiên làm bài chưa sẵn sàng.');
      return;
    }

    const controller = saveControllerRef.current;
    const targetQuestionId = currentQuestion.id;
    const targetAttemptId = attempt.attemptId;
    const targetVersion = attempt.publishedVersionNumber;
    const targetActorId = user.id;
    const targetClassId = classId;
    const targetPracticeId = practiceId;
    const checkGen = ++checkAnswerGenerationRef.current;

    if (controller.isBlocked() || ackStatusRef.current === 'unknown' || ackStatusRef.current === 'error') {
      setActionError(
        'Chưa thể kiểm tra đáp án do trạng thái lưu gặp lỗi hoặc chưa xác định. Vui lòng kiểm tra trạng thái lưu.'
      );
      return;
    }

    const capturedAnswer = structuredClone(
      answersRef.current[targetQuestionId] ?? { questionId: targetQuestionId }
    );
    setActionError(null);
    setIsCheckingAnswer(true);

    startTransition(async () => {
      try {
        await controller.flushAnswers(answersRef.current);

        // Scope guard after flush await
        if (
          !isMountedRef.current ||
          checkAnswerGenerationRef.current !== checkGen ||
          saveControllerRef.current !== controller ||
          controller.isDisposed() ||
          controller.isBlocked() ||
          user.id !== targetActorId ||
          classId !== targetClassId ||
          practiceId !== targetPracticeId ||
          attempt.attemptId !== targetAttemptId ||
          attempt.publishedVersionNumber !== targetVersion
        ) {
          return;
        }

        // Guard answer revision / equality: has the answer changed while awaiting flush?
        const answerNow = answersRef.current[targetQuestionId];
        if (!areAnswersEqual(capturedAnswer, answerNow)) {
          return;
        }

        const fb = await adapter.learning.checkPracticeAnswer({
          classId,
          practiceId,
          attemptId: targetAttemptId,
          questionId: targetQuestionId,
          answer: capturedAnswer,
        });

        // Scope guard after checkPracticeAnswer await
        if (
          !isMountedRef.current ||
          checkAnswerGenerationRef.current !== checkGen ||
          user.id !== targetActorId ||
          classId !== targetClassId ||
          practiceId !== targetPracticeId ||
          attempt.attemptId !== targetAttemptId ||
          attempt.publishedVersionNumber !== targetVersion
        ) {
          return;
        }

        // Final revision guard
        const finalAnswerNow = answersRef.current[targetQuestionId];
        if (!areAnswersEqual(capturedAnswer, finalAnswerNow)) {
          return;
        }

        const nextFeedbacks = {
          ...feedbacksRef.current,
          [targetQuestionId]: fb,
        };
        setFeedbacks(nextFeedbacks);
        feedbacksRef.current = nextFeedbacks;
        checkedSnapshotsRef.current = {
          ...checkedSnapshotsRef.current,
          [targetQuestionId]: capturedAnswer,
        };

        persistScopedDraft(currentIndexRef.current, answersRef.current, nextFeedbacks, {
          [targetQuestionId]: capturedAnswer,
        });

        if (controller.getLastSavedAnswers()) {
          lastAckedAnswersRef.current = controller.getLastSavedAnswers()!;
        }
        setSaveStatus(areAnswerMapsEqual(lastAckedAnswersRef.current, answersRef.current) ? 'Đã lưu: Vừa xong' : 'Chưa lưu lên máy chủ');
      } catch (err: unknown) {
        if (!isMountedRef.current || checkAnswerGenerationRef.current !== checkGen) return;
        const message = err instanceof Error ? err.message : 'Không thể kiểm tra câu trả lời.';
        setActionError(message);
      } finally {
        if (isMountedRef.current && checkAnswerGenerationRef.current === checkGen) {
          setIsCheckingAnswer(false);
        }
      }
    });
  };

  const handleConfirmFinish = () => {
    if (!attempt || !saveControllerRef.current) {
      setActionError('Chưa thể hoàn tất: phiên làm bài chưa sẵn sàng.');
      return;
    }

    const controller = saveControllerRef.current;
    const targetAttemptId = attempt.attemptId;
    const targetVersion = attempt.publishedVersionNumber;
    const targetActorId = user.id;
    const targetClassId = classId;
    const targetPracticeId = practiceId;
    const finishGen = ++finishGenerationRef.current;

    if (controller.isBlocked() || ackStatusRef.current === 'unknown' || ackStatusRef.current === 'error') {
      setActionError(
        'Chưa thể hoàn tất bài do trạng thái lưu gặp lỗi hoặc chưa xác định. Vui lòng kiểm tra trạng thái lưu.'
      );
      return;
    }

    setActionError(null);

    startTransition(async () => {
      try {
        // If there are unsaved local edits and controller is not currently saving, queue them now
        if (
          !areAnswerMapsEqual(lastAckedAnswersRef.current, answersRef.current) &&
          !controller.isSaving() &&
          !controller.hasQueuedEdits()
        ) {
          controller.queueSave(answersRef.current);
        }

        await controller.flushAnswers(answersRef.current);

        // Scope & controller guard AFTER flush await
        if (
          !isMountedRef.current ||
          finishGenerationRef.current !== finishGen ||
          saveControllerRef.current !== controller ||
          controller.isDisposed() ||
          controller.isBlocked() ||
          user.id !== targetActorId ||
          classId !== targetClassId ||
          practiceId !== targetPracticeId ||
          attempt.attemptId !== targetAttemptId ||
          attempt.publishedVersionNumber !== targetVersion
        ) {
          setActionError('Phiên làm bài đã thay đổi trong khi chờ lưu bài.');
          return;
        }

        // Verify latest local answer map equals confirmed ACK
        if (!areAnswerMapsEqual(lastAckedAnswersRef.current, answersRef.current)) {
          setActionError('Một số câu trả lời chưa được xác nhận lưu trên máy chủ. Vui lòng thử lại.');
          return;
        }

        const res = await adapter.learning.finishPracticeAttempt({
          classId,
          practiceId,
          attemptId: targetAttemptId,
        });

        // Scope guard AFTER finishPracticeAttempt await
        if (
          !isMountedRef.current ||
          finishGenerationRef.current !== finishGen ||
          user.id !== targetActorId ||
          attempt.attemptId !== targetAttemptId ||
          attempt.publishedVersionNumber !== targetVersion
        ) {
          return;
        }

        // Clear volatile draft on successful finish
        clearAttemptDraft(user.id, classId, practiceId, targetAttemptId);

        setShowFinishModal(false);
        if (res.resultHref) {
          router.pushConfirmed(res.resultHref);
        } else {
          router.pushConfirmed(`/student/classes/${classId}/practice/${practiceId}/attempts/${targetAttemptId}/result`);
        }
      } catch (err: unknown) {
        if (!isMountedRef.current || finishGenerationRef.current !== finishGen) return;
        const message = err instanceof Error ? err.message : 'Không thể hoàn tất bài luyện tập. Vui lòng thử lại.';
        setActionError(message);
      }
    });
  };

  return (
    <div className="practice-attempt-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Attempt Header Bar */}
      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 20px',
          backgroundColor: '#fff',
          borderRadius: '12px',
          border: '1px solid var(--color-border, #e2e8f0)',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <button
            id="btn-open-leave"
            type="button"
            className="button outline"
            onClick={() => setShowLeaveModal(true)}
            style={{ fontSize: '13px', padding: '6px 12px' }}
          >
            ← Rời bài luyện tập
          </button>

          <div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted, #64748b)' }}>
              {attempt.className} · {attempt.primaryTeacherName} (Giáo viên chính)
            </div>
            <strong style={{ fontSize: '16px', color: '#0f172a' }}>{attempt.title}</strong>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <span
            data-testid="save-status-badge"
            style={{
              fontSize: '13px',
              color: '#475569',
              backgroundColor: '#f1f5f9',
              padding: '4px 10px',
              borderRadius: '6px',
            }}
          >
            {saveStatus}
          </span>

          <button
            id="btn-open-finish"
            type="button"
            className="button primary"
            onClick={() => setShowFinishModal(true)}
            style={{ fontSize: '14px', padding: '8px 18px' }}
          >
            Hoàn tất luyện tập
          </button>
        </div>
      </div>

      {actionError && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            color: '#991b1b',
            fontSize: '14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '10px',
          }}
        >
          <span>{actionError}</span>
          <div style={{ display: 'flex', gap: '8px' }}>
            {(ackStatusRef.current === 'unknown' || saveControllerRef.current?.isBlocked()) && (
              <button
                id="btn-check-save-status"
                type="button"
                className="button outline"
                onClick={handleCheckSaveStatus}
                disabled={isCheckingSaveStatus}
                style={{ fontSize: '13px', padding: '4px 10px', backgroundColor: '#fff' }}
              >
                {isCheckingSaveStatus ? 'Đang kiểm tra…' : 'Kiểm tra trạng thái lưu'}
              </button>
            )}
            {ackStatusRef.current === 'error' && (
              <button
                id="btn-retry-save"
                type="button"
                className="button outline"
                onClick={handleRetrySave}
                style={{ fontSize: '13px', padding: '4px 10px', backgroundColor: '#fff' }}
              >
                Thử lưu lại
              </button>
            )}
          </div>
        </div>
      )}

      {/* Main 2-Column Responsive Layout without sideways scroll */}
      <div className="practice-attempt-grid">
        {/* Left Column: Question Card & Controls */}
        <div className="practice-question-main">
          {currentQuestion && (
            <>
              <QuestionRenderer
                question={currentQuestion}
                questionNumber={currentIndex + 1}
                answer={answers[currentQuestion.id]}
                onAnswerChange={handleAnswerChange}
                feedback={feedbacks[currentQuestion.id]}
                readOnly={isCheckingAnswer}
                classId={classId}
              />

              {/* Bottom Question Controls Bar */}
              <div
                className="card"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '16px 20px',
                  backgroundColor: '#fff',
                  borderRadius: '12px',
                  border: '1px solid var(--color-border, #e2e8f0)',
                  flexWrap: 'wrap',
                  gap: '12px',
                }}
              >
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    id="btn-check-answer"
                    type="button"
                    className="button secondary"
                    onClick={handleCheckAnswer}
                    disabled={isPending || isCheckingAnswer || Boolean(saveControllerRef.current?.isBlocked())}
                    style={{ fontSize: '14px', backgroundColor: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}
                  >
                    {isCheckingAnswer ? 'Đang kiểm tra…' : 'Kiểm tra đáp án'}
                  </button>

                  <button
                    id="btn-toggle-hint"
                    type="button"
                    className="button outline"
                    onClick={() => setShowHint(prev => !prev)}
                    style={{ fontSize: '14px' }}
                  >
                    💡 Gợi ý từ Lumi
                  </button>
                </div>

                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    id="btn-prev"
                    type="button"
                    className="button outline"
                    onClick={() => navigateToQuestion(currentIndex - 1)}
                    disabled={currentIndex === 0}
                    style={{ fontSize: '14px' }}
                  >
                    Câu trước
                  </button>

                  {currentIndex < totalQuestions - 1 ? (
                    <button
                      id="btn-next"
                      type="button"
                      className="button primary"
                      onClick={() => navigateToQuestion(currentIndex + 1)}
                      style={{ fontSize: '14px' }}
                    >
                      Câu tiếp theo
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button primary"
                      onClick={() => setShowFinishModal(true)}
                      style={{ fontSize: '14px' }}
                    >
                      Hoàn tất luyện tập
                    </button>
                  )}
                </div>
              </div>

              {/* Lumi Pedagogical Hint Box */}
              {showHint && (
                <div
                  className="card"
                  style={{
                    marginTop: '16px',
                    padding: '16px 20px',
                    borderRadius: '10px',
                    backgroundColor: '#fffbeb',
                    border: '1px solid #fef08a',
                    color: '#713f12',
                  }}
                >
                  <div style={{ fontWeight: 700, marginBottom: '6px', fontSize: '14px' }}>
                    Gợi ý phương pháp từ Lumi:
                  </div>
                  <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.5 }}>
                    {currentQuestion.sourceRef && currentQuestion.sourceRef.isAccessible !== false && currentQuestion.sourceRef.locator
                      ? `Tham khảo tài liệu "${currentQuestion.sourceRef.documentTitle}", lưu ý mục ${currentQuestion.sourceRef.locator} để nắm công thức trọng tâm.`
                      : 'Hãy xác định dạng hàm số, xem xét kỹ các hệ số và áp dụng các định lý tương ứng từng bước.'}
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Right Column: Question Palette */}
        <div className="practice-palette-sidebar">
          <div
            className="card"
            style={{
              padding: '18px',
              backgroundColor: '#fff',
              borderRadius: '12px',
              border: '1px solid var(--color-border, #e2e8f0)',
              position: 'sticky',
              top: '20px',
            }}
          >
            <h3 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 8px 0', color: '#0f172a' }}>
              Bảng câu hỏi
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)', margin: '0 0 16px 0' }}>
              Đã hoàn thành: {answeredCount}/{totalQuestions} câu
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '18px' }}>
              {questions.map((q, idx) => {
                const isActive = idx === currentIndex;
                const isComplete = isAnswerComplete(q, answers[q.id]);
                const fb = feedbacks[q.id];
                const typeLabel = QUESTION_TYPE_LABELS[q.type] ?? 'Câu hỏi';

                let bg = '#f8fafc';
                let color = '#334155';
                let borderColor = '#cbd5e1';

                if (fb) {
                  bg = fb.isCorrect ? '#f0fdf4' : '#fef2f2';
                  color = fb.isCorrect ? '#16a34a' : '#dc2626';
                  borderColor = fb.isCorrect ? '#86efac' : '#fca5a5';
                } else if (isComplete) {
                  bg = '#eff6ff';
                  color = '#2563eb';
                  borderColor = '#bfdbfe';
                }

                if (isActive) {
                  borderColor = 'var(--brand-primary, #3b82f6)';
                }

                return (
                  <button
                    key={q.id}
                    type="button"
                    onClick={() => navigateToQuestion(idx)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      borderRadius: '8px',
                      border: `2px solid ${borderColor}`,
                      backgroundColor: bg,
                      color,
                      fontWeight: isActive ? 700 : 500,
                      fontSize: '13px',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                  >
                    <span>
                      <strong>{idx + 1}</strong> {typeLabel}
                    </span>
                    {fb ? (
                      <span>{fb.isCorrect ? '✓' : '✕'}</span>
                    ) : isComplete ? (
                      <span style={{ fontSize: '12px' }}>Đã làm</span>
                    ) : (
                      <span style={{ fontSize: '12px', color: '#94a3b8' }}>Chưa làm</span>
                    )}
                  </button>
                );
              })}
            </div>

            <div style={{ fontSize: '12px', color: 'var(--color-text-muted, #64748b)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '10px', height: '10px', borderRadius: '3px', backgroundColor: '#eff6ff', border: '1px solid #bfdbfe' }} />
                <span>Đã trả lời</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '10px', height: '10px', borderRadius: '3px', backgroundColor: '#f0fdf4', border: '1px solid #86efac' }} />
                <span>Đúng (đã kiểm tra)</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '10px', height: '10px', borderRadius: '3px', backgroundColor: '#fef2f2', border: '1px solid #fca5a5' }} />
                <span>Chưa đúng (đã kiểm tra)</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Leave Modal */}
      <Dialog
        open={showLeaveModal}
        onClose={() => setShowLeaveModal(false)}
        title="Rời khỏi bài luyện tập?"
      >
        <div>
          <p style={{ fontSize: '14px', color: 'var(--color-text-muted, #64748b)', margin: '0 0 20px 0', lineHeight: 1.5 }}>
            {!areAnswerMapsEqual(lastAckedAnswersRef.current, answers) || Boolean(saveControllerRef.current?.isBlocked())
              ? 'Một số câu trả lời của bạn chưa được xác nhận lưu trên máy chủ và chỉ được giữ trong phiên làm việc hiện tại. Bạn có thể tiếp tục làm bài hoặc quay lại sau trong phiên này.'
              : 'Các câu trả lời đã được lưu trên hệ thống. Bạn có thể quay lại làm tiếp bất cứ lúc nào.'}
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button
              id="btn-cancel-leave"
              type="button"
              className="button outline"
              onClick={() => setShowLeaveModal(false)}
            >
              Ở lại luyện tập
            </button>
            <button
              id="btn-confirm-leave"
              type="button"
              className="button primary"
              onClick={() => {
                setShowLeaveModal(false);
                persistScopedDraft(currentIndexRef.current, answersRef.current, feedbacksRef.current);
                router.pushConfirmed(`/student/classes/${classId}/practice`);
              }}
            >
              Xác nhận rời
            </button>
          </div>
        </div>
      </Dialog>

      {/* Finish Modal */}
      <Dialog
        open={showFinishModal}
        onClose={() => setShowFinishModal(false)}
        title="Xác nhận hoàn tất bài luyện tập"
        busy={isPending}
      >
        <div>
          <p style={{ fontSize: '14px', color: 'var(--color-text-muted, #64748b)', margin: '0 0 16px 0', lineHeight: 1.5 }}>
            Bạn đã trả lời {answeredCount} / {totalQuestions} câu hỏi. Sau khi hoàn tất, hệ thống sẽ tổng kết điểm số và cung cấp giải thích chi tiết cho từng câu.
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button
              id="btn-close-finish"
              type="button"
              className="button outline"
              onClick={() => setShowFinishModal(false)}
              disabled={isPending}
            >
              Tiếp tục làm bài
            </button>
            <button
              id="btn-confirm-finish"
              type="button"
              className="button primary"
              onClick={handleConfirmFinish}
              disabled={isPending}
            >
              {isPending ? 'Đang hoàn tất…' : 'Hoàn tất'}
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
