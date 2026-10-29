import { routeHref } from '@/config/routes';
import { ApiError } from '../api/errors';
import type { HttpRequest } from '../api/http';
import type { CalendarEvent, ClassSummary, FeedComment, FeedPost, NotificationItem, Page, User, WorkspaceData } from '../domain';
import type { LiveIdentitySession } from './live-identity';

type Request = HttpRequest;
type RecordValue = Record<string, unknown>;

function invalid(): never {
  throw new ApiError('CONTRACT_MISMATCH', 'Dữ liệu máy chủ chưa đúng hợp đồng hiện tại. Vui lòng thử lại sau.', 502);
}

function record(value: unknown): RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as RecordValue : invalid();
}

function string(value: unknown): string {
  return typeof value === 'string' ? value : invalid();
}

function optionalString(value: unknown): string | undefined {
  return value === undefined || value === null ? undefined : string(value);
}

function validDate(value: unknown): Date {
  const parsed = new Date(string(value));
  if (!Number.isFinite(parsed.getTime())) return invalid();
  return parsed;
}

function uuidOrUndefined(value: unknown): string | undefined {
  const id = optionalString(value);
  if (id === undefined) return undefined;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return invalid();
  return id;
}

function page<T>(value: unknown, decode: (row: unknown) => T): Page<T> {
  const source = record(value);
  if (!Array.isArray(source.items)) return invalid();
  return { items: source.items.map(decode), next_cursor: optionalString(source.next_cursor) ?? null };
}

function decodeClass(value: unknown): ClassSummary {
  const source = record(value);
  const grade = source.grade_level;
  if (typeof grade !== 'number' || !Number.isInteger(grade) || grade < 6 || grade > 12) return invalid();
  if (!['ACTIVE', 'ARCHIVED'].includes(String(source.status))) return invalid();
  if (!['AUTO', 'MANUAL'].includes(String(source.enrollment_mode))) return invalid();
  const teachingRole = source.teaching_role;
  if (teachingRole !== undefined && teachingRole !== null && !['PRIMARY', 'ASSISTING'].includes(String(teachingRole))) return invalid();
  return {
    id: string(source.id),
    code: '',
    name: string(source.name),
    status: source.status as ClassSummary['status'],
    metadata: `Khối ${grade} · ${source.enrollment_mode === 'AUTO' ? 'Tự động' : 'Quản lý'}`,
    ...(teachingRole ? { teachingRole: teachingRole as ClassSummary['teachingRole'] } : {}),
  };
}

function decodeComment(value: unknown, postId: string, actor: User, canModerate = false): FeedComment {
  const source = record(value), author = record(source.author);
  const authorId = string(author.id);
  return {
    id: string(source.id),
    postId: string(source.post_id) || postId,
    authorId,
    authorName: optionalString(author.display_name) ?? 'Người dùng',
    content: string(source.body),
    createdAt: string(source.created_at),
    canDelete: authorId === actor.id || canModerate,
  };
}

function decodePost(value: unknown, actor: User, comments: FeedComment[] = [], commentsNextCursor: string | null = null, canModerate = false): FeedPost {
  const source = record(value), author = record(source.author);
  const authorId = string(author.id), classId = string(source.class_id);
  return {
    id: string(source.id),
    classId,
    authorId,
    authorName: optionalString(author.display_name) ?? 'Người dùng',
    content: string(source.body),
    createdAt: string(source.created_at),
    updatedAt: string(source.updated_at),
    canEdit: authorId === actor.id,
    canDelete: authorId === actor.id || canModerate,
    comments,
    commentsNextCursor,
  };
}

function localDate(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
}

function decodeCalendarEvent(value: unknown, className?: string): CalendarEvent {
  const source = record(value);
  const startsAt = validDate(source.starts_at), endsAt = validDate(source.ends_at);
  if (startsAt >= endsAt) return invalid();
  const origin = string(source.origin);
  if (!['CORE', 'LEARNING'].includes(origin)) return invalid();
  return {
    id: string(source.id),
    classId: string(source.class_id),
    className,
    title: string(source.title),
    description: optionalString(source.description),
    category: 'CLASS',
    start: startsAt.toISOString(),
    end: endsAt.toISOString(),
    date: localDate(startsAt),
    timeRange: `${startsAt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} – ${endsAt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`,
    readOnly: origin === 'LEARNING',
  };
}

