import test from 'node:test';
import assert from 'node:assert/strict';
import {calendarInputRange,calendarEditRange} from '../src/lib/calendar-input';
import {ApiError} from '../src/lib/api/errors';

test('calendar uses both entered times and serializes browser-local instants',()=>{
  const previous=process.env.TZ;
  try {
    for(const zone of ['Asia/Ho_Chi_Minh','UTC','America/New_York']) {
      process.env.TZ=zone;
      const range=calendarInputRange('2026-10-22','13:30 - 15:45');
      assert.equal(range.start,new Date(2026,9,22,13,30).toISOString());
      assert.equal(range.end,new Date(2026,9,22,15,45).toISOString());
      assert.equal(Date.parse(range.end)-Date.parse(range.start),135*60*1000);
      assert.equal(range.timeRange,'13:30 – 15:45');
    }
  } finally { if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous; }
});
test('calendar rejects invalid dates, missing end, malformed and reversed clock ranges',()=>{
  for(const [date,range] of [['2026-02-30','07:00 – 09:00'],['2026-13-01','07:00 – 09:00'],['2026-10-22','07:00'],['2026-10-22','24:00 – 25:00'],['2026-10-22','07:60 – 09:00'],['2026-10-22','09:00 – 07:00'],['2026-10-22','09:00 – 09:00'],['','07:00 – 09:00']])assert.throws(()=>calendarInputRange(date,range),(error:unknown)=>error instanceof ApiError&&error.status===422);
});
test('calendar rejects a nonexistent DST clock time without normalizing silently',()=>{
  const previous=process.env.TZ;
  try { process.env.TZ='America/New_York'; assert.throws(()=>calendarInputRange('2026-03-08','02:30 – 04:00'),ApiError); }
  finally { if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous; }
});
test('title-only calendar edits preserve seconds and multi-day instants',()=>{
  const event={date:'2026-10-22',timeRange:'23:30 – 01:00',start:'2026-10-22T23:30:17.123Z',end:'2026-10-24T01:00:19.456Z'};
  assert.deepEqual(calendarEditRange(event,event.date,event.timeRange),{});
  assert.deepEqual(calendarEditRange({...event,end:'2026-10-22T23:45:19.456Z',timeRange:'23:30 – 23:45'},event.date,'23:30 – 23:45'),{});
});
test('calendar cannot silently shorten a multi-day event through the single-day form',()=>{
  const event={date:'2026-10-22',timeRange:'07:00 – 09:00',start:new Date(2026,9,22,7).toISOString(),end:new Date(2026,9,24,9).toISOString()};
  assert.throws(()=>calendarEditRange(event,event.date,'07:00 – 10:00'),(e:unknown)=>e instanceof ApiError&&e.status===422);
  assert.deepEqual(calendarEditRange({...event,end:new Date(2026,9,22,9).toISOString()},event.date,'07:00 – 10:00'),calendarInputRange(event.date,'07:00 – 10:00'));
});
