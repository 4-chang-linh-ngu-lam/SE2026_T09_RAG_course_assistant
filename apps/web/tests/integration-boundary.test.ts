import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assertDataSource, resolveDataMode } from '../config/data-mode.mjs';
import configure from '../next.config.mjs';
import { inspectSource } from '../scripts/boundary-policy.mjs';
import { findFixtureLeaks } from '../scripts/release-policy.mjs';
import { createHttpClient } from '../src/lib/api/http';
import { createCoreProxy } from '../src/lib/api/proxy';
import { ApiError } from '../src/lib/api/errors';
import { decodeMutation, decodeUser } from '../src/lib/api/decoders';
import { isImplementedOperation } from '../src/lib/api/operations';
import { safeReturnTo } from '../src/lib/navigation';

test('production rejects mock, including actual Next config', () => {
  assert.equal(resolveDataMode(undefined, true), 'live');
  assert.throws(() => resolveDataMode('mock', true));
  assert.throws(() => resolveDataMode('typo', false));
  const previous = process.env.NEXT_PUBLIC_DATA_MODE;
  try { process.env.NEXT_PUBLIC_DATA_MODE = 'mock'; assert.throws(() => configure('phase-production-build')); }
  finally { if (previous === undefined) delete process.env.NEXT_PUBLIC_DATA_MODE; else process.env.NEXT_PUBLIC_DATA_MODE = previous; }
});
test('boundary analysis rejects fixture imports, bypasses and persisted credentials', () => {
  assert.ok(inspectSource('src/features/example.ts', "import { users } from '../../dev/mocks/fixtures';").length);
  assert.ok(inspectSource('app/example/page.tsx', "fetch('/api/v1/users/me');").length);
  assert.ok(inspectSource('src/features/example.ts', "window.localStorage.setItem('access', token);").length);
  assert.ok(inspectSource('src/features/example.ts', "import { adapter } from '@data-adapter';").length);
  assert.ok(inspectSource('src/features/example.ts', "require('../../dev/mocks/fixtures');").length);
  assert.ok(inspectSource('src/features/example.ts', "import(variablePath);").length);
  assert.equal(inspectSource('src/features/example.ts', "import { adapter } from '@/lib/data';").length, 0);
});
test('adapter provenance cannot silently differ from selected live mode', () => {
  assert.throws(() => assertDataSource('live', 'mock', false));
  assert.throws(() => assertDataSource('mock', 'mock', true));
  assert.doesNotThrow(() => assertDataSource('live', 'live', true));
});
test('schema mismatch after a successful mutation is an unknown outcome', () => {
  assert.throws(() => decodeMutation(decodeUser, { unexpected: true }), (e: unknown) => e instanceof ApiError && e.outcome === 'unknown');
});
test('release scanner detects a fixture leak, not just a source filename', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'lumi-release-'));
  try { await writeFile(join(dir, 'chunk.js'), 'const data="__LUMI_PREVIEW_FIXTURE_CANARY_20261018__";'); assert.equal((await findFixtureLeaks(dir)).length, 1); }
  finally { await rm(dir, { recursive: true, force: true }); }
});
test('transport sends exact login credentials without generic idempotency, includes cookie, no cache', async () => {
  let call: { url: string; options?: RequestInit } | null = null;
  const client = createHttpClient(() => null, (async (url, options) => { call = { url: String(url), options }; return Response.json({ ok: true }); }) as typeof fetch);
  await client('login', { body: { username: 'user', password: 'password' } });
  assert.equal(call!.url, '/api/v1/auth/login');
  assert.equal(call!.options!.credentials, 'include'); assert.equal(call!.options!.cache, 'no-store');
  assert.equal(new Headers(call!.options!.headers).has('Idempotency-Key'), false);
  assert.deepEqual(JSON.parse(String(call!.options!.body)), { username: 'user', password: 'password' });
});
test('network failure after mutation remains unknown, never retries or returns fixture success', async () => {
  let calls = 0; const client = createHttpClient(() => null, (async () => { calls++; throw new TypeError('offline'); }) as typeof fetch);
  await assert.rejects(() => client('createStudent', { body: { username: 'user' } }), (e: unknown) => e instanceof ApiError && e.outcome === 'unknown');
  assert.equal(calls, 1);
  await assert.rejects(() => client('me'), (e: unknown) => e instanceof ApiError && e.outcome === 'rejected');
});
test('invalid live response never becomes preview user data', () => {
  assert.throws(() => decodeUser({ id: 'x', roles: ['OWNER'], status: 'ACTIVE' }), ApiError);
});
test('unexpected successful HTTP status is not a confirmed mutation', async () => {
  const client = createHttpClient(() => null, (async () => Response.json({})) as typeof fetch);
  await assert.rejects(() => client('activate', { body: {} }), (e: unknown) => e instanceof ApiError && e.outcome === 'unknown');
});
test('configured public origin works behind an internal proxy URL', async () => {
  const proxy = createCoreProxy(() => 'http://core:8000', (async () => Response.json({})) as typeof fetch, () => 'https://school.example');
  const request = new Request('http://internal-next:3000/api/v1/auth/login', { method: 'POST', headers: { Origin: 'https://school.example' }, body: '{}' });
  assert.equal((await proxy(request, ['auth','login'])).status, 200);
  const missing = createCoreProxy(() => 'http://core:8000', fetch, () => undefined);
  assert.equal((await missing(request, ['auth','login'])).status, 503);
});
test('only implemented public Core operations enter the proxy', () => {
  assert.equal(isImplementedOperation('POST', '/auth/login'), true);
  assert.equal(isImplementedOperation('POST', '/auth/register'), false);
  assert.equal(isImplementedOperation('GET', '/classes'), true);
  assert.equal(isImplementedOperation('GET', '/internal/v1/classes/x/access'), false);
  assert.equal(isImplementedOperation('POST', '/admin/students/../../auth/login/activation-codes'), false);
});
test('proxy preserves backend cookies, origin, retry/correlation metadata without service keys', async () => {
  let forwarded: Headers | undefined;
  const proxy = createCoreProxy(() => 'http://core:8000', (async (url, init) => {
    assert.equal(String(url), 'http://core:8000/api/v1/auth/login'); forwarded = new Headers(init?.headers);
    const headers = new Headers({ 'X-Correlation-ID': 'correlation', 'Retry-After': '3' });
    headers.append('Set-Cookie', 'refresh_token=opaque; HttpOnly; Path=/api/v1/auth');
    return Response.json({ access_token: 'opaque' }, { headers });
  }) as typeof fetch);
  const response = await proxy(new Request('http://localhost:3000/api/v1/auth/login', { method: 'POST', headers: { Origin: 'http://localhost:3000', 'X-Service-Key': 'must-not-forward' }, body: '{}' }), ['auth','login']);
  assert.equal(response.status, 200); assert.equal(forwarded!.get('Origin'), 'http://localhost:3000'); assert.equal(forwarded!.has('X-Service-Key'), false);
  assert.equal(response.headers.getSetCookie().length, 1); assert.equal(response.headers.get('Cache-Control'), 'no-store'); assert.equal(response.headers.get('X-Correlation-ID'), 'correlation');
});
test('upstream outage produces 503, does not fall back to local data', async () => {
  const proxy = createCoreProxy(() => 'http://core:8000', (async () => { throw new TypeError('down'); }) as typeof fetch);
  const response = await proxy(new Request('http://localhost:3000/api/v1/users/me'), ['users','me']);
  assert.equal(response.status, 503); assert.equal((await response.json()).error.code, 'UPSTREAM_UNAVAILABLE');
});
test('missing configuration, cross-origin mutation and uncontracted paths are closed', async () => {
  let calls = 0; const fetcher = (async () => { calls++; return Response.json({}); }) as typeof fetch;
  assert.equal((await createCoreProxy(() => undefined, fetcher)(new Request('http://local/api/v1/users/me'), ['users','me'])).status, 503);
  assert.equal((await createCoreProxy(() => 'http://core', fetcher)(new Request('http://local/api/v1/auth/login', { method: 'POST', headers: { Origin: 'http://evil' } }), ['auth','login'])).status, 403);
  assert.equal((await createCoreProxy(() => 'http://core', fetcher)(new Request('http://local/api/v1/documents'), ['documents'])).status, 404); assert.equal(calls, 0);
});
test('return target rejects external URLs, unknown paths and wrong roles', () => {
  assert.equal(safeReturnTo('//evil/path', ['STUDENT'], '/student'), '/student');
  assert.equal(safeReturnTo('/admin/accounts', ['STUDENT'], '/student'), '/student');
  assert.equal(safeReturnTo('/student/classes/../../admin/accounts', ['STUDENT'], '/student'), '/student');
  assert.equal(safeReturnTo('/student/classes/class-1/documents', ['STUDENT'], '/student'), '/student/classes/class-1/documents');
});


test('Webpack and Turbopack resolve the same mode-specific adapter and keep output isolation', () => {
  const previous = process.env.NEXT_PUBLIC_DATA_MODE;
  try {
    for (const mode of ['live', 'mock']) {
      process.env.NEXT_PUBLIC_DATA_MODE = mode;
      const config = configure('phase-development-server');
      const expected = mode === 'mock' ? './dev/mocks/adapter.ts' : './src/lib/data/live.ts';
      assert.equal(config.turbopack.resolveAlias['@data-adapter'], expected);
      const webpack = { resolve: { alias: {} as Record<string, string> } };
      config.webpack(webpack);
      assert.ok(webpack.resolve.alias['@data-adapter$'].replaceAll('\\', '/').endsWith(expected.slice(1)));
      assert.equal(config.distDir, mode === 'mock' ? '.next-preview' : '.next');
    }
  } finally {
    if (previous === undefined) delete process.env.NEXT_PUBLIC_DATA_MODE; else process.env.NEXT_PUBLIC_DATA_MODE = previous;
  }
});
