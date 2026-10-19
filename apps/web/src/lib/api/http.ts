import { ApiError } from './errors';
import { operations, operationPath, successStatus, type OperationId } from './operations';

type Options = { body?: unknown; userId?: string; cursor?: string; signal?: AbortSignal };
export function createHttpClient(getToken: () => string | null, fetcher: typeof fetch = fetch) {
  return async function request(id: OperationId, options: Options = {}): Promise<unknown> {
    const [method] = operations[id];
    const controller = new AbortController();
    const abort = () => controller.abort();
    options.signal?.addEventListener('abort', abort, { once: true });
    if (options.signal?.aborted) controller.abort();
    const timer = setTimeout(abort, 15000);
    const headers = new Headers({ Accept: 'application/json' });
    const token = getToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    // No generic Idempotency-Key or retry: provisioning/activation forbid it,
    // and unknown mutations must be reconciled by the feature-specific contract.
    try {
      const query = options.cursor ? `?cursor=${encodeURIComponent(options.cursor)}` : '';
      const response = await fetcher(`/api/v1${operationPath(id, options.userId)}${query}`, {
        method, headers, credentials: 'include', cache: 'no-store', signal: controller.signal,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
      if (response.ok && response.status !== successStatus[id]) throw new ApiError('CONTRACT_MISMATCH', 'Phản hồi chưa đúng trạng thái xác nhận.', response.status, method === 'GET' ? 'rejected' : 'unknown');
      if (response.status === 204) return undefined;
      let json: unknown;
      try { json = await response.json(); } catch {
        throw new ApiError('INVALID_RESPONSE', 'Phản hồi chưa hợp lệ. Vui lòng thử lại sau.', response.status, method === 'GET' ? 'rejected' : 'unknown');
      }
      if (!response.ok) {
        const detail = typeof json === 'object' && json !== null && 'error' in json ? (json as { error: { code?: string; message?: string } }).error : null;
        throw new ApiError(detail?.code ?? 'REQUEST_FAILED', typeof detail?.message === 'string' ? detail.message : 'Chưa thể hoàn tất yêu cầu.', response.status,
          method !== 'GET' && response.status >= 500 ? 'unknown' : 'rejected', response.headers.get('X-Correlation-ID') ?? undefined, response.headers.get('Retry-After') ?? undefined);
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
