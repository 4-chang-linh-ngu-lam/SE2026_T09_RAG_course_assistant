'use client';

import React, { useState, useEffect, useMemo, type FormEvent } from 'react';
import Link from 'next/link';
import type {
  CoreManagementRoute,
  CoreManagementState,
  ManagementCommand,
} from '@/lib/core-management-controller';
import type {
  CoreAcademicYear,
  CoreAdminUser,
  CoreClass,
  CoreCourse,
  CoreHomeroom,
  CoreMember,
  CoreSemester,
  CoreTeacher,
  CoreUser,
} from '@/lib/api/core-contract';
import type { RouteParams, Role, IssuedCode } from '@/lib/domain';
import type { AdminReason } from '@/lib/api/operations';
import { adminReasons } from '@/lib/api/operations';

export type CoreManagementViewProps = {
  routeId: CoreManagementRoute;
  params: RouteParams;
  state: CoreManagementState;
  onReload: () => void;
  onAcknowledgeUnknown: () => void;
  onCommand: ManagementCommand;
  onPreview: () => void;
  onIssueCode: (verified: boolean) => void;
  onClearCode: () => void;
};

const ADMIN_REASON_LABELS: Record<AdminReason, string> = {
  ADMIN_INTERVENTION: 'Can thiệp quản trị',
  USER_REQUEST: 'Theo yêu cầu người dùng',
  POLICY_VIOLATION: 'Vi phạm chính sách',
};

const USER_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Đang hoạt động',
  PENDING_VERIFICATION: 'Chờ xác nhận',
  LOCKED: 'Đã khóa',
};

const ROLE_LABELS: Record<Role, string> = {
  ADMIN: 'Quản trị viên',
  LECTURER: 'Giáo viên',
  STUDENT: 'Học sinh',
};

const CLASS_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Đang hoạt động',
  ARCHIVED: 'Đã lưu trữ',
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    return date.toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' });
  } catch {
    return iso;
  }
}

function getUserLabel(user: CoreUser | CoreAdminUser | null | undefined, fallbackId?: string): string {
  if (!user) return fallbackId ?? '—';
  if (user.display_name && user.username) {
    return `${user.display_name} (@${user.username})`;
  }
  return user.display_name ?? user.username ?? user.email ?? fallbackId ?? '—';
}

function IssueNotice({ issue }: { issue: { message: string; correlationId?: string } | null }) {
  if (!issue) return null;
  return (
    <div className="notice error" role="alert" style={{ marginBottom: '16px' }}>
      <p style={{ margin: 0, fontWeight: 600 }}>{issue.message}</p>
      {issue.correlationId && (
        <p style={{ margin: '6px 0 0', fontSize: '12px' }}>
          Mã đối chiếu: <code>{issue.correlationId}</code>
        </p>
      )}
    </div>
  );
}

