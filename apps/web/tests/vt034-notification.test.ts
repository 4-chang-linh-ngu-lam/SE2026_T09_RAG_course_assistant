import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveCore } from '../src/lib/data/live-core';
import { createLiveIdentitySession } from '../src/lib/data/live-identity';

test('VT-034 updated post notification has a Vietnamese label and feed target', async () => {
  const userId = '00000000-0000-4000-8000-000000000001';
  const classId = '00000000-0000-4000-8000-000000000002';
  const fetcher = (async (input: RequestInfo | URL) => {
    const path = new URL(String(input), 'https://web.example').pathname;
    if (path === '/api/v1/auth/login') return Response.json({ token_type: 'bearer', access_token: 'test-only', expires_in: 900 });
    if (path === '/api/v1/users/me') return Response.json({ id: userId, email: null, username: 'student.synthetic', school_id: classId, display_name: 'Học sinh', roles: ['STUDENT'], status: 'ACTIVE' });
    if (path === '/api/v1/classes') return Response.json({ items: [], next_cursor: null });
    if (path === '/api/v1/notifications') return Response.json({ items: [{ id: userId, type: 'SOCIAL_POST_UPDATED', payload_json: { class_id: classId }, read: false, created_at: '2026-11-14T00:00:00Z' }], unread_count: 1, next_cursor: null });
    throw new Error(`Unexpected request: ${path}`);
  }) as typeof fetch;
  const session = createLiveIdentitySession({ fetcher, onLost() {} });
  await session.identity.login({ username: 'student.synthetic', password: 'test-only' });
  const result = await createLiveCore(session).workspace.load('account.notifications', {});
  assert.equal(result.kind, 'ready');
  if (result.kind !== 'ready') throw new Error('Expected ready workspace');
  const item = result.notifications?.[0];
  assert.equal(item?.title, 'Bài viết đã cập nhật');
  assert.equal(item?.targetHref, `/student/classes/${classId}/feed`);
  assert.equal(item?.targetLabel, 'Mở bảng tin');
});
