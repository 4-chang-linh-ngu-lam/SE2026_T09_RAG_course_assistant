'use client';

import type React from 'react';

export interface DocumentMetadataFormProps {
  title: string;
  description: string;
  busy: boolean;
  error: string | null;
  onTitleChange(value: string): void;
  onDescriptionChange(value: string): void;
  onSubmit(event: React.FormEvent): void;
  onCancel(): void;
}

export function DocumentMetadataForm({
  title,
  description,
  busy,
  error,
  onTitleChange,
  onDescriptionChange,
  onSubmit,
  onCancel,
}: DocumentMetadataFormProps) {
  const isSubmitDisabled = busy || title.trim().length === 0;

  return (
    <form onSubmit={onSubmit} className="lumi-library-dialog-form">
      {error && (
        <div className="lumi-library-error" role="alert">
          {error}
        </div>
      )}

      <div className="lumi-library-form-group">
        <label htmlFor="document-metadata-title" className="lumi-library-label">
          Tiêu đề tài liệu <span className="lumi-library-required" aria-hidden="true">*</span>
        </label>
        <input
          id="document-metadata-title"
          name="title"
          type="text"
          className="lumi-library-input"
          value={title}
          onChange={e => onTitleChange(e.target.value)}
          maxLength={200}
          required
          disabled={busy}
          placeholder="Nhập tiêu đề tài liệu"
          aria-required="true"
        />
      </div>

      <div className="lumi-library-form-group">
        <label htmlFor="document-metadata-description" className="lumi-library-label">
          Mô tả (tùy chọn)
        </label>
        <textarea
          id="document-metadata-description"
          name="description"
          className="lumi-library-input"
          rows={4}
          value={description}
          onChange={e => onDescriptionChange(e.target.value)}
          maxLength={4000}
          disabled={busy}
          placeholder="Nhập mô tả tài liệu (tùy chọn)"
        />
      </div>

      <div className="lumi-library-dialog-actions">
        <button
          type="button"
          className="button secondary"
          onClick={onCancel}
          disabled={busy}
        >
          Hủy
        </button>
        <button
          type="submit"
          className="button primary"
          disabled={isSubmitDisabled}
        >
          Lưu thông tin
        </button>
      </div>
    </form>
  );
}
