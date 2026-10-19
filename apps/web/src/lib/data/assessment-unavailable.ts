import type { AssessmentPort } from '../assessment';
import { ApiError } from '../api/errors';
export function createUnavailableAssessmentPort():AssessmentPort {
 const unavailable=async():Promise<never>=>{throw new ApiError('CAPABILITY_UNAVAILABLE','Chức năng kiểm tra chưa sẵn sàng. Vui lòng thử lại sau.',503);};
 return {readOwnHistory:unavailable,load:async()=>({kind:'unavailable',message:'Chức năng kiểm tra chưa sẵn sàng. Vui lòng thử lại sau.'}),listCalendarEvents:unavailable,listTeacherActivities:unavailable,createDraft:unavailable,saveDraft:unavailable,reviewQuestion:unavailable,propose:unavailable,decide:unavailable,newVersion:unavailable,generateQuestions:unavailable,start:unavailable,saveAnswers:unavailable,submit:unavailable,reconcileSubmission:unavailable,appeal:unavailable,proposeGrade:unavailable,approveGrade:unavailable,listSubmittedAttempts:unavailable,listGrading:unavailable,getCorrectionTarget:unavailable,applyGradeCorrection:unavailable};
}
