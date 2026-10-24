'use client';

import { ErrorNotice } from '@/components/ui';

export interface GrantMutationNoticeProps {
  busy: boolean;
  unknown: boolean;
  error: string | null;
  message: string | null;
  onReconcile(): void;
  onRetryOriginal?(): void;
}

export function GrantMutationNotice({
  busy,
  unknown,
  error,
  message,
  onReconcile,
  onRetryOriginal,
}: GrantMutationNoticeProps) {
  if (!unknown && !error && !message) {
    return null;
  }

  return (
    <div className="lumi-grant-mutation-notice-wrapper">
      {error && <ErrorNotice message={error} />}
      {!unknown && message && (
        <div className="notice success" role="status">
          <p>{message}</p>
        </div>
      )}
      {unknown && (
        <div className="notice warning lumi-grant-mutation-unknown" role="status">
          <p className="lumi-grant-unknown-text">
            Chưa xác định được kết quả cập nhật quyền chia sẻ. Hệ thống tạm khóa thao tác gửi lại để tránh xung đột dữ liệu. Vui lòng đối soát trạng thái trước khi tiếp tục.
          </p>
          <button
            type="button"
            className="button secondary small lumi-grant-btn-reconcile"
            onClick={onReconcile}
            disabled={busy}
          >
            Kiểm tra trạng thái chia sẻ
          </button>
          {onRetryOriginal&&<button type="button" className="button secondary small" disabled={busy} onClick={onRetryOriginal}>Gửi lại đúng yêu cầu chia sẻ đã lưu</button>}
        </div>
      )}
    </div>
  );
}
