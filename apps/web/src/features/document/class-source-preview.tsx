'use client';
import { useEffect, useState } from 'react';
import { adapter } from '@/lib/data';
import type { ClassSourcePreview } from '@/lib/document-preview';
import { Dialog, StatePanel } from '@/components/ui';
import './class-source-preview.css';
export type SourcePreviewRequest = { classId: string; documentId: string; version: number; page?: number };
export function ClassSourcePreviewDialog({ request, onClose }: { request: SourcePreviewRequest | null; onClose(): void }) {
  const [snapshot, setSnapshot] = useState<{ key: string; data?: ClassSourcePreview; error?: string } | null>(null);
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const key = request ? JSON.stringify(request) : '';
  useEffect(() => {
    let active = true;
    if (!request) { setSnapshot(null); return; }
    setSnapshot(null);
    setPage(request.page ?? 1);
    void adapter.document.previewClassSource(request).then(data => { if (active) setSnapshot({ key, data }); }).catch(error => { if (active) setSnapshot({ key, error: error instanceof Error ? error.message : 'Chưa thể mở nguồn tài liệu.' }); });
    return () => { active = false; };
  }, [key, retry]);
  const current = snapshot?.key === key ? snapshot : null;
  const content = current?.data?.pages.find(p => p.pageNumber === page);
  return <Dialog open={Boolean(request)} title="Đọc nguồn tài liệu của lớp" onClose={onClose} className="class-source-preview">
    {!current ? <StatePanel busy title="Đang kiểm tra quyền đọc và phiên bản…"/> : current.error ? <StatePanel title="Nguồn tài liệu chưa khả dụng" message={current.error}><button className="button" onClick={() => setRetry(r => r + 1)}>Kiểm tra lại</button></StatePanel> : current.data ? <>
      <p><strong>{current.data.title}</strong> · Phiên bản {current.data.version}</p>
      <label>Trang <select className="input" value={page} onChange={e => setPage(Number(e.target.value))}>{current.data.pages.map(p => <option key={p.pageNumber} value={p.pageNumber}>{p.pageNumber} · {p.title}</option>)}</select></label>
      {content ? <article className="card source-reading-page"><h3>{content.title}</h3>{content.paragraphs.map((text, i) => <p key={i}>{text}</p>)}{content.formulas?.map((text, i) => <p className="source-formula" key={i}>{text}</p>)}</article> : <StatePanel title="Không có nội dung ở vị trí này" message="Chọn một trang có trong phiên bản tài liệu."/>}
      <p className="muted">Nguồn được chia sẻ để đọc trong lớp. Việc quản lý tài liệu thuộc thư viện của chủ sở hữu.</p>
    </> : null}
  </Dialog>;
}
