import test from 'node:test';
import assert from 'node:assert/strict';
import { isRouteAvailable } from '../src/lib/route-availability';

test('live navigation offers implemented flows and hides unavailable services', () => {
  for (const id of ['s.documents', 't.library', 's.tutor', 's.practice', 's.progress', 't.analytics', 'a.reports', 'a.dataRequests']) {
    assert.equal(isRouteAvailable(id, 'live'), false);
    assert.equal(isRouteAvailable(id, 'mock'), true);
  }
  for (const id of ['s.feed', 't.overview', 't.calendar', 'a.accounts', 'a.audit', 'account.profile']) {
    assert.equal(isRouteAvailable(id, 'live'), true);
  }
});
