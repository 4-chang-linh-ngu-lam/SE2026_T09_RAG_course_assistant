'use client';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import { routeHref } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { StatePanel, Icon } from '@/components/ui';
import { matchRoute } from '@/lib/navigation';
export function WorkspaceFeature({ route, data, role, reload, params: _params, user: _user }: { route: RouteDefinition; data: WorkspaceData | null; role: Role; reload(): void; params?: RouteParams; user?: User }) {
  if (!data) return <StatePanel busy title="Đang tải nội dung…"/>;
  if (data.kind !== 'ready') return <StatePanel title={data.kind === 'empty' ? 'Chưa có nội dung' : 'Nội dung chưa sẵn sàng'} message={data.message}><button className="button" onClick={reload}>Tải lại</button></StatePanel>;
  return <div className="workspace-content">{data.classes && <div className="class-grid">{data.classes.map(cls => { const id = role === 'LECTURER' ? 't.overview' : role === 'ADMIN' ? 'a.classSettings' : cls.status === 'ARCHIVED' ? 's.history' : 's.overview'; return <article className="card class-card" key={cls.id}><span className="class-card-icon"><Icon name="book"/></span><span className="tag">{cls.code}</span><h2>{cls.name}</h2><p className="muted">{cls.metadata}</p><Link className="button" href={routeHref(id, { classId: cls.id })!}>Mở lớp</Link></article>; })}</div>}{data.rows && <section className="card"><div className="table-scroll" tabIndex={0} aria-label={route.title}><table><thead><tr><th>Nội dung</th><th>Chi tiết</th><th>Trạng thái</th><th><span className="sr-only">Thao tác</span></th></tr></thead><tbody>{data.rows.map(row => <tr key={row.id}><td><strong>{row.title}</strong></td><td>{row.detail}</td><td>{row.status && <span className="status">{row.status}</span>}</td><td>{row.href && matchRoute(row.href) && <Link href={row.href}>Xem chi tiết</Link>}</td></tr>)}</tbody></table></div>{!data.rows.length && <p className="padded muted">Chưa có nội dung phù hợp.</p>}</section>}{!data.classes && !data.rows && <StatePanel title="Chưa có nội dung"/>}</div>;
}
