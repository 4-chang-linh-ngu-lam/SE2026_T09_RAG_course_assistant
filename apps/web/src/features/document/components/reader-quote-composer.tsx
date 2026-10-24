'use client';

export interface ReaderQuoteComposerProps {
  quote: string;
  disabled: boolean;
  onCapture(): void;
  onClear(): void;
}

export function ReaderQuoteComposer({
  quote,
  disabled,
  onCapture,
  onClear,
}: ReaderQuoteComposerProps) {
  const hasQuote = Boolean(quote && quote.trim());

  return (
    <div className="reader-quote-composer">
      <button
        id="reader-capture-quote"
        type="button"
        className="button small"
        disabled={disabled}
        onClick={onCapture}
      >
        Trích dẫn đoạn đã chọn
      </button>
      <p className="muted">
        Chọn đoạn văn bản trong tài liệu nguồn trước khi trích dẫn.
      </p>
      {hasQuote && (
        <div>
          <blockquote className="note-quote-box">{quote}</blockquote>
          <button
            id="reader-clear-quote"
            type="button"
            className="button small"
            disabled={disabled}
            onClick={onClear}
          >
            Bỏ trích dẫn
          </button>
        </div>
      )}
      <p className="muted">Trích dẫn chỉ hiển thị khi còn quyền nguồn.</p>
    </div>
  );
}
