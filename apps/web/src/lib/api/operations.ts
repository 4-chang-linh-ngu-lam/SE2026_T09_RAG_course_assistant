// This allowlist contains only Core operations documented in the current API contract.
export const operations = {
  login: ['POST', '/auth/login'], refresh: ['POST', '/auth/refresh'], logout: ['POST', '/auth/logout'], logoutAll: ['POST', '/auth/logout-all'],
  activate: ['POST', '/auth/activate'], verifyEmail: ['POST', '/auth/verify-email'], forgot: ['POST', '/auth/password/forgot'], reset: ['POST', '/auth/password/reset'],
  me: ['GET', '/users/me'], updateProfile: ['PATCH', '/users/me'], dataRequests: ['GET', '/users/me/data-requests'], createDataRequest: ['POST', '/users/me/data-requests'],
  createStudent: ['POST', '/admin/students'], issueStudentCode: ['POST', '/admin/students/:userId/activation-codes'],
  classes: ['GET', '/classes'], classDetail: ['GET', '/classes/:classId'], classMembers: ['GET', '/classes/:classId/members'],
  posts: ['GET', '/classes/:classId/posts'], createPost: ['POST', '/classes/:classId/posts'], updatePost: ['PATCH', '/classes/:classId/posts/:postId'], deletePost: ['DELETE', '/classes/:classId/posts/:postId'],
  comments: ['GET', '/classes/:classId/posts/:postId/comments'], createComment: ['POST', '/classes/:classId/posts/:postId/comments'], updateComment: ['PATCH', '/classes/:classId/posts/:postId/comments/:commentId'], deleteComment: ['DELETE', '/classes/:classId/posts/:postId/comments/:commentId'],
  calendarEvents: ['GET', '/classes/:classId/calendar'], createCalendarEvent: ['POST', '/classes/:classId/calendar'], updateCalendarEvent: ['PATCH', '/classes/:classId/calendar/:eventId'], deleteCalendarEvent: ['DELETE', '/classes/:classId/calendar/:eventId'],
  notifications: ['GET', '/notifications'], markNotificationRead: ['PATCH', '/notifications/:notificationId/read'], markAllNotificationsRead: ['POST', '/notifications/read-all'],
  adminUsers: ['GET', '/admin/users'], adminCreateUser: ['POST', '/admin/users'], adminUpdateUser: ['PATCH', '/admin/users/:userId'], adminReissueInvitation: ['POST', '/admin/users/:userId/invitation/reissue'],
  adminSetUserStatus: ['PATCH', '/admin/users/:userId/status'], adminSetUserRoles: ['PUT', '/admin/users/:userId/roles'],
  adminAuditEvents: ['GET', '/admin/audit-events'], adminDataRequests: ['GET', '/admin/data-requests'],
  adminDataRequest: ['GET', '/admin/data-requests/:requestId'], adminResolveDataRequest: ['PATCH', '/admin/data-requests/:requestId'],
  adminStudentImportPreview: ['POST', '/admin/students/imports/preview'], adminStudentImportConfirm: ['POST', '/admin/students/imports/confirm'],
  adminStudentImportStatus: ['GET', '/admin/students/imports/:previewId'],
  adminCreateCourse: ['POST', '/admin/courses'], adminCreateHomeroom: ['POST', '/admin/homeroom-classes'],
  adminCatalog: ['GET', '/admin/catalog'], adminHomeroomRoster: ['GET', '/admin/homeroom-classes/:homeroomId/roster'],
  adminClassManagement: ['GET', '/admin/classes/:classId/management'],
  adminSetHomeroomRoster: ['PUT', '/admin/homeroom-classes/:homeroomId/roster'],
  adminTransferHomeroomStudent: ['POST', '/admin/homeroom-classes/:homeroomId/students/:studentId/transfer'],
  adminCreateClass: ['POST', '/admin/classes'], adminSetTeachingAssignments: ['PUT', '/admin/classes/:classId/teaching-assignments'],
  adminPreviewEnrollment: ['POST', '/admin/classes/:classId/enrollment/preview'], adminSetEnrollmentMode: ['PATCH', '/admin/classes/:classId/enrollment-mode'],
  adminSyncEnrollment: ['POST', '/admin/classes/:classId/enrollment/sync'], adminAddClassMember: ['POST', '/admin/classes/:classId/members'],
  adminSetManualRoster: ['PUT', '/admin/classes/:classId/members'],
  adminEndClassMember: ['DELETE', '/admin/classes/:classId/members/:studentId'],
  adminTransferClassMember: ['POST', '/admin/classes/:classId/members/:studentId/transfer'],
  adminArchiveClass: ['POST', '/admin/classes/:classId/archive'], adminRestoreClass: ['POST', '/admin/classes/:classId/restore'],
} as const;

