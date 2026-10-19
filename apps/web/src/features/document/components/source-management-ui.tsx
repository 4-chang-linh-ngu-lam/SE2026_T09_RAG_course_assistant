'use client';

import type { DocumentItem, DocumentVersion, ClassDocumentGrant } from '@/lib/domain';
import { Icon } from '@/components/ui';
import './source-management-ui.css';

const PROCESSING_STATUS_LABELS: Record<string, { label: string; className: string }> = {
  READY: { label: 'Sẵn sàng', className: 'lumi-source-badge-ready' },
  PROCESSING: { label: 'Đang xử lý', className: 'lumi-source-badge-processing' },
  PENDING: { label: 'Chờ xử lý', className: 'lumi-source-badge-pending' },
  FAILED: { label: 'Thất bại', className: 'lumi-source-badge-failed' },
};

/* 1. SourceDocumentSummary */
export interface SourceDocumentSummaryProps {
  document: DocumentItem;
  servingVersion: DocumentVersion | null;
  busy: boolean;
  canShare: boolean;
  onShare(): void;
  onUploadVersion(): void;
  onDelete(): void;
}

export function SourceDocumentSummary({
  document,
  servingVersion,
  busy,
  canShare,
  onShare,
  onUploadVersion,
  onDelete,
}: SourceDocumentSummaryProps) {
  const statusInfo = PROCESSING_STATUS_LABELS[document.processingStatus] ?? {
    label: document.processingStatus,
    className: 'lumi-source-badge-pending',
  };

  return (
    <section className="lumi-source-summary-card" aria-labelledby="lumi-source-doc-title">
      <div className="lumi-source-summary-main">
        <div className="lumi-source-summary-info">
          <div className="lumi-source-title-row">
            <h1 id="lumi-source-doc-title" className="lumi-source-title">
              {document.title}
            </h1>
            <span className="lumi-source-badge lumi-source-badge-format">
              {document.format}
            </span>
            <span className={`lumi-source-badge ${statusInfo.className}`}>
              <span className="lumi-source-badge-dot" aria-hidden="true" />
              <span>{statusInfo.label}</span>
            </span>
            {servingVersion ? (
              <span className="lumi-source-badge lumi-source-badge-serving">
                <span className="lumi-source-badge-dot" aria-hidden="true" />
                <span>Bản phục vụ: v{servingVersion.versionNumber}</span>
              </span>
            ) : (
              <span className="lumi-source-badge lumi-source-badge-unserved">
                <span>Chưa có bản phục vụ</span>
              </span>
            )}
          </div>

          <div className="lumi-source-meta-row">
            <span>Chủ sở hữu: {document.ownerName}</span>
            <span className="lumi-source-meta-divider" aria-hidden="true">·</span>
            <span>Ngày tạo: {document.createdAt}</span>
            {document.locatorCountLabel && (
              <>
                <span className="lumi-source-meta-divider" aria-hidden="true">·</span>
                <span>{document.locatorCountLabel}</span>
              </>
            )}
            <span className="lumi-source-meta-divider" aria-hidden="true">·</span>
            <span>Phiên bản hiện hành: v{document.currentVersion}</span>
          </div>

          {document.description && (
            <p className="lumi-source-desc">{document.description}</p>
          )}
        </div>

        <div className="lumi-source-actions">
          <button
            id="ux-doc-open-share"
            type="button"
            className="button lumi-source-btn lumi-source-btn-outline"
            onClick={onShare}
            disabled={busy || !canShare}
            title={!canShare ? 'Không có quyền chia sẻ tài liệu này' : undefined}
          >
            <Icon name="plus" />
            <span>Chia sẻ</span>
          </button>
          <button
            id="ux-doc-upload-version"
            type="button"
            className="button primary lumi-source-btn lumi-source-btn-primary"
            onClick={onUploadVersion}
            disabled={busy}
          >
            <Icon name="upload" />
            <span>Tải phiên bản mới</span>
          </button>
          <button
            id="ux-doc-open-delete"
            type="button"
            className="button danger lumi-source-btn lumi-source-btn-danger lumi-source-btn-icon"
            onClick={onDelete}
            disabled={busy}
            aria-label="Xóa tài liệu nguồn"
            title="Xóa tài liệu nguồn"
          >
            <Icon name="trash" />
          </button>
        </div>
      </div>
    </section>
  );
}

/* 2. SourceFailureNotice */
export interface SourceFailureNoticeProps {
  version: DocumentVersion;
  servingVersion: DocumentVersion | null;
  busy: boolean;
  onRetry(versionNumber: number): void;
}

export function SourceFailureNotice({
  version,
  servingVersion,
  busy,
  onRetry,
}: SourceFailureNoticeProps) {
  const failureMessage = version.errorMessage || 'Tệp tin xử lý thất bại do lỗi phân tích nội dung.';

  return (
    <section className="lumi-source-failure-card" role="alert" aria-live="polite">
      <div className="lumi-source-failure-main">
        <span className="lumi-source-failure-icon" aria-hidden="true">
          <Icon name="info" />
        </span>
        <div className="lumi-source-failure-body">
          <h2 className="lumi-source-failure-title">
            Phiên bản v{version.versionNumber} xử lý thất bại
          </h2>
          <p className="lumi-source-failure-text">
            {servingVersion
              ? `Các lớp được chia sẻ tiếp tục sử dụng phiên bản phục vụ v${servingVersion.versionNumber} đã sẵn sàng trong khi phiên bản thay thế đang được khắc phục.`
              : 'Hiện tại chưa có phiên bản nào sẵn sàng để phục vụ cho các lớp học.'}
          </p>
          <p className="lumi-source-failure-detail">{failureMessage}</p>
        </div>
      </div>
      <div className="lumi-source-failure-action">
        <button
          id={`ux-doc-retry-v${version.versionNumber}`}
          type="button"
          className="lumi-source-btn-retry"
          onClick={() => onRetry(version.versionNumber)}
          disabled={busy}
        >
          {busy ? 'Đang xử lý…' : `Thử lại xử lý v${version.versionNumber}`}
        </button>
      </div>
    </section>
  );
}

