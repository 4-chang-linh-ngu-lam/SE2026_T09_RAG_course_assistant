'use client';
import {useSession} from '@/components/session-provider';
import {useVolatileDraft} from '@/components/volatile-draft';
import { useState, type FormEvent } from 'react';
import { adapter } from '@/lib/data';
import type { IssuedCode } from '@/lib/domain';
import { ApiError, errorMessage } from '@/lib/api/errors';
import { ErrorNotice, useUnsavedChanges } from '@/components/ui';
export function ProvisioningFeature() {
  const {user}=useSession();
  const [username, setUsername] = useVolatileDraft(`${user?.id}:identity:provisioning:username`, ''), [name, setName] = useVolatileDraft(`${user?.id}:identity:provisioning:name`, ''), [issued, setIssued] = useState<IssuedCode | null>(null), [ack, setAck] = useState(false), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [error, setError] = useState<string | null>(null), [copied, setCopied] = useState(false);
  useUnsavedChanges(issued ? !ack : Boolean(username || name));
  async function submit(event: FormEvent) { event.preventDefault(); if (busy || unknown || issued) return; setBusy(true); setError(null); try { setIssued(await adapter.identity.createStudent(username, name.trim() || undefined)); setUsername(''); setName(''); } catch (e) { setError(errorMessage(e)); setUnknown(e instanceof ApiError && e.outcome === 'unknown'); } finally { setBusy(false); } }
  async function copy() { try { await navigator.clipboard.writeText(issued!.code); setCopied(true); } catch { setError('Chưa sao chép được. Hãy chọn mã bên dưới và sao chép thủ công.'); } }
  return <section className="card padded narrow"><h2>{issued ? 'Bàn giao mã kích hoạt' : 'Thông tin học sinh'}</h2>{issued ? <><p>Tài khoản <strong>{issued.student.username}</strong> đã được cấp. Mã chỉ hiển thị ở lần cấp này.</p><label htmlFor="issued-code">Mã kích hoạt một lần<input id="issued-code" value={issued.code} readOnly autoComplete="off"/></label><p className="muted">Có hạn đến {new Date(issued.expires_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })}.</p><button className="button" onClick={() => void copy()}>{copied ? 'Đã sao chép' : 'Sao chép mã'}</button><label className="check-label"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>Tôi đã bàn giao thông tin an toàn</label></> : <form className="form-stack" onSubmit={submit}><label htmlFor="student-username">Tên đăng nhập<input id="student-username" value={username} required maxLength={200} pattern="[^\s@]+" onChange={e => setUsername(e.target.value)}/></label><label htmlFor="student-name">Tên hiển thị (tùy chọn)<input id="student-name" value={name} maxLength={200} onChange={e => setName(e.target.value)}/></label><button className="button primary" disabled={busy || unknown}>{busy ? 'Đang cấp tài khoản…' : 'Cấp tài khoản học sinh'}</button></form>}<ErrorNotice message={error}/>{unknown && <p className="notice">Chưa rõ tài khoản đã được tạo hay chưa. Hãy kiểm tra tài khoản trước khi cấp lại, không gửi lặp yêu cầu.</p>}</section>;
}
