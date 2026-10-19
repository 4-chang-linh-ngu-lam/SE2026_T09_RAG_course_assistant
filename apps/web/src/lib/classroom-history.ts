import type { ClassroomAdminWorkspace, ClassroomAudit, ClassMember } from './classroom-admin';

/** Display-only history, projected from an already authorized workspace snapshot. */
export type AdministrationHistoryItem = {
  id: string;
  title: string;
  detail: string;
  at?: string;
  actorName?: string;
  statusLabel?: string;
};

const classActions: Readonly<Record<string, { title: string; description: string }>> = {
  CLASS_CREATE: { title: 'Tạo lớp môn học', description: 'Đã ghi nhận thao tác tạo lớp.' },
  CLASS_SETTINGS: { title: 'Cập nhật thông tin hoặc phân công', description: 'Bản ghi chưa cung cấp chi tiết thay đổi từng trường hoặc giáo viên tại thời điểm đó.' },
};
const homeroomActions: Readonly<Record<string, { title: string; description: string }>> = {
  HOMEROOM_CREATE: { title: 'Tạo lớp hành chính', description: 'Đã ghi nhận thao tác tạo lớp hành chính.' },
  HOMEROOM_ROSTER: { title: 'Điều chỉnh danh sách lớp', description: 'Đã ghi nhận thao tác đối chiếu danh sách lớp hành chính.' },
  HOMEROOM_TRANSFER: { title: 'Xác nhận thao tác chuyển lớp', description: 'Bản ghi gắn với lớp nguồn; chưa cung cấp lớp đích hoặc danh sách học sinh của lần chuyển này.' },
};

function timestamp(event: ClassroomAudit): number | null {
  const value = Date.parse(event.at);
  return Number.isFinite(value) ? value : null;
}
function actorName(data: ClassroomAdminWorkspace, id: string): string | undefined {
  // A historical audit actor need not be present in the current authorized staff data.
  const actor = data.teachers.find(user => user.id === id && user.roles.some(role => role === 'ADMIN' || role === 'LECTURER'));
  return actor?.display_name?.trim() || actor?.email?.trim() || undefined;
}
function eventsFor(
  data: ClassroomAdminWorkspace,
  resourceId: string,
  actions: Readonly<Record<string, { title: string; description: string }>>,
): AdministrationHistoryItem[] {
  return data.auditEvents
    .filter(event => event.resourceId === resourceId && Object.hasOwn(actions, event.action))
    .map((event, index) => ({ event, index, time: timestamp(event) }))
    .sort((left, right) => {
      if (left.time !== null && right.time !== null) return right.time - left.time || left.index - right.index;
      if (left.time !== null) return -1;
      if (right.time !== null) return 1;
      return left.index - right.index;
    })
    .map(({ event, time }) => {
      const action = actions[event.action];
      const reason = data.reasonCodes.find(option => option.value === event.reason)?.label;
      const knownActor = actorName(data, event.actorId);
      return {
        id: event.id,
        title: action.title,
        detail: `${action.description} ${reason ? `Lý do: ${reason}.` : 'Chưa có nhãn lý do trong dữ liệu được cung cấp.'}`,
        ...(time !== null ? { at: event.at } : {}),
        ...(knownActor ? { actorName: knownActor } : {}),
      };
    });
}

/** Only the requested class's actual creation/settings audit, not its current assignment presented as history. */
export function projectClassAssignmentHistory(data: ClassroomAdminWorkspace, classId: string): AdministrationHistoryItem[] {
  if (!data.classes.some(subjectClass => subjectClass.summary.id === classId)) return [];
  return eventsFor(data, classId, classActions);
}

/** Transfer events identify their source only in the current DTO; no inferred destination events. */
export function projectHomeroomRosterHistory(data: ClassroomAdminWorkspace, homeroomId: string): AdministrationHistoryItem[] {
  if (!data.homerooms.some(homeroom => homeroom.id === homeroomId)) return [];
  return eventsFor(data, homeroomId, homeroomActions);
}

const sourceLabels: Readonly<Record<ClassMember['source'], string>> = {
  AUTO: 'Theo lớp hành chính',
  MANUAL: 'Danh sách do quản trị viên quản lý',
  OVERRIDE: 'Ngoại lệ ghi danh đã được quản lý',
};

/** Episodes have order and status, but no dates or audit actors in the current model. */
export function projectClassMemberEpisodes(data: ClassroomAdminWorkspace, classId: string): AdministrationHistoryItem[] {
  const subjectClass = data.classes.find(value => value.summary.id === classId);
  if (!subjectClass) return [];
  return subjectClass.members.flatMap((member, index) => {
    const student = data.students.find(user => user.id === member.userId && user.roles.includes('STUDENT'));
    // Do not expose identifiers or records absent from this authorized student snapshot.
    if (!student) return [];
    const label = student.display_name?.trim() || student.username?.trim();
    if (!label) return [];
    return [{
      id: `membership:${classId}:${member.userId}:${index}`,
      title: label,
      detail: sourceLabels[member.source],
      statusLabel: member.status === 'ACTIVE' ? 'Đang ghi danh' : 'Đã kết thúc ghi danh',
    }];
  });
}
