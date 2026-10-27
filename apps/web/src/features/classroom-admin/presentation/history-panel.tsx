'use client';

import { useId } from 'react';
import { Icon } from '@/components/ui';
import './history-panel.css';

export interface AdministrationHistoryItem {
  id: string;
  title: string;
  detail: string;
  at?: string;
  actorName?: string;
  statusLabel?: string;
}

export interface AdministrationHistoryPanelProps {
  title: string;
  description?: string;
  items: ReadonlyArray<AdministrationHistoryItem>;
}

function formatVietnameseIsoTime(isoString?: string): string | null {
  if (!isoString || typeof isoString !== 'string') {
    return null;
  }
  const trimmed = isoString.trim();
  if (!trimmed) {
    return null;
  }
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  try {
    return new Intl.DateTimeFormat('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  } catch {
    return null;
  }
}

export function AdministrationHistoryPanel({
  title,
  description,
  items,
}: AdministrationHistoryPanelProps) {
  const titleId = useId();

  return (
    <section className="lumi-admin-history-panel" aria-labelledby={titleId}>
      <header className="lumi-admin-history-header">
        <div className="lumi-admin-history-header-text">
          <h2 id={titleId} className="lumi-admin-history-title">
            {title}
          </h2>
          {description && (
            <p className="lumi-admin-history-description">{description}</p>
          )}
        </div>
        <span className="lumi-admin-history-count-badge">
          {items.length} bản ghi
        </span>
      </header>

      {items.length === 0 ? (
        <div className="lumi-admin-history-empty" role="status">
          <div className="lumi-admin-history-empty-icon" aria-hidden="true">
            <Icon name="clock" />
          </div>
          <p>Chưa có bản ghi lịch sử nào được ghi nhận.</p>
        </div>
      ) : (
        <ol className="lumi-admin-history-list" aria-label={title}>
          {items.map(item => {
            const formattedTime = formatVietnameseIsoTime(item.at);
            return (
              <li key={item.id} className="lumi-admin-history-item">
                <span className="lumi-admin-history-marker" aria-hidden="true" />
                <div className="lumi-admin-history-item-top">
                  <h3 className="lumi-admin-history-item-title">{item.title}</h3>
                  <div className="lumi-admin-history-item-meta">
                    {item.statusLabel && (
                      <span className="lumi-admin-history-status-badge">
                        {item.statusLabel}
                      </span>
                    )}
                    {item.at && formattedTime && (
                      <time className="lumi-admin-history-time" dateTime={item.at}>
                        {formattedTime}
                      </time>
                    )}
                  </div>
                </div>
                <p className="lumi-admin-history-detail">{item.detail}</p>
                {item.actorName && (
                  <div className="lumi-admin-history-actor">
                    <span className="lumi-admin-history-actor-label">Người thực hiện:</span>
                    <span className="lumi-admin-history-actor-name">{item.actorName}</span>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
