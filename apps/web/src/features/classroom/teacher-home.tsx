'use client';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { WorkspaceData } from '@/lib/domain';
import { StatePanel, Icon } from '@/components/ui';
import { operationalTeachingOverview, teachingWorkload } from '@/lib/classroom-presentation';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherHomeFeature({ route: _route, data, reload }: Props) {
  if (!data) {
    return <StatePanel busy title="Đang tải dữ liệu giảng dạy…" />;
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
        title="Chưa có dữ liệu giảng dạy"
        message={data.message}
      />
    );
  }

  const overview = data.teacherHome;
  const assignedClasses = overview?.assignedClasses ?? data.classes ?? [];
  const { schedule, discussions } = operationalTeachingOverview(assignedClasses, overview);
  const stats = teachingWorkload(assignedClasses, overview?.stats);

  return (
    <div className="teacher-home-container">
      {/* Top Workload Metrics */}
      <section className="workload-stats-grid">
        <div className="card stat-card">
          <span className="stat-label muted text-sm">Lớp phụ trách</span>
          <div className="stat-value">{stats.totalClasses}</div>
          <span className="muted text-xs">{overview?.termLabel ?? 'Học kỳ hiện tại'}</span>
        </div>
        <div className="card stat-card">
          <span className="stat-label muted text-sm">Tổng số học sinh</span>
          <div className="stat-value">{stats.totalStudents ?? <span className="muted text-sm">Chưa có dữ liệu</span>}</div>
          <span className="muted text-xs">Phân bổ qua các lớp</span>
        </div>
        <div className="card stat-card highlight">
          <span className="stat-label muted text-sm">Bài nộp chờ chấm</span>
          <div className="stat-value text-primary">{stats.pendingGrading ?? <span className="muted text-sm">Chưa có dữ liệu</span>}</div>
          <span className="muted text-xs">Cần phản hồi hoặc duyệt</span>
        </div>
      </section>

      {/* Assigned Classes Section */}
      <section className="teacher-section">
        <div className="section-header">
          <div>
            <h2>Lớp phụ trách</h2>
            <p className="muted">Danh sách các lớp bạn được phân công làm giáo viên chính hoặc phối hợp</p>
          </div>
          <Link className="button secondary" href="/teacher/classes">
            Xem tất cả lớp ({assignedClasses.length})
          </Link>
        </div>

        {assignedClasses.length === 0 ? (
          <div className="card empty-card">
            <p className="muted">Bạn chưa được phân công phụ trách lớp học nào.</p>
          </div>
        ) : (
          <div className="class-grid">
            {assignedClasses.map(cls => {
              const isPrimary = cls.teachingRole === 'PRIMARY';
              return (
                <article key={cls.id} className="card class-card teacher-class-card">
                  <div className="class-card-top" style={{ flexWrap: 'wrap', gap: '8px' }}>
                    {cls.code && <span className="tag primary">{cls.code}</span>}
                    <span className={`badge ${isPrimary ? 'primary' : 'secondary'}`}>
                      {cls.teachingRole ? (isPrimary ? 'Giáo viên chính' : 'Giáo viên phối hợp') : 'Được phân công'}
                    </span>
                  {cls.status === 'ARCHIVED' && <span className="badge warning">Đã lưu trữ</span>}
                  </div>

                  <h3>{cls.name}</h3>

                  <div className="class-card-info">
                    <p className="muted text-sm">{cls.metadata}</p>
                    {typeof cls.studentCount === 'number' && (
                      <p className="muted text-xs">Sĩ số: {cls.studentCount} học sinh</p>
                    )}
                  </div>

                  <div className="class-card-actions">
                    <Link
                      className="button primary"
                      href={routeHref(cls.status === 'ARCHIVED' ? 't.gradingQueue' : 't.overview', { classId: cls.id }) ?? '/teacher/classes'}
                    >
                      {cls.status === 'ARCHIVED' ? 'Xem bài đã nộp' : 'Vào lớp'} <Icon name="chevronRight" />
                    </Link>
                    {cls.status === 'ACTIVE' && (<>
                  <Link
                      className="button secondary"
                      href={routeHref('t.feed', { classId: cls.id }) ?? `/teacher/classes/${cls.id}/feed`}
                    >
                      Bảng tin
                    </Link>
                  </>)}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* Two Column Layout: Today's Schedule & Recent Discussions */}
      <div className="teacher-two-col">
        {/* Today's Teaching Schedule */}
        <section className="teacher-section">
          <div className="section-header">
            <div>
              <h2>Lịch dạy & Hoạt động hôm nay</h2>
              <p className="muted">Tiết dạy và hạn bài tập trong ngày</p>
            </div>
            <Link className="link-button" href="/calendar">
              Mở lịch đầy đủ <Icon name="chevronRight" />
            </Link>
          </div>

          <div className="schedule-list">
            {schedule.length === 0 ? (
              <div className="card empty-card">
                <p className="muted">Hôm nay không có tiết dạy hoặc lịch sự kiện nào.</p>
              </div>
            ) : (
              schedule.map(ev => (
                <article key={ev.id} className="card schedule-item-card">
                  <div className="schedule-time-badge">
                    <Icon name="clock" />
                    <span>{ev.timeRange ?? ev.start}</span>
                  </div>
                  <div className="schedule-content">
                    <h4>{ev.title}</h4>
                    <p className="muted text-sm">
                      {ev.className} {ev.location ? `· ${ev.location}` : ''}
                    </p>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>

        {/* Recent Student Discussions */}
        <section className="teacher-section">
          <div className="section-header">
            <div>
              <h2>Bài viết gần đây trong lớp</h2>
              <p className="muted">Bài viết mới trong các lớp đang được phân công</p>
            </div>
          </div>

          <div className="discussion-list">
            {discussions.length === 0 ? (
              <div className="card empty-card">
                <p className="muted">Chưa có bài viết gần đây trong các lớp đang phụ trách.</p>
              </div>
            ) : (
              discussions.map(disc => (
                <article key={disc.id} className="card discussion-item-card">
                  <div className="disc-header">
                    <strong>{disc.studentName}</strong>
                    <span className="tag secondary small">{disc.className}</span>
                    <span className="muted text-xs">{disc.createdAt}</span>
                  </div>
                  <p className="disc-content text-sm">{disc.content}</p>
                  <div className="disc-action">
                    <Link
                      className="link-button text-sm"
                      href={routeHref('t.feed', { classId: disc.classId }) ?? `/teacher/classes/${disc.classId}/feed`}
                    >
                      Mở bảng tin <Icon name="chevronRight" />
                    </Link>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
