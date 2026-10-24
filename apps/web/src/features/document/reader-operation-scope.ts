export interface ReaderOperationIdentity {
  readonly actorId: string;
  readonly classId: string;
  readonly documentId: string;
  readonly version: number;
  readonly page: number;
}
export interface ReaderOperationToken {
  readonly generation: number;
  readonly identity: ReaderOperationIdentity;
}
export interface ReaderOperationScope {
  enter(identity: ReaderOperationIdentity): ReaderOperationToken;
  isCurrent(token: ReaderOperationToken): boolean;
  invalidate(token?: ReaderOperationToken): void;
}
function identityKey(identity: ReaderOperationIdentity): string {
  return JSON.stringify([identity.actorId, identity.classId, identity.documentId, identity.version, identity.page]);
}
/** A page returning to the same identity still receives a new generation. */
export function createReaderOperationScope(): ReaderOperationScope {
  let current: ReaderOperationToken | null = null;
  let key: string | null = null;
  let generation = 0;
  return {
    enter(identity) {
      const nextKey = identityKey(identity);
      if (!current || key !== nextKey) {
        current = Object.freeze({generation: ++generation, identity: Object.freeze({...identity})});
        key = nextKey;
      }
      return current;
    },
    isCurrent(token) { return current === token; },
    invalidate(token) {
      // An old effect cleanup must not invalidate a newer rendered scope.
      if (token && current !== token) return;
      current = null;
      key = null;
    },
  };
}
export type ReaderOperationOutcome = 'confirmed' | 'failed' | 'stale';
/** Only the still-owned editor may react to an acknowledgement or failure. */
export async function settleReaderOperation<T>(options: {
  scope: ReaderOperationScope;
  token: ReaderOperationToken;
  work(): Promise<T>;
  confirmed(result: T): void;
  failed(error: unknown): void;
  settled?(): void;
}): Promise<ReaderOperationOutcome> {
  let result: T;
  try {
    result = await options.work();
  } catch (error) {
    if (!options.scope.isCurrent(options.token)) return 'stale';
    options.failed(error);
    if (options.scope.isCurrent(options.token)) options.settled?.();
    return 'failed';
  }
  if (!options.scope.isCurrent(options.token)) return 'stale';
  options.confirmed(result);
  if (options.scope.isCurrent(options.token)) options.settled?.();
  return 'confirmed';
}
