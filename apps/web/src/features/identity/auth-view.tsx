'use client';
import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { RouteDefinition } from '@/config/routes';
import { homeFor } from '@/config/routes';
import { safeReturnTo } from '@/lib/navigation';
import { adapter } from '@/lib/data';
import { ApiError, errorMessage } from '@/lib/api/errors';
import { Brand, ErrorNotice, Icon } from '@/components/ui';
import { useSession } from '@/components/session-provider';

export function AuthView({ route }: { route: RouteDefinition }) {
  const session = useSession(), router = useRouter();
  const [audience, setAudience] = useState<'student' | 'staff'>('student');
  const [identifier, setIdentifier] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [unknown, setUnknown] = useState(false);
  const [invalidCredential, setInvalidCredential] = useState(false);

  const isLogin = route.id === 'auth.login';
  const isActivate = route.id === 'auth.activate';
  const isRecovery = route.id === 'auth.recover';
  const isReset = route.id === 'auth.reset';
  const isInvitation = route.id === 'auth.invitation';
  const requiresNewPassword = isActivate || isReset || isInvitation;

  useEffect(() => {
    if (!isReset && !isInvitation) return;
    try {
      const url = new URL(window.location.href);
      const token = url.searchParams.get('token');
      if (token) {
        setCode(token);
        url.searchParams.delete('token');
        window.history.replaceState(null, '', url.pathname + url.search + url.hash);
      }
    } catch {
      // Safe fallback
    }
  }, [isReset, isInvitation]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || unknown) return;
    setError(null);
    setNotice(null);

    if (requiresNewPassword && password !== confirm) {
      setError('Mật khẩu xác nhận chưa khớp.');
      return;
    }

    setBusy(true);
    try {
      if (isLogin) {
        const user = await session.login(audience === 'student' ? { username: identifier, password } : { email: identifier, password });
        const next = new URLSearchParams(window.location.search).get('next');
        router.push(safeReturnTo(next, user.roles, homeFor(user.roles))!);
      } else if (isActivate) {
        await adapter.identity.activate({ username: identifier, activation_code: code, new_password: password });
        setNotice('Tài khoản đã được kích hoạt thành công. Bạn có thể đăng nhập ngay.');
      } else if (isRecovery && audience === 'staff') {
        await adapter.identity.forgot(identifier);
        setNotice('Nếu tài khoản đủ điều kiện, hướng dẫn khôi phục sẽ được gửi qua email công vụ của bạn.');
      } else if (isInvitation) {
        await adapter.identity.acceptInvitation(code, password);
        setNotice('Tài khoản giáo viên đã được thiết lập thành công. Bạn có thể đăng nhập ngay.');
      } else if (isReset) {
        await adapter.identity.reset(code, password);
        setNotice('Mật khẩu đã được đặt lại thành công. Bạn có thể đăng nhập với mật khẩu mới.');
      }
      setPassword('');
      setConfirm('');
      setCode('');
    } catch (value) {
      setError(errorMessage(value));
      setUnknown(value instanceof ApiError && value.outcome === 'unknown');
      if ((isReset || isInvitation) && value instanceof ApiError && value.status === 400 && value.outcome !== 'unknown') setInvalidCredential(true);
    } finally {
      setBusy(false);
    }
  }

  // Handle invalid/expired reset or invitation credential (C04e, base-3ad6cef9)
  if (invalidCredential && !notice) {
    return (
      <main className="auth-shell">
        <section className="auth-story">
          <Brand/>
          <div>
            <span className="eyebrow">XÁC THỰC TÀI KHOẢN</span>
            <h2>Bảo vệ an toàn<br/>cho không gian học.</h2>
            <p>Mỗi liên kết xác thực chỉ có hiệu lực một lần và có thời hạn nhất định.</p>
          </div>
          <small>Lumi · Học tập phổ thông</small>
        </section>
        <section className="auth-form-region">
          <div className="auth-card">
            <div className="auth-mobile-brand"><Brand/></div>
            <h1>Liên kết không còn hiệu lực</h1>
            <div className="notice error" role="alert">
              Liên kết đặt lại mật khẩu hoặc kích hoạt này đã hết hạn, không hợp lệ hoặc đã được sử dụng trước đó.
            </div>
            <p className="muted">
              {isInvitation
                ? 'Vui lòng liên hệ quản trị viên nhà trường để yêu cầu gửi lại thư mời.'
                : 'Vui lòng thực hiện lại yêu cầu khôi phục mật khẩu để nhận liên kết mới.'}
            </p>
            <div className="actions" style={{ marginTop: '24px' }}>
              <button className="button" onClick={() => { setInvalidCredential(false); setCode(''); setError(null); }}>Nhập mã khác</button>
              {isRecovery || isReset ? (
                <Link className="button primary" href="/recover">Yêu cầu liên kết mới</Link>
              ) : null}
              <Link className="button" href="/login">Về trang đăng nhập</Link>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <Brand/>
        <div>
          <span className="eyebrow">KHÔNG GIAN HỌC TẬP CỦA BẠN</span>
          <h2>Học sáng hơn,<br/>mỗi ngày.</h2>
          <p>Tài liệu, luyện tập và trợ lý Lumi trong cùng một lớp học.</p>
          <div className="book-art" aria-hidden="true">
            <span>∫</span>
            <span>π</span>
            <span>✦</span>
            <IconBook/>
          </div>
        </div>
        <small>Lumi · Học tập phổ thông</small>
      </section>

      <section className="auth-form-region">
        <div className="auth-card">
          <div className="auth-mobile-brand"><Brand/></div>
          <h1>{route.title}</h1>
          <p className="muted">
            {isActivate
              ? 'Dùng tên đăng nhập và mã một lần do nhà trường cấp để kích hoạt tài khoản học sinh.'
              : isInvitation
              ? 'Thiết lập mật khẩu an toàn để kích hoạt tài khoản công tác của bạn.'
              : isReset
              ? 'Nhập mật khẩu mới từ 12 đến 128 ký tự để bảo mật tài khoản.'
              : isLogin
              ? 'Chào mừng bạn quay trở lại với Lumi.'
              : 'Chọn đối tượng tài khoản và làm theo hướng dẫn an toàn.'}
          </p>

          {(isLogin || isRecovery) && (
            <div className="segmented" aria-label="Loại tài khoản" role="tablist">
              <button
                type="button"
                role="tab"
                id="tab-student"
                aria-selected={audience === 'student'}
                aria-pressed={audience === 'student'}
                onClick={() => { setAudience('student'); setIdentifier(''); setError(null); }}
              >
                Học sinh
              </button>
              <button
                type="button"
                role="tab"
                id="tab-staff"
                aria-selected={audience === 'staff'}
                aria-pressed={audience === 'staff'}
                onClick={() => { setAudience('staff'); setIdentifier(''); setError(null); }}
              >
                Giáo viên & quản trị viên
              </button>
            </div>
          )}

          {isRecovery && audience === 'student' && (
            <div className="notice" role="status">
              <strong>Quy định khôi phục mật khẩu học sinh:</strong>
              <p style={{ marginTop: '8px' }}>
                Học sinh không tự khôi phục mật khẩu qua email. Vui lòng liên hệ trực tiếp giáo viên chủ nhiệm hoặc quản trị viên nhà trường để xác minh danh tính và nhận mã đặt lại mật khẩu một lần.
              </p>
              <div style={{ marginTop: '16px' }}>
                <Link className="button primary" href="/reset-password">Tôi đã có mã đặt lại mật khẩu</Link>
                <Link className="button" href="/login">Về trang đăng nhập</Link>
              </div>
            </div>
          )}

          {(!isRecovery || audience === 'staff') && !notice && (
            <form onSubmit={submit} className="form-stack">
              {(isLogin || isActivate || (isRecovery && audience === 'staff')) && (
                <label htmlFor="identifier">
                  {audience === 'staff' && !isActivate ? 'Email công vụ' : 'Tên đăng nhập'}
                  <input
                    id="identifier"
                    autoComplete="username"
                    type={audience === 'staff' && !isActivate ? 'email' : 'text'}
                    placeholder={audience === 'staff' && !isActivate ? 'vi_du: ha.nguyen@lumi.edu.vn' : 'Ví dụ: minh.anh10a1'}
                    required
                    value={identifier}
                    onChange={e => setIdentifier(e.target.value)}
                  />
                </label>
              )}

              {isActivate && (
                <label htmlFor="activation-code">
                  Mã kích hoạt một lần (do nhà trường cấp)
                  <input
                    id="activation-code"
                    required
                    type="password"
                    autoComplete="one-time-code"
                    placeholder="Nhập mã kích hoạt gồm chữ và số"
                    value={code}
                    onChange={e => setCode(e.target.value)}
                  />
                </label>
              )}

              {(isReset || isInvitation) && (
                <label htmlFor="reset-token">
                  Mã xác thực một lần
                  <input
                    id="reset-token"
                    required
                    type="password"
                    autoComplete="one-time-code"
                    placeholder="Nhập mã từ thư mời hoặc do nhà trường cấp"
                    value={code}
                    onChange={e => setCode(e.target.value)}
                  />
                </label>
              )}

              {(isLogin || requiresNewPassword) && (
                <label htmlFor="password">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>{requiresNewPassword ? 'Mật khẩu mới' : 'Mật khẩu'}</span>
                    <button
                      type="button"
                      id="toggle-password"
                      className="icon-button"
                      style={{ fontSize: '12px', minWidth: 'auto', height: 'auto', padding: '2px 4px' }}
                      onClick={() => setShowPassword(v => !v)}
                    >
                      {showPassword ? 'Ẩn' : 'Hiển thị'}
                    </button>
                  </div>
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    minLength={requiresNewPassword ? 12 : 1}
                    maxLength={128}
                    autoComplete={requiresNewPassword ? 'new-password' : 'current-password'}
                    placeholder={requiresNewPassword ? 'Tối thiểu 12 ký tự' : '••••••••••••'}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                  />
                  {requiresNewPassword && <small>Mật khẩu an toàn từ 12 đến 128 ký tự.</small>}
                </label>
              )}

              {requiresNewPassword && (
                <label htmlFor="confirm-password">
                  Xác nhận mật khẩu mới
                  <input
                    id="confirm-password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    minLength={12}
                    maxLength={128}
                    autoComplete="new-password"
                    placeholder="Nhập lại mật khẩu mới"
                    value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                  />
                </label>
              )}

              <ErrorNotice message={error}/>

              <button className="button primary" disabled={busy || unknown} type="submit">
                {busy
                  ? 'Đang xử lý…'
                  : isLogin
                  ? 'Đăng nhập'
                  : isActivate
                  ? 'Kích hoạt tài khoản'
                  : isRecovery
                  ? 'Gửi hướng dẫn khôi phục'
                  : isInvitation
                  ? 'Thiết lập mật khẩu & Tham gia'
                  : 'Đặt lại mật khẩu'}
              </button>
            </form>
          )}

          {notice && (
            <div className="notice success" role="status">
              <strong>Hoàn tất thành công</strong>
              <p style={{ marginTop: '8px' }}>{notice}</p>
              <div style={{ marginTop: '16px' }}>
                <Link className="button primary" href="/login">Đăng nhập ngay</Link>
              </div>
            </div>
          )}

          <div className="auth-links">
            {isLogin ? (
              <>
                <Link id="login-recovery-link" href="/recover">Quên mật khẩu?</Link>
                <Link href="/activate">Kích hoạt tài khoản →</Link>
              </>
            ) : (
              <Link href="/login">← Về trang đăng nhập</Link>
            )}
          </div>

          {unknown && isLogin && (
            <button className="button" style={{ marginTop: '12px' }} onClick={() => void session.reload()}>
              Kiểm tra phiên đăng nhập
            </button>
          )}

          {session.user && (
            <div style={{ marginTop: '20px' }}>
              <Link className="back-link" href={homeFor(session.user.roles)}>
                <Icon name="arrow"/> Về trang chủ của tôi
              </Link>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function IconBook() {
  return (
    <svg width="180" height="150" viewBox="0 0 180 150" fill="none">
      <path d="M20 30c25-12 45-12 70 4 25-16 45-16 70-4v95c-25-12-45-12-70 4-25-16-45-16-70-4V30Z" fill="white"/>
      <path d="M90 34v95M35 48c15-5 28-4 41 2m-41 16c15-5 28-4 41 2m28-18c13-6 26-7 41-2m-41 20c13-6 26-7 41-2" stroke="#93C5FD" strokeWidth="3" strokeLinecap="round"/>
    </svg>
  );
}
