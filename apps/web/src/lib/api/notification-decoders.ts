import type {NotificationItem} from '../domain';
import {ApiError} from './errors';
import {resourceUuid,sameResourceId} from './operations';

const labels: Record<string, readonly [string,string]> = {
  CLASS_ENROLLMENT_CHANGED: ['Cập nhật ghi danh','Danh sách tham gia lớp của bạn đã được cập nhật.'],
  CLASS_ENROLLMENT_MODE_CHANGED: ['Cập nhật hình thức ghi danh','Hình thức ghi danh của lớp đã được cập nhật.'],
  CLASS_TEACHERS_CHANGED: ['Cập nhật giáo viên','Phân công giáo viên của lớp đã được cập nhật.'],
  CLASS_STATUS_CHANGED: ['Cập nhật trạng thái lớp','Trạng thái hoạt động của lớp đã thay đổi.'],
  CLASS_STUDENT_TRANSFERRED: ['Cập nhật chuyển lớp','Thông tin chuyển lớp môn học của bạn đã được cập nhật.'],
  HOMEROOM_STUDENT_TRANSFERRED: ['Cập nhật lớp hành chính','Thông tin lớp hành chính của bạn đã được cập nhật.'],
  SOCIAL_POST_CREATED: ['Bài đăng mới trong lớp','Lớp học của bạn có bài đăng mới.'],
  SOCIAL_COMMENT_CREATED: ['Phản hồi mới','Bài đăng của bạn có phản hồi mới.'],
  CALENDAR_DEADLINE_CHANGED: ['Cập nhật thời hạn học tập','Một thời hạn học tập của lớp đã được cập nhật.'],
};
function invalid(): never { throw new ApiError('CONTRACT_MISMATCH','Dữ liệu thông báo trả về chưa hợp lệ. Vui lòng tải lại.'); }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : invalid(); }
function id(value: unknown): string { return typeof value === 'string' && resourceUuid.test(value) ? value.toLowerCase() : invalid(); }
export function decodeNotificationPage(value: unknown, actorId: string) {
  const page = record(value);
  if (!Array.isArray(page.items) || !Number.isSafeInteger(page.unread_count) || Number(page.unread_count) < 0) return invalid();
  if (page.next_cursor !== null && (typeof page.next_cursor !== 'string' || !/^[A-Za-z0-9_-]{22}$/.test(page.next_cursor))) return invalid();
  const items: NotificationItem[] = page.items.map(value => {
    const row = record(value);
    if (typeof row.type !== 'string' || !row.type || typeof row.read !== 'boolean' || typeof row.created_at !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(row.created_at) || !Number.isFinite(Date.parse(row.created_at))) return invalid();
    record(row.payload_json);
    // Payloads never supply display HTML, actor IDs or navigation. Other Core
    // workspaces are not contracted yet, so no speculative deep link is emitted.
    const known = Object.hasOwn(labels,row.type);
    const [title,content] = known ? labels[row.type] : ['Thông báo hệ thống','Bạn có cập nhật mới trên hệ thống.'];
    return {id:id(row.id),userId:actorId,title,content,category:known?'CLASS':'SYSTEM',isRead:row.read,createdAt:row.created_at};
  });
  if (new Set(items.map(item => item.id)).size !== items.length) return invalid();
  return {items,unreadCount:Number(page.unread_count),nextCursor:page.next_cursor as string|null};
}
export function decodeNotificationRead(value: unknown, expectedId: string): void {
  const row = record(value);
  if (!sameResourceId(id(row.id),expectedId) || row.read !== true) invalid();
}
