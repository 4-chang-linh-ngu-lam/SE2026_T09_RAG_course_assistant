'use client';
import { useState, useMemo,useRef } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { DocumentItem, RouteParams, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon } from '@/components/ui';
import {useDocumentWrite} from '../use-document-write';

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
  const write=useDocumentWrite(`class-documents:${params.classId}`);
  const intent=useRef<{documentId:string;desired:boolean}|null>(null);

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
    const doc=rawDocs.find(item=>item.id===docId);if(!doc||!doc.currentVersion)return;
    const desired=!doc.isBookmarked;intent.current={documentId:docId,desired};
    void write.run(() => adapter.document.toggleBookmark(docId, params.classId,undefined,doc.currentVersion,desired), () => {
        reload();
    });
  };

  return (
    <div className="student-docs-container space-y-6">
      {(write.error||actionError)&&<p className="notice error" role="alert">{write.error??actionError}</p>}
      {write.unknown&&<button type="button" className="button" disabled={write.busy} onClick={()=>void write.retryOriginal()}>Gửi lại cùng yêu cầu đã lưu</button>}
      {write.unknown&&<button className="button" type="button" disabled={write.busy} onClick={()=>void write.reconcile(async()=>{const current=await adapter.workspace.load('s.documents',{classId:params.classId}),target=intent.current;if(current.kind!=='ready'||!target)return false;const doc=current.classDocuments?.find(item=>item.id===target.documentId);return Boolean(doc&&Boolean(doc.isBookmarked)===target.desired);},reload)}>Đối soát dấu trang</button>}
      {/* Header and Toolbar */}
      <div className="card p-4 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center">
        <div className="flex-1 flex flex-col sm:flex-row gap-3 w-full md:w-auto">
          <input
            id="docSearchInput"
            type="search"
            aria-label="Tìm kiếm tài liệu học tập"
            className="input search-input"
            placeholder="Tìm kiếm tài liệu học tập..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          <select
            id="formatFilter"
            className="input select-input"
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
            className="input select-input"
            value={sortFilter}
            onChange={e => setSortFilter(e.target.value as 'newest' | 'oldest' | 'name')}
            aria-label="Sắp xếp"
          >
            <option value="newest">Mới nhất</option>
            <option value="oldest">Cũ nhất</option>
            <option value="name">Tên A-Z</option>
          </select>
        </div>

        <span className="text-xs muted shrink-0">
          Tổng số: <strong>{filteredDocs.length}</strong> tài liệu
        </span>
      </div>

      {/* Document Grid Cards */}
      {filteredDocs.length === 0 ? (
        <div className="card p-8 text-center empty-panel">
          <p className="muted text-sm">
            {search.trim() || formatFilter !== 'all'
              ? 'Không tìm thấy tài liệu nào phù hợp với bộ lọc.'
              : 'Lớp học hiện chưa có tài liệu nào được chia sẻ.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredDocs.map(doc => {
            const readerHref =
              routeHref('s.reader', { classId: params.classId, documentId: doc.id }) ??
              `/student/classes/${params.classId}/documents/${doc.id}`;
            const isBookmarked = Boolean(doc.isBookmarked);

            return (
              <article
                key={doc.id}
                className="card doc-card p-5 flex flex-col justify-between hover:shadow-md transition-shadow relative"
              >
                <div>
                  <div className="flex justify-between items-start gap-2 mb-3">
                    <span className="badge primary uppercase text-xs">{doc.format}</span>
                    <button
                      type="button"
                      className="bookmark-btn p-1.5 rounded-full hover:bg-surface-container-high transition-colors"
                      data-bookmarked={isBookmarked ? 'true' : 'false'}
                      disabled={write.blocked||doc.currentVersion===0}
                      aria-label={isBookmarked ? 'Bỏ lưu tài liệu' : 'Lưu tài liệu vào danh sách ghi nhớ'}
                      onClick={() => handleToggleBookmark(doc.id)}
                    >
                      <Icon name="star" />
                    </button>
                  </div>

                  <h3 className="text-base font-bold text-on-surface line-clamp-2 hover:text-primary transition-colors">
                    {doc.currentVersion>0?<Link href={readerHref}>{doc.title}</Link>:doc.title}
                  </h3>

                  {doc.description && <p className="text-xs muted line-clamp-2 mt-2">{doc.description}</p>}
                </div>

                <div className="mt-4 pt-3 border-t border-outline-variant/30 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    {doc.locatorCountLabel && (
                      <span className="tag default text-xs">{doc.locatorCountLabel}</span>
                    )}
                    <span className="muted">v{doc.currentVersion}</span>
                  </div>

                  {doc.currentVersion>0?<Link href={readerHref} className="button small primary flex items-center gap-1">
                    <span>Xem tài liệu</span>
                    <Icon name="chevronRight" />
                  </Link>:<span className="muted">Đang chuẩn bị nguồn</span>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
