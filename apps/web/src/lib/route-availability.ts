// Availability is presentation only. Route and server authorization still apply.
const liveUnavailable = new Set([
  's.notes', 't.library', 'a.reports', 'a.dataRequests',
  's.documents', 't.documents', 's.tutor', 't.tutor',
  's.practice', 's.assessments', 's.assignments', 's.progress',
  't.activities', 't.analytics',
]);

export function isRouteAvailable(id: string, source: 'live' | 'mock') {
  return source === 'mock' || !liveUnavailable.has(id);
}
