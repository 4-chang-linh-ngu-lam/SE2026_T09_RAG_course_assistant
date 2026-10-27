'use client';
import { useState, useTransition } from 'react';
import Link from 'next/link';
import {useGuardedRouter as useRouter} from '@/components/unsaved-changes';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData, PracticeActivity, PracticeHistoryItem } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { draftStore, formatPracticeListDraftKey, getAttemptDraft } from '@/lib/draft-store';
import { StatePanel, Dialog, Icon } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  role: Role;
  reload(): void;
  params: RouteParams;
  user: User;
};

export function StudentPracticeListView({ data, reload, params, user }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const classSummary = data && data.kind === 'ready' ? data.classSummary : undefined;
  const practiceList = data && data.kind === 'ready' ? data.practiceList : undefined;
  const classId = params?.classId ?? classSummary?.id ?? practiceList?.classId ?? '';

  const filterKey = formatPracticeListDraftKey(user?.id ?? 'anon', classId);
  const savedFilter = draftStore.get<{ search: string; status: 'all' | 'not_started' | 'in_progress' | 'completed' }>(filterKey);

  const [search, setSearchState] = useState(savedFilter?.search ?? '');
  const [statusFilter, setStatusFilterState] = useState<'all' | 'not_started' | 'in_progress' | 'completed'>(
    savedFilter?.status ?? 'all'
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const setSearch = (val: string) => {
    setSearchState(val);
    draftStore.set(filterKey, { search: val, status: statusFilter });
  };

  const setStatusFilter = (val: 'all' | 'not_started' | 'in_progress' | 'completed') => {
    setStatusFilterState(val);
    draftStore.set(filterKey, { search, status: val });
  };

  if (!data) {
    return <StatePanel busy title="Đang tải danh sách bài luyện tập…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ luyện tập chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return <StatePanel title="Chưa có bài luyện tập" message={data.message} />;
  }

  const activities: PracticeActivity[] = practiceList?.activities ?? [];

  const handleStartOrRetry = (practiceId: string, intent: 'start' | 'resume' | 'retry') => {
    setActionError(null);
    startTransition(async () => {
      try {
        const res = await adapter.learning.startPracticeAttempt({
          classId,
          practiceId,
          intent,
        });
        router.push(res.href);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Không thể bắt đầu bài luyện tập.';
        setActionError(message);
      }
    });
  };

  const filtered = activities.filter(act => {
    if (statusFilter === 'not_started' && act.status !== 'NOT_STARTED') return false;
    if (statusFilter === 'in_progress' && act.status !== 'IN_PROGRESS') return false;
    if (statusFilter === 'completed' && act.status !== 'COMPLETED') return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return act.title.toLowerCase().includes(q) || act.topic.toLowerCase().includes(q);
    }
    return true;
  });

  const allHistory: PracticeHistoryItem[] =
    practiceList?.history ??
    activities.flatMap(a => a.history ?? []);

  const totalHistoryCount = allHistory.length;

  return (
    <div className="practice-hub-content" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Action / History bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <p style={{ margin: 0, color: 'var(--color-text-muted, #64748b)', fontSize: '14px' }}>
          Ôn luyện kiến thức trọng tâm với phản hồi tức thời từ trợ lý học tập Lumi.
        </p>
        <button
          id="open-drawer-btn"
          type="button"
          className="button outline"
          onClick={() => setDrawerOpen(true)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}
        >
          <Icon name="clock" />
          <span>Lịch sử luyện tập: {totalHistoryCount} lượt đã hoàn thành</span>
        </button>
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

      {/* Filter and Search Bar */}
      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          padding: '16px',
          flexWrap: 'wrap',
          backgroundColor: '#fff',
        }}
      >
        <div style={{ flex: 1, minWidth: '240px' }}>
          <input
            id="practice-search"
            type="search"
            aria-label="Tìm kiếm bài luyện tập"
            className="input"
            placeholder="Tìm bài luyện tập theo tên, chuyên đề..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ width: '100%' }}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <label htmlFor="status-filter" style={{ fontSize: '14px', fontWeight: 500, whiteSpace: 'nowrap' }}>
            Trạng thái:
          </label>
          <select
            id="status-filter"
            className="input"
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as 'all' | 'not_started' | 'in_progress' | 'completed')}
            style={{ minWidth: '160px' }}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="not_started">Chưa bắt đầu</option>
            <option value="in_progress">Đang làm</option>
            <option value="completed">Đã hoàn thành</option>
          </select>
        </div>
      </div>

      {/* Canonical Horizontal Row Activities List */}
      {filtered.length === 0 ? (
        <div className="card" style={{ padding: '40px', textAlign: 'center', backgroundColor: '#fff' }}>
          <p style={{ color: 'var(--color-text-muted, #64748b)', margin: 0 }}>
            Không có bài luyện tập nào phù hợp với bộ lọc hiện tại.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {filtered.map(act => {
            const isInProgress = act.status === 'IN_PROGRESS';
            const isCompleted = act.status === 'COMPLETED';

            // Derive current question position from scoped attempt draft if present
            let resumeIndex = act.currentQuestionIndex ?? 0;
            const targetQuestionCount = act.activeAttemptQuestionCount ?? act.questionCount;
            if (isInProgress && act.activeAttemptId && act.activeAttemptVersionNumber !== undefined) {
              const draft = getAttemptDraft(
                user?.id ?? 'anon',
                classId,
                act.id,
                act.activeAttemptId,
                act.activeAttemptVersionNumber
              );
              if (draft && typeof draft.lastVisitedQuestionIndex === 'number') {
                resumeIndex = Math.max(0, Math.min(draft.lastVisitedQuestionIndex, targetQuestionCount - 1));
              }
            }

            return (
              <div
                key={act.id}
                className="card activity-row"
                data-practice-id={act.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '20px 24px',
                  borderRadius: '12px',
                  backgroundColor: '#fff',
                  border: isInProgress ? '2px solid var(--brand-primary, #3b82f6)' : '1px solid var(--color-border, #e2e8f0)',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                  flexWrap: 'wrap',
                  gap: '16px',
                }}
              >
                {/* Left section: Icon badge & details */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1, minWidth: '280px' }}>
                  <div
                    style={{
                      width: '44px',
                      height: '44px',
                      borderRadius: '10px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '18px',
                      fontWeight: 700,
                      backgroundColor: isCompleted ? '#f0fdf4' : isInProgress ? '#fffbeb' : '#f8fafc',
                      color: isCompleted ? '#16a34a' : isInProgress ? '#b45309' : '#64748b',
                      border: `1px solid ${isCompleted ? '#bbf7d0' : isInProgress ? '#fde68a' : '#e2e8f0'}`,
                      flexShrink: 0,
                    }}
                  >
                    {isCompleted ? '✓' : isInProgress ? '✎' : '📋'}
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                      <span
                        style={{
                          fontSize: '12px',
                          fontWeight: 600,
                          padding: '2px 8px',
                          borderRadius: '6px',
                          backgroundColor: isCompleted ? '#f0fdf4' : isInProgress ? '#eff6ff' : '#f1f5f9',
                          color: isCompleted ? '#16a34a' : isInProgress ? '#2563eb' : '#64748b',
                        }}
                      >
                        {isCompleted ? 'Đã hoàn thành' : isInProgress ? 'Đang làm' : 'Chưa bắt đầu'}
                      </span>
                      <span style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)' }}>
                        {act.questionCount} câu hỏi
                      </span>
                      <span style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)' }}>·</span>
                      <span style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)' }}>
                        Chủ đề: {act.topic}
                      </span>
                    </div>

                    <h3 style={{ fontSize: '16px', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                      {act.title}
                    </h3>

                    {isCompleted && act.lastScore && (
                      <div style={{ marginTop: '6px', fontSize: '13px', color: '#16a34a' }}>
                        Điểm gần nhất: <strong>{act.lastScore.correct}/{act.lastScore.total} ({act.lastScore.percentage}%)</strong>
                        {act.lastCompletedAt && (
                          <span style={{ color: 'var(--color-text-muted, #64748b)', marginLeft: '10px' }}>
                            Hoàn thành: {act.lastCompletedAt}
                          </span>
                        )}
                      </div>
                    )}

                    {isInProgress && (
                      <div style={{ marginTop: '6px', fontSize: '13px', color: '#2563eb' }}>
                        Đang làm: Câu {resumeIndex + 1} / {targetQuestionCount}
                      </div>
                    )}
                  </div>
                </div>

                {/* Right section: Action buttons */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
                  {isCompleted ? (
                    <>
                      {act.latestResultAttemptId ? (
                        <Link
                          id={`practice-result-${act.id}`}
                          href={`/student/classes/${classId}/practice/${act.id}/attempts/${act.latestResultAttemptId}/result`}
                          className="button outline"
                          data-practice-id={act.id}
                          data-attempt-id={act.latestResultAttemptId}
                          data-action="view-result"
                          style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                        >
                          <span>Xem kết quả & lời giải</span>
                        </Link>
                      ) : null}
                      <button
                        type="button"
                        className="button primary"
                        data-practice-id={act.id}
                        data-action="retry"
                        onClick={() => handleStartOrRetry(act.id, 'retry')}
                        disabled={isPending}
                        style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                      >
                        <span>Luyện lại</span>
                      </button>
                    </>
                  ) : isInProgress ? (
                    act.activeAttemptId ? (
                      <Link
                        id={`practice-continue-${act.id}`}
                        href={`/student/classes/${classId}/practice/${act.id}/attempts/${act.activeAttemptId}?question=${resumeIndex + 1}`}
                        className="button primary"
                        data-practice-id={act.id}
                        data-attempt-id={act.activeAttemptId}
                        data-action="continue"
                        style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                      >
                        <span>Tiếp tục xem câu {resumeIndex + 1} →</span>
                      </Link>
                    ) : (
                      <button
                        id={`practice-resume-${act.id}`}
                        type="button"
                        className="button primary"
                        data-practice-id={act.id}
                        data-action="resume"
                        onClick={() => handleStartOrRetry(act.id, 'resume')}
                        disabled={isPending}
                        style={{ fontSize: '13px' }}
                      >
                        Tiếp tục làm bài
                      </button>
                    )
                  ) : (
                    <button
                      type="button"
                      className="button outline"
                      data-practice-id={act.id}
                      data-action="start"
                      onClick={() => handleStartOrRetry(act.id, 'start')}
                      disabled={isPending}
                      style={{ fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                    >
                      <span>Bắt đầu luyện tập</span>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Accessible History Dialog / Drawer */}
      <Dialog
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Lịch sử luyện tập"
        className="history-dialog"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: '60vh', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              id="close-drawer-btn"
              type="button"
              className="button outline"
              onClick={() => setDrawerOpen(false)}
              style={{ fontSize: '12px', padding: '4px 10px' }}
              aria-label="Đóng lịch sử luyện tập"
            >
              Đóng lịch sử luyện tập
            </button>
          </div>

          {allHistory.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted, #64748b)', textAlign: 'center', margin: '20px 0' }}>
              Chưa có lượt làm bài nào trong lịch sử.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {allHistory.map((item, idx) => {
                return (
                  <div
                    key={item.attemptId || idx}
                    className="card"
                    data-attempt-id={item.attemptId}
                    data-practice-id={item.practiceId}
                    style={{
                      padding: '14px 16px',
                      borderRadius: '8px',
                      border: '1px solid var(--color-border, #e2e8f0)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <strong style={{ fontSize: '14px', color: '#0f172a' }}>{item.practiceTitle}</strong>
                      <span
                        style={{
                          fontSize: '12px',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          backgroundColor: '#f0fdf4',
                          color: '#16a34a',
                          fontWeight: 600,
                        }}
                      >
                        Lượt #{item.attemptNumber}
                      </span>
                    </div>

                    <p style={{ margin: '0 0 10px 0', fontSize: '12px', color: 'var(--color-text-muted, #64748b)' }}>
                      Hoàn thành: {item.completedAt} · Thời gian: {item.durationMinutes} phút
                    </p>

                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: '#16a34a' }}>
                        Điểm: {item.score.correct}/{item.score.total} ({item.score.percentage}%)
                      </span>
                      <Link
                        id={`history-result-${item.attemptId || idx}`}
                        href={item.resultHref}
                        className="button outline"
                        data-attempt-id={item.attemptId}
                        data-practice-id={item.practiceId}
                        data-action="view-history-detail"
                        onClick={() => setDrawerOpen(false)}
                        style={{ fontSize: '12px', padding: '4px 12px' }}
                      >
                        Xem chi tiết lượt làm
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '10px', borderTop: '1px solid var(--color-border, #e2e8f0)' }}>
            <button
              id="close-drawer-footer-btn"
              type="button"
              className="button outline"
              onClick={() => setDrawerOpen(false)}
              style={{ fontSize: '13px' }}
            >
              Đóng
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
