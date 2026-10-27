export type TutorStopOutcome =
  | {kind: 'confirmed'}
  | {kind: 'not-started'}
  | {kind: 'unconfirmed'; error: unknown}
  | {kind: 'stale'};
/** Local cancellation is immediate; a failed remote ACK is never treated as confirmation. */
export async function stopTutorStream(options: {
  conversationId: string | null;
  stopLocally(): void;
  stopRemote(conversationId: string): Promise<void>;
  isCurrent(): boolean;
}): Promise<TutorStopOutcome> {
  options.stopLocally();
  if (!options.conversationId) return options.isCurrent() ? {kind: 'not-started'} : {kind: 'stale'};
  try {
    await options.stopRemote(options.conversationId);
  } catch (error) {
    return options.isCurrent() ? {kind: 'unconfirmed', error} : {kind: 'stale'};
  }
  return options.isCurrent() ? {kind: 'confirmed'} : {kind: 'stale'};
}
