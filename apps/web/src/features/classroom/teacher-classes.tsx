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

type RoleFilter = 'all' | 'primary' | 'assisting';

export function TeacherClassesFeature({ route: _route, data, reload }: Props) {
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const allClasses = data && data.kind === 'ready' ? data.classes ?? data.teacherHome?.assignedClasses ?? [] : [];

  const filteredClasses = useMemo(() => {
    return allClasses.filter(cls => {
      if (roleFilter === 'primary' && cls.teachingRole !== 'PRIMARY') return false;
      if (roleFilter === 'assisting' && cls.teachingRole !== 'ASSISTING') return false;

      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        cls.name.toLowerCase().includes(q) ||
        cls.code.toLowerCase().includes(q) ||
        cls.metadata.toLowerCase().includes(q)
      );
    });
  }, [allClasses, roleFilter, searchQuery]);

  const primaryCount = useMemo(() => {
    return allClasses.filter(c => c.teachingRole === 'PRIMARY').length;
  }, [allClasses]);

  const assistingCount = useMemo(() => {
    return allClasses.filter(c => c.teachingRole === 'ASSISTING').length;
  }, [allClasses]);

  if (!data) {
    return <StatePanel busy title="Đang tải danh sách lớp phụ trách…" />;
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
        title="Chưa có lớp học phụ trách"
        message={data.message}
      />
    );
  }

  return (
    <div className="teacher-classes-container">
      {/* Toolbar: Role Filter Tabs and Search */}
      <div className="classes-toolbar card">
        <div className="tab-group" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={roleFilter === 'all'}
            className={`tab-btn ${roleFilter === 'all' ? 'active' : ''}`}
            onClick={() => setRoleFilter('all')}
          >
            Tất cả ({allClasses.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={roleFilter === 'primary'}
            className={`tab-btn ${roleFilter === 'primary' ? 'active' : ''}`}
            onClick={() => setRoleFilter('primary')}
          >
            Giáo viên chính ({primaryCount})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={roleFilter === 'assisting'}
            className={`tab-btn ${roleFilter === 'assisting' ? 'active' : ''}`}
            onClick={() => setRoleFilter('assisting')}
          >
            Giáo viên phối hợp ({assistingCount})
          </button>
        </div>

        <div className="classes-search-wrapper">
          <input
            type="search"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Tìm theo mã lớp hoặc tên môn..."
            className="input classes-search-input"
            aria-label="Tìm kiếm lớp học"
          />
        </div>
      </div>

      {/* Class Cards Grid */}
      {filteredClasses.length === 0 ? (
        <div className="card empty-panel">
          <p className="muted">
            {searchQuery.trim()
              ? `Không tìm thấy lớp học nào với từ khóa "${searchQuery}".`
              : 'Chưa có lớp học nào phù hợp với bộ lọc hiện tại.'}
          </p>
          {searchQuery.trim() && (
            <button
              className="button secondary small"
              onClick={() => setSearchQuery('')}
            >
              Xóa bộ lọc
            </button>
          )}
        </div>
      ) : (
        <div className="class-grid">
          {filteredClasses.map(cls => {
            const isPrimary = cls.teachingRole === 'PRIMARY';
            return (
              <article key={cls.id} className="card class-card teacher-class-card">
                <div className="class-card-top">
                  <span className="tag primary">{cls.code}</span>
                  <span className={`badge ${isPrimary ? 'primary' : 'secondary'}`}>
                    {isPrimary ? 'Giáo viên chính' : 'Giáo viên phối hợp'}
                  </span>
                </div>

                <h3>{cls.name}</h3>

                <div className="class-card-info">
                  <p className="muted text-sm">{cls.metadata}</p>
                  {cls.studentCount && (
                    <p className="muted text-xs">Sĩ số: {cls.studentCount} học sinh</p>
                  )}
                </div>

                <div className="class-card-actions">
                  <Link
                    className="button primary"
                    href={routeHref('t.overview', { classId: cls.id }) ?? `/teacher/classes/${cls.id}/overview`}
                  >
                    Tổng quan <Icon name="chevronRight" />
                  </Link>
                  <Link
                    className="button secondary"
                    href={routeHref('t.feed', { classId: cls.id }) ?? `/teacher/classes/${cls.id}/feed`}
                  >
                    Bảng tin
                  </Link>
                  <Link
                    className="button secondary"
                    href={routeHref('t.calendar', { classId: cls.id }) ?? `/teacher/classes/${cls.id}/calendar`}
                  >
                    Lịch
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
