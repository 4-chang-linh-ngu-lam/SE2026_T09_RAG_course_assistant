import { createHmac, timingSafeEqual } from 'node:crypto';
import { isIP } from 'node:net';

export const CLIENT_CONTEXT_HEADER = 'x-lumi-client-context';
const MAX_AGE_SECONDS = 30;
function validSecret(secret) { return typeof secret === 'string' && secret.length >= 32; }
function address(ip) {
  if (typeof ip !== 'string' || ip.includes('%')) throw new Error('Invalid client address');
  const value = ip.startsWith('::ffff:') && isIP(ip.slice(7)) === 4 ? ip.slice(7) : ip;
  if (!isIP(value)) throw new Error('Invalid client address');
  return value;
}
export function signClientContext(ip, method, path, secret, now = Date.now()) {
  if (!validSecret(secret)) throw new Error('CORE_PROXY_SECRET must contain at least 32 characters');
  const payload = Buffer.from(JSON.stringify({ v: 1, ip: address(ip), at: Math.floor(now / 1000), method, path })).toString('base64url');
  return payload + '.' + createHmac('sha256', secret).update(payload).digest('hex');
}
export function verifyClientContext(value, method, path, secret, now = Date.now()) {
  if (!validSecret(secret) || typeof value !== 'string' || value.length > 1024) return false;
  try {
    const [payload, signature, extra] = value.split('.');
    if (extra !== undefined || !/^[A-Za-z0-9_-]+$/.test(payload) || !/^[a-f0-9]{64}$/.test(signature)) return false;
    const expected = createHmac('sha256', secret).update(payload).digest();
    if (!timingSafeEqual(Buffer.from(signature, 'hex'), expected)) return false;
    const claim = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return claim.v === 1 && Number.isInteger(claim.at) && Math.abs(Math.floor(now / 1000) - claim.at) <= MAX_AGE_SECONDS
      && claim.method === method && claim.path === path && address(claim.ip) === claim.ip;
  } catch { return false; }
}
export function attestClientRequest(request, secret, now = Date.now()) {
  // Always overwrite client-supplied metadata. Forwarded IP headers are not a
  // trust source: this entry point is the browser-facing Node HTTP listener.
  delete request.headers[CLIENT_CONTEXT_HEADER];
  delete request.headers['x-forwarded-for'];
  delete request.headers['x-real-ip'];
  const path = new URL(request.url ?? '/', 'http://internal').pathname;
  if (path.startsWith('/api/')) request.headers[CLIENT_CONTEXT_HEADER] = signClientContext(request.socket.remoteAddress, request.method, path, secret, now);
}
