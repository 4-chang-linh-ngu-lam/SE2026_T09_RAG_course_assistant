'use client';
import {NavigationLink} from '@/components/navigation-link';
import {Icon} from '@/components/ui';
import './notification-bell.css';

export function NotificationBellView({unreadCount,syncing,error}:{unreadCount:number|null;syncing:boolean;error:boolean}){
  const label=unreadCount===null?'Thông báo · chưa tải được số chưa đọc':unreadCount>0?`Thông báo · ${unreadCount} chưa đọc`:'Thông báo';
  return <NavigationLink href="/notifications" className="icon-button lumi-notification-bell" aria-label={label} title={error?'Thông báo · dữ liệu có thể chưa cập nhật':label}>
    <Icon name="bell"/>
    {unreadCount!==null&&unreadCount>0&&<span className="lumi-notification-bell-badge" aria-hidden="true">{unreadCount>99?'99+':unreadCount}</span>}
    {error&&<span className="lumi-notification-bell-warning" aria-hidden="true"/>}
    <span className="sr-only">{syncing?'Đang đồng bộ. ':''}{error?'Chưa đồng bộ được dữ liệu mới nhất.':''}</span>
  </NavigationLink>;
}
