'use client';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import Link from 'next/link';

export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Lumi — Trang chủ">
      <svg viewBox="0 0 32 32" width="32" height="32" fill="none" aria-hidden="true">
        <rect width="32" height="32" rx="9" fill="#2563EB"/>
        <path d="M7 9h6a5 5 0 0 1 3 1 5 5 0 0 1 3-1h6v14h-6a5 5 0 0 0-3 1 5 5 0 0 0-3-1H7V9Zm9 1v14" stroke="white" strokeWidth="1.7" strokeLinejoin="round"/>
      </svg>
      <span>
        <strong>Lumi</strong>
        <small>Học sáng hơn mỗi ngày</small>
      </span>
    </Link>
  );
}

export function Icon({ name = 'grid' }: { name?: string }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    book: <><path d="M3 4h6a4 4 0 0 1 3 1 4 4 0 0 1 3-1h6v15h-6a4 4 0 0 0-3 1 4 4 0 0 0-3-1H3Z"/><path d="M12 5v15"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    chat: <path d="M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0Z"/>,
    chart: <path d="M4 3v18h17M8 16v-4m5 4V7m5 9V4"/>,
    menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
    arrow: <path d="m10 5-7 7 7 7M3 12h18"/>,
    chevronDown: <path d="m6 9 6 6 6-6"/>,
    chevronRight: <path d="m9 18 6-6-6-6"/>,
    chevronLeft: <path d="m15 18-6-6 6-6"/>,
    trash: <><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></>,
    edit: <><path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></>,
    check: <path d="M20 6 9 17l-5-5"/>,
    clock: <><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    send: <><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></>,
    lock: <><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></>,
    info: <><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></>,
    home: <><path d="m3 10 9-7 9 7v11h-6v-7H9v7H3Z"/></>,
    users: <><circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M16 4a3 3 0 0 1 0 6m3 11v-2a6 6 0 0 0-3-5"/></>,
    folder: <path d="M3 7V4h6l2 3h10v13H3Z"/>,
    clipboard: <><path d="M9 4H5v17h14V4h-4"/><rect x="9" y="2" width="6" height="5" rx="1"/><path d="M8 11h8M8 15h6"/></>,
    activity: <path d="M2 12h4l3-8 6 16 3-8h4"/>,
    shield: <><path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z"/><path d="m8 12 3 3 5-6"/></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6"/></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M3 16v5h18v-5"/></>,
    layers: <><path d="m12 2 10 5-10 5L2 7Zm-10 10 10 5 10-5M2 17l10 5 10-5"/></>,
    list: <><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></>,
    bookmark: <path d="M6 3h12v18l-6-4-6 4Z"/>,
    star: <path d="m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1Z"/>,
    sparkles: <><path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z"/><path d="M21 2v5m-2.5-2.5h5"/></>,
    stop: <rect x="5" y="5" width="14" height="14" rx="2"/>,
    save: <><path d="M4 3h13l4 4v14H3V3Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/></>,
    zoomIn: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6M7 10h6m-3-3v6"/></>,
    zoomOut: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6M7 10h6"/></>,
    maximize: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>,
    minimize: <path d="M3 8h5V3m8 0v5h5M3 16h5v5m8 0v-5h5"/>,

  };
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name === 'arrowLeft' ? 'arrow' : name === 'message' ? 'chat' : name] ?? <><circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5m0 3h.01"/></>}
    </svg>
  );
}

export function StatePanel({ title, message, busy = false, children }: { title: string; message?: string; busy?: boolean; children?: ReactNode }) {
  return (
    <section className="state-panel card" role={busy ? 'status' : undefined} aria-live="polite">
      <div className={busy ? 'loader' : 'state-icon'}>
        {!busy && <Icon name="book"/>}
      </div>
      <h2>{title}</h2>
      {message && <p>{message}</p>}
      {children && <div className="actions">{children}</div>}
    </section>
  );
}

export function ErrorNotice({ message }: { message: string | null }) {
  return message ? <p className="notice error" role="alert">{message}</p> : null;
}

export function Dialog({
  open,
  title,
  onClose,
  children,
  busy = false,
  className,
}: {
  open: boolean;
  title: string;
  onClose(): void;
  children: ReactNode;
  busy?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();

  useEffect(() => {
    const dialog = ref.current;
    const trigger = document.activeElement as HTMLElement | null;
    if (open && !dialog?.open) dialog?.showModal();
    else if (!open && dialog?.open) dialog.close();
    return () => {
      if (dialog?.open) dialog.close();
      if (open && trigger?.isConnected) trigger.focus();
    };
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={id}
      aria-modal="true"
      aria-busy={busy || undefined}
      className={className}
      onKeyDown={event => {
        if (event.key === 'Tab') {
          const controls = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') ?? []).filter(control => control.getClientRects().length > 0);
          const first = controls[0]; const last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
          else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          if (!busy) onClose();
        }
      }}
      onCancel={event => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="dialog-header">
        <h2 id={id}>{title}</h2>
        <button
          className="icon-button"
          type="button"
          aria-label="Đóng"
          disabled={busy}
          onClick={() => {
            if (!busy) onClose();
          }}
        >
          ×
        </button>
      </div>
      <div className="dialog-body">{children}</div>
    </dialog>
  );
}

export {useUnsavedChanges,useGuardedRouter} from './unsaved-changes';
