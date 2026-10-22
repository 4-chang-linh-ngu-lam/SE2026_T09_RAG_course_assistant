'use client';
import { useState, useMemo } from 'react';
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

type Tab = 'active' | 'archived';

export function StudentClassesFeature({ route: _route, data, reload }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('active');
  const [searchQuery, setSearchQuery] = useState('');

  const allClasses = data && data.kind === 'ready' ? data.classes ?? [] : [];

  const filteredClasses = useMemo(() => {
    return allClasses.filter(cls => {
      const isHistorical = cls.status === 'ARCHIVED' || cls.membershipStatus === 'ENDED';
      const matchesTab = activeTab === 'active' ? !isHistorical : isHistorical;

      if (!matchesTab) return false;

      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        cls.name.toLowerCase().includes(q) ||
        cls.code.toLowerCase().includes(q) ||
        (cls.teacherName && cls.teacherName.toLowerCase().includes(q))
      );
    });
  }, [allClasses, activeTab, searchQuery]);

  const activeCount = useMemo(() => {
    return allClasses.filter(c => c.status !== 'ARCHIVED' && c.membershipStatus !== 'ENDED').length;
  }, [allClasses]);

  const archivedCount = useMemo(() => {
    return allClasses.filter(c => c.status === 'ARCHIVED' || c.membershipStatus === 'ENDED').length;
  }, [allClasses]);

  if (!data) {
    return <StatePanel busy title="Đang tải danh sách lớp học…" />;
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
        title="Chưa có lớp học nào"
        message={data.message}
      />
    );
  }

  return (
    <div className="student-classes-container">
      {/* Search and Tabs Controls */}
      <div className="classes-toolbar card">
        <div className="tab-group" role="group" aria-label="Bộ lọc trạng thái lớp học">
          <button
            type="button"
            aria-pressed={activeTab === 'active'}
            className={`tab-btn ${activeTab === 'active' ? 'active' : ''}`}
            onClick={() => setActiveTab('active')}
          >
            Đang học ({activeCount})
          </button>
          <button
            type="button"
            aria-pressed={activeTab === 'archived'}
            className={`tab-btn ${activeTab === 'archived' ? 'active' : ''}`}
            onClick={() => setActiveTab('archived')}
          >
            Đã lưu trữ / Đã học ({archivedCount})
          </button>
        </div>

        <div className="classes-search-wrapper">
          <input
            type="search"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Tìm theo mã lớp, môn học, giáo viên..."
            className="input classes-search-input"
            aria-label="Tìm kiếm lớp học"
          />
        </div>
      </div>

      {/* Class List / Grid */}
      {filteredClasses.length === 0 ? (
        <div className="card empty-panel">
          <p className="muted">
            {searchQuery.trim()
              ? `Không tìm thấy lớp học nào phù hợp với từ khóa "${searchQuery}".`
              : activeTab === 'active'
              ? 'Hiện bạn chưa có lớp học nào đang hoạt động.'
              : 'Chưa có lớp học nào trong danh sách lưu trữ.'}
          </p>
          {searchQuery.trim() && (
            <button
              className="button secondary small"
              onClick={() => setSearchQuery('')}
            >
              Xóa bộ lọc tìm kiếm
            </button>
          )}
        </div>
      ) : (
        <div className="class-grid">
          {filteredClasses.map(cls => {
            const isHistorical = cls.status === 'ARCHIVED' || cls.membershipStatus === 'ENDED';
            const destinationHref = isHistorical
              ? routeHref('s.history', { classId: cls.id }) ?? `/student/history/classes/${cls.id}`
              : routeHref('s.overview', { classId: cls.id }) ?? `/student/classes/${cls.id}/overview`;

            return (
              <article key={cls.id} className="card class-card student-class-card">
                <div className="class-card-top">
                  <span className={`tag ${isHistorical ? 'default' : 'primary'}`}>
                    {cls.code}
                  </span>
                  {cls.membershipStatus === 'ENDED' ? (
                    <span className="badge warning">Đã kết thúc ghi danh</span>
                  ) : cls.status === 'ARCHIVED' ? (
                    <span className="badge warning">Lưu trữ</span>
                  ) : (
                    typeof cls.studentCount === 'number' && (
                      <span className="muted small">{cls.studentCount} học sinh</span>
                    )
                  )}
                </div>

                <h3>{cls.name}</h3>

                <div className="class-card-info">
                  <p className="teacher-name">
                    <Icon name="user" /> {cls.teacherName ?? 'Giáo viên phụ trách'}
                  </p>
                  <p className="muted text-sm">{cls.metadata}</p>
                </div>

                <div className="class-card-actions">
                  <Link
                    className={`button ${isHistorical ? 'secondary' : 'primary'}`}
                    href={destinationHref}
                  >
                    {isHistorical ? 'Xem lịch sử lớp' : 'Vào lớp'} <Icon name="chevronRight" />
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
