'use client';

import { useId, useRef, useEffect } from 'react';
import type { NotificationItem } from '@/lib/domain';
import type { NotificationReadIssue } from '@/lib/notification-read-controller';
import { Icon, StatePanel, ErrorNotice } from '@/components/ui';
import './notification-center.css';

export type NotificationCenterProps = {
  loadState: 'loading' | 'unavailable' | 'ready';
  loadMessage?: string;
  items: readonly Readonly<NotificationItem>[]; // already filtered by root
  selected: Readonly<NotificationItem> | null;
  filter: 'all' | 'unread';
  totalCount: number;
  unreadCount: number;
  busy: boolean;
  syncing?: boolean;
  lastSyncedAt?: number | null;
  issue: NotificationReadIssue | null;
  snapshotError: string | null;
  accessNotice: string | null;
  onSelect(id: string): void;
  onFilter(filter: 'all' | 'unread'): void;
  onNavigate(item: Readonly<NotificationItem>): void;
  onMarkAll(): void;
  onRetry(): void;
  onReconcile(): void;
  onRefresh(): void;
};

function parseValidDate(isoString: string | undefined | null): Date | null {
  if (!isoString || typeof isoString !== 'string') return null;
  const date = new Date(isoString);
  return isNaN(date.getTime()) ? null : date;
}

function getValidIsoDateTime(isoString: string): string | undefined {
  const date = parseValidDate(isoString);
  if (!date) return undefined;
  try {
    return date.toISOString();
  } catch {
    return undefined;
  }
}

function formatTimeAgo(isoString: string): string {
  const date = parseValidDate(isoString);
  if (!date) return 'Chưa có thời gian';

  try {
    const now = Date.now();
    const diffMs = now - date.getTime();
    if (diffMs < 0) return 'Vừa xong';
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Vừa xong';
    if (diffMins < 60) return `${diffMins} phút trước`;
    const diffHours = Math.floor(diffMs / 3600000);
    if (diffHours < 24) {
      const isToday = new Date().toDateString() === date.toDateString();
      const timeStr = date.toLocaleTimeString('vi-VN', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'Asia/Ho_Chi_Minh',
      });
      return isToday ? `${timeStr} Hôm nay` : `${diffHours} giờ trước`;
    }
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) return 'Hôm qua';
    if (diffDays < 7) return `${diffDays} ngày trước`;
    return date.toLocaleDateString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' });
  } catch {
    return 'Chưa có thời gian';
  }
}

