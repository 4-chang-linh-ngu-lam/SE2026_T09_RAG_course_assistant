import type { ClassSummary, User, Role } from './domain';
import {sameResourceId} from './api/operations';

// Presentation guards only. Core independently checks current scope on mutation.
export function socialAccess(user: Pick<User, 'roles' | 'status'>, summary: ClassSummary | undefined, classId: string) {
  const current = user.status === 'ACTIVE' && summary !== undefined && sameResourceId(summary.id,classId) && summary.status === 'ACTIVE';
  const assigned = current && user.roles.includes('LECTURER') && (summary.teachingRole === 'PRIMARY' || summary.teachingRole === 'ASSISTING' || summary.isAssignedTeacher===true);
  const enrolled = current && user.roles.includes('STUDENT') && summary.membershipStatus === 'ACTIVE';
  return { participate: Boolean(assigned || enrolled), moderate: Boolean(assigned) };
}

export function classroomTabsAllowed(role:Role,summary:ClassSummary|undefined){
  return socialAccess({roles:[role],status:'ACTIVE'},summary,summary?.id??'').participate;
}
