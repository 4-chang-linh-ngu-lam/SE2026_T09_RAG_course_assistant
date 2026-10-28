import { ApiError } from '../api/errors';
import type { HttpRequest } from '../api/http';
import type { ClassSummary, Page, Role, User } from '../domain';
import type {
  AdminReason,
  CatalogEntry,
  CatalogKind,
  ClassMember,
  ClassroomAdminPort,
  ClassroomAdminWorkspace,
  ClassroomChangePreview,
  EnrollmentMode,
  Homeroom,
  ManagedClass,
} from '../classroom-admin';
import type { LiveIdentitySession } from './live-identity';

type Row = Record<string, unknown>;
type Request = HttpRequest;
type Catalog = {
  courses: Row[];
  academic_years: Row[];
  semesters: Row[];
  homerooms: Row[];
  grades: number[];
};
type UserRow = User & { revision: number; createdAt: string };
type ClassRow = { id: string; name: string; status: 'ACTIVE' | 'ARCHIVED'; version: number; courseId: string; yearId: string; semesterId: string; homeroomId: string | null; grade: number; mode: EnrollmentMode };
type PendingChange =
  | { kind: 'HOMEROOM'; preview: ClassroomChangePreview; sourceId: string; sourceVersion: number; sourceIds: string[]; targetIds: string[]; destinationId?: string; destinationVersion?: number; destinationIds?: string[]; transferStudentId?: string }
  | { kind: 'ENROLLMENT'; preview: ClassroomChangePreview; classId: string; expectedClassVersion: number; currentMode: EnrollmentMode; targetMode: EnrollmentMode; targetIds: string[]; expectedRosterVersion?: number };

function invalid(): never {
  throw new ApiError('CONTRACT_MISMATCH', 'Dữ liệu quản trị lớp chưa đúng hợp đồng Core.', 502);
}

function row(value: unknown): Row {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Row : invalid();
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : invalid();
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function integer(value: unknown, min = 0): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min ? value : invalid();
}

function uuid(value: unknown): string {
  const id = text(value);
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) ? id : invalid();
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : invalid();
}

function decodeCatalog(value: unknown): Catalog {
  const source = row(value);
  return {
    courses: list(source.courses).map(row),
    academic_years: list(source.academic_years).map(row),
    semesters: list(source.semesters).map(row),
    homerooms: list(source.homerooms).map(row),
    grades: list(source.grades).map(value => integer(value, 6)),
  };
}

function decodeUser(value: unknown): UserRow {
  const source = row(value);
  const roles = list(source.roles).map(role => text(role));
  if (!roles.length || !roles.every(role => ['ADMIN', 'LECTURER', 'STUDENT'].includes(role))) return invalid();
  if (!['ACTIVE', 'PENDING_VERIFICATION', 'LOCKED'].includes(String(source.status))) return invalid();
  return {
    id: uuid(source.id),
    email: nullableText(source.email),
    username: nullableText(source.username),
    school_id: nullableText(source.school_id),
    display_name: nullableText(source.display_name),
    status: source.status as User['status'],
    roles: roles as Role[],
    revision: integer(source.revision, 0),
    createdAt: text(source.created_at),
  };
}

function decodePage<T>(value: unknown, decode: (item: unknown) => T): Page<T> {
  const source = row(value);
  return {
    items: list(source.items).map(decode),
    next_cursor: source.next_cursor === null || source.next_cursor === undefined ? null : text(source.next_cursor),
  };
}

async function allPages<T>(request: Request, operation: 'classes' | 'adminUsers', decode: (value: unknown) => T, signal?: AbortSignal): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  for (let count = 0; count < 20; count++) {
    const page = decodePage(await request(operation, { query: { limit: 100, cursor }, signal }), decode);
    items.push(...page.items);
    if (!page.next_cursor) return items;
    cursor = page.next_cursor;
  }
  throw new ApiError('PAGE_LIMIT', 'Dữ liệu trường học có quá nhiều trang để tải an toàn. Hãy thu hẹp danh sách.', 413);
}

