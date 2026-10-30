export type Outcome = 'rejected' | 'unknown';
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0, public outcome: Outcome = 'rejected', public correlationId?: string, public retryAfter?: string) { super(message); this.name = 'ApiError'; }
}

const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  400: 'Thông tin gửi lên chưa hợp lệ. Vui lòng kiểm tra lại.',
  401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
  403: 'Bạn không có quyền thực hiện thao tác này.',
  404: 'Không tìm thấy nội dung bạn yêu cầu.',
  409: 'Dữ liệu vừa thay đổi hoặc yêu cầu không còn phù hợp. Vui lòng tải lại rồi thử lại.',
  422: 'Thông tin chưa hợp lệ. Vui lòng kiểm tra các trường đã nhập.',
  429: 'Bạn thao tác quá nhanh. Vui lòng chờ một chút rồi thử lại.',
  500: 'Hệ thống đang gặp sự cố. Vui lòng thử lại sau.',
  502: 'Chưa thể nhận dữ liệu hợp lệ lúc này. Vui lòng thử lại sau.',
  503: 'Dịch vụ đang tạm thời gián đoạn. Vui lòng thử lại sau.',
};

const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  UNAUTHENTICATED: STATUS_MESSAGES[401],
  FORBIDDEN: STATUS_MESSAGES[403],
  NOT_FOUND: STATUS_MESSAGES[404],
  BAD_REQUEST: STATUS_MESSAGES[400],
  CONFLICT: STATUS_MESSAGES[409],
  VALIDATION_ERROR: STATUS_MESSAGES[422],
  RATE_LIMITED: STATUS_MESSAGES[429],
  INTERNAL_ERROR: STATUS_MESSAGES[500],
  SERVICE_UNAVAILABLE: STATUS_MESSAGES[503],
  UNAVAILABLE: STATUS_MESSAGES[503],
  CONTRACT_MISMATCH: STATUS_MESSAGES[502],
};

function isNaturalVietnamese(message: string): boolean {
  const value = message.trim();
  const containsTechnicalValue =
    /^(?:[A-Z][A-Z0-9_]{2,}|HTTP\s+\d{3}|\d{3})\s*[:：-]/u.test(value) ||
    /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/u.test(value) ||
    /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/iu.test(value);
  return !containsTechnicalValue && /[À-ỹ]/u.test(value);
}

export function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.outcome === 'unknown') return 'Chưa xác định được kết quả. Hãy kiểm tra trạng thái trước khi gửi lại.';
  if (error instanceof ApiError) {
    if (isNaturalVietnamese(error.message)) return error.message;
    return ERROR_MESSAGES[error.code] ?? STATUS_MESSAGES[error.status] ?? STATUS_MESSAGES[500];
  }
  if (error instanceof Error && isNaturalVietnamese(error.message)) return error.message;
  return 'Chưa thể hoàn tất yêu cầu. Vui lòng thử lại sau.';
}
