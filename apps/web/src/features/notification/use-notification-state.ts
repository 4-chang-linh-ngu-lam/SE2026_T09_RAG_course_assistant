'use client';
import {useState} from 'react';
import {useRouter} from 'next/navigation';
import type {NotificationItem,User,WorkspaceData} from '@/lib/domain';
import {matchRoute,canOpenRoute} from '@/lib/navigation';
import {useNotificationSync} from '@/components/notification-sync-provider';

export function useNotificationState(_data:WorkspaceData|null,user:User,_reloadParent:()=>void){
  const router=useRouter();
  const {state,loaded,syncing,lastSyncedAt,controller}=useNotificationSync();
  const [filter,setFilter]=useState<'all'|'unread'>('all');
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [accessNotice,setAccessNotice]=useState<string|null>(null);
  const items=filter==='unread'?state.items.filter(item=>!item.isRead):state.items;
  // An opened detail remains visible when its read acknowledgement removes the unread list row.
  const selected=state.items.find(item=>item.id===selectedId)??items[0]??null;
  function select(id:string){
    const item=state.items.find(row=>row.id===id);if(!item)return;
    setSelectedId(id);setAccessNotice(null);if(!item.isRead)void controller?.markOne(id);
  }
  function navigate(item:Readonly<NotificationItem>){
    const current=state.items.find(row=>row.id===item.id);
    if(!current?.targetHref)return;
    const route=matchRoute(current.targetHref.split('?')[0]);
    if(!route||!canOpenRoute(route,user.roles)){setAccessNotice('Bạn không có quyền mở nội dung này.');return;}
    setAccessNotice(null);router.push(current.targetHref);
  }
  return {
    loadState:loaded?'ready' as const:state.snapshotError?'unavailable' as const:'loading' as const,
    loadMessage:state.snapshotError??undefined,items,selected,filter,totalCount:state.items.length,unreadCount:state.unreadCount,
    busy:state.busy||state.reconciling,issue:state.issue,snapshotError:state.snapshotError,accessNotice,syncing,lastSyncedAt,
    onSelect:select,onFilter:setFilter,onNavigate:navigate,onMarkAll:()=>{void controller?.markAll();},
    onRetry:()=>{void controller?.retry();},onReconcile:()=>{controller?.reconcile();},onRefresh:()=>{controller?.refresh();},
  };
}
