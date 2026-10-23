'use client';
import {Suspense,useCallback,useEffect,useMemo,useState} from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import {useSearchParams} from 'next/navigation';
import {getRoute,homeFor,type RouteId} from '@/config/routes';
import {adapter} from '@/lib/data';
import {canOpenRoute,SAFE_ROUTE_QUERY_KEYS,withSafeRouteQuery} from '@/lib/navigation';
import {canonicalParams,featureOwnsRead,resourceParamsKey} from '@/lib/route-load-plan';
import type {Role,RouteParams,WorkspaceData} from '@/lib/domain';
import {errorMessage} from '@/lib/api/errors';
import {sameResourceId} from '@/lib/api/operations';
import {useSession} from './session-provider';
import {Brand,StatePanel} from './ui';
import {PageShell} from './shell';
import {ClassSummaryProvider,type ClassSummaryState} from './class-summary-context';
import {AuthView} from '@/features/identity/auth-view';

// Public auth screens do not eagerly load the authenticated feature registry.
const FeatureEntry=dynamic(()=>import('@/features').then(module=>module.FeatureEntry),{
  loading:()=> <StatePanel busy title="Đang mở nội dung…"/>,
});

function RouteScreenInner({routeId,params}:{routeId:RouteId;params:RouteParams}){
  const session=useSession(),route=getRoute(routeId),searchParams=useSearchParams();
  const queryParams:RouteParams={};
  searchParams?.forEach((value,key)=>{if(SAFE_ROUTE_QUERY_KEYS.has(key))queryParams[key]=value;});
  const paramsKey=canonicalParams({...queryParams,...params});
  const effectiveParams=useMemo<RouteParams>(()=>JSON.parse(paramsKey),[paramsKey]);
  const resourceKey=resourceParamsKey(routeId,effectiveParams);
  const [revision,setRevision]=useState(0);
  const actorKey=JSON.stringify([session.user?.id,session.user?.roles,session.user?.school_id]);
  const snapshotKey=JSON.stringify([routeId,resourceKey,actorKey,revision]);
  const featureKey=JSON.stringify([routeId,resourceKey,actorKey]);
  const summaryKey=JSON.stringify([routeId,resourceKey,actorKey]);
  const selfLoading=featureOwnsRead(routeId);
  const [snapshot,setSnapshot]=useState<{key:string;data:WorkspaceData}|null>(null);
  const [domain,setDomain]=useState<{key:string;value:ClassSummaryState}|null>(null);
  const publicRoute=route.allowedRoles.includes('public');
  const publish=useCallback((value:ClassSummaryState)=>{
    if(value.summary&&params.classId&&!sameResourceId(value.summary.id,params.classId))return;
    setDomain(previous=>previous?.key===summaryKey&&JSON.stringify(previous.value)===JSON.stringify(value)?previous:{key:summaryKey,value});
  },[summaryKey,params.classId]);

  useEffect(()=>{
    if(selfLoading||publicRoute||session.status!=='authenticated'||!session.user||!canOpenRoute(route,session.user.roles)){
      setSnapshot(null);return;
    }
    const controller=new AbortController();
    void adapter.workspace.load(routeId,effectiveParams,controller.signal)
      .then(data=>{if(!controller.signal.aborted)setSnapshot({key:snapshotKey,data});})
      .catch(error=>{if(!controller.signal.aborted)setSnapshot({key:snapshotKey,data:{kind:'unavailable',message:errorMessage(error)}});});
    return()=>controller.abort();
    // Position-only query updates keep the current resource; explicit reload reads current params.
  },[snapshotKey,selfLoading,publicRoute,session.status]);

  if(publicRoute)return <AuthView key={routeId} route={route}/>;
  if(session.status==='loading')return <main className="standalone"><Brand/><StatePanel busy title="Đang kiểm tra phiên…"/></main>;
  if(session.status==='unavailable')return <main className="standalone"><Brand/><StatePanel title="Chưa thể kiểm tra phiên" message={session.error??undefined}><button className="button" onClick={()=>void session.reload()}>Thử lại</button><Link href="/login">Đăng nhập</Link></StatePanel></main>;
  if(!session.user)return <main className="standalone"><Brand/><StatePanel title="Đăng nhập để tiếp tục"><Link className="button primary" href={'/login?next='+encodeURIComponent(windowPath(route.path,effectiveParams))}>Đăng nhập</Link></StatePanel></main>;
  if(!canOpenRoute(route,session.user.roles))return <main className="standalone"><Brand/><StatePanel title="Bạn không có quyền mở nội dung này"><Link href={homeFor(session.user.roles)}>Về trang chủ</Link></StatePanel></main>;
  const pathRole:Role|null=route.path.startsWith('/teacher')?'LECTURER':route.path.startsWith('/admin')?'ADMIN':route.path.startsWith('/student')?'STUDENT':null;
  const role=pathRole&&session.user.roles.includes(pathRole)?pathRole:session.user.roles.includes('ADMIN')?'ADMIN':session.user.roles.includes('LECTURER')?'LECTURER':'STUDENT';
  const data=snapshot?.key===snapshotKey?snapshot.data:null;
  const summaryState=domain?.key===summaryKey?domain.value:undefined;
  const summary=selfLoading?summaryState?.summary:data?.kind==='ready'?data.classSummary:undefined;
  const classLoading=Boolean(params.classId)&&(selfLoading?summaryState?.pending??true:data===null);
  const ownsHeading=['t.libraryDocument','s.progress','t.analytics','t.studentAnalytics','a.dataRequests','a.audit','a.reports','a.exports','s.reader','s.tutor','s.assessments','s.assessment','s.examAttempt','s.receipt','s.examResult','t.assessmentEditor','t.assessmentApproval','t.examGrading','s.assignments','s.assignment','s.historyResult','t.assignmentEditor','t.gradingQueue','t.assignmentGrading','t.correction','t.correctionApproval','t.activities','t.practiceEditor'].includes(routeId);
  return <ClassSummaryProvider publish={publish}>
    <PageShell route={route} params={effectiveParams} role={role} user={session.user} summary={summary} classLoading={classLoading} resourceTitle={data?.kind==='ready'?data.readerModel?.document.title:undefined}>
      {!ownsHeading&&<div className="page-heading"><div><h1>{route.title}</h1>{routeId.endsWith('home')&&<p className="muted">Chào {session.user.display_name??session.user.username??'bạn'}, chúc bạn một ngày học tập hiệu quả.</p>}</div></div>}
      <FeatureEntry key={featureKey} route={route} params={effectiveParams} data={data} role={role} user={session.user} reload={()=>setRevision(value=>value+1)}/>
    </PageShell>
  </ClassSummaryProvider>;
}
export function RouteScreen({routeId,params}:{routeId:RouteId;params:RouteParams}){
  return <Suspense fallback={<main className="standalone"><Brand/><StatePanel busy title="Đang tải trang…"/></main>}><RouteScreenInner routeId={routeId} params={params}/></Suspense>;
}
function windowPath(path:string,params:RouteParams){return withSafeRouteQuery(path.replace(/:(\w+)/g,(_,key:string)=>encodeURIComponent(params[key]??'')),params);}
