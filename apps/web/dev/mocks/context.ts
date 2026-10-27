import type { ClassSummary, User } from '../../src/lib/domain';

// Development-only dependencies shared by isolated preview domain stores.
// Each operation still validates its own actor/resource relation.
export type PreviewClassSource = { id: string; title: string; version: number; isReady: boolean };
export interface PreviewContext {
  actor(): User;
  classSummary(classId: string): ClassSummary | undefined;
  studentMembership(userId: string, classId: string): 'ACTIVE' | 'ENDED' | null;
  activeStudentIds(classId: string): string[];
  teachingRole(userId: string, classId: string): 'PRIMARY' | 'ASSISTING' | null;
  sources(classId: string): PreviewClassSource[];
  sourceAccessible(userId: string, classId: string, documentId: string, version: number): boolean;
  now(): number;
}
