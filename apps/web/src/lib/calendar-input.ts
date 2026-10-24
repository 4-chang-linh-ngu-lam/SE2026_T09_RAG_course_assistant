import {ApiError} from './api/errors';
import type {CalendarEvent} from './domain';

// The form's date and clock times are local to the browser. Serialize the actual
// instants with a timezone, rather than attaching Z to an unrelated fixed hour.
export function calendarInputRange(date: string, timeRange: string) {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const range = /^(\d{2}):(\d{2})\s*[–—-]\s*(\d{2}):(\d{2})$/.exec(timeRange.trim());
  const invalid = (): never => { throw new ApiError('VALIDATION_ERROR', 'Nhập ngày hợp lệ và đủ giờ bắt đầu – kết thúc (HH:mm – HH:mm). Giờ kết thúc phải sau giờ bắt đầu trong ngày đã chọn.', 422); };
  if (!day || !range) return invalid();
  const [year,month,dayOfMonth] = day.slice(1).map(Number);
  const [startHour,startMinute,endHour,endMinute] = range.slice(1).map(Number);
  if (year < 1 || month < 1 || month > 12 || dayOfMonth < 1 || dayOfMonth > 31 || startHour > 23 || endHour > 23 || startMinute > 59 || endMinute > 59) return invalid();
  const make = (hour: number, minute: number) => {
    const value = new Date(year,month-1,dayOfMonth,hour,minute);
    if (year < 100) value.setFullYear(year);
    // Reject rolled-over calendar dates and nonexistent local times (DST gaps).
    if (value.getFullYear() !== year || value.getMonth() !== month-1 || value.getDate() !== dayOfMonth || value.getHours() !== hour || value.getMinutes() !== minute) return invalid();
    return value;
  };
  const start = make(startHour,startMinute), end = make(endHour,endMinute);
  if (end.getTime() <= start.getTime()) return invalid();
  return {date,start:start.toISOString(),end:end.toISOString(),timeRange:`${range[1]}:${range[2]} – ${range[3]}:${range[4]}`};
}

export function calendarEditRange(event:Pick<CalendarEvent,'date'|'timeRange'|'start'|'end'>,date:string,timeRange:string){
  // A title/description edit must preserve the original instants, including
  // seconds and multi-day spans that the single-day form cannot represent.
  if(date===event.date&&timeRange.trim()===event.timeRange?.trim())return {};
  if(event.end){
    const start=new Date(event.start),end=new Date(event.end);
    if(Number.isFinite(start.getTime())&&Number.isFinite(end.getTime())&&
      (start.getFullYear()!==end.getFullYear()||start.getMonth()!==end.getMonth()||start.getDate()!==end.getDate())){
      throw new ApiError('VALIDATION_ERROR','Biểu mẫu hiện chỉ hỗ trợ đổi ngày/giờ của sự kiện trong một ngày. Bạn vẫn có thể sửa tiêu đề và mô tả của sự kiện nhiều ngày.',422);
    }
  }
  return calendarInputRange(date,timeRange);
}
