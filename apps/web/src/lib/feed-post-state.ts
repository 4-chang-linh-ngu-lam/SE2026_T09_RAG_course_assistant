import type { FeedPost } from './domain';

export function updateFeedPosts(
  current: FeedPost[] | null,
  initial: FeedPost[] | undefined,
  update: (posts: FeedPost[]) => FeedPost[],
): FeedPost[] {
  return update(current ?? initial ?? []);
}
