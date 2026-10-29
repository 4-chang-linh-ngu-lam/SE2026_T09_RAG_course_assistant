import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseCalendarEventSchedule, spansMultipleLocalDays } from '../src/lib/calendar';

test('calendar event timestamps follow the entered date and time range', () => {
  const schedule = parseCalendarEventSchedule('2026-10-25', '14:00 – 15:30');
  assert.ok(schedule);
  const start = new Date(schedule.start);
  const end = new Date(schedule.end);
  assert.equal(start.getFullYear(), 2026);
  assert.equal(start.getMonth(), 9);
  assert.equal(start.getDate(), 25);
  assert.equal(start.getHours(), 14);
  assert.equal(start.getMinutes(), 0);
  assert.equal(end.getHours(), 15);
  assert.equal(end.getMinutes(), 30);
});

test('calendar event schedule rejects malformed, invalid, and reversed ranges', () => {
  assert.equal(parseCalendarEventSchedule('2026-02-30', '08:00 – 09:00'), null);
  assert.equal(parseCalendarEventSchedule('2026-10-25', '24:00 – 25:00'), null);
  assert.equal(parseCalendarEventSchedule('2026-10-25', '14:00 – 13:00'), null);
  assert.equal(parseCalendarEventSchedule('2026-10-25', 'after lunch'), null);
});

test('multi-day calendar events are distinguished from same-day schedules', () => {
  assert.equal(spansMultipleLocalDays('2026-10-29T09:00:00+07:00', '2026-10-30T10:00:00+07:00'), true);
  assert.equal(spansMultipleLocalDays('2026-10-29T09:00:00+07:00', '2026-10-29T10:00:00+07:00'), false);
  assert.equal(spansMultipleLocalDays('invalid', 'invalid'), false);
});
