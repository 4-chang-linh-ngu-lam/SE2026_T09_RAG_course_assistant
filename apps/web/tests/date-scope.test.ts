import test from 'node:test';
import assert from 'node:assert/strict';
import { calendarDateScope, localDateInput, withinDateScope } from '../src/lib/date-scope';

test('calendar scope includes both complete local days and excludes adjacent days', () => {
  const scope = calendarDateScope('2026-10-19', '2026-10-20', true);
  assert.equal(scope.error, null);
  assert.equal(withinDateScope(new Date('2026-10-19T00:00:00.000').toISOString(), scope), true);
  assert.equal(withinDateScope(new Date('2026-10-20T23:59:59.999').toISOString(), scope), true);
  assert.equal(withinDateScope(new Date('2026-10-18T23:59:59.999').toISOString(), scope), false);
  assert.equal(withinDateScope(new Date('2026-10-21T00:00:00.000').toISOString(), scope), false);
  assert.equal(localDateInput(scope.from!), '2026-10-19');
  assert.equal(localDateInput(scope.asOf!), '2026-10-20');
});

test('invalid and reversed ranges fail closed without rolling impossible dates forward', () => {
  for (const pair of [['2026-02-30', '2026-03-02'], ['2026-10-21', '2026-10-20'], ['broken', '2026-10-20']]) {
    const scope = calendarDateScope(...pair as [string, string]);
    assert.ok(scope.error);
    assert.equal(scope.from, undefined);
    assert.equal(withinDateScope('2026-10-20T12:00:00Z', scope), false);
  }
  assert.ok(calendarDateScope('', '2026-10-20', true).error);
  assert.deepEqual(calendarDateScope('', ''), { error: null });
});

test('audit date boundaries can be open-ended; invalid audit times never match', () => {
  assert.equal(withinDateScope('2020-01-01T00:00:00Z', calendarDateScope('', '2026-10-20')), true);
  assert.equal(withinDateScope('2030-01-01T00:00:00Z', calendarDateScope('2026-10-20', '')), true);
  assert.equal(withinDateScope('invalid', calendarDateScope('', '')), false);
});