export type OperationId = keyof typeof operations;
export const successStatus: Record<OperationId, number> = {
  login: 200, refresh: 200, logout: 204, logoutAll: 204, activate: 204, verifyEmail: 200, forgot: 200, reset: 204,
  me: 200, updateProfile: 200, dataRequests: 200, createDataRequest: 201, createStudent: 201, issueStudentCode: 200,
  classes: 200, classDetail: 200, classMembers: 200,
  posts: 200, createPost: 201, updatePost: 200, deletePost: 204,
  comments: 200, createComment: 201, updateComment: 200, deleteComment: 204,
  calendarEvents: 200, createCalendarEvent: 201, updateCalendarEvent: 200, deleteCalendarEvent: 204,
  notifications: 200, markNotificationRead: 200, markAllNotificationsRead: 204,
  adminCreateUser: 201, adminUpdateUser: 200, adminReissueInvitation: 200, adminSetUserStatus: 204, adminSetUserRoles: 200,
  adminUsers: 200,
  adminAuditEvents: 200, adminDataRequests: 200, adminDataRequest: 200, adminResolveDataRequest: 200,
  adminStudentImportPreview: 200, adminStudentImportConfirm: 200, adminStudentImportStatus: 200,
  adminCreateCourse: 201, adminCreateHomeroom: 201, adminSetHomeroomRoster: 200, adminTransferHomeroomStudent: 200,
  adminCatalog: 200, adminHomeroomRoster: 200, adminClassManagement: 200,
  adminCreateClass: 201, adminSetTeachingAssignments: 200, adminPreviewEnrollment: 200, adminSetEnrollmentMode: 200,
  adminSyncEnrollment: 200, adminAddClassMember: 201, adminEndClassMember: 204, adminTransferClassMember: 200,
  adminSetManualRoster: 200,
  adminArchiveClass: 200, adminRestoreClass: 200,
};

export const operationQueryParameters: Partial<Record<OperationId, readonly string[]>> = {
  dataRequests: ['cursor', 'limit'], classes: ['cursor', 'limit'], classMembers: ['cursor', 'limit'],
  posts: ['cursor', 'limit'], comments: ['cursor', 'limit'],
  calendarEvents: ['cursor', 'limit', 'from', 'to'], notifications: ['cursor', 'limit'],
  adminAuditEvents: ['cursor', 'limit', 'actor_id', 'action', 'since', 'until'],
  adminDataRequests: ['cursor', 'limit'], adminUsers: ['cursor', 'limit', 'user_id', 'account_type', 'role', 'status', 'search', 'username_missing'],
};

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type PathParams = string | Record<string, string> | undefined;

export function operationPath(id: OperationId, parameters?: PathParams) {
  const template = operations[id][1];
  const values = typeof parameters === 'string' ? { userId: parameters } : parameters ?? {};
  return template.replace(/:([A-Za-z][A-Za-z0-9]*)/g, (_match, name: string) => {
    const value = values[name];
    if (!value || !uuid.test(value)) throw new Error(`A valid UUID for ${name} is required`);
    return value;
  });
}

function matchTemplate(template: string, path: string): boolean {
  const names: string[] = [];
  let pattern = '^';
  let offset = 0;
  const parameter = /:([A-Za-z][A-Za-z0-9]*)/g;
  for (let match = parameter.exec(template); match; match = parameter.exec(template)) {
    pattern += template.slice(offset, match.index).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '([^/]+)';
    names.push(match[1]);
    offset = match.index + match[0].length;
  }
  pattern += template.slice(offset).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$';
  const values = path.match(new RegExp(pattern));
  return values !== null && names.every((_name, index) => uuid.test(values[index + 1]));
}

export function isImplementedOperation(method: string, path: string) {
  return findOperation(method, path) !== undefined;
}

export function findOperation(method: string, path: string): OperationId | undefined {
  return (Object.keys(operations) as OperationId[]).find(id => {
    const [verb, template] = operations[id];
    return method === verb && matchTemplate(template, path);
  });
}
