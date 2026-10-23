import type {DataRequest,Page,Role} from '../domain';
import type {HttpOptions} from './http';
import type {AdminReason} from './operations';
import {ApiError} from './errors';
import {resourceUuid} from './operations';

export type CoreClass={id:string;school_id:string;academic_year_id:string;semester_id:string;course_id:string;homeroom_class_id:string|null;name:string;grade_level:number;enrollment_mode:'AUTO'|'MANUAL';status:'ACTIVE'|'ARCHIVED';version:number};
export type CoreMember={id:string;class_id:string;student_id:string;source:'AUTO'|'MANUAL';status:'ACTIVE'|'ENDED';joined_at:string;ended_at:string|null};
export type CorePost={id:string;class_id:string;author:{id:string;display_name:string|null};body:string;created_at:string;updated_at:string};
export type CoreComment=Omit<CorePost,'class_id'>&{post_id:string};
export type CoreEvent={id:string;class_id:string;title:string;description:string|null;starts_at:string;ends_at:string;origin:'CORE'|'LEARNING';external_ref:string|null};
export type CoreUser={id:string;email:string|null;username:string|null;school_id:string|null;display_name:string|null;status:'ACTIVE'|'PENDING_VERIFICATION'|'LOCKED'};
export type CoreAdminUser=CoreUser&{roles:Role[]};
export type CoreAcademicYear={id:string;school_id:string;label:string};
export type CoreSemester={id:string;academic_year_id:string;name:string};
export type CoreCourse={id:string;school_id:string;code:string;name:string};
export type CoreHomeroom={id:string;school_id:string;academic_year_id:string;name:string;grade_level:number;roster_version:number};
export type CoreRoster={homeroom_class_id:string;student_ids:string[];roster_version:number};
export type CoreTeacher={id:string;class_id:string;lecturer_id:string;role:'PRIMARY'|'ASSISTING';assigned_at:string;ended_at:string|null};
export type CorePreview={class_id:string;target_mode:'AUTO'|'MANUAL';class_version:number;roster_version:number;add_student_ids:string[];end_student_ids:string[]};
export type CoreAudit={id:string;actor_id:string|null;action:string;target_type:string;target_id:string;correlation_id:string;metadata_json:Record<string,unknown>;occurred_at:string};
export type CoreImportPreview={valid:boolean;preview_id:string|null;expires_at:string|null;items:{row:number;action:'CREATE'|'EXISTING'|'ASSIGN_USERNAME';username:string;user_id:string|null}[];errors:{row:number;code:string}[]};
export type CoreImportReceipt={preview_id:string;status:'COMPLETED';replayed:boolean;items:{row:number;outcome:'CREATED'|'EXISTING'|'USERNAME_ASSIGNED';student:CoreUser;code:string|null;expires_at:string|null}[]};
const invalid=():never=>{throw new ApiError('CONTRACT_MISMATCH','Dữ liệu Core trả về chưa hợp lệ. Hãy tải lại.');};
export const object=(v:unknown):Record<string,unknown>=>typeof v==='object'&&v!==null&&!Array.isArray(v)?v as Record<string,unknown>:invalid();
const text=(v:unknown):string=>typeof v==='string'?v:invalid();
const id=(v:unknown):string=>typeof v==='string'&&resourceUuid.test(v)?v:invalid();
const nullable=<T>(v:unknown,decode:(v:unknown)=>T):T|null=>v===null?null:decode(v);
const choice=<T extends string>(v:unknown,values:readonly T[]):T=>typeof v==='string'&&values.includes(v as T)?v as T:invalid();
const integer=(v:unknown,min=1):number=>Number.isSafeInteger(v)&&Number(v)>=min?Number(v):invalid();
const bool=(v:unknown):boolean=>typeof v==='boolean'?v:invalid();
const stamp=(v:unknown):string=>typeof v==='string'&&/(Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v))?v:invalid();
const list=<T>(v:unknown,decode:(v:unknown)=>T):T[]=>Array.isArray(v)?v.map(decode):invalid();
const ids=(v:unknown):string[]=>{const result=list(v,id);if(new Set(result).size!==result.length)invalid();return result;};
export function decodeCorePage<T>(v:unknown,decode:(v:unknown)=>T):Page<T>{
  const x=object(v),cursor=nullable(x.next_cursor,text);
  if(cursor!==null&&!/^[A-Za-z0-9_-]{22}$/.test(cursor))invalid();
  return {items:list(x.items,decode),next_cursor:cursor};
}
export function decodeClass(v:unknown):CoreClass{const x=object(v),grade=integer(x.grade_level,6);if(grade>12)invalid();return {id:id(x.id),school_id:id(x.school_id),academic_year_id:id(x.academic_year_id),semester_id:id(x.semester_id),course_id:id(x.course_id),homeroom_class_id:nullable(x.homeroom_class_id,id),name:text(x.name),grade_level:grade,enrollment_mode:choice(x.enrollment_mode,['AUTO','MANUAL']),status:choice(x.status,['ACTIVE','ARCHIVED']),version:integer(x.version)};}
export function decodeMember(v:unknown):CoreMember{const x=object(v);return {id:id(x.id),class_id:id(x.class_id),student_id:id(x.student_id),source:choice(x.source,['AUTO','MANUAL']),status:choice(x.status,['ACTIVE','ENDED']),joined_at:stamp(x.joined_at),ended_at:nullable(x.ended_at,stamp)};}
const author=(v:unknown)=>{const x=object(v);return {id:id(x.id),display_name:nullable(x.display_name,text)};};
export function decodePost(v:unknown):CorePost{const x=object(v);return {id:id(x.id),class_id:id(x.class_id),author:author(x.author),body:text(x.body),created_at:stamp(x.created_at),updated_at:stamp(x.updated_at)};}
export function decodeComment(v:unknown):CoreComment{const x=object(v);return {id:id(x.id),post_id:id(x.post_id),author:author(x.author),body:text(x.body),created_at:stamp(x.created_at),updated_at:stamp(x.updated_at)};}
export function decodeEvent(v:unknown):CoreEvent{const x=object(v),start=stamp(x.starts_at),end=stamp(x.ends_at);if(Date.parse(start)>=Date.parse(end))invalid();return {id:id(x.id),class_id:id(x.class_id),title:text(x.title),description:nullable(x.description,text),starts_at:start,ends_at:end,origin:choice(x.origin,['CORE','LEARNING']),external_ref:nullable(x.external_ref,text)};}
function decodeUser(v:unknown):CoreUser{const x=object(v);return {id:id(x.id),email:nullable(x.email,text),username:nullable(x.username,text),school_id:nullable(x.school_id,id),display_name:nullable(x.display_name,text),status:choice(x.status,['ACTIVE','PENDING_VERIFICATION','LOCKED'])};}
export function decodeAdminUser(v:unknown):CoreAdminUser{const x=object(v),roles=list(x.roles,v=>choice(v,['ADMIN','LECTURER','STUDENT'] as const));if(new Set(roles).size!==roles.length)invalid();return {...decodeUser(x),roles};}
function decodeAcademicYear(v:unknown):CoreAcademicYear{const x=object(v);return {id:id(x.id),school_id:id(x.school_id),label:text(x.label)};}
function decodeSemester(v:unknown):CoreSemester{const x=object(v);return {id:id(x.id),academic_year_id:id(x.academic_year_id),name:text(x.name)};}
function decodeCourse(v:unknown):CoreCourse{const x=object(v);return {id:id(x.id),school_id:id(x.school_id),code:text(x.code),name:text(x.name)};}
function decodeHomeroom(v:unknown):CoreHomeroom{const x=object(v),grade=integer(x.grade_level,6);if(grade>12)invalid();return {id:id(x.id),school_id:id(x.school_id),academic_year_id:id(x.academic_year_id),name:text(x.name),grade_level:grade,roster_version:integer(x.roster_version)};}
function decodeRoster(v:unknown):CoreRoster{const x=object(v);return {homeroom_class_id:id(x.homeroom_class_id),student_ids:ids(x.student_ids),roster_version:integer(x.roster_version)};}
function decodeTeacher(v:unknown):CoreTeacher{const x=object(v);return {id:id(x.id),class_id:id(x.class_id),lecturer_id:id(x.lecturer_id),role:choice(x.role,['PRIMARY','ASSISTING']),assigned_at:stamp(x.assigned_at),ended_at:nullable(x.ended_at,stamp)};}
function decodePreview(v:unknown):CorePreview{const x=object(v);return {class_id:id(x.class_id),target_mode:choice(x.target_mode,['AUTO','MANUAL']),class_version:integer(x.class_version),roster_version:integer(x.roster_version),add_student_ids:ids(x.add_student_ids),end_student_ids:ids(x.end_student_ids)};}
function decodeAudit(v:unknown):CoreAudit{const x=object(v);return {id:id(x.id),actor_id:nullable(x.actor_id,id),action:text(x.action),target_type:text(x.target_type),target_id:id(x.target_id),correlation_id:id(x.correlation_id),metadata_json:object(x.metadata_json),occurred_at:stamp(x.occurred_at)};}
function decodeDataRequest(v:unknown):DataRequest{const x=object(v);return {id:id(x.id),user_id:id(x.user_id),type:choice(x.type,['ACCESS','EXPORT','CORRECTION','DELETE']),reason:nullable(x.reason,text),status:choice(x.status,['PENDING','IN_REVIEW','COMPLETED','REJECTED']),resolution_note:nullable(x.resolution_note,text),created_at:stamp(x.created_at),updated_at:stamp(x.updated_at)};}
function decodeImportPreview(v:unknown):CoreImportPreview{
  const x=object(v),valid=bool(x.valid),preview_id=nullable(x.preview_id,id),expires_at=nullable(x.expires_at,stamp);
  const items=list(x.items,v=>{const r=object(v);return {row:integer(r.row),action:choice(r.action,['CREATE','EXISTING','ASSIGN_USERNAME'] as const),username:text(r.username),user_id:nullable(r.user_id,id)};});
  const errors=list(x.errors,v=>{const r=object(v);return {row:integer(r.row,0),code:text(r.code)};});
  if(valid&&(!preview_id||!expires_at||errors.length))invalid();
  return {valid,preview_id,expires_at,items,errors};
}
function decodeImportReceipt(v:unknown):CoreImportReceipt{
  const x=object(v),replayed=bool(x.replayed);
  const items=list(x.items,v=>{const r=object(v),code=nullable(r.code,text),expires=nullable(r.expires_at,stamp);if(replayed&&code!==null)invalid();return {row:integer(r.row),outcome:choice(r.outcome,['CREATED','EXISTING','USERNAME_ASSIGNED'] as const),student:decodeUser(r.student),code,expires_at:expires};});
  return {preview_id:id(x.preview_id),status:choice(x.status,['COMPLETED']),replayed,items};
}
const empty=(v:unknown):void=>{if(v!==undefined)invalid();};
export const coreDecoders={
  classes:(v:unknown)=>decodeCorePage(v,decodeClass),classDetail:decodeClass,classMembers:(v:unknown)=>list(v,decodeMember),
  courses:(v:unknown)=>decodeCorePage(v,decodeCourse),academicYears:(v:unknown)=>decodeCorePage(v,decodeAcademicYear),semesters:(v:unknown)=>decodeCorePage(v,decodeSemester),
  homerooms:(v:unknown)=>decodeCorePage(v,decodeHomeroom),roster:decodeRoster,teachingAssignments:(v:unknown)=>list(v,decodeTeacher),
  adminUsers:(v:unknown)=>decodeCorePage(v,decodeAdminUser),adminUser:decodeAdminUser,
  createCourse:decodeCourse,createHomeroom:decodeHomeroom,setRoster:decodeRoster,transferHomeroom:decodeRoster,
  createClass:decodeClass,setTeachers:(v:unknown)=>list(v,decodeTeacher),previewEnrollment:decodePreview,syncEnrollment:decodeClass,setEnrollmentMode:decodeClass,
  addMember:decodeMember,endMember:empty,transferMember:decodeMember,archiveClass:decodeClass,restoreClass:decodeClass,
  posts:(v:unknown)=>decodeCorePage(v,decodePost),createPost:decodePost,updatePost:decodePost,deletePost:empty,
  comments:(v:unknown)=>decodeCorePage(v,decodeComment),createComment:decodeComment,updateComment:decodeComment,deleteComment:empty,
  calendar:(v:unknown)=>decodeCorePage(v,decodeEvent),createEvent:decodeEvent,updateEvent:decodeEvent,deleteEvent:empty,
  createStaff:decodeUser,setUserStatus:empty,setUserRoles:decodeUser,auditEvents:(v:unknown)=>decodeCorePage(v,decodeAudit),
  adminDataRequests:(v:unknown)=>decodeCorePage(v,decodeDataRequest),adminDataRequest:decodeDataRequest,resolveDataRequest:decodeDataRequest,
  previewImport:decodeImportPreview,confirmImport:decodeImportReceipt,
} as const;
export type CoreOperation=keyof typeof coreDecoders;
export type CoreResponse<K extends CoreOperation>=ReturnType<typeof coreDecoders[K]>;
type EventBody={title:string;description?:string|null;starts_at:string;ends_at:string};
type CoreBodies={
  createCourse:{code:string;name:string};createHomeroom:{name:string;academic_year:string;grade_level:number};
  setRoster:{student_ids:string[]};transferHomeroom:{destination_homeroom_id:string};
  createClass:{course_id:string;name:string;academic_year:string;semester:string;grade_level:number;homeroom_class_id?:string|null;enrollment_mode:'AUTO'|'MANUAL';primary_lecturer_id:string};
  setTeachers:{primary_lecturer_id:string;assisting_lecturer_ids?:string[]};setEnrollmentMode:{mode:'AUTO'|'MANUAL';expected_class_version?:number;expected_roster_version?:number};
  addMember:{student_id:string};transferMember:{destination_class_id:string};
  createPost:{body:string};updatePost:{body:string};createComment:{body:string};updateComment:{body:string};createEvent:EventBody;updateEvent:Partial<EventBody>;
  createStaff:{email:string;roles:('ADMIN'|'LECTURER')[]};setUserStatus:{status:'ACTIVE'|'LOCKED'};setUserRoles:{roles:Role[]};
  resolveDataRequest:{status:'IN_REVIEW'|'COMPLETED'|'REJECTED';resolution_note:'VERIFICATION_IN_PROGRESS'|'POLICY_PENDING'|'OUTSIDE_CORE_SCOPE'|'INSUFFICIENT_VERIFICATION'|'REQUEST_REJECTED'|'DUPLICATE_REQUEST';identity_verified?:boolean};
  previewImport:{format:'CSV'|'XLSX';content_base64:string;homeroom_class_id?:string|null};confirmImport:{preview_id:string};
};
type WithReason='setRoster'|'transferHomeroom'|'setTeachers'|'syncEnrollment'|'setEnrollmentMode'|'addMember'|'endMember'|'transferMember'|'archiveClass'|'restoreClass'|'createStaff'|'setUserStatus'|'setUserRoles'|'resolveDataRequest'|'confirmImport';
export type CoreOptions<K extends CoreOperation>=Omit<HttpOptions,'body'|'reason'>&(K extends keyof CoreBodies?{body:CoreBodies[K]}:{body?:never})&(K extends WithReason?{reason:AdminReason}:{reason?:never});
export interface CoreApiPort{request<K extends CoreOperation>(id:K,options:CoreOptions<K>):Promise<CoreResponse<K>>;}
