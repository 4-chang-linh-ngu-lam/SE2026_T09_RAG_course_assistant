'use client';
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { getRoute, homeFor, type RouteId } from '@/config/routes';
import { adapter } from '@/lib/data';
import { canOpenRoute } from '@/lib/navigation';
import type { Role, RouteParams, WorkspaceData } from '@/lib/domain';
import { errorMessage } from '@/lib/api/errors';
import { useSession } from './session-provider';
import { Brand, StatePanel } from './ui';
import { PageShell } from './shell';
import { AuthView } from '@/features/identity/auth-view';
import { FeatureEntry } from '@/features';

const SAFE_QUERY_KEYS = new Set(['version', 'page', 'locator', 'section', 'conversationId', 'mode', 'format', 'search', 'sort', 'question', 'compose']);

function RouteScreenInner({ routeId, params }: { routeId: RouteId; params: RouteParams }) {
  const session = useSession(), route = getRoute(routeId);
  const searchParams = useSearchParams();
  const queryParams: Record<string, string> = {};
  if (searchParams) {
    searchParams.forEach((val, key) => {
      if (SAFE_QUERY_KEYS.has(key)) {
        queryParams[key] = val;
      }
    });
  }
  // Route params from Next.js path strictly take precedence over query parameters
  const effectiveParams: RouteParams = { ...queryParams, ...params };
  const [revision, setRevision] = useState(0);

  // Snapshot identity: includes routeId, query params, actor scope, and reload revision
  const snapshotKey = JSON.stringify([routeId, effectiveParams, session.user?.id, session.user?.roles, session.user?.school_id, revision]);
  const [snapshot, setSnapshot] = useState<{ key: string; data: WorkspaceData } | null>(null);
  const publicRoute = route.allowedRoles.includes('public');

  // Feature mount identity: stable across reloads and non-resource query changes (conversationId, page, mode, search),
  // but remounts cleanly on actor/role/school change or navigation to a different route/resource path or document version.
  const featureKey = JSON.stringify([
    routeId,
    session.user?.id,
    session.user?.roles,
    session.user?.school_id,
    params,
    (routeId === 's.reader' || routeId === 't.libraryDocument') ? effectiveParams.version : undefined,
  ]);

  useEffect(() => {
    if (publicRoute || session.status !== 'authenticated' || !session.user || !canOpenRoute(route, session.user.roles)) {
      setSnapshot(null);
      return;
    }
    const controller = new AbortController();
    void adapter.workspace
      .load(routeId, effectiveParams, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSnapshot({ key: snapshotKey, data }); })
      .catch(error => { if (!controller.signal.aborted) setSnapshot({ key: snapshotKey, data: { kind: 'unavailable', message: errorMessage(error) } }); });
    return () => controller.abort();
  }, [snapshotKey, publicRoute, session.status]); // snapshotKey captures route/params/query/actor/reload without retaining prior content.

  if (publicRoute) return <AuthView key={routeId} route={route}/>;
  if (session.status === 'loading') return <main className="standalone"><Brand/><StatePanel busy title="Đang kiểm tra phiên…"/></main>;
  if (session.status === 'unavailable') return <main className="standalone"><Brand/><StatePanel title="Chưa thể kiểm tra phiên" message={session.error ?? undefined}><button className="button" onClick={() => void session.reload()}>Thử lại</button><Link href="/login">Đăng nhập</Link></StatePanel></main>;
  if (!session.user) return <main className="standalone"><Brand/><StatePanel title="Đăng nhập để tiếp tục"><Link className="button primary" href={'/login?next=' + encodeURIComponent(windowPath(route.path, effectiveParams))}>Đăng nhập</Link></StatePanel></main>;
  if (!canOpenRoute(route, session.user.roles)) return <main className="standalone"><Brand/><StatePanel title="Bạn không có quyền mở nội dung này"><Link href={homeFor(session.user.roles)}>Về trang chủ</Link></StatePanel></main>;

  const pathRole: Role | null = route.path.startsWith('/teacher') ? 'LECTURER' : route.path.startsWith('/admin') ? 'ADMIN' : route.path.startsWith('/student') ? 'STUDENT' : null;
  const role = pathRole && session.user.roles.includes(pathRole) ? pathRole : session.user.roles.includes('ADMIN') ? 'ADMIN' : session.user.roles.includes('LECTURER') ? 'LECTURER' : 'STUDENT';
  const data = snapshot?.key === snapshotKey ? snapshot.data : null;
  const ownsHeading = ['s.progress','t.analytics','t.studentAnalytics','a.dataRequests','a.audit','a.reports','a.exports','s.reader','s.tutor','s.assessments','s.assessment','s.examAttempt','s.receipt','s.examResult','t.assessmentEditor','t.assessmentApproval','t.examGrading','s.assignments','s.assignment','s.historyResult','t.assignmentEditor','t.gradingQueue','t.assignmentGrading','t.correction','t.correctionApproval','t.activities','t.practiceEditor'].includes(routeId);

  return (
    <PageShell route={route} params={effectiveParams} role={role} user={session.user} summary={data?.kind === 'ready' ? data.classSummary : undefined} resourceTitle={data?.kind === 'ready' ? data.readerModel?.document.title : undefined}>
      {!ownsHeading && <div className="page-heading">
        <div>
          <h1>{route.title}</h1>
          {routeId.endsWith('home') && <p className="muted">Chào {session.user.display_name ?? session.user.username ?? 'bạn'}, chúc bạn một ngày học tập hiệu quả.</p>}
        </div>
        {routeId === 'a.accounts' && <Link className="button primary" href="/admin/accounts/students/new">Cấp tài khoản học sinh</Link>}
      </div>}
      <FeatureEntry key={featureKey} route={route} params={effectiveParams} data={data} role={role} user={session.user} reload={() => setRevision(x => x + 1)}/>
    </PageShell>
  );
}

export function RouteScreen({ routeId, params }: { routeId: RouteId; params: RouteParams }) {
  return (
    <Suspense fallback={<main className="standalone"><Brand/><StatePanel busy title="Đang tải trang…"/></main>}>
      <RouteScreenInner routeId={routeId} params={params} />
    </Suspense>
  );
}

function windowPath(path: string, params: RouteParams) {
  return path.replace(/:(\w+)/g, (_, key: string) => encodeURIComponent(params[key] ?? ''));
}
