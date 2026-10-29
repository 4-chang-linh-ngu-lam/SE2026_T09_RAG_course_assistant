import test from 'node:test';
import assert from 'node:assert/strict';
import { createNotificationReadController } from '../src/lib/notification-read-controller';
import type { NotificationSnapshotRequest } from '../src/lib/notification-read-controller';
import type { NotificationItem } from '../src/lib/domain';
import { ApiError } from '../src/lib/api/errors';

function deferred() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function item(id: string, isRead = false, userId = 'actor-a'): NotificationItem {
  return { id, userId, isRead, title: id, content: 'Nội dung dành cho tài khoản hiện tại', category: 'SYSTEM', createdAt: '2026-10-19T00:00:00Z' };
}
function harness() {
  const calls: string[] = [];
  const requests: NotificationSnapshotRequest[] = [];
  let gate = deferred();
  const controller = createNotificationReadController({ actorId: 'actor-a',
    markOne: async id => { calls.push(id); await gate.promise; },
    markAll: async () => { calls.push('all'); await gate.promise; },
    reload: request => { requests.push(request); },
  });
  controller.receiveSnapshot([item('one'), item('two')]);
  return { controller, calls, requests, gate: () => gate, next: () => { gate = deferred(); return gate; } };
}

test('pending mutation remains unread; only confirmed ACK derives read state and reloads', async () => {
  const h = harness();
  const pending = h.controller.markOne('one');
  assert.equal(h.controller.getState().busy, true);
  assert.equal(h.controller.getState().unreadCount, 2);
  assert.equal(h.requests.length, 0);
  h.gate().resolve();
  assert.equal(await pending, 'confirmed');
  assert.equal(h.controller.getState().busy, false);
  assert.equal(h.controller.getState().items.find(row => row.id === 'one')?.isRead, true);
  assert.equal(h.controller.getState().unreadCount, 1);
  assert.equal(h.requests[0].purpose, 'refresh');
});

test('rejection keeps unread and exposes a repeatable known failure without fabricated success', async () => {
  const h = harness();
  const pending = h.controller.markOne('one');
  h.gate().reject(new ApiError('DENIED', 'Quyền đã thay đổi.', 403));
  assert.equal(await pending, 'rejected');
  assert.equal(h.controller.getState().unreadCount, 2);
  assert.equal(h.controller.getState().issue?.message, 'Quyền đã thay đổi.');
  assert.equal(h.requests.length, 0);
  h.next();
  const retry = h.controller.retry();
  h.gate().resolve();
  assert.equal(await retry, 'confirmed');
  assert.deepEqual(h.calls, ['one', 'one']);
});

test('busy guard blocks duplicate single/all commands synchronously', async () => {
  const h = harness();
  const first = h.controller.markAll();
  assert.equal(await h.controller.markOne('one'), 'ignored');
  assert.equal(await h.controller.markAll(), 'ignored');
  assert.equal(await h.controller.retry(), 'ignored');
  assert.deepEqual(h.calls, ['all']);
  h.gate().resolve();
  assert.equal(await first, 'confirmed');
  assert.equal(h.controller.getState().unreadCount, 0);
});

test('server unread count is preserved when unread notifications are outside the visible page', async () => {
  const h = harness();
  h.controller.receiveSnapshot([item('read', true)], undefined, 3);
  assert.equal(h.controller.getState().items.length, 1);
  assert.equal(h.controller.getState().unreadCount, 3);
  const pending = h.controller.markAll();
  assert.deepEqual(h.calls, ['all']);
  h.gate().resolve();
  assert.equal(await pending, 'confirmed');
  assert.equal(h.controller.getState().unreadCount, 0);
});

test('marking one visible item subtracts it only once from the server total', async () => {
  const h = harness();
  h.controller.receiveSnapshot([item('one'), item('read', true)], undefined, 3);
  const pending = h.controller.markOne('one');
  h.gate().resolve();
  assert.equal(await pending, 'confirmed');
  assert.equal(h.controller.getState().unreadCount, 2);
  h.controller.rejectSnapshot(new Error('refresh unavailable'), h.requests[0]);
  assert.equal(h.controller.getState().unreadCount, 2);
});

