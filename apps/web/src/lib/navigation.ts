import { routes, type RouteDefinition } from '@/config/routes';
import type { Role } from './domain';
export const SAFE_ROUTE_QUERY_KEYS = new Set(['version', 'page', 'locator', 'section', 'conversationId', 'mode', 'format', 'search', 'sort', 'question', 'compose', 'postId', 'commentId']);
export function withSafeRouteQuery(path: string, values: Readonly<Record<string, string | undefined>>): string {
  const query = new URLSearchParams();
  for (const key of SAFE_ROUTE_QUERY_KEYS) if (values[key] !== undefined) query.set(key, values[key]!);
  const encoded = query.toString();
  return path + (encoded ? `?${encoded}` : '');
}
export function matchRoute(path: string): RouteDefinition | undefined {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || /%2f|%5c/i.test(path)) return undefined;
  const pathname = path.split(/[?#]/)[0];
  if (pathname.split('/').some(x => x === '.' || x === '..')) return undefined;
  const sorted = [...routes].sort((a, b) => a.path.split(':').length - b.path.split(':').length);
  return sorted.find(r => new RegExp('^' + r.path.replace(/:[a-zA-Z]+/g, '[a-zA-Z0-9_-]+') + '/?$').test(pathname));
}
export function safeReturnTo(path: string | null, roles: readonly Role[], fallback: string) {
  const match = path ? matchRoute(path) : undefined;
  if (!match || match.allowedRoles.includes('public' as never) || !match.allowedRoles.some(r => roles.includes(r as Role))) return fallback;
  const withoutFragment = path!.split('#')[0];
  const question = withoutFragment.indexOf('?');
  const pathname = question < 0 ? withoutFragment : withoutFragment.slice(0, question);
  const query = new URLSearchParams(question < 0 ? '' : withoutFragment.slice(question + 1));
  return withSafeRouteQuery(pathname, Object.fromEntries(query));
}
export function canOpenRoute(route: RouteDefinition, roles: readonly Role[]) { return route.allowedRoles.some(role => role === 'public' || roles.includes(role)); }
