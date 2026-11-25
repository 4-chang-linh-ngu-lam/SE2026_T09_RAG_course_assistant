'use client';
import Link from 'next/link';
import type { ComponentProps } from 'react';
import { routes } from '@/config/routes';
import { dataMode } from '@/lib/data';
import { isRouteAvailable } from '@/lib/route-availability';

export default function AvailableLink(props: ComponentProps<typeof Link>) {
  const path = typeof props.href === 'string' ? props.href.split(/[?#]/)[0] : props.href.pathname;
  const route = routes.find(item => new RegExp(`^${item.path.replace(/:[\w]+/g, '[^/]+')}/?$`).test(path ?? ''));
  if (route && !isRouteAvailable(route.id, dataMode)) return null;
  return <Link {...props} />;
}
