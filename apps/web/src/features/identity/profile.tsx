'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Dialog, ErrorNotice, useUnsavedChanges } from '@/components/ui';
import { useSession } from '@/components/session-provider';
import { errorMessage } from '@/lib/api/errors';
export function ProfileFeature() {
  const session = useSession(), router = useRouter();
  const [name, setName] = useState(session.user?.display_name ?? ''), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [saved, setSaved] = useState(false), [confirm, setConfirm] = useState(false);
  const dirty = name !== (session.user?.display_name ?? ''); useUnsavedChanges(dirty);
  async function save(event: FormEvent) { event.preventDefault(); setBusy(true); setError(null); try { await session.saveProfile(name.trim() || null); setSaved(true); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  async function logout() { setBusy(true); try { await session.logout(true); router.push('/login'); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); setConfirm(false); } }
  return <div className="two-columns"><section className="card padded"><h2>Thông tin cá nhân</h2><p className="muted">Tên đăng nhập và vai trò do nhà trường quản lý.</p><dl className="details"><dt>Tên đăng nhập</dt><dd>{session.user?.username ?? session.user?.email}</dd></dl><form className="form-stack" onSubmit={save}><label htmlFor="display-name">Tên hiển thị<input id="display-name" value={name} maxLength={200} onChange={e => { setName(e.target.value); setSaved(false); }}/><small>Bạn có thể để trống tên hiển thị.</small></label><ErrorNotice message={error}/>{saved && <p className="notice success" role="status">Đã lưu thông tin.</p>}<div className="actions"><button className="button primary" disabled={busy || !dirty}>Lưu thay đổi</button><button className="button" type="button" disabled={busy || !dirty} onClick={() => { setName(session.user?.display_name ?? ''); setSaved(false); }}>Hủy</button></div></form></section><section className="card padded"><h2>Bảo mật và dữ liệu</h2><div className="link-list"><Link href="/recover">Khôi phục mật khẩu</Link><Link href="/account/data-requests">Yêu cầu dữ liệu cá nhân</Link></div><button className="button danger" onClick={() => setConfirm(true)}>Đăng xuất mọi thiết bị</button></section><Dialog open={confirm} title="Đăng xuất mọi thiết bị?" onClose={() => { if (!busy) setConfirm(false); }}><p>Các phiên đang mở sẽ bị thu hồi. Bạn cần đăng nhập lại để tiếp tục.</p><div className="actions"><button className="button" disabled={busy} onClick={() => setConfirm(false)}>Hủy</button><button className="button danger" disabled={busy} onClick={() => void logout()}>{busy ? 'Đang xử lý…' : 'Xác nhận đăng xuất'}</button></div></Dialog></div>;
}