async function mapLimited<T, R>(items: T[], limit: number, run: (item: T) => Promise<R>): Promise<R[]> {
  const result = new Array<R>(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      result[index] = await run(items[index]);
    }
  }));
  return result;
}

function catalogEntries(catalog: Catalog): CatalogEntry[] {
  return [
    ...catalog.academic_years.map(value => ({ id: uuid(value.id), kind: 'YEAR' as const, name: text(value.label), revision: 1 })),
    ...catalog.semesters.map(value => ({ id: uuid(value.id), kind: 'SEMESTER' as const, name: text(value.name), revision: 1, yearId: uuid(value.academic_year_id) })),
    ...catalog.grades.map(grade => ({ id: `grade-${grade}`, kind: 'GRADE' as const, name: `Khối ${grade}`, revision: 1, grade })),
    ...catalog.courses.map(value => ({ id: uuid(value.id), kind: 'COURSE' as const, name: text(value.name), revision: 1, code: text(value.code) })),
  ];
}

function decodeClassRow(value: unknown): ClassRow {
  const source = row(value);
  if (!['ACTIVE', 'ARCHIVED'].includes(String(source.status)) || !['AUTO', 'MANUAL'].includes(String(source.enrollment_mode))) return invalid();
  return {
    id: uuid(source.id),
    name: text(source.name),
    status: source.status as ClassRow['status'],
    version: integer(source.version, 1),
    courseId: uuid(source.course_id),
    yearId: uuid(source.academic_year_id),
    semesterId: uuid(source.semester_id),
    homeroomId: source.homeroom_class_id === null ? null : uuid(source.homeroom_class_id),
    grade: integer(source.grade_level, 6),
    mode: source.enrollment_mode as EnrollmentMode,
  };
}

function decodeRoster(value: unknown): { id: string; studentIds: string[]; version: number } {
  const source = row(value);
  return {
    id: uuid(source.homeroom_class_id),
    studentIds: list(source.student_ids).map(uuid),
    version: integer(source.roster_version, 1),
  };
}

function decodeManagement(value: unknown) {
  const source = row(value), subjectClass = decodeClassRow(source.subject_class);
  const teachingAssignments = list(source.teaching_assignments).map(item => {
    const assignment = row(item);
    if (!['PRIMARY', 'ASSISTING'].includes(String(assignment.role))) return invalid();
    return { lecturerId: uuid(assignment.lecturer_id), role: assignment.role as 'PRIMARY' | 'ASSISTING' };
  });
  const members: ClassMember[] = list(source.members).map(item => {
    const member = row(item);
    if (member.status !== 'ACTIVE' || !['AUTO', 'MANUAL'].includes(String(member.source))) return invalid();
    return { userId: uuid(member.student_id), status: 'ACTIVE', source: member.source as ClassMember['source'] };
  });
  if (teachingAssignments.filter(item => item.role === 'PRIMARY').length !== 1) return invalid();
  return { subjectClass, teachingAssignments, members };
}

function mapManagedClass(
  management: ReturnType<typeof decodeManagement>,
  catalog: Catalog,
  userById: Map<string, UserRow>,
): ManagedClass {
  const source = management.subjectClass;
  const course = catalog.courses.map(row).find(value => value.id === source.courseId);
  const primary = management.teachingAssignments.find(item => item.role === 'PRIMARY');
  const primaryUser = primary ? userById.get(primary.lecturerId) : undefined;
  const yearLabel = catalog.academic_years.map(row).find(value => value.id === source.yearId)?.label;
  const semesterName = catalog.semesters.map(row).find(value => value.id === source.semesterId)?.name;
  const summary: ClassSummary = {
    id: source.id,
    code: course ? text(course.code) : '',
    name: source.name,
    status: source.status,
    metadata: [`Khối ${source.grade}`, source.mode === 'AUTO' ? 'AUTO' : 'MANUAL', yearLabel, semesterName].filter(Boolean).join(' · '),
    teacherName: primaryUser?.display_name ?? primaryUser?.email ?? 'Chưa phân công',
    studentCount: management.members.length,
  };
  return {
    summary,
    revision: source.version,
    courseId: source.courseId,
    yearId: source.yearId,
    semesterId: source.semesterId,
    grade: source.grade,
    homeroomId: source.homeroomId,
    mode: source.mode,
    primaryTeacherId: primary?.lecturerId ?? null,
    assistingTeacherIds: management.teachingAssignments.filter(item => item.role === 'ASSISTING').map(item => item.lecturerId),
    members: management.members,
    manualIncludes: [],
    manualExcludes: [],
  };
}

