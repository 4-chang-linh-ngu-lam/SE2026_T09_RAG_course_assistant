import type { NotificationItem } from './domain';
import { ApiError, errorMessage } from './api/errors';

export type NotificationReadTarget =
  | { readonly kind: 'one'; readonly id: string }
  | { readonly kind: 'all'; readonly ids: readonly string[] };
export type NotificationSnapshotRequest = {
  readonly actorId: string;
  readonly requestId: number;
  readonly purpose: 'refresh' | 'reconcile';
};
export type NotificationReadIssue = {
  readonly message: string;
  readonly outcome: 'rejected' | 'unknown';
  readonly target: NotificationReadTarget;
};
export type NotificationReadState = {
  readonly actorId: string;
  readonly items: readonly Readonly<NotificationItem>[];
  readonly unreadCount: number;
  readonly busy: boolean;
  readonly reconciling: boolean;
  readonly issue: NotificationReadIssue | null;
  readonly snapshotError: string | null;
};
export type NotificationReadResult = 'confirmed' | 'rejected' | 'unknown' | 'ignored';
export type NotificationReadDependencies = {
  actorId: string;
  markOne(id: string): Promise<void>;
  markAll(): Promise<void>;
  // Return a fresh response through receiveSnapshot(items, request), or report its failure
  // with rejectSnapshot. A routine incoming snapshot cannot resolve an unknown mutation.
  reload(request: NotificationSnapshotRequest): void | Promise<void>;
};
export interface NotificationReadController {
  getState(): NotificationReadState;
  subscribe(listener: () => void): () => void;
  receiveSnapshot(items: readonly NotificationItem[], request?: NotificationSnapshotRequest): boolean;
  rejectSnapshot(error: unknown, request: NotificationSnapshotRequest): void;
  markOne(id: string): Promise<NotificationReadResult>;
  markAll(): Promise<NotificationReadResult>;
  retry(): Promise<NotificationReadResult>;
  refresh(): NotificationSnapshotRequest | null;
  reconcile(): NotificationSnapshotRequest | null;
  dispose(): void;
}

