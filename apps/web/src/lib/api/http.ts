import { ApiError } from './errors';
import { operations, operationPath, successStatus, queryKeys, adminReasons, reasonOperations, type AdminReason, type ResourceParams, type OperationId } from './operations';

export type HttpOptions = ResourceParams & { body?: unknown; cursor?: string; limit?: number; query?:Record<string,string|number|undefined>; reason?:AdminReason; signal?: AbortSignal };
export function createHttpClient(getToken: () => string | null, fetcher: typeof fetch = fetch) {
  return async function request(id: OperationId, options: HttpOptions = {}): Promise<unknown> {
    const [method] = operations[id];
    let path: string;
    try { path = operationPath(id, options); }
    catch { throw new ApiError('VALIDATION_ERROR','Định danh tài nguyên chưa hợp lệ.',422); }
    if(options.reason!==undefined&&(!reasonOperations.has(id)||!adminReasons.includes(options.reason)))throw new ApiError('VALIDATION_ERROR','Mã lý do chưa hợp lệ.',422);
    const controller = new AbortController();
    const abort = () => controller.abort();
    options.signal?.addEventListener('abort', abort, { once: true });
    if (options.signal?.aborted) controller.abort();
    const timer = setTimeout(abort, 15000);
    const headers = new Headers({ Accept: 'application/json' });
    const token = getToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    if(options.reason!==undefined){
      headers.set('X-Admin-Reason',options.reason);
    }
    // No generic Idempotency-Key or retry: provisioning/activation forbid it,
    // and unknown mutations must be reconciled by the feature-specific contract.
    try {
      const pagination = new URLSearchParams();
      const filters={...options.query,...(options.cursor===undefined?{}:{cursor:options.cursor}),...(options.limit===undefined?{}:{limit:options.limit})};
      for(const [key,value]of Object.entries(filters))if(value!==undefined){
        if(!queryKeys(id).includes(key))throw new ApiError('VALIDATION_ERROR','Bộ lọc chưa được hỗ trợ.',422);
        pagination.set(key,String(value));
      }
      const query = pagination.size ? `?${pagination}` : '';
      const response = await fetcher(`/api/v1${path}${query}`, {
        method, headers, credentials: 'include', cache: 'no-store', signal: controller.signal,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
      const correlationId = response.headers.get('X-Correlation-ID') ?? undefined;
      const retryAfter = response.headers.get('Retry-After') ?? undefined;
      const outcome = method !== 'GET' && (response.ok || response.status >= 500) ? 'unknown' : 'rejected';
      if (response.ok && response.status !== successStatus[id]) throw new ApiError('CONTRACT_MISMATCH', 'Phản hồi chưa đúng trạng thái xác nhận.', response.status, outcome, correlationId, retryAfter);
      if (response.status === 204) return undefined;
      let json: unknown;
      try { json = await response.json(); } catch {
        throw new ApiError('INVALID_RESPONSE', 'Phản hồi chưa hợp lệ. Vui lòng thử lại sau.', response.status, outcome, correlationId, retryAfter);
      }
      if (!response.ok) {
        const envelope = typeof json === 'object' && json !== null && !Array.isArray(json) ? json as Record<string, unknown> : null;
        const value = envelope?.error;
        const detail = typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
        throw new ApiError(typeof detail?.code === 'string' && detail.code ? detail.code : 'REQUEST_FAILED', typeof detail?.message === 'string' ? detail.message : 'Chưa thể hoàn tất yêu cầu.', response.status,
          outcome, correlationId, retryAfter);
      }
      return json;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError('CONNECTION_ERROR', 'Chưa kết nối được máy chủ. Vui lòng kiểm tra kết nối.', 0, method === 'GET' ? 'rejected' : 'unknown');
    } finally {
      clearTimeout(timer); options.signal?.removeEventListener('abort', abort);
    }
  };
}
