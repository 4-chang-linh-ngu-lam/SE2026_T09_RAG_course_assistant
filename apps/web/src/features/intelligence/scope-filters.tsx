'use client';

import React, { useId } from 'react';
import type { ActivityOption } from '@/lib/intelligence';
import './scope-filters.css';

export interface LearningScopeFiltersProps {
  fromDate: string;
  toDate: string;
  activities: readonly ActivityOption[];
  selectedResourceIds: readonly string[]; // [] means all activities
  appliedSummary: string;
  error: string | null;
  busy?: boolean;
  onFromChange(value: string): void;
  onToChange(value: string): void;
  onResourcesChange(ids: string[]): void;
  onApply(): void;
}

export interface AuditDateRangeProps {
  fromDate: string;
  toDate: string;
  error: string | null;
  onFromChange(value: string): void;
  onToChange(value: string): void;
  onClear(): void;
}

function getActivityKindLabel(kind: ActivityOption['kind']): string {
  switch (kind) {
    case 'PRACTICE':
      return 'Luyện tập';
    case 'ASSESSMENT':
      return 'Kiểm tra chính thức';
    case 'ASSIGNMENT':
    default:
      return 'Bài tập tự luận';
  }
}

function getActivityKindTagClass(kind: ActivityOption['kind']): string {
  switch (kind) {
    case 'PRACTICE':
      return 'in-tag teal lumi-scope-activity-tag';
    case 'ASSESSMENT':
      return 'in-tag blue lumi-scope-activity-tag';
    default:
      return 'in-tag lumi-scope-activity-tag';
  }
}

export function LearningScopeFilters({
  fromDate,
  toDate,
  activities,
  selectedResourceIds,
  appliedSummary,
  error,
  busy = false,
  onFromChange,
  onToChange,
  onResourcesChange,
  onApply,
}: LearningScopeFiltersProps) {
  const fromInputId = useId();
  const toInputId = useId();
  const errorId = useId();

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy || error) {
      return;
    }
    onApply();
  };

  const handleToggleActivity = (resourceId: string) => {
    if (busy) return;
    const isSelected = selectedResourceIds.includes(resourceId);
    const next = isSelected
      ? selectedResourceIds.filter(id => id !== resourceId)
      : [...selectedResourceIds, resourceId];
    onResourcesChange(next);
  };

  const handleClearAll = () => {
    if (busy) return;
    onResourcesChange([]);
  };

  return (
    <form className="in-filters card lumi-scope-filters" onSubmit={handleSubmit}>
      <label htmlFor={fromInputId} className="lumi-scope-date-label">
        Từ ngày
        <input
          id={fromInputId}
          type="date"
          value={fromDate}
          onChange={e => onFromChange(e.target.value)}
          disabled={busy}
          className="lumi-scope-input"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        />
      </label>
      <label htmlFor={toInputId} className="lumi-scope-date-label">
        Đến hết ngày
        <input
          id={toInputId}
          type="date"
          value={toDate}
          onChange={e => onToChange(e.target.value)}
          disabled={busy}
          className="lumi-scope-input"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        />
      </label>

      <fieldset className="lumi-scope-activities-fieldset">
        <legend className="lumi-scope-legend">Hoạt động học tập</legend>
        <div className="lumi-scope-activities-header">
          <button
            type="button"
            className={`button secondary lumi-scope-all-button ${selectedResourceIds.length === 0 ? 'lumi-scope-active' : ''}`}
            onClick={handleClearAll}
            disabled={busy}
            aria-pressed={selectedResourceIds.length === 0}
          >
            Tất cả hoạt động
          </button>
        </div>

        {activities.length === 0 ? (
          <p className="lumi-scope-empty muted">Chưa có hoạt động nào trong phạm vi đã chọn.</p>
        ) : (
          <div className="lumi-scope-activities-list" role="group" aria-label="Lựa chọn hoạt động">
            {activities.map(activity => {
              const checked = selectedResourceIds.includes(activity.resourceId);
              const activityCheckboxId = `lumi-scope-act-${activity.resourceId}`;
              return (
                <label
                  key={activity.resourceId}
                  htmlFor={activityCheckboxId}
                  className={`lumi-scope-activity-choice ${checked ? 'lumi-scope-selected' : ''}`}
                >
                  <input
                    id={activityCheckboxId}
                    type="checkbox"
                    checked={checked}
                    disabled={busy}
                    onChange={() => handleToggleActivity(activity.resourceId)}
                  />
                  <span className="lumi-scope-activity-title">{activity.title}</span>
                  <span className={getActivityKindTagClass(activity.kind)}>
                    {getActivityKindLabel(activity.kind)}
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </fieldset>

      {error && (
        <p id={errorId} role="alert" className="lumi-scope-error notice error">
          {error}
        </p>
      )}

      <div className="lumi-scope-actions">
        <button
          className="button lumi-scope-submit-button"
          type="submit"
          disabled={busy || Boolean(error)}
        >
          Cập nhật phạm vi
        </button>
      </div>

      {appliedSummary && (
        <p className="lumi-scope-applied-summary muted">
          {appliedSummary}
        </p>
      )}
    </form>
  );
}

export function AuditDateRange({
  fromDate,
  toDate,
  error,
  onFromChange,
  onToChange,
  onClear,
}: AuditDateRangeProps) {
  const fromInputId = useId();
  const toInputId = useId();
  const errorId = useId();

  return (
    <fieldset className="lumi-scope-audit-fieldset">
      <legend className="lumi-scope-audit-legend">Khoảng thời gian</legend>
      <label htmlFor={fromInputId} className="lumi-scope-audit-label">
        Từ ngày
        <input
          id={fromInputId}
          type="date"
          value={fromDate}
          onChange={e => onFromChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          className="lumi-scope-audit-input"
        />
      </label>
      <label htmlFor={toInputId} className="lumi-scope-audit-label">
        Đến hết ngày
        <input
          id={toInputId}
          type="date"
          value={toDate}
          onChange={e => onToChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          className="lumi-scope-audit-input"
        />
      </label>
      <button
        type="button"
        className="button secondary lumi-scope-audit-clear"
        onClick={onClear}
      >
        Xóa lọc ngày
      </button>
      {error && (
        <p id={errorId} role="alert" className="lumi-scope-error notice error">
          {error}
        </p>
      )}
    </fieldset>
  );
}
