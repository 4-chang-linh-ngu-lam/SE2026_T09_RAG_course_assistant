'use client';
import { useEffect, useState } from 'react';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import type { ClassroomAdminWorkspace } from '@/lib/classroom-admin';
import { adapter } from '@/lib/data';
import { errorMessage } from '@/lib/api/errors';
import { StatePanel } from '@/components/ui';
import { CatalogView, HomeroomList, HomeroomDetail } from './homerooms';
import { ClassList, ClassSettings } from './subject-classes';
import { EnrollmentView, LifecycleView } from './enrollment';
import './classroom-admin.css';
type Props = { route: RouteDefinition; data: WorkspaceData | null; role: Role; reload(): void; params: RouteParams; user: User };
export function ClassroomAdminFeature(props: Props) {
  const scope = `${props.user.id}:${props.route.id}:${props.params.classId ?? ''}:${props.params.homeroomId ?? ''}`;
  const [revision, setRevision] = useState(0), [state, setState] = useState<{ scope: string; data?: ClassroomAdminWorkspace; error?: string }>({ scope });
  useEffect(() => { const controller = new AbortController(); setState(previous => previous.scope === scope ? previous : { scope }); adapter.classroom.load(props.route.id, props.params, controller.signal).then(data => { if (!controller.signal.aborted) setState({ scope, data }); }).catch(error => { if (!controller.signal.aborted) setState({ scope, error: errorMessage(error) }); }); return () => controller.abort(); }, [scope, revision]);
  const reload = () => setRevision(value => value + 1), data = state.scope === scope ? state.data : undefined, error = state.scope === scope ? state.error : undefined;
  if (error) return <StatePanel title="Chưa thể mở quản lý lớp" message={error}><button className="button" onClick={reload}>Thử lại</button></StatePanel>;
  if (!data) return <StatePanel busy title="Đang tải cấu hình lớp học…"/>;
  return <div className="classroom-admin" key={scope}>{props.route.id === 'a.catalog' ? <CatalogView data={data} reload={reload}/> : props.route.id === 'a.homerooms' ? <HomeroomList data={data} reload={reload}/> : props.route.id === 'a.homeroom' ? (data.homeroom ? <HomeroomDetail data={data} room={data.homeroom} reload={reload} actorId={props.user.id}/> : <StatePanel title="Không tìm thấy lớp hành chính"/>) : props.route.id === 'a.classes' ? <ClassList data={data}/> : props.route.id === 'a.newClass' || props.route.id === 'a.classSettings' ? <ClassSettings data={data} subjectClass={data.subjectClass} isNew={props.route.id === 'a.newClass'} reload={reload} actorId={props.user.id}/> : props.route.id === 'a.enrollment' ? (data.subjectClass ? <EnrollmentView data={data} subjectClass={data.subjectClass} reload={reload} actorId={props.user.id}/> : <StatePanel title="Không tìm thấy lớp môn học"/>) : props.route.id === 'a.lifecycle' ? (data.subjectClass ? <LifecycleView data={data} subjectClass={data.subjectClass} reload={reload}/> : <StatePanel title="Không tìm thấy lớp môn học"/>) : <StatePanel title="Không tìm thấy trang quản lý"/>}</div>;
}
export { ClassroomAdminFeature as Feature };
