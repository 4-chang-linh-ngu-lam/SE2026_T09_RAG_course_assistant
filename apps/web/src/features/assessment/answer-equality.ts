import type {AssessmentAnswer,AssessmentAnswers} from '@/lib/assessment';
function canonical(value:unknown):unknown {
 if(Array.isArray(value))return [...value].sort();
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,v])=>[key,canonical(v)]));
 return value;
}
export const sameAssessmentAnswer=(a?:AssessmentAnswer,b?:AssessmentAnswer):boolean=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
export const sameAssessmentAnswers=(a:AssessmentAnswers|null,b:AssessmentAnswers|null):boolean=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
