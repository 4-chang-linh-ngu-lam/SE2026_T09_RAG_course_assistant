import type { CalendarEvent, ClassSummary, RouteParams, TeacherActivityItem } from './domain';

import { routeHref } from '@/config/routes';

// Frontend-only read models. Learning has no approved public wire contract yet.
export type AssessmentType = 'single_choice' | 'multiple_choice' | 'true_false' | 'short_answer';
export type AssessmentSource = { documentId: string; title: string; version: number; locator: string; accessible: boolean };
export function assessmentSourceHref(classId: string, source: AssessmentSource): string | null {
  const path = routeHref('s.reader', { classId, documentId: source.documentId });
  if (!path) return null;
  const query = new URLSearchParams({ version: String(source.version), locator: source.locator });
  return `${path}?${query.toString()}`;
}
type QuestionBase = { id: string; type: AssessmentType; prompt: string; points: number; source?: AssessmentSource };
export type PublicAssessmentQuestion =
 | (QuestionBase & { type:'single_choice'|'multiple_choice'; options:{id:string;text:string}[] })
 | (QuestionBase & { type:'true_false'; statements:{id:string;text:string}[] })
 | (QuestionBase & { type:'short_answer' });
export type AssessmentQuestion = PublicAssessmentQuestion & { key: string[] | Record<string,boolean> | string; explanation:string; rubric:string; reviewed:boolean; aiProposed:boolean };
export type AssessmentAnswer = { questionId:string; value:string|string[]|Record<string,boolean> };
export type AssessmentAnswers = Record<string,AssessmentAnswer>;
export type AssessmentSettings = { title:string; code:string; opensAt:string; closesAt:string; durationMinutes:number; maxAttempts:number; gradingPolicy:'BEST'|'LATEST'|'AVERAGE'; resultsAt:string };
export type AssessmentDraft = { classId:string; assessmentId:string; revision:number; versionNumber:number; settings:AssessmentSettings; questions:AssessmentQuestion[]; status:'DRAFT'|'PENDING_APPROVAL'|'PUBLISHED'; authorName:string; rejectionReason:string|null; availableSources:AssessmentSource[]; canApprove:boolean };
export type AssessmentSummary = { id:string; title:string; code:string; versionNumber:number; questionCount:number; totalPoints:number; opensAt:string; closesAt:string; durationMinutes:number; resultsAt:string; maxAttempts:number; gradingPolicy:AssessmentSettings['gradingPolicy']; status:'UPCOMING'|'OPEN'|'CLOSED'; usedAttempts:number; activeAttemptId:string|null; completedAttemptId:string|null; canStart:boolean; unavailableReason:string|null };
export type AssessmentReceipt = { id:string; classId:string; assessmentId:string; attemptId:string; versionId:string; versionNumber:number; reason:'MANUAL'|'TIMEOUT'; submittedAt:string; savedAnswerCount:number; totalQuestionCount:number; savedRevision:number; resultReleased:boolean };
export type AssessmentAttempt = { classId:string; assessmentId:string; attemptId:string; ownerId:string; title:string; code:string; className:string; versionId:string; versionNumber:number; attemptNumber:number; questions:PublicAssessmentQuestion[]; savedAnswers:AssessmentAnswers; savedRevision:number; savedAt:string; serverNow:string; startedAt:string; endsAt:string; status:'IN_PROGRESS'|'SUBMITTED'; receipt:AssessmentReceipt|null };
export type AssessmentGradeHistory = { version:number; score:number; feedback:string; reason:string; at:string; approvedBy:string };
export type AssessmentReleasedQuestion = { question:PublicAssessmentQuestion; answer:AssessmentAnswer|null; score:number; maximum:number; feedback:string; releasedSolution:string; source:AssessmentSource|null };
export type AssessmentResult = { classId:string; assessmentId:string; attemptId:string; title:string; versionNumber:number; released:boolean; receipt:AssessmentReceipt; effectiveGrade:AssessmentGradeHistory|null; questions:AssessmentReleasedQuestion[]; gradeHistory:AssessmentGradeHistory[]; appeal:{allowed:boolean; reason:string|null; status:'NONE'|'PENDING'|'RESOLVED'; submittedReason:string|null}; pendingGradeProposal:boolean };
export type AssessmentGrading = { classId:string; assessmentId:string; attemptId:string; studentName:string; title:string; versionNumber:number; questions:{ question:AssessmentQuestion; answer:AssessmentAnswer|null; score:number|null; feedback:string }[]; gradeVersion:number; effectiveGrade:AssessmentGradeHistory|null; pendingProposal:{id:string; baseVersion:number; scores:Record<string,number>; feedback:string; reason:string; proposedBy:string}|null; canApprove:boolean };
export type AssessmentPage =
 | {type:'list';classSummary:ClassSummary;items:AssessmentSummary[];serverNow:string}
 | {type:'detail';classSummary:ClassSummary;assessment:AssessmentSummary;serverNow:string}
 | {type:'attempt';attempt:AssessmentAttempt}
 | {type:'receipt';receipt:AssessmentReceipt;title:string}
 | {type:'result';result:AssessmentResult}
 | {type:'editor'|'approval';classSummary:ClassSummary;draft:AssessmentDraft}
 | {type:'grading';grading:AssessmentGrading};
