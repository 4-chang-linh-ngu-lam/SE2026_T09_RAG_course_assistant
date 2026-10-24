import type { DataAdapter } from './port';
import type { User } from '../domain';
import { createHttpClient } from '../api/http';
import {createDocumentHttpClient} from '../api/document-http';
import { ApiError } from '../api/errors';
import { decodeCode, decodeMutation, decodeRequest, decodeRequests, decodeToken, decodeUser } from '../api/decoders';
import { notifyAuthenticationLost } from '../auth-events';

// Access tokens live only in memory; refresh cookies remain HttpOnly. Credential
// requests are serialized so an older response cannot replace a newer login cookie.
type SessionOptions = { fetcher?: typeof fetch; now?: () => number; onLost?: () => void };
export function createLiveCoreSession(options: SessionOptions = {}) {
  const now = options.now ?? Date.now;
  const lost = options.onLost ?? notifyAuthenticationLost;
  let token: string | null = null, expiresAt = 0, generation = 0, suspended = false;
  let actorId: string | null = null;
  let recoveryIdentity: { field: 'username' | 'email'; value: string } | null = null;
  let credentialQueue: Promise<unknown> = Promise.resolve();
  let refreshing: { generation: number; promise: Promise<void> } | null = null;
  let restoring: { generation: number; promise: Promise<User | null> } | null = null;
  const http = (credential: string | null) => createHttpClient(() => credential, options.fetcher);
  const changed = (mutation = false) => new ApiError('SESSION_CHANGED', 'Phiên đăng nhập đã thay đổi. Hãy mở lại nội dung trong phiên hiện tại.', 401, mutation ? 'unknown' : 'rejected');
  function check(expected: number, mutation = false) { if (expected !== generation || suspended) throw changed(mutation); }
  function clear(expected: number, notify = true) {
    if (expected !== generation) return;
    token = null; expiresAt = 0; suspended = true; recoveryIdentity = null; actorId = null; generation++;
    if (notify) lost();
  }
  function serialize<T>(run: () => Promise<T>): Promise<T> {
    const result = credentialQueue.then(run, run);
    credentialQueue = result.catch(() => undefined);
    return result;
  }
  function install(value: ReturnType<typeof decodeToken>) { token = value.access_token; expiresAt = now() + value.expires_in * 1000; }
  function refresh(expected: number): Promise<void> {
    if (refreshing?.generation === expected) return refreshing.promise;
    const promise = serialize(async () => {
      check(expected);
      try {
        const value = decodeToken(await http(null)('refresh')); check(expected);
        if (actorId) {
          const user = decodeUser(await http(value.access_token)('me')); check(expected);
          if (user.id !== actorId || user.status !== 'ACTIVE') { clear(expected); throw changed(); }
        }
        install(value);
      }
      catch (error) { if (error instanceof ApiError && error.status === 401) clear(expected); throw error; }
    });
    const flight = { generation: expected, promise };
    refreshing = flight;
    void promise.finally(() => { if (refreshing === flight) refreshing = null; }).catch(() => undefined);
    return promise;
  }
  async function authenticated<T>(run: (request: ReturnType<typeof createHttpClient>) => Promise<T>, mutation = false, reconciling = false): Promise<T> {
    const expected = generation;
    check(expected);
    if (recoveryIdentity && !reconciling) throw new ApiError('SESSION_UNCONFIRMED', 'Hãy kiểm tra lại phiên đăng nhập trước khi tiếp tục.', 403);
    if (!token || now() >= expiresAt) await refresh(expected);
    check(expected);
    const captured = token;
    try { const value = await run(http(captured)); check(expected, mutation); return value; }
    catch (error) { if (error instanceof ApiError && error.status === 401 && error.code !== 'SESSION_CHANGED') clear(expected); throw error; }
  }
  async function logout(all: boolean): Promise<void> {
    const captured = token, capturedActorId = actorId, expired = !token || now() >= expiresAt, unconfirmed = recoveryIdentity !== null, expected = ++generation;
    token = null; expiresAt = 0; suspended = true; recoveryIdentity = null; actorId = null;
    await serialize(async () => {
      try {
        if (!all) { await http(captured)('logout'); return; }
        if (unconfirmed) {
          await http(null)('logout');
          throw new ApiError('SESSION_UNCONFIRMED', 'Đã thoát trên thiết bị này. Cần xác minh tài khoản trước khi thu hồi mọi phiên.', 403);
        }
        // Keep credentials private to this queued sign-out. A later login must
        // wait for cookie rotation/revocation, but never receive this token.
        let credential = captured, refreshed = false;
        const renew = async () => {
          const value = decodeToken(await http(null)('refresh'));
          if (capturedActorId) {
            const user = decodeUser(await http(value.access_token)('me'));
            if (user.id !== capturedActorId || user.status !== 'ACTIVE') throw changed();
          }
          return value.access_token;
        };
        if (expired) { credential = await renew(); refreshed = true; }
        try { await http(credential)('logoutAll'); }
        catch (error) {
          // A definite authentication rejection is safe to reconcile once;
          // timeouts/5xx/unknown mutation outcomes are never replayed.
          if (refreshed || !(error instanceof ApiError) || error.status !== 401) throw error;
          credential = await renew();
          await http(credential)('logoutAll');
        }
      }
      finally { if (expected === generation) { token = null; expiresAt = 0; } }
    });
  }
  async function resetCredential(id: 'activate' | 'reset', body: unknown): Promise<void> {
    generation++; token = null; expiresAt = 0; suspended = true; recoveryIdentity = null; actorId = null;
    lost();
    await serialize(async () => { await http(null)(id, { body }); });
  }
  const identity: DataAdapter['identity'] = {
    restore() {
      if (suspended) return Promise.resolve(null);
      const expected = generation;
      if (restoring?.generation === expected) return restoring.promise;
      const promise = authenticated(async request => {
        const user = decodeUser(await request('me'));
        check(expected);
        if (recoveryIdentity && user[recoveryIdentity.field]?.trim().toLowerCase() !== recoveryIdentity.value) {
          clear(expected);
          throw changed();
        }
        recoveryIdentity = null;
        actorId = user.id;
        return user;
      }, false, true).catch(error => {
        if (error instanceof ApiError && (error.status === 401 || expected !== generation)) return null;
        throw error;
      });
      const flight = { generation: expected, promise };
      restoring = flight;
      void promise.finally(() => { if (restoring === flight) restoring = null; }).catch(() => undefined);
      return promise;
    },
    login(input) {
      const expected = ++generation;
      token = null; expiresAt = 0; suspended = false; actorId = null;
      recoveryIdentity = 'username' in input && input.username !== undefined
        ? { field: 'username', value: input.username.trim().toLowerCase() }
        : { field: 'email', value: input.email!.trim().toLowerCase() };
      return serialize(async () => {
        check(expected);
        let accepted = false;
        try {
          const value = decodeMutation(decodeToken, await http(null)('login', { body: input }));
          check(expected); install(value); accepted = true;
          const user = decodeUser(await http(token)('me'));
          check(expected);
          if (user.status !== 'ACTIVE') { clear(expected); throw new ApiError('FORBIDDEN', 'Tài khoản hiện không hoạt động.', 403); }
          recoveryIdentity = null;
          actorId = user.id;
          return user;
        } catch (error) {
          if (expected === generation) {
            const uncertain = error instanceof ApiError && (error.outcome === 'unknown' || accepted && (error.status === 0 || error.status >= 500));
            token = null; expiresAt = 0; suspended = !uncertain;
            if (uncertain && error instanceof ApiError) error.outcome = 'unknown';
            if (!uncertain) recoveryIdentity = null;
          }
          throw error;
        }
      });
    },
    logout: () => logout(false), logoutAll: () => logout(true),
    updateProfile: name => authenticated(async request => decodeMutation(decodeUser, await request('updateProfile', { body: { display_name: name } })), true),
    activate: input => resetCredential('activate', input),
    async forgot(email) { await http(null)('forgot', { body: { email } }); },
    reset: (code, newPassword) => resetCredential('reset', { token: code, new_password: newPassword }),
    acceptInvitation: (code, newPassword) => resetCredential('reset', { token: code, new_password: newPassword }),
    requests: cursor => authenticated(async request => decodeRequests(await request('dataRequests', { cursor }))),
    createRequest: (type, reason) => authenticated(async request => decodeMutation(decodeRequest, await request('createDataRequest', { body: { type, ...(reason ? { reason } : {}) } })), true),
    createStudent: (username, displayName) => authenticated(async request => decodeMutation(decodeCode, await request('createStudent', { body: { username, ...(displayName ? { display_name: displayName } : {}) } })), true),
    issueCode: (userId, identityVerified) => authenticated(async request => decodeMutation(decodeCode, await request('issueStudentCode', { userId, body: identityVerified ? { identity_verified: true } : {} })), true),
  };
  return {identity, getActorId: () => actorId,
    documentAuthenticated:<T>(run:(request:ReturnType<typeof createDocumentHttpClient>)=>Promise<T>,mutation=false)=>authenticated(async()=>{const captured=token;return run(createDocumentHttpClient(()=>captured,options.fetcher));},mutation),
    authenticated: <T>(run: (request: ReturnType<typeof createHttpClient>) => Promise<T>, mutation = false) => authenticated(run, mutation)};
}

export function createLiveIdentity(options: SessionOptions = {}): DataAdapter['identity'] {
  return createLiveCoreSession(options).identity;
}
