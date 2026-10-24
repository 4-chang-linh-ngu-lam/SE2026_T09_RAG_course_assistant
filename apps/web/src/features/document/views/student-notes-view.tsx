'use client';
import { useState, useMemo, useRef } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import type { BookmarkItem, PersonalNoteItem, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog, useUnsavedChanges } from '@/components/ui';
import {useDocumentWrite} from '../use-document-write';

type Props = {
  route: RouteDefinition;
  data: WorkspaceData | null;
  reload(): void;
};

export function StudentNotesView({ data, reload }: Props) {
  const [tab, setTab] = useState<'all' | 'notes' | 'bookmarks'>('all');
  const [search, setSearch] = useState('');
  const [editingNote, setEditingNote] = useState<PersonalNoteItem | null>(null);
  const [editingText, setEditingText] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const write=useDocumentWrite('personal-notes');
  const isPending=write.blocked;
  const intent=useRef<{kind:'edit'|'delete'|'bookmark';id:string;text?:string;revision?:number}|null>(null);
  useUnsavedChanges(Boolean(editingNote&&editingText!==editingNote.noteText));

  const allNotes = data && data.kind === 'ready' ? data.studentNotes ?? [] : [];
  const allBookmarks = data && data.kind === 'ready' ? data.studentBookmarks ?? [] : [];

  const filteredNotes = useMemo(() => {
    if (tab === 'bookmarks') return [];
    if (!search.trim()) return allNotes;
    const q = search.toLowerCase();
    return allNotes.filter(
      n =>
        n.documentTitle.toLowerCase().includes(q) ||
        n.className.toLowerCase().includes(q) ||
        n.locator.toLowerCase().includes(q) ||
        n.noteText.toLowerCase().includes(q) ||
        (n.sourceQuote && n.sourceQuote.toLowerCase().includes(q))
    );
  }, [allNotes, tab, search]);

  const filteredBookmarks = useMemo(() => {
    if (tab === 'notes') return [];
    if (!search.trim()) return allBookmarks;
    const q = search.toLowerCase();
    return allBookmarks.filter(
      b =>
        b.documentTitle.toLowerCase().includes(q) ||
        b.className.toLowerCase().includes(q) ||
        b.locator.toLowerCase().includes(q)
    );
  }, [allBookmarks, tab, search]);

  if (!data) {
    return <StatePanel busy title="Đang tải ghi chú và dấu trang…" />;
  }

  if (data.kind === 'unavailable') {
    return (
      <StatePanel title="Dịch vụ ghi chú chưa sẵn sàng" message={data.message}>
        <button type="button" className="button" onClick={reload}>
          Thử lại
        </button>
      </StatePanel>
    );
  }

  if (data.kind === 'empty') {
    return <StatePanel title="Chưa có ghi chú nào" message={data.message} />;
  }

  const handleUpdateNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingNote || !editingText.trim()) return;
    setActionError(null);
    const note=editingNote;
    intent.current={kind:'edit',id:note.id,text:editingText.trim(),revision:note.revision};
    void write.run(() => adapter.document.saveNote({
          id: editingNote.id,
          documentId: editingNote.documentId,
          classId: editingNote.classId,
          locator: editingNote.locator,
          noteText: editingText.trim(),
          expectedRevision:note.revision,version:note.version,locatorId:note.locatorId,pageNumber:note.pageNumber,
        }), () => {
        setEditingNote(null);
        setEditingText('');
        reload();
    });
  };

  const handleDeleteNote = (noteId: string) => {
    setActionError(null);
    const note=allNotes.find(item=>item.id===noteId);if(!note||!window.confirm('Xóa ghi chú cá nhân này?'))return;
    intent.current={kind:'delete',id:noteId};
    void write.run(() => adapter.document.deleteNote(noteId,note.revision), () => {
        reload();
    });
  };

  const handleDeleteBookmark = (bookmark:BookmarkItem) => {
    setActionError(null);
    intent.current={kind:'bookmark',id:bookmark.id};
    void write.run(async () => {if(adapter.document.removeBookmark)await adapter.document.removeBookmark(bookmark.id);else await adapter.document.toggleBookmark(bookmark.documentId,bookmark.classId,bookmark.locator,bookmark.version,false);}, () => {
        reload();
    });
  };

  const totalCount = filteredNotes.length + filteredBookmarks.length;

  return (
    <div className="student-notes-container">
      {/* Top filter toolbar */}
      <div className="notes-toolbar card">
        <div className="tab-group" role="tablist" aria-label="Phân loại nội dung">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'all'}
            className={`tab-btn ${tab === 'all' ? 'active' : ''}`}
            onClick={() => setTab('all')}
          >
            Tất cả ({allNotes.length + allBookmarks.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'notes'}
            className={`tab-btn ${tab === 'notes' ? 'active' : ''}`}
            onClick={() => setTab('notes')}
          >
            Ghi chú ({allNotes.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'bookmarks'}
            className={`tab-btn ${tab === 'bookmarks' ? 'active' : ''}`}
            onClick={() => setTab('bookmarks')}
          >
            Dấu trang ({allBookmarks.length})
          </button>
        </div>

        <div className="notes-search-wrap">
          <label htmlFor="notesSearchInput" className="sr-only">Tìm kiếm ghi chú và dấu trang</label>
          <input
            id="notesSearchInput"
            type="search"
            className="input search-input"
            placeholder="Tìm theo tài liệu, lớp hoặc từ khóa…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {actionError && <p className="notice error" role="alert">{actionError}</p>}
      {write.error&&<p className="notice error" role="alert">{write.error}</p>}
      {write.unknown&&<button type="button" className="button" disabled={write.busy} onClick={()=>void write.retryOriginal()}>Gửi lại cùng yêu cầu đã lưu</button>}
      {write.unknown&&<button type="button" className="button" disabled={write.busy} onClick={()=>void write.reconcile(async()=>{const current=await adapter.workspace.load('s.notes',{}),target=intent.current;if(current.kind!=='ready'||!target)return false;if(target.kind==='bookmark')return !current.studentBookmarks?.some(item=>item.id===target.id);const note=current.studentNotes?.find(item=>item.id===target.id);return target.kind==='delete'?!note:Boolean(note&&note.noteText===target.text&&(note.revision??0)>(target.revision??0));},()=>{setEditingNote(null);reload();})}>Đối soát thay đổi đã gửi</button>}

      {totalCount === 0 ? (
        <div className="card state-panel">
          <div className="state-icon">
            <Icon name="book" />
          </div>
          <h2>Không tìm thấy ghi chú hoặc dấu trang nào</h2>
          <p className="muted">
            {search.trim()
              ? 'Không có kết quả phù hợp với từ khóa tìm kiếm.'
              : 'Bạn chưa tạo ghi chú hoặc lưu dấu trang nào trong quá trình đọc tài liệu.'}
          </p>
        </div>
      ) : (
        <div className="notes-cards-matrix">
          {/* Notes Cards */}
          {filteredNotes.map(note => {
            const readerHref = `/student/classes/${note.classId}/documents/${note.documentId}${
              `?${new URLSearchParams({...(note.pageNumber?{page:String(note.pageNumber)}:{}),...(note.version?{version:String(note.version)}:{})})}`
            }`;

            return (
              <article key={note.id} className="note-card card">
                <header className="note-card-header">
                  <div className="note-title-line">
                    <span className="badge primary text-xs">{note.documentFormat}</span>
                    {note.isSourceAccessible?<Link href={readerHref} className="note-doc-title-link">
                      <strong>{note.documentTitle}</strong>
                    </Link>:<strong>{note.documentTitle}</strong>}
                  </div>
                  <div className="note-meta-badges">
                    <span className="badge secondary text-xs">{note.className}</span>
                    <span className="badge info text-xs">{note.locator}</span>
                    {note.classStatus === 'ARCHIVED' && (
                      <span className="badge warning text-xs" title="Lớp đã lưu trữ, cho phép xem và sửa ghi chú theo quy tắc O2">
                        Lớp lưu trữ (Cho phép sửa)
                      </span>
                    )}
                  </div>
                </header>

                <div className="note-card-body">
                  {/* Under Rule H6/L6, hide quote if source not accessible */}
                  {note.isSourceAccessible && note.sourceQuote ? (
                    <blockquote className="note-quote-box">
                      <span className="quote-mark">“</span>
                      <span>{note.sourceQuote}</span>
                    </blockquote>
                  ) : !note.isSourceAccessible ? (
                    <div className="revoked-source-strip">
                      <Icon name="lock" />
                      <span>{note.sourceAccess==='UNAVAILABLE'?'Chưa xác minh được quyền nguồn. Trích dẫn tạm ẩn.':'Bạn không còn quyền mở nguồn. Trích dẫn đã ẩn; chữ ghi chú của bạn được giữ lại.'}</span>
                    </div>
                  ) : null}

                  <p className="note-text-content">{note.noteText}</p>
                </div>

                <footer className="note-card-footer">
                  <span className="text-xs muted">{new Date(note.updatedAt).toLocaleString('vi-VN')}</span>
                  <div className="note-actions">
                    <button
                      type="button"
                      className="button small secondary"
                      disabled={isPending||!note.isSourceAccessible}
                      onClick={() => {
                        setEditingNote(note);
                        setEditingText(note.noteText);
                      }}
                    >
                      <Icon name="edit" />
                      <span>Chỉnh sửa</span>
                    </button>
                    <button
                      type="button"
                      className="button small danger"
                      onClick={() => handleDeleteNote(note.id)}
                      disabled={isPending}
                      aria-label="Xóa ghi chú này"
                    >
                      <Icon name="trash" />
                      <span>Xóa</span>
                    </button>
                  </div>
                </footer>
              </article>
            );
          })}

          {/* Bookmarks Cards */}
          {filteredBookmarks.map(bm => {
            const readerHref = `/student/classes/${bm.classId}/documents/${bm.documentId}${
              `?${new URLSearchParams({...(bm.pageNumber?{page:String(bm.pageNumber)}:{}),...(bm.version?{version:String(bm.version)}:{})})}`
            }`;

            return (
              <article key={bm.id} className="bookmark-card card">
                <header className="note-card-header">
                  <div className="note-title-line">
                    <span className="badge primary text-xs">{bm.documentFormat}</span>
                    {bm.isSourceAccessible?<Link href={readerHref} className="note-doc-title-link">
                      <strong>{bm.documentTitle}</strong>
                    </Link>:<strong>{bm.documentTitle}</strong>}
                  </div>
                  <div className="note-meta-badges">
                    <span className="badge secondary text-xs">{bm.className}</span>
                    <span className="badge info text-xs">{bm.locator}</span>
                  </div>
                </header>

                <div className="bookmark-card-body">
                  <p className="text-xs muted">
                    Dấu trang được lưu tại <strong>{bm.locator}</strong> vào ngày {new Date(bm.createdAt).toLocaleString('vi-VN')}. Bấm vào nút bên dưới để mở đúng vị trí trong tài liệu.
                  </p>
                </div>

                <footer className="note-card-footer">
                  <span className="text-xs muted">Đã lưu: {new Date(bm.createdAt).toLocaleString('vi-VN')}</span>
                  <div className="note-actions">
                    {bm.isSourceAccessible?<Link href={readerHref} className="button small primary">
                      <Icon name="book" />
                      <span>Mở tài liệu</span>
                    </Link>:<span className="muted">Nguồn chưa thể mở</span>}
                    <button
                      type="button"
                      className="button small danger"
                      onClick={() => handleDeleteBookmark(bm)}
                      disabled={isPending}
                      aria-label="Gỡ dấu trang này"
                    >
                      <Icon name="trash" />
                      <span>Gỡ</span>
                    </button>
                  </div>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {/* Edit Note Dialog */}
      <Dialog
        open={Boolean(editingNote)}
        title={`Chỉnh sửa ghi chú (${editingNote?.locator ?? ''})`}
        onClose={() => setEditingNote(null)}
        busy={write.busy}
      >
        <form onSubmit={handleUpdateNote} className="form-stack">
          {write.error&&<p className="notice error" role="alert">{write.error}</p>}
          {write.unknown&&<p>Đóng hộp thoại để đối soát thay đổi đã gửi.</p>}
          {allNotes.find(note=>note.id===editingNote?.id)?.isSourceAccessible && editingNote?.sourceQuote && (
            <div className="notice-box info">
              <p className="text-xs">
                <strong>Trích dẫn gốc:</strong> {editingNote.sourceQuote}
              </p>
            </div>
          )}
          {!editingNote?.isSourceAccessible && (
            <div className="notice-box info">
              <p className="text-xs">
                Nguồn chưa thể mở trong lớp. Chữ tự viết vẫn được giữ để đọc; chỉ sửa ghi chú khi còn quyền nguồn.
              </p>
            </div>
          )}
          <div>
            <label htmlFor="editNoteModalTextarea">Nội dung ghi chú cá nhân:</label>
            <textarea
              id="editNoteModalTextarea"
              className="note-textarea"
              rows={4}
              value={editingText}
              disabled={isPending||!allNotes.find(note=>note.id===editingNote?.id)?.isSourceAccessible}
              onChange={e => setEditingText(e.target.value)}
              required
            />
          </div>
          <div className="actions">
            <button type="button" className="button secondary" onClick={() => setEditingNote(null)}>
              Hủy
            </button>
            <button type="submit" className="button primary" disabled={isPending || !editingText.trim() || !allNotes.find(note=>note.id===editingNote?.id)?.isSourceAccessible}>
              Lưu thay đổi
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
