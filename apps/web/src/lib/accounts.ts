import type { IssuedCode, Login, Role, RouteParams, User } from './domain';

// Frontend view models. Administration HTTP payloads remain uncontracted.
export type ManagedAccount = User & { revision: number; legacy: boolean; activationRequired: boolean; lastAdmin: boolean; createdAt: string };
export type TokenDeliveryStatus = 'PENDING' | 'DELIVERED' | 'CANCELLED' | 'NEEDS_REISSUE';
export type StaffInvitation = { id: string; userId: string; email: string; roles: Role[]; createdAt: string; expiresAt: string | null; status: 'PENDING' | 'ACCEPTED' | 'EXPIRED' | 'REVOKED'; deliveryStatus?: TokenDeliveryStatus | null };
export type StaffInvitationResult = { invitation: StaffInvitation; code?: string; deliveryStatus?: TokenDeliveryStatus };
export type ImportCell = string | number | boolean | Date | null;
export type ImportSourceRow = { rowNumber: number; cells: ImportCell[] };
export type ImportFile = { filename: string; format: 'CSV' | 'XLSX'; headers: string[]; rows: ImportSourceRow[]; contentBase64?: string };
export type ImportMapping = { username: number; displayName: number | null };
export type ImportRow = { rowNumber: number; username: string; displayName: string; errors: string[]; status: 'VALID' | 'INVALID' | 'CREATED' | 'EXISTING' | 'USERNAME_ASSIGNED'; action?: 'CREATE' | 'EXISTING' | 'ASSIGN_USERNAME'; userId?: string; activationCode?: string | null; codeExpiresAt?: string | null };
export type ImportJob = { id: string; filename: string; createdAt: string; revision: number; accountRevision: number; mapping: ImportMapping; rows: ImportRow[]; status: 'PREVIEW' | 'COMPLETED'; createdCount: number; rejectedCount: number; replayed?: boolean; canConfirm?: boolean };
export type AccountsWorkspace = { accounts: ManagedAccount[]; account?: ManagedAccount; invitations: StaffInvitation[]; importJob?: ImportJob; revision: number };
export interface AccountsPort {
  load(routeId: string, params: RouteParams, signal?: AbortSignal): Promise<AccountsWorkspace>;
  updateAccount(input: { userId: string; revision: number; roles: Role[]; status: User['status']; reason: string }): Promise<ManagedAccount>;
  assignLegacyUsername(input: { userId: string; revision: number; username: string }): Promise<ManagedAccount>;
  inviteStaff(input: { email: string; displayName: string; roles: ('ADMIN' | 'LECTURER')[] }): Promise<StaffInvitationResult>;
  revokeInvitation(id: string): Promise<void>;
  resendInvitation(id: string): Promise<StaffInvitationResult>;
  previewImport(input: { file: ImportFile; mapping: ImportMapping }): Promise<ImportJob>;
  confirmImport(input: { importId: string; revision: number; reason: string }): Promise<ImportJob>;
  reconcileImport(importId: string): Promise<ImportJob>;
}
export interface PreviewIdentityStore {
  user(id: string): User | null;
  allUsers(): User[];
  sessionRevision(userId: string): number;
  revokeSessions(userId: string): void;
  login(input: Login): User;
  updateProfile(userId: string, displayName: string | null): User;
  createStudent(actorId: string, username: string, displayName?: string): IssuedCode;
  issueCode(actorId: string, userId: string, identityVerified: boolean): IssuedCode;
  activate(input: { username: string; activation_code: string; new_password: string }): void;
  reset(token: string, newPassword: string): void;
  acceptInvitation(token: string, newPassword: string): void;
  forgot(email: string): void;
}
