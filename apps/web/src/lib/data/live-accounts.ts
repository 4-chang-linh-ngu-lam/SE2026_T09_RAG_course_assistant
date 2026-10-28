import { ApiError } from '../api/errors';
import type { HttpRequest } from '../api/http';
import type { AccountsPort, AccountsWorkspace, ImportFile, ImportJob, ImportMapping, ImportRow, ManagedAccount, StaffInvitation, StaffInvitationResult, TokenDeliveryStatus } from '../accounts';
import type { Page, Role, User } from '../domain';
import type { LiveIdentitySession } from './live-identity';

type AdminUser = ManagedAccount & {
  invitation_expires_at: string | null;
  invitation_delivery_status: TokenDeliveryStatus | null;
};
type Row = Record<string, unknown>;
type PendingImport = { job: ImportJob; previewId: string | null; reason?: string; operationKey: string };

function invalid(): never {
  throw new ApiError('CONTRACT_MISMATCH', 'Dữ liệu danh sách tài khoản chưa đúng hợp đồng Core.', 502);
}

function record(value: unknown): Row {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Row : invalid();
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : invalid();
}

function integer(value: unknown, min = 0): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min ? value : invalid();
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function decodeUser(value: unknown): AdminUser {
  const row = record(value);
  if (!Array.isArray(row.roles) || !row.roles.length || !row.roles.every(role => ['ADMIN', 'LECTURER', 'STUDENT'].includes(String(role)))) return invalid();
  if (!['ACTIVE', 'PENDING_VERIFICATION', 'LOCKED'].includes(String(row.status))) return invalid();
  if (typeof row.revision !== 'number' || !Number.isInteger(row.revision) || typeof row.email_verified !== 'boolean'
    || typeof row.activation_required !== 'boolean' || typeof row.last_admin !== 'boolean') return invalid();
  const delivery = row.invitation_delivery_status;
  if (delivery !== null && delivery !== undefined && !['PENDING', 'DELIVERED', 'CANCELLED', 'NEEDS_REISSUE'].includes(String(delivery))) return invalid();
  return {
    id: text(row.id),
    email: nullableText(row.email),
    username: nullableText(row.username),
    school_id: text(row.school_id),
    display_name: nullableText(row.display_name),
    status: row.status as User['status'],
    roles: row.roles as Role[],
    revision: row.revision,
    legacy: (row.roles as Role[]).includes('STUDENT') && row.username === null,
    activationRequired: row.activation_required,
    lastAdmin: row.last_admin,
    createdAt: text(row.created_at),
    invitation_expires_at: nullableText(row.invitation_expires_at),
    invitation_delivery_status: delivery as TokenDeliveryStatus | null,
  };
}

function decodePage(value: unknown): Page<AdminUser> {
  const row = record(value);
  if (!Array.isArray(row.items)) return invalid();
  return { items: row.items.map(decodeUser), next_cursor: row.next_cursor === null || row.next_cursor === undefined ? null : text(row.next_cursor) };
}

async function listAccounts(request: HttpRequest, signal?: AbortSignal): Promise<AdminUser[]> {
  const result: AdminUser[] = [];
  let cursor: string | undefined;
  for (let pageNumber = 0; pageNumber < 20; pageNumber++) {
    const response = decodePage(await request('adminUsers', { query: { limit: 100, cursor }, signal }));
    result.push(...response.items);
    if (!response.next_cursor) return result;
    cursor = response.next_cursor;
  }
  throw new ApiError('PAGE_LIMIT', 'Danh sách tài khoản quá lớn để tải trong một lượt. Hãy lọc danh sách rồi thử lại.', 413);
}

