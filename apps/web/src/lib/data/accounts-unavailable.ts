import type { AccountsPort } from '../accounts';
import { ApiError } from '../api/errors';
const unavailable = async (): Promise<never> => { throw new ApiError('CAPABILITY_UNAVAILABLE', 'Chức năng quản lý này chưa được kết nối. Vui lòng thử lại khi nhà trường mở dịch vụ.', 503); };
export const unavailableAccounts: AccountsPort = {
  load: unavailable, updateAccount: unavailable, assignLegacyUsername: unavailable,
  inviteStaff: unavailable, revokeInvitation: unavailable, resendInvitation: unavailable, previewImport: unavailable,
  confirmImport: unavailable, reconcileImport: unavailable,
};

export function createUnavailableAccountsPort(): AccountsPort { return unavailableAccounts; }