function rosterEqual(left: string[], right: string[]) {
  return [...left].sort().join(':') === [...right].sort().join(':');
}

function reasonCodes(): ClassroomAdminWorkspace['reasonCodes'] {
  return [
    { value: 'ADMIN_INTERVENTION', label: 'Can thiệp của quản trị viên' },
    { value: 'USER_REQUEST', label: 'Yêu cầu người dùng' },
    { value: 'POLICY_VIOLATION', label: 'Vi phạm chính sách' },
  ];
}

export function createLiveClassroomAdminPort(session: LiveIdentitySession): ClassroomAdminPort {
  let workspace: ClassroomAdminWorkspace | null = null;
  const pending = new Map<string, PendingChange>();

  function remember(change: PendingChange) {
    pending.set(change.preview.id, change);
    while (pending.size > 50) pending.delete(pending.keys().next().value as string);
  }

  function requireWorkspace(): ClassroomAdminWorkspace {
    if (!workspace) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Hãy tải lại trang quản trị trước khi tiếp tục.', 409);
    return workspace;
  }

  async function requireAdmin() {
    const actor = session.currentUser() ?? await session.identity.restore();
    if (!actor) throw new ApiError('UNAUTHENTICATED', 'Phiên đăng nhập đã hết hạn.', 401);
    if (!actor.roles.includes('ADMIN') || actor.status !== 'ACTIVE') throw new ApiError('FORBIDDEN', 'Chỉ quản trị viên đang hoạt động mới được quản lý lớp.', 403);
  }

  async function load(routeId: string, params: Record<string, string>, signal?: AbortSignal): Promise<ClassroomAdminWorkspace> {
    await requireAdmin();
    const loaded = await session.authenticated(async request => {
      const catalog = decodeCatalog(await request('adminCatalog', { signal }));
      const [users, classRows] = await Promise.all([
        allPages(request, 'adminUsers', decodeUser, signal),
        allPages(request, 'classes', decodeClassRow, signal),
      ]);
      const userById = new Map(users.map(user => [user.id, user]));
      const managementRows = await mapLimited(classRows, 5, async item => decodeManagement(await request('adminClassManagement', { pathParams: { classId: item.id }, signal })));
      const managedClasses = managementRows.map(item => mapManagedClass(item, catalog, userById));
      const rooms = await mapLimited(catalog.homerooms, 5, async raw => {
        const homeroomId = uuid(raw.id);
        const roster = decodeRoster(await request('adminHomeroomRoster', { pathParams: { homeroomId }, signal }));
        return {
          id: homeroomId,
          name: text(raw.name),
          grade: integer(raw.grade_level, 6),
          yearId: uuid(raw.academic_year_id),
          revision: roster.version,
          studentIds: roster.studentIds,
        } satisfies Homeroom;
      });
      const students = users.filter(user => user.status === 'ACTIVE' && user.roles.includes('STUDENT'));
      const teachers = users.filter(user => user.status === 'ACTIVE' && user.roles.includes('LECTURER'));
      const selectedClassId = params.classId;
      const selectedHomeroomId = params.homeroomId;
      return {
        revision: Math.max(0, ...managedClasses.map(item => item.revision), ...rooms.map(item => item.revision)),
        catalog: catalogEntries(catalog),
        homerooms: rooms,
        classes: managedClasses,
        students,
        teachers,
        homeroom: selectedHomeroomId ? rooms.find(item => item.id === selectedHomeroomId) : undefined,
        subjectClass: selectedClassId ? managedClasses.find(item => item.summary.id === selectedClassId) : undefined,
        auditEvents: [],
        historyAvailable: false,
        reasonCodes: reasonCodes(),
        policyNote: 'Core áp dụng quyền theo trường và lớp ở máy chủ. AUTO đồng bộ chính xác roster lớp hành chính; MANUAL dùng danh sách do Admin xác nhận. Lịch sử audit chi tiết chưa được nối vào màn hình này.',
      } satisfies ClassroomAdminWorkspace;
    });
    workspace = loaded;
    return loaded;
  }

  async function freshRoster(request: Request, homeroomId: string, signal?: AbortSignal) {
    return decodeRoster(await request('adminHomeroomRoster', { pathParams: { homeroomId }, signal }));
  }

  function homeroomImpact(sourceId: string, targetIds: string[], sourceCurrentIds: string[], destination?: { id: string; currentIds: string[]; targetIds: string[] }) {
    const base = requireWorkspace();
    const affectedIds = new Set([sourceId, ...(destination ? [destination.id] : [])]);
    return base.classes.filter(item => item.mode === 'AUTO' && item.homeroomId && affectedIds.has(item.homeroomId)).map(item => {
      const roomIds = item.homeroomId === sourceId
        ? targetIds
        : destination?.targetIds ?? [];
      const currentRoomIds = item.homeroomId === sourceId
        ? sourceCurrentIds
        : destination?.currentIds ?? [];
      const members = item.members.map(member => member.userId);
      const targetSet = new Set(roomIds);
      const addedIds = [...targetSet].filter(id => !members.includes(id));
      const endedIds = members.filter(id => !targetSet.has(id));
      return { classId: item.summary.id, className: item.summary.name, currentCount: members.length, projectedCount: Math.max(0, members.length + addedIds.length - endedIds.length) };
    });
  }

  return {
    load,
    async saveCatalog(input) {
      await requireAdmin();
      if (input.kind !== 'COURSE') throw new ApiError('CAPABILITY_UNAVAILABLE', 'Core hiện tạo năm học và học kỳ cùng lúc với lớp hành chính hoặc lớp môn học; khối 6–12 là danh mục cố định.', 503);
      if (input.id) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Core chưa có API sửa môn học đã tạo.', 503);
      const created = row(await session.authenticated(request => request('adminCreateCourse', {
        body: { code: input.code, name: input.name },
        headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
      }), true));
      return { id: uuid(created.id), kind: 'COURSE', name: text(created.name), code: text(created.code), revision: 1 };
    },
    async createHomeroom(input) {
      await requireAdmin();
      const current = requireWorkspace();
      const year = current.catalog.find(item => item.id === input.yearId && item.kind === 'YEAR');
      const academicYear = year?.name ?? input.yearId;
      const created = row(await session.authenticated(request => request('adminCreateHomeroom', {
        body: { name: input.name, academic_year: academicYear, grade_level: input.grade },
        headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
      }), true));
      return { id: uuid(created.id), name: text(created.name), grade: integer(created.grade_level, 6), yearId: uuid(created.academic_year_id), revision: integer(created.roster_version, 1), studentIds: [] };
    },
    async previewHomeroomRoster(input) {
      await requireAdmin();
      const id = crypto.randomUUID();
      const preview = await session.authenticated(async request => {
        const source = await freshRoster(request, input.homeroomId);
        if (source.version !== input.revision) throw new ApiError('REQUEST_FAILED', 'Danh sách lớp hành chính đã đổi. Tải lại trước khi xem trước.', 409);
        const current = requireWorkspace().homerooms.find(item => item.id === input.homeroomId);
        if (!current) throw new ApiError('NOT_FOUND', 'Không tìm thấy lớp hành chính trong trường hiện tại.', 404);
        if (input.destinationHomeroomId) {
          if (input.studentIds.length !== 1) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Core hiện chuyển từng học sinh trong một transaction. Hãy chọn đúng một học sinh mỗi lần.', 409);
          const destination = await freshRoster(request, input.destinationHomeroomId);
          const target = requireWorkspace().homerooms.find(item => item.id === input.destinationHomeroomId);
          if (!target || target.grade !== current.grade || target.yearId !== current.yearId) throw new ApiError('VALIDATION_ERROR', 'Lớp đích phải cùng năm học và khối.', 422);
          if (!source.studentIds.includes(input.studentIds[0]) || destination.studentIds.includes(input.studentIds[0])) throw new ApiError('REQUEST_FAILED', 'Roster đã đổi. Tải lại trước khi chuyển học sinh.', 409);
          const moved = input.studentIds[0];
          const destinationNext = [...destination.studentIds, moved];
          const sourceNext = source.studentIds.filter(studentId => studentId !== moved);
          return {
            preview: { id, kind: 'HOMEROOM' as const, resourceId: current.id, revision: source.version, currentCount: source.studentIds.length, projectedCount: sourceNext.length, addedIds: [moved], endedIds: [moved], status: 'PREVIEW' as const, impact: homeroomImpact(current.id, sourceNext, source.studentIds, { id: target.id, currentIds: destination.studentIds, targetIds: destinationNext }), policyNote: 'Học sinh được chuyển nguyên tử giữa hai lớp cùng năm học và khối. Các lớp AUTO của nguồn và đích đồng bộ trong cùng thao tác; lịch sử lớp môn học được giữ.' },
            change: { kind: 'HOMEROOM' as const, preview: undefined, sourceId: current.id, sourceVersion: source.version, sourceIds: source.studentIds, targetIds: sourceNext, destinationId: target.id, destinationVersion: destination.version, destinationIds: destination.studentIds, transferStudentId: moved },
          };
        }
        const targetIds = [...new Set(input.studentIds)];
        const targetSet = new Set(targetIds);
        const addedIds = targetIds.filter(studentId => !source.studentIds.includes(studentId));
        const endedIds = source.studentIds.filter(studentId => !targetSet.has(studentId));
        return {
          preview: { id, kind: 'HOMEROOM' as const, resourceId: current.id, revision: source.version, currentCount: source.studentIds.length, projectedCount: targetIds.length, addedIds, endedIds, status: 'PREVIEW' as const, impact: homeroomImpact(current.id, targetIds, source.studentIds), policyNote: 'Danh sách sẽ được thay trong một transaction. Các lớp AUTO đồng bộ theo roster mới; lớp MANUAL giữ nguyên danh sách. Học sinh bỏ khỏi roster sẽ kết thúc ghi danh AUTO, lịch sử được giữ.' },
          change: { kind: 'HOMEROOM' as const, preview: undefined, sourceId: current.id, sourceVersion: source.version, sourceIds: source.studentIds, targetIds },
        };
      });
      const complete = { ...preview.preview, id };
      remember({ ...preview.change, preview: complete } as PendingChange);
      return complete;
    },
    async confirmHomeroomRoster(input) {
      await requireAdmin();
      const change = pending.get(input.previewId);
      if (!change || change.kind !== 'HOMEROOM') throw new ApiError('CAPABILITY_UNAVAILABLE', 'Bản xem trước lớp hành chính không còn trong phiên. Hãy tải lại và xem trước lần nữa.', 410);
      if (change.transferStudentId && change.destinationId && change.destinationVersion !== undefined) {
        await session.authenticated(request => request('adminTransferHomeroomStudent', {
          pathParams: { homeroomId: change.sourceId, studentId: change.transferStudentId! },
          body: { destination_homeroom_id: change.destinationId, expected_source_roster_version: change.sourceVersion, expected_destination_roster_version: change.destinationVersion },
          headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
        }), true);
      } else {
        await session.authenticated(request => request('adminSetHomeroomRoster', {
          pathParams: { homeroomId: change.sourceId },
          body: { student_ids: change.targetIds, expected_roster_version: change.sourceVersion },
          headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
        }), true);
      }
      pending.delete(input.previewId);
      return { ...change.preview, status: 'APPLIED' };
    },
    async createClass(input) {
      await requireAdmin();
      const current = requireWorkspace();
      const savedYear = current.catalog.find(item => item.id === input.yearId && item.kind === 'YEAR');
      const savedSemester = current.catalog.find(item => item.id === input.semesterId && item.kind === 'SEMESTER');
      const course = current.catalog.find(item => item.id === input.courseId && item.kind === 'COURSE');
      const year = savedYear?.name ?? input.yearId.trim();
      const semester = savedSemester?.name ?? input.semesterId.trim();
      if (!year || !semester || !course || !input.primaryTeacherId) throw new ApiError('VALIDATION_ERROR', 'Cần chọn năm học, học kỳ, môn và giáo viên chính hợp lệ.', 422);
      const createdClass = await session.authenticated(async request => {
        const created = await request('adminCreateClass', {
          body: {
            course_id: input.courseId,
            name: input.name,
            academic_year: year,
            semester,
            grade_level: input.grade,
            homeroom_class_id: input.homeroomId,
            enrollment_mode: input.mode,
            primary_lecturer_id: input.primaryTeacherId,
            assisting_lecturer_ids: input.assistingTeacherIds,
          },
          headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
        });
        return decodeClassRow(created);
      }, true);
      const value = {
        subjectClass: createdClass,
        teachingAssignments: [
          { lecturerId: input.primaryTeacherId, role: 'PRIMARY' as const },
          ...input.assistingTeacherIds.map(lecturerId => ({ lecturerId, role: 'ASSISTING' as const })),
        ],
        members: [],
      };
      return mapManagedClass(value, {
        courses: current.catalog.filter(item => item.kind === 'COURSE').map(item => ({ id: item.id, code: item.code, name: item.name })),
        academic_years: [...current.catalog.filter(item => item.kind === 'YEAR').map(item => ({ id: item.id, label: item.name })), ...(savedYear ? [] : [{ id: value.subjectClass.yearId, label: year }])],
        semesters: [...current.catalog.filter(item => item.kind === 'SEMESTER').map(item => ({ id: item.id, academic_year_id: item.yearId, name: item.name })), ...(savedSemester ? [] : [{ id: value.subjectClass.semesterId, academic_year_id: value.subjectClass.yearId, name: semester }])],
        homerooms: [], grades: [],
      }, new Map([...current.students, ...current.teachers].map(user => [user.id, { ...user, revision: 0, createdAt: '' }])));
    },
    async saveClassSettings(input) {
      await requireAdmin();
      const current = requireWorkspace();
      const managed = current.classes.find(item => item.summary.id === input.classId);
      if (!managed) throw new ApiError('NOT_FOUND', 'Không tìm thấy lớp môn học trong trường hiện tại.', 404);
      if (input.name !== managed.summary.name) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Core chưa có API đổi tên lớp đã tạo; hiện chỉ có thể cập nhật phân công giáo viên.', 503);
      return session.authenticated(async request => {
        await request('adminSetTeachingAssignments', {
          pathParams: { classId: input.classId },
          body: { primary_lecturer_id: input.primaryTeacherId, assisting_lecturer_ids: input.assistingTeacherIds, expected_class_version: input.revision },
          headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
        });
        const updated = decodeManagement(await request('adminClassManagement', { pathParams: { classId: input.classId } }));
        return mapManagedClass(updated, {
          courses: current.catalog.filter(item => item.kind === 'COURSE').map(item => ({ id: item.id, code: item.code, name: item.name })),
          academic_years: current.catalog.filter(item => item.kind === 'YEAR').map(item => ({ id: item.id, label: item.name })),
          semesters: current.catalog.filter(item => item.kind === 'SEMESTER').map(item => ({ id: item.id, academic_year_id: item.yearId, name: item.name })),
          homerooms: [], grades: [],
        }, new Map([...current.students, ...current.teachers].map(user => [user.id, { ...user, revision: 0, createdAt: '' }])));
      }, true);
    },
    async previewEnrollment(input) {
      await requireAdmin();
      if (input.manualIncludes?.length || input.manualExcludes?.length) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Core AUTO tuân theo chính xác roster lớp hành chính và chưa hỗ trợ ngoại lệ.', 409);
      const base = requireWorkspace();
      const known = base.classes.find(item => item.summary.id === input.classId);
      if (!known) throw new ApiError('NOT_FOUND', 'Không tìm thấy lớp môn học trong trường hiện tại.', 404);
      const id = crypto.randomUUID();
      const change = await session.authenticated(async request => {
        const management = decodeManagement(await request('adminClassManagement', { pathParams: { classId: input.classId } }));
        const source = management.subjectClass;
        if (source.version !== input.revision) throw new ApiError('REQUEST_FAILED', 'Lớp đã thay đổi. Tải lại trước khi xem trước.', 409);
        const currentIds = management.members.map(item => item.userId);
        if (input.mode === 'AUTO') {
          const previewRaw = row(await request('adminPreviewEnrollment', { pathParams: { classId: input.classId } }));
          const classVersion = integer(previewRaw.class_version, 1), rosterVersion = integer(previewRaw.roster_version, 1);
          if (classVersion !== source.version) throw new ApiError('REQUEST_FAILED', 'Lớp đã thay đổi. Tải lại trước khi xem trước.', 409);
          const addedIds = list(previewRaw.add_student_ids).map(uuid), endedIds = list(previewRaw.end_student_ids).map(uuid);
          const target = [...new Set([...currentIds.filter(studentId => !endedIds.includes(studentId)), ...addedIds])];
          const projected = source.mode === 'AUTO' ? target.length : target.length;
          const preview: ClassroomChangePreview = {
            id, kind: 'ENROLLMENT', resourceId: input.classId, revision: classVersion,
            currentCount: currentIds.length, projectedCount: projected, addedIds, endedIds, status: 'PREVIEW', impact: [],
            policyNote: source.mode === 'MANUAL' ? 'Khi chuyển sang AUTO, Core đồng bộ roster lớp hành chính; danh sách MANUAL hiện tại có thể kết thúc.' : 'Xem trước thay đổi roster AUTO trước khi đồng bộ.',
          };
          return { preview, classId: input.classId, currentMode: source.mode, targetMode: input.mode, targetIds: target, expectedClassVersion: classVersion, expectedRosterVersion: rosterVersion };
        }
        const targetIds = [...new Set(input.studentIds ?? currentIds)];
        if (source.mode !== input.mode && !rosterEqual(targetIds, currentIds)) throw new ApiError('VALIDATION_ERROR', 'Hãy đổi chế độ ghi danh trước, sau đó chỉnh danh sách ở bước riêng.', 422);
        const targetSet = new Set(targetIds);
        const addedIds = targetIds.filter(studentId => !currentIds.includes(studentId));
        const endedIds = currentIds.filter(studentId => !targetSet.has(studentId));
        const preview: ClassroomChangePreview = {
          id, kind: 'ENROLLMENT', resourceId: input.classId, revision: source.version,
          currentCount: currentIds.length, projectedCount: targetIds.length, addedIds, endedIds, status: 'PREVIEW', impact: [],
          policyNote: source.mode === 'AUTO' ? 'Chế độ AUTO sẽ chuyển sang MANUAL, giữ nguyên roster hiện hành. Sau khi áp dụng chế độ, có thể chỉnh danh sách riêng.' : 'Danh sách MANUAL được thay nguyên tử, roster lớp hành chính không ghi đè lớp này.',
        };
        return { preview, classId: input.classId, currentMode: source.mode, targetMode: input.mode, targetIds, expectedClassVersion: source.version };
      });
      remember({ kind: 'ENROLLMENT', ...change });
      return change.preview;
    },
    async confirmEnrollment(input) {
      await requireAdmin();
      const change = pending.get(input.previewId);
      if (!change || change.kind !== 'ENROLLMENT') throw new ApiError('CAPABILITY_UNAVAILABLE', 'Bản xem trước ghi danh không còn trong phiên. Hãy tải lại và xem trước lần nữa.', 410);
      await session.authenticated(async request => {
        if (change.targetMode === 'AUTO') {
          if (change.currentMode === 'MANUAL') {
            await request('adminSetEnrollmentMode', {
              pathParams: { classId: change.classId },
              body: { mode: 'AUTO', expected_class_version: change.expectedClassVersion, expected_roster_version: change.expectedRosterVersion },
              headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
            });
          } else if (change.preview.addedIds.length || change.preview.endedIds.length) {
            await request('adminSyncEnrollment', {
              pathParams: { classId: change.classId },
              body: { expected_class_version: change.expectedClassVersion, expected_roster_version: change.expectedRosterVersion },
              headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
            });
          }
        } else if (change.currentMode === 'AUTO') {
          await request('adminSetEnrollmentMode', {
            pathParams: { classId: change.classId },
            body: { mode: 'MANUAL', expected_class_version: change.expectedClassVersion },
            headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
          });
        } else if (change.preview.addedIds.length || change.preview.endedIds.length) {
          await request('adminSetManualRoster', {
            pathParams: { classId: change.classId },
            body: { student_ids: change.targetIds, expected_class_version: change.expectedClassVersion },
            headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
          });
        }
      }, true);
      pending.delete(input.previewId);
      return { ...change.preview, status: 'APPLIED' };
    },
    async reconcileEnrollment(previewId) {
      await requireAdmin();
      const change = pending.get(previewId);
      if (!change) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Không còn bản xem trước để đối chiếu. Tải lại dữ liệu hiện hành.', 410);
      const applied = await session.authenticated(async request => {
        if (change.kind === 'HOMEROOM') {
          const source = await freshRoster(request, change.sourceId);
          if (change.transferStudentId && change.destinationId && change.destinationIds) {
            const destination = await freshRoster(request, change.destinationId);
            return !source.studentIds.includes(change.transferStudentId)
              && destination.studentIds.includes(change.transferStudentId);
          }
          return rosterEqual(source.studentIds, change.targetIds);
        }
        const management = decodeManagement(await request('adminClassManagement', { pathParams: { classId: change.classId } }));
        return management.subjectClass.mode === change.targetMode
          && rosterEqual(management.members.map(item => item.userId), change.targetIds);
      });
      if (applied) pending.delete(previewId);
      return { ...change.preview, status: applied ? 'APPLIED' : 'PREVIEW' };
    },
    async changeLifecycle(input) {
      await requireAdmin();
      const managed = requireWorkspace().classes.find(item => item.summary.id === input.classId);
      if (!managed) throw new ApiError('NOT_FOUND', 'Không tìm thấy lớp môn học trong trường hiện tại.', 404);
      if (input.status === managed.summary.status || input.confirmation.trim() !== managed.summary.name) throw new ApiError('VALIDATION_ERROR', 'Tên xác nhận hoặc trạng thái lớp không hợp lệ.', 422);
      await session.authenticated(request => request(input.status === 'ARCHIVED' ? 'adminArchiveClass' : 'adminRestoreClass', {
        pathParams: { classId: input.classId },
        body: { expected_class_version: input.revision },
        headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': crypto.randomUUID() },
      }), true);
      return { ...managed, summary: { ...managed.summary, status: input.status }, revision: input.revision + 1 };
    },
  };
}