const notificationCopy: Record<string, { title: string; content: string; category: NotificationItem['category']; target: 'feed' | 'calendar' | 'classes' | null }> = {
  CLASS_ENROLLMENT_CHANGED: { title: 'Danh sách lớp đã thay đổi', content: 'Thông tin ghi danh của lớp đã được cập nhật.', category: 'CLASS', target: 'classes' },
  CLASS_ENROLLMENT_MODE_CHANGED: { title: 'Chế độ ghi danh đã thay đổi', content: 'Chế độ ghi danh của lớp đã được cập nhật.', category: 'CLASS', target: 'classes' },
  CLASS_TEACHERS_CHANGED: { title: 'Phân công giáo viên đã thay đổi', content: 'Phân công giảng dạy của lớp đã được cập nhật.', category: 'CLASS', target: 'classes' },
  CLASS_STATUS_CHANGED: { title: 'Trạng thái lớp đã thay đổi', content: 'Trạng thái lớp học đã được cập nhật.', category: 'CLASS', target: 'classes' },
  CLASS_STUDENT_TRANSFERRED: { title: 'Thông tin chuyển lớp', content: 'Ghi danh lớp học của bạn đã được cập nhật.', category: 'CLASS', target: 'classes' },
  HOMEROOM_STUDENT_TRANSFERRED: { title: 'Thông tin lớp hành chính', content: 'Danh sách lớp hành chính của bạn đã được cập nhật.', category: 'CLASS', target: 'classes' },
  SOCIAL_POST_CREATED: { title: 'Bài viết mới', content: 'Có bài viết mới trong bảng tin lớp.', category: 'CLASS', target: 'feed' },
  SOCIAL_COMMENT_CREATED: { title: 'Bình luận mới', content: 'Có bình luận mới trong bảng tin lớp.', category: 'CLASS', target: 'feed' },
  CALENDAR_DEADLINE_CHANGED: { title: 'Lịch lớp học đã cập nhật', content: 'Thời hạn hoặc sự kiện học tập của lớp đã thay đổi.', category: 'ASSIGNMENT', target: 'calendar' },
};

function decodeNotification(value: unknown, actor: User, classNames: Map<string, string>): NotificationItem {
  const source = record(value), type = string(source.type), payload = record(source.payload_json);
  if (typeof source.read !== 'boolean') return invalid();
  const spec = notificationCopy[type] ?? { title: 'Thông báo mới', content: 'Bạn có một thông báo mới.', category: 'SYSTEM' as const, target: null };
  const classId = uuidOrUndefined(payload.class_id);
  const className = classId ? classNames.get(classId) : undefined;
  const rolePrefix = actor.roles.includes('LECTURER') ? '/teacher' : actor.roles.includes('STUDENT') ? '/student' : null;
  let targetHref: string | undefined;
  if (rolePrefix && classId && spec.target === 'feed') targetHref = routeHref(rolePrefix === '/teacher' ? 't.feed' : 's.feed', { classId }) ?? `${rolePrefix}/classes/${classId}/feed`;
  else if (rolePrefix && classId && spec.target === 'calendar') targetHref = routeHref(rolePrefix === '/teacher' ? 't.calendar' : 's.calendar', { classId }) ?? `${rolePrefix}/classes/${classId}/calendar`;
  else if (rolePrefix && spec.target === 'classes') targetHref = routeHref(rolePrefix === '/teacher' ? 't.classes' : 's.classes') ?? `${rolePrefix}/classes`;
  return {
    id: string(source.id),
    userId: actor.id,
    title: spec.title,
    content: className ? `${spec.content} (${className})` : spec.content,
    category: spec.category,
    createdAt: string(source.created_at),
    isRead: source.read,
    ...(classId ? { classId } : {}),
    ...(className ? { className } : {}),
    ...(targetHref ? { targetHref, targetLabel: spec.target === 'feed' ? 'Mở bảng tin' : spec.target === 'calendar' ? 'Mở lịch' : 'Mở danh sách lớp' } : {}),
  };
}

