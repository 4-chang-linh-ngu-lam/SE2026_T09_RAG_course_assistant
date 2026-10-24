import {getRoute} from '@/config/routes';
import type {RouteParams} from '@/lib/domain';
import {canonicalResourceId} from './api/operations';

const featureOwned = new Set([
  's.feed','t.feed','account.notifications',
  't.library','t.libraryDocument','t.documents','s.documents','s.reader','s.notes',
  'account.profile','account.requests','a.newStudent',
  'a.accounts','a.account','a.legacy','a.staffInvite','a.importNew','a.import',
  'a.catalog','a.homerooms','a.homeroom','a.classes','a.newClass','a.classSettings','a.enrollment','a.lifecycle',
  's.progress','t.analytics','t.studentAnalytics','a.dataRequests','a.audit','a.reports','a.exports',
  's.assessments','s.assessment','s.examAttempt','s.receipt','s.examResult','t.assessmentEditor','t.assessmentApproval','t.examGrading',
  's.assignments','s.assignment','s.historyResult','t.assignmentEditor','t.gradingQueue','t.assignmentGrading','t.correction','t.correctionApproval',
  't.practiceEditor',
]);

export function featureOwnsRead(routeId: string): boolean { return featureOwned.has(routeId); }
export function canonicalParams(params: RouteParams): string {
  return JSON.stringify(Object.fromEntries(Object.entries(params).map(([key,value])=>[key,key.endsWith('Id')?canonicalResourceId(value):value]).sort(([a],[b])=>a.localeCompare(b))));
}

/** Resource identity, distinct from position/filter UI. Reader pages may arrive in one versioned model. */
export function resourceParamsKey(routeId: string, params: RouteParams): string {
  const keys = [...getRoute(routeId).path.matchAll(/:(\w+)/g)].map(match=>match[1]);
  if (routeId === 's.reader' || routeId === 't.libraryDocument') keys.push('version');
  if (routeId === 's.tutor') keys.push('conversationId');
  return canonicalParams(Object.fromEntries(keys.filter(key=>params[key]!==undefined).map(key=>[key,params[key]])));
}
