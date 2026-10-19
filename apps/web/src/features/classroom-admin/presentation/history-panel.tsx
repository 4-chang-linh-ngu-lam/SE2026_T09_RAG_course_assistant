'use client';

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

export function AdministrationHistoryPanel({
  title,
  description,
  items,
}: AdministrationHistoryPanelProps) {
  return (
    <section className="lumi-admin-history-panel" aria-labelledby="lumi-admin-history-panel-title">
      <header className="lumi-admin-history-header">
        <div className="lumi-admin-history-header-text">
          <h2 id="lumi-admin-history-panel-title" className="lumi-admin-history-title">
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
          {items.map(item => (
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
                  {item.at && (
                    <time className="lumi-admin-history-time" dateTime={item.at}>
                      {item.at}
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
          ))}
        </ol>
      )}
    </section>
  );
}
