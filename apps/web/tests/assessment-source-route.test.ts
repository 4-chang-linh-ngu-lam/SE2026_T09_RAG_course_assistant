import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assessmentSourceHref } from '../src/lib/assessment';

test('assessment citations use the registered reader route and preserve source position', () => {
  const href = assessmentSourceHref('class-1', {
    documentId: 'doc-1',
    title: 'Source',
    version: 3,
    locator: 'page:4/section:2',
    accessible: true,
  });
  assert.ok(href);
  const url = new URL(href, 'https://example.test');
  assert.equal(url.pathname, '/student/classes/class-1/documents/doc-1');
  assert.equal(url.searchParams.get('version'), '3');
  assert.equal(url.searchParams.get('locator'), 'page:4/section:2');
});
