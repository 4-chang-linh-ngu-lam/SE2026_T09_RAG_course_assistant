import test from 'node:test';
import assert from 'node:assert/strict';
import { personalSourceHref } from '../src/lib/document-preview';

test('saved note and bookmark links retain their historical source version and page', () => {
  const href = personalSourceHref({ classId: 'math 10', documentId: 'doc/1', version: 2, pageNumber: 7 });
  assert.equal(href, '/student/classes/math%2010/documents/doc%2F1?version=2&page=7');
  assert.equal(new URL(href, 'https://lumi.example').searchParams.get('version'), '2');
});

test('legacy saved sources without a version still open, while invalid locators are discarded', () => {
  const source = { classId: 'class', documentId: 'document' };
  assert.equal(personalSourceHref({ ...source, pageNumber: 3 }), '/student/classes/class/documents/document?page=3');
  for (const invalid of [0, -1, 1.5, NaN, Infinity]) {
    assert.equal(personalSourceHref({ ...source, version: invalid, pageNumber: invalid }), '/student/classes/class/documents/document');
  }
});
