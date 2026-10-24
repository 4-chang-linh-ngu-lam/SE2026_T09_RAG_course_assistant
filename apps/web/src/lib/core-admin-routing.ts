import type {User} from './domain';

export const coreAdminRoutes=['a.staffInvite','a.importNew','a.dataRequests'] as const;
export type CoreAdminRoute=typeof coreAdminRoutes[number];
export function usesCoreAdminUi(source:'live'|'mock',routeId:string):routeId is CoreAdminRoute{
  return source==='live'&&(coreAdminRoutes as readonly string[]).includes(routeId);
}
// Presentation/session binding only; every request still needs backend Admin
// authorization and current DB school/role/status checks.
export function coreAdminScope(user:User|null,routeId:CoreAdminRoute):string|null{
  if(!user||user.status!=='ACTIVE'||!user.roles.includes('ADMIN')||!user.school_id)return null;
  return JSON.stringify([routeId,user.id,user.school_id,[...user.roles].sort()]);
}
