import { findOperation, operationQueryParameters } from './operations';

function failure(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status, headers: { 'Cache-Control': 'no-store' } });
}
export function createCoreProxy(getOrigin: () => string | undefined, fetcher: typeof fetch = fetch, getWebOrigin?: () => string | undefined) {
  return async function proxy(request: Request, parts: string[]) {
    const path = '/' + parts.join('/');
    const operation = findOperation(request.method, path);
    if (parts.some(p => !p || p.includes('/') || p.includes('\\') || p === '.' || p === '..') || !operation) {
      return failure('NOT_FOUND', 'Không tìm thấy nội dung.', 404);
    }
    const method = request.method;
    let publicOrigin: string;
    try {
      const configured = getWebOrigin ? getWebOrigin() : new URL(request.url).origin;
      if (!configured) throw new Error();
      const origin = new URL(configured);
      if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error();
      publicOrigin = origin.origin;
    } catch { return failure('CONFIGURATION_ERROR', 'Dịch vụ chưa sẵn sàng.', 503); }
    if (!['GET', 'HEAD'].includes(method) && request.headers.get('Origin') !== publicOrigin) {
      return failure('FORBIDDEN', 'Yêu cầu không hợp lệ.', 403);
    }
    let origin: URL;
    try {
      const configured = getOrigin(); if (!configured) throw new Error();
      origin = new URL(configured);
      if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== '/') throw new Error();
    } catch { return failure('CONFIGURATION_ERROR', 'Dịch vụ chưa sẵn sàng.', 503); }
    const target = new URL('/api/v1' + path, origin);
    const incoming = new URL(request.url);
    // Forward only query parameters explicitly documented for the matched operation.
    for (const key of operationQueryParameters[operation] ?? []) {
      if (incoming.searchParams.has(key)) target.searchParams.set(key, incoming.searchParams.get(key)!);
    }
    const headers = new Headers({ Accept: 'application/json' });
    for (const name of ['authorization', 'cookie', 'content-type', 'origin', 'referer', 'x-correlation-id', 'x-admin-reason', 'idempotency-key']) {
      const value = request.headers.get(name); if (value) headers.set(name, value);
    }
    try {
      const upstream = await fetcher(target, { method, headers, body: ['GET', 'HEAD'].includes(method) ? undefined : await request.text(), cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(15000) });
      if (upstream.status >= 300 && upstream.status < 400) return failure('UPSTREAM_ERROR', 'Dịch vụ chưa sẵn sàng.', 502);
      const responseHeaders = new Headers({ 'Cache-Control': 'no-store' });
      for (const name of ['content-type', 'x-correlation-id', 'retry-after', 'x-token-delivery-status']) { const value = upstream.headers.get(name); if (value) responseHeaders.set(name, value); }
      for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append('Set-Cookie', cookie);
      return new Response(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status, headers: responseHeaders });
    } catch { return failure('UPSTREAM_UNAVAILABLE', 'Chưa kết nối được máy chủ. Vui lòng thử lại sau.', 503); }
  };
}
