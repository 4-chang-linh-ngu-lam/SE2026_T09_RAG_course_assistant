'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { adapter } from '@/lib/data';
import type { NotificationItem, User, WorkspaceData } from '@/lib/domain';
import { ApiError } from '@/lib/api/errors';
import { matchRoute, canOpenRoute } from '@/lib/navigation';
import { createNotificationReadController, type NotificationReadController, type NotificationReadState, type NotificationSnapshotRequest } from '@/lib/notification-read-controller';

const emptyState = (actorId: string): NotificationReadState => ({ actorId, items: [], unreadCount: 0, busy: false, reconciling: false, issue: null, snapshotError: null });

/** Business controller for the AGY-authored, controlled NotificationCenter UI. */
export function useNotificationState(data: WorkspaceData | null, user: User, reloadParent: () => void) {
  const router = useRouter();
  const actorId = user.id;
  const [state, setState] = useState<NotificationReadState>(() => emptyState(actorId));
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [accessNotice, setAccessNotice] = useState<string | null>(null);
  const controllerRef = useRef<NotificationReadController | null>(null);
  const snapshotRef = useRef(data);
  snapshotRef.current = data;
  const generation = useRef(0);

  useEffect(() => {
    const expected = ++generation.current;
    let controller: NotificationReadController;
    const receive = async (ticket: NotificationSnapshotRequest) => {
      try {
        const response = await adapter.workspace.load('account.notifications', {});
        if (generation.current !== expected) return;
        if (response.kind === 'unavailable') throw new ApiError('UNAVAILABLE', response.message, 503);
        controller.receiveSnapshot(
          response.kind === 'ready' ? response.notifications ?? [] : [],
          ticket,
          response.kind === 'ready' ? response.notificationUnreadCount : undefined,
        );
      } catch (error) { if (generation.current === expected) controller.rejectSnapshot(error, ticket); }
    };
    controller = createNotificationReadController({ actorId, markOne: id => adapter.notifications.markAsRead(id), markAll: () => adapter.notifications.markAllAsRead(), reload: receive });
    controllerRef.current = controller;
    const unsubscribe = controller.subscribe(() => { if (generation.current === expected) setState(controller.getState()); });
    const snapshot = snapshotRef.current;
    controller.receiveSnapshot(
      snapshot?.kind === 'ready' ? snapshot.notifications ?? [] : [],
      undefined,
      snapshot?.kind === 'ready' ? snapshot.notificationUnreadCount : undefined,
    );
    setState(controller.getState()); setFilter('all'); setSelectedId(null); setAccessNotice(null);
    return () => { ++generation.current; unsubscribe(); controller.dispose(); if (controllerRef.current === controller) controllerRef.current = null; };
  }, [actorId]);

  useEffect(() => { if (data?.kind === 'ready') controllerRef.current?.receiveSnapshot(data.notifications ?? [], undefined, data.notificationUnreadCount); else if (data?.kind === 'empty') controllerRef.current?.receiveSnapshot([]); }, [data, actorId]);

  const currentState = state.actorId === actorId ? state : emptyState(actorId);
  const items = filter === 'unread' ? currentState.items.filter(item => !item.isRead) : currentState.items;
  const selected = items.find(item => item.id === selectedId) ?? items[0] ?? null;
  function select(id: string) {
    const item = currentState.items.find(item => item.id === id);
    if (!item) return;
    setSelectedId(id); setAccessNotice(null);
    if (!item.isRead) void controllerRef.current?.markOne(id);
  }
  function navigate(item: Readonly<NotificationItem>) {
    if (!item.targetHref || !currentState.items.some(row => row.id === item.id)) return;
    const route = matchRoute(item.targetHref);
    if (!route) { setAccessNotice('Đường dẫn không tồn tại trên hệ thống.'); return; }
    if (!canOpenRoute(route, user.roles)) { setAccessNotice('Bạn không có quyền truy cập vào nội dung này.'); return; }
    setAccessNotice(null); router.push(item.targetHref);
  }
  return {
    loadState: !data ? 'loading' as const : data.kind === 'unavailable' ? 'unavailable' as const : 'ready' as const,
    loadMessage: data?.kind === 'unavailable' || data?.kind === 'empty' ? data.message : undefined,
    items, selected, filter, totalCount: currentState.items.length, unreadCount: currentState.unreadCount,
    busy: currentState.busy || currentState.reconciling, issue: currentState.issue, snapshotError: currentState.snapshotError, accessNotice,
    onSelect: select, onFilter: setFilter, onNavigate: navigate,
    onMarkAll: () => { void controllerRef.current?.markAll(); },
    onRetry: () => { void controllerRef.current?.retry(); },
    onReconcile: () => { controllerRef.current?.reconcile(); },
    onRefresh: () => { if (!data || data.kind !== 'ready') reloadParent(); else controllerRef.current?.refresh(); },
  };
}
