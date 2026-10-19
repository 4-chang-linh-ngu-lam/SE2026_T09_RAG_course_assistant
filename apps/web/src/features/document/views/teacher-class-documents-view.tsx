'use client';
import { ClassSourcePreviewDialog, type SourcePreviewRequest } from '../class-source-preview';
import { useState, useTransition } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { DocumentItem, RouteParams, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog } from '@/components/ui';

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
  const [isPending, startTransition] = useTransition();

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
    if (!revokeDoc || !params.classId) return;
    startTransition(async () => {
      try {
        await adapter.document.revokeShare(revokeDoc.id, params.classId);
        setRevokeDoc(null);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Có lỗi khi gỡ tài liệu khỏi lớp.');
      }
    });
  };

  return (
    <div className="teacher-class-docs-container space-y-6">
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

        <Link
          id="ux-class-add-doc"
          href="/teacher/library"
          className="button primary small flex items-center gap-1.5"
        >
          <Icon name="plus" />
          <span>Thêm tài liệu từ thư viện</span>
        </Link>
      </div>

      {/* Class Documents Table */}
      {classDocuments.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="muted text-sm">Lớp học này chưa có tài liệu nào được chia sẻ.</p>
          <Link href="/teacher/library" className="button secondary small mt-3 inline-block">
            Mở thư viện tài liệu để chia sẻ
          </Link>
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
                        onClick={() => {
                          setRevokeDoc(doc);
                          setActionError(null);
                        }}
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
        onClose={() => {
          if (!isPending) setRevokeDoc(null);
        }}
      >
        <div className="space-y-4 text-sm">
          {actionError && <div className="card p-2 bg-red-50 text-red-700 text-xs">{actionError}</div>}
          <p>
            Bạn có chắc chắn muốn gỡ tài liệu <strong>{revokeDoc?.title}</strong> khỏi lớp{' '}
            <strong>{classSummary?.name}</strong>?
          </p>
          <div className="card p-3 bg-amber-50 text-amber-900 text-xs border border-amber-200 rounded-lg">
            Học sinh trong lớp này sẽ không còn quyền đọc tài liệu và trợ lý Lumi sẽ ngừng trích dẫn nội dung này trong lớp.
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-outline-variant/30">
            <button
              type="button"
              className="button secondary"
              onClick={() => setRevokeDoc(null)}
              disabled={isPending}
            >
              Hủy
            </button>
            <button
              type="button"
              className="button danger"
              onClick={handleConfirmRevoke}
              disabled={isPending}
            >
              {isPending ? 'Đang gỡ…' : 'Xác nhận gỡ khỏi lớp'}
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
