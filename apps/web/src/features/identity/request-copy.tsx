'use client';
import { useEffect, useRef, useState } from 'react';
import { adapter } from '@/lib/data';
import { errorMessage } from '@/lib/api/errors';
export function RequestCopy({ requestId }: { requestId: string }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function download() {
    if (busy) return; setBusy(true); setError(null);
    try {
      const file = await adapter.personalData.download(requestId);
      if (!mounted.current) return;
      const bytes = new Uint8Array(file.bytes);
      const url = URL.createObjectURL(new Blob([bytes.buffer], { type: file.type }));
      const link = document.createElement('a'); link.href = url; link.download = file.name; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (mounted.current) setError(errorMessage(error)); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <div><button className="button small" disabled={busy} onClick={() => void download()}>{busy ? 'Đang kiểm tra bản sao…' : 'Nhận bản sao dữ liệu'}</button>{error && <p className="muted" role="status">{error}</p>}</div>;
}
