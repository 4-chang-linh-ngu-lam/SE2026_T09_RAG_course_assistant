'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { RouteDefinition } from '@/config/routes';
import type { Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import type { ClassroomAdminWorkspace } from '@/lib/classroom-admin';
import { adapter } from '@/lib/data';
import { errorMessage } from '@/lib/api/errors';
import { canonicalParams } from '@/lib/route-load-plan';
import { StatePanel } from '@/components/ui';
import { CatalogView, HomeroomList, HomeroomDetail } from './homerooms';
import { ClassList, ClassSettings } from './subject-classes';
import { EnrollmentView, LifecycleView } from './enrollment';
import './classroom-admin.css';
type Props = { route: RouteDefinition; data: WorkspaceData | null; role: Role; reload(): void; params: RouteParams; user: User };
export function ClassroomAdminFeature(props: Props) {
  const scope = `${props.user.id}:${props.route.id}:${props.params.classId ?? ''}:${props.params.homeroomId ?? ''}`;
  const paramsKey=canonicalParams(props.params);
  const loadParams=useMemo(()=>JSON.parse(paramsKey) as RouteParams,[paramsKey]);
  const [revision, setRevision] = useState(0), [state, setState] = useState<{ scope: string; data?: ClassroomAdminWorkspace; error?: string }>({ scope });
  const requestId=useRef(0), activeRequest=useRef<AbortController|null>(null);
  const loadCurrent=useCallback(async (retainOnError=false):Promise<ClassroomAdminWorkspace>=>{
    const current=++requestId.current;activeRequest.current?.abort();const controller=new AbortController();activeRequest.current=controller;
    setState(previous=>previous.scope===scope?{scope,data:previous.data}:{scope});
    try{
      const loaded=await adapter.classroom.load(props.route.id,loadParams,controller.signal);
      if(current!==requestId.current||controller.signal.aborted)throw new DOMException('Workspace read was superseded.','AbortError');
      setState({scope,data:loaded});
      return loaded;
    }catch(error){
      if(!retainOnError&&current===requestId.current&&!controller.signal.aborted)setState(previous=>previous.scope===scope?{scope,data:previous.data,error:errorMessage(error)}:{scope,error:errorMessage(error)});
      throw error;
    }
  },[scope,props.route.id,loadParams]);
  useEffect(()=>{void loadCurrent().catch(()=>{});return()=>{requestId.current++;activeRequest.current?.abort();};},[loadCurrent,revision]);
  const reload = () => setRevision(value => value + 1), data = state.scope === scope ? state.data : undefined, error = state.scope === scope ? state.error : undefined;
  if (error) return <StatePanel title="Chưa thể mở quản lý lớp" message={error}><button className="button" onClick={reload}>Thử lại</button></StatePanel>;
  if (!data) return <StatePanel busy title="Đang tải cấu hình lớp học…"/>;
  return <div className="classroom-admin" key={scope}>{props.route.id === 'a.catalog' ? <CatalogView data={data} reload={reload}/> : props.route.id === 'a.homerooms' ? <HomeroomList data={data} reload={reload}/> : props.route.id === 'a.homeroom' ? (data.homeroom ? <HomeroomDetail data={data} room={data.homeroom} reload={reload} actorId={props.user.id}/> : <StatePanel title="Không tìm thấy lớp hành chính"/>) : props.route.id === 'a.classes' ? <ClassList data={data}/> : props.route.id === 'a.newClass' || props.route.id === 'a.classSettings' ? <ClassSettings data={data} subjectClass={data.subjectClass} isNew={props.route.id === 'a.newClass'} reload={reload} actorId={props.user.id}/> : props.route.id === 'a.enrollment' ? (data.subjectClass ? <EnrollmentView key={`${data.subjectClass.summary.id}:${data.subjectClass.revision}`} data={data} subjectClass={data.subjectClass} reload={reload} actorId={props.user.id}/> : <StatePanel title="Không tìm thấy lớp môn học"/>) : props.route.id === 'a.lifecycle' ? (data.subjectClass ? <LifecycleView data={data} subjectClass={data.subjectClass} reload={reload} loadCurrent={()=>loadCurrent(true)} actorId={props.user.id}/> : <StatePanel title="Không tìm thấy lớp môn học"/>) : <StatePanel title="Không tìm thấy trang quản lý"/>}</div>;
}
export { ClassroomAdminFeature as Feature };
