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
    return <StatePanel busy title="Äang táº£i thÃ´ng tin tÃ i liá»‡u nguá»“nâ€¦" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dá»‹ch vá»¥ tÃ i liá»‡u chÆ°a sáºµn sÃ ng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thá»­ láº¡i
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty' || !data.sourceDocumentDetail) {
    return <StatePanel title="KhÃ´ng tÃ¬m tháº¥y tÃ i liá»‡u" message={data.kind === 'empty' ? data.message : 'TÃ i liá»‡u khÃ´ng tá»“n táº¡i.'} />;
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
        setActionError(err instanceof Error ? err.message : 'CÃ³ lá»—i khi xÃ³a tÃ i liá»‡u.');
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
        setActionError(err instanceof Error ? err.message : 'CÃ³ lá»—i khi táº£i lÃªn phiÃªn báº£n má»›i.');
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
        setActionError(err instanceof Error ? err.message : 'CÃ³ lá»—i khi thá»­ láº¡i xá»­ lÃ½.');
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
          <span>Quay láº¡i ThÆ° viá»‡n tÃ i liá»‡u</span>
        </Link>
      </div>

      <SourceDocumentSummary
        document={doc}
        servingVersion={servingVersion}
        busy={mutationBlocked}
        canShare={canShare}
        shareUnavailableReason="Cáº§n má»™t phiÃªn báº£n xá»­ lÃ½ thÃ nh cÃ´ng trÆ°á»›c khi chia sáº»."
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
        title="Cáº¥p thÃªm quyá»n chia sáº» cho lá»›p há»c"
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
          <p className="lumi-source-dialog-desc">Chá»n cÃ¡c lá»›p báº¡n phá»¥ trÃ¡ch Ä‘á»ƒ cáº¥p quyá»n Ä‘á»c há»c liá»‡u vÃ  há»i Lumi:</p>

          <ErrorNotice message={actionError}/>

          {shareableClasses.length === 0 ? (
            <div className="lumi-source-empty-classes">
              KhÃ´ng cÃ³ lá»›p há»c nÃ o kháº£ dá»¥ng Ä‘á»ƒ chia sáº» tÃ i liá»‡u nÃ y.
            </div>
          ) : (
            <>
              {shareableClasses.filter(c => c.status === 'ACTIVE' && !grants.some(g => g.classId === c.id && g.isShared)).length === 0 && (
                <div className="lumi-source-empty-choices-notice" role="status">
                  Táº¥t cáº£ cÃ¡c lá»›p há»c hoáº¡t Ä‘á»™ng Ä‘Ã£ Ä‘Æ°á»£c cáº¥p quyá»n chia sáº» tÃ i liá»‡u nÃ y.
                </div>
              )}
              <div className="lumi-source-share-list" role="group" aria-label="Danh sÃ¡ch lá»›p Ä‘á»ƒ cáº¥p quyá»n chia sáº»">
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
                          Äang chia sáº»; thu há»“i táº¡i danh sÃ¡ch lá»›p bÃªn dÆ°á»›i
                        </span>
                      ) : isArchived ? (
                        <span className="lumi-source-badge lumi-source-badge-archived">
                          Lá»›p Ä‘Ã£ lÆ°u trá»¯
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
              Há»§y
            </button>
            <button
              id="ux-doc-confirm-share"
              type="button"
              className="button primary lumi-source-dialog-btn"
              onClick={handleConfirmShare}
              disabled={mutationBlocked || !newTargets.length}
            >
              {isPending ? 'Äang cáº¥p quyá»nâ€¦' : 'Cáº¥p quyá»n cho lá»›p Ä‘Ã£ chá»n'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* D05: Confirm Revoke Grant Dialog (Rule B6) */}
      <Dialog
        busy={isPending}
        open={Boolean(revokeClass)}
        title="XÃ¡c nháº­n thu há»“i quyá»n chia sáº»"
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
            Báº¡n cÃ³ cháº¯c cháº¯n muá»‘n thu há»“i quyá»n truy cáº­p tÃ i liá»‡u <strong>{doc.title}</strong> khá»i lá»›p{' '}
            <strong>{revokeClass?.className}</strong>?
          </p>
          <div className="lumi-source-impact-notice" role="note">
            <div className="lumi-source-impact-title">âš ï¸ áº¢nh hÆ°á»Ÿng khi thu há»“i quyá»n chia sáº»:</div>
            <ul className="lumi-source-impact-list">
              <li>Há»c sinh trong lá»›p khÃ´ng thá»ƒ má»Ÿ tÃ i liá»‡u nguá»“n.</li>
              <li>Trá»£ lÃ½ Lumi khÃ´ng cÃ²n truy xuáº¥t hoáº·c trÃ­ch dáº«n ná»™i dung tÃ i liá»‡u nÃ y trong lá»›p.</li>
              <li>CÃ¡c Ä‘oáº¡n trÃ­ch dáº«n nguyÃªn vÄƒn trong ghi chÃº cÃ¡ nhÃ¢n sáº½ bá»‹ áº©n; ná»™i dung ghi chÃº riÃªng cá»§a há»c sinh váº«n Ä‘Æ°á»£c báº£o lÆ°u.</li>
              <li>Quyá»n truy cáº­p cá»§a cÃ¡c lá»›p há»c khÃ¡c khÃ´ng bá»‹ áº£nh hÆ°á»Ÿng.</li>
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
              Há»§y
            </button>
            <button
              id="ux-doc-revoke"
              type="button"
              className="button danger lumi-source-dialog-btn"
              onClick={handleConfirmRevoke}
              disabled={mutationBlocked || revokeClass?.classStatus !== 'ACTIVE'}
            >
              {isPending ? 'Äang thu há»“iâ€¦' : 'XÃ¡c nháº­n thu há»“i'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* D06: Confirm Delete Source Dialog */}
      <Dialog
        busy={isPending}
        open={deleteOpen}
        title="XÃ¡c nháº­n xÃ³a tÃ i liá»‡u nguá»“n"
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setDeleteOpen(false);
        }}
      >
        <div id="ux-delete-dialog" className="lumi-source-dialog-content">
          <ErrorNotice message={actionError}/>
          <p className="lumi-source-dialog-text">
            Báº¡n cÃ³ cháº¯c cháº¯n muá»‘n xÃ³a tÃ i liá»‡u nguá»“n <strong>{doc.title}</strong>?
          </p>
          <div className="lumi-source-danger-notice" role="alert">
            âš ï¸ ToÃ n bá»™ cÃ¡c phiÃªn báº£n vÃ  liÃªn káº¿t chia sáº» tá»›i cÃ¡c lá»›p sáº½ bá»‹ xÃ³a hoÃ n toÃ n. Thao tÃ¡c nÃ y khÃ´ng thá»ƒ hoÃ n tÃ¡c.
          </div>

          <div className="lumi-source-dialog-actions">
            <button
              id="ux-doc-cancel-delete"
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setDeleteOpen(false)}
              disabled={isPending}
            >
              Há»§y
            </button>
            <button
              id="ux-doc-delete"
              type="button"
              className="button danger lumi-source-dialog-btn"
              onClick={handleConfirmDelete}
              disabled={isPending}
            >
              {isPending ? 'Äang xÃ³aâ€¦' : 'XÃ¡c nháº­n xÃ³a tÃ i liá»‡u'}
            </button>
          </div>
        </div>
      </Dialog>

      {/* Upload New Version Dialog */}
      <Dialog
        busy={isPending}
        open={newVersionOpen}
        title={`Táº£i lÃªn phiÃªn báº£n má»›i cho ${doc.title}`}
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setNewVersionOpen(false);
        }}
      >
        <form onSubmit={handleUploadVersionSubmit} className="lumi-source-dialog-content">
          <ErrorNotice message={actionError}/>

          <div className="lumi-source-form-group">
            <label htmlFor="ux-doc-version-file-input" className="lumi-source-form-label">
              Chá»n tá»‡p phiÃªn báº£n má»›i
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
            PhiÃªn báº£n tiáº¿p theo sáº½ lÃ  v{Math.max(doc.currentVersion, ...versions.map(v => v.versionNumber)) + 1}. Náº¿u phiÃªn báº£n nÃ y xá»­ lÃ½ thÃ nh cÃ´ng, há»‡ thá»‘ng sáº½ tá»± Ä‘á»™ng
            phá»¥c vá»¥ báº£n má»›i nháº¥t cho cÃ¡c lá»›p Ä‘Æ°á»£c chia sáº».
          </p>

          <div className="lumi-source-dialog-actions">
            <button
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setNewVersionOpen(false)}
              disabled={isPending}
            >
              Há»§y
            </button>
            <button type="submit" className="button primary lumi-source-dialog-btn" disabled={isPending || !selectedFile}>
              {isPending ? 'Äang táº£i lÃªnâ€¦' : 'Táº£i lÃªn phiÃªn báº£n'}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
