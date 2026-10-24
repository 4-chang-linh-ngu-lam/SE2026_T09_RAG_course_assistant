'use client';

import React, { useState, useRef, useEffect, type FormEvent, type ChangeEvent } from 'react';
import type { CoreAdminState, StaffDraft, ResolutionDraft } from '@/lib/core-admin-controller';
import type { AdminReason } from '@/lib/api/operations';
import { adminReasons } from '@/lib/api/operations';

const ADMIN_REASON_LABELS: Record<AdminReason, string> = {
  ADMIN_INTERVENTION: 'Can thiệp quản trị',
  USER_REQUEST: 'Theo yêu cầu người dùng',
  POLICY_VIOLATION: 'Vi phạm chính sách',
};

const REQUEST_TYPE_LABELS: Record<string, string> = {
  ACCESS: 'Truy cập dữ liệu',
  EXPORT: 'Xuất bản sao dữ liệu',
  CORRECTION: 'Đính chính dữ liệu',
  DELETE: 'Xóa dữ liệu',
};

const REQUEST_STATUS_LABELS: Record<string, string> = {
  PENDING: 'Chờ tiếp nhận',
  IN_REVIEW: 'Đang xem xét',
  COMPLETED: 'Đã hoàn thành',
  REJECTED: 'Từ chối',
};

const RESOLUTION_NOTE_LABELS: Record<ResolutionDraft['resolution_note'], string> = {
  VERIFICATION_IN_PROGRESS: 'Đang xác minh thông tin',
  POLICY_PENDING: 'Chờ chính sách dữ liệu',
  OUTSIDE_CORE_SCOPE: 'Ngoài phạm vi xử lý',
  INSUFFICIENT_VERIFICATION: 'Không đủ thông tin xác minh',
  REQUEST_REJECTED: 'Từ chối yêu cầu',
  DUPLICATE_REQUEST: 'Yêu cầu trùng lặp',
};

const IMPORT_ACTION_LABELS: Record<string, string> = {
  CREATE: 'Tạo mới',
  EXISTING: 'Đã tồn tại',
  ASSIGN_USERNAME: 'Gán tên đăng nhập',
};

const IMPORT_OUTCOME_LABELS: Record<string, string> = {
  CREATED: 'Đã tạo mới',
  EXISTING: 'Đã tồn tại',
  USERNAME_ASSIGNED: 'Đã gán tên đăng nhập',
};

const USER_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Đang hoạt động',
  PENDING_VERIFICATION: 'Chờ xác nhận',
  LOCKED: 'Đã khóa',
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    return date.toLocaleString('vi-VN');
  } catch {
    return iso;
  }
}

