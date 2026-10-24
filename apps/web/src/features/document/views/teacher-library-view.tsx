'use client';
import { useState, useRef, useTransition } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { DocumentCapabilityPolicy, DocumentFormat, DocumentItem, ProcessingStatus, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { documentFileError, documentFileSelection } from '@/lib/document-upload';
import { StatePanel, Icon, Dialog, useUnsavedChanges } from '@/components/ui';
import '../library.css';
import {useDocumentWrite} from '../use-document-write';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherLibraryView({ data, reload }: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const clearSelectedFile = () => { setSelectedFile(null); if (fileInput.current) fileInput.current.value = ''; };
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
  const [isRetryPending, startTransition] = useTransition();
  const uploadWrite=useDocumentWrite('library-upload');
  const uploadRequest=useRef<string|null>(null);
  const isPending=isRetryPending||uploadWrite.blocked;
  useUnsavedChanges(uploadOpen&&Boolean(selectedFile||title.trim()||description.trim()));

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
    const selection = documentFileSelection(e.target.files?.[0], capability);
    setSelectedFile(selection.file);
    setUploadError(selection.error);
    uploadRequest.current=null;
    if (!selection.file) { e.target.value = ''; return; }
    const file = selection.file;
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
    const fileError = documentFileError(selectedFile, capability);
    if (fileError || !selectedFile) { setUploadError(fileError); return; }

    const requestId=uploadRequest.current??crypto.randomUUID();uploadRequest.current=requestId;
    void uploadWrite.run(() => adapter.document.uploadDocument({
          name: selectedFile.name,
          size: selectedFile.size,
          type: selectedFile.type,
          title: title.trim(),
          description: description.trim() || undefined,
          file:selectedFile,requestId,
        }), () => {
        setUploadOpen(false);
        setTitle('');
        setDescription('');
        clearSelectedFile();
        setUploadError(null);
        uploadRequest.current=null;
        reload();
    },requestId);
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
    <div className="teacher-library-container">
      {/* Top action & filter bar */}
      <div className="card library-toolbar">
        <div className="library-toolbar-filters">
          <label htmlFor="ux-doc-search" className="sr-only">
            Tìm kiếm tài liệu
          </label>
          <input
            id="ux-doc-search"
            type="search"
            className="library-search-input"
            aria-label="Tìm kiếm tài liệu"
            placeholder="Tìm kiếm tài liệu..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          <label htmlFor="processingFilter" className="sr-only">
            Lọc theo trạng thái xử lý
          </label>
          <select
            id="processingFilter"
            className="library-select-input"
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
          className="button primary library-upload-btn"
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
      <div className="library-format-toolbar" role="toolbar" aria-label="Lọc theo định dạng">
        <span className="library-format-label" id="ux-format-filter-label">Định dạng:</span>
        {(['all', 'pdf', 'pptx', 'docx', 'txt', 'md'] as const).map(fmt => (
          <button
            key={fmt}
            type="button"
            data-ux-format={fmt}
            aria-pressed={formatFilter === fmt}
            className={`tag cursor-pointer ${formatFilter === fmt ? 'primary' : 'default'}`}
            onClick={() => setFormatFilter(fmt)}
          >
            {fmt === 'all' ? 'Tất cả' : fmt.toUpperCase()}
          </button>
        ))}
      </div>

      {retryError && <p className="notice error lumi-library-error" role="alert">{retryError}</p>}

      {/* Documents Table */}
      {filtered.length === 0 ? (
        <div className="card empty-panel library-empty-panel">
          <p className="muted">
            {search.trim() || statusFilter !== 'all' || formatFilter !== 'all'
              ? 'Không có tài liệu nào phù hợp với bộ lọc hiện tại.'
              : 'Thư viện tài liệu của bạn chưa có tài liệu nào. Bấm nút tải lên để bắt đầu.'}
          </p>
        </div>
      ) : (
        <div
          className="card library-table-container"
          tabIndex={0}
          role="region"
          aria-label="Bảng danh sách tài liệu"
        >
          <table className="library-table" aria-label="Bảng danh sách tài liệu">
            <thead>
              <tr >
                <th className="p-3">Tên tài liệu</th>
                <th className="p-3">Định dạng</th>
                <th className="p-3">Phiên bản</th>
                <th className="p-3">Trạng thái</th>
                <th className="p-3">Lớp chia sẻ</th>
                <th className="p-3">Ngày cập nhật</th>
                <th className="p-3 library-table-actions">Thao tác</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {filtered.map(doc => {
                const detailHref = routeHref('t.libraryDocument', { documentId: doc.id }) ?? `/teacher/library/${doc.id}`;
                return (
                  <tr key={doc.id} >
                    <td className="library-table-title-cell">
                      <Link href={detailHref} className="library-title-link">
                        <Icon name="file" />
                        <span>{doc.title}</span>
                      </Link>
                      {doc.description && <p className="library-table-desc">{doc.description}</p>}
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
                    <td className="p-3 text-xs muted">{new Date(doc.updatedAt).toLocaleString('vi-VN')}</td>
                    <td className="p-3 library-table-actions">
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
        className="lumi-library-dialog"
        onClose={() => {
          if (!isPending) setUploadOpen(false);
        }}
      >
        <form id="ux-document-dialog" onSubmit={handleUploadSubmit} className="lumi-library-dialog-form">
          {uploadWrite.error&&<p className="lumi-library-error" role="alert">{uploadWrite.error}</p>}
          {uploadWrite.unknown&&<button type="button" className="button" disabled={uploadWrite.busy} onClick={()=>void uploadWrite.retryOriginal()}>Gửi lại cùng yêu cầu đã lưu</button>}
          {uploadWrite.unknown&&uploadWrite.receiptId&&adapter.document.uploadReceipt&&<button type="button" className="button" disabled={uploadWrite.busy} onClick={()=>void uploadWrite.reconcile(async()=>{await adapter.document.uploadReceipt!(uploadWrite.receiptId!);return true;},()=>{setUploadOpen(false);clearSelectedFile();setTitle('');setDescription('');uploadRequest.current=null;reload();})}>Đối soát upload đã gửi</button>}
          {uploadError && (
            <div className="lumi-library-error" role="alert">
              {uploadError}
            </div>
          )}

          <div className="lumi-library-form-group">
            <label htmlFor="ux-doc-title" className="lumi-library-label">
              Tiêu đề tài liệu <span className="text-red-500">*</span>
            </label>
            <input
              id="ux-doc-title"
              type="text"
              className="lumi-library-input"
              placeholder="ví dụ: Hàm số bậc hai và đồ thị"
              value={title}
              onChange={e => setTitle(e.target.value)}
              disabled={isPending}
              required
            />
          </div>

          <div className="lumi-library-form-group">
            <label htmlFor="ux-doc-description" className="lumi-library-label">Mô tả ngắn (tùy chọn)</label>
            <textarea id="ux-doc-description" className="lumi-library-input" rows={3}
              placeholder="Mô tả nội dung và mục đích sử dụng" value={description}
              onChange={e => setDescription(e.target.value)} disabled={isPending}/>
          </div>
          <div className="lumi-library-form-group">
            <label htmlFor="ux-doc-file" className="lumi-library-label">Tệp tài liệu <span aria-hidden="true">*</span></label>
            <input id="ux-doc-file" ref={fileInput} type="file" className="lumi-library-input"
              accept={capability?.allowedExtensions.join(',')} onChange={handleFileChange} disabled={isPending}
              aria-describedby="ux-doc-file-help" aria-invalid={Boolean(uploadError)}/>
            <p id="ux-doc-file-help" className="muted">Hỗ trợ {capability?.allowedExtensions.join(', ') ?? 'chưa xác định'}.
              {capability && ` Tối đa ${(capability.maxSizeBytes / 1024 / 1024).toFixed(0)} MB.`} Chọn tệp khác để thay thế.</p>
            {selectedFile && <div className="lumi-library-selected-file">
              <div><strong>{selectedFile.name}</strong><p className="muted">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p></div>
              <button id="ux-doc-remove" type="button" className="button small danger" disabled={isPending} onClick={clearSelectedFile}>Gỡ tệp</button>
            </div>}
          </div>

          <div className="lumi-library-dialog-actions">
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
