import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeFeedComments } from '../src/lib/feed-comments';
import type { FeedComment } from '../src/lib/domain';

function comment(id: string, createdAt: string): FeedComment {
  return { id, postId: 'post', authorId: 'author', authorName: 'Author', content: id, createdAt };
}

test('comment pagination deduplicates overlapping IDs and keeps chronological order', () => {
  const merged = mergeFeedComments(
    [comment('one', '2026-10-29T10:00:00Z'), comment('two', '2026-10-29T10:02:00Z')],
    [comment('two', '2026-10-29T10:02:00Z'), comment('three', '2026-10-29T10:03:00Z')],
  );
  assert.deepEqual(merged.map(item => item.id), ['one', 'two', 'three']);
});