function invitationFor(account: AdminUser): StaffInvitation | null {
  const staffRoles = account.roles.filter(role => role === 'ADMIN' || role === 'LECTURER');
  if (!staffRoles.length) return null;
  let status: StaffInvitation['status'];
  if (account.status === 'ACTIVE') status = 'ACCEPTED';
  else if (account.status === 'LOCKED') status = 'REVOKED';
  else if (!account.invitation_expires_at || new Date(account.invitation_expires_at).getTime() <= Date.now()
    || ['CANCELLED', 'NEEDS_REISSUE'].includes(account.invitation_delivery_status ?? '')) status = 'EXPIRED';
  else status = 'PENDING';
  return {
    id: account.id,
    userId: account.id,
    email: account.email ?? '',
    roles: staffRoles,
    createdAt: account.createdAt,
    expiresAt: account.invitation_expires_at,
    status,
    deliveryStatus: account.invitation_delivery_status,
  };
}

function deliveryStatus(value: string | null): TokenDeliveryStatus {
  if (value && ['PENDING', 'DELIVERED', 'CANCELLED', 'NEEDS_REISSUE'].includes(value)) return value as TokenDeliveryStatus;
  return 'PENDING';
}

function importText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (value instanceof Date) return value.toISOString();
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : invalid();
}

function importError(code: string): string {
  const messages: Record<string, string> = {
    DUPLICATE_ROW: 'Dòng bị trùng trong tệp.', INVALID_ROW: 'Dòng không hợp lệ; kiểm tra tên đăng nhập và kiểu ô.',
    ACCOUNT_UNAVAILABLE: 'Tài khoản không khả dụng trong trường hiện tại.', USERNAME_UNAVAILABLE: 'Tên đăng nhập đã được sử dụng.',
    USERNAME_MISMATCH: 'Tên đăng nhập không khớp tài khoản hiện có.', DISPLAY_NAME_MISMATCH: 'Họ tên không khớp tài khoản hiện có.',
    LEGACY_VERIFICATION_REQUIRED: 'Tài khoản cũ cần được xác minh trước khi gán tên đăng nhập.',
  };
  return messages[code] ?? 'Dòng không hợp lệ theo quy tắc Core.';
}

function mapImportRows(file: ImportFile, mapping: ImportMapping, items: Row[], errors: Row[]): ImportRow[] {
  const byRow = new Map<number, Row>(items.map(item => [Number(item.row), item]));
  const errorsByRow = new Map<number, string[]>([]);
  for (const error of errors) {
    const rowNumber = Number(error.row), list = errorsByRow.get(rowNumber) ?? [];
    list.push(importError(text(error.code)));
    errorsByRow.set(rowNumber, list);
  }
  return file.rows.map(source => {
    const username = importText(source.cells[mapping.username]).trim();
    const displayName = mapping.displayName === null ? '' : importText(source.cells[mapping.displayName]).trim();
    const match = byRow.get(source.rowNumber), rowErrors = errorsByRow.get(source.rowNumber) ?? [];
    const action = match?.action;
    if (action !== undefined && !['CREATE', 'EXISTING', 'ASSIGN_USERNAME'].includes(String(action))) return invalid();
    return {
      rowNumber: source.rowNumber,
      username,
      displayName,
      errors: rowErrors,
      status: rowErrors.length ? 'INVALID' : 'VALID',
      ...(action ? { action: action as ImportRow['action'] } : {}),
      ...(match?.user_id ? { userId: text(match.user_id) } : {}),
    };
  });
}

function importResultJob(previous: ImportJob, value: unknown, replayed: boolean): ImportJob {
  const response = record(value);
  if (!Array.isArray(response.items)) return invalid();
  const byRow = new Map<number, Row>(response.items.map(item => {
    const result = record(item);
    return [integer(result.row), result] as const;
  }));
  let createdCount = 0;
  const rows = previous.rows.map(item => {
    const result = byRow.get(item.rowNumber);
    if (!result) return { ...item, status: 'INVALID' as const, errors: ['Core không trả kết quả cho dòng này.'] };
    const outcome = text(result.outcome), student = record(result.student);
    if (!['CREATED', 'EXISTING', 'USERNAME_ASSIGNED'].includes(outcome)) return invalid();
    if (outcome === 'CREATED') createdCount++;
    return {
      ...item,
      status: outcome === 'CREATED' ? 'CREATED' as const : outcome === 'USERNAME_ASSIGNED' ? 'USERNAME_ASSIGNED' as const : 'EXISTING' as const,
      userId: text(student.id),
      ...(typeof result.code === 'string' ? { activationCode: result.code } : {}),
      ...(typeof result.expires_at === 'string' ? { codeExpiresAt: result.expires_at } : {}),
    };
  });
  return { ...previous, rows, status: 'COMPLETED', createdCount, rejectedCount: rows.filter(item => item.status === 'INVALID').length, replayed };
}

