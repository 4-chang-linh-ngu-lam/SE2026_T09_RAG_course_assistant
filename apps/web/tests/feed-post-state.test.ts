import test from 'node:test';
import assert from 'node:assert/strict';
import { canParticipateInFeed, updateFeedPosts } from '../src/lib/feed-post-state';
import type { ClassSummary, FeedPost } from '../src/lib/domain';

test('feed writing requires current matching active class membership or teaching assignment', () => {
  const summary: ClassSummary = { id: 'class', code: 'M10', name: 'Toán 10', status: 'ACTIVE', metadata: '' };
  assert.equal(canParticipateInFeed({ ...summary, membershipStatus: 'ACTIVE' }, 'STUDENT', 'class'), true);
  for (const teachingRole of ['PRIMARY', 'ASSISTING'] as const) {
    assert.equal(canParticipateInFeed({ ...summary, teachingRole }, 'LECTURER', 'class'), true);
    assert.equal(canParticipateInFeed({ ...summary, teachingRole, status: 'ARCHIVED' }, 'LECTURER', 'class'), false);
  }
  assert.equal(canParticipateInFeed({ ...summary, membershipStatus: 'ENDED' }, 'STUDENT', 'class'), false);
  assert.equal(canParticipateInFeed({ ...summary, membershipStatus: 'ACTIVE', status: 'ARCHIVED' }, 'STUDENT', 'class'), false);
  assert.equal(canParticipateInFeed(summary, 'STUDENT', 'class'), false);
  assert.equal(canParticipateInFeed(summary, 'LECTURER', 'class'), false);
  assert.equal(canParticipateInFeed({ ...summary, teachingRole: 'PRIMARY' }, 'ADMIN', 'class'), false);
  assert.equal(canParticipateInFeed(undefined, 'STUDENT', 'class'), false);
  assert.equal(canParticipateInFeed({ ...summary, membershipStatus: 'ACTIVE' }, 'STUDENT', 'other-class'), false);
});

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
