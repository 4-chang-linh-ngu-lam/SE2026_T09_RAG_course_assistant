'use client';
import { useEffect, useRef, useState, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { RouteDefinition } from '@/config/routes';
import type { ClassDocumentGrant, DocumentItem, DocumentVersion, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog, ErrorNotice } from '@/components/ui';
import { SourceDocumentSummary, SourceFailureNotice, SourceGrantsPanel, SourceVersionHistory } from '../components/source-management-ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherLibraryDocumentView({ data, reload }: Props) {
  const router = useRouter();
  const mutationScope = useRef(0);
  useEffect(() => { ++mutationScope.current; return () => { ++mutationScope.current; }; }, []);
  const [shareOpen, setShareOpen] = useState(false);
  const [revokeClass, setRevokeClass] = useState<ClassDocumentGrant | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [newVersionOpen, setNewVersionOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  // Multi-class share selections
  const [selectedClassesToShare, setSelectedClassesToShare] = useState<string[]>([]);

  if (!data) {
    return <StatePanel busy title="Đang tải thông tin tài liệu nguồn…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ tài liệu chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty' || !data.sourceDocumentDetail) {
    return <StatePanel title="Không tìm thấy tài liệu" message={data.kind === 'empty' ? data.message : 'Tài liệu không tồn tại.'} />;
  }

  const { document: doc, versions, grants } = data.sourceDocumentDetail;
  const failedVersion = versions.find(v => v.status === 'FAILED');
  const servingVersion = versions.find(v => v.isServing && v.status === 'READY') ?? null;
  const canShare = versions.some(v => v.status === 'READY');

  const handleOpenShare = () => {
    setSelectedClassesToShare(grants.filter(g => g.isShared).map(g => g.classId));
    setShareOpen(true);
    setActionError(null);
  };

  const handleConfirmShare = () => {
    startTransition(async () => {
      const generation = mutationScope.current;
      try {
        await adapter.document.shareDocument(doc.id, selectedClassesToShare);
        if (mutationScope.current !== generation) return;
        setShareOpen(false);
        reload();
      } catch (err) {
        if (mutationScope.current !== generation) return;
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi cập nhật chia sẻ.');
      }
    });
  };

  const handleConfirmRevoke = () => {
    if (!revokeClass) return;
    startTransition(async () => {
      const generation = mutationScope.current;
      try {
        await adapter.document.revokeShare(doc.id, revokeClass.classId);
        if (mutationScope.current !== generation) return;
        setRevokeClass(null);
        reload();
      } catch (err) {
        if (mutationScope.current !== generation) return;
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi thu hồi quyền.');
      }
    });
  };

  const handleConfirmDelete = () => {
    startTransition(async () => {
      const generation = mutationScope.current;
      try {
        await adapter.document.deleteDocument(doc.id);
        if (mutationScope.current !== generation) return;
        setDeleteOpen(false);
        router.push('/teacher/library');
      } catch (err) {
        if (mutationScope.current !== generation) return;
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi xóa tài liệu.');
      }
    });
  };

  const handleUploadVersionSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;
    startTransition(async () => {
      const generation = mutationScope.current;
      try {
        await adapter.document.uploadVersion(doc.id, {
          name: selectedFile.name,
          size: selectedFile.size,
          type: selectedFile.type,
        });
        if (mutationScope.current !== generation) return;
        setNewVersionOpen(false);
        setSelectedFile(null);
        reload();
      } catch (err) {
        if (mutationScope.current !== generation) return;
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi tải lên phiên bản mới.');
      }
    });
  };

  const handleRetryProcessing = (vNum: number) => {
    startTransition(async () => {
      const generation = mutationScope.current;
      try {
        await adapter.document.retryProcessing(doc.id, vNum);
        if (mutationScope.current !== generation) return;
        reload();
      } catch (err) {
        if (mutationScope.current !== generation) return;
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi thử lại xử lý.');
      }
    });
  };

  return (
    <div className="workspace-content">
      {/* Return link */}
      <div>
        <Link href="/teacher/library" className="link-button text-sm text-primary flex items-center gap-1.5 hover:underline">
          <Icon name="arrowLeft" />
          <span>Quay lại Thư viện tài liệu</span>
        </Link>
      </div>

      <SourceDocumentSummary document={doc} servingVersion={servingVersion} busy={isPending}
        canShare={canShare} shareUnavailableReason="Cần một phiên bản xử lý thành công trước khi chia sẻ."
        onShare={handleOpenShare}
        onUploadVersion={() => { setNewVersionOpen(true); setActionError(null); }}
        onDelete={() => { setDeleteOpen(true); setActionError(null); }}/>
      {actionError && !shareOpen && !revokeClass && !deleteOpen && !newVersionOpen && <div className="notice error" role="alert">{actionError}</div>}
      {failedVersion && <SourceFailureNotice version={failedVersion} servingVersion={servingVersion} busy={isPending} onRetry={handleRetryProcessing}/>}
      <SourceGrantsPanel grants={grants.filter(grant => grant.isShared)} busy={isPending}
        onRevoke={grant => { setRevokeClass(grant); setActionError(null); }}/>
      <SourceVersionHistory versions={versions} busy={isPending} onRetry={handleRetryProcessing}/>

      {/* D04: Class Share Dialog */}
      <Dialog
        busy={isPending}
        open={shareOpen}
        title="Quản lý chia sẻ tài liệu cho lớp học"
        onClose={() => {
          if (!isPending) setShareOpen(false);
        }}
      >
        <div id="ux-share-dialog" className="space-y-4">
          <p className="text-xs muted">Chọn các lớp bạn phụ trách để cấp quyền đọc học liệu và hỏi Lumi:</p>

          {actionError && <div className="card p-2 bg-red-50 text-red-700 text-xs">{actionError}</div>}

          <div className="space-y-2 border border-outline-variant rounded-lg p-3 max-h-60 overflow-y-auto">
            {grants.map(grant => {
              const isChecked = selectedClassesToShare.includes(grant.classId);
              return (
                <label
                  key={grant.classId}
                  className="flex items-center gap-3 p-2 rounded hover:bg-surface-container-low cursor-pointer text-sm"
                >
                  <input
                    type="checkbox"
                    disabled={isPending}
                    className="checkbox"
                    checked={isChecked}
                    onChange={e => {
                      if (e.target.checked) {
                        setSelectedClassesToShare(prev => [...prev, grant.classId]);
                      } else {
                        setSelectedClassesToShare(prev => prev.filter(id => id !== grant.classId));
                      }
                    }}
                  />
                  <div className="flex-1">
                    <span className="font-medium text-on-surface">{grant.className}</span>
                    <span className="muted text-xs ml-2">({grant.classCode})</span>
                  </div>
                  {grant.isShared && <span className="badge info text-xs">Đang chia sẻ</span>}
                </label>
              );
            })}
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-outline-variant/30">
            <button
              id="ux-doc-cancel-share"
              type="button"
              className="button secondary"
              onClick={() => setShareOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-confirm-share"
              type="button"
              className="button primary"
              onClick={handleConfirmShare}
              disabled={isPending}
            >
              {isPending ? 'Đang lưu…' : 'Lưu quyền chia sẻ'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* D05: Confirm Revoke Grant Dialog (Rule B6) */}
      <Dialog
        busy={isPending}
        open={Boolean(revokeClass)}
        title="Xác nhận thu hồi quyền chia sẻ"
        onClose={() => {
          if (!isPending) setRevokeClass(null);
        }}
      >
        <div id="ux-revoke-dialog" className="space-y-4 text-sm">
          <ErrorNotice message={actionError}/>
          <p className="text-on-surface">
            Bạn có chắc chắn muốn thu hồi quyền truy cập tài liệu <strong>{doc.title}</strong> khỏi lớp{' '}
            <strong>{revokeClass?.className}</strong>?
          </p>
          <div className="card p-3 bg-red-50 text-red-800 text-xs border border-red-200 rounded-lg">
            ⚠️ <strong>Ảnh hưởng khi thu hồi:</strong> Học sinh trong lớp này sẽ lập tức mất quyền mở tài liệu gốc,
            trích đoạn tài liệu trong ghi chú cá nhân sẽ bị ẩn và trợ lý Lumi sẽ ngừng trích dẫn nội dung này.
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-outline-variant/30">
            <button
              id="ux-doc-cancel-revoke"
              type="button"
              className="button secondary"
              onClick={() => setRevokeClass(null)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-revoke"
              type="button"
              className="button danger"
              onClick={handleConfirmRevoke}
              disabled={isPending}
            >
              {isPending ? 'Đang thu hồi…' : 'Xác nhận thu hồi'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* D06: Confirm Delete Source Dialog */}
      <Dialog
        busy={isPending}
        open={deleteOpen}
        title="Xác nhận xóa tài liệu nguồn"
        onClose={() => {
          if (!isPending) setDeleteOpen(false);
        }}
      >
        <div id="ux-delete-dialog" className="space-y-4 text-sm">
          <ErrorNotice message={actionError}/>
          <p className="text-on-surface">
            Bạn có chắc chắn muốn xóa tài liệu nguồn <strong>{doc.title}</strong>?
          </p>
          <div className="card p-3 bg-red-50 text-red-800 text-xs border border-red-200 rounded-lg">
            ⚠️ Toàn bộ các phiên bản và liên kết chia sẻ tới các lớp sẽ bị xóa hoàn toàn. Thao tác này không thể hoàn tác.
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-outline-variant/30">
            <button
              id="ux-doc-cancel-delete"
              type="button"
              className="button secondary"
              onClick={() => setDeleteOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-delete"
              type="button"
              className="button danger"
              onClick={handleConfirmDelete}
              disabled={isPending}
            >
              {isPending ? 'Đang xóa…' : 'Xác nhận xóa tài liệu'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* Upload New Version Dialog */}
      <Dialog
        busy={isPending}
        open={newVersionOpen}
        title={`Tải lên phiên bản mới cho ${doc.title}`}
        onClose={() => {
          if (!isPending) setNewVersionOpen(false);
        }}
      >
        <form onSubmit={handleUploadVersionSubmit} className="space-y-4 text-sm">
          {actionError && <div className="card p-2 bg-red-50 text-red-700 text-xs">{actionError}</div>}

          <div>
            <label className="label text-xs font-semibold block mb-1">Chọn tệp phiên bản mới</label>
            <input
              type="file"
              disabled={isPending}
              className="input w-full"
              accept=".pdf,.pptx,.docx,.txt,.md,.markdown"
              onChange={e => setSelectedFile(e.target.files?.[0] ?? null)}
              required
            />
          </div>

          <p className="text-xs muted">
            Phiên bản tiếp theo sẽ là v{doc.currentVersion + 1}. Nếu phiên bản này xử lý thành công, hệ thống sẽ tự động
            phục vụ bản mới nhất cho các lớp được chia sẻ.
          </p>

          <div className="flex justify-end gap-2 pt-3 border-t border-outline-variant/30">
            <button
              type="button"
              className="button secondary"
              onClick={() => setNewVersionOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button type="submit" className="button primary" disabled={isPending || !selectedFile}>
              {isPending ? 'Đang tải lên…' : 'Tải lên phiên bản'}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