/* 3. SourceGrantsPanel */
export interface SourceGrantsPanelProps {
  grants: ClassDocumentGrant[];
  busy: boolean;
  onRevoke(grant: ClassDocumentGrant): void;
}

export function SourceGrantsPanel({ grants, busy, onRevoke }: SourceGrantsPanelProps) {
  return (
    <section className="lumi-source-grants-card" aria-labelledby="lumi-source-grants-heading">
      <div className="lumi-source-grants-header">
        <h2 id="lumi-source-grants-heading" className="lumi-source-section-title">
          Các lớp được cấp quyền chia sẻ
        </h2>
        <p className="lumi-source-section-subtitle">
          Học sinh trong các lớp này có quyền đọc học liệu và trao đổi với trợ lý học tập.
        </p>
      </div>

      {grants.length === 0 ? (
        <div className="lumi-source-empty-state">
          Tài liệu này chưa được chia sẻ cho lớp nào. Chọn &quot;Chia sẻ&quot; để cấp quyền cho lớp học.
        </div>
      ) : (
        <div className="lumi-source-grants-list" role="list">
          {grants.map(grant => (
            <article key={grant.classId} className="lumi-source-grant-item" role="listitem">
              <div className="lumi-source-grant-info">
                <div className="lumi-source-grant-title-line">
                  <span className="lumi-source-grant-name">{grant.className}</span>
                  <span className="lumi-source-grant-code">({grant.classCode})</span>
                </div>
                <div className="lumi-source-grant-meta">
                  <span>Phiên bản phục vụ: v{grant.servingVersion}</span>
                  {grant.grantedAt && <span>Cấp quyền: {grant.grantedAt}</span>}
                </div>
              </div>
              <button
                id={`ux-doc-revoke-class-${grant.classId}`}
                type="button"
                className="lumi-source-btn-revoke"
                onClick={() => onRevoke(grant)}
                disabled={busy}
              >
                Thu hồi chia sẻ
              </button>
            </article>
          ))}
        </div>
      )}

      <p className="lumi-source-policy-note">
        <Icon name="info" />
        <span>
          Thu hồi chia sẻ chỉ áp dụng cho lớp được chọn. Các lớp được chia sẻ khác không bị ảnh hưởng.
        </span>
      </p>
    </section>
  );
}

/* 4. SourceVersionHistory */
export interface SourceVersionHistoryProps {
  versions: DocumentVersion[];
  busy: boolean;
  onRetry(versionNumber: number): void;
}

export function SourceVersionHistory({
  versions,
  busy,
  onRetry,
}: SourceVersionHistoryProps) {
  return (
    <section className="lumi-source-history-card" aria-labelledby="lumi-source-history-heading">
      <div className="lumi-source-history-header">
        <h2 id="lumi-source-history-heading" className="lumi-source-section-title">
          Lịch sử phiên bản tệp
        </h2>
        <span className="lumi-source-history-count">
          {versions.length} phiên bản tổng cộng
        </span>
      </div>

      <div
        className="lumi-source-table-container"
        tabIndex={0}
        role="region"
        aria-label="Bảng lịch sử phiên bản tệp"
      >
        <table className="lumi-source-table">
          <thead>
            <tr>
              <th scope="col">Phiên bản</th>
              <th scope="col">Tệp tin</th>
              <th scope="col">Dung lượng</th>
              <th scope="col">Ngày tải lên</th>
              <th scope="col">Trạng thái xử lý</th>
              <th scope="col">Phục vụ lớp</th>
              <th scope="col" className="lumi-source-table-actions">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {versions.length === 0 ? (
              <tr>
                <td colSpan={7} className="lumi-source-empty-state">
                  Chưa có phiên bản nào được tải lên.
                </td>
              </tr>
            ) : (
              versions.map(v => {
                const statusMeta = PROCESSING_STATUS_LABELS[v.status] ?? {
                  label: v.status,
                  className: 'lumi-source-badge-pending',
                };
                return (
                  <tr key={v.versionNumber} className={v.isServing ? 'is-serving' : undefined}>
                    <td className="lumi-source-table-version-cell">v{v.versionNumber}</td>
                    <td>
                      <div className="lumi-source-table-filename" title={v.filename}>
                        {v.filename}
                      </div>
                    </td>
                    <td>{v.fileSizeFormatted}</td>
                    <td>{v.uploadedAt}</td>
                    <td>
                      <span className={`lumi-source-badge ${statusMeta.className}`}>
                        <span className="lumi-source-badge-dot" aria-hidden="true" />
                        <span>{statusMeta.label}</span>
                      </span>
                    </td>
                    <td>
                      {v.isServing ? (
                        <span className="lumi-source-badge lumi-source-badge-serving">
                          <span className="lumi-source-badge-dot" aria-hidden="true" />
                          <span>Đang phục vụ</span>
                        </span>
                      ) : (
                        <span className="lumi-source-badge lumi-source-badge-unserved">
                          <span>Chưa áp dụng</span>
                        </span>
                      )}
                    </td>
                    <td className="lumi-source-table-actions">
                      {v.status === 'FAILED' ? (
                        <button
                          id={`ux-doc-retry-v${v.versionNumber}`}
                          type="button"
                          className="lumi-source-btn-retry"
                          onClick={() => onRetry(v.versionNumber)}
                          disabled={busy}
                        >
                          Thử lại
                        </button>
                      ) : (
                        <span className="muted text-xs">—</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
