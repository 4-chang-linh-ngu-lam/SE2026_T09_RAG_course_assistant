import type {ResourceSelectionMode} from './activity-selection';
import type { ClassSummary, DataRequest, RouteParams } from './domain';
import type { LearningEvidence } from './learning-evidence';
// Frontend-only projections; these are not proposed Intelligence/Core wire DTOs.
export type IntelligenceFilter = { asOf?: string; from?: string; resourceIds?: string[]; resourceSelectionMode?: ResourceSelectionMode };
export type TopicEvidence = { topic: string; count: number; independentResourceCount: number; conclusion: 'INSUFFICIENT_DATA' };
export type TutorTopicAggregate = { topic: string; participantCount: number | null; suppressed: boolean; reason: string | null };
export type TutorAggregateView = { available: boolean; minimumParticipants: number; totalParticipants: number | null; topics: TutorTopicAggregate[]; message: string };
export type ActivityAggregate = { resourceId: string; kind: LearningEvidence['kind']; title: string; count: number; distinctStudents: number; meanScore: number | null; maximum: number; distribution: {label:string;count:number}[] };
export type ActivityOption = Pick<ActivityAggregate, 'resourceId' | 'kind' | 'title'>;
export type DataClassification = { category: string; action: 'RETAIN' | 'CORRECT' | 'EXPORT' | 'ANONYMIZE' | 'DELETE'; reason: string };
export type AdminDataRequest = DataRequest & { requesterName: string; processingStatus:'NOT_STARTED'|'PROCESSING'|'READY'|'BLOCKED'; artifact?:{name:string;type:string;size:number;preparedAt:string}; identityVerified: boolean; revision: number; classifications: DataClassification[] };
export type DataRequestUpdate = { id:string;expectedRevision:number;status:'IN_REVIEW'|'COMPLETED'|'REJECTED';identityVerified:boolean;resolution:string;classifications:DataClassification[] };
export type DataRequestProcess = {id:string;expectedRevision:number;verificationNote:string;classifications:DataClassification[]};
export type IntelligenceAuditRecord = { id:string;actorId:string;actorName:string;action:string;resourceType:string;resourceId:string;classId?:string;reason:string;at:string };
export type ReportScope = {classIds:string[];from:string;asOf:string;resourceIds:string[];resourceSelectionMode?:ResourceSelectionMode;includePractice:boolean};
export type ReportClassSummary = {classId:string;name:string;rosterCount:number;officialResultCount:number;practiceAttemptCount:number;activities:ActivityAggregate[]};
export type ReportPreview = {id:string;scope:ReportScope;classes:ReportClassSummary[];createdAt:string;notice:string};
export type ExportJob = {id:string;ownerId:string;title:string;format:'PDF'|'XLSX';status:'QUEUED'|'PROCESSING'|'READY'|'FAILED';scope:ReportScope;classNames:string[];createdAt:string;completedAt:string|null;error:string|null;fileName:string|null;size:number|null};
export type IntelligencePage =
 | {kind:'student';classSummary:ClassSummary;studentId:string;studentName:string;asOf:string;from:string;limitedHistory:boolean;evidence:LearningEvidence[];topics:TopicEvidence[];availableActivities:ActivityOption[];selectedResourceIds:string[];resourceSelectionMode:ResourceSelectionMode}
 | {kind:'class';classSummary:ClassSummary;asOf:string;from:string;rosterCount:number;activities:ActivityAggregate[];availableActivities:ActivityOption[];selectedResourceIds:string[];resourceSelectionMode:ResourceSelectionMode;topics:TopicEvidence[];students:{id:string;name:string;officialResults:number;practiceAttempts:number}[];tutor:TutorAggregateView}
 | {kind:'requests';items:AdminDataRequest[];unavailableReason?:string}
 | {kind:'audit';items:IntelligenceAuditRecord[];unavailableReason?:string}
 | {kind:'reports';classes:ClassSummary[];asOf:string;from:string;unavailableReason?:string}
 | {kind:'exports';jobs:ExportJob[]};
export interface IntelligencePort {
 load(routeId:string,params:RouteParams,filter?:IntelligenceFilter,signal?:AbortSignal):Promise<IntelligencePage>;
 updateRequest(input:DataRequestUpdate):Promise<AdminDataRequest>;
 processRequest(input:DataRequestProcess):Promise<AdminDataRequest>;
 downloadRequest(requestId:string):Promise<{name:string;type:string;bytes:Uint8Array}>;
 previewReport(scope:ReportScope):Promise<ReportPreview>;
 createExport(input:{previewId:string;format:'PDF'|'XLSX';operationId:string}):Promise<ExportJob>;
 reconcileExport(operationId:string):Promise<ExportJob|null>;
 processExport(jobId:string):Promise<ExportJob>;
 downloadExport(jobId:string):Promise<{name:string;type:string;bytes:Uint8Array}>;
}
export interface IntelligenceDependencies {
 schoolId:string;
 classes():ClassSummary[];
 studentName?(studentId:string):string;
 listRequests?():Promise<AdminDataRequest[]>;
 updateRequest?(input:DataRequestUpdate):Promise<AdminDataRequest>;
 processRequest?(input:DataRequestProcess):Promise<AdminDataRequest>;
 downloadRequest?(requestId:string):Promise<{name:string;type:string;bytes:Uint8Array}>;
 readAudit?():Promise<IntelligenceAuditRecord[]>;
 // Aggregate-only inputs are never returned to feature code or exports as participant IDs.
 readTutorAggregates?(classId:string,asOf:string):{privacyReviewed:boolean;topics:{topic:string;participantIds:string[]}[]};
}