async function allPages<T>(request: Request, id: 'classes' | 'calendarEvents', decode: (item: unknown) => T, pathParams?: Record<string, string>, query: Record<string, string | number | undefined> = {}, signal?: AbortSignal): Promise<T[]> {
  const result: T[] = [];
  let cursor: string | undefined;
  for (let pageNumber = 0; pageNumber < 20; pageNumber++) {
    const response = await request(id, { pathParams, query: { ...query, limit: 100, cursor }, signal });
    const next = page(response, decode);
    result.push(...next.items);
    if (!next.next_cursor) return result;
    cursor = next.next_cursor;
  }
  throw new ApiError('PAGE_LIMIT', 'Dữ liệu có quá nhiều trang để tải an toàn. Hãy thu hẹp phạm vi.', 413);
}

async function allNotificationPages(request: Request, signal?: AbortSignal): Promise<{ items: unknown[]; unreadCount: number }> {
  const items: unknown[] = [];
  let cursor: string | undefined, unreadCount = 0;
  for (let pageNumber = 0; pageNumber < 20; pageNumber++) {
    const source = record(await request('notifications', { query: { limit: 100, cursor }, signal }));
    if (!Array.isArray(source.items) || typeof source.unread_count !== 'number'
      || !Number.isInteger(source.unread_count) || source.unread_count < 0) return invalid();
    items.push(...source.items);
    unreadCount = source.unread_count;
    const next = optionalString(source.next_cursor);
    if (!next) return { items, unreadCount };
    cursor = next;
  }
  throw new ApiError('PAGE_LIMIT', 'Thông báo có quá nhiều trang để tải an toàn. Hãy tải lại sau.', 413);
}

function toIso(value: string | undefined): string {
  if (!value) throw new ApiError('VALIDATION_ERROR', 'Cần có thời gian bắt đầu và kết thúc.', 422);
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new ApiError('VALIDATION_ERROR', 'Thời gian sự kiện không hợp lệ.', 422);
  return date.toISOString();
}

