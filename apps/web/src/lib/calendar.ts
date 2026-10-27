import type { Role } from './domain';
import { canOpenRoute, matchRoute } from './navigation';
import { routeHref } from '@/config/routes';

export type CalendarDayCell = {
  dayNumber: number;
  inMonth: boolean;
  dateString: string;
  isToday: boolean;
};

/** Converts an entered same-day schedule into timestamps in the browser's local timezone. */
export function parseCalendarEventSchedule(date: string, timeRange: string): { start: string; end: string } | null {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const timeMatch = /^(\d{2}):(\d{2})\s*[–—-]\s*(\d{2}):(\d{2})$/.exec(timeRange.trim());
  if (!dateMatch || !timeMatch) return null;

  const [, yearText, monthText, dayText] = dateMatch;
  const [, startHourText, startMinuteText, endHourText, endMinuteText] = timeMatch;
  const [year, month, day, startHour, startMinute, endHour, endMinute] = [
    yearText, monthText, dayText, startHourText, startMinuteText, endHourText, endMinuteText,
  ].map(Number);
  if (startHour > 23 || endHour > 23 || startMinute > 59 || endMinute > 59) return null;

  const start = new Date(year, month - 1, day, startHour, startMinute);
  const end = new Date(year, month - 1, day, endHour, endMinute);
  const sameEnteredDate = (value: Date) =>
    value.getFullYear() === year && value.getMonth() === month - 1 && value.getDate() === day;
  if (!sameEnteredDate(start) || !sameEnteredDate(end) || end <= start) return null;

  return { start: start.toISOString(), end: end.toISOString() };
}

/**
 * Returns the number of days in the specified month (1-indexed: 1 = Jan, ..., 12 = Dec).
 * Correctly accounts for leap years in February (29 in leap years, 28 otherwise).
 */
export function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

/**
 * Returns Monday-indexed weekday of the first day of the month:
 * 0 = Monday (Thứ 2), 1 = Tuesday (Thứ 3), ..., 6 = Sunday (Chủ Nhật).
 */
export function getStartDayOfWeek(year: number, month: number): number {
  const day = new Date(year, month - 1, 1).getDay();
  return (day + 6) % 7;
}

/**
 * Formats a Date object to YYYY-MM-DD.
 */
