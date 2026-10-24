import { matchedOperation, queryKeys, reasonOperations, adminReasons, type AdminReason } from './operations';
import { CLIENT_CONTEXT_HEADER, verifyClientContext } from '../../../config/client-identity.mjs';

export function createCoreProxy(getOrigin: () => string | undefined, fetcher: typeof fetch = fetch, getWebOrigin?: () => string | undefined, getProxySecret?: () => string | undefined) {
  return async function proxy(request: Request, parts: string[]) {
    const incomingId = request.headers.get('X-Correlation-ID');
    const correlationId = incomingId && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(incomingId) ? incomingId : crypto.randomUUID();
    const failure = (code: string, message: string, status: number) => Response.json({ error: { code, message, correlation_id: correlationId } }, { status, headers: { 'Cache-Control': 'no-store', 'X-Correlation-ID': correlationId } });
    const path = '/' + parts.join('/');
    const operation=matchedOperation(request.method,path);
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
    // Only documented pagination parameters, not arbitrary forwarded query strings.
    for(const key of queryKeys(operation))if(incoming.searchParams.has(key))target.searchParams.set(key,incoming.searchParams.get(key)!);
    const headers = new Headers({ Accept: 'application/json' });
    for (const name of ['authorization', 'cookie', 'content-type', 'origin', 'referer', 'x-correlation-id']) {
      const value = request.headers.get(name); if (value) headers.set(name, value);
    }
    headers.set('X-Correlation-ID', correlationId);
    if(reasonOperations.has(operation)){
      const reason=request.headers.get('X-Admin-Reason');
      if(reason!==null){
        if(!adminReasons.includes(reason as AdminReason))return failure('VALIDATION_ERROR','Mã lý do chưa hợp lệ.',400);
        headers.set('X-Admin-Reason',reason);
      }
    }
    if (getProxySecret) {
      const secret = getProxySecret();
      if (!secret || secret.length < 32) return failure('CONFIGURATION_ERROR', 'Dịch vụ chưa sẵn sàng.', 503);
      const context = request.headers.get(CLIENT_CONTEXT_HEADER);
      if (!verifyClientContext(context, method, '/api/v1' + path, secret)) return failure('FORBIDDEN', 'Yêu cầu không hợp lệ.', 403);
      headers.set(CLIENT_CONTEXT_HEADER, context!);
    }
    try {
      const upstream = await fetcher(target, { method, headers, body: ['GET', 'HEAD'].includes(method) ? undefined : await request.text(), cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(15000) });
      if (upstream.status >= 300 && upstream.status < 400) return failure('UPSTREAM_ERROR', 'Dịch vụ chưa sẵn sàng.', 502);
      const responseHeaders = new Headers({ 'Cache-Control': 'no-store', 'X-Correlation-ID': correlationId });
      for (const name of ['content-type', 'x-correlation-id', 'retry-after']) { const value = upstream.headers.get(name); if (value) responseHeaders.set(name, value); }
      for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append('Set-Cookie', cookie);
      return new Response(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status, headers: responseHeaders });
    } catch { return failure('UPSTREAM_UNAVAILABLE', 'Chưa kết nối được máy chủ. Vui lòng thử lại sau.', 503); }
  };
}
