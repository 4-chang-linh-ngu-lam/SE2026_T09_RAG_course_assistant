'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, TeacherActivityItem, User, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { ApiError, errorMessage } from '@/lib/api/errors';
import { draftStore } from '@/lib/draft-store';
import { Dialog, ErrorNotice, StatePanel } from '@/components/ui';
import './practice-authoring.css';
type Props = { route: RouteDefinition; data: WorkspaceData | null; role: Role; reload(): void; params: RouteParams; user: User };
type ActivityType = TeacherActivityItem['type'];
type Filters = { type: 'all' | ActivityType; status: 'all' | TeacherActivityItem['status']; search: string };
const TYPE_LABELS: Record<ActivityType, string> = { PRACTICE: 'Luyện tập', ASSESSMENT: 'Kiểm tra', ASSIGNMENT: 'Bài tập' };
const STATUS_LABELS: Record<TeacherActivityItem['status'], string> = { DRAFT: 'Bản nháp', PENDING_APPROVAL: 'Chờ giáo viên chính duyệt', PUBLISHED: 'Đã công bố' };
export function TeacherActivitiesView({ data, reload, params, user }: Props) {
  const router = useRouter();
  const model = data?.kind === 'ready' ? data.teacherActivities : undefined;
  const classId = params.classId ?? '';
  const key = `teacher-activities:${user.id}:${classId}`;
  const [filters, setFilters] = useState<Filters>(() => draftStore.get<Filters>(key) ?? { type: 'all', status: 'all', search: '' });
  const [domainRows, setDomainRows] = useState<TeacherActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [readRevision, setReadRevision] = useState(0);
  const [readError, setReadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [kind, setKind] = useState<ActivityType>('PRACTICE');
  const [name, setName] = useState('');
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creationUnknown, setCreationUnknown] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => { draftStore.set(key, filters); }, [key, filters]);
  useEffect(() => {
    let current = true;
    if (!model) return;
    setLoading(true); setReadError(null); setDomainRows([]);
    void Promise.allSettled([adapter.assessment.listTeacherActivities(classId), adapter.assignment.listTeacherActivities(classId)]).then(results => {
      if (!current) return;
      setDomainRows(results.flatMap(result => result.status === 'fulfilled' ? result.value : []));
      if (results.some(result => result.status === 'rejected')) setReadError('Chưa tải đủ các hoạt động kiểm tra hoặc bài tập. Bạn có thể tải lại danh sách.');
      setLoading(false);
    });
    return () => { current = false; };
  }, [model, classId, user.id, readRevision]);
  if (!data) return <StatePanel busy title="Đang tải hoạt động học tập…"/>;
  if (data.kind !== 'ready' || !model) return <StatePanel title="Chưa thể mở hoạt động học tập" message={data.kind === 'ready' ? 'Không có dữ liệu của lớp này.' : data.message}><button className="button" onClick={reload}>Tải lại</button></StatePanel>;
  const rows = [...model.activities.filter(row => row.type === 'PRACTICE'), ...domainRows];
  const filtered = rows.filter(row => (filters.type === 'all' || row.type === filters.type) && (filters.status === 'all' || row.status === filters.status) && `${row.title} ${row.topic}`.toLocaleLowerCase('vi').includes(filters.search.toLocaleLowerCase('vi')));
  async function create() {
    if (busy || creationUnknown) return;
    if (kind === 'PRACTICE' && (!name.trim() || !topic.trim())) { setError('Nhập tên bài luyện tập và chủ đề kiến thức.'); return; }
    setBusy(true); setError(null);
    try {
      const result = kind === 'PRACTICE'
        ? { href: (await adapter.learning.createPracticeDraft({ classId, title: name.trim(), topic: topic.trim() })).editHref }
        : kind === 'ASSESSMENT' ? await adapter.assessment.createDraft(classId) : await adapter.assignment.createDraft(classId);
      if (!active.current) return;
      setCreateOpen(false); router.push(result.href);
    } catch (err) {
      if (!active.current) return;
      setError(errorMessage(err));
      if (err instanceof ApiError && err.outcome === 'unknown') setCreationUnknown(true);
    } finally { if (active.current) setBusy(false); }
  }
  return <div className="teacher-activities-workspace">
    <div className="activities-context"><p>Vai trò của bạn trong lớp: <strong>{model.teacherRoleLabel}</strong> · {user.display_name ?? user.email}</p><label>Chọn lớp phụ trách<select id="assigned-class-selector" className="input" value={classId} onChange={e => { if (model.assignedClasses?.some(c => c.id === e.target.value)) router.push(`/teacher/classes/${e.target.value}/activities`); }}>{model.assignedClasses?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label></div>
    <div className="section-heading"><p className="muted">Quản lý hoạt động trong những lớp bạn được phân công.</p><button id="create-menu-btn" className="button primary" onClick={() => { setError(null); setCreateOpen(true); }}>+ Tạo hoạt động</button></div>
    <div className="card activities-filters"><div className="actions" role="group" aria-label="Loại hoạt động">{(['all','PRACTICE','ASSESSMENT','ASSIGNMENT'] as const).map(type => <button className={`button ${filters.type === type ? 'primary' : ''}`} aria-pressed={filters.type === type} key={type} onClick={() => setFilters({ ...filters, type })}>{type === 'all' ? 'Tất cả' : TYPE_LABELS[type]}</button>)}</div><label className="sr-only" htmlFor="activity-search">Tìm hoạt động</label><input id="activity-search" className="input" value={filters.search} placeholder="Tìm tên hoạt động, chủ đề…" onChange={e => setFilters({ ...filters, search: e.target.value })}/><label className="sr-only" htmlFor="activity-status">Trạng thái hoạt động</label><select id="activity-status" className="input" value={filters.status} onChange={e => { const status = (['all','DRAFT','PENDING_APPROVAL','PUBLISHED'] as const).find(s => s === e.target.value); if (status) setFilters({ ...filters, status }); }}><option value="all">Tất cả trạng thái</option>{Object.entries(STATUS_LABELS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></div>
    {readError && <div><ErrorNotice message={readError}/><button className="button" onClick={() => setReadRevision(v => v + 1)}>Tải lại danh sách</button></div>}
    {loading && <p role="status">Đang tải các hoạt động kiểm tra và bài tập…</p>}
    {filtered.length ? <div className="card activity-table-scroll" tabIndex={0} role="region" aria-label="Danh sách hoạt động học tập"><table className="activities-table"><thead><tr><th>Hoạt động</th><th>Loại</th><th>Chủ đề</th><th>Trạng thái</th><th>Hạn / Thời gian</th><th>Cần chấm</th><th>Thao tác</th></tr></thead><tbody>{filtered.map(row => <tr key={`${row.type}:${row.resourceId}`} data-resource-id={row.resourceId} data-activity-type={row.type}><td><strong>{row.title}</strong></td><td>{TYPE_LABELS[row.type]}</td><td>{row.topic}</td><td><span className={`badge ${row.status === 'PUBLISHED' ? 'success' : row.status === 'PENDING_APPROVAL' ? 'warning' : ''}`}>{STATUS_LABELS[row.status]}</span></td><td>{row.dueOrTimeLabel}</td><td>{row.pendingGradingCount === undefined ? '—' : row.pendingGradingCount}</td><td>{row.editHref ? <Link className="button small" href={row.editHref}>{row.status === 'DRAFT' ? 'Tiếp tục soạn' : row.status === 'PENDING_APPROVAL' ? 'Xem đề xuất' : 'Xem hoạt động'}</Link> : <span className="muted">Chưa có thao tác</span>}{row.submissionsHref && <Link className="button small" href={row.submissionsHref}>Xem bài nộp</Link>}</td></tr>)}</tbody></table></div> : !loading ? <StatePanel title={rows.length ? 'Không có hoạt động phù hợp bộ lọc' : 'Lớp chưa có hoạt động học tập'}><button className="button" onClick={() => setFilters({ type: 'all', status: 'all', search: '' })}>Xóa bộ lọc</button></StatePanel> : null}
    <p className="muted">Hiển thị {filtered.length} trên {rows.length} hoạt động.</p>
    <Dialog open={createOpen} title="Tạo hoạt động học tập" busy={busy} onClose={() => setCreateOpen(false)}><ErrorNotice message={error}/><label>Loại hoạt động<select id="form-activity-type" className="input" value={kind} disabled={busy} onChange={e => { const selected = (['PRACTICE','ASSESSMENT','ASSIGNMENT'] as const).find(type => type === e.target.value); if (selected) setKind(selected); }}>{Object.entries(TYPE_LABELS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>{kind === 'PRACTICE' ? <><label>Tên bài luyện tập<input id="form-activity-name" className="input" value={name} disabled={busy} onChange={e => setName(e.target.value)}/></label><label>Chủ đề kiến thức<input id="form-topic" className="input" value={topic} disabled={busy} onChange={e => setTopic(e.target.value)}/></label><p className="muted">Luyện tập không tính điểm chính thức.</p></> : <p>Tiếp tục đến trình soạn để nhập nội dung, thời gian và chính sách của {TYPE_LABELS[kind].toLocaleLowerCase('vi')}. Kiểm tra chính thức cần giáo viên chính phê duyệt trước khi công bố.</p>}<div className="actions"><button className="button" disabled={busy} onClick={() => setCreateOpen(false)}>Hủy bỏ</button><button id="ux-continue-editor" className="button primary" disabled={busy || creationUnknown} onClick={() => void create()}>{busy ? 'Đang tạo bản nháp…' : 'Tiếp tục soạn nội dung'}</button></div></Dialog>
  </div>;
}
