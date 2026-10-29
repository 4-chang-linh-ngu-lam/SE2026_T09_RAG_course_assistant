import test from 'node:test';
import assert from 'node:assert/strict';
import { updateFeedPosts } from '../src/lib/feed-post-state';
import type { FeedPost } from '../src/lib/domain';

function post(id: string, content = id): FeedPost {
  return { id, classId: 'class', authorId: 'author', authorName: 'Author', content, createdAt: '2026-10-29T10:00:00Z', comments: [] };
}

test('feed page and mutation state updates preserve each other in either completion order', () => {
  const initial = [post('newest'), post('oldest')];
  const olderPage = [post('older-page')];
  const updateNewest = (posts: FeedPost[]) => posts.map(item => item.id === 'newest' ? { ...item, content: 'comment added' } : item);
  const appendOlderPage = (posts: FeedPost[]) => [...posts, ...olderPage];

  let current: FeedPost[] | null = null;
  current = updateFeedPosts(current, initial, appendOlderPage);
  current = updateFeedPosts(current, initial, updateNewest);
  assert.deepEqual(current.map(item => item.id), ['newest', 'oldest', 'older-page']);
  assert.equal(current[0].content, 'comment added');

  current = null;
  current = updateFeedPosts(current, initial, updateNewest);
  current = updateFeedPosts(current, initial, appendOlderPage);
  assert.deepEqual(current.map(item => item.id), ['newest', 'oldest', 'older-page']);
  assert.equal(current[0].content, 'comment added');
});
