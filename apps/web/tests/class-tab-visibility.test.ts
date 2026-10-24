import test from 'node:test';
import assert from 'node:assert/strict';
import { classTabScrollDelta } from '../src/components/class-tab-visibility';

test('class tabs reveal a selected off-screen tab inside the strip without moving a visible tab', () => {
  const viewport = { viewportLeft: 16, viewportRight: 374 };
  const right = { ...viewport, tabLeft: 1011.5, tabRight: 1110.5 };
  const delta = classTabScrollDelta(right);
  assert.equal(right.tabRight - delta, viewport.viewportRight);
  assert.ok(right.tabLeft - delta >= viewport.viewportLeft);
  assert.equal(classTabScrollDelta({ ...viewport, tabLeft: 30, tabRight: 160 }), 0);
  const left = { ...viewport, tabLeft: -80, tabRight: 30 };
  assert.equal(left.tabLeft - classTabScrollDelta(left), viewport.viewportLeft);
});

test('an oversized tab aligns its start and does not oscillate between two edges', () => {
  const viewport = { viewportLeft: 0, viewportRight: 200 };
  const delta = classTabScrollDelta({ ...viewport, tabLeft: 80, tabRight: 380 });
  assert.equal(delta, 80);
  assert.equal(classTabScrollDelta({ ...viewport, tabLeft: 0, tabRight: 300 }), 0);
});
