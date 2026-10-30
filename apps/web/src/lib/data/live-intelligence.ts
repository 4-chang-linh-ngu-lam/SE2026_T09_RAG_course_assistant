import { ApiError } from '../api/errors';
import type { IntelligenceAuditRecord, IntelligencePort, IntelligencePage } from '../intelligence';
import type { LiveIdentitySession } from './live-identity';
import { createUnavailableIntelligencePort } from './intelligence-unavailable';

type Row = Record<string, unknown>;

function invalid(): never {
  throw new ApiError('CONTRACT_MISMATCH', 'Dữ liệu audit chưa đúng hợp đồng Core.', 502);
}

function record(value: unknown): Row {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Row : invalid();
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : invalid();
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function decodeAudit(value: unknown): IntelligenceAuditRecord {
  const source = record(value), metadata = record(source.metadata_json);
  const actorId = nullableText(source.actor_id);
  if (actorId !== null && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(actorId)) return invalid();
  const targetId = text(source.target_id), timestamp = text(source.occurred_at);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(targetId)
    || !Number.isFinite(Date.parse(timestamp))) return invalid();
  const reason = metadata.reason_code;
  return {
    id: text(source.id),
    actorId: actorId ?? '',
    actorName: typeof source.actor_name === 'string' && source.actor_name.trim()
      ? source.actor_name
      : actorId === null ? 'Hệ thống' : 'Người dùng trong trường',
    action: text(source.action),
    resourceType: text(source.target_type),
    resourceId: targetId,
    reason: typeof reason === 'string' ? reason : 'Không có mã lý do trong bản ghi',
    at: timestamp,
  };
}

export function createLiveIntelligencePort(session: LiveIdentitySession): IntelligencePort {
  const unavailable = createUnavailableIntelligencePort();
  return {
    ...unavailable,
    async load(routeId, params, filter, signal): Promise<IntelligencePage> {
      if (routeId !== 'a.audit') return unavailable.load(routeId, params, filter, signal);
      const actor = session.currentUser() ?? await session.identity.restore();
      if (!actor) throw new ApiError('UNAUTHENTICATED', 'Phiên đăng nhập đã hết hạn.', 401);
      if (!actor.roles.includes('ADMIN') || actor.status !== 'ACTIVE') throw new ApiError('FORBIDDEN', 'Chỉ quản trị viên đang hoạt động mới được xem nhật ký.', 403);
      const response = record(await session.authenticated(request => request('adminAuditEvents', {
        query: { limit: 100, cursor: filter?.cursor }, signal,
      })));
      if (!Array.isArray(response.items)) return invalid();
      return {
        kind: 'audit',
        items: response.items.map(decodeAudit),
        nextCursor: response.next_cursor === null || response.next_cursor === undefined ? null : text(response.next_cursor),
      };
    },
  };
}
