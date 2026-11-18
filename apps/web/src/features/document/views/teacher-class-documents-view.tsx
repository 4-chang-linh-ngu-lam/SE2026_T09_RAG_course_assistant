'use client';
import { ClassSourcePreviewDialog, type SourcePreviewRequest } from '../class-source-preview';
import { useState } from 'react';
import { useDocumentGrantAction } from '../use-document-grant-action';
import { GrantMutationNotice } from '../components/grant-mutation-notice';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { DocumentItem, RouteParams, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog, ErrorNotice } from '@/components/ui';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  params: RouteParams;
  reload(): void;
};

export function TeacherClassDocumentsView({ data, params, reload }: Props) {
  const [sourcePreview, setSourcePreview] = useState<SourcePreviewRequest | null>(null);
  const [revokeDoc, setRevokeDoc] = useState<DocumentItem | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const grantAction = useDocumentGrantAction();
  const isPending = grantAction.busy;
  const mutationBlocked = isPending || Boolean(grantAction.unknown);

  if (!data) {
    return <StatePanel busy title="Đang tải danh sách tài liệu lớp…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ tài liệu lớp chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return <StatePanel title="Chưa có tài liệu nào trong lớp" message={data.message} />;
  }

  const classSummary = data.classSummary;
  const classDocuments = data.classDocuments ?? [];
  const isAssisting = classSummary?.teachingRole === 'ASSISTING';

  const handleConfirmRevoke = () => {
    if (mutationBlocked || !revokeDoc?.canRevokeGrant || !params.classId || classSummary?.status !== 'ACTIVE') return;
    const documentId = revokeDoc.id;
    void grantAction.run({documentId, classIds:[params.classId], shared:false, classRoute:params.classId},
      () => adapter.document.revokeShare(documentId, params.classId), () => { setRevokeDoc(null); reload(); });
  };

  return (
    <div className="teacher-class-docs-container">
      {!revokeDoc && (
        <GrantMutationNotice
          busy={isPending}
          unknown={Boolean(grantAction.unknown)}
          error={grantAction.error}
          message={grantAction.message}
          onReconcile={() => void grantAction.reconcile(() => { setRevokeDoc(null); reload(); })}
        />
      )}
      {/* Role Banner under Rule O1 */}
      {isAssisting && (
        <div className="class-docs-role-banner">
          <Icon name="info" />
          <span>
            Bạn đang tham gia với vai trò <strong>Giáo viên phối hợp</strong> tại lớp này. Bạn có thể gỡ chia sẻ tài liệu
            khỏi lớp. Chỉ chủ sở hữu tài liệu mới có quyền sửa đổi nội dung nguồn và cập nhật phiên bản.
          </span>
        </div>
      )}

      {/* Toolbar */}
      <div className="card class-docs-toolbar">
        <div className="class-docs-toolbar-copy">
          <h2 className="class-docs-title">Tài liệu đã chia sẻ trong lớp</h2>
          <p className="class-docs-subtitle">
            {classDocuments.length} tài liệu đang phục vụ học sinh lớp {classSummary?.name ?? ''}
          </p>
        </div>

        {classSummary?.status === 'ACTIVE' ? (
          <Link
            id="ux-class-add-doc"
            href="/teacher/library"
            className="button primary small lumi-class-btn-add"
          >
            <Icon name="plus" />
            <span>Thêm tài liệu từ thư viện</span>
          </Link>
        ) : (
          <button
            id="ux-class-add-doc"
            type="button"
            disabled
            className="button primary small lumi-class-btn-add"
            title="Lớp học đã lưu trữ, không thể thêm tài liệu"
          >
            <Icon name="plus" />
            <span>Thêm tài liệu từ thư viện</span>
          </button>
        )}
      </div>

      {/* Class Documents Table */}
      {classDocuments.length === 0 ? (
        <div className="card lumi-class-docs-empty">
          <p>Lớp học này chưa có tài liệu nào được chia sẻ.</p>
          {classSummary?.status === 'ACTIVE' && (
            <Link href="/teacher/library" className="button secondary small">
              Mở thư viện tài liệu để chia sẻ
            </Link>
          )}
        </div>
      ) : (
        <div className="card class-docs-table-card">
          <div
            className="class-docs-table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Danh sách tài liệu trong lớp"
          >
            <table className="class-docs-table" aria-label="Danh sách tài liệu trong lớp">
              <thead>
                <tr>
                  <th>Tên tài liệu</th>
                  <th>Định dạng</th>
                  <th>Phiên bản phục vụ</th>
                  <th>Chủ sở hữu</th>
                  <th>Trạng thái</th>
                  <th className="class-docs-actions-col">Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {classDocuments.map(doc => {
                  const libraryHref = routeHref('t.libraryDocument', { documentId: doc.id }) ?? `/teacher/library/${doc.id}`;
                  return (
                    <tr key={doc.id}>
                      <td className="class-docs-title-cell">
                        <div className="class-docs-doc-name">
                          <Icon name="file" />
                          <span>{doc.title}</span>
                        </div>
                        {doc.locatorCountLabel && <span className="class-docs-doc-meta">{doc.locatorCountLabel}</span>}
                      </td>
                      <td>
                        <span className="doc-format-pill" data-format={doc.format.toLowerCase()}>
                          {doc.format}
                        </span>
                      </td>
                      <td className="class-docs-version">v{doc.currentVersion}</td>
                      <td>
                        <div className="class-docs-owner-cell">
                          <span>{doc.ownerName}</span>
                          {doc.canManageSource && <span className="class-docs-owner-badge">Của bạn</span>}
                        </div>
                      </td>
                      <td>
                        <span className="class-docs-status-pill">Đang phục vụ</span>
                      </td>
                      <td className="class-docs-actions-col">
                        <div className="class-docs-row-actions">
                          {doc.canManageSource ? (
                            <Link href={libraryHref} className="button small secondary">
                              Quản lý nguồn
                            </Link>
                          ) : (
                            <button
                              type="button"
                              className="button small secondary"
                              onClick={() => setSourcePreview({classId: params.classId, documentId: doc.id, version: doc.currentVersion})}
                            >
                              Đọc nguồn
                            </button>
                          )}

                          <button
                            type="button"
                            className="button small danger"
                            disabled={mutationBlocked || !doc.canRevokeGrant || classSummary?.status !== 'ACTIVE'}
                            onClick={() => {
                              setRevokeDoc(doc);
                              setActionError(null);
                            }}
                            title={
                              classSummary?.status !== 'ACTIVE'
                                ? 'Lớp học đã lưu trữ, không thể gỡ tài liệu'
                                : !doc.canRevokeGrant
                                ? 'Bạn không có quyền gỡ tài liệu này khỏi lớp'
                                : undefined
                            }
                          >
                            Gỡ khỏi lớp
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <ClassSourcePreviewDialog request={sourcePreview} onClose={() => setSourcePreview(null)}/>
      {/* Revoke Confirm Dialog */}
      <Dialog
        busy={isPending}
        open={Boolean(revokeDoc)}
        title="Gỡ tài liệu khỏi lớp học"
        className="lumi-source-dialog"
        onClose={() => {
          if (!isPending) setRevokeDoc(null);
        }}
      >
        <div id="ux-class-revoke-dialog" className="lumi-source-dialog-content">
          <GrantMutationNotice
            busy={isPending}
            unknown={Boolean(grantAction.unknown)}
            error={grantAction.error}
            message={grantAction.message}
            onReconcile={() => void grantAction.reconcile(() => { setRevokeDoc(null); reload(); })}
          />
          <ErrorNotice message={actionError}/>
          <p className="lumi-source-dialog-text">
            Bạn có chắc chắn muốn gỡ tài liệu <strong>{revokeDoc?.title}</strong> khỏi lớp{' '}
            <strong>{classSummary?.name}</strong>?
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
              type="button"
              className="button secondary lumi-source-dialog-btn"
              onClick={() => setRevokeDoc(null)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              type="button"
              className="button danger lumi-source-dialog-btn"
              onClick={handleConfirmRevoke}
              disabled={mutationBlocked || !revokeDoc?.canRevokeGrant || classSummary?.status !== 'ACTIVE'}
            >
              {isPending ? 'Đang gỡ…' : 'Xác nhận gỡ khỏi lớp'}
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
