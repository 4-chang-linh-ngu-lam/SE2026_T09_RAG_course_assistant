'use client';
import Link from '@/components/available-link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { WorkspaceData } from '@/lib/domain';
import { StatePanel, Icon } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function ClassOverviewFeature({ route: _route, data, reload }: Props) {
  if (!data) {
    return <StatePanel busy title="Đang tải tổng quan lớp học…" />;
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
        title="Chưa có dữ liệu lớp học"
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
  const materials = overview?.recentMaterials ?? [];
  const activities = overview?.upcomingActivities ?? [];
  const classId = summary.id;
  const learningPending = data.pendingCapabilities?.includes('Learning') ?? false;
  const documentPending = data.pendingCapabilities?.includes('Document') ?? false;
  const tutorPending = data.pendingCapabilities?.includes('AI Tutor') ?? false;

  return (
    <div className="class-overview-container">
      {summary.teacherName && <p className="muted">Giáo viên chính: {summary.teacherName}</p>}

      <section className="overview-section">
        <div className="section-header">
          <div>
            <h2>Bảng tin lớp</h2>
            <p className="muted">Bài viết và trao đổi trong lớp</p>
          </div>
          <Link
            className="link-button text-sm"
            href={routeHref('s.feed', { classId }) ?? `/student/classes/${classId}/feed`}
          >
            Mở bảng tin <Icon name="chevronRight" />
          </Link>
        </div>

        {announcement ? (
          <article className="card announcement-hero-card">
            <div className="announcement-badge-row">
              <span className="tag primary">Bài viết mới nhất</span>
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
            <p className="muted">Lớp chưa có bài đăng nào. Bài viết mới sẽ xuất hiện tại đây.</p>
          </div>
        )}
      </section>

      <div className="overview-two-col">
        <section className="overview-col-main">
          <div className="section-header">
            <div>
              <h2>Hoạt động &amp; Bài tập sắp tới</h2>
              <p className="muted">Nhiệm vụ học tập cần chú ý trong lớp</p>
            </div>
          </div>

          <div className="activity-list">
            {learningPending ? (
              <div className="card empty-card" role="status">
                <p className="muted">Hoạt động và bài tập sẽ hiển thị tại đây khi dịch vụ học tập được kết nối.</p>
              </div>
            ) : activities.length === 0 ? (
              <div className="card empty-card">
                <p className="muted">Hiện tại lớp chưa có hoạt động hay bài tập nào mới.</p>
              </div>
            ) : (
              activities.map(act => (
                <article key={act.id} className={`card activity-item-card activity-type-${act.type.toLowerCase()}`}>
                  <div className="activity-item-main">
                    <div className="activity-header">
                      <span className={`tag ${act.type === 'EXAM' ? 'danger' : 'info'}`}>
                        {act.type === 'EXAM' ? 'Kiểm tra' : act.type === 'ASSIGNMENT' ? 'Bài tập' : 'Luyện tập'}
                      </span>
                      <span className="badge warning text-xs">{act.badgeLabel}</span>
                    </div>
                    <h4>{act.title}</h4>
                    <p className="muted text-sm">{act.dueDetail}</p>
                  </div>
                  <div className="activity-item-action">
                    <Link className="button primary small" href={act.href}>
                      {act.actionLabel}
                    </Link>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>

        <div className="overview-col-side">
          <section className="overview-section">
            <div className="section-header">
              <div>
                <h2>Tài liệu gần đây</h2>
                <p className="muted">Bài giảng và tài liệu học tập</p>
              </div>
              {!documentPending && (
                <Link
                  className="link-button text-sm"
                  href={routeHref('s.documents', { classId }) ?? `/student/classes/${classId}/documents`}
                >
                  Xem tất cả
                </Link>
              )}
            </div>

            <div className="materials-list">
              {documentPending ? (
                <div className="card empty-card" role="status">
                  <p className="muted">Tài liệu lớp sẽ hiển thị tại đây khi dịch vụ tài liệu được kết nối.</p>
                </div>
              ) : materials.length === 0 ? (
                <div className="card empty-card">
                  <p className="muted">Chưa có tài liệu nào được đăng tải.</p>
                </div>
              ) : (
                materials.map(mat => (
                  <article key={mat.id} className="card material-item-card">
                    <div className="material-icon-wrapper">
                      <span className={`format-tag ${mat.format.toLowerCase()}`}>
                        {mat.format}
                      </span>
                    </div>
                    <div className="material-info">
                      <h4>
                        <Link href={mat.href}>{mat.title}</Link>
                      </h4>
                      <p className="muted text-xs">{mat.detail}</p>
                    </div>
                    <Link className="button secondary small" href={mat.href}>
                      Đọc
                    </Link>
                  </article>
                ))
              )}
            </div>
          </section>

          <section className="overview-section">
            <article className="card lumi-tutor-box">
              <div className="lumi-box-header">
                <span className="lumi-badge">✨ Hỏi Lumi trong lớp này</span>
                <p className="muted text-sm">
                  Lumi trả lời dựa trên tài liệu và bài giảng của giáo viên lớp {summary.name}
                </p>
              </div>
              {tutorPending ? (
                <p className="notice" role="status">Chức năng hỏi Lumi sẽ hiển thị tại đây khi dịch vụ Gia sư AI được kết nối.</p>
              ) : (
                <Link
                  className="button primary full-width"
                  href={routeHref('s.tutor', { classId }) ?? `/student/classes/${classId}/tutor`}
                >
                  Đặt câu hỏi cho Lumi <Icon name="chevronRight" />
                </Link>
              )}
            </article>
          </section>
        </div>
      </div>
    </div>
  );
}
