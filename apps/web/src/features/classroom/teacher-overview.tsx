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

export function TeacherOverviewFeature({ route: _route, data, reload }: Props) {
  if (!data) {
    return <StatePanel busy title="Đang tải tổng quan lớp học…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel
        title="Dịch vụ giảng dạy trực tiếp chưa sẵn sàng"
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
        title="Chưa có dữ liệu tổng quan lớp"
        message={data.message}
      />
    );
  }

  const overview = data.classOverview;
  const summary = overview?.summary ?? data.classSummary;
  if (!summary?.id) {
    return (
      <StatePanel
        title="Không tìm thấy thông tin lớp học"
        message="Vui lòng kiểm tra lại đường dẫn hoặc chọn lớp học từ danh sách."
      />
    );
  }
  const announcement = overview?.announcement;
  const activities = overview?.upcomingActivities ?? [];
  const classId = summary.id;

  return (
    <div className="teacher-overview-container">
      {/* Quick Action Toolbar */}
      <section className="card teacher-quick-actions-bar">
        <div className="quick-actions-info">
          <h3>Thao tác nhanh cho lớp {summary?.name ?? ''}</h3>
          <p className="muted text-sm">Quản lý hoạt động học tập, tài liệu và tương tác với học sinh</p>
        </div>
        <div className="quick-actions-buttons">
          <Link
            className="button primary"
            href={routeHref('t.activities', { classId }) ?? `/teacher/classes/${classId}/activities`}
          >
            <Icon name="plus" /> Tạo hoạt động
          </Link>
          <Link
            className="button secondary"
            href={routeHref('t.feed', { classId }) ?? `/teacher/classes/${classId}/feed`}
          >
            <Icon name="send" /> Đăng bảng tin
          </Link>
          <Link
            className="button secondary"
            href={routeHref('t.documents', { classId }) ?? `/teacher/classes/${classId}/documents`}
          >
            <Icon name="file" /> Thêm tài liệu
          </Link>
        </div>
      </section>

      {/* Class Metrics */}
      <section className="class-metrics-grid">
        <div className="card metric-card">
          <span className="muted text-sm">Sĩ số lớp</span>
          <div className="metric-number">{summary?.studentCount ?? '—'}</div>
          <span className="muted text-xs">Học sinh chính thức</span>
        </div>
        <div className="card metric-card">
          <span className="muted text-sm">Bài nộp đang chờ</span>
          <div className="metric-number text-primary">{data.teacherMetrics?.pendingGrading ?? '—'}</div>
          <span className="muted text-xs">Cần chấm hoặc phản hồi</span>
        </div>
        <div className="card metric-card">
          <span className="muted text-sm">Hoạt động đang mở</span>
          <div className="metric-number">{data.teacherMetrics?.openActivities ?? '—'}</div>
          <span className="muted text-xs">Luyện tập & Kiểm tra</span>
        </div>
      </section>

      {/* Two Column: Announcements & Activities */}
      <div className="overview-two-col">
        {/* Latest Announcement */}
        <section className="overview-col-main">
          <div className="section-header">
            <div>
              <h2>Bảng tin & Thông báo lớp</h2>
              <p className="muted">Nội dung đã gửi cho học sinh trong lớp</p>
            </div>
            <Link
              className="link-button text-sm"
              href={routeHref('t.feed', { classId }) ?? `/teacher/classes/${classId}/feed`}
            >
              Mở bảng tin <Icon name="chevronRight" />
            </Link>
          </div>

          {announcement ? (
            <article className="card announcement-hero-card">
              <div className="announcement-badge-row">
                <span className="tag primary">Thông báo đã đăng</span>
                <span className="muted text-sm">{announcement.timeAgo}</span>
              </div>
              <div className="announcement-author-row">
                <div className="avatar-circle">{announcement.authorInitials}</div>
                <div>
                  <strong>{announcement.authorName}</strong>
                  <p className="muted text-xs">{announcement.authorRole}</p>
                </div>
              </div>
              <div className="announcement-body">
                <h3>{announcement.title}</h3>
                <p className="announcement-text">{announcement.content}</p>
                {announcement.deadlineNotice && (
                  <div className="notice-box info">
                    <Icon name="clock" />
                    <span>{announcement.deadlineNotice}</span>
                  </div>
                )}
              </div>
            </article>
          ) : (
            <div className="card empty-card">
              <p className="muted">Chưa có thông báo nào được đăng gần đây.</p>
              <Link
                className="button secondary small"
                href={routeHref('t.feed', { classId }) ?? `/teacher/classes/${classId}/feed`}
              >
                Đăng thông báo mới
              </Link>
            </div>
          )}
        </section>

        {/* Activities List */}
        <div className="overview-col-side">
          <section className="overview-section">
            <div className="section-header">
              <div>
                <h2>Hoạt động học tập</h2>
                <p className="muted">Bài tập và kiểm tra</p>
              </div>
              <Link
                className="link-button text-sm"
                href={routeHref('t.activities', { classId }) ?? `/teacher/classes/${classId}/activities`}
              >
                Quản lý
              </Link>
            </div>

            <div className="activity-list">
              {activities.length === 0 ? (
                <div className="card empty-card">
                  <p className="muted">Chưa có hoạt động nào trong lớp này.</p>
                </div>
              ) : (
                activities.map(act => (
                  <article key={act.id} className="card activity-item-card">
                    <div className="activity-item-main">
                      <div className="activity-header">
                        <span className={`tag ${act.type === 'EXAM' ? 'danger' : 'info'}`}>
                          {act.type === 'EXAM' ? 'Kiểm tra' : act.type === 'ASSIGNMENT' ? 'Bài tập' : 'Luyện tập'}
                        </span>
                        <span className="badge warning text-xs">{act.badgeLabel}</span>
                      </div>
                      <h4>{act.title}</h4>
                      <p className="muted text-xs">{act.dueDetail}</p>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