function IssueNotice({ issue }: { issue: { message: string; correlationId?: string } | null }) {
  if (!issue) return null;
  return (
    <div className="notice error" role="alert">
      <p style={{ margin: 0, fontWeight: 600 }}>{issue.message}</p>
      {issue.correlationId && (
        <p style={{ margin: '6px 0 0', fontSize: '12px' }}>
          Mã đối chiếu: <code>{issue.correlationId}</code>
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 1. CoreStaffInviteView
// ---------------------------------------------------------------------------

export function CoreStaffInviteView({
  state,
  onSubmit,
}: {
  state: CoreAdminState;
  onSubmit(input: StaffDraft): void;
}) {
  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState<('LECTURER' | 'ADMIN')[]>(['LECTURER']);
  const [reason, setReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const isUnknown = state.unknown === 'staff';
  const isBusy = state.busy;

  const handleRoleToggle = (role: 'LECTURER' | 'ADMIN') => {
    setRoles(current =>
      current.includes(role) ? current.filter(r => r !== role) : [...current, role]
    );
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (isBusy || isUnknown || !email.trim() || !roles.length) return;
    onSubmit({
      email: email.trim().toLowerCase(),
      roles,
      reason,
    });
  };

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <h2>Mời cán bộ & giáo viên</h2>
        <p className="muted">
          Cán bộ và giáo viên nhà trường sẽ nhận được liên kết để thiết lập mật khẩu qua email.
        </p>

        <IssueNotice issue={state.issue} />

        {isUnknown && (
          <div className="notice error" role="alert">
            <p style={{ margin: 0, fontWeight: 600 }}>
              Chưa xác định được kết quả gửi lời mời
            </p>
            <p style={{ margin: '6px 0 0', fontSize: '13px' }}>
              Yêu cầu chưa nhận được phản hồi xác nhận từ máy chủ. Thao tác gửi lại tạm thời bị khóa để tránh tạo trùng lặp. Vui lòng đối soát thông tin trước khi thực hiện lại.
            </p>
          </div>
        )}

        {state.staff && (
          <div className="notice success" role="status">
            <h3 style={{ margin: '0 0 8px', fontSize: '15px' }}>Đã gửi lời mời nhân sự thành công</h3>
            <p style={{ margin: '0 0 8px', fontSize: '13px' }}>
              Thông tin nhân sự đã được ghi nhận để phát liên kết thiết lập mật khẩu.
            </p>
            <ul style={{ margin: '0 0 8px', paddingLeft: '20px', fontSize: '13px' }}>
              <li><strong>Mã nhân sự:</strong> <code>{state.staff.id}</code></li>
              <li><strong>Email:</strong> {state.staff.email ?? '—'}</li>
              <li><strong>Tên đăng nhập:</strong> {state.staff.username ?? 'Chưa tạo'}</li>
              <li><strong>Họ tên:</strong> {state.staff.display_name ?? 'Chưa cập nhật'}</li>
              <li><strong>Trạng thái:</strong> {USER_STATUS_LABELS[state.staff.status] ?? state.staff.status}</li>
            </ul>
          </div>
        )}

        <form className="form-stack" onSubmit={handleSubmit} style={{ marginTop: '20px' }}>
          <label>
            Email nhân sự
            <input
              type="email"
              required
              maxLength={320}
              value={email}
              disabled={isBusy || isUnknown}
              placeholder="nhansu@truong.edu.vn"
              onChange={e => setEmail(e.target.value)}
            />
          </label>

          <fieldset style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', margin: 0 }}>
            <legend style={{ padding: '0 6px', color: '#64748b', fontSize: '13px', fontWeight: 600 }}>
              Vai trò nhân sự (chọn ít nhất một)
            </legend>
            <label className="check-label" style={{ marginTop: '8px' }}>
              <input
                type="checkbox"
                checked={roles.includes('LECTURER')}
                disabled={isBusy || isUnknown}
                onChange={() => handleRoleToggle('LECTURER')}
              />
              Giáo viên
            </label>
            <label className="check-label" style={{ marginTop: '8px' }}>
              <input
                type="checkbox"
                checked={roles.includes('ADMIN')}
                disabled={isBusy || isUnknown}
                onChange={() => handleRoleToggle('ADMIN')}
              />
              Quản trị viên
            </label>
          </fieldset>

          <label>
            Căn cứ / Lý do quản trị
            <select
              value={reason}
              disabled={isBusy || isUnknown}
              onChange={e => setReason(e.target.value as AdminReason)}
            >
              {adminReasons.map(r => (
                <option key={r} value={r}>
                  {ADMIN_REASON_LABELS[r]}
                </option>
              ))}
            </select>
          </label>

          <div className="accounts-actions">
            <button
              type="submit"
              className="button primary"
              disabled={isBusy || isUnknown || !email.trim() || !roles.length}
            >
              {isBusy ? 'Đang gửi lời mời…' : 'Gửi lời mời nhân sự'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. CoreImportView
// ---------------------------------------------------------------------------

export function CoreImportView({
  state,
  onPreview,
  onConfirm,
  onReconfirm,
  onClearCodes,
}: {
  state: CoreAdminState;
  onPreview(file: File): void;
  onConfirm(reason: AdminReason): void;
  onReconfirm(reason: AdminReason): void;
  onClearCodes(): void;
}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [reason, setReason] = useState<AdminReason>('ADMIN_INTERVENTION');
  const [acknowledged, setAcknowledged] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isBusy = state.busy;
  const isUnknownPreview = state.unknown === 'preview';
  const isUnknownConfirm = state.unknown === 'confirm';
  const hasReceipt = !!state.receipt;
  const hasPreview = !!state.preview;
  const canPreview = !isBusy && !hasReceipt && state.unknown === null && !hasPreview && !!selectedFile;
  const canConfirm =
    !isBusy &&
    !hasReceipt &&
    state.unknown === null &&
    hasPreview &&
    state.preview?.valid &&
    !!state.preview?.preview_id &&
    acknowledged;

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setAcknowledged(false);
  };

  const handlePreviewSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !canPreview) return;
    onPreview(selectedFile);
  };

  const handleConfirmSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canConfirm) return;
    onConfirm(reason);
  };

  const handleClear = () => {
    setSelectedFile(null);
    setAcknowledged(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    onClearCodes();
  };

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <h2>Nhập danh sách học sinh từ tệp</h2>
        <p className="muted">
          Tải lên tệp CSV UTF-8 hoặc Excel XLSX để kiểm tra toàn bộ dữ liệu và xem trước kết quả trước khi ghi nhận.
        </p>

        <IssueNotice issue={state.issue} />

        {isUnknownPreview && (
          <div className="notice error" role="alert">
            <p style={{ margin: 0, fontWeight: 600 }}>Chưa nhận được bản xem trước</p>
            <p style={{ margin: '6px 0 0', fontSize: '13px' }}>
              Chưa nhận được bản xem trước. Tải lại trang và chọn lại tệp để kiểm tra.
            </p>
          </div>
        )}

        {/* RECEIPT PRESENTATION & SENSITIVE CODE DISCLOSURE */}
        {state.receipt && (
          <div style={{ marginTop: '20px', borderTop: '2px solid #e2e8f0', paddingTop: '20px' }}>
            <div className="notice success" role="status">
              <h3 style={{ margin: '0 0 8px', fontSize: '16px' }}>Biên nhận nhập danh sách học sinh</h3>
              <p style={{ margin: '0 0 6px', fontSize: '13px' }}>
                <strong>Mã phiên xem trước:</strong> <code>{state.receipt.preview_id}</code> · <strong>Trạng thái:</strong> {state.receipt.status}
              </p>
              <p style={{ margin: '0 0 6px', fontSize: '13px' }}>
                <strong>Hình thức xác nhận:</strong>{' '}
                {state.receipt.replayed ? 'Xác nhận lại (kết quả đã có)' : 'Xác nhận lần đầu'}
              </p>
              <p className="muted" style={{ margin: '8px 0 0', fontSize: '12px' }}>
                Mã kích hoạt một lần chỉ hiển thị duy nhất tại màn hình này và sẽ không hiển thị lại. Quản trị viên vui lòng bàn giao mã an toàn cho học sinh trước khi hoàn tất và xóa hiển thị.
              </p>
            </div>

            <div className="accounts-table-scroll" tabIndex={0} aria-label="Kết quả chi tiết từng dòng nhập" style={{ marginTop: '16px' }}>
              <table>
                <thead>
                  <tr>
                    <th>Dòng</th>
                    <th>Kết quả</th>
                    <th>Tên đăng nhập</th>
                    <th>ID học sinh</th>
                    <th>Mã kích hoạt một lần</th>
                    <th>Thời hạn mã</th>
                  </tr>
                </thead>
                <tbody>
                  {state.receipt.items.map(item => (
                    <tr key={item.row}>
                      <td><strong>{item.row}</strong></td>
                      <td>{IMPORT_OUTCOME_LABELS[item.outcome] ?? item.outcome}</td>
                      <td><code>{item.student.username ?? '—'}</code></td>
                      <td><small>{item.student.id}</small></td>
                      <td>
                        {item.code !== null ? (
                          <strong style={{ color: '#0f766e', fontSize: '14px', letterSpacing: '0.05em' }}>
                            {item.code}
                          </strong>
                        ) : state.receipt?.replayed ? (
                          <span className="muted">Mã đã phát hành sẽ không hiển thị lại</span>
                        ) : (
                          <span className="muted">Không phát hành mã</span>
                        )}
                      </td>
                      <td>{formatDate(item.expires_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="accounts-actions" style={{ marginTop: '20px' }}>
              <button
                type="button"
                className="button primary"
                disabled={isBusy}
                onClick={handleClear}
              >
                Tôi đã bàn giao mã an toàn — Xóa mã hiển thị & Hoàn tất
              </button>
            </div>
          </div>
        )}

        {/* UNKNOWN CONFIRMATION & DELIBERATE RE-CONFIRMATION */}
        {isUnknownConfirm && (
          <div className="notice error" role="alert" style={{ marginTop: '20px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>Chưa nhận được kết quả xác nhận nhập</p>
            <p style={{ margin: '6px 0 0', fontSize: '13px' }}>
              Yêu cầu xác nhận chưa nhận được phản hồi từ máy chủ. Khi gửi lại, hệ thống có thể hoàn tất lần nhập hoặc trả kết quả đã có. Mã đã phát hành sẽ không hiển thị lại.
            </p>
            <div className="accounts-actions" style={{ marginTop: '14px' }}>
              <button
                type="button"
                className="button primary"
                disabled={isBusy}
                onClick={() => onReconfirm(reason)}
              >
                {isBusy ? 'Đang gửi lại xác nhận…' : 'Xác nhận lại theo mã phiên nhập'}
              </button>
            </div>
          </div>
        )}

        {/* UPLOAD & PREVIEW CONTROLS (Only visible if no receipt is pending acknowledgment) */}
        {!hasReceipt && (
          <>
            <form className="form-stack" onSubmit={handlePreviewSubmit} style={{ marginTop: '20px' }}>
              <div style={{ background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '10px', padding: '16px' }}>
                <p style={{ margin: '0 0 8px', fontWeight: 600, fontSize: '14px' }}>
                  Yêu cầu định dạng tệp nguồn:
                </p>
                <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: '#475569', lineHeight: 1.6 }}>
                  <li>Dung lượng tối đa: <strong>2.000.000 bytes</strong> (2 MB); số lượng tối đa: <strong>100 dòng</strong> dữ liệu.</li>
                  <li>Dòng đầu tiên bắt buộc phải chứa đúng tên các cột: <code>username</code> (bắt buộc), <code>display_name</code> (tùy chọn), <code>user_id</code> (tùy chọn).</li>
                  <li>Các ô chứa <code>username</code> phải ở định dạng văn bản (text) để bảo toàn ký tự số (như số 0 ở đầu).</li>
                  <li>Hệ thống kiểm tra toàn bộ tệp; tất cả các lỗi phải được khắc phục trước khi có thể xác nhận nhập.</li>
                </ul>
              </div>

              <label>
                Chọn tệp dữ liệu CSV hoặc XLSX
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx"
                  disabled={isBusy || state.unknown !== null || hasPreview}
                  onChange={handleFileChange}
                />
              </label>

              {selectedFile && (
                <p className="muted" style={{ margin: 0, fontSize: '13px' }}>
                  Tệp đã chọn: <strong>{selectedFile.name}</strong> ({selectedFile.size.toLocaleString('vi-VN')} bytes)
                </p>
              )}

              <div className="accounts-actions">
                <button
                  type="submit"
                  className="button primary"
                  disabled={!canPreview}
                >
                  {isBusy && !hasPreview ? 'Đang kiểm tra tệp…' : 'Xem trước danh sách'}
                </button>
                {hasPreview && !hasReceipt && state.unknown === null && (
                  <button
                    type="button"
                    className="button"
                    disabled={isBusy}
                    onClick={handleClear}
                  >
                    Chọn tệp khác
                  </button>
                )}
              </div>
            </form>

            {/* PREVIEW RESULT & CONFIRMATION SECTION */}
            {state.preview && (
              <div style={{ marginTop: '28px', borderTop: '1px solid #e2e8f0', paddingTop: '20px' }}>
                <h3>Kết quả kiểm tra danh sách</h3>
                <p className="muted" style={{ fontSize: '13px' }}>
                  {state.filename ? `Tệp: ${state.filename} · ` : ''}
                  Mã phiên xem trước: <code>{state.preview.preview_id ?? 'Chưa cấp'}</code>
                  {state.preview.expires_at ? ` · Hạn phiên: ${formatDate(state.preview.expires_at)}` : ''}
                </p>

                <p style={{ fontSize: '14px' }}>
                  Trạng thái hợp lệ:{' '}
                  <strong style={{ color: state.preview.valid ? '#166534' : '#b91c1c' }}>
                    {state.preview.valid ? 'Hợp lệ — Sẵn sàng nhập' : 'Không hợp lệ — Có lỗi dữ liệu'}
                  </strong>
                </p>

                {state.preview.errors.length > 0 && (
                  <div className="notice error" role="alert">
                    <p style={{ margin: '0 0 6px', fontWeight: 600 }}>
                      Phát hiện {state.preview.errors.length} lỗi trong tệp nguồn:
                    </p>
                    <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px' }}>
                      {state.preview.errors.map((err, idx) => (
                        <li key={idx}>
                          Dòng {err.row}: Mã lỗi <code>{err.code}</code>
                        </li>
                      ))}
                    </ul>
                    <p style={{ margin: '8px 0 0', fontSize: '12px' }}>
                      Cần chỉnh sửa lại tệp nguồn và chọn lại tệp. Tất cả các lỗi phải được khắc phục trước khi có thể xác nhận nhập.
                    </p>
                  </div>
                )}

                {state.preview.items.length > 0 && (
                  <div className="accounts-table-scroll" tabIndex={0} aria-label="Bản xem trước dữ liệu">
                    <table>
                      <thead>
                        <tr>
                          <th>Dòng</th>
                          <th>Hành động</th>
                          <th>Tên đăng nhập (username)</th>
                          <th>ID người dùng (user_id)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {state.preview.items.map(item => (
                          <tr key={item.row}>
                            <td><strong>{item.row}</strong></td>
                            <td>{IMPORT_ACTION_LABELS[item.action] ?? item.action}</td>
                            <td><code>{item.username}</code></td>
                            <td><small>{item.user_id ?? '—'}</small></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* CONFIRMATION FORM */}
                {state.preview.valid && state.preview.preview_id && (
                  <form className="form-stack" onSubmit={handleConfirmSubmit} style={{ marginTop: '24px', borderTop: '1px solid #e2e8f0', paddingTop: '20px' }}>
                    <label>
                      Căn cứ / Lý do xác nhận nhập
                      <select
                        value={reason}
                        disabled={isBusy || state.unknown !== null}
                        onChange={e => setReason(e.target.value as AdminReason)}
                      >
                        {adminReasons.map(r => (
                          <option key={r} value={r}>
                            {ADMIN_REASON_LABELS[r]}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={acknowledged}
                        disabled={isBusy || state.unknown !== null}
                        onChange={e => setAcknowledged(e.target.checked)}
                      />
                      Tôi xác nhận tạo mới và cập nhật các dòng tài khoản học sinh theo danh sách xem trước trên.
                    </label>

                    <div className="accounts-actions">
                      <button
                        type="submit"
                        className="button primary"
                        disabled={!canConfirm}
                      >
                        {isBusy ? 'Đang thực hiện nhập…' : 'Xác nhận nhập danh sách'}
                      </button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3. CoreDataRequestsView
// ---------------------------------------------------------------------------

export function CoreDataRequestsView({
  state,
  onReload,
  onSelect,
  onResolve,
}: {
  state: CoreAdminState;
  onReload(): void;
  onSelect(id: string): void;
  onResolve(input: ResolutionDraft): void;
}) {
  const [resolutionStatus, setResolutionStatus] = useState<ResolutionDraft['status']>('IN_REVIEW');
  const [resolutionNote, setResolutionNote] = useState<ResolutionDraft['resolution_note']>('VERIFICATION_IN_PROGRESS');
  const [identityVerified, setIdentityVerified] = useState(false);
  const [reason, setReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const selectedId = state.selected?.id;

  useEffect(() => {
    setIdentityVerified(false);
    setResolutionStatus('IN_REVIEW');
    setResolutionNote('VERIFICATION_IN_PROGRESS');
    setReason('ADMIN_INTERVENTION');
  }, [selectedId]);

  const isBusy = state.busy;
  const isUnknownResolve = state.unknown === 'resolve';
  const selected = state.selected;

  const canResolve =
    !isBusy &&
    !isUnknownResolve &&
    !!selected &&
    (resolutionStatus === 'IN_REVIEW' || identityVerified);

  const handleResolveSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!canResolve) return;
    onResolve({
      status: resolutionStatus,
      resolution_note: resolutionNote,
      identity_verified: identityVerified,
      reason,
    });
  };

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px' }}>Yêu cầu dữ liệu cá nhân</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Xem xét và giải quyết các yêu cầu quyền riêng tư của người dùng theo quy định.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={isBusy}
            onClick={onReload}
          >
            {isBusy && !selected ? 'Đang tải…' : 'Tải lại danh sách'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {isUnknownResolve && (
          <div className="notice error" role="alert" style={{ marginTop: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>Chưa nhận được kết quả cập nhật yêu cầu</p>
            <p style={{ margin: '6px 0 0', fontSize: '13px' }}>
              Yêu cầu chưa nhận được phản hồi xác nhận từ máy chủ. Thao tác cập nhật tạm thời bị khóa. Vui lòng bấm &ldquo;Tải lại danh sách để đối soát&rdquo; để kiểm tra trạng thái mới nhất.
            </p>
            <div className="accounts-actions" style={{ marginTop: '12px' }}>
              <button
                type="button"
                className="button primary"
                disabled={isBusy}
                onClick={onReload}
              >
                {isBusy ? 'Đang tải lại…' : 'Tải lại danh sách để đối soát'}
              </button>
            </div>
          </div>
        )}

        {/* REQUESTS LIST */}
        <div style={{ marginTop: '20px' }}>
          {isBusy && !state.loaded && (
            <p className="muted" role="status">Đang tải danh sách yêu cầu…</p>
          )}

          {state.loaded && state.requests.length === 0 && (
            <p className="muted">Chưa có yêu cầu dữ liệu cá nhân nào.</p>
          )}

          {state.requests.length > 0 && (
            <div className="accounts-table-scroll" tabIndex={0} aria-label="Danh sách yêu cầu dữ liệu">
              <table>
                <thead>
                  <tr>
                    <th>Mã yêu cầu</th>
                    <th>ID người dùng</th>
                    <th>Loại yêu cầu</th>
                    <th>Trạng thái</th>
                    <th>Thời gian gửi</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {state.requests.map(req => {
                    const isRowSelected = selected?.id === req.id;
                    return (
                      <tr
                        key={req.id}
                        style={isRowSelected ? { background: '#eff6ff' } : undefined}
                      >
                        <td><small>{req.id}</small></td>
                        <td><small>{req.user_id}</small></td>
                        <td>{REQUEST_TYPE_LABELS[req.type] ?? req.type}</td>
                        <td>
                          <strong>{REQUEST_STATUS_LABELS[req.status] ?? req.status}</strong>
                        </td>
                        <td>{formatDate(req.created_at)}</td>
                        <td>
                          <button
                            type="button"
                            className="accounts-link"
                            disabled={isBusy || isUnknownResolve}
                            onClick={() => onSelect(req.id)}
                          >
                            {isRowSelected ? 'Đang xem' : 'Xem & xử lý'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* SELECTED DETAIL & RESOLUTION FORM */}
        {selected && (
          <div style={{ marginTop: '28px', borderTop: '2px solid #e2e8f0', paddingTop: '20px' }}>
            <h3>Chi tiết yêu cầu được chọn</h3>

            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', margin: '14px 0' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: '12px', fontSize: '13px' }}>
                <div><strong>Mã yêu cầu:</strong> <code style={{ wordBreak: 'break-all' }}>{selected.id}</code></div>
                <div><strong>ID người dùng:</strong> <code style={{ wordBreak: 'break-all' }}>{selected.user_id}</code></div>
                <div><strong>Loại yêu cầu:</strong> {REQUEST_TYPE_LABELS[selected.type] ?? selected.type}</div>
                <div><strong>Trạng thái máy chủ:</strong> <strong>{REQUEST_STATUS_LABELS[selected.status] ?? selected.status}</strong></div>
                <div><strong>Lý do từ người gửi:</strong> {selected.reason ?? 'Không có lý do'}</div>
                <div><strong>Ghi chú giải quyết hiện tại:</strong> {selected.resolution_note ? (RESOLUTION_NOTE_LABELS[selected.resolution_note as ResolutionDraft['resolution_note']] ?? selected.resolution_note) : 'Chưa có ghi chú'}</div>
                <div><strong>Thời gian gửi:</strong> {formatDate(selected.created_at)}</div>
                <div><strong>Cập nhật lần cuối:</strong> {formatDate(selected.updated_at)}</div>
              </div>
            </div>

            <div className="notice" style={{ fontSize: '13px', lineHeight: 1.6 }}>
              Yêu cầu có thể tiếp tục ở trạng thái đang xem xét sau khi gửi. Quản trị viên vui lòng kiểm tra trạng thái và ghi chú thực tế trả về từ hệ thống.
            </div>

            <form className="form-stack" onSubmit={handleResolveSubmit} style={{ marginTop: '20px' }}>
              <h4>Cập nhật quyết định xem xét yêu cầu</h4>

              <label>
                Quyết định xử lý
                <select
                  value={resolutionStatus}
                  disabled={isBusy || isUnknownResolve}
                  onChange={e => setResolutionStatus(e.target.value as ResolutionDraft['status'])}
                >
                  <option value="IN_REVIEW">Tiếp tục xem xét</option>
                  <option value="COMPLETED">Đề nghị hoàn tất</option>
                  <option value="REJECTED">Từ chối yêu cầu</option>
                </select>
              </label>

              <label>
                Ghi chú giải quyết
                <select
                  value={resolutionNote}
                  disabled={isBusy || isUnknownResolve}
                  onChange={e => setResolutionNote(e.target.value as ResolutionDraft['resolution_note'])}
                >
                  <option value="VERIFICATION_IN_PROGRESS">Đang xác minh thông tin</option>
                  <option value="POLICY_PENDING">Chờ chính sách dữ liệu</option>
                  <option value="OUTSIDE_CORE_SCOPE">Ngoài phạm vi xử lý</option>
                  <option value="INSUFFICIENT_VERIFICATION">Không đủ thông tin xác minh</option>
                  <option value="REQUEST_REJECTED">Từ chối yêu cầu</option>
                  <option value="DUPLICATE_REQUEST">Yêu cầu trùng lặp</option>
                </select>
              </label>

              <label className="check-label">
                <input
                  type="checkbox"
                  checked={identityVerified}
                  disabled={isBusy || isUnknownResolve}
                  onChange={e => setIdentityVerified(e.target.checked)}
                />
                Đã kiểm tra và xác minh danh tính người gửi yêu cầu
              </label>
              {resolutionStatus !== 'IN_REVIEW' && !identityVerified && (
                <p className="muted" style={{ margin: 0, fontSize: '12px', color: '#b91c1c' }}>
                  * Bắt buộc phải xác nhận đã kiểm tra danh tính trước khi đề nghị hoàn tất hoặc từ chối.
                </p>
              )}

              <label>
                Căn cứ / Lý do quản trị
                <select
                  value={reason}
                  disabled={isBusy || isUnknownResolve}
                  onChange={e => setReason(e.target.value as AdminReason)}
                >
                  {adminReasons.map(r => (
                    <option key={r} value={r}>
                      {ADMIN_REASON_LABELS[r]}
                    </option>
                  ))}
                </select>
              </label>

              <div className="accounts-actions">
                <button
                  type="submit"
                  className="button primary"
                  disabled={!canResolve}
                >
                  {isBusy ? 'Đang lưu quyết định…' : 'Xác nhận xử lý yêu cầu'}
                </button>
              </div>
            </form>
          </div>
        )}
      </section>
    </div>
  );
}