test('unknown outcome blocks retry; only a matching explicit reconciliation snapshot clears it', async () => {
  const h = harness();
  const pending = h.controller.markOne('one');
  h.gate().reject(new ApiError('TIMEOUT', 'Kết nối bị gián đoạn.', 0, 'unknown'));
  assert.equal(await pending, 'unknown');
  assert.equal(await h.controller.retry(), 'ignored');
  assert.equal(await h.controller.markAll(), 'ignored');
  h.controller.receiveSnapshot([item('one'), item('two'), item('new')]);
  assert.equal(h.controller.getState().issue?.outcome, 'unknown');
  const request = h.controller.reconcile();
  assert.ok(request);
  assert.equal(h.controller.getState().reconciling, true);
  assert.equal(h.controller.reconcile(), request);
  assert.equal(h.controller.receiveSnapshot([item('one', true)], { ...request, requestId: request.requestId - 1 }), false);
  assert.equal(h.controller.getState().issue?.outcome, 'unknown');
  h.controller.receiveSnapshot([item('one', true), item('two'), item('new')], request);
  assert.equal(h.controller.getState().issue, null);
  assert.equal(h.controller.getState().reconciling, false);
  assert.equal(h.controller.getState().unreadCount, 2);
  assert.deepEqual(h.calls, ['one']);
});

test('fresh reconciliation with still-unread target keeps it unread and permits a subsequent retry', async () => {
  const h = harness();
  const pending = h.controller.markOne('one');
  h.gate().reject(new ApiError('TIMEOUT', 'Không rõ kết quả.', 0, 'unknown'));
  await pending;
  const request = h.controller.reconcile();
  assert.ok(request);
  h.controller.receiveSnapshot([item('one'), item('two')], request);
  assert.equal(h.controller.getState().unreadCount, 2);
  assert.equal(h.controller.getState().issue?.outcome, 'rejected');
  h.next();
  const retry = h.controller.retry();
  h.gate().resolve();
  assert.equal(await retry, 'confirmed');
  assert.equal(h.controller.getState().unreadCount, 1);
});

test('failed reconciliation remains unknown and blocked until another explicit snapshot succeeds', async () => {
  const h = harness();
  const pending = h.controller.markAll();
  h.gate().reject(new ApiError('TIMEOUT', 'Không rõ kết quả.', 0, 'unknown'));
  await pending;
  const failed = h.controller.reconcile();
  assert.ok(failed);
  h.controller.rejectSnapshot(new Error('network'), failed);
  assert.equal(h.controller.getState().reconciling, false);
  assert.ok(h.controller.getState().snapshotError);
  assert.equal(h.controller.getState().issue?.outcome, 'unknown');
  assert.equal(await h.controller.retry(), 'ignored');
  const fresh = h.controller.reconcile();
  assert.ok(fresh);
  assert.notEqual(fresh.requestId, failed.requestId);
  h.controller.receiveSnapshot([item('one', true), item('two', true)], fresh);
  assert.equal(h.controller.getState().issue, null);
});

test('late ACK after disposal cannot notify listeners or reload another actor session', async () => {
  const h = harness();
  let notifications = 0;
  h.controller.subscribe(() => { notifications++; });
  const pending = h.controller.markOne('one');
  const beforeDispose = notifications;
  h.controller.dispose();
  h.gate().resolve();
  assert.equal(await pending, 'ignored');
  assert.equal(notifications, beforeDispose);
  assert.equal(h.requests.length, 0);
  assert.equal(h.controller.getState().items.length, 0);
  assert.equal(await h.controller.markOne('one'), 'ignored');
  assert.equal(h.controller.receiveSnapshot([item('one')]), false);
});

test('late rejection after disposal cannot create an error or callback', async () => {
  const h = harness();
  let notifications = 0;
  h.controller.subscribe(() => { notifications++; });
  const pending = h.controller.markAll();
  h.controller.dispose();
  const count = notifications;
  h.gate().reject(new ApiError('TIMEOUT', 'Không rõ kết quả.', 0, 'unknown'));
  assert.equal(await pending, 'ignored');
  assert.equal(notifications, count);
  assert.equal(h.controller.getState().issue, null);
});

