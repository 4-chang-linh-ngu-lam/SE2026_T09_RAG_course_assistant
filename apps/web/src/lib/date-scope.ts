/** Local calendar-day boundaries; kept separate from service DTOs and display labels. */
export function localDateInput(value: string): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 10) : '';
}

function day(value: string, end: boolean): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T${end ? '23:59:59.999' : '00:00:00.000'}`);
  return Number.isFinite(date.getTime()) && localDateInput(date.toISOString()) === value ? date : null;
}

export type DateScope = { from?: string; asOf?: string; error: string | null };
export function calendarDateScope(fromDate: string, toDate: string, required = false): DateScope {
  if (required && (!fromDate || !toDate)) return { error: 'Chọn đầy đủ ngày bắt đầu và ngày kết thúc.' };
  const from = fromDate ? day(fromDate, false) : null;
  const to = toDate ? day(toDate, true) : null;
  if ((fromDate && !from) || (toDate && !to)) return { error: 'Ngày đã chọn không hợp lệ.' };
  if (from && to && from.getTime() > to.getTime()) return { error: 'Ngày bắt đầu phải trước hoặc cùng ngày kết thúc.' };
  return { ...(from ? { from: from.toISOString() } : {}), ...(to ? { asOf: to.toISOString() } : {}), error: null };
}

export function withinDateScope(at: string, scope: DateScope): boolean {
  if (scope.error) return false;
  const timestamp = Date.parse(at);
  if (!Number.isFinite(timestamp)) return false;
  return (!scope.from || timestamp >= Date.parse(scope.from)) && (!scope.asOf || timestamp <= Date.parse(scope.asOf));
}
