import type { ManagedClass } from '@/lib/classroom-admin';

export type PendingLifecycleMutation = {
  classId: string;
  revision: number;
  previousStatus: ManagedClass['summary']['status'];
  targetStatus: ManagedClass['summary']['status'];
};

export function classifyLifecycleObservation(
  pending: PendingLifecycleMutation,
  observed: ManagedClass,
): 'APPLIED' | 'UNKNOWN' {
  // Only a newer authoritative revision with the requested status confirms this mutation.
  // An unchanged/other revision cannot safely release the unknown-outcome lock.
  if (
    observed.summary.id === pending.classId &&
    observed.revision > pending.revision &&
    observed.summary.status === pending.targetStatus
  ) return 'APPLIED';
  return 'UNKNOWN';
}
