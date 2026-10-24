import test from 'node:test';
import assert from 'node:assert/strict';
import {calendarEventInMonth, calendarEventOnDate} from '../src/lib/calendar';

function inZones(run: () => void) {
  const previous = process.env.TZ;
  try {
    for (const zone of ['Asia/Ho_Chi_Minh', 'UTC', 'America/New_York']) {
      process.env.TZ = zone;
      run();
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
}

test('a 31 October–2 November event occupies both months and every intersecting local day', () => {
  inZones(() => {
    const event = {date:'2026-10-31', start:new Date(2026,9,31,14).toISOString(), end:new Date(2026,10,2,9).toISOString()};
    assert.equal(calendarEventInMonth(event,2026,10),true);
    assert.equal(calendarEventInMonth(event,2026,11),true);
    assert.equal(calendarEventInMonth(event,2026,12),false);
    for (const day of ['2026-10-31','2026-11-01','2026-11-02']) assert.equal(calendarEventOnDate(event,day),true);
    for (const day of ['2026-10-30','2026-11-03']) assert.equal(calendarEventOnDate(event,day),false);
  });
});

test('an event surrounding the whole month remains in its list and interior days', () => {
  inZones(() => {
    const event = {date:'2026-09-30',start:new Date(2026,8,30,23).toISOString(),end:new Date(2026,11,1).toISOString()};
    for (const month of [9,10,11]) assert.equal(calendarEventInMonth(event,2026,month),true);
    assert.equal(calendarEventInMonth(event,2026,12),false);
    assert.equal(calendarEventOnDate(event,'2026-11-15'),true);
  });
});

test('midnight is an exclusive end while a later end includes the next day', () => {
  inZones(() => {
    const event = {date:'2026-10-31',start:new Date(2026,9,31,23).toISOString(),end:new Date(2026,10,1).toISOString()};
    assert.equal(calendarEventInMonth(event,2026,11),false);
    assert.equal(calendarEventOnDate(event,'2026-11-01'),false);
    assert.equal(calendarEventOnDate({...event,end:new Date(2026,10,1,0,0,0,1).toISOString()},'2026-11-01'),true);
  });
});

test('overlap handles year rollover and leap day', () => {
  inZones(() => {
    const year = {date:'2026-12-31',start:new Date(2026,11,31,20).toISOString(),end:new Date(2027,0,2,8).toISOString()};
    assert.equal(calendarEventInMonth(year,2027,1),true);
    assert.equal(calendarEventOnDate(year,'2027-01-01'),true);
    const leap = {date:'2028-02-28',start:new Date(2028,1,28,20).toISOString(),end:new Date(2028,2,1).toISOString()};
    assert.equal(calendarEventOnDate(leap,'2028-02-29'),true);
    assert.equal(calendarEventOnDate(leap,'2028-03-01'),false);
    assert.equal(calendarEventOnDate(leap,'2028-02-30'),false);
  });
});

test('point deadlines and missing ends occupy exactly their local start day', () => {
  inZones(() => {
    const event = {date:'2026-11-01',start:new Date(2026,10,1,23,59).toISOString()};
    for (const value of [event,{...event,end:event.start}]) {
      assert.equal(calendarEventOnDate(value,'2026-11-01'),true);
      assert.equal(calendarEventOnDate(value,'2026-11-02'),false);
      assert.equal(calendarEventInMonth(value,2026,11),true);
    }
  });
});

test('timestamp timezone wins over a stale start-date label', () => {
  inZones(() => {
    const event = {date:'2026-10-31',start:'2026-10-31T23:30:00Z'};
    const expected = process.env.TZ === 'Asia/Ho_Chi_Minh' ? '2026-11-01' : '2026-10-31';
    assert.equal(calendarEventOnDate(event,expected),true);
    assert.equal(calendarEventInMonth(event,2026,expected === '2026-11-01' ? 11 : 10),true);
  });
});

test('local day bounds respect the 23-hour and 25-hour DST days', () => {
  const previous = process.env.TZ;
  try {
    process.env.TZ = 'America/New_York';
    const spring = {date:'2026-03-09',start:new Date(2026,2,9,0,15).toISOString(),end:new Date(2026,2,9,0,30).toISOString()};
    assert.equal(calendarEventOnDate(spring,'2026-03-08'),false);
    assert.equal(calendarEventOnDate(spring,'2026-03-09'),true);
    const autumn = {date:'2026-11-01',start:new Date(2026,10,1,23,30).toISOString(),end:new Date(2026,10,1,23,45).toISOString()};
    assert.equal(calendarEventOnDate(autumn,'2026-11-01'),true);
    assert.equal(calendarEventOnDate(autumn,'2026-11-02'),false);
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test('legacy date-only items still appear while invalid or reversed intervals do not', () => {
  inZones(() => {
    assert.equal(calendarEventOnDate({date:'2026-11-01',start:'07:00'},'2026-11-01'),true);
    assert.equal(calendarEventOnDate({date:'2026-11-01',start:'2026-11-01'},'2026-11-01'),true);
    assert.equal(calendarEventOnDate({date:'invalid',start:'invalid'},'2026-11-01'),false);
    assert.equal(calendarEventInMonth({date:'2026-11-02',start:'2026-11-02T08:00:00',end:'2026-11-01T08:00:00'},2026,11),false);
  });
});