function withoutImportCodes(job: ImportJob): ImportJob {
  return { ...job, rows: job.rows.map(({ activationCode: _code, codeExpiresAt: _expiry, ...item }) => item) };
}

export function createLiveAccounts(session: LiveIdentitySession): AccountsPort {
  let cachedAccounts: AdminUser[] = [];
  const imports = new Map<string, PendingImport>();
  return {
    async load(routeId, params, signal): Promise<AccountsWorkspace> {
      const accounts = await session.authenticated(request => listAccounts(request, signal));
      cachedAccounts = accounts;
      if (routeId === 'a.import' && params.importId) {
        const imported = imports.get(params.importId);
        if (!imported) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Bản xem trước import không còn trong phiên. Hãy chọn lại tệp để kiểm tra dữ liệu mới.', 410);
        return { accounts, importJob: imported.job, invitations: accounts.map(invitationFor).filter((item): item is StaffInvitation => item !== null), revision: accounts.reduce((latest, item) => Math.max(latest, item.revision), 0) };
      }
      const account = params.userId ? accounts.find(item => item.id === params.userId) : undefined;
      return {
        accounts,
        account,
        invitations: accounts.map(invitationFor).filter((item): item is StaffInvitation => item !== null),
        revision: accounts.reduce((latest, item) => Math.max(latest, item.revision), 0),
      };
    },
    async updateAccount(input) {
      await session.authenticated(request => request('adminUpdateUser', {
        pathParams: { userId: input.userId },
        body: { expected_revision: input.revision, roles: input.roles, status: input.status },
        headers: { 'X-Admin-Reason': input.reason },
      }), true);
      const existing = cachedAccounts.find(item => item.id === input.userId);
      if (!existing) throw new ApiError('CONTRACT_MISMATCH', 'Tài khoản đã cập nhật nhưng không có bản tóm tắt để đối chiếu.', 502, 'unknown');
      const changed = existing.status !== input.status || [...existing.roles].sort().join(',') !== [...input.roles].sort().join(',');
      return { ...existing, roles: input.roles, status: input.status, revision: input.revision + (changed ? 1 : 0) };
    },
    async assignLegacyUsername() {
      throw new ApiError('CAPABILITY_UNAVAILABLE', 'Chuẩn hóa tài khoản cũ đang chờ TV1/TV2 duyệt School mapping (issue #13).', 503);
    },
    async inviteStaff(input): Promise<StaffInvitationResult> {
      let sentStatus: string | null = null;
      const created = record(await session.authenticated(request => request('adminCreateUser', {
        body: { email: input.email, display_name: input.displayName, roles: input.roles },
        headers: { 'X-Admin-Reason': 'ADMIN_INTERVENTION' },
        onResponse(response) { sentStatus = response.headers.get('X-Token-Delivery-Status'); },
      }), true));
      const status = deliveryStatus(sentStatus);
      const invitation: StaffInvitation = {
        id: text(created.id),
        userId: text(created.id),
        email: nullableText(created.email) ?? input.email,
        roles: input.roles,
        createdAt: new Date().toISOString(),
        expiresAt: null,
        status: 'PENDING',
        deliveryStatus: status,
      };
      return { invitation, deliveryStatus: status };
    },
    async revokeInvitation() {
      throw new ApiError('CAPABILITY_UNAVAILABLE', 'Core chưa có thao tác thu hồi invitation; hãy khóa tài khoản nếu cần chặn đăng nhập.', 503);
    },
    async resendInvitation(id): Promise<StaffInvitationResult> {
      let sentStatus: string | null = null;
      const updated = record(await session.authenticated(request => request('adminReissueInvitation', {
        pathParams: { userId: id },
        headers: { 'X-Admin-Reason': 'ADMIN_INTERVENTION' },
        onResponse(response) { sentStatus = response.headers.get('X-Token-Delivery-Status'); },
      }), true));
      const account = cachedAccounts.find(item => item.id === id);
      const status = deliveryStatus(sentStatus);
      const invitation: StaffInvitation = {
        id,
        userId: id,
        email: nullableText(updated.email) ?? account?.email ?? '',
        roles: account?.roles.filter(role => role === 'ADMIN' || role === 'LECTURER') ?? ['LECTURER'],
        createdAt: account?.createdAt ?? new Date().toISOString(),
        expiresAt: null,
        status: 'PENDING',
        deliveryStatus: status,
      };
      return { invitation, deliveryStatus: status };
    },
    async previewImport(input) {
      const { file, mapping } = input;
      if (!file.contentBase64) throw new ApiError('VALIDATION_ERROR', 'Hãy chọn lại tệp gốc để Core kiểm tra.', 422);
      const header = (index: number | null) => index === null ? null : file.headers[index];
      if (!header(mapping.username) || (mapping.displayName !== null && !header(mapping.displayName))) throw new ApiError('VALIDATION_ERROR', 'Cột đã chọn không còn trong tệp.', 422);
      const result = record(await session.authenticated(request => request('adminStudentImportPreview', {
        body: { format: file.format, content_base64: file.contentBase64, username_header: header(mapping.username), display_name_header: header(mapping.displayName), user_id_header: null },
      }), true));
      if (typeof result.valid !== 'boolean' || !Array.isArray(result.items) || !Array.isArray(result.errors)) return invalid();
      const previewId = result.preview_id === null || result.preview_id === undefined ? null : text(result.preview_id);
      if (result.valid && !previewId) return invalid();
      const id = crypto.randomUUID();
      const rows = mapImportRows(file, mapping, result.items.map(record), result.errors.map(record));
      const job: ImportJob = {
        id, filename: file.filename, createdAt: new Date().toISOString(), revision: 1,
        accountRevision: cachedAccounts.reduce((latest, item) => Math.max(latest, item.revision), 0),
        mapping, rows, status: 'PREVIEW', createdCount: 0,
        rejectedCount: rows.filter(item => item.status === 'INVALID').length,
        canConfirm: result.valid,
      };
      imports.set(id, { job, previewId, operationKey: crypto.randomUUID() });
      return job;
    },
    async confirmImport(input) {
      const pending = imports.get(input.importId);
      if (!pending || !pending.previewId || pending.job.canConfirm === false) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Bản xem trước không thể xác nhận. Hãy sửa lỗi và kiểm tra lại tệp.', 409);
      pending.reason = input.reason;
      const response = await session.authenticated(request => request('adminStudentImportConfirm', {
        body: { preview_id: pending.previewId },
        headers: { 'X-Admin-Reason': input.reason, 'Idempotency-Key': pending.operationKey },
      }), true);
      const job = importResultJob(pending.job, response, Boolean(record(response).replayed));
      pending.job = withoutImportCodes(job);
      return job;
    },
    async reconcileImport(importId) {
      const pending = imports.get(importId);
      if (!pending?.previewId) throw new ApiError('CAPABILITY_UNAVAILABLE', 'Không có mã bản xem trước để đối chiếu.', 410);
      const status = record(await session.authenticated(request => request('adminStudentImportStatus', { pathParams: { previewId: pending.previewId! } })));
      if (status.status === 'PREVIEW') {
        pending.job = { ...pending.job, canConfirm: true };
        return pending.job;
      }
      if (status.status === 'EXPIRED') throw new ApiError('REQUEST_FAILED', 'Bản xem trước đã hết hạn. Hãy chọn lại tệp.', 409);
      if (status.status !== 'COMPLETED' || !Array.isArray(status.items)) return invalid();
      const response = { items: status.items.map(item => {
        const source = record(item);
        return { row: source.row, outcome: source.outcome, student: { id: source.user_id }, code: null, expires_at: null };
      }), replayed: true };
      const job = importResultJob(pending.job, response, true);
      pending.job = withoutImportCodes(job);
      return job;
    },
  };
}
