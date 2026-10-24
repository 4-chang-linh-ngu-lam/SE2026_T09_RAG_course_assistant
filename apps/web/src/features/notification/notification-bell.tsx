'use client';
import {useNotificationSync} from '@/components/notification-sync-provider';
import {NotificationBellView} from './notification-bell-view';

export function NotificationBell(){
  const {state,loaded,syncing}=useNotificationSync();
  return <NotificationBellView unreadCount={loaded?state.unreadCount:null} syncing={syncing} error={Boolean(state.snapshotError)}/>;
}
