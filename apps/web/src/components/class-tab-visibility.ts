'use client';
import { useLayoutEffect, useRef } from 'react';

type HorizontalBounds = { viewportLeft: number; viewportRight: number; tabLeft: number; tabRight: number };
export function classTabScrollDelta(bounds: HorizontalBounds): number {
  if (bounds.tabLeft < bounds.viewportLeft || bounds.tabRight - bounds.tabLeft > bounds.viewportRight - bounds.viewportLeft) return bounds.tabLeft - bounds.viewportLeft;
  if (bounds.tabRight > bounds.viewportRight) return bounds.tabRight - bounds.viewportRight;
  return 0;
}

// Reveal only inside the tab strip; scrollIntoView would also move the page.
export function useCurrentClassTabVisibility(activeTab: string | null, classKey: string) {
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const nav = ref.current;
    if (!nav) return;
    const reveal = () => {
      const active = nav.querySelector<HTMLElement>('[aria-current="page"]');
      if (!active) return;
      const viewport = nav.getBoundingClientRect(), tab = active.getBoundingClientRect();
      const viewportLeft = viewport.left + nav.clientLeft;
      const delta = classTabScrollDelta({ viewportLeft, viewportRight: viewportLeft + nav.clientWidth, tabLeft: tab.left, tabRight: tab.right });
      if (delta) nav.scrollLeft += delta;
    };
    reveal();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(reveal);
    observer.observe(nav);
    return () => observer.disconnect();
  }, [activeTab, classKey]);
  return ref;
}
