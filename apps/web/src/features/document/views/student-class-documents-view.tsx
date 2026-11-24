'use client';
import { useState, useMemo, useTransition } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { DocumentItem, RouteParams, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  params: RouteParams;
  reload(): void;
};

export function StudentClassDocumentsView({ data, params, reload }: Props) {
  const [search, setSearch] = useState('');
  const [formatFilter, setFormatFilter] = useState('all');
  const [sortFilter, setSortFilter] = useState<'newest' | 'oldest' | 'name'>('newest');
  const [actionError, setActionError] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const rawDocs = data && data.kind === 'ready' ? data.classDocuments ?? [] : [];

  const filteredDocs = useMemo(() => {
    let list = rawDocs.filter(d => {
      if (formatFilter !== 'all' && d.format.toLowerCase() !== formatFilter.toLowerCase()) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return d.title.toLowerCase().includes(q) || (d.description && d.description.toLowerCase().includes(q));
      }
      return true;
    });

    if (sortFilter === 'newest') {
      list.sort((a, b) => (b.updatedAt > a.updatedAt ? 1 : -1));
    } else if (sortFilter === 'oldest') {
      list.sort((a, b) => (a.updatedAt > b.updatedAt ? 1 : -1));
    } else if (sortFilter === 'name') {
      list.sort((a, b) => a.title.localeCompare(b.title));
    }
    return list;
  }, [rawDocs, formatFilter, search, sortFilter]);

  if (!data) {
    return <StatePanel busy title="Đang tải danh sách tài liệu học tập…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ tài liệu học tập chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return <StatePanel title="Chưa có tài liệu nào" message={data.message} />;
  }

  const classSummary = data.classSummary;

  const handleToggleBookmark = (docId: string) => {
    if (!params.classId) return;
    setActionError(null);
    startTransition(async () => {
      try {
        await adapter.document.toggleBookmark(docId, params.classId);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Không thể lưu dấu trang.');
      }
    });
  };

  return (
    <div className="student-docs-container">
      {/* Header and Toolbar */}
      <div className="card student-docs-toolbar">
        <div className="student-docs-filters">
          <input
            id="docSearchInput"
            type="search"
            aria-label="Tìm kiếm tài liệu học tập"
            className="input student-docs-search"
            placeholder="Tìm kiếm tài liệu học tập..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          <select
            id="formatFilter"
            className="input student-docs-select"
            value={formatFilter}
            onChange={e => setFormatFilter(e.target.value)}
            aria-label="Lọc theo định dạng"
          >
            <option value="all">Tất cả định dạng</option>
            <option value="pdf">PDF</option>
            <option value="pptx">PPTX</option>
            <option value="docx">DOCX</option>
            <option value="txt">TXT</option>
            <option value="md">Markdown</option>
          </select>

          <select
            id="sortFilter"
            className="input student-docs-select"
            value={sortFilter}
            onChange={e => setSortFilter(e.target.value as 'newest' | 'oldest' | 'name')}
            aria-label="Sắp xếp"
          >
            <option value="newest">Mới nhất</option>
            <option value="oldest">Cũ nhất</option>
            <option value="name">Tên A-Z</option>
          </select>
        </div>

        <span className="student-docs-count">
          Tổng số: <strong>{filteredDocs.length}</strong> tài liệu
        </span>
      </div>

      {actionError && (
        <p className="notice error" role="alert">
          {actionError}
        </p>
      )}

      {/* Document Grid Cards */}
      {filteredDocs.length === 0 ? (
        <div className="card student-docs-empty-panel">
          <p className="muted">
            {search.trim() || formatFilter !== 'all'
              ? 'Không tìm thấy tài liệu nào phù hợp với bộ lọc.'
              : 'Lớp học hiện chưa có tài liệu nào được chia sẻ.'}
          </p>
        </div>
      ) : (
        <div className="student-docs-grid">
          {filteredDocs.map(doc => {
            const readerHref =
              routeHref('s.reader', { classId: params.classId, documentId: doc.id }) ??
              `/student/classes/${params.classId}/documents/${doc.id}`;
            const isBookmarked = Boolean(doc.isBookmarked);

            return (
              <article key={doc.id} className="card student-doc-card">
                <div className="student-doc-card-body">
                  <div className="student-doc-card-top">
                    <span className="doc-format-pill" data-format={doc.format.toLowerCase()}>
                      {doc.format}
                    </span>
                    <button
                      type="button"
                      className="student-doc-bookmark-btn"
                      data-bookmarked={isBookmarked ? 'true' : 'false'}
                      aria-pressed={isBookmarked}
                      aria-label={isBookmarked ? 'Bỏ lưu tài liệu' : 'Lưu tài liệu vào danh sách ghi nhớ'}
                      onClick={() => handleToggleBookmark(doc.id)}
                    >
                      <Icon name="star" />
                    </button>
                  </div>

                  <h3 className="student-doc-card-title">
                    <Link href={readerHref}>{doc.title}</Link>
                  </h3>

                  {doc.description && <p className="student-doc-card-desc">{doc.description}</p>}
                </div>

                <div className="student-doc-card-footer">
                  <div className="student-doc-card-meta">
                    {doc.locatorCountLabel && (
                      <span className="student-doc-locator-chip">{doc.locatorCountLabel}</span>
                    )}
                    <span className="student-doc-version">v{doc.currentVersion}</span>
                  </div>

                  <Link href={readerHref} className="button small primary student-doc-open-btn">
                    <span>Xem tài liệu</span>
                    <Icon name="chevronRight" />
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
