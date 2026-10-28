'use client';
import { useEffect, useState } from 'react';
import type { FeedComment, FeedPost, Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { adapter, dataMode } from '@/lib/data';
import { Dialog, ErrorNotice, Icon, StatePanel } from '@/components/ui';

type Props = {
  data: WorkspaceData | null;
  role: Role;
  user: User;
  params: RouteParams;
  reload(): void;
};

export function ClassFeedFeature({ data, role, user, params, reload }: Props) {
  const [localPosts, setLocalPosts] = useState<FeedPost[] | null>(null);
  const [newPostContent, setNewPostContent] = useState('');
  const [commentInputs, setCommentInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingCommentsId, setLoadingCommentsId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingPostId, setEditingPostId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');

  // Deletion modal state
  const [deleteTarget, setDeleteTarget] = useState<
    | { type: 'post'; postId: string }
    | { type: 'comment'; postId: string; commentId: string }
    | null
  >(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  useEffect(() => {
    setLocalPosts(null);
    setNextCursor(data?.kind === 'ready' ? data.feedNextCursor ?? null : null);
  }, [data, params.classId]);

  if (!data) return <StatePanel busy title="Đang tải bảng tin…"/>;

  if (data.kind === 'unavailable') {
    return (
      <div className="workspace-content">
        <div className="card padded">
          <div className="section-heading">
            <div>
              <h2>Bảng tin lớp học</h2>
              <p className="muted">Trao đổi và thông báo học tập</p>
            </div>
            <button className="button" onClick={reload}>Thử lại</button>
          </div>
          <StatePanel title="Dịch vụ bảng tin chưa sẵn sàng" message={data.message}>
            <button className="button" onClick={reload}>Tải lại</button>
          </StatePanel>
        </div>
      </div>
    );
  }

  if (data.kind === 'empty') {
    return (
      <div className="workspace-content">
        <div className="card padded">
          <div className="section-heading">
            <div>
              <h2>Bảng tin lớp học</h2>
              <p className="muted">Trao đổi và thông báo học tập</p>
            </div>
            <button className="button" onClick={reload}>Thử lại</button>
          </div>
          <StatePanel title="Chưa có bài viết nào trên bảng tin" message={data.message} />
        </div>
      </div>
    );
  }

  const readyData = data;
  const posts = localPosts ?? readyData.feedPosts ?? [];
  const isTeacher = role === 'LECTURER';

  async function handleLoadMorePosts() {
    if (!nextCursor || !params.classId || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await adapter.social.listPosts(params.classId, nextCursor);
      setLocalPosts(current => [...(current ?? posts), ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Chưa thể tải thêm bài viết.');
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleLoadMoreComments(postId: string, cursor: string) {
    if (!params.classId || loadingCommentsId) return;
    setLoadingCommentsId(postId);
    setError(null);
    try {
      const page = await adapter.social.listComments(params.classId, postId, cursor);
      setLocalPosts(current => (current ?? posts).map(post => post.id === postId
        ? { ...post, comments: [...post.comments, ...page.items], commentsNextCursor: page.next_cursor }
        : post));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Chưa thể tải thêm bình luận.');
    } finally {
      setLoadingCommentsId(null);
    }
  }

  async function handleUpdatePost(postId: string) {
    if (!editContent.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await adapter.social.updatePost(params.classId, postId, editContent.trim());
      setLocalPosts(posts.map(p => (p.id === postId ? updated : p)));
      setEditingPostId(null);
      setEditContent('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Chưa thể cập nhật bài viết.');
    } finally {
      setBusy(false);
    }
  }

  async function handleCreatePost(event: React.FormEvent) {
    event.preventDefault();
    if (!newPostContent.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await adapter.social.createPost(params.classId, newPostContent.trim());
      setLocalPosts([created, ...posts]);
      setNewPostContent('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Chưa thể đăng bài.');
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateComment(postId: string) {
    const text = commentInputs[postId]?.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const created = await adapter.social.createComment(params.classId, postId, text);
      const updated = posts.map(p => {
        if (p.id === postId) {
          return { ...p, comments: [...p.comments, created] };
        }
        return p;
      });
      setLocalPosts(updated);
      setCommentInputs(prev => ({ ...prev, [postId]: '' }));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Chưa thể gửi phản hồi.');
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    setError(null);
    try {
      if (deleteTarget.type === 'post') {
        await adapter.social.deletePost(params.classId, deleteTarget.postId);
        setLocalPosts(posts.filter(p => p.id !== deleteTarget.postId));
      } else {
        await adapter.social.deleteComment(params.classId, deleteTarget.postId, deleteTarget.commentId);
        setLocalPosts(
          posts.map(p => {
            if (p.id === deleteTarget.postId) {
              return { ...p, comments: p.comments.filter(c => c.id !== deleteTarget.commentId) };
            }
            return p;
          })
        );
      }
      setDeleteTarget(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Chưa thể xóa nội dung.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="feed-container">
      {/* Composer Card */}
      <section className="card padded feed-composer-card">
        <div className="feed-composer-header">
          <div className="avatar" aria-hidden="true">
            {(user.display_name ?? 'MA').split(' ').slice(-2).map(x => x[0]).join('')}
          </div>
          <div>
            <strong>{user.display_name ?? user.username ?? 'Tài khoản'}</strong>
            <span className={`tag ${isTeacher ? 'tag-amber' : 'tag-blue'}`} style={{ marginLeft: '8px' }}>
              {isTeacher ? 'Giáo viên phụ trách' : 'Học sinh'}
            </span>
          </div>
        </div>

        <form onSubmit={handleCreatePost} className="form-stack" style={{ marginTop: '14px' }}>
          <label htmlFor="feed-new-post" className="sr-only">Nội dung bài viết mới</label>
          <textarea
            id="feed-new-post"
            rows={3}
            placeholder={
              isTeacher
                ? 'Đăng thông báo hoặc hướng dẫn học tập cho cả lớp...'
                : 'Đặt câu hỏi hoặc chia sẻ trao đổi bài học với lớp...'
            }
            value={newPostContent}
            onChange={e => setNewPostContent(e.target.value)}
          />

          <ErrorNotice message={error}/>

          <div className="actions" style={{ justifyContent: 'flex-end' }}>
            <button
              className="button primary"
              type="submit"
              disabled={busy || !newPostContent.trim()}
            >
              <Icon name="send"/> {isTeacher ? 'Đăng thông báo' : 'Đăng bài viết'}
            </button>
          </div>
        </form>
      </section>

      {/* Posts Stream */}
      <div className="feed-posts-stream">
        {posts.length === 0 ? (
          <div className="card padded" style={{ textAlign: 'center' }}>
            <p className="muted">Chưa có bài viết nào trên bảng tin lớp.</p>
          </div>
        ) : (
          posts.map(post => {
            const canEditPost = post.canEdit ?? post.authorId === user.id;
            const canDeletePost = post.canDelete ?? (isTeacher || post.authorId === user.id);
            return (
              <article key={post.id} className={`card padded feed-post-card ${post.isAnnouncement ? 'announcement-post' : ''}`}>
                <div className="feed-post-top">
                  <div className="feed-author-info">
                    <div className="avatar" aria-hidden="true">
                      {post.authorAvatar ?? post.authorName.split(' ').slice(-2).map(x => x[0]).join('')}
                    </div>
                    <div>
                      <div className="feed-author-name-row">
                        <strong>{post.authorName}</strong>
                        {post.authorRole && <span className={`tag ${post.authorRole === 'TEACHER' ? 'tag-amber' : 'tag-blue'}`}>
                          {post.authorRole === 'TEACHER' ? 'Giáo viên' : 'Học sinh'}
                        </span>}
                      </div>
                      <time className="muted">{formatDateTime(post.createdAt)}</time>
                    </div>
                  </div>

                  <div className="feed-post-actions">
                    {canEditPost && (
                      <button
                        className="icon-button"
                        type="button"
                        aria-label="Sửa bài viết"
                        title="Sửa bài viết"
                        onClick={() => {
                          setEditingPostId(post.id);
                          setEditContent(post.content);
                        }}
                      >
                        <Icon name="edit" />
                      </button>
                    )}
                    {canDeletePost && (
                      <button
                        className="icon-button"
                        type="button"
                        aria-label="Xóa bài viết"
                        title="Xóa bài viết"
                        onClick={() => setDeleteTarget({ type: 'post', postId: post.id })}
                      >
                        <Icon name="trash"/>
                      </button>
                    )}
                  </div>
                </div>

                <div className="feed-post-content">
                  {editingPostId === post.id ? (
                    <form
                      onSubmit={e => {
                        e.preventDefault();
                        void handleUpdatePost(post.id);
                      }}
                      className="form-stack"
                    >
                      <textarea
                        value={editContent}
                        onChange={e => setEditContent(e.target.value)}
                        rows={3}
                        aria-label="Chỉnh sửa nội dung bài viết"
                      />
                      <div className="actions" style={{ justifyContent: 'flex-end' }}>
                        <button
                          type="button"
                          className="button small"
                          onClick={() => {
                            setEditingPostId(null);
                            setEditContent('');
                          }}
                        >
                          Hủy
                        </button>
                        <button
                          type="submit"
                          className="button primary small"
                          disabled={busy || !editContent.trim()}
                        >
                          Lưu
                        </button>
                      </div>
                    </form>
                  ) : (
                    <p>{post.content}</p>
                  )}
                </div>

                {/* Comments Section */}
                <div className="feed-comments-region">
                  <div className="feed-comments-header">
                    <span className="muted" style={{ fontWeight: 600, fontSize: '12px' }}>
                      Bình luận ({post.comments.length}{post.commentsNextCursor ? '+' : ''})
                    </span>
                  </div>

                  <div className="feed-comments-list">
                    {post.comments.map(comment => {
                      const canDeleteComment = isTeacher || comment.authorId === user.id;
                      return (
                        <div key={comment.id} className="feed-comment-item">
                          <div className="feed-comment-main">
                            <div className="feed-comment-meta">
                              <strong>{comment.authorName}</strong>
                              {comment.authorRole === 'TEACHER' ? (
                                <span className="tag tag-amber">Giáo viên</span>
                              ) : comment.authorRole === 'STUDENT' ? (
                                <span className="tag">{comment.authorClass ?? 'Học sinh'}</span>
                              ) : null}
                              <time className="muted">{formatDateTime(comment.createdAt)}</time>
                            </div>
                            <p className="feed-comment-text">{comment.content}</p>
                          </div>

                          {(comment.canDelete ?? canDeleteComment) && (
                            <button
                              className="icon-button"
                              type="button"
                              aria-label="Xóa bình luận"
                              title="Xóa bình luận"
                              style={{ minWidth: '32px', height: '32px' }}
                              onClick={() =>
                                setDeleteTarget({
                                  type: 'comment',
                                  postId: post.id,
                                  commentId: comment.id,
                                })
                              }
                            >
                              <Icon name="trash"/>
                            </button>
                          )}
                        </div>
                      );
                    })}
                    {post.commentsNextCursor && <button className="accounts-link" type="button" disabled={loadingCommentsId === post.id} onClick={() => void handleLoadMoreComments(post.id, post.commentsNextCursor!)}>{loadingCommentsId === post.id ? 'Đang tải…' : 'Tải thêm bình luận'}</button>}
                  </div>

                  {/* Inline Reply Field */}
                  <div className="feed-reply-box">
                    <label htmlFor={`reply-input-${post.id}`} className="sr-only">Viết phản hồi</label>
                    <input
                      id={`reply-input-${post.id}`}
                      placeholder={isTeacher ? 'Viết phản hồi cho học sinh...' : 'Viết phản hồi...'}
                      value={commentInputs[post.id] ?? ''}
                      onChange={e =>
                        setCommentInputs({ ...commentInputs, [post.id]: e.target.value })
                      }
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          void handleCreateComment(post.id);
                        }
                      }}
                    />
                    <button
                      className="button primary"
                      type="button"
                      disabled={busy || !commentInputs[post.id]?.trim()}
                      onClick={() => void handleCreateComment(post.id)}
                    >
                      Gửi
                    </button>
                  </div>
                </div>
              </article>
            );
          })
        )}
        {nextCursor && <div className="feed-load-more"><button className="button" type="button" disabled={loadingMore} onClick={() => void handleLoadMorePosts()}>{loadingMore ? 'Đang tải…' : 'Tải bài viết cũ hơn'}</button></div>}
      </div>

      {/* Delete Confirmation Dialog */}
      <Dialog
        busy={busy}
        open={!!deleteTarget}
        title={deleteTarget?.type === 'post' ? 'Xác nhận xóa bài viết?' : 'Xác nhận xóa bình luận?'}
        onClose={() => setDeleteTarget(null)}
      >
        <p>
          {deleteTarget?.type === 'post'
            ? 'Bài viết và toàn bộ phản hồi liên quan sẽ bị gỡ khỏi bảng tin khỏi bảng tin lớp.'
            : 'Bình luận này sẽ bị xóa khỏi bài viết.'}
        </p>
        <div className="actions" style={{ justifyContent: 'flex-end', marginTop: '20px' }}>
          <button className="button" type="button" disabled={busy} onClick={() => setDeleteTarget(null)}>
            Hủy
          </button>
          <button className="button danger" type="button" disabled={busy} onClick={() => void handleConfirmDelete()}>
            {busy ? 'Đang xóa…' : 'Xác nhận xóa'}
          </button>
        </div>
      </Dialog>
    </div>
  );
}

function formatDateTime(isoString: string) {
  try {
    return new Date(isoString).toLocaleString('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoString;
  }
}
