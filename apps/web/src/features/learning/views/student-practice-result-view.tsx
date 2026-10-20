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
    <div className="practice-result-content" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Navigation & Action Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Link
            href={`/student/classes/${classId}/practice`}
            className="button outline"
            style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
          >
            ← Trở về Luyện tập
          </Link>
          <span style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)' }}>
            Lượt làm #{result.attemptNumber} · Hoàn thành: {result.completedAt}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            type="button"
            className="button outline"
            onClick={handleReviewWithLumi}
            style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
          >
            <Icon name="sparkles" />
            <span>Ôn cùng Lumi</span>
          </button>
          <button
            type="button"
            className="button primary"
            onClick={handleRetry}
            disabled={isPending}
            style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
          >
            {isPending ? 'Đang tạo lượt mới…' : 'Làm lại bài luyện tập (Tạo lượt mới)'}
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
          }}
        >
          {actionError}
        </div>
      )}

      {/* Main Score & Stats Banner */}
      <div
        className="card"
        style={{
          padding: '28px',
          borderRadius: '16px',
          backgroundColor: '#fff',
          border: '1px solid var(--color-border, #e2e8f0)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '20px' }}>
          <div>
            <span
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '3px 10px',
                borderRadius: '6px',
                backgroundColor: '#f0fdf4',
                color: '#16a34a',
                display: 'inline-block',
                marginBottom: '8px',
              }}
            >
              Hoàn thành bài luyện tập
            </span>
            <h1 style={{ fontSize: '22px', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              {result.title}
            </h1>
            <p style={{ margin: '6px 0 0 0', fontSize: '14px', color: 'var(--color-text-muted, #64748b)' }}>
              {result.className} · Phiên bản v{result.publishedVersionNumber}
            </p>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '24px',
              padding: '16px 24px',
              borderRadius: '12px',
              backgroundColor: '#f8fafc',
              border: '1px solid #e2e8f0',
            }}
          >
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '32px', fontWeight: 800, color: '#2563eb', lineHeight: 1 }}>
                {result.score.percentage}%
              </div>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginTop: '4px' }}>
                Độ chính xác
              </div>
            </div>

            <div style={{ width: '1px', height: '40px', backgroundColor: '#e2e8f0' }} />

            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '28px', fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>
                {result.score.correct}/{result.score.total}
              </div>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginTop: '4px' }}>
                Câu đúng
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3 Metric Summary Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '16px',
        }}
      >
        <div
          className="card"
          style={{
            padding: '20px',
            borderRadius: '12px',
            backgroundColor: '#fff',
            border: '1px solid var(--color-border, #e2e8f0)',
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
          }}
        >
          <div
            style={{
              width: '46px',
              height: '46px',
              borderRadius: '10px',
              backgroundColor: '#f0fdf4',
              color: '#16a34a',
              border: '1px solid #bbf7d0',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '20px',
              fontWeight: 700,
            }}
          >
            ✓
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted, #64748b)', marginBottom: '2px' }}>
              Trả lời chính xác
            </div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#16a34a' }}>
              {result.correctCount} câu
            </div>
          </div>
        </div>

        <div
          className="card"
          style={{
            padding: '20px',
            borderRadius: '12px',
            backgroundColor: '#fff',
            border: '1px solid var(--color-border, #e2e8f0)',
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
          }}
        >
          <div
            style={{
              width: '46px',
              height: '46px',
              borderRadius: '10px',
              backgroundColor: '#fef2f2',
              color: '#dc2626',
              border: '1px solid #fecaca',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '20px',
              fontWeight: 700,
            }}
          >
            ✕
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted, #64748b)', marginBottom: '2px' }}>
              Cần ôn luyện lại
            </div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#dc2626' }}>
              {result.incorrectCount} câu
            </div>
          </div>
        </div>

        <div
          className="card"
          style={{
            padding: '20px',
            borderRadius: '12px',
            backgroundColor: '#fff',
            border: '1px solid var(--color-border, #e2e8f0)',
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
          }}
        >
          <div
            style={{
              width: '46px',
              height: '46px',
              borderRadius: '10px',
              backgroundColor: '#eff6ff',
              color: '#2563eb',
              border: '1px solid #bfdbfe',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '18px',
            }}
          >
            <Icon name="clock" />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted, #64748b)', marginBottom: '2px' }}>
              Thời gian hoàn thành
            </div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#0f172a' }}>
              {result.durationMinutes} phút
            </div>
          </div>
        </div>
      </div>

      {/* Pedagogical Study Tip Card */}
      {result.studyTip && (
        <div
          className="card"
          style={{
            padding: '16px 20px',
            borderRadius: '12px',
            backgroundColor: '#fffbeb',
            border: '1px solid #fef08a',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', flex: 1, minWidth: '260px' }}>
            <span style={{ fontSize: '20px' }}>💡</span>
            <div>
              <strong style={{ color: '#854d0e', fontSize: '14px', display: 'block', marginBottom: '4px' }}>
                Lời khuyên học tập từ Lumi:
              </strong>
              <p style={{ margin: 0, fontSize: '14px', color: '#713f12', lineHeight: 1.5 }}>
                {result.studyTip}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="button outline"
            onClick={handleReviewWithLumi}
            style={{ fontSize: '13px', backgroundColor: '#fff', color: '#854d0e', borderColor: '#fde047' }}
          >
            Hỏi chi tiết Lumi →
          </button>
        </div>
      )}

      {/* Filter Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '8px',
          borderBottom: '1px solid var(--color-border, #e2e8f0)',
          paddingBottom: '8px',
        }}
      >
        <button
          type="button"
          onClick={() => setFilterMode('all')}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            border: 'none',
            backgroundColor: filterMode === 'all' ? 'var(--brand-primary, #3b82f6)' : 'transparent',
            color: filterMode === 'all' ? '#fff' : '#475569',
            fontWeight: 600,
            fontSize: '14px',
            cursor: 'pointer',
          }}
        >
          Tất cả ({questions.length})
        </button>

        <button
          type="button"
          onClick={() => setFilterMode('incorrect')}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            border: 'none',
            backgroundColor: filterMode === 'incorrect' ? '#ef4444' : 'transparent',
            color: filterMode === 'incorrect' ? '#fff' : '#475569',
            fontWeight: 600,
            fontSize: '14px',
            cursor: 'pointer',
          }}
        >
          Chỉ câu sai ({incorrectQuestions.length})
        </button>

        <button
          type="button"
          onClick={() => setFilterMode('correct')}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            border: 'none',
            backgroundColor: filterMode === 'correct' ? '#16a34a' : 'transparent',
            color: filterMode === 'correct' ? '#fff' : '#475569',
            fontWeight: 600,
            fontSize: '14px',
            cursor: 'pointer',
          }}
        >
          Chỉ câu đúng ({correctQuestions.length})
        </button>
      </div>

      {/* Question Details List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {displayedQuestions.map(q => (
          <div
            key={q.id}
            className="card"
            style={{
              padding: '20px 24px',
              borderRadius: '12px',
              backgroundColor: '#fff',
              border: `1px solid ${q.isCorrect ? '#e2e8f0' : '#fecaca'}`,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '28px',
                    height: '28px',
                    borderRadius: '6px',
                    backgroundColor: q.isCorrect ? '#f0fdf4' : '#fef2f2',
                    color: q.isCorrect ? '#16a34a' : '#dc2626',
                    fontWeight: 700,
                    fontSize: '14px',
                  }}
                >
                  {q.questionNumber}
                </span>
                <span
                  style={{
                    fontSize: '13px',
                    fontWeight: 600,
                    padding: '3px 10px',
                    borderRadius: '6px',
                    backgroundColor: q.isCorrect ? '#f0fdf4' : '#fef2f2',
                    color: q.isCorrect ? '#16a34a' : '#dc2626',
                  }}
                >
                  {q.isCorrect ? 'Chính xác' : 'Chưa chính xác'}
                </span>
              </div>

              <button
                type="button"
                className="button outline"
                onClick={() => handleAskLumiQuestion(q)}
                style={{ fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <Icon name="sparkles" />
                <span>Hỏi Lumi câu này</span>
              </button>
            </div>

            <div style={{ fontSize: '15px', fontWeight: 600, color: '#0f172a', marginBottom: '16px', lineHeight: 1.5 }}>
              {q.prompt}
            </div>

            {/* Student answer vs Correct answer comparison */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: '14px',
                padding: '14px 16px',
                borderRadius: '8px',
                backgroundColor: '#f8fafc',
                marginBottom: '16px',
                fontSize: '14px',
              }}
            >
              <div>
                <span style={{ color: 'var(--color-text-muted, #64748b)', fontSize: '12px', display: 'block', marginBottom: '4px' }}>
                  Câu trả lời của bạn:
                </span>
                <strong style={{ color: q.isCorrect ? '#16a34a' : '#dc2626' }}>
                  {q.studentAnswerText}
                </strong>
              </div>

              {!q.isCorrect && (
                <div>
                  <span style={{ color: 'var(--color-text-muted, #64748b)', fontSize: '12px', display: 'block', marginBottom: '4px' }}>
                    Đáp án đúng:
                  </span>
                  <strong style={{ color: '#16a34a' }}>
                    {q.correctAnswerText}
                  </strong>
                </div>
              )}
            </div>

            {/* Explanation */}
            <div style={{ fontSize: '14px', color: '#334155', lineHeight: 1.6, marginBottom: '12px' }}>
              <strong>Giải thích:</strong> {q.explanation}
            </div>

            {/* Grounding Source Citation */}
            {q.sourceRef && (
              <div style={{ marginTop: '10px' }}>
                {q.sourceRef.isAccessible === false ? (
                  <span
                    style={{
                      fontSize: '12px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: '#64748b',
                      backgroundColor: '#f1f5f9',
                      padding: '4px 10px',
                      borderRadius: '6px',
                    }}
                  >
                    <span>Nguồn: Tài liệu không còn khả dụng</span>
                  </span>
                ) : (
                  <Link
                    href={`/student/classes/${classId}/documents/${q.sourceRef.documentId}?version=${q.sourceRef.versionNumber}&page=${q.sourceRef.pageNumber ?? 1}`}
                    className="button outline source-reference-link"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: '12px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: '#2563eb',
                      backgroundColor: '#eff6ff',
                      borderColor: '#bfdbfe',
                    }}
                  >
                    <span>📖 {q.sourceRef.displayText || q.sourceReference || 'Xem tài liệu nguồn của lớp'}</span>
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
