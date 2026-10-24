import type { IntelligenceAuditRecord } from '../../src/lib/intelligence';
import type { PreviewContext } from './context';
const events: IntelligenceAuditRecord[] = [];
export function recordPreviewAudit(event: Omit<IntelligenceAuditRecord, 'id'>): void { events.push({ ...structuredClone(event), id: crypto.randomUUID() }); }
export function readPreviewAudit(): IntelligenceAuditRecord[] { return structuredClone(events); }
// Only operation metadata reaches the audit journal. Never arguments, tokens,
// attachment contents, answer keys, or private conversations.
export function auditedPort<T extends object>(port: T, context: PreviewContext, resourceType: string, mutations: string[]): T {
  const selected = new Set(mutations);
  return Object.fromEntries(Object.entries(port).map(([name, value]) => {
    if (!selected.has(name) || typeof value !== 'function') return [name, value];
    return [name, async (...args: unknown[]) => {
      const actor = context.actor();
      const result: unknown = await value(...args);
      const input = args[0] && typeof args[0] === 'object' ? args[0] as Record<string, unknown> : {};
      const output = result && typeof result === 'object' ? result as Record<string, unknown> : {};
      const id = ['attemptId','submissionId','assessmentId','assignmentId','practiceId','userId','documentId','proposalId','appealId','importId','id'].map(key => input[key] ?? output[key]).find(item => typeof item === 'string');
      const published = (resourceType === 'assignment' && name === 'saveDraft' && input.publish === true && output.status === 'PUBLISHED') || (resourceType === 'assessment' && name === 'decide' && input.decision === 'APPROVE' && output.status === 'PUBLISHED') || (resourceType === 'practice' && name === 'publishPractice');
      recordPreviewAudit({ actorId: actor.id, actorName: actor.display_name ?? actor.username ?? actor.email ?? 'Người dùng', action: published ? `${resourceType.toUpperCase()}_PUBLISHED` : `${resourceType.toUpperCase()}_${name}`, resourceType, resourceId: typeof id === 'string' ? id : resourceType, classId: typeof input.classId === 'string' ? input.classId : undefined, reason: 'Thao tác đã được xác nhận trong phiên dùng thử.', at: new Date(context.now()).toISOString() });
      return result;
    }];
  })) as T;
}
