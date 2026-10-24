const listeners = new Set<() => void>();
// Adapter-independent session loss notification. No credentials cross this boundary.
export function onAuthenticationLost(listener: () => void): () => void { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function notifyAuthenticationLost(): void { for (const listener of listeners) listener(); }