export type AssessmentLoad = {kind:'ready';page:AssessmentPage;classSummary?:ClassSummary}|{kind:'unavailable';message:string};
export type AssessmentTarget = {classId:string;assessmentId:string};
export type AssessmentAttemptTarget = AssessmentTarget & {attemptId:string};
export type AssessmentSubmission = {state:'CONFIRMED';receipt:AssessmentReceipt}|{state:'UNKNOWN';operationId:string};
export type OfficialCorrectionTarget = {classId:string;assessmentId:string;attemptId:string;title:string;studentName:string;studentId:string;appealId:string|null;appealReason:string|null;gradeHistory:AssessmentGradeHistory[];gradeVersion:number;effectiveScore:number;feedback:string};
export interface AssessmentPort {
 readOwnHistory(resultId:string):Promise<AssessmentResult>;
 load(routeId:string,params:RouteParams,signal?:AbortSignal):Promise<AssessmentLoad>;
 listCalendarEvents(classId:string):Promise<CalendarEvent[]>;
 listTeacherActivities(classId:string):Promise<TeacherActivityItem[]>;
 createDraft(classId:string):Promise<{assessmentId:string;href:string}>;
 saveDraft(input:AssessmentTarget & {expectedRevision:number;settings:AssessmentSettings;questions:AssessmentQuestion[]}):Promise<AssessmentDraft>;
 reviewQuestion(input:AssessmentTarget & {expectedRevision:number;questionId:string}):Promise<AssessmentDraft>;
 propose(input:AssessmentTarget & {expectedRevision:number}):Promise<AssessmentDraft>;
 decide(input:AssessmentTarget & {expectedRevision:number;decision:'APPROVE'|'REJECT';reason:string}):Promise<AssessmentDraft>;
 newVersion(input:AssessmentTarget):Promise<AssessmentDraft>;
 generateQuestions(input:AssessmentTarget & {documentId:string;version:number;instructions:string;type:AssessmentType}):Promise<AssessmentQuestion[]>;
 start(input:AssessmentTarget):Promise<{attemptId:string;href:string}>;
 saveAnswers(input:AssessmentAttemptTarget & {expectedRevision:number;answers:AssessmentAnswers}):Promise<AssessmentAttempt>;
 submit(input:AssessmentAttemptTarget & {operationId:string;expectedRevision:number}):Promise<AssessmentSubmission>;
 reconcileSubmission(input:AssessmentAttemptTarget & {operationId?:string}):Promise<{state:'IN_PROGRESS';attempt:AssessmentAttempt}|AssessmentSubmission>;
 appeal(input:AssessmentAttemptTarget & {reason:string;questionId?:string}):Promise<AssessmentResult>;
 proposeGrade(input:AssessmentAttemptTarget & {expectedGradeVersion:number;scores:Record<string,number>;feedback:string;reason:string}):Promise<AssessmentGrading>;
 approveGrade(input:AssessmentAttemptTarget & {proposalId:string;reason:string}):Promise<AssessmentGrading>;
 listSubmittedAttempts(classId:string):Promise<{classId:string;assessmentId:string;attemptId:string;title:string;studentName:string;submittedAt:string;released:boolean;effectiveScore:number|null;href:string}[]>;
 listGrading(classId:string):Promise<OfficialCorrectionTarget[]>;
 getCorrectionTarget(input:AssessmentAttemptTarget):Promise<OfficialCorrectionTarget>;
 applyGradeCorrection(input:AssessmentAttemptTarget & {expectedVersion:number;score:number;feedback:string;reason:string}):Promise<OfficialCorrectionTarget>;
}
export function assessmentAttemptHref(t:AssessmentAttemptTarget,suffix=''):string { return `/student/classes/${encodeURIComponent(t.classId)}/assessments/${encodeURIComponent(t.assessmentId)}/attempts/${encodeURIComponent(t.attemptId)}${suffix}`; }
export function publicAssessmentQuestion(q:AssessmentQuestion):PublicAssessmentQuestion {
 const base={id:q.id,type:q.type,prompt:q.prompt,points:q.points};
 if(q.type==='single_choice'||q.type==='multiple_choice')return {...base,type:q.type,options:q.options.map(o=>({id:o.id,text:o.text}))};
 if(q.type==='true_false')return {...base,type:q.type,statements:q.statements.map(s=>({id:s.id,text:s.text}))};
 return {...base,type:'short_answer'};
}
export function hasAssessmentAnswer(q:PublicAssessmentQuestion,a:AssessmentAnswer|undefined):boolean {
 if(!a||a.questionId!==q.id)return false;
 if(q.type==='single_choice')return typeof a.value==='string'&&q.options.some(o=>o.id===a.value);
 if(q.type==='multiple_choice')return Array.isArray(a.value)&&a.value.length>0&&new Set(a.value).size===a.value.length&&a.value.every(v=>q.options.some(o=>o.id===v));
 if(q.type==='true_false')return typeof a.value==='object'&&!Array.isArray(a.value)&&q.statements.every(s=>typeof (a.value as Record<string,boolean>)[s.id]==='boolean');
 return typeof a.value==='string'&&a.value.trim().length>0;
}
