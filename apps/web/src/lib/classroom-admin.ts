import type { ClassSummary, RouteParams, User } from './domain';
export type AdminReason = 'ADMIN_INTERVENTION' | 'USER_REQUEST' | 'POLICY_VIOLATION';
export type EnrollmentMode = 'AUTO' | 'MANUAL';
export type CatalogKind = 'YEAR' | 'SEMESTER' | 'GRADE' | 'COURSE';
export type CatalogEntry = { id: string; kind: CatalogKind; name: string; revision: number; grade?: number; yearId?: string; code?: string; startDate?: string; endDate?: string };
export type Homeroom = { id: string; name: string; grade: number; yearId: string; revision: number; studentIds: string[] };
export type ClassMember = { userId: string; status: 'ACTIVE' | 'ENDED'; source: 'AUTO' | 'MANUAL' | 'OVERRIDE' };
export type ManagedClass = { summary: ClassSummary; revision: number; courseId: string; yearId: string; semesterId: string; grade: number; homeroomId: string | null; mode: EnrollmentMode; primaryTeacherId: string | null; assistingTeacherIds: string[]; members: ClassMember[]; manualIncludes: string[]; manualExcludes: string[] };
export type ClassroomChangePreview = { id: string; kind: 'ENROLLMENT' | 'HOMEROOM'; resourceId: string; revision: number; currentCount: number; projectedCount: number; addedIds: string[]; endedIds: string[]; status: 'PREVIEW' | 'APPLIED'; impact: { classId: string; className: string; currentCount: number; projectedCount: number }[]; policyNote: string };
export type ClassroomAudit = { id: string; actorId: string; resourceId: string; action: string; reason: AdminReason; at: string };
export type ClassroomAdminWorkspace = { revision: number; catalog: CatalogEntry[]; homerooms: Homeroom[]; classes: ManagedClass[]; students: User[]; teachers: User[]; homeroom?: Homeroom; subjectClass?: ManagedClass; auditEvents: ClassroomAudit[]; historyAvailable?: boolean; reasonCodes: { value: AdminReason; label: string }[]; policyNote: string };
export type ClassSettingsInput = { name: string; primaryTeacherId: string; assistingTeacherIds: string[] };
export interface ClassroomAdminPort {
  load(routeId: string, params: RouteParams, signal?: AbortSignal): Promise<ClassroomAdminWorkspace>;
  saveCatalog(input: { kind: CatalogKind; id?: string; name: string; grade?: number; yearId?: string; revision?: number; code?: string; startDate?: string; endDate?: string; reason: AdminReason }): Promise<CatalogEntry>;
  createHomeroom(input: { name: string; grade: number; yearId: string; reason: AdminReason }): Promise<Homeroom>;
  previewHomeroomRoster(input: { homeroomId: string; revision: number; studentIds: string[]; destinationHomeroomId?: string }): Promise<ClassroomChangePreview>;
  confirmHomeroomRoster(input: { previewId: string; reason: AdminReason }): Promise<ClassroomChangePreview>;
  createClass(input: ClassSettingsInput & { courseId: string; yearId: string; semesterId: string; grade: number; homeroomId: string | null; mode: EnrollmentMode; reason: AdminReason }): Promise<ManagedClass>;
  saveClassSettings(input: ClassSettingsInput & { classId: string; revision: number; reason: AdminReason }): Promise<ManagedClass>;
  previewEnrollment(input: { classId: string; revision: number; mode: EnrollmentMode; studentIds?: string[]; manualIncludes?: string[]; manualExcludes?: string[] }): Promise<ClassroomChangePreview>;
  confirmEnrollment(input: { previewId: string; reason: AdminReason }): Promise<ClassroomChangePreview>;
  reconcileEnrollment(previewId: string): Promise<ClassroomChangePreview>;
  changeLifecycle(input: { classId: string; revision: number; status: ClassSummary['status']; confirmation: string; reason: AdminReason }): Promise<ManagedClass>;
}