/** Actor-bound read state, independent of React, routing and concrete data adapters. */
export function createNotificationReadController(deps: NotificationReadDependencies): NotificationReadController {
  const actorId = deps.actorId;
  const listeners = new Set<() => void>();
  const acknowledged = new Set<string>();
  let incoming: NotificationItem[] = [];
  let issue: NotificationReadIssue | null = null;
  let snapshotError: string | null = null;
  let busy = false;
  let disposed = false;
  let operation = 0;
  let snapshotSequence = 0;
  let activeSnapshot: NotificationSnapshotRequest | null = null;
  let state: NotificationReadState = derive();

  function derive(): NotificationReadState {
    const items = incoming.map(item => Object.freeze({ ...item, isRead: item.isRead || acknowledged.has(item.id) }));
    return Object.freeze({ actorId, items: Object.freeze(items), unreadCount: items.filter(item => !item.isRead).length,
      busy, reconciling: activeSnapshot?.purpose === 'reconcile', issue, snapshotError });
  }
  function emit() {
    if (disposed) return;
    state = derive();
    for (const listener of [...listeners]) listener();
  }
  function matches(request: NotificationSnapshotRequest) {
    return !disposed && request.actorId === actorId && activeSnapshot?.requestId === request.requestId
      && activeSnapshot.purpose === request.purpose;
  }
  function rejectSnapshot(error: unknown, request: NotificationSnapshotRequest) {
    if (!matches(request)) return;
    activeSnapshot = null;
    snapshotError = errorMessage(error);
    emit();
  }
  function requestSnapshot(purpose: NotificationSnapshotRequest['purpose']) {
    if (disposed || !actorId) return null;
    const request = Object.freeze({ actorId, requestId: ++snapshotSequence, purpose });
    activeSnapshot = request;
    snapshotError = null;
    emit();
    try {
      const result = deps.reload(request);
      if (result) void result.catch(error => rejectSnapshot(error, request));
    } catch (error) { rejectSnapshot(error, request); }
    return request;
  }
  function reconcile() {
    if (disposed || busy || issue?.outcome !== 'unknown') return null;
    if (activeSnapshot?.purpose === 'reconcile') return activeSnapshot;
    return requestSnapshot('reconcile');
  }
  function receiveSnapshot(items: readonly NotificationItem[], request?: NotificationSnapshotRequest) {
    if (disposed || (request && !matches(request))) return false;
    const byId = new Map<string, NotificationItem>();
    for (const item of items) if (actorId && item.userId === actorId) byId.set(item.id, { ...item });
    incoming = [...byId.values()];
    snapshotError = null;
    if (request) {
      activeSnapshot = null;
      if (request.purpose === 'reconcile' && issue?.outcome === 'unknown') {
        const ids = issue.target.kind === 'one' ? [issue.target.id] : issue.target.ids;
        const stillUnread = incoming.some(item => ids.includes(item.id) && !item.isRead);
        // Missing rows no longer expose a retryable target. Do not manufacture a read receipt.
        issue = stillUnread ? Object.freeze({ ...issue, outcome: 'rejected' as const,
          message: 'Chưa ghi nhận đầy đủ trạng thái đã đọc. Bạn có thể kiểm tra nội dung và thử lại.' }) : null;
      }
    }
    if (issue?.outcome === 'rejected') {
      const ids = issue.target.kind === 'one' ? [issue.target.id] : issue.target.ids;
      if (!incoming.some(item => ids.includes(item.id) && !item.isRead && !acknowledged.has(item.id))) issue = null;
    }
    emit();
    return true;
  }
  async function execute(target: NotificationReadTarget): Promise<NotificationReadResult> {
    if (disposed || !actorId || busy || issue?.outcome === 'unknown' || activeSnapshot?.purpose === 'reconcile') return 'ignored';
    const unread = state.items.filter(item => !item.isRead);
    const ids = target.kind === 'one' ? [target.id] : [...target.ids];
    if (!ids.length || ids.some(id => !unread.some(item => item.id === id))) return 'ignored';
    const requestOperation = ++operation;
    busy = true;
    issue = null;
    emit();
    const current = () => !disposed && operation === requestOperation;
    try {
      if (target.kind === 'one') await deps.markOne(target.id);
      else await deps.markAll();
      if (!current()) return 'ignored';
      for (const id of ids) acknowledged.add(id);
      busy = false;
      emit();
      requestSnapshot('refresh');
      return 'confirmed';
    } catch (error) {
      if (!current()) return 'ignored';
      const outcome = error instanceof ApiError && error.outcome === 'unknown' ? 'unknown' : 'rejected';
      issue = Object.freeze({ message: errorMessage(error), outcome, target });
      busy = false;
      emit();
      return outcome;
    }
  }
  function markOne(id: string) { return execute(Object.freeze({ kind: 'one' as const, id })); }
  function markAll() {
    return execute(Object.freeze({ kind: 'all' as const, ids: Object.freeze(state.items.filter(item => !item.isRead).map(item => item.id)) }));
  }
  return {
    getState: () => state,
    subscribe(listener) { if (disposed) return () => {}; listeners.add(listener); return () => { listeners.delete(listener); }; },
    receiveSnapshot,
    rejectSnapshot,
    markOne,
    markAll,
    retry() { return !issue || issue.outcome === 'unknown' ? Promise.resolve('ignored') : issue.target.kind === 'one' ? markOne(issue.target.id) : markAll(); },
    refresh() { return busy ? null : issue?.outcome === 'unknown' ? reconcile() : requestSnapshot('refresh'); },
    reconcile,
    dispose() {
      if (disposed) return;
      disposed = true;
      operation++;
      snapshotSequence++;
      activeSnapshot = null;
      incoming = [];
      acknowledged.clear();
      issue = null;
      snapshotError = null;
      busy = false;
      listeners.clear();
      state = derive();
    },
  };
}
