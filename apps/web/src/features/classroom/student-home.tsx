'use client';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { WorkspaceData } from '@/lib/domain';
import { StatePanel, Icon } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function StudentHomeFeature({ route: _route, data, reload }: Props) {
  if (!data) {
    return <StatePanel busy title="Đang tải dữ liệu trang chủ…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel
        title="Dịch vụ lớp học trực tiếp chưa sẵn sàng"
        message={data.message}
      >
        <button className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return (
      <StatePanel
        title="Chưa có dữ liệu học tập"
        message={data.message}
      />
    );
  }

  const overview = data.studentHome;
  const activeClasses = overview?.activeClasses ?? data.classes ?? [];
  const upcomingTasks = overview?.upcomingTasks ?? [];
  const recentStudies = overview?.recentStudies ?? [];
  const tutorSuggestions = overview?.tutorSuggestions ?? [];

  return (
    <div className="student-home-container">
      {/* Active Classes Grid */}
      <section className="home-section">
        <div className="section-header">
          <div>
            <h2>Lớp học của tôi</h2>
            <p className="muted">Các lớp học bạn đang tham gia trong học kỳ này</p>
          </div>
          <Link className="button secondary" href="/student/classes">
            Xem tất cả lớp ({activeClasses.length})
          </Link>
        </div>

        {activeClasses.length === 0 ? (
          <div className="card empty-card">
            <p className="muted">Bạn chưa tham gia lớp học nào.</p>
          </div>
        ) : (
          <div className="class-grid">
            {activeClasses.map(cls => (
              <article key={cls.id} className="card class-card student-class-card">
                <div className="class-card-top">
                  {cls.code && <span className="tag primary">{cls.code}</span>}
                  {typeof cls.studentCount === 'number' && (
                    <span className="muted small">{cls.studentCount} học sinh</span>
                  )}
                </div>
                <h3>{cls.name}</h3>
                <p className="muted text-sm">{cls.teacherName ?? cls.metadata}</p>
                <div className="class-card-actions">
                  <Link
                    className="button primary"
                    href={routeHref('s.overview', { classId: cls.id }) ?? `/student/classes/${cls.id}/overview`}
                  >
                    Vào lớp <Icon name="chevronRight" />
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Two Column Layout: Upcoming Tasks & Recent Studies */}
      <div className="home-two-col">
        {/* Upcoming Tasks */}
        <section className="home-section">
          <div className="section-header">
            <div>
              <h2>Nhiệm vụ sắp tới</h2>
              <p className="muted">Bài tập và lịch kiểm tra cần lưu ý</p>
            </div>
            <Link className="link-button" href="/calendar">
              Mở lịch <Icon name="chevronRight" />
            </Link>
          </div>

          <div className="task-list">
            {upcomingTasks.length === 0 ? (
              <div className="card empty-card">
                <p className="muted">{data.pendingCapabilities?.includes('Learning') ? 'Bài tập và kết quả sẽ xuất hiện khi dịch vụ học tập được kết nối.' : 'Không có nhiệm vụ nào cần hoàn thành ngay.'}</p>
              </div>
            ) : (
              upcomingTasks.map(task => (
                <article key={task.id} className="card task-item-card">
                  <div className="task-item-main">
                    <div className="task-item-header">
                      <span className={`tag ${task.type === 'EXAM' ? 'danger' : 'info'}`}>
                        {task.type === 'EXAM' ? 'Kiểm tra' : task.type === 'ASSIGNMENT' ? 'Bài tập' : 'Tài liệu'}
                      </span>
                      <span className="days-left-badge">{task.daysLeftLabel}</span>
                    </div>
                    <h4>{task.title}</h4>
                    <p className="muted text-sm">{task.className} · {task.dueDetail}</p>
                  </div>
                  <div className="task-item-action">
                    <Link className="button secondary small" href={task.href}>
                      {task.actionLabel}
                    </Link>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>

        {/* Recent Studies & Tutor Widget */}
        <div className="home-side-col">
          {/* Recent Studies */}
          <section className="home-section">
            <div className="section-header">
              <div>
                <h2>Tiến độ học tập gần đây</h2>
                <p className="muted">Tài liệu và nội dung đang học</p>
              </div>
            </div>

            <div className="study-list">
              {recentStudies.length === 0 ? (
                <div className="card empty-card">
                  <p className="muted">{data.pendingCapabilities?.includes('Learning') ? 'Tiến độ học tập chưa được kết nối với dịch vụ Learning.' : 'Chưa có hoạt động học tập nào được ghi nhận.'}</p>
                </div>
              ) : (
                recentStudies.map(study => (
                  <article key={study.id} className="card study-item-card">
                    <div className="study-item-info">
                      <h4>{study.title}</h4>
                      <p className="muted text-sm">{study.className}</p>
                    </div>
                    <div className="progress-bar-container">
                      <div className="progress-bar-track">
                        <div
                          className="progress-bar-fill"
                          style={{ width: `${study.progressPercent}%` }}
                        />
                      </div>
                      <span className="progress-bar-text">{study.progressText}</span>
                    </div>
                    {study.extraNote && (
                      <p className="muted text-xs">{study.extraNote}</p>
                    )}
                    <Link className="link-button text-sm" href={study.href}>
                      {study.actionLabel} →
                    </Link>
                  </article>
                ))
              )}
            </div>
          </section>

          {/* Lumi Tutor Quick Assistant */}
          <section className="home-section">
            <article className="card lumi-assistant-card">
              <div className="lumi-card-header">
                <span className="lumi-badge">✨ Trợ lý Lumi</span>
                <p className="muted text-sm">Gợi ý câu hỏi học tập nhanh cho bạn</p>
              </div>
              <ul className="tutor-suggestion-list">
                {tutorSuggestions.map((item, idx) => {
                  if (!item.classId) return null;
                  return (
                    <li key={idx}>
                      <Link
                        className="tutor-suggestion-pill"
                        href={routeHref('s.tutor', { classId: item.classId }) ?? `/student/classes/${item.classId}/tutor`}
                      >
                        <Icon name="message" />
                        <span>{item.prompt}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </article>
          </section>
        </div>
      </div>
    </div>
  );
}
