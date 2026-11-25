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
    <div className="practice-hub-content">
      {/* Action / History bar */}
      <div className="practice-hub-bar">
        <p className="practice-hub-lead">
          Ôn luyện kiến thức trọng tâm với phản hồi tức thời từ trợ lý học tập Lumi.
        </p>
        <button
          id="open-drawer-btn"
          type="button"
          className="button outline practice-history-btn"
          onClick={() => setDrawerOpen(true)}
        >
          <Icon name="clock" />
          <span>Lịch sử luyện tập: {totalHistoryCount} lượt đã hoàn thành</span>
        </button>
      </div>

      {actionError && (
        <div className="practice-error-banner">
          {actionError}
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="card practice-filters">
        <div className="practice-search-wrap">
          <input
            id="practice-search"
            type="search"
            aria-label="Tìm kiếm bài luyện tập"
            className="input"
            placeholder="Tìm bài luyện tập theo tên, chuyên đề..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="practice-status-wrap">
          <label htmlFor="status-filter" className="practice-status-label">
            Trạng thái:
          </label>
          <select
            id="status-filter"
            className="input practice-status-select"
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as 'all' | 'not_started' | 'in_progress' | 'completed')}
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
        <div className="card practice-empty-card">
          <p className="practice-hub-lead">
            Không có bài luyện tập nào phù hợp với bộ lọc hiện tại.
          </p>
        </div>
      ) : (
        <div className="practice-list-stack">
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
                className={`card activity-row ${isInProgress ? 'is-in-progress' : ''}`}
                data-practice-id={act.id}
              >
                {/* Left section: Icon badge & details */}
                <div className="practice-row-main">
                  <div
                    className={`practice-row-icon ${isCompleted ? 'is-completed' : isInProgress ? 'is-in-progress' : ''}`}
                    aria-hidden="true"
                  >
                    <Icon name={isCompleted ? 'check' : isInProgress ? 'edit' : 'clipboard'} />
                  </div>

                  <div className="practice-row-body">
                    <div className="practice-row-meta">
                      <span
                        className={`practice-status-pill ${isCompleted ? 'is-completed' : isInProgress ? 'is-in-progress' : ''}`}
                      >
                        {isCompleted ? 'Đã hoàn thành' : isInProgress ? 'Đang làm' : 'Chưa bắt đầu'}
                      </span>
                      <span>
                        {act.questionCount} câu hỏi
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        Chủ đề: {act.topic}
                      </span>
                    </div>

                    <h3 className="practice-row-title">
                      {act.title}
                    </h3>

                    {isCompleted && act.lastScore && (
                      <div className="practice-row-score">
                        Điểm gần nhất: <strong>{act.lastScore.correct}/{act.lastScore.total} ({act.lastScore.percentage}%)</strong>
                        {act.lastCompletedAt && (
                          <span className="practice-row-date">
                            Hoàn thành: {act.lastCompletedAt}
                          </span>
                        )}
                      </div>
                    )}

                    {isInProgress && (
                      <div className="practice-row-progress">
                        Đang làm: Câu {resumeIndex + 1} / {targetQuestionCount}
                      </div>
                    )}
                  </div>
                </div>

                {/* Right section: Action buttons */}
                <div className="practice-row-actions">
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
        <div className="history-dialog-body">
          <div className="history-dialog-top">
            <button
              id="close-drawer-btn"
              type="button"
              className="button outline"
              onClick={() => setDrawerOpen(false)}
              aria-label="Đóng lịch sử luyện tập"
            >
              Đóng lịch sử luyện tập
            </button>
          </div>

          {allHistory.length === 0 ? (
            <p className="history-dialog-empty">
              Chưa có lượt làm bài nào trong lịch sử.
            </p>
          ) : (
            <div className="history-dialog-list">
              {allHistory.map((item, idx) => {
                return (
                  <div
                    key={item.attemptId || idx}
                    className="card history-item-card"
                    data-attempt-id={item.attemptId}
                    data-practice-id={item.practiceId}
                  >
                    <div className="history-item-head">
                      <strong>{item.practiceTitle}</strong>
                      <span className="history-attempt-badge">
                        Lượt #{item.attemptNumber}
                      </span>
                    </div>

                    <p className="history-item-meta">
                      Hoàn thành: {item.completedAt} · Thời gian: {item.durationMinutes} phút
                    </p>

                    <div className="history-item-foot">
                      <span className="history-item-score">
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
                      >
                        Xem chi tiết lượt làm
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="history-dialog-footer">
            <button
              id="close-drawer-footer-btn"
              type="button"
              className="button outline"
              onClick={() => setDrawerOpen(false)}
            >
              Đóng
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
