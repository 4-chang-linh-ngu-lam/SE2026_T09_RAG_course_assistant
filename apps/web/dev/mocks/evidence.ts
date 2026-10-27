import type { LearningEvidence } from '../../src/lib/learning-evidence';
const events = new Map<string, LearningEvidence>();
export function recordLearningEvidence(event: LearningEvidence): void {
  if (!Number.isFinite(event.score) || !Number.isFinite(event.maxScore) || event.maxScore <= 0 || !Number.isFinite(Date.parse(event.occurredAt))) return;
  const key = `${event.kind}:${event.id}:v${event.gradeVersion}`;
  const previous = events.get(key);
  if (previous && JSON.stringify(previous) !== JSON.stringify(event)) throw new Error('Confirmed evidence version cannot be overwritten');
  events.set(key, structuredClone(event));
}
export function readLearningEvidence(asOf: string): LearningEvidence[] {
  const at = Date.parse(asOf);
  if (!Number.isFinite(at)) return [];
  const latest = new Map<string, LearningEvidence>();
  for (const event of events.values()) {
    if (Date.parse(event.occurredAt) > at) continue;
    const key = `${event.kind}:${event.id}`;
    if (!latest.has(key) || latest.get(key)!.gradeVersion < event.gradeVersion) latest.set(key, event);
  }
  return structuredClone([...latest.values()]);
}
export function clearLearningEvidenceForTests(): void { events.clear(); }
