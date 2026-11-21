'use client';
import { useState, useTransition } from 'react';
import Link from 'next/link';
import {useGuardedRouter as useRouter} from '@/components/unsaved-changes';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData, PracticeResultQuestionItem } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { setTutorDraft } from '@/lib/draft-store';
import { StatePanel, Icon } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params: RouteParams;
  user: User;
};

export function StudentPracticeResultView({ data, reload, params, user }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [filterMode, setFilterMode] = useState<'all' | 'incorrect' | 'correct'>('all');
  const [actionError, setActionError] = useState<string | null>(null);

  if (!data) {
    return <StatePanel busy title="Đang tải kết quả bài luyện tập…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ kết quả luyện tập chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty' || !data.practiceResult) {
    return (
      <StatePanel
        title="Không tìm thấy kết quả"
        message={data.kind === 'empty' ? data.message : 'Lượt làm bài chưa có kết quả.'}
      />
    );
  }

  const result = data.practiceResult;
  const classId = params?.classId ?? result.classId;
  const practiceId = params?.practiceId ?? result.practiceId;
  const questions: PracticeResultQuestionItem[] = result.questions ?? [];

  const handleRetry = () => {
    setActionError(null);
    startTransition(async () => {
      try {
        const res = await adapter.learning.startPracticeAttempt({
          classId,
          practiceId,
          intent: 'retry',
        });
        router.push(res.href);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Không thể tạo lượt làm mới.';
        setActionError(message);
      }
    });
  };

  const handleReviewWithLumi = () => {
    const prompt = `Chào Lumi, mình vừa hoàn thành bài luyện tập "${result.title}" (Độ chính xác ${result.score.percentage}%). Bạn có thể giúp mình ôn tập và giải đáp thêm các phần kiến thức còn vướng mắc không?`;
    setTutorDraft(user.id, classId, prompt, 'new');
    router.push(`/student/classes/${classId}/tutor?compose=new`);
  };

  const handleAskLumiQuestion = (q: PracticeResultQuestionItem) => {
    const prompt = `Chào Lumi, em muốn hỏi về câu ${q.questionNumber}: "${q.prompt}". Em đã chọn "${q.studentAnswerText}" nhưng đáp án đúng là "${q.correctAnswerText}". Em chưa hiểu rõ phần này, Lumi giảng thêm cho em nhé!`;
    setTutorDraft(user.id, classId, prompt, 'new');
    router.push(`/student/classes/${classId}/tutor?compose=new`);
  };

  const correctQuestions = questions.filter(q => q.isCorrect);
  const incorrectQuestions = questions.filter(q => !q.isCorrect);

  const displayedQuestions =
    filterMode === 'incorrect'
      ? incorrectQuestions
      : filterMode === 'correct'
      ? correctQuestions
      : questions;

  return (
    <div className="practice-result-content">
      {/* Top Navigation & Action Header */}
      <div className="practice-result-topbar">
        <div className="practice-result-nav">
          <Link
            href={`/student/classes/${classId}/practice`}
            className="button outline"
          >
            ← Trở về Luyện tập
          </Link>
          <span className="practice-result-meta">
            Lượt làm #{result.attemptNumber} · Hoàn thành: {result.completedAt}
          </span>
        </div>

        <div className="practice-result-actions">
          <button
            type="button"
            className="button outline"
            onClick={handleReviewWithLumi}
          >
            <Icon name="sparkles" />
            <span>Ôn cùng Lumi</span>
          </button>
          <button
            type="button"
            className="button primary"
            onClick={handleRetry}
            disabled={isPending}
          >
            {isPending ? 'Đang tạo lượt mới…' : 'Làm lại bài luyện tập (Tạo lượt mới)'}
          </button>
        </div>
      </div>

      {actionError && (
        <div className="practice-error-banner">
          {actionError}
        </div>
      )}

      {/* Main Score & Stats Banner */}
      <div className="card practice-result-banner">
        <div className="practice-result-banner-inner">
          <div className="practice-result-banner-info">
            <span className="practice-result-badge">
              Hoàn thành bài luyện tập
            </span>
            <h1 className="practice-result-title">
              {result.title}
            </h1>
            <p className="practice-result-sub">
              {result.className} · Phiên bản v{result.publishedVersionNumber}
            </p>
          </div>

          <div className="practice-score-summary">
            <div className="practice-score-metric">
              <div className="practice-score-pct">
                {result.score.percentage}%
              </div>
              <div className="practice-score-label">
                Độ chính xác
              </div>
            </div>

            <div className="practice-score-divider" />

            <div className="practice-score-metric">
              <div className="practice-score-ratio">
                {result.score.correct}/{result.score.total}
              </div>
              <div className="practice-score-label">
                Câu đúng
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3 Metric Summary Cards */}
      <div className="practice-metrics-grid">
        <div className="card practice-metric-card">
          <div className="practice-metric-icon is-correct" aria-hidden="true">
            <Icon name="check" />
          </div>
          <div>
            <div className="practice-metric-label">
              Trả lời chính xác
            </div>
            <div className="practice-metric-value is-correct">
              {result.correctCount} câu
            </div>
          </div>
        </div>

        <div className="card practice-metric-card">
          <div className="practice-metric-icon is-incorrect" aria-hidden="true">
            ✕
          </div>
          <div>
            <div className="practice-metric-label">
              Cần ôn luyện lại
            </div>
            <div className="practice-metric-value is-incorrect">
              {result.incorrectCount} câu
            </div>
          </div>
        </div>

        <div className="card practice-metric-card">
          <div className="practice-metric-icon is-time" aria-hidden="true">
            <Icon name="clock" />
          </div>
          <div>
            <div className="practice-metric-label">
              Thời gian hoàn thành
            </div>
            <div className="practice-metric-value">
              {result.durationMinutes} phút
            </div>
          </div>
        </div>
      </div>

      {/* Pedagogical Study Tip Card */}
      {result.studyTip && (
        <div className="card practice-tip-card">
          <div className="practice-tip-main">
            <span className="practice-tip-icon" aria-hidden="true">
              <Icon name="info" />
            </span>
            <div>
              <strong>
                Lời khuyên học tập từ Lumi:
              </strong>
              <p>
                {result.studyTip}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="button outline practice-tip-btn"
            onClick={handleReviewWithLumi}
          >
            Hỏi chi tiết Lumi →
          </button>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="practice-result-tabs">
        <button
          type="button"
          onClick={() => setFilterMode('all')}
          className={`practice-result-tab is-all ${filterMode === 'all' ? 'is-active' : ''}`}
        >
          Tất cả ({questions.length})
        </button>

        <button
          type="button"
          onClick={() => setFilterMode('incorrect')}
          className={`practice-result-tab is-incorrect ${filterMode === 'incorrect' ? 'is-active' : ''}`}
        >
          Chỉ câu sai ({incorrectQuestions.length})
        </button>

        <button
          type="button"
          onClick={() => setFilterMode('correct')}
          className={`practice-result-tab is-correct ${filterMode === 'correct' ? 'is-active' : ''}`}
        >
          Chỉ câu đúng ({correctQuestions.length})
        </button>
      </div>

      {/* Question Details List */}
      <div className="practice-result-list">
        {displayedQuestions.map(q => (
          <div
            key={q.id}
            className={`card practice-result-item ${q.isCorrect ? '' : 'is-incorrect'}`}
          >
            <div className="practice-result-item-head">
              <div className="practice-result-item-badges">
                <span className={`practice-result-qnum ${q.isCorrect ? 'is-correct' : 'is-incorrect'}`}>
                  {q.questionNumber}
                </span>
                <span className={`practice-result-state ${q.isCorrect ? 'is-correct' : 'is-incorrect'}`}>
                  {q.isCorrect ? 'Chính xác' : 'Chưa chính xác'}
                </span>
              </div>

              <button
                type="button"
                className="button outline practice-ask-lumi-btn"
                onClick={() => handleAskLumiQuestion(q)}
              >
                <Icon name="sparkles" />
                <span>Hỏi Lumi câu này</span>
              </button>
            </div>

            <div className="practice-result-prompt">
              {q.prompt}
            </div>

            {/* Student answer vs Correct answer comparison */}
            <div className="practice-answer-compare">
              <div>
                <span className="practice-answer-label">
                  Câu trả lời của bạn:
                </span>
                <strong className={`practice-answer-val ${q.isCorrect ? 'is-correct' : 'is-incorrect'}`}>
                  {q.studentAnswerText}
                </strong>
              </div>

              {!q.isCorrect && (
                <div>
                  <span className="practice-answer-label">
                    Đáp án đúng:
                  </span>
                  <strong className="practice-answer-val is-correct">
                    {q.correctAnswerText}
                  </strong>
                </div>
              )}
            </div>

            {/* Explanation */}
            <div className="practice-result-explanation">
              <strong>Giải thích:</strong> {q.explanation}
            </div>

            {/* Grounding Source Citation */}
            {q.sourceRef && (
              <div className="practice-result-source">
                {q.sourceRef.isAccessible === false ? (
                  <span className="practice-result-source-unavailable">
                    <span>Nguồn: Tài liệu không còn khả dụng</span>
                  </span>
                ) : (
                  <Link
                    href={`/student/classes/${classId}/documents/${q.sourceRef.documentId}?version=${q.sourceRef.versionNumber}&page=${q.sourceRef.pageNumber ?? 1}`}
                    className="button outline source-reference-link"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Icon name="book" />
                    <span>{q.sourceRef.displayText || q.sourceReference || 'Xem tài liệu nguồn của lớp'}</span>
                  </Link>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
