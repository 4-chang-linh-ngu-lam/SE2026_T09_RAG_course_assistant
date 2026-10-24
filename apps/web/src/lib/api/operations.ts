// Existing Core operations approved 2026-10-22. Health/internal/register stay closed.
// Adding a service endpoint requires an approved contract and decoder.
export const operations = {
  login: ['POST', '/auth/login'], refresh: ['POST', '/auth/refresh'], logout: ['POST', '/auth/logout'], logoutAll: ['POST', '/auth/logout-all'],
  activate: ['POST', '/auth/activate'], verifyEmail: ['POST', '/auth/verify-email'], forgot: ['POST', '/auth/password/forgot'], reset: ['POST', '/auth/password/reset'],
  me: ['GET', '/users/me'], updateProfile: ['PATCH', '/users/me'], dataRequests: ['GET', '/users/me/data-requests'], createDataRequest: ['POST', '/users/me/data-requests'],
  createStudent: ['POST', '/admin/students'], issueStudentCode: ['POST', '/admin/students/:userId/activation-codes'],
  notifications: ['GET', '/notifications'], markNotificationRead: ['PATCH', '/notifications/:notificationId/read'], markAllNotificationsRead: ['POST', '/notifications/read-all'],
  classes: ['GET','/classes'], classDetail: ['GET','/classes/:classId'], classMembers: ['GET','/classes/:classId/members'],
  courses:['GET','/admin/courses'],academicYears:['GET','/admin/academic-years'],semesters:['GET','/admin/academic-years/:yearId/semesters'],
  homerooms:['GET','/admin/homeroom-classes'],roster:['GET','/admin/homeroom-classes/:homeroomId/roster'],teachingAssignments:['GET','/admin/classes/:classId/teaching-assignments'],
  adminUsers:['GET','/admin/users'],adminUser:['GET','/admin/users/:userId'],
  createCourse: ['POST','/admin/courses'], createHomeroom: ['POST','/admin/homeroom-classes'],
  setRoster: ['PUT','/admin/homeroom-classes/:homeroomId/roster'], transferHomeroom: ['POST','/admin/homeroom-classes/:homeroomId/students/:studentId/transfer'],
  createClass: ['POST','/admin/classes'], setTeachers: ['PUT','/admin/classes/:classId/teaching-assignments'],
  previewEnrollment: ['POST','/admin/classes/:classId/enrollment/preview'], syncEnrollment: ['POST','/admin/classes/:classId/enrollment/sync'],
  setEnrollmentMode: ['PATCH','/admin/classes/:classId/enrollment-mode'], addMember: ['POST','/admin/classes/:classId/members'],
  endMember: ['DELETE','/admin/classes/:classId/members/:studentId'], transferMember: ['POST','/admin/classes/:classId/members/:studentId/transfer'],
  archiveClass: ['POST','/admin/classes/:classId/archive'], restoreClass: ['POST','/admin/classes/:classId/restore'],
  posts: ['GET','/classes/:classId/posts'], createPost: ['POST','/classes/:classId/posts'],
  updatePost: ['PATCH','/classes/:classId/posts/:postId'], deletePost: ['DELETE','/classes/:classId/posts/:postId'],
  comments: ['GET','/classes/:classId/posts/:postId/comments'], createComment: ['POST','/classes/:classId/posts/:postId/comments'],
  updateComment: ['PATCH','/classes/:classId/posts/:postId/comments/:commentId'], deleteComment: ['DELETE','/classes/:classId/posts/:postId/comments/:commentId'],
  calendar: ['GET','/classes/:classId/calendar'], createEvent: ['POST','/classes/:classId/calendar'],
  updateEvent: ['PATCH','/classes/:classId/calendar/:eventId'], deleteEvent: ['DELETE','/classes/:classId/calendar/:eventId'],
  createStaff: ['POST','/admin/users'], setUserStatus: ['PATCH','/admin/users/:userId/status'], setUserRoles: ['PUT','/admin/users/:userId/roles'],
  auditEvents: ['GET','/admin/audit-events'], adminDataRequests: ['GET','/admin/data-requests'], adminDataRequest: ['GET','/admin/data-requests/:requestId'],
  resolveDataRequest: ['PATCH','/admin/data-requests/:requestId'], previewImport: ['POST','/admin/students/imports/preview'], confirmImport: ['POST','/admin/students/imports/confirm'],
} as const;
export type OperationId = keyof typeof operations;
export const successStatus: Record<OperationId, number> = {
  login: 200, refresh: 200, logout: 204, logoutAll: 204, activate: 204, verifyEmail: 200, forgot: 200, reset: 204,
  me: 200, updateProfile: 200, dataRequests: 200, createDataRequest: 201, createStudent: 201, issueStudentCode: 200,
  notifications: 200, markNotificationRead: 200, markAllNotificationsRead: 204,
  classes:200,classDetail:200,classMembers:200,createCourse:201,createHomeroom:201,setRoster:200,transferHomeroom:200,
  courses:200,academicYears:200,semesters:200,homerooms:200,roster:200,teachingAssignments:200,adminUsers:200,adminUser:200,
  createClass:201,setTeachers:200,previewEnrollment:200,syncEnrollment:200,setEnrollmentMode:200,addMember:201,endMember:204,
  transferMember:200,archiveClass:200,restoreClass:200,posts:200,createPost:201,updatePost:200,deletePost:204,
  comments:200,createComment:201,updateComment:200,deleteComment:204,calendar:200,createEvent:201,updateEvent:200,deleteEvent:204,
  createStaff:201,setUserStatus:204,setUserRoles:200,auditEvents:200,adminDataRequests:200,adminDataRequest:200,resolveDataRequest:200,previewImport:200,confirmImport:200,
};
export const resourceUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function canonicalResourceId(value:string):string{return resourceUuid.test(value)?value.toLowerCase():value;}
export function sameResourceId(actual:string|undefined,expected:string|undefined):boolean{return actual!==undefined&&expected!==undefined&&canonicalResourceId(actual)===canonicalResourceId(expected);}
export const adminReasons = ['ADMIN_INTERVENTION','POLICY_VIOLATION','USER_REQUEST'] as const;
export type AdminReason = typeof adminReasons[number];
export const reasonOperations = new Set<OperationId>(['setRoster','transferHomeroom','setTeachers','syncEnrollment','setEnrollmentMode','addMember','endMember','transferMember','archiveClass','restoreClass','createStaff','setUserStatus','setUserRoles','resolveDataRequest','confirmImport']);
const paginated:OperationId[]=['dataRequests','notifications','classes','posts','comments','calendar','auditEvents','adminDataRequests','courses','academicYears','semesters','homerooms','adminUsers'];
export function queryKeys(id:OperationId):readonly string[]{
  const page=paginated.includes(id)?['cursor','limit']:[];
  return id==='calendar'?[...page,'from','to']:id==='auditEvents'?[...page,'actor_id','action','since','until']:page;
}
export type ResourceParams=Partial<Record<'userId'|'notificationId'|'classId'|'homeroomId'|'studentId'|'postId'|'commentId'|'eventId'|'requestId'|'yearId',string>>;
export function operationPath(id: OperationId, resourceId?: string|ResourceParams) {
  const path = operations[id][1];
  if (!path.includes(':')) return path;
  const keys=[...path.matchAll(/:(\w+)/g)].map(match=>match[1]);
  return path.replace(/:(\w+)/g,(_match,key:string)=>{
    const value=typeof resourceId==='string'&&keys.length===1?resourceId:typeof resourceId==='object'?resourceId[key as keyof ResourceParams]:undefined;
    if(!value||!resourceUuid.test(value))throw new Error('A valid resource UUID is required');
    return value;
  });
}
export function matchedOperation(method:string,path:string):OperationId|undefined {
  return (Object.keys(operations) as OperationId[]).find(id=>{
    const [verb,template]=operations[id];
    if(method!==verb)return false;
    const actual=path.split('/'),parts=template.split('/');
    return parts.length===actual.length&&parts.every((part,index)=>part.startsWith(':')?resourceUuid.test(actual[index]):part===actual[index]);
  });
}
export function isImplementedOperation(method:string,path:string){return matchedOperation(method,path)!==undefined;}
