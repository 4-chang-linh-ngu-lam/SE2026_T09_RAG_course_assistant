'use client';

import './navigation-feedback.css';

export type ClassHeaderPlaceholderProps = {
  role: 'STUDENT' | 'LECTURER' | 'ADMIN';
  className?: string;
};

const ROLE_TAB_WIDTHS: Record<'STUDENT' | 'LECTURER' | 'ADMIN', readonly number[]> = {
  STUDENT: [64, 56, 50, 58, 64, 56, 50, 54, 50],
  LECTURER: [64, 56, 50, 58, 112, 54, 60],
  ADMIN: [],
};

export function ClassHeaderPlaceholder({ role, className }: ClassHeaderPlaceholderProps) {
  const tabWidths = ROLE_TAB_WIDTHS[role] ?? [];
  const combinedClassName = className
    ? `class-header lumi-class-placeholder ${className}`
    : 'class-header lumi-class-placeholder';

  return (
    <header className={combinedClassName} aria-busy="true">
      <span className="sr-only" role="status">
        Đang tải thông tin lớp học...
      </span>

      <div className="class-summary lumi-class-placeholder__summary" aria-hidden="true">
        <span className="lumi-class-placeholder__badge lumi-class-placeholder__badge--code" />
        <span className="lumi-class-placeholder__badge lumi-class-placeholder__badge--status" />
        <span className="lumi-class-placeholder__text lumi-class-placeholder__text--name" />
        <span className="lumi-class-placeholder__text lumi-class-placeholder__text--meta" />
      </div>

      {tabWidths.length > 0 && (
        <div className="class-tabs lumi-class-placeholder__tabs" aria-hidden="true">
          {tabWidths.map((width, index) => (
            <div key={index} className="lumi-class-placeholder__tab">
              <span className="lumi-class-placeholder__tab-icon" />
              <span
                className="lumi-class-placeholder__tab-label"
                style={{ width: `${width}px` }}
              />
            </div>
          ))}
        </div>
      )}
    </header>
  );
}

export default ClassHeaderPlaceholder;
