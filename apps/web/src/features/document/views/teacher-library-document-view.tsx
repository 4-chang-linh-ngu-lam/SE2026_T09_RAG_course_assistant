'use client';
import { useState, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { RouteDefinition } from '@/config/routes';
import type { ClassDocumentGrant, DocumentItem, DocumentVersion, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherLibraryDocumentView({ data, reload }: Props) {
  const router = useRouter();
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
  const servingVersion = versions.find(v => v.isServing);

  const handleOpenShare = () => {
    setSelectedClassesToShare(grants.filter(g => g.isShared).map(g => g.classId));
    setShareOpen(true);
    setActionError(null);
  };

  const handleConfirmShare = () => {
    startTransition(async () => {
      try {
        await adapter.document.shareDocument(doc.id, selectedClassesToShare);
        setShareOpen(false);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi cập nhật chia sẻ.');
      }
    });
  };

  const handleConfirmRevoke = () => {
    if (!revokeClass) return;
    startTransition(async () => {
      try {
        await adapter.document.revokeShare(doc.id, revokeClass.classId);
        setRevokeClass(null);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi thu hồi quyền.');
      }
    });
  };

  const handleConfirmDelete = () => {
    startTransition(async () => {
      try {
        await adapter.document.deleteDocument(doc.id);
        setDeleteOpen(false);
        router.push('/teacher/library');
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi xóa tài liệu.');
      }
    });
  };

  const handleUploadVersionSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;
    startTransition(async () => {
      try {
        await adapter.document.uploadVersion(doc.id, {
          name: selectedFile.name,
          size: selectedFile.size,
          type: selectedFile.type,
        });
        setNewVersionOpen(false);
        setSelectedFile(null);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi tải lên phiên bản mới.');
      }
    });
  };

  const handleRetryProcessing = (vNum: number) => {
    startTransition(async () => {
      try {
        await adapter.document.retryProcessing(doc.id, vNum);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi thử lại xử lý.');
      }
    });
  };

  return (
    <div className="teacher-library-doc-container space-y-6">
      {/* Return link */}
      <div>
        <Link href="/teacher/library" className="link-button text-sm text-primary flex items-center gap-1.5 hover:underline">
          <Icon name="arrowLeft" />
          <span>Quay lại Thư viện tài liệu</span>
        </Link>
      </div>

      {/* Header Document Summary */}
      <div className="card p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="badge primary uppercase text-xs">{doc.format}</span>
            <span className="muted text-xs">Phiên bản hiện hành: v{doc.currentVersion}</span>
            <span className="badge success text-xs">Đang phục vụ: v{servingVersion?.versionNumber ?? doc.currentVersion}</span>
          </div>
          <h1 className="text-xl font-bold text-on-surface">{doc.title}</h1>
          {doc.description && <p className="text-sm muted mt-1">{doc.description}</p>}
          <p className="text-xs muted mt-2">Chủ sở hữu: {doc.ownerName} · Ngày tạo: {doc.createdAt}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            id="ux-doc-open-share"
            type="button"
            className="button primary small flex items-center gap-1.5"
            onClick={handleOpenShare}
          >
            <Icon name="plus" />
            <span>Chia sẻ cho lớp</span>
          </button>
          <button
            id="ux-doc-upload-version"
            type="button"
            className="button secondary small flex items-center gap-1.5"
            onClick={() => {
              setNewVersionOpen(true);
              setActionError(null);
            }}
          >
            <Icon name="file" />
            <span>Tải phiên bản mới</span>
          </button>
          <button
            id="ux-doc-open-delete"
            type="button"
            className="button danger small flex items-center gap-1.5"
            onClick={() => {
              setDeleteOpen(true);
              setActionError(null);
            }}
          >
            <Icon name="trash" />
            <span>Xóa tài liệu nguồn</span>
          </button>
        </div>
      </div>

      {/* Failed Version Alert Banner (Rules B4 & H3) */}
      {failedVersion && (
        <div className="card p-4 bg-amber-50 border border-amber-200 text-amber-900 rounded-xl flex items-start gap-3">
          <Icon name="info" />
          <div className="flex-1 text-sm">
            <h3 className="font-semibold text-amber-950">Phiên bản v{failedVersion.versionNumber} xử lý thất bại</h3>
            <p className="mt-1 text-xs text-amber-800 leading-relaxed">
              {failedVersion.errorMessage ?? 'Quá trình phân tích cú pháp gặp lỗi.'} Theo quy tắc nghiệp vụ B4 & H3, các
              lớp học sinh vẫn tiếp tục sử dụng phiên bản thành công gần nhất (v{servingVersion?.versionNumber ?? 1}) mà
              không bị gián đoạn học tập.
            </p>
            <div className="mt-3">
              <button
                id={`ux-doc-retry-v${failedVersion.versionNumber}`}
                type="button"
                className="button small warning"
                onClick={() => handleRetryProcessing(failedVersion.versionNumber)}
                disabled={isPending}
              >
                Thử lại xử lý v{failedVersion.versionNumber}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Section: Class Grants */}
      <div className="card p-5 space-y-4">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-base font-bold text-on-surface">Các lớp được cấp quyền chia sẻ</h2>
            <p className="text-xs muted">Học sinh trong các lớp này có thể đọc và hỏi Lumi về tài liệu</p>
          </div>
        </div>

        {grants.filter(g => g.isShared).length === 0 ? (
          <p className="text-sm muted p-4 text-center bg-surface-container-low rounded-lg">
            Tài liệu này chưa được chia sẻ cho lớp nào. Bấm &quot;Chia sẻ cho lớp&quot; để cấp quyền.
          </p>
        ) : (
          <div className="divide-y divide-outline-variant/30">
            {grants
              .filter(g => g.isShared)
              .map(grant => (
                <div key={grant.classId} className="py-3 flex justify-between items-center text-sm">
                  <div>
                    <span className="font-medium">{grant.className}</span>
                    <span className="muted text-xs ml-2">({grant.classCode})</span>
                    <p className="text-xs muted">Cấp quyền: {grant.grantedAt} · Bản đang phục vụ: v{grant.servingVersion}</p>
                  </div>
                  <button
                    id={`ux-doc-revoke-class-${grant.classId}`}
                    type="button"
                    className="button small danger"
                    onClick={() => setRevokeClass(grant)}
                  >
                    Thu hồi quyền
                  </button>
                </div>
              ))}
          </div>
        )}
      </div>

      {/* Section: Version History */}
      <div className="card p-5 space-y-4">
        <h2 className="text-base font-bold text-on-surface">Lịch sử các phiên bản</h2>
        <div className="table-container overflow-x-auto">
          <table className="table w-full text-left text-sm" aria-label="Lịch sử phiên bản">
            <thead>
              <tr className="border-b text-xs text-muted uppercase">
                <th className="p-3">Phiên bản</th>
                <th className="p-3">Tệp tin</th>
                <th className="p-3">Dung lượng</th>
                <th className="p-3">Ngày tải lên</th>
                <th className="p-3">Trạng thái xử lý</th>
                <th className="p-3">Đang phục vụ</th>
                <th className="p-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {versions.map(v => (
                <tr key={v.versionNumber} className="hover:bg-surface-container-low">
                  <td className="p-3 font-semibold">v{v.versionNumber}</td>
                  <td className="p-3 text-xs">{v.filename}</td>
                  <td className="p-3 text-xs muted">{v.fileSizeFormatted}</td>
                  <td className="p-3 text-xs muted">{v.uploadedAt}</td>
                  <td className="p-3">
                    {v.status === 'READY' && <span className="badge success text-xs">Sẵn sàng</span>}
                    {v.status === 'PROCESSING' && <span className="badge info text-xs animate-pulse">Đang xử lý</span>}
                    {v.status === 'PENDING' && <span className="badge warning text-xs">Chờ xử lý</span>}
                    {v.status === 'FAILED' && <span className="badge danger text-xs">Lỗi xử lý</span>}
                  </td>
                  <td className="p-3">
                    {v.isServing ? (
                      <span className="badge primary text-xs">Đang phục vụ</span>
                    ) : (
                      <span className="muted text-xs">-</span>
                    )}
                  </td>
                  <td className="p-3 text-right">
                    {v.status === 'FAILED' && (
                      <button
                        type="button"
                        className="button small warning"
                        onClick={() => handleRetryProcessing(v.versionNumber)}
                        disabled={isPending}
                      >
                        Thử lại
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

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
          <p className="text-on-surface">
            Bạn có chắc chắn muốn thu hồi quyền truy cập tài liệu <strong>{doc.title}</strong> khỏi lớp{' '}
            <strong>{revokeClass?.className}</strong>?
          </p>
          <div className="card p-3 bg-red-50 text-red-800 text-xs border border-red-200 rounded-lg">
            ⚠️ <strong>Ảnh hưởng bảo mật (Rule B6):</strong> Học sinh trong lớp này sẽ lập tức mất quyền mở tài liệu gốc,
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
        title="Xác nhận gỡ khỏi bảng tin tài liệu nguồn"
        onClose={() => {
          if (!isPending) setDeleteOpen(false);
        }}
      >
        <div id="ux-delete-dialog" className="space-y-4 text-sm">
          <p className="text-on-surface">
            Bạn có chắc chắn muốn gỡ khỏi bảng tin tài liệu <strong>{doc.title}</strong>?
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
