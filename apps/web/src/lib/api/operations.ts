// Only HTTP operations implemented in this repository's Identity contract.
// Adding a service endpoint requires an approved contract and decoder.
export const operations = {
  login: ['POST', '/auth/login'], refresh: ['POST', '/auth/refresh'], logout: ['POST', '/auth/logout'], logoutAll: ['POST', '/auth/logout-all'],
  activate: ['POST', '/auth/activate'], verifyEmail: ['POST', '/auth/verify-email'], forgot: ['POST', '/auth/password/forgot'], reset: ['POST', '/auth/password/reset'],
  me: ['GET', '/users/me'], updateProfile: ['PATCH', '/users/me'], dataRequests: ['GET', '/users/me/data-requests'], createDataRequest: ['POST', '/users/me/data-requests'],
  createStudent: ['POST', '/admin/students'], issueStudentCode: ['POST', '/admin/students/:userId/activation-codes'],
} as const;
export type OperationId = keyof typeof operations;
export const successStatus: Record<OperationId, number> = {
  login: 200, refresh: 200, logout: 204, logoutAll: 204, activate: 204, verifyEmail: 200, forgot: 200, reset: 204,
  me: 200, updateProfile: 200, dataRequests: 200, createDataRequest: 201, createStudent: 201, issueStudentCode: 200,
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function operationPath(id: OperationId, userId?: string) {
  const path = operations[id][1];
  if (!path.includes(':userId')) return path;
  if (!userId || !uuid.test(userId)) throw new Error('A valid user UUID is required');
  return path.replace(':userId', userId);
}
export function isImplementedOperation(method: string, path: string) {
  return Object.entries(operations).some(([id, [verb, template]]) => {
    if (method !== verb) return false;
    if (!template.includes(':userId')) return path === template;
    const match = path.match(/^\/admin\/students\/([^/]+)\/activation-codes$/);
    return !!match && uuid.test(match[1]) && operationPath(id as OperationId, match[1]) === path;
  });
}
