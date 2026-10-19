import { routes, type RouteDefinition } from '@/config/routes';
import type { Role } from './domain';
export function matchRoute(path: string): RouteDefinition | undefined {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || /%2f|%5c/i.test(path)) return undefined;
  const pathname = path.split(/[?#]/)[0];
  if (pathname.split('/').some(x => x === '.' || x === '..')) return undefined;
  const sorted = [...routes].sort((a, b) => a.path.split(':').length - b.path.split(':').length);
  return sorted.find(r => new RegExp('^' + r.path.replace(/:[a-zA-Z]+/g, '[a-zA-Z0-9_-]+') + '/?$').test(pathname));
}
export function safeReturnTo(path: string | null, roles: readonly Role[], fallback: string) {
  const match = path ? matchRoute(path) : undefined;
  return match && !match.allowedRoles.includes('public' as never) && match.allowedRoles.some(r => roles.includes(r as Role)) ? path!.split(/[?#]/)[0] : fallback;
}
export function canOpenRoute(route: RouteDefinition, roles: readonly Role[]) { return route.allowedRoles.some(role => role === 'public' || roles.includes(role)); }
