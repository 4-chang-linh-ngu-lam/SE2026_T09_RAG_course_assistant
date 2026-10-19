import type { DataRequest, User } from '../../src/lib/domain';
import type { AdminDataRequest, DataClassification, IntelligenceDependencies } from '../../src/lib/intelligence';
import { ApiError } from '../../src/lib/api/errors';
import type { PreviewContext } from './context';
import { recordPreviewAudit } from './audit';

export function createDataRequestReview(options: { context: PreviewContext; schoolId: string; records(): DataRequest[]; user(id: string): User | null; snapshot(userId: string): { profile: unknown; learningResults: unknown; personalNotes: unknown } }): Pick<IntelligenceDependencies, 'listRequests'|'updateRequest'|'processRequest'|'downloadRequest'> {
  const details = new Map<string, AdminDataRequest>();
  const files = new Map<string, {name: string; type: string; bytes: Uint8Array; scope: string}>();
  const clone = <T,>(value: T): T => structuredClone(value);
  function admin() { const actor = options.context.actor(); if (!actor.roles.includes('ADMIN') || actor.school_id !== options.schoolId) throw new ApiError('FORBIDDEN', 'Bạn không có quyền xử lý yêu cầu dữ liệu của trường.', 403); return actor; }
  function read(id: string): AdminDataRequest {
    const base = options.records().find(item => item.id === id), requester = base && options.user(base.user_id);
    if (!base || !requester || requester.school_id !== options.schoolId) throw new ApiError('NOT_FOUND', 'Không tìm thấy yêu cầu trong phạm vi trường.', 404);
    let row = details.get(id);
    if (!row) { row = { ...clone(base), requesterName: requester.display_name ?? requester.username ?? requester.email ?? 'Người yêu cầu', identityVerified: false, revision: 1, classifications: [], processingStatus: 'NOT_STARTED' }; details.set(id, row); }
    return row;
  }
  function writable(id: string, revision: number) { const row = read(id); if (row.revision !== revision) throw new ApiError('CONFLICT', 'Yêu cầu đã thay đổi. Hãy tải lại thông tin hiện hành.', 409); if (['COMPLETED','REJECTED'].includes(row.status)) throw new ApiError('CONFLICT', 'Yêu cầu đã được đóng.', 409); return row; }
  function validScope(scope: DataClassification[]) { if (!scope.length || scope.some(item => !item.category.trim() || !item.reason.trim() || !['RETAIN','CORRECT','EXPORT','ANONYMIZE','DELETE'].includes(item.action)) || new Set(scope.map(item => item.category)).size !== scope.length) throw new ApiError('VALIDATION_ERROR', 'Mỗi nhóm dữ liệu cần có một hướng xử lý và căn cứ rõ ràng.', 422); }
  function save(row: AdminDataRequest, action: string) {
    row.revision++; row.updated_at = new Date(options.context.now()).toISOString();
    const base = options.records().find(item => item.id === row.id)!;
    Object.assign(base, { status: row.status, resolution_note: row.resolution_note, updated_at: row.updated_at });
    const actor = admin(); recordPreviewAudit({ actorId: actor.id, actorName: actor.display_name ?? 'Quản trị viên', action, resourceType: 'DATA_REQUEST', resourceId: row.id, reason: 'Xử lý theo phạm vi yêu cầu đã xác minh; nội dung riêng tư không được ghi vào nhật ký.', at: row.updated_at });
    return clone(row);
  }
  return {
    async listRequests() { admin(); return options.records().filter(item => options.user(item.user_id)?.school_id === options.schoolId).map(item => clone(read(item.id))); },
    async updateRequest(input) {
      admin(); const row = writable(input.id, input.expectedRevision);
      if (!input.resolution.trim()) throw new ApiError('VALIDATION_ERROR', 'Ghi rõ căn cứ và kết quả xử lý.', 422);
      if (!['IN_REVIEW','COMPLETED','REJECTED'].includes(input.status)) throw new ApiError('VALIDATION_ERROR', 'Trạng thái không hợp lệ.', 422);
      if (input.status !== 'REJECTED') { validScope(input.classifications); if (!input.identityVerified) throw new ApiError('VALIDATION_ERROR', 'Cần xác minh danh tính trước khi xử lý.', 422); }
      const scope = JSON.stringify(input.classifications);
      if (input.status === 'COMPLETED' && (row.processingStatus !== 'READY' || !row.identityVerified || scope !== JSON.stringify(row.classifications) || files.get(row.id)?.scope !== scope)) throw new ApiError('CONFLICT', 'Chưa có kết quả xử lý được xác nhận cho đúng phạm vi này.', 409);
      if (scope !== JSON.stringify(row.classifications) || !input.identityVerified || input.status === 'REJECTED') { files.delete(row.id); delete row.artifact; row.processingStatus = 'NOT_STARTED'; }
      Object.assign(row, { status: input.status, identityVerified: input.identityVerified, classifications: clone(input.classifications), resolution_note: input.resolution.trim() });
      return save(row, `DATA_REQUEST_${input.status}`);
    },
    async processRequest(input) {
      admin(); const row = writable(input.id, input.expectedRevision); validScope(input.classifications);
      if (!row.identityVerified || row.status !== 'IN_REVIEW' || !input.verificationNote.trim() || JSON.stringify(input.classifications) !== JSON.stringify(row.classifications)) throw new ApiError('CONFLICT', 'Lưu kết quả xác minh và đúng phạm vi trước khi thực hiện.', 409);
      const allowed = ['PROFILE','LEARNING_RESULTS','PERSONAL_NOTES'];
      if (!['ACCESS','EXPORT'].includes(row.type) || input.classifications.some(item => !allowed.includes(item.category) || item.action !== 'EXPORT')) {
        row.processingStatus = 'BLOCKED'; files.delete(row.id); delete row.artifact;
        return save(row, 'DATA_REQUEST_PROCESSING_BLOCKED');
      }
      const snapshot = options.snapshot(row.user_id);
      const names = { PROFILE: 'profile', LEARNING_RESULTS: 'learningResults', PERSONAL_NOTES: 'personalNotes' } as const;
      const data = Object.fromEntries(input.classifications.map(item => [names[item.category as keyof typeof names], snapshot[names[item.category as keyof typeof names]]]));
      const preparedAt = new Date(options.context.now()).toISOString();
      const bytes = new TextEncoder().encode(JSON.stringify({ requestId: row.id, preparedAt, scope: clone(input.classifications), data, notice: 'Bản sao chỉ gồm các nhóm dữ liệu được xác minh và chọn trong phạm vi yêu cầu. Không phải bản sao toàn bộ hệ thống.' }, null, 2));
      const file = { name: `lumi-personal-data-${row.id}.json`, type: 'application/json', bytes, scope: JSON.stringify(input.classifications) };
      files.set(row.id, file); row.processingStatus = 'READY'; row.artifact = { name: file.name, type: file.type, size: bytes.byteLength, preparedAt };
      return save(row, 'DATA_REQUEST_COPY_PREPARED');
    },
    async downloadRequest(id) { const actor = options.context.actor(), row = read(id); if (actor.school_id !== options.schoolId || (!actor.roles.includes('ADMIN') && actor.id !== row.user_id)) throw new ApiError('FORBIDDEN', 'Bạn không có quyền tải bản sao này.', 403); const file = files.get(id); if (row.processingStatus !== 'READY' || !file || !row.identityVerified || file.scope !== JSON.stringify(row.classifications)) throw new ApiError('NOT_FOUND', 'Chưa có bản sao được xác nhận.', 404); return { name: file.name, type: file.type, bytes: new Uint8Array(file.bytes) }; },
  };
}
