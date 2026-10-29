import type { FeedComment } from './domain';

export function mergeFeedComments(existing: readonly FeedComment[], incoming: readonly FeedComment[]): FeedComment[] {
  const byId = new Map<string, FeedComment>();
  for (const comment of [...existing, ...incoming]) byId.set(comment.id, comment);
  return [...byId.values()].sort((left, right) => {
    const time = Date.parse(left.createdAt) - Date.parse(right.createdAt);
    return Number.isFinite(time) && time !== 0 ? time : left.id.localeCompare(right.id);
  });
}