export function createLiveCore(session: LiveIdentitySession) {
  async function actor(): Promise<User> {
    const current = session.currentUser() ?? await session.identity.restore();
    if (!current) throw new ApiError('UNAUTHENTICATED', 'Phiên đăng nhập đã hết hạn.', 401);
    return current;
  }

  async function readClasses(signal?: AbortSignal) {
    return session.authenticated(request => allPages(request, 'classes', decodeClass, undefined, {}, signal));
  }

  async function readClass(classId: string, signal?: AbortSignal) {
    return session.authenticated(async request => decodeClass(await request('classDetail', { pathParams: { classId }, signal })));
  }

  async function readPosts(classId: string, cursor?: string, signal?: AbortSignal): Promise<Page<FeedPost>> {
    return session.authenticated(async request => {
      const current = await actor();
      const classData = record(await request('classDetail', { pathParams: { classId }, signal }));
      const canModerate = classData.teaching_role === 'PRIMARY' || classData.teaching_role === 'ASSISTING';
      const posts = page(await request('posts', { pathParams: { classId }, query: { limit: 20, cursor }, signal }), item => item);
      const items = await Promise.all(posts.items.map(async value => {
        const post = record(value);
        const postId = string(post.id);
        const comments = page(await request('comments', { pathParams: { classId, postId }, query: { limit: 20 }, signal }), item => decodeComment(item, postId, current, canModerate));
        return decodePost(value, current, comments.items, comments.next_cursor, canModerate);
      }));
      return { items, next_cursor: posts.next_cursor };
    });
  }

  async function readComments(classId: string, postId: string, cursor?: string, signal?: AbortSignal): Promise<Page<FeedComment>> {
    return session.authenticated(async request => {
      const current = await actor();
      const classData = record(await request('classDetail', { pathParams: { classId }, signal }));
      const canModerate = classData.teaching_role === 'PRIMARY' || classData.teaching_role === 'ASSISTING';
      return page(await request('comments', { pathParams: { classId, postId }, query: { limit: 20, cursor }, signal }), item => decodeComment(item, postId, current, canModerate));
    });
  }

  async function readEvents(classId: string, className?: string, signal?: AbortSignal, range?: { from: string; to: string }): Promise<CalendarEvent[]> {
    return session.authenticated(request => allPages(request, 'calendarEvents', item => decodeCalendarEvent(item, className), { classId }, range, signal));
  }

  async function readRecentClassPosts(classes: ClassSummary[], current: User, signal?: AbortSignal) {
    const active = classes.filter(item => item.status === 'ACTIVE');
    return session.authenticated(async request => Promise.all(active.map(async cls => {
      const snapshot = page(await request('posts', { pathParams: { classId: cls.id }, query: { limit: 1 }, signal }), item => item);
      const first = snapshot.items[0];
      if (!first) return null;
      const post = decodePost(first, current);
      return post.authorId === current.id ? null : {
        id: post.id,
        studentName: post.authorName,
        className: cls.name,
        classId: cls.id,
        createdAt: post.createdAt,
        content: post.content,
      };
    }))).then(items => items.filter((item): item is NonNullable<typeof item> => item !== null));
  }

  function localDayRange() {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    return { from: start.toISOString(), to: end.toISOString() };
  }

  async function loadWorkspace(routeId: string, params: Record<string, string>, signal?: AbortSignal): Promise<WorkspaceData> {
    const current = await actor();
    const pendingCapabilities = ['Class history', 'Document', 'Learning', 'AI Tutor', 'Learner Intelligence'];
    if (['s.home', 's.classes', 't.home', 't.classes'].includes(routeId)) {
      const classes = await readClasses(signal);
      if (routeId === 's.home') return { kind: 'ready', classes, pendingCapabilities, studentHome: { activeClasses: classes.filter(row => row.status === 'ACTIVE'), upcomingTasks: [], recentStudies: [], tutorSuggestions: [] } };
      if (routeId === 't.home') {
        const range = localDayRange();
        const [todaySchedule, recentDiscussions] = await Promise.all([
          Promise.all(classes.filter(cls => cls.status === 'ACTIVE').map(cls => readEvents(cls.id, cls.name, signal, range))).then(rows => rows.flat()),
          readRecentClassPosts(classes, current, signal),
        ]);
        return { kind: 'ready', classes, pendingCapabilities, teacherHome: { assignedClasses: classes, recentDiscussions, todaySchedule } };
      }
      return { kind: 'ready', classes, pendingCapabilities };
    }
    if (routeId === 's.overview' || routeId === 't.overview') {
      const classId = params.classId;
      if (!classId) return { kind: 'unavailable', message: 'Thiếu mã lớp trong đường dẫn.' };
      return { kind: 'ready', classSummary: await readClass(classId, signal), pendingCapabilities };
    }
    if (routeId === 's.feed' || routeId === 't.feed') {
      const classId = params.classId;
      if (!classId) return { kind: 'unavailable', message: 'Thiếu mã lớp trong đường dẫn.' };
      const [classSummary, posts] = await Promise.all([readClass(classId, signal), readPosts(classId, undefined, signal)]);
      return { kind: 'ready', classSummary, feedPosts: posts.items, feedNextCursor: posts.next_cursor, pendingCapabilities };
    }
    if (routeId === 's.calendar' || routeId === 't.calendar') {
      const classId = params.classId;
      if (!classId) return { kind: 'unavailable', message: 'Thiếu mã lớp trong đường dẫn.' };
      const [classSummary, events] = await Promise.all([readClass(classId, signal), readEvents(classId, undefined, signal)]);
      return { kind: 'ready', classSummary, calendarEvents: events, displayDate: new Date().toISOString(), pendingCapabilities };
    }
    if (routeId === 'account.calendar') {
      if (current.roles.includes('ADMIN')) return { kind: 'unavailable', message: 'Lịch tổng hợp chỉ hiển thị các lớp đang được ghi danh hoặc phân công.' };
      const classes = await readClasses(signal);
      const events = (await Promise.all(classes.map(cls => readEvents(cls.id, cls.name, signal)))).flat();
      return { kind: 'ready', classes, calendarEvents: events, displayDate: new Date().toISOString(), pendingCapabilities };
    }
    if (routeId === 'account.notifications') {
      const [classes, inbox] = await Promise.all([
        readClasses(signal),
        session.authenticated(request => allNotificationPages(request, signal)),
      ]);
      const classNames = new Map(classes.map(cls => [cls.id, cls.name]));
      const notifications = inbox.items.map(item => decodeNotification(item, current, classNames));
      return { kind: 'ready', notifications, notificationUnreadCount: inbox.unreadCount, pendingCapabilities };
    }
    return { kind: 'unavailable', message: 'Luồng này chưa có adapter Core được triển khai.' };
  }

  return {
    identity: session.identity,
    social: {
      listPosts: readPosts,
      listComments: readComments,
      async createPost(classId: string, content: string) {
        return session.authenticated(async request => decodePost(await request('createPost', { pathParams: { classId }, body: { body: content } }), await actor()), true);
      },
      async updatePost(classId: string, postId: string, content: string) {
        return session.authenticated(async request => decodePost(await request('updatePost', { pathParams: { classId, postId }, body: { body: content } }), await actor()), true);
      },
      async deletePost(classId: string, postId: string) {
        await session.authenticated(request => request('deletePost', { pathParams: { classId, postId } }), true);
      },
      async createComment(classId: string, postId: string, content: string) {
        return session.authenticated(async request => decodeComment(await request('createComment', { pathParams: { classId, postId }, body: { body: content } }), postId, await actor()), true);
      },
      async deleteComment(classId: string, postId: string, commentId: string) {
        await session.authenticated(request => request('deleteComment', { pathParams: { classId, postId, commentId } }), true);
      },
    },
    calendar: {
      async createEvent(event: Omit<CalendarEvent, 'id'>) {
        const classId = event.classId;
        if (!classId) throw new ApiError('VALIDATION_ERROR', 'Hãy chọn lớp trước khi tạo sự kiện.', 422);
        const response = await session.authenticated(request => request('createCalendarEvent', { pathParams: { classId }, body: { title: event.title, description: event.description ?? null, starts_at: toIso(event.start), ends_at: toIso(event.end) } }), true);
        return decodeCalendarEvent(response, event.className);
      },
      async updateEvent(id: string, patch: Partial<CalendarEvent>, classId?: string) {
        if (!classId) throw new ApiError('VALIDATION_ERROR', 'Không xác định được lớp sở hữu sự kiện.', 422);
        const body: Record<string, unknown> = {};
        if (patch.title !== undefined) body.title = patch.title;
        if ('description' in patch) body.description = patch.description?.trim() || null;
        if (patch.start !== undefined) body.starts_at = toIso(patch.start);
        if (patch.end !== undefined) body.ends_at = toIso(patch.end);
        const response = await session.authenticated(request => request('updateCalendarEvent', { pathParams: { classId, eventId: id }, body }), true);
        return decodeCalendarEvent(response, patch.className);
      },
      async deleteEvent(id: string, classId?: string) {
        if (!classId) throw new ApiError('VALIDATION_ERROR', 'Không xác định được lớp sở hữu sự kiện.', 422);
        await session.authenticated(request => request('deleteCalendarEvent', { pathParams: { classId, eventId: id } }), true);
      },
    },
    notifications: {
      async markAsRead(id: string) {
        await session.authenticated(request => request('markNotificationRead', { pathParams: { notificationId: id } }), true);
      },
      async markAllAsRead() {
        await session.authenticated(request => request('markAllNotificationsRead'), true);
      },
    },
    workspace: { load: loadWorkspace },
  };
}
