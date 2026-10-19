'use client';
import { useState, useMemo, useTransition } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { DocumentCapabilityPolicy, DocumentFormat, DocumentItem, ProcessingStatus, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherLibraryView({ data, reload }: Props) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [formatFilter, setFormatFilter] = useState<string>('all');
  const [uploadOpen, setUploadOpen] = useState(false);

  // Upload dialog state
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  if (!data) {
    return <StatePanel busy title="Đang tải thư viện tài liệu…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ thư viện tài liệu chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return <StatePanel title="Thư viện tài liệu trống" message={data.message} />;
  }

  const documents = data.libraryDocuments ?? [];
  const capability = data.capabilityPolicy;

  const filtered = documents.filter(doc => {
    if (statusFilter !== 'all' && doc.processingStatus !== statusFilter) return false;
    if (formatFilter !== 'all' && doc.format.toLowerCase() !== formatFilter.toLowerCase()) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return doc.title.toLowerCase().includes(q) || (doc.description && doc.description.toLowerCase().includes(q));
    }
    return true;
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadError(null);
    const file = e.target.files?.[0];
    if (!file) return;

    if (!capability) {
      setUploadError('Chính sách tải lên tài liệu chưa sẵn sàng trên hệ thống.');
      e.target.value = '';
      return;
    }

    if (file.size === 0) {
      setUploadError('Tệp tin không được rỗng (0 bytes). Vui lòng chọn tệp có nội dung.');
      e.target.value = '';
      return;
    }

    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!capability.allowedExtensions.includes(ext)) {
      setUploadError(`Định dạng tệp ${ext} không được hỗ trợ. Các định dạng được phép: ${capability.allowedExtensions.join(', ')}.`);
      e.target.value = '';
      return;
    }
    if (file.size > capability.maxSizeBytes) {
      const maxMb = (capability.maxSizeBytes / (1024 * 1024)).toFixed(0);
      setUploadError(`Dung lượng tệp vượt quá giới hạn ${maxMb}MB cho phép.`);
      e.target.value = '';
      return;
    }

    setSelectedFile(file);
    if (!title) {
      setTitle(file.name.replace(/\.[^/.]+$/, ''));
    }
  };

  const handleUploadSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!capability) {
      setUploadError('Chính sách tải lên tài liệu chưa sẵn sàng trên hệ thống.');
      return;
    }
    if (!title.trim()) {
      setUploadError('Vui lòng nhập tiêu đề tài liệu.');
      return;
    }
    if (!selectedFile) {
      setUploadError('Vui lòng chọn tệp tin tải lên.');
      return;
    }

    startTransition(async () => {
      try {
        await adapter.document.uploadDocument({
          name: selectedFile.name,
          size: selectedFile.size,
          type: selectedFile.type,
          title: title.trim(),
          description: description.trim() || undefined,
        });
        setUploadOpen(false);
        setTitle('');
        setDescription('');
        setSelectedFile(null);
        setUploadError(null);
        reload();
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : 'Có lỗi khi tải lên tài liệu.');
      }
    });
  };

  const handleRetry = (docId: string) => {
    setRetryError(null);
    startTransition(async () => {
      try {
        await adapter.document.retryProcessing(docId);
        reload();
      } catch (err) {
        setRetryError(err instanceof Error ? err.message : 'Có lỗi khi thử lại xử lý tài liệu.');
      }
    });
  };

  return (
    <div className="teacher-library-container space-y-6">
      {/* Top action & filter bar */}
      <div className="card library-toolbar p-4 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center">
        <div className="flex-1 flex flex-col sm:flex-row gap-3 w-full md:w-auto">
          <input
            id="ux-doc-search"
            type="search"
            className="input search-input"
            placeholder="Tìm kiếm tài liệu..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          <select
            id="processingFilter"
            className="input select-input"
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            aria-label="Lọc theo trạng thái xử lý"
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="READY">Sẵn sàng</option>
            <option value="PROCESSING">Đang xử lý</option>
            <option value="PENDING">Chờ xử lý</option>
            <option value="FAILED">Xử lý thất bại</option>
          </select>
        </div>

        <button
          id="ux-doc-open-upload"
          type="button"
          className="button primary shrink-0 flex items-center gap-2"
          onClick={() => {
            setUploadOpen(true);
            setUploadError(null);
          }}
        >
          <Icon name="plus" />
          <span>Tải tài liệu mới</span>
        </button>
      </div>

      {/* Format Chips */}
      <div className="flex flex-wrap gap-2 items-center text-sm" role="toolbar" aria-label="Lọc theo định dạng">
        <span className="muted mr-2">Định dạng:</span>
        {(['all', 'pdf', 'pptx', 'docx', 'txt', 'md'] as const).map(fmt => (
          <button
            key={fmt}
            type="button"
            data-ux-format={fmt}
            className={`tag cursor-pointer ${formatFilter === fmt ? 'primary' : 'default'}`}
            onClick={() => setFormatFilter(fmt)}
          >
            {fmt === 'all' ? 'Tất cả' : fmt.toUpperCase()}
          </button>
        ))}
      </div>

      {retryError && <p className="notice error">{retryError}</p>}

      {/* Documents Table */}
      {filtered.length === 0 ? (
        <div className="card empty-panel p-8 text-center">
          <p className="muted">
            {search.trim() || statusFilter !== 'all' || formatFilter !== 'all'
              ? 'Không có tài liệu nào phù hợp với bộ lọc hiện tại.'
              : 'Thư viện tài liệu của bạn chưa có tài liệu nào. Bấm nút tải lên để bắt đầu.'}
          </p>
        </div>
      ) : (
        <div className="card table-container overflow-x-auto">
          <table className="table w-full text-left border-collapse" aria-label="Bảng danh sách tài liệu">
            <thead>
              <tr className="border-b text-xs text-muted font-semibold uppercase">
                <th className="p-3">Tên tài liệu</th>
                <th className="p-3">Định dạng</th>
                <th className="p-3">Phiên bản</th>
                <th className="p-3">Trạng thái</th>
                <th className="p-3">Lớp chia sẻ</th>
                <th className="p-3">Ngày cập nhật</th>
                <th className="p-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30 text-sm">
              {filtered.map(doc => {
                const detailHref = routeHref('t.libraryDocument', { documentId: doc.id }) ?? `/teacher/library/${doc.id}`;
                return (
                  <tr key={doc.id} className="hover:bg-surface-container-low transition-colors">
                    <td className="p-3 font-medium">
                      <Link href={detailHref} className="text-primary hover:underline flex items-center gap-2">
                        <Icon name="file" />
                        <span>{doc.title}</span>
                      </Link>
                      {doc.description && <p className="text-xs muted line-clamp-1 mt-0.5">{doc.description}</p>}
                    </td>
                    <td className="p-3">
                      <span className="badge primary text-xs">{doc.format}</span>
                    </td>
                    <td className="p-3 text-xs">v{doc.currentVersion}</td>
                    <td className="p-3">
                      {doc.processingStatus === 'READY' && <span className="badge success text-xs">Sẵn sàng</span>}
                      {doc.processingStatus === 'PROCESSING' && (
                        <span className="badge info text-xs animate-pulse">Đang xử lý</span>
                      )}
                      {doc.processingStatus === 'PENDING' && <span className="badge warning text-xs">Chờ xử lý</span>}
                      {doc.processingStatus === 'FAILED' && (
                        <span className="badge danger text-xs" title={doc.processingError}>
                          Thất bại
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-xs">
                      {doc.sharedClassCount ? `${doc.sharedClassCount} lớp` : <span className="muted">Chưa chia sẻ</span>}
                    </td>
                    <td className="p-3 text-xs muted">{doc.updatedAt}</td>
                    <td className="p-3 text-right space-x-2">
                      {doc.processingStatus === 'FAILED' && (
                        <button
                          type="button"
                          data-ux-document-action="retry"
                          className="button small warning"
                          onClick={() => handleRetry(doc.id)}
                          disabled={isPending}
                        >
                          Thử lại
                        </button>
                      )}
                      <Link href={detailHref} className="button small secondary">
                        Quản lý nguồn
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* D02 Upload Document Modal */}
      <Dialog
        busy={isPending}
        open={uploadOpen}
        title="Tải lên tài liệu mới"
        onClose={() => {
          if (!isPending) setUploadOpen(false);
        }}
      >
        <form id="ux-document-dialog" onSubmit={handleUploadSubmit} className="space-y-4">
          {uploadError && (
            <div className="card p-3 bg-red-50 text-red-700 text-xs border border-red-200" role="alert">
              {uploadError}
            </div>
          )}

          <div>
            <label htmlFor="ux-doc-title" className="label text-xs font-semibold block mb-1">
              Tiêu đề tài liệu <span className="text-red-500">*</span>
            </label>
            <input
              id="ux-doc-title"
              type="text"
              className="input w-full"
              placeholder="ví dụ: Hàm số bậc hai và đồ thị"
              value={title}
              onChange={e => setTitle(e.target.value)}
              required
            />
          </div>

          <div>
            <label htmlFor="ux-doc-description" className="label text-xs font-semibold block mb-1">
              Mô tả ngắn (tùy chọn)
            </label>
            <textarea
              id="ux-doc-description"
              className="input w-full h-20"
              placeholder="ví dụ: Ôn tập khảo sát parabol và tính chất đơn điệu"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>

          <div>
            <label className="label text-xs font-semibold block mb-1">
              Tệp tài liệu <span className="text-red-500">*</span>
            </label>
            {!selectedFile ? (
              <div className="border-2 border-dashed border-outline-variant p-6 rounded-lg text-center cursor-pointer hover:bg-surface-container-low transition-colors">
                <input
                  id="ux-doc-file"
                  type="file"
                  className="hidden"
                  accept={capability ? capability.allowedExtensions.join(',') : undefined}
                  onChange={handleFileChange}
                />
                <label htmlFor="ux-doc-file" className="cursor-pointer block">
                  <Icon name="file" />
                  <p className="mt-2 text-sm font-medium">Bấm vào đây để chọn tệp tài liệu</p>
                  <p className="text-xs muted mt-1">
                    Hỗ trợ: {capability ? capability.allowedExtensions.map(e => e.replace('.', '').toUpperCase()).join(', ') : 'Chưa xác định'} (tối đa {capability ? (capability.maxSizeBytes / (1024 * 1024)).toFixed(0) : '0'}MB)
                  </p>
                </label>
              </div>
            ) : (
              <div className="card p-3 flex items-center justify-between bg-surface-container-low border border-outline-variant">
                <div className="flex items-center gap-3">
                  <span className="badge primary uppercase text-xs">
                    {selectedFile.name.split('.').pop()}
                  </span>
                  <div>
                    <p className="text-xs font-semibold text-on-surface">{selectedFile.name}</p>
                    <p className="text-xs muted">{(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</p>
                  </div>
                </div>
                <button
                  id="ux-doc-remove"
                  type="button"
                  className="button small danger"
                  onClick={() => setSelectedFile(null)}
                >
                  Gỡ tệp
                </button>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-4 border-t border-outline-variant/30">
            <button
              id="ux-doc-cancel"
              type="button"
              className="button secondary"
              onClick={() => setUploadOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-upload"
              type="submit"
              className="button primary"
              disabled={isPending || !selectedFile || !title.trim()}
            >
              {isPending ? 'Đang tải lên…' : 'Tải lên tài liệu'}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
