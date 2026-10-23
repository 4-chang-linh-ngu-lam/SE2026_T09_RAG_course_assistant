'use client';
import React, { useEffect, useState } from 'react';
import {ApiError} from '@/lib/api/errors';
import type { FeedComment, FeedPost, Role, RouteParams, User, WorkspaceData } from '@/lib/domain';
import { adapter, dataMode } from '@/lib/data';
import { socialAccess } from '@/lib/social-access';
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
  const [unknown,setUnknown]=useState(false);
  useEffect(()=>{if(data?.kind==='ready'){setLocalPosts(null);setUnknown(false);setError(null);}},[data]);
  const [error, setError] = useState<string | null>(null);
  const [editingPostId, setEditingPostId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editingComment,setEditingComment]=useState<{postId:string;comment:FeedComment}|null>(null);
  const [commentEditContent,setCommentEditContent]=useState('');

  // Deletion modal state
  const [deleteTarget, setDeleteTarget] = useState<
    | { type: 'post'; postId: string }
    | { type: 'comment'; postId: string; commentId: string }
    | null
  >(null);

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
  const access = socialAccess(user, readyData.classSummary, params.classId);

  async function handleUpdatePost(postId: string) {
    if(busy||unknown)return;
    if (!access.participate || !posts.some(post => post.id === postId && post.authorId === user.id && post.canEdit !== false) || !editContent.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await adapter.social.updatePost(params.classId, postId, editContent.trim());
      setLocalPosts(posts.map(p => (p.id === postId ? {...updated,comments:p.comments} : p)));
      setEditingPostId(null);
      setEditContent('');
    } catch (err: unknown) {
      if(err instanceof ApiError&&err.outcome==='unknown')setUnknown(true);
      setError(err instanceof Error ? err.message : 'Chưa thể cập nhật bài viết.');
    } finally {
      setBusy(false);
    }
  }

  async function handleCreatePost(event: React.FormEvent) {
    event.preventDefault();
    if(busy||unknown)return;
    if (!access.participate || !newPostContent.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await adapter.social.createPost(params.classId, newPostContent.trim());
      setLocalPosts([created, ...posts]);
      setNewPostContent('');
    } catch (err: unknown) {
      if(err instanceof ApiError&&err.outcome==='unknown')setUnknown(true);
      setError(err instanceof Error ? err.message : 'Chưa thể đăng bài.');
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateComment(postId: string) {
    if(busy||unknown)return;
    if (!access.participate) return;
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
      if(err instanceof ApiError&&err.outcome==='unknown')setUnknown(true);
      setError(err instanceof Error ? err.message : 'Chưa thể gửi phản hồi.');
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmDelete() {
    if(busy||unknown)return;
    if (!deleteTarget || !access.participate) return;
    const post = posts.find(item => item.id === deleteTarget.postId);
    const target = deleteTarget.type === 'post' ? post : post?.comments.find(item => item.id === deleteTarget.commentId);
    if (!target || target.canDelete === false || !(access.moderate || target.authorId === user.id)) return;
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
      if(err instanceof ApiError&&err.outcome==='unknown')setUnknown(true);
      setError(err instanceof Error ? err.message : 'Chưa thể xóa nội dung.');
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateComment(){
    if(busy||unknown||!access.participate||!editingComment||editingComment.comment.authorId!==user.id||!commentEditContent.trim())return;
    setBusy(true);setError(null);
    try{
      const updated=await adapter.social.updateComment(params.classId,editingComment.postId,editingComment.comment.id,commentEditContent.trim());
      setLocalPosts(posts.map(post=>post.id===editingComment.postId?{...post,comments:post.comments.map(comment=>comment.id===updated.id?updated:comment)}:post));
      setEditingComment(null);setCommentEditContent('');
    }catch(err){if(err instanceof ApiError&&err.outcome==='unknown')setUnknown(true);setError(err instanceof Error?err.message:'Chưa thể sửa bình luận.');}
    finally{setBusy(false);}
  }

  return (
    <div className="feed-container">
      {unknown&&<p className="notice">Chưa xác định kết quả thao tác. Tải trạng thái hiện tại và kiểm tra nội dung trước khi gửi thao tác mới. <button className="button" onClick={reload}>Tải lại bảng tin</button></p>}
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
              disabled={busy || !access.participate || !newPostContent.trim()}
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
            const canEditPost = access.participate && post.authorId === user.id && post.canEdit !== false;
            const canDeletePost = access.participate && post.canDelete !== false && (access.moderate || post.authorId === user.id);
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
                        {post.authorRole&&<span className={`tag ${post.authorRole === 'TEACHER' ? 'tag-amber' : 'tag-blue'}`}>
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
                      Bình luận ({post.comments.length})
                    </span>
                  </div>

                  <div className="feed-comments-list">
                    {post.comments.map(comment => {
                      const canDeleteComment = access.participate && comment.canDelete !== false && (access.moderate || comment.authorId === user.id);
                      return (
                        <div key={comment.id} className="feed-comment-item">
                          <div className="feed-comment-main">
                            <div className="feed-comment-meta">
                              <strong>{comment.authorName}</strong>
                              {comment.authorRole === 'TEACHER' ? (
                                <span className="tag tag-amber">Giáo viên</span>
                              ) : comment.authorRole==='STUDENT' ? (
                                <span className="tag">{comment.authorClass ?? 'Học sinh'}</span>
                              ) : null}
                              <time className="muted">{formatDateTime(comment.createdAt)}</time>
                            </div>
                            <p className="feed-comment-text">{comment.content}</p>
                          </div>

                          {access.participate&&comment.authorId===user.id&&<button className="icon-button" type="button" aria-label="Sửa bình luận" title="Sửa bình luận" disabled={busy||unknown} onClick={()=>{setEditingComment({postId:post.id,comment});setCommentEditContent(comment.content);}}><Icon name="edit"/></button>}
                          {canDeleteComment && (
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
                      disabled={busy || !access.participate || !commentInputs[post.id]?.trim()}
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
      </div>

      {/* Delete Confirmation Dialog */}
      <Dialog busy={busy} open={Boolean(editingComment)} title="Sửa bình luận" onClose={()=>setEditingComment(null)}>
        <form className="form-stack" onSubmit={event=>{event.preventDefault();void handleUpdateComment();}}>
          <label>Nội dung bình luận<textarea value={commentEditContent} onChange={event=>setCommentEditContent(event.target.value)} maxLength={10000} required/></label>
          <ErrorNotice message={error}/>
          {unknown&&<p className="notice">Chưa rõ kết quả. Đóng và tải lại bảng tin để đối chiếu.</p>}
          <button className="button primary" disabled={busy||unknown||!access.participate||!commentEditContent.trim()}>Lưu bình luận</button>
        </form>
      </Dialog>
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
