'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { RouteDefinition } from '@/config/routes';
import type { NotificationItem, Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { adapter, dataMode } from '@/lib/data';
import { matchRoute, canOpenRoute } from '@/lib/navigation';
import { Icon, StatePanel } from '@/components/ui';

type Props = {
  data: WorkspaceData | null;
  role: Role;
  params: RouteParams;
  reload(): void;
  route?: RouteDefinition;
  user?: User;
};

export function NotificationFeature({ data, role, reload }: Props) {
  const router = useRouter();
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [localNotifications, setLocalNotifications] = useState<NotificationItem[] | null>(null);
  const [accessNotice, setAccessNotice] = useState<string | null>(null);

  if (!data) return <StatePanel busy title="Đang tải thông báo…"/>;

  // In live mode, if data is unavailable, render honest unavailable state within designed structure
  if (data.kind === 'unavailable') {
    return (
      <div className="workspace-content">
        <div className="card padded">
          <div className="section-heading">
            <div>
              <h2>Thông báo</h2>
              <p className="muted">Trung tâm cập nhật học tập</p>
            </div>
            <button className="button" onClick={reload}>Thử lại</button>
          </div>
          <StatePanel title="Dịch vụ thông báo chưa sẵn sàng" message={data.message}>
            <button className="button" onClick={reload}>Tải lại</button>
          </StatePanel>
        </div>
      </div>
    );
  }

  if (data.kind === 'empty') {
    return (
      <div className="workspace-content">
        <div className="card padded">
          <div className="section-heading">
            <div>
              <h2>Thông báo</h2>
              <p className="muted">Trung tâm cập nhật học tập</p>
            </div>
            <button className="button" onClick={reload}>Tải lại</button>
          </div>
          <StatePanel title="Chưa có thông báo nào" message={data.message} />
        </div>
      </div>
    );
  }

  const items = localNotifications ?? data.notifications ?? [];
  const filtered = filter === 'unread' ? items.filter(n => !n.isRead) : items;
  const unreadCount = items.filter(n => !n.isRead).length;
  const current = items.find(n => n.id === (selectedId ?? items[0]?.id)) ?? items[0] ?? null;

  async function handleSelect(id: string) {
    setSelectedId(id);
    setAccessNotice(null);
    const item = items.find(n => n.id === id);
    if (item && !item.isRead) {
      const updated = items.map(n => (n.id === id ? { ...n, isRead: true } : n));
      setLocalNotifications(updated);
      try {
        await adapter.notifications.markAsRead(id);
      } catch {
        // Silently tolerate if in preview
      }
    }
  }

  async function handleMarkAllRead() {
    const updated = items.map(n => ({ ...n, isRead: true }));
    setLocalNotifications(updated);
    try {
      await adapter.notifications.markAllAsRead();
    } catch {
      // Silently tolerate in preview
    }
  }

  function handleNavigate(targetHref?: string) {
    if (!targetHref) return;
    setAccessNotice(null);
    const matched = matchRoute(targetHref);
    if (!matched) {
      setAccessNotice('Đường dẫn không tồn tại trên hệ thống.');
      return;
    }
    const userRoles: Role[] = role ? [role] : [];
    if (!canOpenRoute(matched, userRoles)) {
      setAccessNotice('Bạn không có quyền truy cập vào nội dung này (quyền đã thay đổi hoặc bị thu hồi).');
      return;
    }
    router.push(targetHref);
  }

  const badgeColors: Record<string, string> = {
    ASSIGNMENT: 'tag-amber',
    EXAM: 'tag-red',
    MATERIAL: 'tag-blue',
    CLASS: 'tag-teal',
    SYSTEM: 'tag-slate',
  };

  return (
    <div className="notifications-layout">
      {/* Master List Pane */}
      <section className="card notif-list-card" aria-label="Danh sách thông báo">
        <div className="notif-header">
          <div className="notif-title-row">
            <div>
              <h2>Thông báo</h2>
              <small className="muted">Trung tâm cập nhật học tập</small>
            </div>
            {unreadCount > 0 && (
              <button
                className="button-link"
                type="button"
                onClick={() => void handleMarkAllRead()}
              >
                <Icon name="check"/> Đánh dấu tất cả đã đọc
              </button>
            )}
          </div>

          <div className="notif-filter-row">
            <div className="segmented" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={filter === 'all'}
                onClick={() => setFilter('all')}
              >
                Tất cả ({items.length})
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={filter === 'unread'}
                onClick={() => setFilter('unread')}
              >
                Chưa đọc ({unreadCount})
              </button>
            </div>
          </div>
        </div>

        <div className="notif-scroll-region" role="list">
          {filtered.length === 0 ? (
            <p className="padded muted" style={{ textAlign: 'center' }}>
              {filter === 'unread' ? 'Không có thông báo chưa đọc.' : 'Bạn chưa có thông báo nào.'}
            </p>
          ) : (
            filtered.map(item => {
              const active = current?.id === item.id;
              return (
                <div
                  key={item.id}
                  role="listitem"
                  tabIndex={0}
                  className={`notif-item ${active ? 'selected' : ''} ${!item.isRead ? 'unread' : ''}`}
                  onClick={() => void handleSelect(item.id)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); void handleSelect(item.id); } }}
                >
                  <div className="notif-item-top">
                    {!item.isRead && <span className="unread-dot" title="Chưa đọc"/>}
                    <span className={`tag ${badgeColors[item.category] ?? 'tag-blue'}`}>
                      {item.categoryLabel ?? item.category}
                    </span>
                    {item.className && <span className="notif-class-tag">{item.className}</span>}
                    <time className="notif-time">{formatTimeAgo(item.createdAt)}</time>
                  </div>
                  <strong className="notif-item-title">{item.title}</strong>
                  <p className="notif-item-snippet">{item.content}</p>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* Detail Pane */}
      <section className="card notif-detail-card" aria-label="Chi tiết thông báo">
        {current ? (
          <div className="notif-detail-content">
            <div className="notif-detail-header">
              <div className="actions">
                <span className={`tag ${badgeColors[current.category] ?? 'tag-blue'}`}>
                  {current.categoryLabel ?? current.category}
                </span>
                {current.className && <span className="tag">{current.className}</span>}
              </div>
              <time className="muted">{new Date(current.createdAt).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })}</time>
            </div>

            <h2 className="notif-detail-title">{current.title}</h2>
            <div className="notif-detail-body">
              <p>{current.content}</p>
            </div>

            {accessNotice && (
              <div className="notice error" role="alert">
                {accessNotice}
              </div>
            )}

            {current.targetHref && (
              <div className="notif-detail-actions">
                <button
                  className="button primary"
                  type="button"
                  onClick={() => handleNavigate(current.targetHref)}
                >
                  {current.targetLabel ?? 'Mở nội dung liên quan'} →
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="padded muted" style={{ textAlign: 'center', marginTop: '40px' }}>
            <Icon name="bell"/>
            <p style={{ marginTop: '12px' }}>Chọn một thông báo từ danh sách để xem chi tiết.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function formatTimeAgo(isoString: string) {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffHours = Math.floor(diffMs / 3600000);
    if (diffHours < 1) return 'Vừa xong';
    if (diffHours < 24) return `${diffHours} giờ trước`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) return 'Hôm qua';
    if (diffDays < 7) return `${diffDays} ngày trước`;
    return new Date(isoString).toLocaleDateString('vi-VN');
  } catch {
    return isoString;
  }
}

// Re-export as Feature for backward-compatible module signature
export { NotificationFeature as Feature };
