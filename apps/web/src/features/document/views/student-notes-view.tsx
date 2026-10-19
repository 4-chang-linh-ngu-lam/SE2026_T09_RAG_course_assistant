'use client';
import { useState, useMemo, useTransition } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import type { BookmarkItem, PersonalNoteItem, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog } from '@/components/ui';

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
  const [isPending, startTransition] = useTransition();

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
    startTransition(async () => {
      try {
        await adapter.document.saveNote({
          id: editingNote.id,
          documentId: editingNote.documentId,
          classId: editingNote.classId,
          locator: editingNote.locator,
          noteText: editingText.trim(),
        });
        setEditingNote(null);
        setEditingText('');
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Không thể lưu ghi chú.');
      }
    });
  };

  const handleDeleteNote = (noteId: string) => {
    setActionError(null);
    startTransition(async () => {
      try {
        await adapter.document.deleteNote(noteId);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Không thể xóa ghi chú.');
      }
    });
  };

  const handleDeleteBookmark = (docId: string, classId: string) => {
    setActionError(null);
    startTransition(async () => {
      try {
        await adapter.document.toggleBookmark(docId, classId);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Không thể gỡ dấu trang.');
      }
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
              note.pageNumber ? `?page=${note.pageNumber}` : ''
            }`;

            return (
              <article key={note.id} className="note-card card">
                <header className="note-card-header">
                  <div className="note-title-line">
                    <span className="badge primary text-xs">{note.documentFormat}</span>
                    <Link href={readerHref} className="note-doc-title-link">
                      <strong>{note.documentTitle}</strong>
                    </Link>
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
                      <span>Nguồn tài liệu đã bị thu hồi hoặc xóa. Trích dẫn đã ẩn theo quy định học vụ.</span>
                    </div>
                  ) : null}

                  <p className="note-text-content">{note.noteText}</p>
                </div>

                <footer className="note-card-footer">
                  <span className="text-xs muted">{note.updatedAt}</span>
                  <div className="note-actions">
                    <button
                      type="button"
                      className="button small secondary"
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
              bm.pageNumber ? `?page=${bm.pageNumber}` : ''
            }`;

            return (
              <article key={bm.id} className="bookmark-card card">
                <header className="note-card-header">
                  <div className="note-title-line">
                    <span className="badge primary text-xs">{bm.documentFormat}</span>
                    <Link href={readerHref} className="note-doc-title-link">
                      <strong>{bm.documentTitle}</strong>
                    </Link>
                  </div>
                  <div className="note-meta-badges">
                    <span className="badge secondary text-xs">{bm.className}</span>
                    <span className="badge info text-xs">{bm.locator}</span>
                  </div>
                </header>

                <div className="bookmark-card-body">
                  <p className="text-xs muted">
                    Dấu trang được lưu tại <strong>{bm.locator}</strong> vào ngày {bm.createdAt}. Bấm vào nút bên dưới để mở đúng vị trí trong tài liệu.
                  </p>
                </div>

                <footer className="note-card-footer">
                  <span className="text-xs muted">Đã lưu: {bm.createdAt}</span>
                  <div className="note-actions">
                    <Link href={readerHref} className="button small primary">
                      <Icon name="book" />
                      <span>Mở tài liệu</span>
                    </Link>
                    <button
                      type="button"
                      className="button small danger"
                      onClick={() => handleDeleteBookmark(bm.documentId, bm.classId)}
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
      >
        <form onSubmit={handleUpdateNote} className="form-stack">
          {editingNote?.isSourceAccessible && editingNote.sourceQuote && (
            <div className="notice-box info">
              <p className="text-xs">
                <strong>Trích dẫn gốc:</strong> {editingNote.sourceQuote}
              </p>
            </div>
          )}
          {!editingNote?.isSourceAccessible && (
            <div className="notice-box info">
              <p className="text-xs">
                Nguồn tài liệu không còn khả dụng trong lớp học. Bạn vẫn có thể chỉnh sửa và lưu giữ ghi chú của riêng mình.
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
              onChange={e => setEditingText(e.target.value)}
              required
            />
          </div>
          <div className="actions">
            <button type="button" className="button secondary" onClick={() => setEditingNote(null)}>
              Hủy
            </button>
            <button type="submit" className="button primary" disabled={isPending || !editingText.trim()}>
              Lưu thay đổi
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
