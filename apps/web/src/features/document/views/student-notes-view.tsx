'use client';
import { useState, useMemo, useTransition } from 'react';
import Link from 'next/link';
import type { RouteDefinition } from '@/config/routes';
import type { BookmarkItem, PersonalNoteItem, WorkspaceData } from '@/lib/domain';
import { adapter } from '@/lib/data';
import { StatePanel, Icon, Dialog, ErrorNotice, useUnsavedChanges } from '@/components/ui';
import { personalSourceHref } from '@/lib/document-preview';

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
  const [deleteTarget, setDeleteTarget] = useState<
    { kind: 'note'; item: PersonalNoteItem } | { kind: 'bookmark'; item: BookmarkItem } | null
  >(null);
  const { confirmDiscard } = useUnsavedChanges(Boolean(editingNote && editingText !== editingNote.noteText));

  function closeEditor() {
    if (!isPending && confirmDiscard()) {
      setEditingNote(null);
      setEditingText('');
      setActionError(null);
    }
  }

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
    if (!editingNote || !editingText.trim() || isPending) return;
    setActionError(null);
    startTransition(async () => {
      try {
        await adapter.document.saveNote({
          id: editingNote.id,
          documentId: editingNote.documentId,
          classId: editingNote.classId,
          locator: editingNote.locator,
          version: editingNote.version,
          pageNumber: editingNote.pageNumber,
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

  const confirmDelete = () => {
    if (!deleteTarget || isPending) return;
    setActionError(null);
    startTransition(async () => {
      try {
        if (deleteTarget.kind === 'note') await adapter.document.deleteNote(deleteTarget.item.id);
        else await adapter.document.toggleBookmark(deleteTarget.item.documentId, deleteTarget.item.classId);
        setDeleteTarget(null);
        reload();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : 'Không thể xóa nội dung đã chọn.');
      }
    });
  };

  const totalCount = filteredNotes.length + filteredBookmarks.length;

  return (
    <div className="student-notes-container">
      {/* Top filter toolbar */}
      <div className="notes-toolbar card">
        <div className="tab-group" role="group" aria-label="Phân loại nội dung">
          <button
            type="button"
            aria-pressed={tab === 'all'}
            className={`tab-btn ${tab === 'all' ? 'active' : ''}`}
            onClick={() => setTab('all')}
          >
            Tất cả ({allNotes.length + allBookmarks.length})
          </button>
          <button
            type="button"
            aria-pressed={tab === 'notes'}
            className={`tab-btn ${tab === 'notes' ? 'active' : ''}`}
            onClick={() => setTab('notes')}
          >
            Ghi chú ({allNotes.length})
          </button>
          <button
            type="button"
            aria-pressed={tab === 'bookmarks'}
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

      {!editingNote && !deleteTarget && <ErrorNotice message={actionError}/>}

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
            const readerHref = personalSourceHref(note);

            return (
              <article key={note.id} className="note-card card">
                <header className="note-card-header">
                  <div className="note-title-line">
                    <span className="doc-format-pill" data-format={note.documentFormat.toLowerCase()}>
                      {note.documentFormat}
                    </span>
                    <Link href={readerHref} className="note-doc-title-link">
                      <strong>{note.documentTitle}</strong>
                    </Link>
                  </div>
                  <div className="note-meta-badges">
                    <span className="badge secondary">{note.className}</span>
                    <span className="badge info">{note.locator}</span>
                    {note.classStatus === 'ARCHIVED' && (
                      <span className="badge warning" title="Lớp đã lưu trữ, cho phép xem và sửa ghi chú theo quy tắc O2">
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
                  <span className="note-timestamp">{note.updatedAt}</span>
                  <div className="note-actions">
                    <button
                      type="button"
                      className="button small secondary"
                      disabled={isPending}
                      onClick={() => {
                        setActionError(null);
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
                      onClick={() => { setActionError(null); setDeleteTarget({ kind: 'note', item: note }); }}
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
            const readerHref = personalSourceHref(bm);

            return (
              <article key={bm.id} className="bookmark-card card">
                <header className="note-card-header">
                  <div className="note-title-line">
                    <span className="doc-format-pill" data-format={bm.documentFormat.toLowerCase()}>
                      {bm.documentFormat}
                    </span>
                    <Link href={readerHref} className="note-doc-title-link">
                      <strong>{bm.documentTitle}</strong>
                    </Link>
                  </div>
                  <div className="note-meta-badges">
                    <span className="badge secondary">{bm.className}</span>
                    <span className="badge info">{bm.locator}</span>
                  </div>
                </header>

                <div className="bookmark-card-body">
                  <p className="bookmark-summary-text">
                    Dấu trang được lưu tại <strong>{bm.locator}</strong> vào ngày {bm.createdAt}. Bấm vào nút bên dưới để mở đúng vị trí trong tài liệu.
                  </p>
                </div>

                <footer className="note-card-footer">
                  <span className="note-timestamp">Đã lưu: {bm.createdAt}</span>
                  <div className="note-actions">
                    <Link href={readerHref} className="button small primary">
                      <Icon name="book" />
                      <span>Mở tài liệu</span>
                    </Link>
                    <button
                      type="button"
                      className="button small danger"
                      onClick={() => { setActionError(null); setDeleteTarget({ kind: 'bookmark', item: bm }); }}
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
        onClose={closeEditor}
        busy={isPending}
      >
        <form onSubmit={handleUpdateNote} className="form-stack">
          {editingNote?.isSourceAccessible && editingNote.sourceQuote && (
            <div className="notice-box info">
              <p>
                <strong>Trích dẫn gốc:</strong> {editingNote.sourceQuote}
              </p>
            </div>
          )}
          {!editingNote?.isSourceAccessible && (
            <div className="notice-box info">
              <p>
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
            <button type="button" className="button secondary" onClick={closeEditor} disabled={isPending}>
              Hủy
            </button>
            <button type="submit" className="button primary" disabled={isPending || !editingText.trim()}>
              {isPending ? 'Đang lưu…' : 'Lưu thay đổi'}
            </button>
          </div>
          <ErrorNotice message={actionError}/>
        </form>
      </Dialog>
      <Dialog open={Boolean(deleteTarget)} title={deleteTarget?.kind === 'note' ? 'Xóa ghi chú này?' : 'Gỡ dấu trang này?'} busy={isPending} onClose={() => { if (!isPending) { setDeleteTarget(null); setActionError(null); } }}>
        <p>{deleteTarget?.item.documentTitle} · {deleteTarget?.item.locator}</p>
        <p className="muted">{deleteTarget?.kind === 'note' ? 'Nội dung ghi chú cá nhân này sẽ bị xóa. Tài liệu gốc được giữ nguyên.' : 'Dấu trang sẽ được gỡ khỏi danh sách đã lưu.'}</p>
        <ErrorNotice message={actionError}/>
        <div className="actions">
          <button className="button secondary" disabled={isPending} onClick={() => { setDeleteTarget(null); setActionError(null); }}>Hủy</button>
          <button className="button danger" disabled={isPending} onClick={confirmDelete}>{isPending ? 'Đang xử lý…' : deleteTarget?.kind === 'note' ? 'Xóa ghi chú' : 'Gỡ dấu trang'}</button>
        </div>
      </Dialog>
    </div>
  );
}
