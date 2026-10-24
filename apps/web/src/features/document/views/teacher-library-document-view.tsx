'use client';
import { useEffect, useRef, useState, useTransition } from 'react';
import Link from 'next/link';
import {useGuardedRouter as useRouter} from '@/components/unsaved-changes';
import type { RouteDefinition } from '@/config/routes';
import type { ClassDocumentGrant, DocumentItem, DocumentVersion, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog, ErrorNotice, useUnsavedChanges } from '@/components/ui';
import { useDocumentGrantAction } from '../use-document-grant-action';
import { documentFileError, documentFileSelection } from '@/lib/document-upload';
import { documentVersionState } from '@/lib/document-versions';
import { newShareTargets } from '@/lib/document-sharing';
import { GrantMutationNotice } from '../components/grant-mutation-notice';
import { SourceDocumentSummary, SourceFailureNotice, SourceGrantsPanel, SourceVersionHistory } from '../components/source-management-ui';
import {useDocumentWrite} from '../use-document-write';
import {saveDocumentBlob} from '../save-document-blob';
import {DocumentMetadataForm} from '../components/document-metadata-form';
import {ApiError} from '@/lib/api/errors';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function TeacherLibraryDocumentView({ data, reload }: Props) {
  const router = useRouter();
  const grantAction = useDocumentGrantAction();
  const sourceWrite=useDocumentWrite(data?.kind==='ready'?data.sourceDocumentDetail?.document.id??'source':'source');
  const versionRequest=useRef<string|null>(null);
  const sourceIntent=useRef<{kind:'delete'|'metadata';title?:string;description?:string;revision?:number}|null>(null);
  const [metadataDraft,setMetadataDraft]=useState<{title:string;description:string;revision:number}|null>(null);
  const mutationScope = useRef(0);
  useEffect(() => { ++mutationScope.current; return () => { ++mutationScope.current; }; }, []);
  const [shareOpen, setShareOpen] = useState(false);
  const [revokeClass, setRevokeClass] = useState<ClassDocumentGrant | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteSnapshot,setDeleteSnapshot]=useState<{revision?:number;count:number}|null>(null);
  const [newVersionOpen, setNewVersionOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isOtherPending, startTransition] = useTransition();
  const isPending = isOtherPending || grantAction.busy || sourceWrite.busy;
  const mutationBlocked = isPending || Boolean(grantAction.unknown) || sourceWrite.unknown;
  const originalDocument=data?.kind==='ready'?data.sourceDocumentDetail?.document:undefined;
  const metadataDirty=Boolean(metadataDraft&&(metadataDraft.title!==originalDocument?.title||metadataDraft.description!==(originalDocument?.description??'')));
  useUnsavedChanges(metadataDirty||Boolean(newVersionOpen&&selectedFile));

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
      () => adapter.document.shareDocument(doc.id, newTargets,doc.revision), () => { setShareOpen(false); reload(); });
  };

  const handleConfirmRevoke = () => {
    if (mutationBlocked || !revokeClass || revokeClass.classStatus !== 'ACTIVE') return;
    const classId = revokeClass.classId;
    void grantAction.run({documentId: doc.id, classIds: [classId], shared: false},
      () => adapter.document.revokeShare(doc.id, classId,revokeClass.revision), () => { setRevokeClass(null); reload(); });
  };

  const handleConfirmDelete = () => {
    if(!deleteSnapshot)return;
    sourceIntent.current={kind:'delete'};
    void sourceWrite.run(() => adapter.document.deleteDocument(doc.id,deleteSnapshot.revision,deleteSnapshot.count), () => {
        setDeleteOpen(false);
        requestAnimationFrame(()=>router.push('/teacher/library'));
    });
  };

  const handleUploadVersionSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const fileError = documentFileError(selectedFile, data.capabilityPolicy);
    if (fileError || !selectedFile) { setActionError(fileError); return; }
    const requestId=versionRequest.current??crypto.randomUUID();versionRequest.current=requestId;
    void sourceWrite.run(() => adapter.document.uploadVersion(doc.id, {
          name: selectedFile.name,
          size: selectedFile.size,
          type: selectedFile.type,
          file:selectedFile,requestId,
        }), () => {
        setNewVersionOpen(false);
        setSelectedFile(null);
        versionRequest.current=null;
        reload();
    },requestId);
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

  const reconcileSource=()=>void sourceWrite.reconcile(async()=>{
    if(sourceWrite.receiptId&&adapter.document.uploadReceipt){await adapter.document.uploadReceipt(sourceWrite.receiptId);return true;}
    const intent=sourceIntent.current;if(!intent)return false;
    try{const snapshot=await adapter.workspace.load('t.libraryDocument',{documentId:doc.id});
      if(intent.kind==='delete'||snapshot.kind!=='ready')return false;
      const actual=snapshot.sourceDocumentDetail?.document;
      return Boolean(actual&&actual.title===intent.title&&(actual.description??'')===intent.description&&(actual.revision??0)>(intent.revision??0));
    }catch(error){if(intent.kind==='delete'&&error instanceof ApiError&&error.status===404)return true;throw error;}
  },()=>{if(sourceIntent.current?.kind==='delete'&&!sourceWrite.receiptId){setDeleteOpen(false);requestAnimationFrame(()=>router.push('/teacher/library'));}else{setMetadataDraft(null);setNewVersionOpen(false);setSelectedFile(null);versionRequest.current=null;reload();}});
  const sourceFeedback=<><ErrorNotice message={sourceWrite.error}/>{sourceWrite.unknown&&<div className="actions"><button type="button" className="button" disabled={sourceWrite.busy} onClick={reconcileSource}>Đối soát thay đổi đã gửi</button><button type="button" className="button" disabled={sourceWrite.busy} onClick={()=>void sourceWrite.retryOriginal()}>Gửi lại cùng yêu cầu đã lưu</button></div>}</>;

  return (
    <div className="workspace-content">
      {!metadataDraft&&!deleteOpen&&!newVersionOpen&&sourceFeedback}
      {!shareOpen && !revokeClass && (
        <GrantMutationNotice
          busy={grantAction.busy}
          onRetryOriginal={grantAction.canRetryOriginal?()=>void grantAction.retryOriginal():undefined}
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
        onDelete={() => { setDeleteSnapshot({revision:doc.revision,count:doc.sharedClassCount??0});setDeleteOpen(true); setActionError(null); }}
      />
      {adapter.document.updateMetadata&&doc.revision!==undefined&&<button type="button" className="button" disabled={mutationBlocked} onClick={()=>{sourceWrite.clearError();setMetadataDraft({title:doc.title,description:doc.description??'',revision:doc.revision!});}}>Sửa tên và mô tả</button>}
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
      {adapter.document.download&&servingVersion&&<button type="button" className="button" disabled={mutationBlocked} onClick={()=>{setActionError(null);void adapter.document.download!(doc.id,servingVersion.versionNumber).then(blob=>saveDocumentBlob(blob,servingVersion.filename)).catch(error=>setActionError(error instanceof Error?error.message:'Chưa tải được tệp.'));}}>Tải bản gốc v{servingVersion.versionNumber}</button>}

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
          onRetryOriginal={grantAction.canRetryOriginal?()=>void grantAction.retryOriginal():undefined}
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
                        {grant.classCode&&<span className="lumi-source-share-class-code">({grant.classCode})</span>}
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
          onRetryOriginal={grantAction.canRetryOriginal?()=>void grantAction.retryOriginal():undefined}
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
          {sourceFeedback}
          <ErrorNotice message={actionError}/>
          <ErrorNotice message={sourceWrite.error}/>
          {sourceWrite.unknown&&<p>Đóng hộp thoại rồi kiểm tra lại trạng thái nguồn trước khi thao tác tiếp.</p>}
          <p className="lumi-source-dialog-text">
            Bạn có chắc chắn muốn xóa tài liệu nguồn <strong>{doc.title}</strong>?
          </p>
          <div className="lumi-source-danger-notice" role="alert">
            Nguồn sẽ ngừng phục vụ ở tất cả các lớp. Chữ ghi chú cá nhân được giữ lại; trích dẫn nguồn bị ẩn.
          </div>
          <p>Số lớp bị ảnh hưởng trong lần xác nhận này: <strong>{deleteSnapshot?.count??0}</strong>.</p>
          <ul>{grants.filter(grant=>grant.isShared).map(grant=><li key={grant.classId}>{grant.className}</li>)}</ul>

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
              disabled={mutationBlocked}
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
          {sourceFeedback}
          <ErrorNotice message={actionError}/>
          <ErrorNotice message={sourceWrite.error}/>
          {sourceWrite.unknown&&sourceWrite.receiptId&&adapter.document.uploadReceipt&&<button type="button" className="button" disabled={sourceWrite.busy} onClick={()=>void sourceWrite.reconcile(async()=>{await adapter.document.uploadReceipt!(sourceWrite.receiptId!);return true;},()=>{setNewVersionOpen(false);setSelectedFile(null);versionRequest.current=null;reload();})}>Đối soát phiên bản đã gửi</button>}

          <div className="lumi-source-form-group">
            <label htmlFor="ux-doc-version-file-input" className="lumi-source-form-label">
              Chọn tệp phiên bản mới
            </label>
            <input
              id="ux-doc-version-file-input"
              type="file"
              disabled={mutationBlocked}
              className="lumi-source-file-input"
              accept={data.capabilityPolicy?.allowedExtensions.join(',')}
              onChange={e => {
                const selection = documentFileSelection(e.target.files?.[0], data.capabilityPolicy);
                setSelectedFile(selection.file); setActionError(selection.error);versionRequest.current=null;
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
            <button type="submit" className="button primary lumi-source-dialog-btn" disabled={mutationBlocked || !selectedFile}>
              {isPending ? 'Đang tải lên…' : 'Tải lên phiên bản'}
            </button>
          </div>
        </form>
      </Dialog>
      <Dialog open={metadataDraft!==null} busy={sourceWrite.busy} title="Sửa thông tin tài liệu" onClose={()=>setMetadataDraft(null)} className="lumi-source-dialog">
        {metadataDraft&&<DocumentMetadataForm title={metadataDraft.title} description={metadataDraft.description} busy={sourceWrite.blocked} error={sourceWrite.error} onTitleChange={title=>setMetadataDraft({...metadataDraft,title})} onDescriptionChange={description=>setMetadataDraft({...metadataDraft,description})} onCancel={()=>setMetadataDraft(null)} onSubmit={event=>{event.preventDefault();if(!adapter.document.updateMetadata||sourceWrite.blocked)return;const draft=metadataDraft;sourceIntent.current={kind:'metadata',title:draft.title.trim(),description:draft.description,revision:draft.revision};void sourceWrite.run(()=>adapter.document.updateMetadata!(doc.id,draft.title.trim(),draft.description,draft.revision),()=>{setMetadataDraft(null);reload();});}}/>}
        {sourceWrite.unknown&&sourceFeedback}
      </Dialog>
    </div>
  );
}
