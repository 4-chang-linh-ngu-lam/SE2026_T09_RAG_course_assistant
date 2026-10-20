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
    <div className="teacher-class-docs-container space-y-6">
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
        <div className="card p-3.5 bg-blue-50 border border-blue-200 text-blue-900 rounded-xl flex items-center gap-3 text-xs">
          <Icon name="info" />
          <span>
            Bạn đang tham gia với vai trò <strong>Giáo viên phối hợp</strong> tại lớp này. Bạn có thể gỡ chia sẻ tài liệu
            khỏi lớp. Chỉ chủ sở hữu tài liệu mới có quyền sửa đổi nội dung nguồn và cập nhật phiên bản.
          </span>
        </div>
      )}

      {/* Toolbar */}
      <div className="card p-4 flex justify-between items-center">
        <div>
          <h2 className="text-base font-bold text-on-surface">Tài liệu đã chia sẻ trong lớp</h2>
          <p className="text-xs muted">
            {classDocuments.length} tài liệu đang phục vụ học sinh lớp {classSummary?.name ?? ''}
          </p>
        </div>

        {classSummary?.status === 'ACTIVE' ? (
          <Link
            id="ux-class-add-doc"
            href="/teacher/library"
            className="button primary small flex items-center gap-1.5 lumi-class-btn-add"
          >
            <Icon name="plus" />
            <span>Thêm tài liệu từ thư viện</span>
          </Link>
        ) : (
          <button
            id="ux-class-add-doc"
            type="button"
            disabled
            className="button primary small flex items-center gap-1.5 lumi-class-btn-add"
            title="Lớp học đã lưu trữ, không thể thêm tài liệu"
          >
            <Icon name="plus" />
            <span>Thêm tài liệu từ thư viện</span>
          </button>
        )}
      </div>

      {/* Class Documents Table */}
      {classDocuments.length === 0 ? (
        <div className="card p-8 text-center lumi-class-docs-empty">
          <p className="muted text-sm">Lớp học này chưa có tài liệu nào được chia sẻ.</p>
          {classSummary?.status === 'ACTIVE' && (
            <Link href="/teacher/library" className="button secondary small mt-3 inline-block">
              Mở thư viện tài liệu để chia sẻ
            </Link>
          )}
        </div>
      ) : (
        <div className="card table-container overflow-x-auto">
          <table className="table w-full text-left text-sm" aria-label="Danh sách tài liệu trong lớp">
            <thead>
              <tr className="border-b text-xs text-muted uppercase">
                <th className="p-3">Tên tài liệu</th>
                <th className="p-3">Định dạng</th>
                <th className="p-3">Phiên bản phục vụ</th>
                <th className="p-3">Chủ sở hữu</th>
                <th className="p-3">Trạng thái</th>
                <th className="p-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {classDocuments.map(doc => {
                const libraryHref = routeHref('t.libraryDocument', { documentId: doc.id }) ?? `/teacher/library/${doc.id}`;
                return (
                  <tr key={doc.id} className="hover:bg-surface-container-low">
                    <td className="p-3 font-medium">
                      <div className="flex items-center gap-2">
                        <Icon name="file" />
                        <span>{doc.title}</span>
                      </div>
                      {doc.locatorCountLabel && <span className="text-xs muted">{doc.locatorCountLabel}</span>}
                    </td>
                    <td className="p-3">
                      <span className="badge primary text-xs">{doc.format}</span>
                    </td>
                    <td className="p-3 text-xs">v{doc.currentVersion}</td>
                    <td className="p-3 text-xs">
                      {doc.ownerName}
                      {doc.canManageSource && <span className="badge info text-xs ml-1.5">Của bạn</span>}
                    </td>
                    <td className="p-3">
                      <span className="badge success text-xs">Đang phục vụ</span>
                    </td>
                    <td className="p-3 text-right space-x-2">
                      {doc.canManageSource ? (
                        <Link href={libraryHref} className="button small secondary">
                          Quản lý nguồn
                        </Link>
                      ) : (
                        <button className="button small" onClick={() => setSourcePreview({classId: params.classId, documentId: doc.id, version: doc.currentVersion})}>Đọc nguồn</button>
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
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
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