export function formatDateIso(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Generates the complete calendar grid for a given year and month (1-indexed).
 * Correctly aligns weekdays (Mon..Sun) and pads leading days from the previous month
 * and trailing days into the next month.
 * Accommodates 28/29/30/31 day months, 5-week or 6-week months (e.g. August 2026),
 * and December/January year rollovers.
 */
export function generateCalendarGrid(
  year: number,
  month: number,
  todayDateString?: string
): CalendarDayCell[] {
  const daysInCurrentMonth = getDaysInMonth(year, month);
  const startDayOfWeek = getStartDayOfWeek(year, month);

  // Total rows required: 5 or 6 (35 or 42 cells)
  const totalSlotsNeeded = startDayOfWeek + daysInCurrentMonth;
  const totalCells = Math.max(35, Math.ceil(totalSlotsNeeded / 7) * 7);

  const cells: CalendarDayCell[] = [];

  // Trailing days from previous month
  const prevYear = month === 1 ? year - 1 : year;
  const prevMonth = month === 1 ? 12 : month - 1;
  const daysInPrevMonth = getDaysInMonth(prevYear, prevMonth);

  for (let i = startDayOfWeek - 1; i >= 0; i--) {
    const dayNumber = daysInPrevMonth - i;
    const dateString = `${prevYear}-${String(prevMonth).padStart(2, '0')}-${String(dayNumber).padStart(2, '0')}`;
    cells.push({
      dayNumber,
      inMonth: false,
      dateString,
      isToday: Boolean(todayDateString && dateString === todayDateString),
    });
  }

  // Days in current month
  for (let d = 1; d <= daysInCurrentMonth; d++) {
    const dateString = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    cells.push({
      dayNumber: d,
      inMonth: true,
      dateString,
      isToday: Boolean(todayDateString && dateString === todayDateString),
    });
  }

  // Leading days into next month
  const nextYear = month === 12 ? year + 1 : year;
  const nextMonth = month === 12 ? 1 : month + 1;
  const remainingSlots = totalCells - cells.length;

  for (let d = 1; d <= remainingSlots; d++) {
    const dateString = `${nextYear}-${String(nextMonth).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    cells.push({
      dayNumber: d,
      inMonth: false,
      dateString,
      isToday: Boolean(todayDateString && dateString === todayDateString),
    });
  }

  return cells;
}

/**
 * Generates the 7 days (Monday to Sunday) for the week containing the specified date.
 */
export function generateWeekDays(
  referenceDateString: string,
  todayDateString?: string
): CalendarDayCell[] {
  const parts = referenceDateString.split('-');
  const y = parseInt(parts[0], 10);
  const m = parseInt(parts[1], 10);
  const d = parseInt(parts[2], 10);

  const targetDate = new Date(y, m - 1, d);
  const dayOfWeek = (targetDate.getDay() + 6) % 7; // Monday = 0

  const mondayDate = new Date(y, m - 1, d - dayOfWeek);
  const cells: CalendarDayCell[] = [];

  for (let i = 0; i < 7; i++) {
    const current = new Date(mondayDate.getFullYear(), mondayDate.getMonth(), mondayDate.getDate() + i);
    const dateString = formatDateIso(current);
    cells.push({
      dayNumber: current.getDate(),
      inMonth: current.getMonth() + 1 === m,
      dateString,
      isToday: Boolean(todayDateString && dateString === todayDateString),
    });
  }

  return cells;
}

/**
 * Resolves the initial calendar year, month, and today date string.
 * Uses a model-provided displayDate (in preview/mock) or system clock (in live).
 */
export function getInitialCalendarState(displayDate?: string): {
  year: number;
  month: number;
  todayDate: string;
} {
  if (displayDate) {
    const parts = displayDate.split('-');
    if (parts.length === 3) {
      const y = parseInt(parts[0], 10);
      const m = parseInt(parts[1], 10);
      if (!isNaN(y) && !isNaN(m)) {
        return { year: y, month: m, todayDate: displayDate };
      }
    }
  }

  const now = new Date();
  return {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
    todayDate: formatDateIso(now),
  };
}

function extractRouteParams(pattern: string, pathname: string): Record<string, string> {
  const normPattern = pattern.replace(/\/+$/, '') || '/';
  const normPath = pathname.replace(/\/+$/, '') || '/';
  const patternParts = normPattern.split('/');
  const pathParts = normPath.split('/');
  const params: Record<string, string> = {};

  if (patternParts.length !== pathParts.length) {
    return params;
  }

  for (let i = 0; i < patternParts.length; i++) {
    const part = patternParts[i];
    if (part.startsWith(':')) {
      const key = part.slice(1);
      try {
        params[key] = decodeURIComponent(pathParts[i]);
      } catch {
        params[key] = pathParts[i];
      }
    }
  }

  return params;
}

/**
 * Rewrites event URLs to be safe for the user's role and prevents cross-role navigation leaks.
 */
export function getRoleAwareEventHref(
  href: string | undefined,
  role: Role,
  classId?: string
): string | undefined {
  if (!href || typeof href !== 'string') return undefined;

  const matched = matchRoute(href);
  if (!matched) return undefined;

  const pathname = href.split(/[?#]/)[0];
  const cleanPath = pathname.replace(/\/+$/, '') || '/';
  const params = extractRouteParams(matched.path, cleanPath);
  const urlClassId = params['classId'];

  // Reject mismatched provided class ID
  if (urlClassId && classId && urlClassId !== classId) {
    return undefined;
  }

  // Keep valid same-role resource URLs
  if (canOpenRoute(matched, [role])) {
    return cleanPath;
  }

  const effectiveClassId = urlClassId || classId;

  if (role === 'LECTURER') {
    if (matched.id === 's.home') {
      return routeHref('t.home') ?? '/teacher';
    }
    if (matched.id === 's.classes') {
      return routeHref('t.classes') ?? '/teacher/classes';
    }

    if (effectiveClassId) {
      if (matched.id === 's.overview') {
        return routeHref('t.overview', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 's.feed') {
        return routeHref('t.feed', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 's.documents' || matched.id === 's.reader') {
        return routeHref('t.documents', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 's.tutor') {
        return routeHref('t.tutor', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 's.calendar') {
        return routeHref('t.calendar', { classId: effectiveClassId }) ?? undefined;
      }

      // Wrong-role Learning activity source -> map to safe real teacher route `t.activities`
      if (
        matched.capabilityIds.includes('learning') ||
        matched.id.startsWith('s.assignment') ||
        matched.id.startsWith('s.assessment') ||
        matched.id.startsWith('s.practice') ||
        matched.id === 's.progress'
      ) {
        return routeHref('t.activities', { classId: effectiveClassId }) ?? undefined;
      }

      // Fallback safe route for other student class routes
      return routeHref('t.overview', { classId: effectiveClassId }) ?? undefined;
    }

    return undefined;
  }

  if (role === 'STUDENT') {
    if (matched.id === 't.home') {
      return routeHref('s.home') ?? '/student';
    }
    if (matched.id === 't.classes') {
      return routeHref('s.classes') ?? '/student/classes';
    }

    if (effectiveClassId) {
      if (matched.id === 't.overview') {
        return routeHref('s.overview', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 't.feed') {
        return routeHref('s.feed', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 't.documents') {
        return routeHref('s.documents', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 't.tutor') {
        return routeHref('s.tutor', { classId: effectiveClassId }) ?? undefined;
      }
      if (matched.id === 't.calendar') {
        return routeHref('s.calendar', { classId: effectiveClassId }) ?? undefined;
      }

      // Teacher learning activities, deep editors, grading queue/submissions, or when no exact target exists:
      // Student safely returns to s.overview
      return routeHref('s.overview', { classId: effectiveClassId }) ?? undefined;
    }

    return undefined;
  }

  return undefined;
}
