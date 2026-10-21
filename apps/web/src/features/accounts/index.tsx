'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import type { AccountsWorkspace } from '@/lib/accounts';
import { adapter } from '@/lib/data';
import { errorMessage } from '@/lib/api/errors';
import { Dialog, Icon, StatePanel } from '@/components/ui';
import { ProvisioningFeature } from '@/features/identity/provisioning';
import { AccountDetail, AccountSummary, Recovery } from './account-detail';
import { LegacyAccounts, StaffInvitations } from './staff-legacy';
import { ImportNew, ImportReview } from './import-views';
import './accounts.css';
import { roleLabel, statusLabel, Status } from './common';
type Props = { route: RouteDefinition; data: WorkspaceData | null; role: Role; reload(): void; params: RouteParams; user: User };
export function AccountsFeature(props: Props) {
  const scope = `${props.user.id}:${props.route.id}:${props.params.userId ?? ''}:${props.params.importId ?? ''}`;
  const [revision, setRevision] = useState(0), [state, setState] = useState<{ scope: string; data?: AccountsWorkspace; error?: string }>({ scope });
  useEffect(() => { if(props.route.id === 'a.importNew')return; const controller = new AbortController(); setState(previous => previous.scope === scope ? previous : { scope }); adapter.accounts.load(props.route.id, props.params, controller.signal).then(data => { if (!controller.signal.aborted) setState({ scope, data }); }).catch(error => { if (!controller.signal.aborted) setState({ scope, error: errorMessage(error) }); }); return () => controller.abort(); }, [scope, revision]);
  const reload = () => setRevision(value => value + 1), data = state.scope === scope ? state.data : undefined, error = state.scope === scope ? state.error : undefined;
  if (props.route.id === 'a.newStudent') return <ProvisioningFeature/>;
  if (props.route.id === 'a.importNew') return <div className="accounts-workspace"><ImportNew actorId={props.user.id}/></div>;
  if (error) return <StatePanel title="Chưa thể mở quản lý tài khoản" message={error}><button className="button" onClick={reload}>Thử lại</button></StatePanel>;
  if (!data) return <StatePanel busy title="Đang tải tài khoản…"/>;
  return <div className="accounts-workspace" key={scope}>{props.route.id === 'a.accounts' ? <AccountList data={data} reload={reload}/> : props.route.id === 'a.account' ? (data.account ? <AccountDetail account={data.account} reload={reload} actorId={props.user.id}/> : <StatePanel title="Không tìm thấy tài khoản"/>) : props.route.id === 'a.legacy' ? <LegacyAccounts data={data} reload={reload}/> : props.route.id === 'a.staffInvite' ? <StaffInvitations data={data} reload={reload} actorId={props.user.id}/> : props.route.id === 'a.importNew' ? <ImportNew actorId={props.user.id}/> : props.route.id === 'a.import' ? (data.importJob ? <ImportReview initialJob={data.importJob}/> : <StatePanel title="Không tìm thấy lần nhập" message="Bản xem trước trong phiên dùng thử có thể đã kết thúc. Hãy chọn lại tệp nguồn."><Link className="button primary" href="/admin/imports/new">Chọn tệp</Link></StatePanel>) : <StatePanel title="Không tìm thấy trang quản lý"/>}</div>;
}
function AccountList({ data, reload }: { data: AccountsWorkspace; reload(): void }) {
  const query = useSearchParams(), pathname = usePathname();
  const kind = query.get('group') === 'staff' ? 'staff' : 'students', urlSearch = query.get('q') ?? '', status = query.get('status') ?? 'ALL';
  const page = Math.max(1, Number(query.get('page')) || 1), pageSize = 10;
  const [search, setSearch] = useState(urlSearch);
  const authoredSearch = useRef<string | null>(null);
  const composing = useRef(false);
  const [compositionRevision, setCompositionRevision] = useState(0);
  useEffect(() => {
    if (authoredSearch.current === urlSearch) { authoredSearch.current = null; return; }
    setSearch(urlSearch);
  }, [urlSearch]);
  useEffect(() => {
    if (composing.current || search === urlSearch) return;
    const timer = setTimeout(() => { if (!composing.current) filter('q', search); }, 200);
    return () => clearTimeout(timer);
  }, [search, urlSearch, pathname, compositionRevision]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = data.accounts.find(account => account.id === selectedId);
  const students = data.accounts.filter(account => account.roles.includes('STUDENT')), staff = data.accounts.filter(account => !account.roles.includes('STUDENT'));
  const filtered = (kind === 'students' ? students : staff).filter(account => (status === 'ALL' || account.status === status) && [account.username, account.email, account.display_name].some(value => value?.toLocaleLowerCase('vi').includes(search.toLocaleLowerCase('vi'))));
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize)), currentPage = Math.min(page, totalPages), visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  function filter(name: string, value: string) {
    const next = new URLSearchParams(window.location.search);
    if (value) next.set(name, value); else next.delete(name);
    if (name !== 'page') next.delete('page');
    if (name === 'q') authoredSearch.current = value;
    const suffix = next.toString();
    // This table already owns the loaded rows. URL-only filters need no RSC navigation.
    window.history.replaceState(null, '', pathname + (suffix ? '?' + suffix : ''));
  }
  return <><div className="accounts-stats"><article className="card"><span className="muted">Tài khoản học sinh</span><strong>{students.length}</strong><Icon name="user"/></article><article className="card"><span className="muted">Cán bộ & giáo viên</span><strong>{staff.length}</strong><Icon name="user"/></article></div><section className="card accounts-controls"><div className="accounts-tabs" aria-label="Nhóm tài khoản"><button className={kind === 'students' ? 'active' : ''} onClick={() => filter('group', 'students')}>Học sinh ({students.length})</button><button className={kind === 'staff' ? 'active' : ''} onClick={() => filter('group', 'staff')}>Cán bộ & giáo viên ({staff.length})</button></div><div className="accounts-actions"><Link className="button" href="/admin/imports/new"><Icon name="file"/>Nhập danh sách</Link><Link className="button" href="/admin/accounts/staff/invitations"><Icon name="user"/>Mời nhân sự</Link><Link className="button primary" href="/admin/accounts/students/new"><Icon name="plus"/>Cấp tài khoản học sinh</Link><Link className="accounts-subtle-link" href="/admin/accounts/legacy">Chuẩn hóa tài khoản cũ</Link></div><div className="accounts-filter"><label>Tìm tài khoản<input type="search" placeholder="Tên đăng nhập, email hoặc họ tên" value={search} onChange={event => setSearch(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={event => { composing.current = false; setSearch(event.currentTarget.value); setCompositionRevision(value => value + 1); }}/></label><label>Trạng thái<select value={status} onChange={event => filter('status', event.target.value)}><option value="ALL">Tất cả</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div></section><section className="card"><div className="accounts-table-scroll" tabIndex={0} aria-label="Danh sách tài khoản"><table><thead><tr><th>Tên đăng nhập / email</th><th>Họ và tên</th><th>Vai trò</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{visible.map(account => <tr key={account.id}><td><strong>{account.username ?? account.email ?? 'Chưa có tên đăng nhập'}</strong>{account.legacy && <small className="accounts-legacy">Cần chuẩn hóa</small>}</td><td>{account.display_name ?? 'Chưa cập nhật'}</td><td>{account.roles.map(role => roleLabel[role]).join(', ')}</td><td><Status value={account.status}/></td><td><button className="accounts-link" onClick={() => setSelectedId(account.id)}>Xem chi tiết</button></td></tr>)}</tbody></table></div>{!filtered.length && <div className="accounts-empty"><Icon name="user"/><h3>{search || status !== 'ALL' ? 'Không có tài khoản phù hợp' : 'Chưa có tài khoản trong nhóm này'}</h3><p className="muted">Điều chỉnh bộ lọc hoặc cấp tài khoản mới theo nhu cầu của nhà trường.</p></div>}<div className="accounts-pagination"><span>{filtered.length ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filtered.length)} trên ${filtered.length} tài khoản` : '0 tài khoản'}</span><div><button className="button" disabled={currentPage <= 1} onClick={() => filter('page', String(currentPage - 1))}>Trước</button><span>Trang {currentPage}/{totalPages}</span><button className="button" disabled={currentPage >= totalPages} onClick={() => filter('page', String(currentPage + 1))}>Sau</button></div></div></section><Dialog open={!!selected} title="Chi tiết tài khoản" onClose={() => setSelectedId(null)}>{selected && <><AccountSummary account={selected}/><div className="accounts-actions"><Link className="button primary" href={`/admin/accounts/${selected.id}`}>Quản lý vai trò và trạng thái</Link></div><Recovery account={selected} reload={reload}/></>}</Dialog></>;
}
export { AccountsFeature as Feature };