function formatFullDateTime(isoString: string): string {
  const date = parseValidDate(isoString);
  if (!date) return 'Chưa có thời gian';

  try {
    return date.toLocaleString('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh',
      hour: '2-digit',
      minute: '2-digit',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return 'Chưa có thời gian';
  }
}

function getCategoryLabel(category: NotificationItem['category'], customLabel?: string): string {
  if (customLabel) return customLabel;
  switch (category) {
    case 'ASSIGNMENT':
      return 'Bài tập';
    case 'EXAM':
      return 'Bài kiểm tra';
    case 'MATERIAL':
      return 'Tài liệu học tập';
    case 'CLASS':
      return 'Lớp học';
    case 'SYSTEM':
      return 'Hệ thống';
    default:
      return 'Thông báo';
  }
}

function getCategoryBadgeClass(category: NotificationItem['category']): string {
  switch (category) {
    case 'ASSIGNMENT':
      return 'lumi-notification-badge-assignment';
    case 'EXAM':
      return 'lumi-notification-badge-exam';
    case 'MATERIAL':
      return 'lumi-notification-badge-material';
    case 'CLASS':
      return 'lumi-notification-badge-class';
    case 'SYSTEM':
      return 'lumi-notification-badge-system';
    default:
      return 'lumi-notification-badge-default';
  }
}

function getCategoryIconName(category: NotificationItem['category']): string {
  switch (category) {
    case 'ASSIGNMENT':
      return 'clipboard';
    case 'EXAM':
      return 'edit';
    case 'MATERIAL':
      return 'file';
    case 'CLASS':
      return 'users';
    case 'SYSTEM':
      return 'shield';
    default:
      return 'bell';
  }
}

export function NotificationCenter({
  loadState,
  loadMessage,
  items,
  selected,
  filter,
  totalCount,
  unreadCount,
  busy,
  syncing = false,
  lastSyncedAt = null,
  issue,
  snapshotError,
  accessNotice,
  onSelect,
  onFilter,
  onNavigate,
  onMarkAll,
  onRetry,
  onReconcile,
  onRefresh,
}: NotificationCenterProps) {
  const listRegionId = useId();
  const tabsId = useId();
  const detailTitleId = useId();

  const detailHeadingRef = useRef<HTMLHeadingElement>(null);
  const allTabRef = useRef<HTMLButtonElement>(null);
  const unreadTabRef = useRef<HTMLButtonElement>(null);

  const prevSelectedIdRef = useRef<string | null>(selected ? selected.id : null);
  const isUserActivatedRef = useRef(false);
  const userActivatedTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (selected && selected.id !== prevSelectedIdRef.current) {
      if (isUserActivatedRef.current) {
        isUserActivatedRef.current = false;
        if (userActivatedTimeoutRef.current !== null) {
          clearTimeout(userActivatedTimeoutRef.current);
          userActivatedTimeoutRef.current = null;
        }
        detailHeadingRef.current?.focus();
      }
      prevSelectedIdRef.current = selected.id;
    } else if (!selected) {
      prevSelectedIdRef.current = null;
      isUserActivatedRef.current = false;
    }
  }, [selected]);

  useEffect(() => {
    return () => {
      if (userActivatedTimeoutRef.current !== null) {
        clearTimeout(userActivatedTimeoutRef.current);
      }
    };
  }, []);

  const handleItemSelect = (id: string) => {
    if (selected?.id === id) {
      detailHeadingRef.current?.focus();
      onSelect(id);
      return;
    }

    isUserActivatedRef.current = true;
    if (userActivatedTimeoutRef.current !== null) {
      clearTimeout(userActivatedTimeoutRef.current);
    }
    userActivatedTimeoutRef.current = setTimeout(() => {
      isUserActivatedRef.current = false;
      userActivatedTimeoutRef.current = null;
    }, 1000);

    onSelect(id);
  };

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, currentTab: 'all' | 'unread') => {
    let targetTab: 'all' | 'unread' | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      targetTab = currentTab === 'all' ? 'unread' : 'all';
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      targetTab = currentTab === 'unread' ? 'all' : 'unread';
    } else if (e.key === 'Home') {
      e.preventDefault();
      targetTab = 'all';
    } else if (e.key === 'End') {
      e.preventDefault();
      targetTab = 'unread';
    }

    if (targetTab !== null) {
      if (targetTab === 'all') {
        allTabRef.current?.focus();
      } else {
        unreadTabRef.current?.focus();
      }
      if (targetTab !== currentTab) {
        onFilter(targetTab);
      }
    }
  };

  const isMarkAllDisabled = busy || unreadCount === 0 || issue?.outcome === 'unknown';
  const markAllTitle = issue?.outcome === 'unknown'
    ? 'Cần đối soát trạng thái đọc trước khi đánh dấu tất cả'
    : unreadCount === 0
      ? 'Không có thông báo chưa đọc'
      : 'Đánh dấu tất cả đã đọc';

  if (loadState === 'loading') {
    return (
      <div className="lumi-notification-container is-loading" aria-busy="true">
        <StatePanel
          busy
          title="Đang tải thông báo…"
          message={loadMessage || 'Đang đồng bộ dữ liệu thông báo từ máy chủ...'}
        />
      </div>
    );
  }

  if (loadState === 'unavailable') {
    return (
      <div className="lumi-notification-container is-unavailable">
        <StatePanel
          title="Dịch vụ thông báo chưa sẵn sàng"
          message={loadMessage || 'Không thể kết nối hoặc tải dữ liệu thông báo lúc này.'}
        >
          <button
            type="button"
            className="button primary lumi-notification-btn-retry"
            onClick={onRefresh}
            disabled={busy}
          >
            <Icon name="clock" />
            <span>Thử lại</span>
          </button>
        </StatePanel>
      </div>
    );
  }

  return (
    <div className="lumi-notification-container">
      {/* CỘT 1: DANH SÁCH THÔNG BÁO (MASTER) */}
      <section className="lumi-notification-master card" aria-label="Danh sách thông báo">
        <header className="lumi-notification-header">
          <div className="lumi-notification-title-block">
            <h2 className="lumi-notification-heading">Thông báo</h2>
            <p className="lumi-notification-subtitle muted">{unreadCount>0?`${unreadCount} thông báo chưa đọc`:'Bạn đã xem hết thông báo mới'}</p>
            <p className="lumi-notification-sync-status">{syncing?'Đang đồng bộ…':snapshotError?'Chưa cập nhật được dữ liệu mới nhất':lastSyncedAt?`Cập nhật lúc ${new Date(lastSyncedAt).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`:'Tự cập nhật khi mở tab'}</p>
          </div>

          <div className="lumi-notification-header-actions">
            <button
              type="button"
              className="button lumi-notification-btn-refresh"
              onClick={onRefresh}
              disabled={busy || syncing}
              title="Làm mới thông báo"
              aria-label="Làm mới thông báo"
            >
              <Icon name="clock" />
              <span className="lumi-notification-btn-text">Làm mới</span>
            </button>

            <button
              type="button"
              className="button lumi-notification-btn-markall"
              onClick={onMarkAll}
              disabled={isMarkAllDisabled}
              title={markAllTitle}
              aria-label={markAllTitle}
            >
              <Icon name="check" />
              <span>Đánh dấu tất cả đã đọc</span>
            </button>
          </div>
        </header>

        {/* BỘ LỌC TABS */}
        <div className="lumi-notification-tabs-bar">
          <div className="lumi-notification-tabs" role="tablist" aria-label="Bộ lọc thông báo">
            <button
              ref={allTabRef}
              type="button"
              role="tab"
              id={`${tabsId}-all`}
              aria-selected={filter === 'all'}
              aria-controls={listRegionId}
              tabIndex={filter === 'all' ? 0 : -1}
              className={`lumi-notification-tab ${filter === 'all' ? 'is-active' : ''}`}
              onClick={() => onFilter('all')}
              onKeyDown={e => handleTabKeyDown(e, 'all')}
            >
              <span>Tất cả</span>
              <span className="lumi-notification-count">({totalCount})</span>
            </button>

            <button
              ref={unreadTabRef}
              type="button"
              role="tab"
              id={`${tabsId}-unread`}
              aria-selected={filter === 'unread'}
              aria-controls={listRegionId}
              tabIndex={filter === 'unread' ? 0 : -1}
              className={`lumi-notification-tab ${filter === 'unread' ? 'is-active' : ''}`}
              onClick={() => onFilter('unread')}
              onKeyDown={e => handleTabKeyDown(e, 'unread')}
            >
              <span>Chưa đọc</span>
              <span className="lumi-notification-count">({unreadCount})</span>
              {unreadCount > 0 && <span className="lumi-notification-tab-dot" aria-hidden="true" />}
            </button>
          </div>
        </div>

        {/* KHU VỰC THÔNG BÁO TRẠNG THÁI / LỖI ĐỒNG BỘ */}
        <div className="lumi-notification-alerts-region">
          {busy && (
            <div className="lumi-notification-banner is-busy" role="status" aria-live="polite">
              <span className="loader" aria-hidden="true" />
              <span>Đang xử lý đồng bộ trạng thái đọc...</span>
            </div>
          )}

          {snapshotError && (
            <div className="lumi-notification-banner is-error" role="alert">
              <div className="lumi-notification-banner-content">
                <Icon name="info" />
                <span className="lumi-notification-banner-text">{snapshotError}</span>
              </div>
              <button
                type="button"
                className="button lumi-notification-banner-btn"
                onClick={onRefresh}
                disabled={busy}
              >
                Tải lại
              </button>
            </div>
          )}

          {issue && issue.outcome === 'unknown' && (
            <div className="lumi-notification-banner is-warning" role="alert">
              <div className="lumi-notification-banner-content">
                <Icon name="info" />
                <div className="lumi-notification-banner-text">
                  <strong>Chưa xác định trạng thái đọc:</strong>
                  <p>{issue.message}</p>
                </div>
              </div>
              <button
                type="button"
                className="button lumi-notification-banner-btn"
                onClick={onReconcile}
                disabled={busy}
              >
                Đối soát trạng thái
              </button>
            </div>
          )}

          {issue && issue.outcome === 'rejected' && (
            <div className="lumi-notification-banner is-error" role="alert">
              <div className="lumi-notification-banner-content">
                <Icon name="info" />
                <div className="lumi-notification-banner-text">
                  <strong>Không thể cập nhật trạng thái đọc:</strong>
                  <p>{issue.message}</p>
                </div>
              </div>
              <button
                type="button"
                className="button lumi-notification-banner-btn"
                onClick={onRetry}
                disabled={busy}
              >
                Thử lại
              </button>
            </div>
          )}
        </div>

        {/* DANH SÁCH CUỘN THÔNG BÁO */}
        <div
          id={listRegionId}
          className="lumi-notification-list-scroll"
          role="list"
          tabIndex={0}
          aria-label={`Danh sách thông báo ${filter === 'unread' ? 'chưa đọc' : 'tất cả'}`}
        >
          {items.length === 0 ? (
            <div className="lumi-notification-empty-list" role="status">
              <div className={`lumi-notification-empty-icon ${filter === 'unread' ? 'is-success' : ''}`}>
                <Icon name={filter === 'unread' ? 'check' : 'bell'} />
              </div>
              <p className="lumi-notification-empty-title">
                {filter === 'unread' ? 'Không có thông báo chưa đọc' : 'Bạn chưa có thông báo nào'}
              </p>
              <p className="lumi-notification-empty-text muted">
                {filter === 'unread'
                  ? 'Bạn đã xem hết các thông báo mới.'
                  : 'Các cập nhật từ lớp học và hệ thống sẽ xuất hiện tại đây.'}
              </p>
            </div>
          ) : (
            items.map(item => {
              const isSelected = selected?.id === item.id;
              const isUnread = !item.isRead;
              const itemTimeAgo = formatTimeAgo(item.createdAt);
              const validTimeIso = getValidIsoDateTime(item.createdAt);
              const timeDescription = itemTimeAgo === 'Chưa có thời gian' ? 'chưa có thời gian' : `gửi lúc ${itemTimeAgo}`;
              return (
                <div key={item.id} role="listitem" className="lumi-notification-listitem">
                  <button
                    type="button"
                    aria-current={isSelected ? 'true' : undefined}
                    aria-label={`${item.title}, ${isUnread ? 'chưa đọc' : 'đã đọc'}, ${timeDescription}`}
                    className={`lumi-notification-item ${isSelected ? 'is-selected' : ''} ${isUnread ? 'is-unread' : 'is-read'}`}
                    onClick={() => handleItemSelect(item.id)}
                  >
                    <div className="lumi-notification-item-top">
                      <div className="lumi-notification-item-badges">
                        {isUnread && <span className="lumi-notification-unread-dot" title="Chưa đọc" aria-hidden="true" />}
                        <span className={`lumi-notification-badge ${getCategoryBadgeClass(item.category)}`}>
                          <Icon name={getCategoryIconName(item.category)} />
                          <span>{getCategoryLabel(item.category, item.categoryLabel)}</span>
                        </span>
                        {item.className && <span className="lumi-notification-class-tag">{item.className}</span>}
                      </div>
                      <time className="lumi-notification-time" dateTime={validTimeIso}>
                        {itemTimeAgo}
                      </time>
                    </div>

                    <span className="lumi-notification-item-title">{item.title}</span>
                    <span className="lumi-notification-item-snippet">{item.content}</span>

                    <div className="lumi-notification-item-footer">
                      <span className={`lumi-notification-status-indicator ${isUnread ? 'is-unread' : 'is-read'}`}>
                        {isUnread ? 'Chưa đọc' : 'Đã đọc'}
                      </span>
                    </div>
                  </button>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* CỘT 2: CHI TIẾT THÔNG BÁO (DETAIL) */}
      <section className="lumi-notification-detail card" aria-label="Chi tiết thông báo">
        {selected ? (
          <article className="lumi-notification-detail-article" aria-labelledby={detailTitleId}>
            <header className="lumi-notification-detail-header">
              <div className="lumi-notification-detail-meta-left">
                <span className={`lumi-notification-badge ${getCategoryBadgeClass(selected.category)}`}>
                  <Icon name={getCategoryIconName(selected.category)} />
                  <span>{getCategoryLabel(selected.category, selected.categoryLabel)}</span>
                </span>
                {selected.className && (
                  <span className="lumi-notification-class-badge">{selected.className}</span>
                )}
                <span className={`lumi-notification-status-badge ${!selected.isRead ? 'is-unread' : 'is-read'}`}>
                  {!selected.isRead && <span className="lumi-notification-unread-dot" aria-hidden="true" />}
                  {!selected.isRead ? 'Chưa đọc' : 'Đã đọc'}
                </span>
              </div>
              <time className="lumi-notification-detail-date" dateTime={getValidIsoDateTime(selected.createdAt)}>
                {formatFullDateTime(selected.createdAt)}
              </time>
            </header>

            <h2
              id={detailTitleId}
              ref={detailHeadingRef}
              tabIndex={-1}
              className="lumi-notification-detail-title"
            >
              {selected.title}
            </h2>

            {selected.className && (
              <div className="lumi-notification-context-box">
                <div className="lumi-notification-context-icon" aria-hidden="true">
                  <Icon name="users" />
                </div>
                <div className="lumi-notification-context-meta">
                  <div className="lumi-notification-context-name">{selected.className}</div>
                  <div className="lumi-notification-context-sub muted">
                    Thông tin liên kết từ lớp học
                  </div>
                </div>
              </div>
            )}

            <div className="lumi-notification-detail-body">
              <p>{selected.content}</p>
            </div>

            {accessNotice && (
              <div className="lumi-notification-access-notice">
                <ErrorNotice message={accessNotice} />
              </div>
            )}

            {selected.targetHref && (
              <div className="lumi-notification-detail-actions">
                <button
                  type="button"
                  className="button primary lumi-notification-btn-navigate"
                  onClick={() => onNavigate(selected)}
                >
                  <span>{selected.targetLabel || 'Mở nội dung liên quan'}</span>
                  <Icon name="chevronRight" />
                </button>
              </div>
            )}
          </article>
        ) : (
          <div className="lumi-notification-detail-empty" role="region" aria-label="Chi tiết thông báo">
            <div className="lumi-notification-empty-icon">
              <Icon name="bell" />
            </div>
            <h2 className="lumi-notification-empty-title">Chi tiết thông báo</h2>
            <p className="lumi-notification-empty-text muted">
              Chọn một thông báo từ danh sách để xem đầy đủ nội dung.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
