export type Outcome = 'rejected' | 'unknown';
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0, public outcome: Outcome = 'rejected', public correlationId?: string, public retryAfter?: string) { super(message); this.name = 'ApiError'; }
}
export function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.outcome === 'unknown') return 'Chưa xác định được kết quả. Hãy kiểm tra trạng thái trước khi gửi lại.';
  if (error instanceof ApiError) return error.message;
  return 'Chưa thể hoàn tất yêu cầu. Vui lòng thử lại sau.';
}
