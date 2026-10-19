import type { DataRequest, IssuedCode, Page, Role, User } from '../domain';
import { ApiError } from './errors';
function invalid(): never { throw new ApiError('CONTRACT_MISMATCH', 'Dữ liệu trả về chưa hợp lệ. Vui lòng liên hệ quản trị viên.'); }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : invalid(); }
function text(value: unknown): string { return typeof value === 'string' ? value : invalid(); }
function nullable(value: unknown): string | null { return value === null ? null : text(value); }
export function decodeUser(value: unknown): User {
  const x = record(value);
  if (!Array.isArray(x.roles) || !x.roles.length || !x.roles.every(role => ['STUDENT', 'LECTURER', 'ADMIN'].includes(role))) invalid();
  if (!['ACTIVE', 'PENDING_VERIFICATION', 'LOCKED'].includes(String(x.status))) invalid();
  return { id: text(x.id), email: nullable(x.email), username: nullable(x.username), school_id: nullable(x.school_id), display_name: nullable(x.display_name), roles: x.roles as Role[], status: x.status as User['status'] };
}
export function decodeToken(value: unknown) {
  const x = record(value);
  if (x.token_type !== 'bearer' || typeof x.expires_in !== 'number' || !Number.isFinite(x.expires_in) || x.expires_in <= 0) invalid();
  const access_token = text(x.access_token); if (!access_token) invalid();
  return { access_token, expires_in: x.expires_in };
}
export function decodeRequest(value: unknown): DataRequest {
  const x = record(value);
  if (!['ACCESS', 'EXPORT', 'CORRECTION', 'DELETE'].includes(String(x.type)) || !['PENDING', 'IN_REVIEW', 'COMPLETED', 'REJECTED'].includes(String(x.status))) invalid();
  return { id: text(x.id), user_id: text(x.user_id), type: x.type as DataRequest['type'], reason: nullable(x.reason), status: x.status as DataRequest['status'], resolution_note: nullable(x.resolution_note), created_at: text(x.created_at), updated_at: text(x.updated_at) };
}
export function decodeRequests(value: unknown): Page<DataRequest> {
  const x = record(value); if (!Array.isArray(x.items)) invalid();
  return { items: x.items.map(decodeRequest), next_cursor: nullable(x.next_cursor) };
}
export function decodeCode(value: unknown): IssuedCode {
  const x = record(value), s = record(x.student);
  if (!['ACTIVATION', 'PASSWORD_RESET'].includes(String(x.purpose)) || !['ACTIVE', 'PENDING_VERIFICATION', 'LOCKED'].includes(String(s.status))) invalid();
  return { student: { id: text(s.id), email: nullable(s.email), username: nullable(s.username), school_id: nullable(s.school_id), status: s.status as User['status'] }, purpose: x.purpose as IssuedCode['purpose'], code: text(x.code), expires_at: text(x.expires_at) };
}
export function decodeMutation<T>(decoder: (value: unknown) => T, value: unknown): T {
  try { return decoder(value); }
  catch (error) { if (error instanceof ApiError) error.outcome = 'unknown'; throw error; }
}
