import type { ClassSummary, FeedPost, Role } from './domain';

/** UI reflects current class access; the server still authorizes every mutation. */
export function canParticipateInFeed(summary: ClassSummary | undefined, role: Role, classId: string | undefined): boolean {
  if (!summary || summary.id !== classId || summary.status !== 'ACTIVE') return false;
  if (role === 'STUDENT') return summary.membershipStatus === 'ACTIVE';
  if (role === 'LECTURER') return summary.teachingRole === 'PRIMARY' || summary.teachingRole === 'ASSISTING';
  return false;
}

export function updateFeedPosts(
  current: FeedPost[] | null,
  initial: FeedPost[] | undefined,
  update: (posts: FeedPost[]) => FeedPost[],
): FeedPost[] {
  return update(current ?? initial ?? []);
}
