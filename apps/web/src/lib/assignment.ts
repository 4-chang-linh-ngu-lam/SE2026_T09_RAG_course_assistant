import type { AssessmentGrading, AssessmentResult } from './assessment';
import type { CalendarEvent, ClassSummary, RouteParams, TeacherActivityItem } from './domain';

// Frontend-only read models. Learning service contracts remain unapproved.
export type AssignmentSource = { id: string; title: string; version: number };
export type AssignmentPolicy = { maxVersions: number; allowLate: boolean; lateUntil: string | null; resubmitUntil: string | null; gradedVersion: 'LATEST' | 'FIRST'; maxBytes: number; acceptedTypes: string[]; newEnrollment: 'REVIEW' | 'AUTO' };
export type AssignmentDefinition = { activityType?: 'ASSIGNMENT' | 'ASSESSMENT'; publishedRevision?: number; id: string; classId: string; title: string; topic: string; instructions: string; dueAt: string; status: 'DRAFT' | 'PUBLISHED'; revision: number; policy: AssignmentPolicy; source?: AssignmentSource; sourceHref?: string };
export type SubmissionFile = { id: string; name: string; size: number; type: string };
export type AssignmentGrade = { version: number; score: number; feedback: string; teacherId: string; teacherName: string; confirmedAt: string; reason: string };
export type AssignmentSubmission = { id: string; assignmentId: string; assignmentRevision: number; classId: string; studentId: string; studentName: string; number: number; file: SubmissionFile; note: string; submittedAt: string; late: boolean; grade: AssignmentGrade | null; gradeHistory: AssignmentGrade[]; isGradedVersion: boolean; resultId: string };
export type AssignmentUpload = { id: string; assignmentId: string; file: SubmissionFile; acknowledgedAt: string; previewOnly: true };
export type GradeAppeal = { officialTarget?: { classId: string; assessmentId: string; attemptId: string }; id: string; classId: string; submissionId: string; studentId: string; reason: string; createdAt: string; status: 'OPEN' | 'PROPOSED' | 'RESOLVED'; resolution?: string };
export type GradeProposal = { officialTarget?: { classId: string; assessmentId: string; attemptId: string }; id: string; appealId: string; classId: string; submissionId: string; score: number; reason: string; expectedGradeVersion: number; proposerId: string; proposerName: string; proposedAt: string; status: 'PENDING' | 'APPROVED' | 'REJECTED'; decisionReason?: string; decidedAt?: string; decidedBy?: string };
export type GradingQueueItem = { id: string; title: string; studentName: string; number: number; submittedAt: string; late: boolean; graded: boolean; membershipEnded: boolean; href: string; kind: 'ASSIGNMENT' | 'ASSESSMENT' };
export type AssignmentPage =
 | { kind: 'official-history'; classSummary: ClassSummary; result: AssessmentResult; limitedHistory: boolean }
 | { kind: 'list'; classSummary: ClassSummary; assignments: { assignment: AssignmentDefinition; submissions: AssignmentSubmission[] }[] }
 | { kind: 'detail'; classSummary: ClassSummary; assignment: AssignmentDefinition; submissions: AssignmentSubmission[]; canSubmit: boolean; submitBlockedReason?: string; canAppeal: boolean; appeals: GradeAppeal[]; proposals: GradeProposal[] }
 | { kind: 'history'; classSummary: ClassSummary; assignment: AssignmentDefinition; submission: AssignmentSubmission; canAppeal: boolean; appeals: GradeAppeal[]; proposals: GradeProposal[]; limitedHistory: boolean }
 | { kind: 'editor'; classSummary: ClassSummary; assignment: AssignmentDefinition; sources: AssignmentSource[]; audience: {userId: string; assigned: boolean}[] }
 | { kind: 'queue'; classSummary: ClassSummary; items: GradingQueueItem[]; appeals: GradeAppeal[]; proposals: GradeProposal[] }
 | { kind: 'grading'; classSummary: ClassSummary; assignment: AssignmentDefinition; submission: AssignmentSubmission; submissions: AssignmentSubmission[]; teachingRole: 'PRIMARY' | 'ASSISTING'; appeals: GradeAppeal[] }
 | { kind: 'correction'; officialEvidence?: AssessmentGrading; classSummary: ClassSummary; assignment: AssignmentDefinition; submission: AssignmentSubmission; appeal: GradeAppeal; proposals: GradeProposal[]; teachingRole: 'PRIMARY' | 'ASSISTING' }
 | { kind: 'approval'; officialEvidence?: AssessmentGrading; classSummary: ClassSummary; assignment: AssignmentDefinition; submission: AssignmentSubmission; appeal: GradeAppeal; proposal: GradeProposal; canDecide: boolean };
export type AssignmentDraftInput = { classId: string; assignmentId: string; title: string; topic: string; instructions: string; dueAt: string; policy: AssignmentPolicy; source?: AssignmentSource; expectedRevision: number; publish: boolean };
export interface AssignmentPort {
 listCalendarEvents(classId:string):Promise<CalendarEvent[]>;
 listTeacherActivities(classId: string): Promise<TeacherActivityItem[]>;
 setRecipients(input: {classId: string; assignmentId: string; studentIds: string[]; expectedRevision: number}): Promise<void>;
 createDraft(classId: string): Promise<{assignmentId: string; href: string}>;
 load(routeId: string, params: RouteParams): Promise<AssignmentPage>;
 upload(input: { classId: string; assignmentId: string; file: File; expectedRevision: number }): Promise<AssignmentUpload>;
 submit(input: { classId: string; assignmentId: string; uploadId: string; expectedRevision: number; operationId: string; note: string }): Promise<AssignmentSubmission>;
 reconcile(input: { classId: string; assignmentId: string; operationId: string }): Promise<AssignmentSubmission | null>;
 readFile(input: { submissionId: string; fileId: string }): Promise<{ name: string; type: string; bytes: Uint8Array }>;
 saveDraft(input: AssignmentDraftInput): Promise<AssignmentDefinition>;
 grade(input: { submissionId: string; score: number; feedback: string; expectedGradeVersion: number }): Promise<AssignmentGrade>;
 gradeHint(input: { submissionId: string }): Promise<{ feedback: string; limitations: string }>;
 appeal(input: { submissionId: string; reason: string }): Promise<GradeAppeal>;
 propose(input: { classId: string; appealId: string; score: number; reason: string; expectedGradeVersion: number }): Promise<GradeProposal>;
 decide(input: { proposalId: string; approve: boolean; reason: string; expectedGradeVersion: number }): Promise<GradeProposal>;
}