test('private userId filter denies foreign notification IDs and empty actors fail closed', async () => {
  const h = harness();
  h.controller.receiveSnapshot([item('mine'), item('peer-secret', false, 'actor-b')]);
  assert.deepEqual(h.controller.getState().items.map(row => row.id), ['mine']);
  assert.equal(await h.controller.markOne('peer-secret'), 'ignored');
  assert.equal(h.calls.length, 0);
  const empty = createNotificationReadController({ actorId: '', markOne: async () => { assert.fail('unexpected mutation'); }, markAll: async () => { assert.fail('unexpected mutation'); }, reload: () => { assert.fail('unexpected reload'); } });
  empty.receiveSnapshot([item('secret', false, '')]);
  assert.equal(empty.getState().items.length, 0);
  assert.equal(await empty.markAll(), 'ignored');
});

test('new incoming notifications survive first ACK and subsequent snapshots; state is stable and immutable', async () => {
  const h = harness();
  const original = h.controller.getState();
  assert.equal(h.controller.getState(), original);
  const pending = h.controller.markOne('one');
  h.controller.receiveSnapshot([item('one'), item('two'), item('new')]);
  h.gate().resolve();
  await pending;
  assert.deepEqual(h.controller.getState().items.map(row => row.id), ['one', 'two', 'new']);
  assert.equal(h.controller.getState().unreadCount, 2);
  h.controller.receiveSnapshot([item('one'), item('two'), item('new'), item('newer')], h.requests[0]);
  assert.equal(h.controller.getState().items[0].isRead, true);
  assert.equal(h.controller.getState().unreadCount, 3);
  assert.ok(Object.isFrozen(h.controller.getState()));
  assert.ok(Object.isFrozen(h.controller.getState().items));
  assert.ok(Object.isFrozen(h.controller.getState().items[0]));
});

test('only newest matching actor-bound snapshot request is accepted', () => {
  const h = harness();
  const stale = h.controller.refresh();
  const current = h.controller.refresh();
  assert.ok(stale && current);
  assert.equal(h.controller.receiveSnapshot([item('old')], stale), false);
  assert.equal(h.controller.receiveSnapshot([item('foreign')], { ...current, actorId: 'actor-b' }), false);
  assert.equal(h.controller.receiveSnapshot([item('new')], current), true);
  assert.deepEqual(h.controller.getState().items.map(row => row.id), ['new']);
});

test('refresh rejection after confirmed ACK reports snapshot error without reverting known read receipt', async () => {
  const h = harness();
  const pending = h.controller.markOne('one');
  h.gate().resolve();
  await pending;
  h.controller.rejectSnapshot(new Error('refresh failed'), h.requests[0]);
  assert.equal(h.controller.getState().items.find(row => row.id === 'one')?.isRead, true);
  assert.equal(h.controller.getState().issue, null);
  assert.ok(h.controller.getState().snapshotError);
});


test('fresh snapshot clears a rejected read when the real target is now read, without another mutation', async () => {
 const h=harness();const pending=h.controller.markOne('one');
 h.gate().reject(new ApiError('REJECTED','Refused',422));await pending;
 h.controller.receiveSnapshot([item('one',true),item('two')]);
 assert.equal(h.controller.getState().issue,null);
 assert.equal(h.controller.getState().unreadCount,1);
 assert.equal(await h.controller.retry(),'ignored');
 assert.deepEqual(h.calls,['one']);
});

test('removed rejected targets release stale retry, while still-unread targets retain it', async () => {
 const h=harness();const pending=h.controller.markAll();
 h.gate().reject(new ApiError('REJECTED','Refused',422));await pending;
 h.controller.receiveSnapshot([item('one',true),item('two'),item('new')]);
 assert.equal(h.controller.getState().issue?.outcome,'rejected');
 h.controller.receiveSnapshot([item('one',true),item('new')]);
 assert.equal(h.controller.getState().issue,null);
 assert.equal(h.controller.getState().unreadCount,1);
 assert.equal(h.controller.getState().items.find(row=>row.id==='new')?.isRead,false);
 assert.equal(await h.controller.retry(),'ignored');
 assert.deepEqual(h.calls,['all']);
});
