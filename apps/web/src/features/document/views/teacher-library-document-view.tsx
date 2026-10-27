'use client';
import { useEffect, useRef, useState, useTransition } from 'react';
import Link from 'next/link';
import {useGuardedRouter as useRouter} from '@/components/unsaved-changes';
import type { RouteDefinition } from '@/config/routes';
import type { ClassDocumentGrant, DocumentItem, DocumentVersion, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog, ErrorNotice } from '@/components/ui';
import { useDocumentGrantAction } from '../use-document-grant-action';
import { documentFileError, documentFileSelection } from '@/lib/document-upload';
import { documentVersionState } from '@/lib/document-versions';
import { newShareTargets } from '@/lib/document-sharing';
import { GrantMutationNotice } from '../components/grant-mutation-notice';
import { SourceDocumentSummary, SourceFailureNotice, SourceGrantsPanel, SourceVersionHistory } from '../components/source-management-ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherLibraryDocumentView({ data, reload }: Props) {
  const router = useRouter();
  const grantAction = useDocumentGrantAction();
  const mutationScope = useRef(0);
  useEffect(() => { ++mutationScope.current; return () => { ++mutationScope.current; }; }, []);
  const [shareOpen, setShareOpen] = useState(false);
  const [revokeClass, setRevokeClass] = useState<ClassDocumentGrant | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [newVersionOpen, setNewVersionOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isOtherPending, startTransition] = useTransition();
  const isPending = isOtherPending || grantAction.busy;
  const mutationBlocked = isPending || Boolean(grantAction.unknown);

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

  const { document: doc, versions, grants, shareableClasses = [] } = data.sourceDocumentDetail;
  const newTargets = newShareTargets(selectedClassesToShare, shareableClasses, grants);
  const versionState = documentVersionState(versions);
  const failedVersion = versionState.failed;
  const servingVersion = versionState.serving;
  const canShare = Boolean(servingVersion);

  const handleOpenShare = () => {
    setSelectedClassesToShare(grants.filter(g => g.isShared).map(g => g.classId));
    grantAction.clearError();
    setShareOpen(true);
    setActionError(null);
  };

  const handleConfirmShare = () => {
    if (mutationBlocked || !newTargets.length || !canShare) return;
    void grantAction.run({documentId: doc.id, classIds: newTargets, shared: true},
      () => adapter.document.shareDocument(doc.id, newTargets), () => { setShareOpen(false); reload(); });
  };

  const handleConfirmRevoke = () => {
    if (mutationBlocked || !revokeClass || revokeClass.classStatus !== 'ACTIVE') return;
    const classId = revokeClass.classId;
    void grantAction.run({documentId: doc.id, classIds: [classId], shared: false},
      () => adapter.document.revokeShare(doc.id, classId), () => { setRevokeClass(null); reload(); });
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
    const fileError = documentFileError(selectedFile, data.capabilityPolicy);
    if (fileError || !selectedFile) { setActionError(fileError); return; }
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
      {!shareOpen && !revokeClass && (
        <GrantMutationNotice
          busy={grantAction.busy}
          unknown={Boolean(grantAction.unknown)}
          error={grantAction.error}
          message={grantAction.message}
          onReconcile={() => void grantAction.reconcile(() => { setShareOpen(false); setRevokeClass(null); reload(); })}
        />
      )}
      {/* Return link */}
      <div>
        <Link href="/teacher/library" className="lumi-source-back-link">
          <Icon name="arrowLeft" />
          <span>Quay lại Thư viện tài liệu</span>
        </Link>
      </div>

      <SourceDocumentSummary
        document={doc}
        servingVersion={servingVersion}
        busy={mutationBlocked}
        canShare={canShare}
        shareUnavailableReason="Cần một phiên bản xử lý thành công trước khi chia sẻ."
        onShare={handleOpenShare}
        onUploadVersion={() => { setNewVersionOpen(true); setSelectedFile(null); setActionError(null); }}
        onDelete={() => { setDeleteOpen(true); setActionError(null); }}
      />
      {actionError && !shareOpen && !revokeClass && !deleteOpen && !newVersionOpen && (
        <div className="notice error" role="alert">{actionError}</div>
      )}
      {failedVersion && (
        <SourceFailureNotice
          version={failedVersion}
          servingVersion={servingVersion}
          busy={mutationBlocked}
          onRetry={handleRetryProcessing}
        />
      )}
      <SourceGrantsPanel
        grants={grants.filter(grant => grant.isShared)}
        busy={mutationBlocked}
        onRevoke={grant => { setRevokeClass(grant); setActionError(null); }}
      />
      <SourceVersionHistory versions={versionState.ordered.map(v => ({...v, isServing: v.versionNumber === servingVersion?.versionNumber}))} busy={mutationBlocked} onRetry={handleRetryProcessing}/>

      {/* D04: Class Share Dialog */}
      <Dialog
        busy={isPending}
        open={shareOpen}
        title="Cấp thêm quyền chia sẻ cho lớp học"
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setShareOpen(false);
        }}
      >
        <div id="ux-share-dialog" className="lumi-source-dialog-content">
          <GrantMutationNotice
            busy={grantAction.busy}
            unknown={Boolean(grantAction.unknown)}
            error={grantAction.error}
            message={grantAction.message}
            onReconcile={() => void grantAction.reconcile(() => { setShareOpen(false); reload(); })}
          />
          <p className="lumi-source-dialog-desc">Chọn các lớp bạn phụ trách để cấp quyền đọc học liệu và hỏi Lumi:</p>

          <ErrorNotice message={actionError}/>

          {shareableClasses.length === 0 ? (
            <div className="lumi-source-empty-classes">
              Không có lớp học nào khả dụng để chia sẻ tài liệu này.
            </div>
          ) : (
            <>
              {shareableClasses.filter(c => c.status === 'ACTIVE' && !grants.some(g => g.classId === c.id && g.isShared)).length === 0 && (
                <div className="lumi-source-empty-choices-notice" role="status">
                  Tất cả các lớp học hoạt động đã được cấp quyền chia sẻ tài liệu này.
                </div>
              )}
              <div className="lumi-source-share-list" role="group" aria-label="Danh sách lớp để cấp quyền chia sẻ">
                {shareableClasses.map(cls => {
                  const grant = grants.find(g => g.classId === cls.id) ?? {
                    classId: cls.id,
                    className: cls.name,
                    classCode: cls.code,
                    isShared: false,
                    servingVersion: doc.currentVersion,
                    classStatus: cls.status,
                  };
                  const isShared = grant.isShared;
                  const isChecked = isShared || selectedClassesToShare.includes(grant.classId);
                  const isArchived = cls.status !== 'ACTIVE';
                  const isDisabled = mutationBlocked || isShared || isArchived;

                  return (
                    <label
                      key={grant.classId}
                      className={`lumi-source-share-item ${isShared ? 'is-shared' : ''} ${isArchived ? 'is-archived' : ''}`}
                    >
                      <input
                        type="checkbox"
                        disabled={isDisabled}

                        checked={isChecked}
                        onChange={e => {
                          if (isShared || isArchived) return;
                          if (e.target.checked) {
                            setSelectedClassesToShare(prev => [...prev, grant.classId]);
                          } else {
                            setSelectedClassesToShare(prev => prev.filter(id => id !== grant.classId));
                          }
                        }}
                      />
                      <div className="lumi-source-share-item-info">
                        <span className="lumi-source-share-class-name">{grant.className}</span>
                        <span className="lumi-source-share-class-code">({grant.classCode})</span>
                      </div>
                      {isShared ? (
                        <span className="lumi-source-grant-badge-shared">
                          Đang chia sẻ; thu hồi tại danh sách lớp bên dưới
                        </span>
                      ) : isArchived ? (
                        <span className="lumi-source-badge lumi-source-badge-archived">
                          Lớp đã lưu trữ
                        </span>
                      ) : null}
                    </label>
                  );
                })}
              </div>
            </>
          )}

          <div className="lumi-source-dialog-actions">
            <button
              id="ux-doc-cancel-share"
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setShareOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-confirm-share"
              type="button"
              className="button primary lumi-source-dialog-btn"
              onClick={handleConfirmShare}
              disabled={mutationBlocked || !newTargets.length}
            >
              {isPending ? 'Đang cấp quyền…' : 'Cấp quyền cho lớp đã chọn'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* D05: Confirm Revoke Grant Dialog (Rule B6) */}
      <Dialog
        busy={isPending}
        open={Boolean(revokeClass)}
        title="Xác nhận thu hồi quyền chia sẻ"
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setRevokeClass(null);
        }}
      >
        <div id="ux-revoke-dialog" className="lumi-source-dialog-content">
          <GrantMutationNotice
            busy={grantAction.busy}
            unknown={Boolean(grantAction.unknown)}
            error={grantAction.error}
            message={grantAction.message}
            onReconcile={() => void grantAction.reconcile(() => { setRevokeClass(null); reload(); })}
          />
          <ErrorNotice message={actionError}/>
          <p className="lumi-source-dialog-text">
            Bạn có chắc chắn muốn thu hồi quyền truy cập tài liệu <strong>{doc.title}</strong> khỏi lớp{' '}
            <strong>{revokeClass?.className}</strong>?
          </p>
          <div className="lumi-source-impact-notice" role="note">
            <div className="lumi-source-impact-title">⚠️ Ảnh hưởng khi thu hồi quyền chia sẻ:</div>
            <ul className="lumi-source-impact-list">
              <li>Học sinh trong lớp không thể mở tài liệu nguồn.</li>
              <li>Trợ lý Lumi không còn truy xuất hoặc trích dẫn nội dung tài liệu này trong lớp.</li>
              <li>Các đoạn trích dẫn nguyên văn trong ghi chú cá nhân sẽ bị ẩn; nội dung ghi chú riêng của học sinh vẫn được bảo lưu.</li>
              <li>Quyền truy cập của các lớp học khác không bị ảnh hưởng.</li>
            </ul>
          </div>

          <div className="lumi-source-dialog-actions">
            <button
              id="ux-doc-cancel-revoke"
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setRevokeClass(null)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-revoke"
              type="button"
              className="button danger lumi-source-dialog-btn"
              onClick={handleConfirmRevoke}
              disabled={mutationBlocked || revokeClass?.classStatus !== 'ACTIVE'}
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
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setDeleteOpen(false);
        }}
      >
        <div id="ux-delete-dialog" className="lumi-source-dialog-content">
          <ErrorNotice message={actionError}/>
          <p className="lumi-source-dialog-text">
            Bạn có chắc chắn muốn xóa tài liệu nguồn <strong>{doc.title}</strong>?
          </p>
          <div className="lumi-source-danger-notice" role="alert">
            ⚠️ Toàn bộ các phiên bản và liên kết chia sẻ tới các lớp sẽ bị xóa hoàn toàn. Thao tác này không thể hoàn tác.
          </div>

          <div className="lumi-source-dialog-actions">
            <button
              id="ux-doc-cancel-delete"
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setDeleteOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              id="ux-doc-delete"
              type="button"
              className="button danger lumi-source-dialog-btn"
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
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setNewVersionOpen(false);
        }}
      >
        <form onSubmit={handleUploadVersionSubmit} className="lumi-source-dialog-content">
          <ErrorNotice message={actionError}/>

          <div className="lumi-source-form-group">
            <label htmlFor="ux-doc-version-file-input" className="lumi-source-form-label">
              Chọn tệp phiên bản mới
            </label>
            <input
              id="ux-doc-version-file-input"
              type="file"
              disabled={isPending}
              className="lumi-source-file-input"
              accept={data.capabilityPolicy?.allowedExtensions.join(',')}
              onChange={e => {
                const selection = documentFileSelection(e.target.files?.[0], data.capabilityPolicy);
                setSelectedFile(selection.file); setActionError(selection.error);
                if (!selection.file) e.target.value = '';
              }}
              required
            />
          </div>

          <p className="lumi-source-dialog-desc">
            Phiên bản tiếp theo sẽ là v{Math.max(doc.currentVersion, ...versions.map(v => v.versionNumber)) + 1}. Nếu phiên bản này xử lý thành công, hệ thống sẽ tự động
            phục vụ bản mới nhất cho các lớp được chia sẻ.
          </p>

          <div className="lumi-source-dialog-actions">
            <button
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setNewVersionOpen(false)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button type="submit" className="button primary lumi-source-dialog-btn" disabled={isPending || !selectedFile}>
              {isPending ? 'Đang tải lên…' : 'Tải lên phiên bản'}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
