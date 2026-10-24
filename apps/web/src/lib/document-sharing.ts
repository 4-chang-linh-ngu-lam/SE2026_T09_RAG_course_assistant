import type { ClassDocumentGrant, ClassSummary, WorkspaceData } from './domain';
export type DocumentGrantChange = { documentId: string; classIds: string[]; shared: boolean; classRoute?: string };
export function newShareTargets(selected: readonly string[], eligible: readonly ClassSummary[], grants: readonly ClassDocumentGrant[]): string[] {
  const allowed = new Set(eligible.filter(c => c.status === 'ACTIVE').map(c => c.id));
  const existing = new Set(grants.filter(g => g.isShared).map(g => g.classId));
  return [...new Set(selected)].filter(id => allowed.has(id) && !existing.has(id));
}
// Only positive evidence of the exact target state resolves an ambiguous write.
// A negative snapshot may race a write still being processed; it never authorizes a retry.
export function documentGrantConfirmed(change: DocumentGrantChange, data: WorkspaceData): boolean {
  if (data.kind !== 'ready') return false;
  if (data.sourceDocumentDetail?.document.id === change.documentId) {
    return change.classIds.every(id => data.sourceDocumentDetail!.grants.some(g => g.classId === id && g.isShared) === change.shared);
  }
  if (!change.shared && change.classRoute && data.classSummary?.id === change.classRoute && data.classDocuments) {
    return !data.classDocuments.some(d => d.id === change.documentId);
  }
  return false;
}
