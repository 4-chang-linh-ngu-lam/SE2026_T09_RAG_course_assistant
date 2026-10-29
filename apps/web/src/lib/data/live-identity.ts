import type { DataAdapter } from './port';
import type { User } from '../domain';
import { createHttpClient } from '../api/http';
import { ApiError } from '../api/errors';
import { decodeCode, decodeMutation, decodeRequest, decodeRequests, decodeToken, decodeUser } from '../api/decoders';
import { notifyAuthenticationLost } from '../auth-events';

export type LiveIdentitySession = {
  identity: DataAdapter['identity'];
  authenticated<T>(run: (request: ReturnType<typeof createHttpClient>) => Promise<T>, mutation?: boolean): Promise<T>;
  currentUser(): User | null;
  sessionGeneration(): number;
};

// Access tokens live only in memory; refresh cookies remain HttpOnly. Credential
// requests are serialized so an older response cannot replace a newer login cookie.
export function createLiveIdentitySession(options: { fetcher?: typeof fetch; now?: () => number; onLost?: () => void } = {}): LiveIdentitySession {
  const now = options.now ?? Date.now;
  const lost = options.onLost ?? notifyAuthenticationLost;
  let token: string | null = null, expiresAt = 0, generation = 0, suspended = false;
  let user: User | null = null;
  let credentialQueue: Promise<unknown> = Promise.resolve();
  let refreshing: { generation: number; promise: Promise<void> } | null = null;
  let restoring: { generation: number; promise: Promise<User | null> } | null = null;
  const http = (credential: string | null) => createHttpClient(() => credential, options.fetcher);
  const changed = (mutation = false) => new ApiError('SESSION_CHANGED', 'Phiên đăng nhập đã thay đổi. Hãy mở lại nội dung trong phiên hiện tại.', 401, mutation ? 'unknown' : 'rejected');
  function check(expected: number, mutation = false) { if (expected !== generation || suspended) throw changed(mutation); }
  function clear(expected: number, notify = true) {
    if (expected !== generation) return;
    token = null; expiresAt = 0; user = null; suspended = true; generation++;
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
      try { const value = decodeToken(await http(null)('refresh')); check(expected); install(value); }
      catch (error) { if (error instanceof ApiError && error.status === 401) clear(expected); throw error; }
    });
    const flight = { generation: expected, promise };
    refreshing = flight;
    void promise.finally(() => { if (refreshing === flight) refreshing = null; }).catch(() => undefined);
    return promise;
  }
  async function authenticated<T>(run: (request: ReturnType<typeof createHttpClient>) => Promise<T>, mutation = false): Promise<T> {
    const expected = generation;
    check(expected);
    if (!token || now() >= expiresAt) await refresh(expected);
    check(expected);
    const captured = token;
    try { const value = await run(http(captured)); check(expected, mutation); return value; }
    catch (error) { if (error instanceof ApiError && error.status === 401 && error.code !== 'SESSION_CHANGED') clear(expected); throw error; }
  }
  async function logout(all: boolean): Promise<void> {
    const captured = token, expected = ++generation;
    token = null; expiresAt = 0; user = null; suspended = true;
    await serialize(async () => {
      try { await http(captured)(all ? 'logoutAll' : 'logout'); }
      finally { if (expected === generation) { token = null; expiresAt = 0; user = null; } }
    });
  }
  const identity: DataAdapter['identity'] = {
    restore() {
      if (suspended) return Promise.resolve(null);
      if (user && token && now() < expiresAt) return Promise.resolve(user);
      const expected = generation;
      if (restoring?.generation === expected) return restoring.promise;
      const promise = authenticated(async request => {
        const current = decodeUser(await request('me'));
        check(expected);
        user = current;
        return current;
      }).catch(error => {
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
          token = null; expiresAt = 0; user = null; suspended = false;
      return serialize(async () => {
        check(expected);
        try {
          const value = decodeMutation(decodeToken, await http(null)('login', { body: input }));
          check(expected); install(value);
          const loggedInUser = decodeUser(await http(token)('me'));
          check(expected);
          if (loggedInUser.status !== 'ACTIVE') { clear(expected); throw new ApiError('FORBIDDEN', 'Tài khoản hiện không hoạt động.', 403); }
          user = loggedInUser;
          return loggedInUser;
        } catch (error) {
          if (expected === generation) {
            const mayHaveCreatedSession = token !== null || (error instanceof ApiError && error.outcome === 'unknown');
            token = null; expiresAt = 0; user = null; suspended = !mayHaveCreatedSession;
          }
          throw error;
        }
      });
    },
    logout: () => logout(false), logoutAll: () => logout(true),
    async updateProfile(name) {
      const expected = generation;
      const updated = await authenticated(async request =>
        decodeMutation(decodeUser, await request('updateProfile', { body: { display_name: name } })), true,
      );
      check(expected, true);
      user = updated;
      return updated;
    },
    async activate(input) { await http(null)('activate', { body: input }); },
    async forgot(email) { await http(null)('forgot', { body: { email } }); },
    async reset(code, newPassword) { await serialize(async () => { await http(null)('reset', { body: { token: code, new_password: newPassword } }); }); },
    async acceptInvitation(code, newPassword) { await serialize(async () => { await http(null)('reset', { body: { token: code, new_password: newPassword } }); }); },
    requests: cursor => authenticated(async request => decodeRequests(await request('dataRequests', { cursor }))),
    createRequest: (type, reason) => authenticated(async request => decodeMutation(decodeRequest, await request('createDataRequest', { body: { type, ...(reason ? { reason } : {}) } })), true),
    createStudent: (username, displayName) => authenticated(async request => decodeMutation(decodeCode, await request('createStudent', { body: { username, ...(displayName ? { display_name: displayName } : {}) } })), true),
    issueCode: (userId, identityVerified) => authenticated(async request => decodeMutation(decodeCode, await request('issueStudentCode', { userId, body: identityVerified ? { identity_verified: true } : {} })), true),
  };
  return { identity, authenticated, currentUser: () => user, sessionGeneration: () => generation };
}

export function createLiveIdentity(options: { fetcher?: typeof fetch; now?: () => number; onLost?: () => void } = {}): DataAdapter['identity'] {
  return createLiveIdentitySession(options).identity;
}