function UnknownWarning({
  reconciled,
  onReload,
  onAcknowledge,
  busy,
}: {
  reconciled: boolean;
  onReload: () => void;
  onAcknowledge: () => void;
  busy: boolean;
}) {
  const [acknowledgedCheck, setAcknowledgedCheck] = useState(false);

  return (
    <div className="notice error" role="alert" style={{ marginBottom: '16px' }}>
      <p style={{ margin: 0, fontWeight: 600 }}>
        Chưa xác định được kết quả thao tác trước từ máy chủ
      </p>
      <p style={{ margin: '6px 0 0', fontSize: '13px', lineHeight: 1.6 }}>
        Yêu cầu trước chưa nhận được phản hồi xác nhận dứt điểm từ máy chủ. Các thao tác cập nhật dữ liệu tạm thời bị khóa để tránh gửi trùng lặp. Vui lòng bấm &ldquo;Tải lại dữ liệu để đối chiếu&rdquo; trước khi tiếp tục.
      </p>
      <div className="accounts-actions" style={{ marginTop: '12px' }}>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={onReload}
        >
          {busy ? 'Đang tải lại…' : 'Tải lại dữ liệu để đối chiếu'}
        </button>
      </div>
      {reconciled && (
        <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid #fca5a5' }}>
          <label className="check-label" style={{ fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={acknowledgedCheck}
              disabled={busy}
              onChange={e => setAcknowledgedCheck(e.target.checked)}
            />
            Tôi đã đối chiếu dữ liệu
          </label>
          <div className="accounts-actions" style={{ marginTop: '10px' }}>
            <button
              type="button"
              className="button primary"
              disabled={busy || !acknowledgedCheck}
              onClick={onAcknowledge}
            >
              Xác nhận đã đối chiếu để mở khóa
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function IssuedCodeBanner({
  issued,
  onClear,
  busy,
}: {
  issued: IssuedCode;
  onClear: () => void;
  busy: boolean;
}) {
  const [safeHandoff, setSafeHandoff] = useState(false);

  return (
    <div className="notice success" role="status" style={{ marginBottom: '20px' }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '16px' }}>
        Mã kích hoạt một lần đã được cấp thành công
      </h3>
      <p style={{ margin: '0 0 8px', fontSize: '13px', lineHeight: 1.6 }}>
        Mã chỉ hiển thị duy nhất tại phiên làm việc này và không lưu lại trong trình duyệt. Quản trị viên vui lòng bàn giao trực tiếp, an toàn cho học sinh trước khi đóng hiển thị.
      </p>
      <div style={{ background: '#ffffff', border: '1px solid #cbd5e1', borderRadius: '8px', padding: '14px', margin: '12px 0' }}>
        <div style={{ display: 'grid', gap: '8px', fontSize: '13px' }}>
          <div>
            <strong>Mã kích hoạt:</strong>{' '}
            <input
              type="text"
              readOnly
              value={issued.code}
              aria-label="Mã kích hoạt học sinh"
              style={{
                fontFamily: 'monospace',
                fontSize: '18px',
                fontWeight: 700,
                color: '#0f766e',
                letterSpacing: '0.08em',
                padding: '6px 12px',
                width: 'auto',
                display: 'inline-block',
                background: '#f8fafc',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
              }}
            />
          </div>
          <div><strong>Tên đăng nhập:</strong> <code>{issued.student.username ?? '—'}</code></div>
          <div><strong>Mã học sinh:</strong> <small>{issued.student.id}</small></div>
          <div><strong>Mục đích:</strong> {issued.purpose === 'ACTIVATION' ? 'Kích hoạt tài khoản học sinh' : 'Đặt lại mật khẩu'}</div>
          <div><strong>Thời hạn mã:</strong> {formatDate(issued.expires_at)}</div>
        </div>
      </div>
      <label className="check-label" style={{ marginTop: '12px', fontWeight: 600 }}>
        <input
          type="checkbox"
          checked={safeHandoff}
          disabled={busy}
          onChange={e => setSafeHandoff(e.target.checked)}
        />
        Tôi đã bàn giao mã an toàn cho học sinh và xác nhận hoàn tất
      </label>
      <div className="accounts-actions" style={{ marginTop: '12px' }}>
        <button
          type="button"
          className="button primary"
          disabled={busy || !safeHandoff}
          onClick={onClear}
        >
          Đã bàn giao — Xóa hiển thị mã
        </button>
      </div>
    </div>
  );
}

function ReasonSelect({
  value,
  onChange,
  disabled,
  id,
}: {
  value: AdminReason;
  onChange: (value: AdminReason) => void;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <label htmlFor={id}>
      Căn cứ / Lý do quản trị
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value as AdminReason)}
      >
        {adminReasons.map(r => (
          <option key={r} value={r}>
            {ADMIN_REASON_LABELS[r]}
          </option>
        ))}
      </select>
    </label>
  );
}

function ClassAdminTabs({
  classId,
  current,
}: {
  classId: string;
  current: 'settings' | 'enrollment' | 'lifecycle';
}) {
  return (
    <nav className="accounts-tabs" aria-label="Điều hướng lớp môn học" style={{ marginBottom: '20px' }}>
      <Link
        href={`/admin/classes/${classId}/settings`}
        style={{
          display: 'inline-block',
          padding: '10px 16px',
          borderRadius: '8px',
          fontWeight: 600,
          textDecoration: 'none',
          color: current === 'settings' ? '#2563eb' : '#64748b',
          background: current === 'settings' ? '#ffffff' : 'transparent',
          boxShadow: current === 'settings' ? '0 1px 3px rgba(15, 23, 42, 0.08)' : 'none',
        }}
      >
        Cấu hình & Phân công
      </Link>
      <Link
        href={`/admin/classes/${classId}/enrollment`}
        style={{
          display: 'inline-block',
          padding: '10px 16px',
          borderRadius: '8px',
          fontWeight: 600,
          textDecoration: 'none',
          color: current === 'enrollment' ? '#2563eb' : '#64748b',
          background: current === 'enrollment' ? '#ffffff' : 'transparent',
          boxShadow: current === 'enrollment' ? '0 1px 3px rgba(15, 23, 42, 0.08)' : 'none',
        }}
      >
        Ghi danh học sinh
      </Link>
      <Link
        href={`/admin/classes/${classId}/lifecycle`}
        style={{
          display: 'inline-block',
          padding: '10px 16px',
          borderRadius: '8px',
          fontWeight: 600,
          textDecoration: 'none',
          color: current === 'lifecycle' ? '#2563eb' : '#64748b',
          background: current === 'lifecycle' ? '#ffffff' : 'transparent',
          boxShadow: current === 'lifecycle' ? '0 1px 3px rgba(15, 23, 42, 0.08)' : 'none',
        }}
      >
        Vòng đời lớp học
      </Link>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// 1. AccountsListView (a.accounts)
// ---------------------------------------------------------------------------

function AccountsListView({
  state,
  onReload,
  onAcknowledgeUnknown,
  onClearCode,
}: CoreManagementViewProps) {
  const [search, setSearch] = useState('');

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return state.users;
    return state.users.filter(u => {
      const name = (u.display_name ?? '').toLowerCase();
      const email = (u.email ?? '').toLowerCase();
      const username = (u.username ?? '').toLowerCase();
      return name.includes(q) || email.includes(q) || username.includes(q);
    });
  }, [state.users, search]);

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px' }}>Danh sách tài khoản</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Quản lý tài khoản, vai trò và trạng thái người dùng trong trường học.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải dữ liệu…' : 'Tải lại danh sách'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        <div className="accounts-actions" style={{ marginBottom: '16px' }}>
          <Link className="button" href="/admin/accounts/students/new">
            + Cấp tài khoản học sinh
          </Link>
          <Link className="button" href="/admin/accounts/staff/invitations">
            Mời cán bộ & giáo viên
          </Link>
          <Link className="button" href="/admin/imports/new">
            Nhập học sinh từ tệp
          </Link>
        </div>

        <div className="accounts-filter">
          <label>
            Tìm kiếm tài khoản
            <input
              type="search"
              value={search}
              placeholder="Tìm theo họ tên, email hoặc tên đăng nhập"
              onChange={e => setSearch(e.target.value)}
            />
          </label>
          <div style={{ alignSelf: 'end', fontSize: '13px', color: '#64748b' }}>
            Hiển thị {filteredUsers.length} / {state.users.length} tài khoản
          </div>
        </div>

        {state.busy && !state.loaded && (
          <p className="muted" role="status" style={{ marginTop: '16px' }}>
            Đang tải dữ liệu tài khoản…
          </p>
        )}

        {state.loaded && filteredUsers.length === 0 && (
          <p className="muted" style={{ marginTop: '20px' }}>
            {state.users.length === 0
              ? 'Chưa có tài khoản nào trong trường học.'
              : 'Không tìm thấy tài khoản phù hợp với từ khóa tìm kiếm.'}
          </p>
        )}

        {filteredUsers.length > 0 && (
          <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng danh sách tài khoản" style={{ marginTop: '16px' }}>
            <table>
              <thead>
                <tr>
                  <th>Họ tên & Tên đăng nhập</th>
                  <th>Email</th>
                  <th>Vai trò</th>
                  <th>Trạng thái</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map(user => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.display_name ?? 'Chưa cập nhật'}</strong>
                      <br />
                      <code>{user.username ? `@${user.username}` : 'Chưa có tên đăng nhập'}</code>
                    </td>
                    <td>{user.email ?? '—'}</td>
                    <td>
                      {user.roles.length > 0
                        ? user.roles.map(r => ROLE_LABELS[r] ?? r).join(', ')
                        : 'Chưa có vai trò'}
                    </td>
                    <td>
                      <span className={`accounts-status accounts-status-${user.status.toLowerCase()}`}>
                        {USER_STATUS_LABELS[user.status] ?? user.status}
                      </span>
                    </td>
                    <td>
                      <Link className="accounts-link" href={`/admin/accounts/${user.id}`}>
                        Chi tiết & Quản lý
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. AccountDetailView (a.account)
// ---------------------------------------------------------------------------

function AccountDetailView({
  params,
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onIssueCode,
  onClearCode,
}: CoreManagementViewProps) {
  const account = state.account;
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  // Status mutation draft
  const [statusDraft, setStatusDraft] = useState<'' | 'ACTIVE' | 'LOCKED'>(()=>account?.status==='ACTIVE'||account?.status==='LOCKED'?account.status:'');
  const [statusReason, setStatusReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  // Roles mutation draft
  const [rolesDraft, setRolesDraft] = useState<Role[]>(()=>account?.roles??[]);
  const [roleReason, setRoleReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  // Issue code draft
  const [verifiedIdentity, setVerifiedIdentity] = useState(false);

  useEffect(() => {
    if (account) {
      setStatusDraft(account.status === 'ACTIVE' || account.status === 'LOCKED' ? account.status : '');
      setRolesDraft(account.roles);
      setVerifiedIdentity(false);
    }
  }, [account]);

  const handleRoleToggle = (role: Role) => {
    setRolesDraft(current =>
      current.includes(role) ? current.filter(r => r !== role) : [...current, role]
    );
  };

  const handleStatusSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!account || !statusDraft || isMutationDisabled) return;
    onCommand('setUserStatus', {
      userId: account.id,
      body: { status: statusDraft },
      reason: statusReason,
    });
  };

  const handleRolesSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!account || rolesDraft.length === 0 || isMutationDisabled) return;
    onCommand('setUserRoles', {
      userId: account.id,
      body: { roles: rolesDraft },
      reason: roleReason,
    });
  };

  const handleIssueCodeSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!account || !verifiedIdentity || isMutationDisabled) return;
    onIssueCode(true);
  };

  if (!account && state.loaded) {
    return (
      <div className="accounts-workspace">
        <section className="card accounts-panel">
          <Link className="accounts-link" href="/admin/accounts" style={{ marginBottom: '16px', display: 'inline-block' }}>
            ← Quay lại danh sách tài khoản
          </Link>
          <h2>Không tìm thấy tài khoản</h2>
          <p className="muted">
            Không tìm thấy thông tin tài khoản với mã định danh <code>{params.userId}</code> trong phạm vi nhà trường.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <Link className="accounts-link" href="/admin/accounts" style={{ marginBottom: '8px', display: 'inline-block' }}>
              ← Quay lại danh sách tài khoản
            </Link>
            <h1 style={{ margin: 0, fontSize: '24px' }}>
              Quản lý tài khoản: {account?.display_name ?? account?.username ?? params.userId}
            </h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Cập nhật trạng thái hoạt động, phân công vai trò và cấp mã kích hoạt học sinh.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại thông tin'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        {account && (
          <>
            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '20px', margin: '16px 0 24px' }}>
              <h3 style={{ margin: '0 0 12px', fontSize: '16px' }}>Thông tin chi tiết tài khoản</h3>
              <dl className="accounts-details" style={{ margin: 0 }}>
                <div>
                  <dt>Mã tài khoản</dt>
                  <dd><code>{account.id}</code></dd>
                </div>
                <div>
                  <dt>Họ và tên</dt>
                  <dd><strong>{account.display_name ?? 'Chưa cập nhật'}</strong></dd>
                </div>
                <div>
                  <dt>Tên đăng nhập</dt>
                  <dd><code>{account.username ?? 'Chưa có'}</code></dd>
                </div>
                <div>
                  <dt>Email</dt>
                  <dd>{account.email ?? 'Chưa có'}</dd>
                </div>
                <div>
                  <dt>Trạng thái hiện tại</dt>
                  <dd>
                    <span className={`accounts-status accounts-status-${account.status.toLowerCase()}`}>
                      {USER_STATUS_LABELS[account.status] ?? account.status}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Vai trò hiện tại</dt>
                  <dd>
                    {account.roles.length > 0
                      ? account.roles.map(r => ROLE_LABELS[r] ?? r).join(', ')
                      : 'Chưa có vai trò'}
                  </dd>
                </div>
              </dl>
            </div>

            <div className="accounts-two-column">
              {/* Form 1: Cập nhật trạng thái */}
              <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                <h3 style={{ margin: '0 0 12px' }}>Cập nhật trạng thái tài khoản</h3>
                <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                  Khóa hoặc kích hoạt lại tài khoản. Khi bị khóa, người dùng sẽ không thể đăng nhập vào hệ thống.
                </p>

                <form className="form-stack" onSubmit={handleStatusSubmit}>
                  <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                    <label htmlFor="user-status-select">
                      Trạng thái tài khoản
                      <select
                        id="user-status-select"
                        value={statusDraft}
                        onChange={e => setStatusDraft(e.target.value as 'ACTIVE' | 'LOCKED')}
                      >
                        {statusDraft === '' && (
                          <option value="">-- Chọn trạng thái (ACTIVE hoặc LOCKED) --</option>
                        )}
                        <option value="ACTIVE">Đang hoạt động (ACTIVE)</option>
                        <option value="LOCKED">Đã khóa (LOCKED)</option>
                      </select>
                    </label>

                    <ReasonSelect
                      id="status-reason-select"
                      value={statusReason}
                      onChange={setStatusReason}
                    />

                    <div className="accounts-actions" style={{ marginTop: '16px' }}>
                      <button
                        type="submit"
                        className="button primary"
                        disabled={isMutationDisabled || !statusDraft}
                      >
                        {state.busy ? 'Đang cập nhật…' : 'Cập nhật trạng thái'}
                      </button>
                    </div>
                  </fieldset>
                </form>
              </div>

              {/* Form 2: Cập nhật vai trò */}
              <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                <h3 style={{ margin: '0 0 12px' }}>Cập nhật vai trò người dùng</h3>
                <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                  Một tài khoản phải có ít nhất một vai trò. Máy chủ sẽ thực thi các ràng buộc bảo vệ quản trị viên cuối cùng và ngăn chặn xung đột vai trò.
                </p>

                <form className="form-stack" onSubmit={handleRolesSubmit}>
                  <fieldset disabled={isMutationDisabled} style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', margin: 0 }}>
                    <legend style={{ padding: '0 6px', color: '#64748b', fontSize: '13px', fontWeight: 600 }}>
                      Vai trò (chọn ít nhất một)
                    </legend>
                    <label className="check-label" style={{ marginTop: '8px' }}>
                      <input
                        type="checkbox"
                        checked={rolesDraft.includes('STUDENT')}
                        onChange={() => handleRoleToggle('STUDENT')}
                      />
                      Học sinh (STUDENT)
                    </label>
                    <label className="check-label" style={{ marginTop: '8px' }}>
                      <input
                        type="checkbox"
                        checked={rolesDraft.includes('LECTURER')}
                        onChange={() => handleRoleToggle('LECTURER')}
                      />
                      Giáo viên (LECTURER)
                    </label>
                    <label className="check-label" style={{ marginTop: '8px' }}>
                      <input
                        type="checkbox"
                        checked={rolesDraft.includes('ADMIN')}
                        onChange={() => handleRoleToggle('ADMIN')}
                      />
                      Quản trị viên (ADMIN)
                    </label>
                  </fieldset>

                  <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: '14px 0 0' }}>
                    <ReasonSelect
                      id="roles-reason-select"
                      value={roleReason}
                      onChange={setRoleReason}
                    />

                    <div className="accounts-actions" style={{ marginTop: '16px' }}>
                      <button
                        type="submit"
                        className="button primary"
                        disabled={isMutationDisabled || rolesDraft.length === 0}
                      >
                        {state.busy ? 'Đang cập nhật…' : 'Cập nhật vai trò'}
                      </button>
                    </div>
                  </fieldset>
                </form>
              </div>
            </div>

            {/* Section 3: Cấp mã kích hoạt học sinh */}
            {account.roles.length===1&&account.roles[0]==='STUDENT'&&account.username&&account.status!=='LOCKED' && (
              <div className="card accounts-panel" style={{ marginTop: '24px', border: '1px solid #cbd5e1' }}>
                <h3 style={{ margin: '0 0 8px' }}>Cấp mã kích hoạt học sinh một lần</h3>
                <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                  Học sinh sử dụng mã kích hoạt này cùng tên đăng nhập để thiết lập mật khẩu ban đầu hoặc khôi phục quyền truy cập. Quản trị viên cần trực tiếp xác minh nhân thân học sinh trước khi cấp mã.
                </p>

                <form className="form-stack" onSubmit={handleIssueCodeSubmit}>
                  <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                    <label className="check-label" style={{ fontWeight: 600 }}>
                      <input
                        type="checkbox"
                        checked={verifiedIdentity}
                        onChange={e => setVerifiedIdentity(e.target.checked)}
                      />
                      Tôi xác nhận đã kiểm tra và xác minh đúng danh tính học sinh này
                    </label>

                    <div className="accounts-actions" style={{ marginTop: '16px' }}>
                      <button
                        type="submit"
                        className="button primary"
                        disabled={isMutationDisabled || !verifiedIdentity}
                      >
                        {state.busy ? 'Đang xử lý cấp mã…' : 'Cấp mã kích hoạt'}
                      </button>
                    </div>
                  </fieldset>
                </form>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3. CatalogView (a.catalog)
// ---------------------------------------------------------------------------

function CatalogView({
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onClearCode,
}: CoreManagementViewProps) {
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const [courseCode, setCourseCode] = useState('');
  const [courseName, setCourseName] = useState('');
  useEffect(()=>{if(state.acknowledgement?.operation==='createCourse'){setCourseCode('');setCourseName('');}},[state.acknowledgement]);

  const yearMap = useMemo(() => {
    return new Map(state.years.map(y => [y.id, y.label]));
  }, [state.years]);

  const handleCreateCourse = (e: FormEvent) => {
    e.preventDefault();
    if (isMutationDisabled || !courseCode.trim() || !courseName.trim()) return;
    onCommand('createCourse', {
      body: {
        code: courseCode.trim(),
        name: courseName.trim(),
      },
    });
  };

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px' }}>Danh mục học vụ</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Xem danh mục năm học, học kỳ, khối lớp và quản lý môn học chính khóa của trường.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại danh mục'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        {/* Khối lớp tĩnh 6..12 */}
        <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '16px', margin: '16px 0' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: '15px' }}>Khối lớp áp dụng (Quy chuẩn THCS/THPT)</h3>
          <p className="muted" style={{ fontSize: '13px', margin: '0 0 10px' }}>
            Hệ thống hỗ trợ các khối lớp từ khối 6 đến khối 12 theo quy định nghiệp vụ cốt lõi của nhà trường.
          </p>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {[6, 7, 8, 9, 10, 11, 12].map(grade => (
              <span
                key={grade}
                style={{
                  background: '#ffffff',
                  border: '1px solid #cbd5e1',
                  borderRadius: '6px',
                  padding: '6px 14px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#1e293b',
                }}
              >
                Khối {grade}
              </span>
            ))}
          </div>
        </div>

        {/* Bảng năm học & học kỳ */}
        <div className="accounts-two-column" style={{ marginTop: '20px' }}>
          <div>
            <h3 style={{ margin: '0 0 8px' }}>Năm học ({state.years.length})</h3>
            <p className="muted" style={{ fontSize: '12px', margin: '0 0 12px' }}>
              Năm học được khởi tạo thông qua việc tạo lớp hành chính hoặc lớp môn học.
            </p>
            <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng danh sách năm học">
              <table>
                <thead>
                  <tr>
                    <th>Năm học</th>
                    <th>Mã năm học</th>
                  </tr>
                </thead>
                <tbody>
                  {state.years.map(y => (
                    <tr key={y.id}>
                      <td><strong>{y.label}</strong></td>
                      <td><small>{y.id}</small></td>
                    </tr>
                  ))}
                  {state.years.length === 0 && (
                    <tr>
                      <td colSpan={2} className="muted">Chưa có năm học nào.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h3 style={{ margin: '0 0 8px' }}>Học kỳ ({state.semesters.length})</h3>
            <p className="muted" style={{ fontSize: '12px', margin: '0 0 12px' }}>
              Học kỳ gắn với năm học cụ thể thuộc phạm vi nhà trường.
            </p>
            <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng danh sách học kỳ">
              <table>
                <thead>
                  <tr>
                    <th>Tên học kỳ</th>
                    <th>Thuộc năm học</th>
                  </tr>
                </thead>
                <tbody>
                  {state.semesters.map(s => (
                    <tr key={s.id}>
                      <td><strong>{s.name}</strong></td>
                      <td>{yearMap.get(s.academic_year_id) ?? s.academic_year_id}</td>
                    </tr>
                  ))}
                  {state.semesters.length === 0 && (
                    <tr>
                      <td colSpan={2} className="muted">Chưa có học kỳ nào.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Quản lý môn học */}
        <div style={{ marginTop: '32px', borderTop: '2px solid #e2e8f0', paddingTop: '24px' }}>
          <h2 style={{ margin: '0 0 12px' }}>Danh mục môn học ({state.courses.length})</h2>
          <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
            Các môn học được giảng dạy trong nhà trường. Môn học được dùng để tạo các lớp môn học chính khóa.
          </p>

          <div className="accounts-two-column">
            <div>
              <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng danh mục môn học">
                <table>
                  <thead>
                    <tr>
                      <th>Mã môn</th>
                      <th>Tên môn học</th>
                      <th>Mã định danh môn</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.courses.map(course => (
                      <tr key={course.id}>
                        <td><code>{course.code}</code></td>
                        <td><strong>{course.name}</strong></td>
                        <td><small>{course.id}</small></td>
                      </tr>
                    ))}
                    {state.courses.length === 0 && (
                      <tr>
                        <td colSpan={3} className="muted">Chưa có môn học nào.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
              <h3 style={{ margin: '0 0 12px' }}>Tạo môn học mới</h3>
              <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                Thêm môn học vào danh mục trường. Mã môn tối đa 50 ký tự, tên môn tối đa 200 ký tự. Thao tác không yêu cầu lý do quản trị.
              </p>

              <form className="form-stack" onSubmit={handleCreateCourse}>
                <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                  <label htmlFor="course-code-input">
                    Mã môn học (code)
                    <input
                      id="course-code-input"
                      type="text"
                      required
                      maxLength={50}
                      placeholder="Ví dụ: TOAN, VAN, ANH"
                      value={courseCode}
                      onChange={e => setCourseCode(e.target.value)}
                    />
                  </label>

                  <label htmlFor="course-name-input">
                    Tên môn học (name)
                    <input
                      id="course-name-input"
                      type="text"
                      required
                      maxLength={200}
                      placeholder="Ví dụ: Toán học, Ngữ văn, Tiếng Anh"
                      value={courseName}
                      onChange={e => setCourseName(e.target.value)}
                    />
                  </label>

                  <div className="accounts-actions" style={{ marginTop: '16px' }}>
                    <button
                      type="submit"
                      className="button primary"
                      disabled={isMutationDisabled || !courseCode.trim() || !courseName.trim()}
                    >
                      {state.busy ? 'Đang tạo…' : 'Tạo môn học'}
                    </button>
                  </div>
                </fieldset>
              </form>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 4. HomeroomsListView (a.homerooms)
// ---------------------------------------------------------------------------

function HomeroomsListView({
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onClearCode,
}: CoreManagementViewProps) {
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const [name, setName] = useState('');
  const [academicYear, setAcademicYear] = useState('');
  const [gradeLevel, setGradeLevel] = useState<number>(10);
  useEffect(()=>{if(state.acknowledgement?.operation==='createHomeroom')setName('');},[state.acknowledgement]);

  const yearMap = useMemo(() => {
    return new Map(state.years.map(y => [y.id, y.label]));
  }, [state.years]);

  const handleCreateHomeroom = (e: FormEvent) => {
    e.preventDefault();
    if (isMutationDisabled || !name.trim() || !academicYear.trim()) return;
    onCommand('createHomeroom', {
      body: {
        name: name.trim(),
        academic_year: academicYear.trim(),
        grade_level: Number(gradeLevel),
      },
    });
  };

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px' }}>Danh sách lớp hành chính</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Quản lý các lớp hành chính, danh sách học sinh chính thức (roster) và năm học.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại danh sách'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        <div className="accounts-two-column" style={{ marginTop: '20px' }}>
          <div>
            <h3 style={{ margin: '0 0 12px' }}>Các lớp hành chính hiện có ({state.homerooms.length})</h3>
            <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng danh sách lớp hành chính">
              <table>
                <thead>
                  <tr>
                    <th>Tên lớp</th>
                    <th>Năm học</th>
                    <th>Khối</th>
                    <th>Phiên bản Roster</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {state.homerooms.map(homeroom => (
                    <tr key={homeroom.id}>
                      <td><strong>{homeroom.name}</strong></td>
                      <td>{yearMap.get(homeroom.academic_year_id) ?? homeroom.academic_year_id}</td>
                      <td>Khối {homeroom.grade_level}</td>
                      <td><code>v{homeroom.roster_version}</code></td>
                      <td>
                        <Link className="accounts-link" href={`/admin/homerooms/${homeroom.id}`}>
                          Roster & Chuyển lớp
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {state.homerooms.length === 0 && (
                    <tr>
                      <td colSpan={5} className="muted">Chưa có lớp hành chính nào.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
            <h3 style={{ margin: '0 0 12px' }}>Tạo lớp hành chính mới</h3>
            <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
              Tạo lớp hành chính gắn với năm học và khối lớp. Thao tác không yêu cầu lý do quản trị.
            </p>

            <form className="form-stack" onSubmit={handleCreateHomeroom}>
              <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                <label htmlFor="homeroom-name-input">
                  Tên lớp hành chính
                  <input
                    id="homeroom-name-input"
                    type="text"
                    required
                    maxLength={200}
                    placeholder="Ví dụ: 10A1, 11A2, 12 Tin"
                    value={name}
                    onChange={e => setName(e.target.value)}
                  />
                </label>

                <label htmlFor="homeroom-year-input">
                  Năm học (nhãn văn bản)
                  <input
                    id="homeroom-year-input"
                    type="text"
                    required
                    list="homeroom-years-datalist"
                    placeholder="Ví dụ: 2026-2027"
                    value={academicYear}
                    onChange={e => setAcademicYear(e.target.value)}
                  />
                  <datalist id="homeroom-years-datalist">
                    {state.years.map(y => (
                      <option key={y.id} value={y.label} />
                    ))}
                  </datalist>
                </label>

                <label htmlFor="homeroom-grade-select">
                  Khối lớp
                  <select
                    id="homeroom-grade-select"
                    value={gradeLevel}
                    onChange={e => setGradeLevel(Number(e.target.value))}
                  >
                    {[6, 7, 8, 9, 10, 11, 12].map(g => (
                      <option key={g} value={g}>
                        Khối {g}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="accounts-actions" style={{ marginTop: '16px' }}>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={isMutationDisabled || !name.trim() || !academicYear.trim()}
                  >
                    {state.busy ? 'Đang tạo…' : 'Tạo lớp hành chính'}
                  </button>
                </div>
              </fieldset>
            </form>
          </div>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 5. HomeroomDetailView (a.homeroom)
// ---------------------------------------------------------------------------

function HomeroomDetailView({
  params,
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onClearCode,
}: CoreManagementViewProps) {
  const homeroomId = params.homeroomId;
  const homeroom = state.homerooms.find(h => h.id.toLowerCase() === homeroomId?.toLowerCase());
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const yearMap = useMemo(() => {
    return new Map(state.years.map(y => [y.id, y.label]));
  }, [state.years]);

  // Candidates for roster: role STUDENT or already in roster
  const rosterStudentIds = useMemo(() => {
    return new Set(state.roster?.student_ids ?? []);
  }, [state.roster?.student_ids]);

  const candidateStudents = useMemo(() => {
    return state.users.filter(u => u.roles.includes('STUDENT') || rosterStudentIds.has(u.id));
  }, [state.users, rosterStudentIds]);

  // Draft: Selected student IDs for setRoster
  const [selectedStudentIds, setSelectedStudentIds] = useState<string[]>(() => state.roster?.student_ids ?? []);
  const [rosterReason, setRosterReason] = useState<AdminReason>('ADMIN_INTERVENTION');
  const [confirmRoster, setConfirmRoster] = useState(false);
  const [studentSearch, setStudentSearch] = useState('');

  // Draft: Transfer student
  const [transferStudentId, setTransferStudentId] = useState('');
  const [destinationHomeroomId, setDestinationHomeroomId] = useState('');
  const [transferReason, setTransferReason] = useState<AdminReason>('ADMIN_INTERVENTION');
  const [confirmTransfer, setConfirmTransfer] = useState(false);

  useEffect(() => {
    setSelectedStudentIds(state.roster?.student_ids ?? []);
    setConfirmRoster(false);
    setTransferStudentId('');
    setDestinationHomeroomId('');
    setConfirmTransfer(false);
  }, [state.roster]);

  const sameYearHomerooms = useMemo(() => {
    if (!homeroom) return [];
    return state.homerooms.filter(
      h => h.id !== homeroom.id && h.academic_year_id === homeroom.academic_year_id && h.grade_level === homeroom.grade_level
    );
  }, [state.homerooms, homeroom]);

  const filteredCandidates = useMemo(() => {
    const q = studentSearch.trim().toLowerCase();
    if (!q) return candidateStudents;
    return candidateStudents.filter(u => {
      const name = (u.display_name ?? '').toLowerCase();
      const username = (u.username ?? '').toLowerCase();
      return name.includes(q) || username.includes(q);
    });
  }, [candidateStudents, studentSearch]);

  const handleStudentCheckbox = (id: string, checked: boolean) => {
    setSelectedStudentIds(prev =>
      checked ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter(x => x !== id)
    );
  };

  const handleSetRosterSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!homeroom || !confirmRoster || isMutationDisabled) return;
    onCommand('setRoster', {
      homeroomId: homeroom.id,
      body: { student_ids: selectedStudentIds },
      reason: rosterReason,
    });
  };

  const handleTransferSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!homeroom || !transferStudentId || !destinationHomeroomId || !confirmTransfer || isMutationDisabled) return;
    onCommand('transferHomeroom', {
      homeroomId: homeroom.id,
      studentId: transferStudentId,
      body: { destination_homeroom_id: destinationHomeroomId },
      reason: transferReason,
    });
  };

  if (!homeroom && state.loaded) {
    return (
      <div className="accounts-workspace">
        <section className="card accounts-panel">
          <Link className="accounts-link" href="/admin/homerooms" style={{ marginBottom: '16px', display: 'inline-block' }}>
            ← Quay lại danh sách lớp hành chính
          </Link>
          <h2>Không tìm thấy lớp hành chính</h2>
          <p className="muted">
            Không tìm thấy lớp hành chính với mã <code>{homeroomId}</code> trong phạm vi nhà trường.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <Link className="accounts-link" href="/admin/homerooms" style={{ marginBottom: '8px', display: 'inline-block' }}>
              ← Quay lại danh sách lớp hành chính
            </Link>
            <h1 style={{ margin: 0, fontSize: '24px' }}>
              Lớp {homeroom?.name} (Khối {homeroom?.grade_level})
            </h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Năm học: <strong>{homeroom ? (yearMap.get(homeroom.academic_year_id) ?? homeroom.academic_year_id) : '—'}</strong> ·
              Phiên bản danh sách: <code>v{state.roster?.roster_version ?? homeroom?.roster_version}</code> ·
              Sĩ số hiện tại: <strong>{state.roster?.student_ids.length ?? 0} học sinh</strong>
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại dữ liệu'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        {homeroom && (
          <>
            {/* Form 1: Cập nhật danh sách học sinh (setRoster) */}
            <div style={{ marginTop: '20px', borderTop: '2px solid #e2e8f0', paddingTop: '20px' }}>
              <h2>Cập nhật danh sách học sinh (Roster)</h2>
              <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                Chọn các học sinh sẽ thuộc lớp hành chính này. Khi xác nhận, toàn bộ danh sách lớp hành chính sẽ được thay thế bằng danh sách được chọn.
              </p>

              <form className="form-stack" onSubmit={handleSetRosterSubmit}>
                <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                  <label htmlFor="student-search-input">
                    Lọc danh sách học sinh
                    <input
                      id="student-search-input"
                      type="search"
                      placeholder="Tìm theo họ tên hoặc tên đăng nhập"
                      value={studentSearch}
                      onChange={e => setStudentSearch(e.target.value)}
                    />
                  </label>

                  <div style={{ margin: '8px 0', fontSize: '13px', color: '#64748b' }}>
                    Đã chọn <strong>{selectedStudentIds.length}</strong> học sinh trong danh sách.
                  </div>

                  <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng chọn học sinh vào lớp hành chính" style={{ maxHeight: '420px', overflowY: 'auto' }}>
                    <table>
                      <thead>
                        <tr>
                          <th style={{ width: '48px' }}>Chọn</th>
                          <th>Họ tên học sinh</th>
                          <th>Tên đăng nhập</th>
                          <th>Trạng thái</th>
                          <th>Hiện tại</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCandidates.map(student => {
                          const isSelected = selectedStudentIds.includes(student.id);
                          const inRoster = rosterStudentIds.has(student.id);
                          return (
                            <tr key={student.id}>
                              <td>
                                <input
                                  type="checkbox"
                                  aria-label={`Chọn học sinh ${student.display_name ?? student.username ?? student.id}`}
                                  checked={isSelected}
                                  onChange={e => handleStudentCheckbox(student.id, e.target.checked)}
                                />
                              </td>
                              <td><strong>{student.display_name ?? 'Chưa cập nhật'}</strong></td>
                              <td><code>{student.username ? `@${student.username}` : '—'}</code></td>
                              <td>
                                <span className={`accounts-status accounts-status-${student.status.toLowerCase()}`}>
                                  {USER_STATUS_LABELS[student.status] ?? student.status}
                                </span>
                              </td>
                              <td>
                                <span style={{ fontSize: '12px', color: inRoster ? '#0f766e' : '#64748b' }}>
                                  {inRoster ? 'Đang trong lớp' : 'Chưa trong lớp'}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                        {(state.roster?.student_ids??[]).filter(id=>!state.users.some(user=>user.id===id)).map(id=><tr key={id}><td><input type="checkbox" aria-label={`Giữ học sinh ${id}`} checked={selectedStudentIds.includes(id)} onChange={event=>handleStudentCheckbox(id,event.target.checked)}/></td><td colSpan={4}><code>{id}</code> — Chưa đọc được thông tin tài khoản; giữ trong danh sách trừ khi bỏ chọn.</td></tr>)}
                        {filteredCandidates.length === 0 && (
                          <tr>
                            <td colSpan={5} className="muted">Không tìm thấy học sinh phù hợp.</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ marginTop: '16px' }}>
                    <ReasonSelect
                      id="roster-reason-select"
                      value={rosterReason}
                      onChange={setRosterReason}
                    />
                  </div>

                  <label className="check-label" style={{ marginTop: '14px', fontWeight: 600 }}>
                    <input
                      type="checkbox"
                      checked={confirmRoster}
                      onChange={e => setConfirmRoster(e.target.checked)}
                    />
                    Tôi xác nhận thay thế toàn bộ danh sách học sinh của lớp hành chính này bằng danh sách đã chọn
                  </label>

                  <div className="accounts-actions" style={{ marginTop: '16px' }}>
                    <button
                      type="submit"
                      className="button primary"
                      disabled={isMutationDisabled || !confirmRoster}
                    >
                      {state.busy ? 'Đang lưu danh sách…' : 'Xác nhận lưu toàn bộ danh sách lớp'}
                    </button>
                  </div>
                </fieldset>
              </form>
            </div>

            {/* Form 2: Chuyển học sinh sang lớp hành chính khác (transferHomeroom) */}
            <div style={{ marginTop: '32px', borderTop: '2px solid #e2e8f0', paddingTop: '20px' }}>
              <h2>Chuyển học sinh sang lớp hành chính khác</h2>
              <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                Chuyển một học sinh đang có trong lớp này sang lớp hành chính khác cùng khối và cùng năm học.
              </p>

              <form className="form-stack" onSubmit={handleTransferSubmit}>
                <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                  <label htmlFor="transfer-student-select">
                    Học sinh cần chuyển (từ danh sách hiện tại)
                    <select
                      id="transfer-student-select"
                      value={transferStudentId}
                      onChange={e => setTransferStudentId(e.target.value)}
                    >
                      <option value="">-- Chọn học sinh cần chuyển --</option>
                      {(state.roster?.student_ids ?? []).map(sid => {
                        const user = state.users.find(u => u.id === sid);
                        return (
                          <option key={sid} value={sid}>
                            {getUserLabel(user, sid)}
                          </option>
                        );
                      })}
                    </select>
                  </label>

                  <label htmlFor="transfer-destination-select">
                    Lớp hành chính đích (cùng năm học, cùng khối)
                    <select
                      id="transfer-destination-select"
                      value={destinationHomeroomId}
                      onChange={e => setDestinationHomeroomId(e.target.value)}
                    >
                      <option value="">-- Chọn lớp hành chính đích --</option>
                      {sameYearHomerooms.map(h => (
                        <option key={h.id} value={h.id}>
                          Lớp {h.name} (Khối {h.grade_level})
                        </option>
                      ))}
                    </select>
                  </label>

                  {sameYearHomerooms.length === 0 && (
                    <p className="muted" style={{ fontSize: '13px', color: '#b45309' }}>
                      Không có lớp hành chính nào khác cùng khối {homeroom.grade_level} và cùng năm học để chuyển đến.
                    </p>
                  )}

                  <ReasonSelect
                    id="transfer-reason-select"
                    value={transferReason}
                    onChange={setTransferReason}
                  />

                  <label className="check-label" style={{ marginTop: '14px', fontWeight: 600 }}>
                    <input
                      type="checkbox"
                      checked={confirmTransfer}
                      onChange={e => setConfirmTransfer(e.target.checked)}
                    />
                    Tôi xác nhận chuyển học sinh đã chọn sang lớp hành chính đích
                  </label>

                  <div className="accounts-actions" style={{ marginTop: '16px' }}>
                    <button
                      type="submit"
                      className="button primary"
                      disabled={isMutationDisabled || !transferStudentId || !destinationHomeroomId || !confirmTransfer}
                    >
                      {state.busy ? 'Đang chuyển học sinh…' : 'Xác nhận chuyển lớp hành chính'}
                    </button>
                  </div>
                </fieldset>
              </form>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 6. ClassesListView (a.classes)
// ---------------------------------------------------------------------------

function ClassesListView({
  state,
  onReload,
  onAcknowledgeUnknown,
  onClearCode,
}: CoreManagementViewProps) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'ACTIVE' | 'ARCHIVED'>('ALL');
  const [modeFilter, setModeFilter] = useState<'ALL' | 'AUTO' | 'MANUAL'>('ALL');

  const courseMap = useMemo(() => new Map(state.courses.map(c => [c.id, c.name])), [state.courses]);
  const yearMap = useMemo(() => new Map(state.years.map(y => [y.id, y.label])), [state.years]);
  const semesterMap = useMemo(() => new Map(state.semesters.map(s => [s.id, s.name])), [state.semesters]);

  const filteredClasses = useMemo(() => {
    const q = search.trim().toLowerCase();
    return state.classes.filter(cls => {
      if (statusFilter !== 'ALL' && cls.status !== statusFilter) return false;
      if (modeFilter !== 'ALL' && cls.enrollment_mode !== modeFilter) return false;
      if (!q) return true;
      const name = cls.name.toLowerCase();
      const course = (courseMap.get(cls.course_id) ?? '').toLowerCase();
      return name.includes(q) || course.includes(q);
    });
  }, [state.classes, search, statusFilter, modeFilter, courseMap]);

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px' }}>Danh sách lớp môn học chính khóa</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Quản lý các lớp môn học, cấu hình phân công giáo viên và chế độ ghi danh.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại danh sách'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        <div className="accounts-actions" style={{ marginBottom: '16px' }}>
          <Link className="button primary" href="/admin/classes/new">
            + Tạo lớp môn học
          </Link>
        </div>

        <div className="accounts-filter" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(140px, 1fr) minmax(160px, 1fr)' }}>
          <label>
            Tìm kiếm lớp môn học
            <input
              type="search"
              value={search}
              placeholder="Tìm theo tên lớp hoặc tên môn học"
              onChange={e => setSearch(e.target.value)}
            />
          </label>

          <label>
            Trạng thái
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value as 'ALL' | 'ACTIVE' | 'ARCHIVED')}
            >
              <option value="ALL">Tất cả trạng thái</option>
              <option value="ACTIVE">Đang hoạt động</option>
              <option value="ARCHIVED">Đã lưu trữ</option>
            </select>
          </label>

          <label>
            Chế độ ghi danh
            <select
              value={modeFilter}
              onChange={e => setModeFilter(e.target.value as 'ALL' | 'AUTO' | 'MANUAL')}
            >
              <option value="ALL">Tất cả chế độ</option>
              <option value="AUTO">Tự động (AUTO)</option>
              <option value="MANUAL">Quản trị viên (MANUAL)</option>
            </select>
          </label>
        </div>

        {filteredClasses.length === 0 && state.loaded && (
          <p className="muted" style={{ marginTop: '20px' }}>
            {state.classes.length === 0
              ? 'Chưa có lớp môn học nào trong trường học.'
              : 'Không tìm thấy lớp môn học phù hợp với bộ lọc.'}
          </p>
        )}

        {filteredClasses.length > 0 && (
          <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng danh sách lớp môn học" style={{ marginTop: '16px' }}>
            <table>
              <thead>
                <tr>
                  <th>Tên lớp</th>
                  <th>Môn học</th>
                  <th>Năm học / Học kỳ</th>
                  <th>Khối</th>
                  <th>Ghi danh</th>
                  <th>Trạng thái</th>
                  <th>Quản lý</th>
                </tr>
              </thead>
              <tbody>
                {filteredClasses.map(cls => (
                  <tr key={cls.id}>
                    <td>
                      <strong>{cls.name}</strong>
                      <br />
                      <small style={{ color: '#64748b' }}>v{cls.version}</small>
                    </td>
                    <td>{courseMap.get(cls.course_id) ?? cls.course_id}</td>
                    <td>
                      {yearMap.get(cls.academic_year_id) ?? cls.academic_year_id}
                      <br />
                      <small>{semesterMap.get(cls.semester_id) ?? cls.semester_id}</small>
                    </td>
                    <td>Khối {cls.grade_level}</td>
                    <td>
                      <span style={{ fontSize: '12px', fontWeight: 600 }}>
                        {cls.enrollment_mode === 'AUTO' ? 'Tự động (AUTO)' : 'Thủ công (MANUAL)'}
                      </span>
                    </td>
                    <td>
                      <span className={`accounts-status accounts-status-${cls.status.toLowerCase()}`}>
                        {CLASS_STATUS_LABELS[cls.status] ?? cls.status}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <Link className="accounts-link" href={`/admin/classes/${cls.id}/settings`}>
                          Cài đặt
                        </Link>
                        <span>·</span>
                        <Link className="accounts-link" href={`/admin/classes/${cls.id}/enrollment`}>
                          Ghi danh
                        </Link>
                        <span>·</span>
                        <Link className="accounts-link" href={`/admin/classes/${cls.id}/lifecycle`}>
                          Vòng đời
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 7. NewClassView (a.newClass)
// ---------------------------------------------------------------------------

function NewClassView({
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onClearCode,
}: CoreManagementViewProps) {
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const [courseId, setCourseId] = useState('');
  const [name, setName] = useState('');
  const [academicYear, setAcademicYear] = useState('');
  const [semester, setSemester] = useState('');
  const [gradeLevel, setGradeLevel] = useState<number>(10);
  const [enrollmentMode, setEnrollmentMode] = useState<'AUTO' | 'MANUAL'>('AUTO');
  const [homeroomClassId, setHomeroomClassId] = useState('');
  const [primaryLecturerId, setPrimaryLecturerId] = useState('');
  useEffect(()=>{if(state.acknowledgement?.operation==='createClass')setName('');},[state.acknowledgement]);
  const availableHomerooms=state.homerooms.filter(home=>home.grade_level===gradeLevel&&state.years.some(year=>year.id===home.academic_year_id&&year.label===academicYear.trim()));
  const homeroomValid=!homeroomClassId||availableHomerooms.some(home=>home.id===homeroomClassId);
  useEffect(()=>{if(!homeroomValid)setHomeroomClassId('');},[homeroomValid]);

  const activeLecturers = useMemo(() => {
    return state.users.filter(u => u.status === 'ACTIVE' && u.roles.includes('LECTURER'));
  }, [state.users]);

  const handleCreateSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (
      isMutationDisabled ||
      !courseId ||
      !name.trim() ||
      !academicYear.trim() ||
      !semester.trim() ||
      !primaryLecturerId ||
      !homeroomValid||(enrollmentMode === 'AUTO' && !homeroomClassId)
    ) {
      return;
    }

    onCommand('createClass', {
      body: {
        course_id: courseId,
        name: name.trim(),
        academic_year: academicYear.trim(),
        semester: semester.trim(),
        grade_level: Number(gradeLevel),
        enrollment_mode: enrollmentMode,
        homeroom_class_id: homeroomClassId || null,
        primary_lecturer_id: primaryLecturerId,
      },
    });
  };

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '8px', display: 'inline-block' }}>
              ← Quay lại danh sách lớp môn học
            </Link>
            <h1 style={{ margin: 0, fontSize: '24px' }}>Tạo lớp môn học mới</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Khởi tạo lớp môn học chính khóa, chọn giáo viên chính và cấu hình chế độ ghi danh.
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại dữ liệu'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        <form className="form-stack" onSubmit={handleCreateSubmit} style={{ maxWidth: '680px', marginTop: '20px' }}>
          <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
            <label htmlFor="create-class-course-select">
              Môn học
              <select
                id="create-class-course-select"
                required
                value={courseId}
                onChange={e => setCourseId(e.target.value)}
              >
                <option value="">-- Chọn môn học --</option>
                {state.courses.map(course => (
                  <option key={course.id} value={course.id}>
                    {course.code} - {course.name}
                  </option>
                ))}
              </select>
            </label>

            <label htmlFor="create-class-name-input">
              Tên lớp môn học
              <input
                id="create-class-name-input"
                type="text"
                required
                maxLength={200}
                placeholder="Ví dụ: Toán 10A1, Hóa học 11 Chuyên"
                value={name}
                onChange={e => setName(e.target.value)}
              />
            </label>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: '16px' }}>
              <label htmlFor="create-class-year-input">
                Năm học (nhãn văn bản)
                <input
                  id="create-class-year-input"
                  type="text"
                  required
                  list="class-years-datalist"
                  placeholder="Ví dụ: 2026-2027"
                  value={academicYear}
                  onChange={e => setAcademicYear(e.target.value)}
                />
                <datalist id="class-years-datalist">
                  {state.years.map(y => (
                    <option key={y.id} value={y.label} />
                  ))}
                </datalist>
              </label>

              <label htmlFor="create-class-semester-input">
                Học kỳ (nhãn văn bản)
                <input
                  id="create-class-semester-input"
                  type="text"
                  required
                  list="class-semesters-datalist"
                  placeholder="Ví dụ: Học kỳ 1"
                  value={semester}
                  onChange={e => setSemester(e.target.value)}
                />
                <datalist id="class-semesters-datalist">
                  {state.semesters.map(s => (
                    <option key={s.id} value={s.name} />
                  ))}
                </datalist>
              </label>
            </div>

            <label htmlFor="create-class-grade-select">
              Khối lớp
              <select
                id="create-class-grade-select"
                value={gradeLevel}
                onChange={e => setGradeLevel(Number(e.target.value))}
              >
                {[6, 7, 8, 9, 10, 11, 12].map(g => (
                  <option key={g} value={g}>
                    Khối {g}
                  </option>
                ))}
              </select>
            </label>

            <fieldset style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', margin: '8px 0' }}>
              <legend style={{ padding: '0 6px', color: '#64748b', fontSize: '13px', fontWeight: 600 }}>
                Chế độ ghi danh học sinh
              </legend>
              <label className="check-label" style={{ marginTop: '8px' }}>
                <input
                  type="radio"
                  name="enrollment-mode"
                  value="AUTO"
                  checked={enrollmentMode === 'AUTO'}
                  onChange={() => setEnrollmentMode('AUTO')}
                />
                Tự động theo lớp hành chính (AUTO) — Bắt buộc chọn lớp hành chính nguồn
              </label>
              <label className="check-label" style={{ marginTop: '8px' }}>
                <input
                  type="radio"
                  name="enrollment-mode"
                  value="MANUAL"
                  checked={enrollmentMode === 'MANUAL'}
                  onChange={() => setEnrollmentMode('MANUAL')}
                />
                Quản trị viên quản lý trực tiếp (MANUAL) — Lớp ghép, lớp tự chọn
              </label>
            </fieldset>

            <label htmlFor="create-class-homeroom-select">
              Lớp hành chính liên kết {enrollmentMode === 'MANUAL' ? '(Tùy chọn)' : '(Bắt buộc)'}
              <select
                id="create-class-homeroom-select"
                required={enrollmentMode === 'AUTO'}
                value={homeroomClassId}
                onChange={e => setHomeroomClassId(e.target.value)}
              >
                <option value="">
                  {enrollmentMode === 'AUTO' ? '-- Bắt buộc chọn lớp hành chính --' : '-- Không chọn (Lớp ghép / tự chọn) --'}
                </option>
                {availableHomerooms.map(h => (
                  <option key={h.id} value={h.id}>
                    Lớp {h.name} (Khối {h.grade_level})
                  </option>
                ))}
              </select>
            </label>

            <label htmlFor="create-class-primary-teacher-select">
              Giáo viên chính (Bắt buộc)
              <select
                id="create-class-primary-teacher-select"
                required
                value={primaryLecturerId}
                onChange={e => setPrimaryLecturerId(e.target.value)}
              >
                <option value="">-- Chọn giáo viên chính đang hoạt động --</option>
                {activeLecturers.map(teacher => (
                  <option key={teacher.id} value={teacher.id}>
                    {getUserLabel(teacher, teacher.id)}
                  </option>
                ))}
              </select>
            </label>

            <div className="accounts-actions" style={{ marginTop: '20px' }}>
              <button
                type="submit"
                className="button primary"
                disabled={
                  isMutationDisabled ||
                  !courseId ||
                  !name.trim() ||
                  !academicYear.trim() ||
                  !semester.trim() ||
                  !primaryLecturerId ||
                  (enrollmentMode === 'AUTO' && !homeroomClassId)
                }
              >
                {state.busy ? 'Đang tạo lớp…' : 'Xác nhận tạo lớp môn học'}
              </button>
            </div>
          </fieldset>
        </form>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 8. ClassSettingsView (a.classSettings)
// ---------------------------------------------------------------------------

function ClassSettingsView({
  params,
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onClearCode,
}: CoreManagementViewProps) {
  const klass = state.klass;
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const courseMap = useMemo(() => new Map(state.courses.map(c => [c.id, c.name])), [state.courses]);
  const yearMap = useMemo(() => new Map(state.years.map(y => [y.id, y.label])), [state.years]);
  const semesterMap = useMemo(() => new Map(state.semesters.map(s => [s.id, s.name])), [state.semesters]);
  const homeroomMap = useMemo(() => new Map(state.homerooms.map(h => [h.id, h.name])), [state.homerooms]);

  const activeLecturers = useMemo(() => {
    return state.users.filter(u => u.status === 'ACTIVE' && u.roles.includes('LECTURER'));
  }, [state.users]);

  // Draft state for setTeachers
  const [primaryId, setPrimaryId] = useState(()=>state.teachers.find(t=>t.role==='PRIMARY'&&!t.ended_at)?.lecturer_id??'');
  const [assistingIds, setAssistingIds] = useState<string[]>(()=>state.teachers.filter(t=>t.role==='ASSISTING'&&!t.ended_at).map(t=>t.lecturer_id));
  const [teachersReason, setTeachersReason] = useState<AdminReason>('ADMIN_INTERVENTION');
  const eligibleTeacherIds=new Set(activeLecturers.map(user=>user.id));
  const assignmentsEligible=eligibleTeacherIds.has(primaryId)&&assistingIds.every(id=>eligibleTeacherIds.has(id));

  useEffect(() => {
    const serverPrimary = state.teachers.find(t => t.role === 'PRIMARY' && !t.ended_at)?.lecturer_id ?? '';
    const serverAssisting = state.teachers.filter(t => t.role === 'ASSISTING' && !t.ended_at).map(t => t.lecturer_id);
    setPrimaryId(serverPrimary);
    setAssistingIds(serverAssisting);
  }, [klass?.id, klass?.version, state.teachers]);

  const handleAssistingToggle = (id: string) => {
    setAssistingIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const handleSetTeachersSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || !primaryId || !assignmentsEligible || isMutationDisabled || klass.status === 'ARCHIVED') return;
    onCommand('setTeachers', {
      classId: klass.id,
      body: {
        primary_lecturer_id: primaryId,
        assisting_lecturer_ids: assistingIds,
      },
      reason: teachersReason,
    });
  };

  if (!klass && state.loaded) {
    return (
      <div className="accounts-workspace">
        <section className="card accounts-panel">
          <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '16px', display: 'inline-block' }}>
            ← Quay lại danh sách lớp môn học
          </Link>
          <h2>Không tìm thấy lớp môn học</h2>
          <p className="muted">
            Không tìm thấy thông tin lớp với mã định danh <code>{params.classId}</code> trong phạm vi nhà trường.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '8px', display: 'inline-block' }}>
              ← Quay lại danh sách lớp môn học
            </Link>
            <h1 style={{ margin: 0, fontSize: '24px' }}>{klass?.name}</h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Phiên bản lớp: <code>v{klass?.version}</code> · Trạng thái: <strong>{klass ? (CLASS_STATUS_LABELS[klass.status] ?? klass.status) : '—'}</strong>
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại dữ liệu'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        {klass && (
          <>
            <ClassAdminTabs classId={klass.id} current="settings" />

            {/* Read-only Class Metadata */}
            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
              <h3 style={{ margin: '0 0 12px', fontSize: '16px' }}>Thông tin lớp môn học (Chỉ đọc)</h3>
              <dl className="accounts-details" style={{ margin: 0 }}>
                <div>
                  <dt>Tên lớp</dt>
                  <dd><strong>{klass.name}</strong></dd>
                </div>
                <div>
                  <dt>Mã định danh lớp</dt>
                  <dd><code>{klass.id}</code></dd>
                </div>
                <div>
                  <dt>Phiên bản dữ liệu lớp</dt>
                  <dd><code>v{klass.version}</code></dd>
                </div>
                <div>
                  <dt>Môn học</dt>
                  <dd>{courseMap.get(klass.course_id) ?? klass.course_id}</dd>
                </div>
                <div>
                  <dt>Năm học / Học kỳ</dt>
                  <dd>
                    {yearMap.get(klass.academic_year_id) ?? klass.academic_year_id} · {semesterMap.get(klass.semester_id) ?? klass.semester_id}
                  </dd>
                </div>
                <div>
                  <dt>Khối lớp</dt>
                  <dd>Khối {klass.grade_level}</dd>
                </div>
                <div>
                  <dt>Chế độ ghi danh</dt>
                  <dd>{klass.enrollment_mode === 'AUTO' ? 'Tự động (AUTO)' : 'Quản trị viên (MANUAL)'}</dd>
                </div>
                <div>
                  <dt>Lớp hành chính liên kết</dt>
                  <dd>
                    {klass.homeroom_class_id
                      ? (homeroomMap.get(klass.homeroom_class_id) ?? klass.homeroom_class_id)
                      : 'Không có (Lớp ghép / tự chọn)'}
                  </dd>
                </div>
                <div>
                  <dt>Trạng thái</dt>
                  <dd>
                    <span className={`accounts-status accounts-status-${klass.status.toLowerCase()}`}>
                      {CLASS_STATUS_LABELS[klass.status] ?? klass.status}
                    </span>
                  </dd>
                </div>
              </dl>
              <p className="muted" style={{ fontSize: '12px', margin: '12px 0 0' }}>
                Giao diện hiện tại chưa hỗ trợ chỉnh sửa tên lớp và thông tin học vụ sau khi tạo.
              </p>
            </div>

            {/* Phân công giáo viên hiện hành */}
            <div style={{ marginBottom: '28px' }}>
              <h3 style={{ margin: '0 0 12px' }}>Phân công giáo viên hiện hành ({state.teachers.length})</h3>
              <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng phân công giáo viên">
                <table>
                  <thead>
                    <tr>
                      <th>Vai trò giảng dạy</th>
                      <th>Giáo viên</th>
                      <th>Ngày phân công</th>
                      <th>Ngày kết thúc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.teachers.map(t => {
                      const teacherUser = state.users.find(u => u.id === t.lecturer_id);
                      return (
                        <tr key={t.id}>
                          <td>
                            <strong>{t.role === 'PRIMARY' ? 'Giáo viên chính (PRIMARY)' : 'Giáo viên phối hợp (ASSISTING)'}</strong>
                          </td>
                          <td>{getUserLabel(teacherUser, t.lecturer_id)}</td>
                          <td>{formatDate(t.assigned_at)}</td>
                          <td>{formatDate(t.ended_at)}</td>
                        </tr>
                      );
                    })}
                    {state.teachers.length === 0 && (
                      <tr>
                        <td colSpan={4} className="muted">Chưa có phân công giáo viên nào.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Form setTeachers */}
            <div className="card accounts-panel" style={{ border: '1px solid #cbd5e1' }}>
              <h3 style={{ margin: '0 0 12px' }}>Cập nhật phân công giáo viên</h3>
              <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                Chỉ quản trị viên có quyền chỉ định giáo viên chính và các giáo viên phối hợp. Giáo viên chính không thể đồng thời là giáo viên phối hợp.
              </p>

              {klass.status === 'ARCHIVED' && (
                <div className="notice" style={{ marginBottom: '16px' }}>
                  Lớp môn học đang lưu trữ. Thao tác phân công bị khóa cho đến khi lớp được khôi phục.
                </div>
              )}

              <form className="form-stack" onSubmit={handleSetTeachersSubmit}>
                <fieldset disabled={isMutationDisabled || klass.status === 'ARCHIVED'} style={{ border: 0, padding: 0, margin: 0 }}>
                  <label htmlFor="settings-primary-teacher-select">
                    Giáo viên chính (PRIMARY)
                    <select
                      id="settings-primary-teacher-select"
                      required
                      value={primaryId}
                      onChange={e => {
                        const newPrimary = e.target.value;
                        setPrimaryId(newPrimary);
                        setAssistingIds(prev => prev.filter(id => id !== newPrimary));
                      }}
                    >
                      <option value="">-- Chọn giáo viên chính --</option>
                      {primaryId&&!eligibleTeacherIds.has(primaryId)&&<option value={primaryId} disabled>{getUserLabel(state.users.find(user=>user.id===primaryId),primaryId)} — Cần thay giáo viên đủ điều kiện</option>}
                      {activeLecturers.map(teacher => (
                        <option key={teacher.id} value={teacher.id}>
                          {getUserLabel(teacher, teacher.id)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <fieldset style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', margin: '14px 0' }}>
                    <legend style={{ padding: '0 6px', color: '#64748b', fontSize: '13px', fontWeight: 600 }}>
                      Giáo viên phối hợp (ASSISTING)
                    </legend>
                    {activeLecturers.filter(u => u.id !== primaryId).map(teacher => (
                      <label key={teacher.id} className="check-label" style={{ marginTop: '8px' }}>
                        <input
                          type="checkbox"
                          checked={assistingIds.includes(teacher.id)}
                          onChange={() => handleAssistingToggle(teacher.id)}
                        />
                        {getUserLabel(teacher, teacher.id)}
                      </label>
                    ))}
                    {assistingIds.filter(id=>!eligibleTeacherIds.has(id)).map(id=><label key={id} className="check-label"><input type="checkbox" checked onChange={()=>handleAssistingToggle(id)}/>{getUserLabel(state.users.find(user=>user.id===id),id)} — Không còn đủ điều kiện; bỏ chọn để kết thúc phân công.</label>)}
                    {activeLecturers.filter(u => u.id !== primaryId).length === 0 && (
                      <p className="muted" style={{ margin: '6px 0 0', fontSize: '13px' }}>
                        Không có giáo viên khả dụng khác để phối hợp.
                      </p>
                    )}
                  </fieldset>

                  <ReasonSelect
                    id="settings-teachers-reason-select"
                    value={teachersReason}
                    onChange={setTeachersReason}
                  />

                  <div className="accounts-actions" style={{ marginTop: '16px' }}>
                    <button
                      type="submit"
                      className="button primary"
                      disabled={isMutationDisabled || !primaryId || !assignmentsEligible || klass.status === 'ARCHIVED'}
                    >
                      {state.busy ? 'Đang cập nhật…' : 'Cập nhật phân công giáo viên'}
                    </button>
                  </div>
                </fieldset>
              </form>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 9. ClassEnrollmentView (a.enrollment)
// ---------------------------------------------------------------------------

function ClassEnrollmentView({
  params,
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onPreview,
  onClearCode,
}: CoreManagementViewProps) {
  const klass = state.klass;
  const isArchived = klass?.status === 'ARCHIVED';
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const preview = state.preview;

  // Active student members
  const activeMembers = useMemo(() => {
    return state.members.filter(m => m.status === 'ACTIVE');
  }, [state.members]);

  const activeMemberStudentIds = useMemo(() => {
    return new Set(activeMembers.map(m => m.student_id));
  }, [activeMembers]);

  // Mode change drafts
  const [confirmManualSwitch, setConfirmManualSwitch] = useState(false);
  const [manualSwitchReason, setManualSwitchReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const [confirmAutoSwitch, setConfirmAutoSwitch] = useState(false);
  const [autoSwitchReason, setAutoSwitchReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const [confirmSync, setConfirmSync] = useState(false);
  const [syncReason, setSyncReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  // MANUAL member mutations
  const [addStudentId, setAddStudentId] = useState('');
  const [confirmAdd, setConfirmAdd] = useState(false);
  const [addReason, setAddReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const [endStudentId, setEndStudentId] = useState('');
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [endReason, setEndReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const [transferStudentId, setTransferStudentId] = useState('');
  const [destinationClassId, setDestinationClassId] = useState('');
  const [confirmTransferMember, setConfirmTransferMember] = useState(false);
  const [transferMemberReason, setTransferMemberReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  useEffect(() => {
    setConfirmManualSwitch(false);
    setConfirmAutoSwitch(false);
    setConfirmSync(false);
    setAddStudentId('');
    setConfirmAdd(false);
    setEndStudentId('');
    setConfirmEnd(false);
    setTransferStudentId('');
    setDestinationClassId('');
    setConfirmTransferMember(false);
  }, [klass?.id, klass?.version]);

  // Destination classes for transfer (active and different)
  const destinationClasses = useMemo(() => {
    if (!klass) return [];
    return state.classes.filter(c => c.id !== klass.id && c.status === 'ACTIVE'&&c.enrollment_mode==='MANUAL'&&c.course_id===klass.course_id&&c.academic_year_id===klass.academic_year_id&&c.semester_id===klass.semester_id);
  }, [state.classes, klass]);

  // Non-member candidate students for addMember
  const nonMemberStudents = useMemo(() => {
    return state.users.filter(u => u.status==='ACTIVE'&&u.roles.includes('STUDENT') && !activeMemberStudentIds.has(u.id));
  }, [state.users, activeMemberStudentIds]);

  const handleManualSwitchSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || isArchived || !confirmManualSwitch) return;
    onCommand('setEnrollmentMode', {
      classId: klass.id,
      body: { mode: 'MANUAL' },
      reason: manualSwitchReason,
    });
  };

  const handleAutoSwitchSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || isArchived || !preview || !confirmAutoSwitch) return;
    onCommand('setEnrollmentMode', {
      classId: klass.id,
      body: {
        mode: 'AUTO',
        expected_class_version: preview.class_version,
        expected_roster_version: preview.roster_version,
      },
      reason: autoSwitchReason,
    });
  };

  const handleSyncSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || isArchived || !preview || !confirmSync) return;
    onCommand('syncEnrollment', {
      classId: klass.id,
      reason: syncReason,
    });
  };

  const handleAddMemberSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || isArchived || !addStudentId || !confirmAdd) return;
    onCommand('addMember', {
      classId: klass.id,
      body: { student_id: addStudentId },
      reason: addReason,
    });
  };

  const handleEndMemberSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || isArchived || !endStudentId || !confirmEnd) return;
    onCommand('endMember', {
      classId: klass.id,
      studentId: endStudentId,
      reason: endReason,
    });
  };

  const handleTransferMemberSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || isArchived || !transferStudentId || !destinationClassId || !confirmTransferMember) return;
    onCommand('transferMember', {
      classId: klass.id,
      studentId: transferStudentId,
      body: { destination_class_id: destinationClassId },
      reason: transferMemberReason,
    });
  };

  if (!klass && state.loaded) {
    return (
      <div className="accounts-workspace">
        <section className="card accounts-panel">
          <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '16px', display: 'inline-block' }}>
            ← Quay lại danh sách lớp môn học
          </Link>
          <h2>Không tìm thấy lớp môn học</h2>
          <p className="muted">
            Không tìm thấy thông tin lớp với mã <code>{params.classId}</code> trong phạm vi nhà trường.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '8px', display: 'inline-block' }}>
              ← Quay lại danh sách lớp môn học
            </Link>
            <h1 style={{ margin: 0, fontSize: '24px' }}>
              Ghi danh học sinh: {klass?.name}
            </h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Chế độ hiện tại: <strong>{klass?.enrollment_mode === 'AUTO' ? 'Tự động theo lớp hành chính (AUTO)' : 'Quản trị viên quản lý (MANUAL)'}</strong> ·
              Sĩ số đang tham gia: <strong>{activeMembers.length} học sinh</strong> ·
              Phiên bản lớp: <code>v{klass?.version}</code>
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại dữ liệu'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        {klass && (
          <>
            <ClassAdminTabs classId={klass.id} current="enrollment" />

            {isArchived && (
              <div className="notice error" role="alert" style={{ marginBottom: '20px' }}>
                <p style={{ margin: 0, fontWeight: 600 }}>Lớp môn học đang ở trạng thái lưu trữ (ARCHIVED)</p>
                <p style={{ margin: '6px 0 0', fontSize: '13px' }}>
                  Danh sách ghi danh chuyển sang chế độ chỉ đọc. Tất cả các thao tác thay đổi ghi danh, chuyển chế độ và đồng bộ đều bị khóa.
                </p>
              </div>
            )}

            {/* Xem trước tác động ghi danh */}
            <div style={{ background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '16px' }}>Đối chiếu & Xem trước tác động ghi danh</h3>
                  <p className="muted" style={{ fontSize: '13px', margin: '4px 0 0' }}>
                    Xem trước danh sách học sinh sẽ được bổ sung hoặc kết thúc trước khi đồng bộ hoặc chuyển sang chế độ AUTO.
                    {!klass.homeroom_class_id && ' Lớp chưa liên kết lớp hành chính nên chưa thể xem trước hoặc chuyển sang AUTO.'}
                  </p>
                </div>
                <button
                  type="button"
                  className="button primary"
                  disabled={isMutationDisabled || isArchived || !klass.homeroom_class_id}
                  onClick={onPreview}
                >
                  {state.busy ? 'Đang đối chiếu…' : 'Xem trước tác động ghi danh'}
                </button>
              </div>

              {preview && (
                <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #e2e8f0' }}>
                  <h4 style={{ margin: '0 0 10px', fontSize: '15px', color: '#0f172a' }}>
                    Kết quả đối chiếu tác động:
                  </h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: '12px', fontSize: '13px', marginBottom: '14px' }}>
                    <div><strong>Chế độ dự kiến:</strong> {preview.target_mode}</div>
                    <div><strong>Phiên bản lớp đối chiếu:</strong> <code>v{preview.class_version}</code></div>
                    <div><strong>Phiên bản danh sách đối chiếu:</strong> <code>v{preview.roster_version}</code></div>
                  </div>

                  <div className="accounts-two-column">
                    <div>
                      <strong style={{ color: '#166534', fontSize: '13px' }}>
                        Học sinh sẽ thêm vào lớp ({preview.add_student_ids.length}):
                      </strong>
                      <ul style={{ margin: '6px 0 0', paddingLeft: '20px', fontSize: '13px', color: '#334155' }}>
                        {preview.add_student_ids.map(sid => {
                          const user = state.users.find(u => u.id === sid);
                          return <li key={sid}>{getUserLabel(user, sid)}</li>;
                        })}
                        {preview.add_student_ids.length === 0 && <li className="muted">Không có học sinh thêm mới.</li>}
                      </ul>
                    </div>

                    <div>
                      <strong style={{ color: '#991b1b', fontSize: '13px' }}>
                        Học sinh sẽ kết thúc ghi danh ({preview.end_student_ids.length}):
                      </strong>
                      <ul style={{ margin: '6px 0 0', paddingLeft: '20px', fontSize: '13px', color: '#334155' }}>
                        {preview.end_student_ids.map(sid => {
                          const user = state.users.find(u => u.id === sid);
                          return <li key={sid}>{getUserLabel(user, sid)}</li>;
                        })}
                        {preview.end_student_ids.length === 0 && <li className="muted">Không có học sinh bị kết thúc.</li>}
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Chế độ AUTO: Đồng bộ & Chuyển sang MANUAL */}
            {klass.enrollment_mode === 'AUTO' && (
              <div className="accounts-two-column" style={{ marginBottom: '28px' }}>
                {/* Đồng bộ ghi danh AUTO */}
                <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                  <h3 style={{ margin: '0 0 8px' }}>Đồng bộ ghi danh</h3>
                  <p className="muted" style={{ fontSize: '13px', margin: '0 0 14px' }}>
                    Đồng bộ sĩ số lớp học theo danh sách lớp hành chính tại thời điểm máy chủ tiếp nhận yêu cầu. Yêu cầu phải xem trước tác động trước khi đồng bộ.
                  </p>

                  {!preview && (
                    <p className="muted" style={{ fontSize: '13px', color: '#b45309' }}>
                      * Cần bấm &ldquo;Xem trước tác động ghi danh&rdquo; ở trên trước khi thực hiện đồng bộ.
                    </p>
                  )}

                  <form className="form-stack" onSubmit={handleSyncSubmit}>
                    <fieldset disabled={isMutationDisabled || isArchived || !preview} style={{ border: 0, padding: 0, margin: 0 }}>
                      <ReasonSelect
                        id="sync-enrollment-reason-select"
                        value={syncReason}
                        onChange={setSyncReason}
                      />

                      <label className="check-label" style={{ marginTop: '12px', fontWeight: 600 }}>
                        <input
                          type="checkbox"
                          checked={confirmSync}
                          onChange={e => setConfirmSync(e.target.checked)}
                        />
                        Tôi xác nhận đồng bộ danh sách lớp học theo lớp hành chính
                      </label>

                      <div className="accounts-actions" style={{ marginTop: '16px' }}>
                        <button
                          type="submit"
                          className="button primary"
                          disabled={isMutationDisabled || isArchived || !preview || !confirmSync}
                        >
                          {state.busy ? 'Đang đồng bộ…' : 'Đồng bộ ghi danh'}
                        </button>
                      </div>
                    </fieldset>
                  </form>
                </div>

                {/* Chuyển sang MANUAL */}
                <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                  <h3 style={{ margin: '0 0 8px' }}>Chuyển sang chế độ MANUAL</h3>
                  <p className="muted" style={{ fontSize: '13px', margin: '0 0 14px' }}>
                    Chuyển sang chế độ quản lý trực tiếp. Danh sách học sinh sẽ được quản trị viên thêm, bớt hoặc chuyển lớp thủ công.
                  </p>

                  <form className="form-stack" onSubmit={handleManualSwitchSubmit}>
                    <fieldset disabled={isMutationDisabled || isArchived} style={{ border: 0, padding: 0, margin: 0 }}>
                      <ReasonSelect
                        id="manual-switch-reason-select"
                        value={manualSwitchReason}
                        onChange={setManualSwitchReason}
                      />

                      <label className="check-label" style={{ marginTop: '12px', fontWeight: 600 }}>
                        <input
                          type="checkbox"
                          checked={confirmManualSwitch}
                          onChange={e => setConfirmManualSwitch(e.target.checked)}
                        />
                        Tôi xác nhận chuyển chế độ ghi danh sang MANUAL
                      </label>

                      <div className="accounts-actions" style={{ marginTop: '16px' }}>
                        <button
                          type="submit"
                          className="button primary"
                          disabled={isMutationDisabled || isArchived || !confirmManualSwitch}
                        >
                          {state.busy ? 'Đang chuyển…' : 'Chuyển sang MANUAL'}
                        </button>
                      </div>
                    </fieldset>
                  </form>
                </div>
              </div>
            )}

            {/* Chế độ MANUAL: Chuyển sang AUTO */}
            {klass.enrollment_mode === 'MANUAL' && (
              <div className="card accounts-panel" style={{ border: '1px solid #cbd5e1', marginBottom: '28px' }}>
                <h3 style={{ margin: '0 0 8px' }}>Chuyển sang chế độ AUTO theo lớp hành chính</h3>
                <p className="muted" style={{ fontSize: '13px', margin: '0 0 14px' }}>
                  Chuyển sang ghi danh tự động theo lớp hành chính liên kết. Thao tác chỉ được thực hiện sau khi xem trước và đối chiếu đúng phiên bản lớp và roster mới nhất.
                </p>

                {!preview && (
                  <p className="muted" style={{ fontSize: '13px', color: '#b45309' }}>
                    * Bắt buộc bấm &ldquo;Xem trước tác động ghi danh&rdquo; ở trên trước khi có thể chuyển sang AUTO.
                  </p>
                )}

                {preview && (
                  <p style={{ fontSize: '13px', margin: '0 0 12px' }}>
                    Phiên bản xác nhận: Lớp <code>v{preview.class_version}</code> · Danh sách <code>v{preview.roster_version}</code>
                  </p>
                )}

                <form className="form-stack" onSubmit={handleAutoSwitchSubmit}>
                  <fieldset disabled={isMutationDisabled || isArchived || !preview} style={{ border: 0, padding: 0, margin: 0 }}>
                    <ReasonSelect
                      id="auto-switch-reason-select"
                      value={autoSwitchReason}
                      onChange={setAutoSwitchReason}
                    />

                    <label className="check-label" style={{ marginTop: '12px', fontWeight: 600 }}>
                      <input
                        type="checkbox"
                        checked={confirmAutoSwitch}
                        onChange={e => setConfirmAutoSwitch(e.target.checked)}
                      />
                      Tôi xác nhận chuyển chế độ ghi danh sang AUTO theo kết quả xem trước đối chiếu
                    </label>

                    <div className="accounts-actions" style={{ marginTop: '16px' }}>
                      <button
                        type="submit"
                        className="button primary"
                        disabled={isMutationDisabled || isArchived || !preview || !confirmAutoSwitch}
                      >
                        {state.busy ? 'Đang chuyển…' : 'Xác nhận chuyển sang AUTO'}
                      </button>
                    </div>
                  </fieldset>
                </form>
              </div>
            )}

            {/* Thao tác thủ công với thành viên (MANUAL Member Mutations) */}
            <div style={{ marginTop: '24px', borderTop: '2px solid #e2e8f0', paddingTop: '20px' }}>
              <h3>Điều chỉnh thành viên thủ công</h3>
              <p className="muted" style={{ fontSize: '13px', margin: '0 0 16px' }}>
                Thêm học sinh, kết thúc ghi danh hoặc chuyển học sinh sang lớp môn học khác.
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))', gap: '20px' }}>
                {/* 1. Thêm thành viên */}
                <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                  <h4 style={{ margin: '0 0 8px' }}>Thêm học sinh vào lớp</h4>
                  <form className="form-stack" onSubmit={handleAddMemberSubmit}>
                    <fieldset disabled={isMutationDisabled || isArchived} style={{ border: 0, padding: 0, margin: 0 }}>
                      <label htmlFor="add-member-student-select">
                        Chọn học sinh
                        <select
                          id="add-member-student-select"
                          required
                          value={addStudentId}
                          onChange={e => setAddStudentId(e.target.value)}
                        >
                          <option value="">-- Chọn học sinh --</option>
                          {nonMemberStudents.map(student => (
                            <option key={student.id} value={student.id}>
                              {getUserLabel(student, student.id)}
                            </option>
                          ))}
                        </select>
                      </label>

                      <ReasonSelect
                        id="add-member-reason-select"
                        value={addReason}
                        onChange={setAddReason}
                      />

                      <label className="check-label" style={{ marginTop: '10px' }}>
                        <input
                          type="checkbox"
                          checked={confirmAdd}
                          onChange={e => setConfirmAdd(e.target.checked)}
                        />
                        Xác nhận thêm học sinh vào lớp
                      </label>

                      <div className="accounts-actions" style={{ marginTop: '14px' }}>
                        <button
                          type="submit"
                          className="button primary"
                          disabled={isMutationDisabled || isArchived || !addStudentId || !confirmAdd}
                        >
                          Thêm vào lớp
                        </button>
                      </div>
                    </fieldset>
                  </form>
                </div>

                {/* 2. Kết thúc ghi danh */}
                <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                  <h4 style={{ margin: '0 0 8px' }}>Kết thúc ghi danh</h4>
                  <form className="form-stack" onSubmit={handleEndMemberSubmit}>
                    <fieldset disabled={isMutationDisabled || isArchived} style={{ border: 0, padding: 0, margin: 0 }}>
                      <label htmlFor="end-member-student-select">
                        Chọn học sinh đang tham gia
                        <select
                          id="end-member-student-select"
                          required
                          value={endStudentId}
                          onChange={e => setEndStudentId(e.target.value)}
                        >
                          <option value="">-- Chọn học sinh đang tham gia --</option>
                          {activeMembers.map(member => {
                            const user = state.users.find(u => u.id === member.student_id);
                            return (
                              <option key={member.student_id} value={member.student_id}>
                                {getUserLabel(user, member.student_id)}
                              </option>
                            );
                          })}
                        </select>
                      </label>

                      <ReasonSelect
                        id="end-member-reason-select"
                        value={endReason}
                        onChange={setEndReason}
                      />

                      <label className="check-label" style={{ marginTop: '10px' }}>
                        <input
                          type="checkbox"
                          checked={confirmEnd}
                          onChange={e => setConfirmEnd(e.target.checked)}
                        />
                        Xác nhận kết thúc ghi danh học sinh
                      </label>

                      <div className="accounts-actions" style={{ marginTop: '14px' }}>
                        <button
                          type="submit"
                          className="button"
                          style={{ color: '#b91c1c' }}
                          disabled={isMutationDisabled || isArchived || !endStudentId || !confirmEnd}
                        >
                          Kết thúc ghi danh
                        </button>
                      </div>
                    </fieldset>
                  </form>
                </div>

                {/* 3. Chuyển lớp */}
                <div className="card accounts-panel" style={{ border: '1px solid #e2e8f0' }}>
                  <h4 style={{ margin: '0 0 8px' }}>Chuyển lớp môn học</h4>
                  <form className="form-stack" onSubmit={handleTransferMemberSubmit}>
                    <fieldset disabled={isMutationDisabled || isArchived} style={{ border: 0, padding: 0, margin: 0 }}>
                      <label htmlFor="transfer-member-student-select">
                        Học sinh cần chuyển
                        <select
                          id="transfer-member-student-select"
                          required
                          value={transferStudentId}
                          onChange={e => setTransferStudentId(e.target.value)}
                        >
                          <option value="">-- Chọn học sinh đang tham gia --</option>
                          {activeMembers.map(member => {
                            const user = state.users.find(u => u.id === member.student_id);
                            return (
                              <option key={member.student_id} value={member.student_id}>
                                {getUserLabel(user, member.student_id)}
                              </option>
                            );
                          })}
                        </select>
                      </label>

                      <label htmlFor="transfer-member-destination-select">
                        Lớp môn học đích
                        <select
                          id="transfer-member-destination-select"
                          required
                          value={destinationClassId}
                          onChange={e => setDestinationClassId(e.target.value)}
                        >
                          <option value="">-- Chọn lớp môn học đích --</option>
                          {destinationClasses.map(dest => (
                            <option key={dest.id} value={dest.id}>
                              {dest.name} (Khối {dest.grade_level})
                            </option>
                          ))}
                        </select>
                      </label>

                      <ReasonSelect
                        id="transfer-member-reason-select"
                        value={transferMemberReason}
                        onChange={setTransferMemberReason}
                      />

                      <label className="check-label" style={{ marginTop: '10px' }}>
                        <input
                          type="checkbox"
                          checked={confirmTransferMember}
                          onChange={e => setConfirmTransferMember(e.target.checked)}
                        />
                        Xác nhận chuyển học sinh sang lớp đích
                      </label>

                      <div className="accounts-actions" style={{ marginTop: '14px' }}>
                        <button
                          type="submit"
                          className="button primary"
                          disabled={isMutationDisabled || isArchived || !transferStudentId || !destinationClassId || !confirmTransferMember}
                        >
                          Chuyển lớp môn học
                        </button>
                      </div>
                    </fieldset>
                  </form>
                </div>
              </div>
            </div>

            {/* Bảng danh sách thành viên */}
            <div style={{ marginTop: '32px', borderTop: '2px solid #e2e8f0', paddingTop: '20px' }}>
              <h3>Lịch sử & Danh sách thành viên lớp ({state.members.length})</h3>
              <div className="accounts-table-scroll" tabIndex={0} aria-label="Bảng thành viên lớp môn học" style={{ marginTop: '12px' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Học sinh</th>
                      <th>Mã học sinh</th>
                      <th>Nguồn ghi danh</th>
                      <th>Trạng thái</th>
                      <th>Ngày tham gia</th>
                      <th>Ngày kết thúc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.members.map(member => {
                      const user = state.users.find(u => u.id === member.student_id);
                      return (
                        <tr key={member.id}>
                          <td><strong>{getUserLabel(user, member.student_id)}</strong></td>
                          <td><code>{member.student_id}</code></td>
                          <td>{member.source === 'AUTO' ? 'Tự động (AUTO)' : 'Thủ công (MANUAL)'}</td>
                          <td>
                            <span className={`accounts-status accounts-status-${member.status === 'ACTIVE' ? 'active' : 'locked'}`}>
                              {member.status === 'ACTIVE' ? 'Đang tham gia' : 'Đã kết thúc'}
                            </span>
                          </td>
                          <td>{formatDate(member.joined_at)}</td>
                          <td>{formatDate(member.ended_at)}</td>
                        </tr>
                      );
                    })}
                    {state.members.length === 0 && (
                      <tr>
                        <td colSpan={6} className="muted">Lớp chưa có thành viên nào.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 10. ClassLifecycleView (a.lifecycle)
// ---------------------------------------------------------------------------

function ClassLifecycleView({
  params,
  state,
  onReload,
  onAcknowledgeUnknown,
  onCommand,
  onClearCode,
}: CoreManagementViewProps) {
  const klass = state.klass;
  const isMutationDisabled =
    state.busy ||
    !state.loaded ||
    state.needsReload ||
    state.unknown ||
    Boolean(state.issued);

  const [confirmArchive, setConfirmArchive] = useState(false);
  const [archiveReason, setArchiveReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  const [confirmRestore, setConfirmRestore] = useState(false);
  const [restoreReason, setRestoreReason] = useState<AdminReason>('ADMIN_INTERVENTION');

  useEffect(() => {
    setConfirmArchive(false);
    setConfirmRestore(false);
  }, [klass?.id, klass?.status, klass?.version]);

  const handleArchiveSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || !confirmArchive) return;
    onCommand('archiveClass', {
      classId: klass.id,
      reason: archiveReason,
    });
  };

  const handleRestoreSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!klass || isMutationDisabled || !confirmRestore) return;
    onCommand('restoreClass', {
      classId: klass.id,
      reason: restoreReason,
    });
  };

  if (!klass && state.loaded) {
    return (
      <div className="accounts-workspace">
        <section className="card accounts-panel">
          <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '16px', display: 'inline-block' }}>
            ← Quay lại danh sách lớp môn học
          </Link>
          <h2>Không tìm thấy lớp môn học</h2>
          <p className="muted">
            Không tìm thấy thông tin lớp với mã <code>{params.classId}</code> trong phạm vi nhà trường.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="accounts-workspace">
      <section className="card accounts-panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div>
            <Link className="accounts-link" href="/admin/classes" style={{ marginBottom: '8px', display: 'inline-block' }}>
              ← Quay lại danh sách lớp môn học
            </Link>
            <h1 style={{ margin: 0, fontSize: '24px' }}>
              Vòng đời lớp: {klass?.name}
            </h1>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Trạng thái máy chủ: <strong>{klass ? (CLASS_STATUS_LABELS[klass.status] ?? klass.status) : '—'}</strong> ·
              Phiên bản: <code>v{klass?.version}</code>
            </p>
          </div>
          <button
            type="button"
            className="button"
            disabled={state.busy}
            onClick={onReload}
          >
            {state.busy ? 'Đang tải lại…' : 'Tải lại dữ liệu'}
          </button>
        </div>

        <IssueNotice issue={state.issue} />

        {state.notice && (
          <div className="notice success" role="status" style={{ marginBottom: '16px' }}>
            <p style={{ margin: 0, fontWeight: 600 }}>{state.notice}</p>
          </div>
        )}

        {state.unknown && (
          <UnknownWarning
            reconciled={state.reconciled}
            onReload={onReload}
            onAcknowledge={onAcknowledgeUnknown}
            busy={state.busy}
          />
        )}

        {state.issued && (
          <IssuedCodeBanner
            issued={state.issued}
            onClear={onClearCode}
            busy={state.busy}
          />
        )}

        {klass && (
          <>
            <ClassAdminTabs classId={klass.id} current="lifecycle" />

            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
              <h3 style={{ margin: '0 0 10px', fontSize: '16px' }}>Thông tin đối chiếu vòng đời</h3>
              <dl className="accounts-details" style={{ margin: 0 }}>
                <div>
                  <dt>Tên lớp</dt>
                  <dd><strong>{klass.name}</strong></dd>
                </div>
                <div>
                  <dt>Mã định danh lớp</dt>
                  <dd><code>{klass.id}</code></dd>
                </div>
                <div>
                  <dt>Phiên bản máy chủ</dt>
                  <dd><code>v{klass.version}</code></dd>
                </div>
                <div>
                  <dt>Trạng thái hiện tại</dt>
                  <dd>
                    <span className={`accounts-status accounts-status-${klass.status.toLowerCase()}`}>
                      {CLASS_STATUS_LABELS[klass.status] ?? klass.status}
                    </span>
                  </dd>
                </div>
              </dl>
            </div>

            {/* If ACTIVE -> Archive Form */}
            {klass.status === 'ACTIVE' && (
              <div className="card accounts-panel" style={{ border: '1px solid #cbd5e1' }}>
                <h3 style={{ margin: '0 0 8px', color: '#991b1b' }}>Lưu trữ lớp môn học</h3>
                <p className="muted" style={{ fontSize: '13px', margin: '0 0 14px', lineHeight: 1.6 }}>
                  Lớp môn học sẽ được lưu trữ và chuyển sang trạng thái chỉ đọc trong hệ thống Core. Hoạt động giảng dạy, bài viết, và ghi danh mới sẽ dừng lại. Dữ liệu học tập và lịch sử thành viên được giữ nguyên theo phạm vi quyền.
                </p>

                <form className="form-stack" onSubmit={handleArchiveSubmit}>
                  <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                    <ReasonSelect
                      id="archive-class-reason-select"
                      value={archiveReason}
                      onChange={setArchiveReason}
                    />

                    <label className="check-label" style={{ marginTop: '14px', fontWeight: 600 }}>
                      <input
                        type="checkbox"
                        checked={confirmArchive}
                        onChange={e => setConfirmArchive(e.target.checked)}
                      />
                      Tôi xác nhận lưu trữ lớp môn học này. Lớp sẽ chuyển sang trạng thái chỉ đọc trong hệ thống Core.
                    </label>

                    <div className="accounts-actions" style={{ marginTop: '16px' }}>
                      <button
                        type="submit"
                        className="button"
                        style={{ color: '#b91c1c', borderColor: '#fca5a5' }}
                        disabled={isMutationDisabled || !confirmArchive}
                      >
                        {state.busy ? 'Đang lưu trữ lớp…' : 'Xác nhận lưu trữ lớp môn học'}
                      </button>
                    </div>
                  </fieldset>
                </form>
              </div>
            )}

            {/* If ARCHIVED -> Restore Form */}
            {klass.status === 'ARCHIVED' && (
              <div className="card accounts-panel" style={{ border: '1px solid #cbd5e1' }}>
                <h3 style={{ margin: '0 0 8px', color: '#0f766e' }}>Khôi phục lớp môn học</h3>
                <p className="muted" style={{ fontSize: '13px', margin: '0 0 14px', lineHeight: 1.6 }}>
                  Khôi phục lớp môn học để tiếp tục các hoạt động trong hệ thống Core. Các lượt ghi danh đã kết thúc trước đó không tự động kích hoạt lại.
                </p>

                <form className="form-stack" onSubmit={handleRestoreSubmit}>
                  <fieldset disabled={isMutationDisabled} style={{ border: 0, padding: 0, margin: 0 }}>
                    <ReasonSelect
                      id="restore-class-reason-select"
                      value={restoreReason}
                      onChange={setRestoreReason}
                    />

                    <label className="check-label" style={{ marginTop: '14px', fontWeight: 600 }}>
                      <input
                        type="checkbox"
                        checked={confirmRestore}
                        onChange={e => setConfirmRestore(e.target.checked)}
                      />
                      Tôi xác nhận khôi phục lớp môn học này để tiếp tục hoạt động trong hệ thống Core.
                    </label>

                    <div className="accounts-actions" style={{ marginTop: '16px' }}>
                      <button
                        type="submit"
                        className="button primary"
                        disabled={isMutationDisabled || !confirmRestore}
                      >
                        {state.busy ? 'Đang khôi phục lớp…' : 'Xác nhận khôi phục lớp môn học'}
                      </button>
                    </div>
                  </fieldset>
                </form>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Export: CoreManagementView
// ---------------------------------------------------------------------------

export function CoreManagementView(props: CoreManagementViewProps) {
  const { routeId } = props;

  switch (routeId) {
    case 'a.accounts':
      return <AccountsListView {...props} />;
    case 'a.account':
      return <AccountDetailView {...props} />;
    case 'a.catalog':
      return <CatalogView {...props} />;
    case 'a.homerooms':
      return <HomeroomsListView {...props} />;
    case 'a.homeroom':
      return <HomeroomDetailView {...props} />;
    case 'a.classes':
      return <ClassesListView {...props} />;
    case 'a.newClass':
      return <NewClassView {...props} />;
    case 'a.classSettings':
      return <ClassSettingsView {...props} />;
    case 'a.enrollment':
      return <ClassEnrollmentView {...props} />;
    case 'a.lifecycle':
      return <ClassLifecycleView {...props} />;
    default:
      return (
        <div className="accounts-workspace">
          <section className="card accounts-panel">
            <h2>Chức năng không tồn tại</h2>
            <p className="muted">Tuyến đường quản trị không hợp lệ.</p>
          </section>
        </div>
      );
  }
}
