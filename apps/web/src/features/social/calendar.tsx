'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import type { CalendarEvent, Role, RouteParams, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { Dialog, ErrorNotice, Icon, StatePanel } from '@/components/ui';
import {
  generateCalendarGrid,
  generateWeekDays,
  getInitialCalendarState,
  getRoleAwareEventHref,
  parseCalendarEventSchedule,
  spansMultipleLocalDays,
} from '@/lib/calendar';

type Props = {
  data: WorkspaceData | null;
  role: Role;
  params: RouteParams;
  reload(): void;
  isGlobal?: boolean;
};

export function CalendarFeature({ data, role, params, reload, isGlobal = false }: Props) {
  const [viewMode, setViewMode] = useState<'month' | 'week' | 'list'>('month');
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [localEvents, setLocalEvents] = useState<CalendarEvent[] | null>(null);

  // Dialog states
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Form states for Create
  const [createClassId, setCreateClassId] = useState(params.classId ?? '');
  const [newTitle, setNewTitle] = useState('');
  const [newDate, setNewDate] = useState('');
  const [newTimeRange, setNewTimeRange] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  // Form states for Edit
  const [editTitle, setEditTitle] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editTimeRange, setEditTimeRange] = useState('');
  const [editScheduleChanged, setEditScheduleChanged] = useState(false);
  const [editDescription, setEditDescription] = useState('');
  const [editLocation, setEditLocation] = useState('');
  const [editError, setEditError] = useState<string | null>(null);

  // Delete state
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const contextKey = `${isGlobal ? 'global' : params.classId ?? 'class'}:${role}`;
  const initializedContextRef = useRef<string | null>(null);

  // Date state derived from data model or clock
  const readyData = data?.kind === 'ready' ? data : null;
  const initialState = getInitialCalendarState(readyData?.displayDate);
  const [currentYearMonth, setCurrentYearMonth] = useState({
    year: initialState.year,
    month: initialState.month,
  });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  useEffect(() => {
    if (data?.kind === 'ready') {
      if (initializedContextRef.current !== contextKey) {
        initializedContextRef.current = contextKey;
        const initial = getInitialCalendarState(data.displayDate);
        setCurrentYearMonth({
          year: initial.year,
          month: initial.month,
        });
        setSelectedEventId(null);
        setSelectedDate(null);
      }
    }
  }, [data, contextKey]);

  if (!data) return <StatePanel busy title="Đang tải lịch học…" />;

  if (data.kind === 'unavailable') {
    return (
      <div className="workspace-content">
        <div className="card padded">
          <div className="section-heading">
            <div>
              <h2>{isGlobal ? 'Lịch tổng hợp các lớp' : 'Lịch học lớp'}</h2>
              <p className="muted">Thời khóa biểu, sự kiện và thời hạn học tập</p>
            </div>
            <button className="button" onClick={reload}>Thử lại</button>
          </div>
          <StatePanel title="Dịch vụ lịch học chưa sẵn sàng" message={data.message}>
            <button className="button" onClick={reload}>Tải lại</button>
          </StatePanel>
        </div>
      </div>
    );
  }

  if (data.kind === 'empty') {
    return (
      <div className="workspace-content">
        <div className="card padded">
          <div className="section-heading">
            <div>
              <h2>Lịch học</h2>
              <p className="muted">Thời khóa biểu, sự kiện và thời hạn học tập</p>
            </div>
            <button className="button" onClick={reload}>Thử lại</button>
          </div>
          <StatePanel title="Chưa có sự kiện nào trong lịch" message={data.message} />
        </div>
      </div>
    );
  }

  const events = localEvents ?? readyData?.calendarEvents ?? [];
  const monthPrefix = `${currentYearMonth.year}-${String(currentYearMonth.month).padStart(2, '0')}`;
  const monthEvents = events.filter(e => e.date && e.date.startsWith(monthPrefix));
  const selectedEvent =
    (selectedEventId ? monthEvents.find(e => e.id === selectedEventId) : null) ??
    monthEvents[0] ??
    null;
  const selectedEventSpansDays = Boolean(
    adapter.source === 'live'
    && selectedEvent?.end
    && spansMultipleLocalDays(selectedEvent.start, selectedEvent.end),
  );
  const isTeacher = role === 'LECTURER';

  const assignedClasses = readyData?.classes ?? (readyData?.classSummary ? [readyData.classSummary] : []);
  const todayDateStr = getInitialCalendarState(readyData?.displayDate).todayDate;

  function prevMonth() {
    setSelectedEventId(null);
    setSelectedDate(null);
    setCurrentYearMonth(prev => {
      const month = prev.month === 1 ? 12 : prev.month - 1;
      const year = prev.month === 1 ? prev.year - 1 : prev.year;
      return { year, month };
    });
  }

  function nextMonth() {
    setSelectedEventId(null);
    setSelectedDate(null);
    setCurrentYearMonth(prev => {
      const month = prev.month === 12 ? 1 : prev.month + 1;
      const year = prev.month === 12 ? prev.year + 1 : prev.year;
      return { year, month };
    });
  }

  function handleOpenCreate() {
    setFormError(null);
    setNewTitle('');
    setNewDate(todayDateStr);
    setNewTimeRange('07:00 – 09:15');
    setNewDescription('');
    setCreateClassId(params.classId ?? assignedClasses[0]?.id ?? '');
    setCreateDialogOpen(true);
  }

  function handleOpenEdit() {
    if (!selectedEvent) return;
    setEditError(null);
    setEditTitle(selectedEvent.title);
    setEditDate(selectedEvent.date);
    setEditTimeRange(selectedEvent.timeRange ?? '');
    setEditScheduleChanged(false);
    setEditDescription(selectedEvent.description ?? '');
    setEditLocation(selectedEvent.location ?? '');
    setEditDialogOpen(true);
  }

  function handleOpenDelete() {
    if (!selectedEvent) return;
    setDeleteError(null);
    setDeleteDialogOpen(true);
  }

  async function handleCreateEvent(e: React.FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) {
      setFormError('Vui lòng nhập tiêu đề sự kiện.');
      return;
    }
    const targetClassId = params.classId || createClassId;
    const targetClass = assignedClasses.find(c => c.id === targetClassId) ?? readyData?.classSummary;
    const timeRange = newTimeRange.trim();
    const schedule = timeRange ? parseCalendarEventSchedule(newDate, timeRange) : null;
    if (adapter.source === 'live' && !timeRange) {
      setFormError('Hãy nhập giờ bắt đầu và kết thúc cho sự kiện trên máy chủ.');
      return;
    }
    if (!newDate || (timeRange && !schedule)) {
      setFormError(timeRange ? 'Ngày hoặc khung giờ không hợp lệ. Hãy nhập giờ kết thúc sau giờ bắt đầu.' : 'Vui lòng chọn ngày sự kiện.');
      return;
    }

    setBusy(true);
    setFormError(null);
    try {
      const created = await adapter.calendar.createEvent({
        classId: targetClassId || undefined,
        className: targetClass?.name ?? 'Lớp học',
        title: newTitle.trim(),
        description: newDescription.trim() || undefined,
        category: 'CLASS',
        date: newDate,
        start: schedule?.start ?? newDate,
        end: schedule?.end,
        timeRange: timeRange || undefined,
        teacherName: isTeacher ? 'Giáo viên phụ trách' : undefined,
      });
      setLocalEvents([...events, created]);
      setSelectedEventId(created.id);
      setCreateDialogOpen(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Chưa thể tạo sự kiện.');
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateEvent(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedEvent) return;
    if (!editTitle.trim()) {
      setEditError('Vui lòng nhập tiêu đề sự kiện.');
      return;
    }
    const schedule = editTimeRange.trim() ? parseCalendarEventSchedule(editDate, editTimeRange) : null;
    const updateSchedule = adapter.source === 'live' ? (editScheduleChanged ? schedule : null) : schedule;
    if (adapter.source === 'live' && (!selectedEvent.classId || (editScheduleChanged && !schedule))) {
      setEditError('Hãy nhập ngày, giờ bắt đầu và kết thúc hợp lệ cho sự kiện trên máy chủ.');
      return;
    }
    if (selectedEventSpansDays && editScheduleChanged) {
      setEditError('Sự kiện kéo dài nhiều ngày; API hiện chưa hỗ trợ sửa riêng ngày kết thúc. Hãy chỉ sửa tiêu đề hoặc mô tả.');
      return;
    }
    setBusy(true);
    setEditError(null);
    try {
      const updated = await adapter.calendar.updateEvent(selectedEvent.id, {
        title: editTitle.trim(),
        date: editDate,
        timeRange: editTimeRange.trim() || undefined,
        ...(updateSchedule ? { start: updateSchedule.start, end: updateSchedule.end } : {}),
        description: editDescription.trim() || undefined,
        location: editLocation.trim() || undefined,
      }, selectedEvent.classId ?? params.classId);
      setLocalEvents(prev => (prev ?? events).map(ev => (ev.id === updated.id ? updated : ev)));
      setEditDialogOpen(false);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Chưa thể cập nhật sự kiện.');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteEvent() {
    if (!selectedEvent) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await adapter.calendar.deleteEvent(selectedEvent.id, selectedEvent.classId ?? params.classId);
      setLocalEvents(prev => (prev ?? events).filter(ev => ev.id !== selectedEvent.id));
      setSelectedEventId(null);
      setDeleteDialogOpen(false);
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : 'Chưa thể xóa sự kiện.');
    } finally {
      setBusy(false);
    }
  }

  const anchorDateStr = (() => {
    if (selectedEventId) {
      const activeEvt = monthEvents.find(e => e.id === selectedEventId);
      if (activeEvt?.date) return activeEvt.date;
    }
    if (selectedDate && selectedDate.startsWith(monthPrefix)) {
      return selectedDate;
    }
    if (todayDateStr && todayDateStr.startsWith(monthPrefix)) {
      return todayDateStr;
    }
    if (monthEvents[0]?.date) {
      return monthEvents[0].date;
    }
    return `${monthPrefix}-01`;
  })();

  // Pure grid computation
  const calendarDays = generateCalendarGrid(currentYearMonth.year, currentYearMonth.month, todayDateStr);
  const weekDays = generateWeekDays(anchorDateStr, todayDateStr);
  const listEvents = monthEvents;

  const categoryColor: Record<string, string> = {
    CLASS: 'cal-badge-blue',
    ASSIGNMENT: 'cal-badge-amber',
    EXAM: 'cal-badge-red',
    OTHER: 'cal-badge-green',
  };

  const categoryLabel: Record<string, string> = {
    CLASS: 'Sự kiện lớp',
    ASSIGNMENT: 'Bài tập cần nộp',
    EXAM: 'Bài kiểm tra',
    OTHER: 'Hoạt động khác',
  };

  const isSelectedEventEditable = Boolean(
    isTeacher &&
      selectedEvent &&
      !selectedEvent.readOnly &&
      selectedEvent.category !== 'ASSIGNMENT' &&
      selectedEvent.category !== 'EXAM'
  );

  const safeActionHref = selectedEvent ? getRoleAwareEventHref(selectedEvent.href, role, params.classId ?? selectedEvent.classId) : undefined;

  return (
    <div className="calendar-feature">
      {/* Calendar Toolbar */}
      <div className="calendar-toolbar card padded">
        <div className="cal-nav-group">
          <button className="icon-button" type="button" aria-label="Tháng trước" onClick={prevMonth}>
            <Icon name="chevronLeft" />
          </button>
          <span className="cal-month-title">Tháng {currentYearMonth.month}, {currentYearMonth.year}</span>
          <button className="icon-button" type="button" aria-label="Tháng sau" onClick={nextMonth}>
            <Icon name="chevronRight" />
          </button>
          {isGlobal ? (
            <span className="tag" style={{ background: '#f1f5f9', color: '#475569' }}>
              Tổng hợp tất cả các lớp
            </span>
          ) : readyData?.classSummary ? (
            <span className="tag">{readyData.classSummary.name}</span>
          ) : null}
        </div>

        <div className="cal-controls-right">
          {/* Legend */}
          <div className="cal-legend" aria-label="Chú thích màu">
            <span className="legend-item"><span className="dot dot-blue" />Sự kiện lớp</span>
            <span className="legend-item"><span className="dot dot-amber" />Bài tập</span>
            <span className="legend-item"><span className="dot dot-red" />Kiểm tra</span>
            <span className="legend-item"><span className="dot dot-green" />Hoạt động khác</span>
          </div>

          {/* View switcher */}
          <div className="segmented" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'month'}
              onClick={() => setViewMode('month')}
            >
              Tháng
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'week'}
              onClick={() => setViewMode('week')}
            >
              Tuần
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === 'list'}
              onClick={() => setViewMode('list')}
            >
              Danh sách
            </button>
          </div>

          {/* Teacher Add Event Button */}
          {isTeacher && (
            <button
              className="button primary"
              type="button"
              onClick={handleOpenCreate}
            >
              <Icon name="plus" /> {isGlobal ? 'Thêm sự kiện' : 'Thêm sự kiện lớp'}
            </button>
          )}
        </div>
      </div>

      {/* Main Grid + Detail Sidebar */}
      <div className="calendar-main-grid">
        {/* Left Column: Month / Week / List View */}
        <div className="cal-calendar-pane card">
          {viewMode === 'month' && (
            <div className="cal-month-table">
              <div className="cal-weekdays-header">
                <div>Thứ Hai (T2)</div>
                <div>Thứ Ba (T3)</div>
                <div>Thứ Tư (T4)</div>
                <div>Thứ Năm (T5)</div>
                <div>Thứ Sáu (T6)</div>
                <div>Thứ Bảy (T7)</div>
                <div>Chủ Nhật (CN)</div>
              </div>

              <div className="cal-days-grid">
                {calendarDays.map((cell, idx) => {
                  const dayEvents = events.filter(e => e.date === cell.dateString);
                  return (
                    <div
                      key={idx}
                      className={`cal-day-cell ${cell.inMonth ? 'in-month' : 'other-month'} ${cell.isToday ? 'today' : ''} ${selectedDate === cell.dateString ? 'selected' : ''}`}
                      onClick={() => {
                        setSelectedDate(cell.dateString);
                        const firstEvt = dayEvents[0];
                        if (firstEvt) setSelectedEventId(firstEvt.id);
                      }}
                    >
                      <div className="cal-day-header">
                        <span className="cal-day-number">{cell.dayNumber}</span>
                        {cell.isToday && <span className="today-chip">Hôm nay</span>}
                      </div>
                      <div className="cal-day-events">
                        {dayEvents.map(evt => {
                          const active = selectedEvent?.id === evt.id;
                          return (
                            <button
                              key={evt.id}
                              type="button"
                              className={`cal-event-pill ${categoryColor[evt.category] ?? 'cal-badge-blue'} ${active ? 'active' : ''}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedDate(cell.dateString);
                                setSelectedEventId(evt.id);
                              }}
                              title={`${evt.timeRange ? evt.timeRange + ': ' : ''}${evt.title}`}
                            >
                              {evt.timeRange && (
                                <strong style={{ marginRight: '4px' }}>
                                  {evt.timeRange.split('–')[0]?.trim()}
                                </strong>
                              )}
                              <span>{evt.title}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {viewMode === 'week' && (
            <div className="cal-month-table">
              <div className="cal-weekdays-header">
                <div>Thứ Hai (T2)</div>
                <div>Thứ Ba (T3)</div>
                <div>Thứ Tư (T4)</div>
                <div>Thứ Năm (T5)</div>
                <div>Thứ Sáu (T6)</div>
                <div>Thứ Bảy (T7)</div>
                <div>Chủ Nhật (CN)</div>
              </div>

              <div className="cal-days-grid" style={{ gridTemplateRows: '1fr' }}>
                {weekDays.map((cell, idx) => {
                  const dayEvents = events.filter(e => e.date === cell.dateString);
                  return (
                    <div
                      key={idx}
                      className={`cal-day-cell ${cell.inMonth ? 'in-month' : 'other-month'} ${cell.isToday ? 'today' : ''} ${selectedDate === cell.dateString ? 'selected' : ''}`}
                      style={{ minHeight: '320px' }}
                      onClick={() => {
                        setSelectedDate(cell.dateString);
                        const firstEvt = dayEvents[0];
                        if (firstEvt) setSelectedEventId(firstEvt.id);
                      }}
                    >
                      <div className="cal-day-header">
                        <span className="cal-day-number">{cell.dayNumber}</span>
                        {cell.isToday && <span className="today-chip">Hôm nay</span>}
                      </div>
                      <div className="cal-day-events">
                        {dayEvents.map(evt => {
                          const active = selectedEvent?.id === evt.id;
                          return (
                            <button
                              key={evt.id}
                              type="button"
                              className={`cal-event-pill ${categoryColor[evt.category] ?? 'cal-badge-blue'} ${active ? 'active' : ''}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedDate(cell.dateString);
                                setSelectedEventId(evt.id);
                              }}
                              title={`${evt.timeRange ? evt.timeRange + ': ' : ''}${evt.title}`}
                            >
                              {evt.timeRange && (
                                <strong style={{ marginRight: '4px' }}>
                                  {evt.timeRange.split('–')[0]?.trim()}
                                </strong>
                              )}
                              <span>{evt.title}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {viewMode === 'list' && (
            <div className="cal-list-view padded">
              <h3>
                Hoạt động tháng {currentYearMonth.month}/{currentYearMonth.year} ({listEvents.length})
              </h3>
              {listEvents.length === 0 ? (
                <p className="muted" style={{ padding: '24px 0' }}>
                  Không có sự kiện nào trong tháng {currentYearMonth.month}/{currentYearMonth.year}.
                </p>
              ) : (
                <div className="item-list">
                  {listEvents.map(evt => (
                    <div
                      key={evt.id}
                      tabIndex={0}
                      className={`cal-list-item ${selectedEvent?.id === evt.id ? 'selected' : ''}`}
                      onClick={() => setSelectedEventId(evt.id)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') setSelectedEventId(evt.id);
                      }}
                    >
                      <div className="actions">
                        <span className={`tag ${categoryColor[evt.category] ?? 'cal-badge-blue'}`}>
                          {categoryLabel[evt.category] ?? evt.category}
                        </span>
                        {evt.className && <span className="tag">{evt.className}</span>}
                        <span className="muted">{evt.date} · {evt.timeRange}</span>
                      </div>
                      <strong style={{ display: 'block', margin: '6px 0' }}>{evt.title}</strong>
                      {evt.description && <p className="muted" style={{ margin: 0 }}>{evt.description}</p>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: Selected Event Detail Panel */}
        <aside className="cal-detail-aside">
          {selectedEvent ? (
            <div className="card padded cal-detail-card">
              <div className="cal-detail-top">
                <span className={`tag ${categoryColor[selectedEvent.category] ?? 'cal-badge-blue'}`}>
                  {categoryLabel[selectedEvent.category] ?? selectedEvent.category}
                </span>
                {selectedEvent.className && <span className="tag">{selectedEvent.className}</span>}
              </div>

              <h3>{selectedEvent.title}</h3>
              {selectedEvent.description && <p className="muted">{selectedEvent.description}</p>}

              <dl className="details" style={{ margin: '16px 0' }}>
                <dt>Thời gian</dt>
                <dd>
                  <strong>{selectedEvent.date}</strong>
                  {selectedEvent.timeRange && <span> · {selectedEvent.timeRange}</span>}
                </dd>
                {selectedEvent.teacherName && (
                  <>
                    <dt>Giáo viên</dt>
                    <dd>{selectedEvent.teacherName}</dd>
                  </>
                )}
                {selectedEvent.location && (
                  <>
                    <dt>Địa điểm</dt>
                    <dd>{selectedEvent.location}</dd>
                  </>
                )}
              </dl>

              {/* Read-only Learning deadline notice */}
              {(selectedEvent.readOnly ||
                selectedEvent.category === 'ASSIGNMENT' ||
                selectedEvent.category === 'EXAM') && (
                <div className="notice" style={{ fontSize: '12px', margin: '12px 0' }}>
                  <Icon name="lock" /> Hạn nộp và bài kiểm tra thuộc phân hệ học tập ở chế độ chỉ đọc. Mở hoạt động tương ứng để xem theo quyền.
                </div>
              )}

              {/* Safe Role-aware Destination Link */}
              {safeActionHref && (
                <div style={{ marginTop: '16px' }}>
                  <Link
                    className="button primary"
                    style={{ width: '100%', textAlign: 'center' }}
                    href={safeActionHref}
                  >
                    Mở hoạt động liên quan →
                  </Link>
                </div>
              )}

              {/* Teacher Actions for Editable Core Events */}
              {isSelectedEventEditable && (
                <div className="cal-teacher-actions" style={{ marginTop: '16px', display: 'flex', gap: '8px' }}>
                  <button
                    className="button secondary small"
                    type="button"
                    style={{ flex: 1 }}
                    onClick={handleOpenEdit}
                  >
                    <Icon name="edit" /> Chỉnh sửa
                  </button>
                  <button
                    className="button danger small"
                    type="button"
                    onClick={handleOpenDelete}
                  >
                    <Icon name="trash" /> Xóa
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="card padded" style={{ textAlign: 'center' }}>
              <p className="muted">Chọn một sự kiện trên lịch để xem chi tiết.</p>
            </div>
          )}
        </aside>
      </div>

      {/* Teacher Create Event Dialog */}
      <Dialog
        busy={busy}
        open={createDialogOpen}
        title={isGlobal ? 'Thêm sự kiện lịch' : 'Thêm sự kiện lớp học'}
        onClose={() => setCreateDialogOpen(false)}
      >
        <form onSubmit={handleCreateEvent} className="form-stack">
          {(!params.classId || isGlobal) && assignedClasses.length > 0 && (
            <label htmlFor="evt-class">
              Lớp học phụ trách
              <select
                id="evt-class"
                required
                value={createClassId}
                onChange={e => setCreateClassId(e.target.value)}
              >
                {assignedClasses.map(cls => (
                  <option key={cls.id} value={cls.id}>
                    {cls.name}{cls.code ? ` (${cls.code})` : ''}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label htmlFor="evt-title">
            Tiêu đề sự kiện
            <input
              id="evt-title"
              required
              placeholder="Nhập tiêu đề sự kiện"
              value={newTitle}
              onChange={e => setNewTitle(e.target.value)}
            />
          </label>

          <label htmlFor="evt-date">
            Ngày diễn ra
            <input
              id="evt-date"
              type="date"
              required
              value={newDate}
              onChange={e => setNewDate(e.target.value)}
            />
          </label>

          <label htmlFor="evt-time">
            Khung giờ (Ví dụ: 07:00 – 09:15)
            <input
              id="evt-time"
              placeholder="07:00 – 09:15"
              value={newTimeRange}
              onChange={e => setNewTimeRange(e.target.value)}
            />
          </label>

          <label htmlFor="evt-desc">
            Ghi chú / Mô tả (tùy chọn)
            <textarea
              id="evt-desc"
              rows={3}
              placeholder="Nội dung chi tiết..."
              value={newDescription}
              onChange={e => setNewDescription(e.target.value)}
            />
          </label>

          <ErrorNotice message={formError} />

          <div className="actions">
            <button className="button" type="button" onClick={() => setCreateDialogOpen(false)}>
              Hủy
            </button>
            <button className="button primary" disabled={busy} type="submit">
              {busy ? 'Đang tạo…' : 'Lưu sự kiện'}
            </button>
          </div>
        </form>
      </Dialog>

      {/* Teacher Edit Event Dialog */}
      <Dialog
        busy={busy}
        open={editDialogOpen}
        title="Chỉnh sửa sự kiện lịch"
        onClose={() => setEditDialogOpen(false)}
      >
        <form onSubmit={handleUpdateEvent} className="form-stack">
          <label htmlFor="edit-title">
            Tiêu đề sự kiện
            <input
              id="edit-title"
              required
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
            />
          </label>

          {selectedEventSpansDays && <p className="notice">Sự kiện kéo dài nhiều ngày. Bạn có thể sửa tiêu đề và mô tả; ngày/giờ được giữ nguyên vì biểu mẫu chưa có ngày kết thúc.</p>}

          <label htmlFor="edit-date">
            Ngày diễn ra
            <input
              id="edit-date"
              type="date"
              required
              disabled={busy || selectedEventSpansDays}
              value={editDate}
              onChange={e => { setEditDate(e.target.value); setEditScheduleChanged(true); }}
            />
          </label>

          <label htmlFor="edit-time">
            Khung giờ
            <input
              id="edit-time"
              disabled={busy || selectedEventSpansDays}
              value={editTimeRange}
              onChange={e => { setEditTimeRange(e.target.value); setEditScheduleChanged(true); }}
            />
          </label>

          <label htmlFor="edit-desc">
            Mô tả
            <textarea
              id="edit-desc"
              rows={3}
              value={editDescription}
              onChange={e => setEditDescription(e.target.value)}
            />
          </label>

          {adapter.source === 'mock' && <label htmlFor="edit-location">
            Địa điểm
            <input
              id="edit-location"
              value={editLocation}
              onChange={e => setEditLocation(e.target.value)}
            />
          </label>}

          <ErrorNotice message={editError} />

          <div className="actions">
            <button className="button" type="button" onClick={() => setEditDialogOpen(false)}>
              Hủy
            </button>
            <button className="button primary" disabled={busy} type="submit">
              {busy ? 'Đang lưu…' : 'Cập nhật'}
            </button>
          </div>
        </form>
      </Dialog>

      {/* Teacher Delete Confirmation Dialog */}
      <Dialog
        busy={busy}
        open={deleteDialogOpen}
        title="Xác nhận xóa sự kiện"
        onClose={() => setDeleteDialogOpen(false)}
      >
        <div className="form-stack">
          <p>
            Bạn có chắc chắn muốn xóa sự kiện <strong>{selectedEvent?.title}</strong> khỏi lịch học không? Thao tác này không thể hoàn tác.
          </p>

          <ErrorNotice message={deleteError} />

          <div className="actions">
            <button className="button" type="button" onClick={() => setDeleteDialogOpen(false)}>
              Hủy
            </button>
            <button
              className="button danger"
              disabled={busy}
              type="button"
              onClick={handleDeleteEvent}
            >
              {busy ? 'Đang xóa…' : 'Xóa sự kiện'}
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
