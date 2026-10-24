'use client';
import {useEffect,useRef,useState,type KeyboardEvent} from 'react';
import {Dialog,ErrorNotice,Icon,StatePanel} from '@/components/ui';
import type {ClassFeedViewProps,FeedViewPost} from './feed-view-model';
import './feed.css';

function dateTime(value:string){return new Date(value).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit',year:'numeric'});}
function initials(name:string){return name.trim().split(/\s+/).slice(-2).map(word=>word[0]).join('').toUpperCase();}
function edited(created:string,updated?:string){return Boolean(updated&&Date.parse(updated)>Date.parse(created));}
function submitShortcut(event:KeyboardEvent<HTMLTextAreaElement>,submit:()=>void,disabled:boolean){
  if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.nativeEvent.isComposing){event.preventDefault();if(!disabled)submit();}
}

function PostCard({post,p}:{post:FeedViewPost;p:ClassFeedViewProps}){
  const [allComments,setAllComments]=useState(false),[fullText,setFullText]=useState(false);
  const locked=p.busy||p.unknown||!p.canParticipate;
  const linked=post.id===p.highlightedPostId;
  const showAll=allComments||linked&&Boolean(p.highlightedCommentId);
  const comments=showAll?post.comments:post.comments.slice(-3);
  const draft=p.commentDrafts[post.id]??'';
  return <article id={`feed-post-${post.id}`} data-post-id={post.id} tabIndex={-1} className={`feed-post-card${linked?' is-linked':''}`} aria-label={`Bài viết của ${post.authorName}`}>
    <header className="feed-post-top">
      <div className="feed-author-info">
        <span className={`feed-avatar${post.own?' is-own':''}`} aria-hidden="true">{initials(post.authorName)}</span>
        <div className="feed-author-meta"><strong>{post.authorName}</strong><span><time dateTime={post.createdAt}>{dateTime(post.createdAt)}</time>{edited(post.createdAt,post.updatedAt)&&' · Đã chỉnh sửa'}</span></div>
      </div>
      <div className="feed-post-actions">
        {post.canEdit&&<button className="icon-button" type="button" aria-label="Sửa bài viết" title="Sửa bài viết" disabled={locked} onClick={()=>p.onEditStart({type:'post',postId:post.id,content:post.content})}><Icon name="edit"/></button>}
        {post.canDelete&&<button className="icon-button" type="button" aria-label="Xóa bài viết" title="Xóa bài viết" disabled={locked} onClick={()=>p.onDeleteStart({type:'post',postId:post.id})}><Icon name="trash"/></button>}
      </div>
    </header>
    <div className="feed-post-content"><p>{fullText||post.content.length<=1600?post.content:post.content.slice(0,1600)+'…'}</p>
      {post.content.length>1600&&<button type="button" className="feed-text-button" aria-expanded={fullText} onClick={()=>setFullText(value=>!value)}>{fullText?'Thu gọn bài viết':'Đọc toàn bộ bài viết'}</button>}
    </div>
    <section className="feed-comments-region" aria-label={`Bình luận bài viết của ${post.authorName}`}>
      <div className="feed-comments-header"><span><Icon name="chat"/> {post.comments.length} bình luận</span>
        {post.comments.length>3&&<button className="feed-text-button" type="button" aria-expanded={showAll} onClick={()=>setAllComments(value=>!value)} disabled={linked&&Boolean(p.highlightedCommentId)}>{showAll?'Thu gọn':`Xem tất cả ${post.comments.length} bình luận`}</button>}
      </div>
      {post.comments.length===0&&<p className="feed-no-comments">Chưa có bình luận. Hãy bắt đầu cuộc trao đổi.</p>}
      <div className="feed-comments-list">{comments.map(comment=><div id={`feed-comment-${comment.id}`} key={comment.id} tabIndex={-1} className={`feed-comment-item${comment.id===p.highlightedCommentId?' is-linked':''}`}>
        <span className={`feed-avatar is-small${comment.own?' is-own':''}`} aria-hidden="true">{initials(comment.authorName)}</span>
        <div className="feed-comment-main"><div className="feed-comment-bubble"><strong>{comment.authorName}</strong><p>{comment.content}</p></div>
          <div className="feed-comment-meta"><time dateTime={comment.createdAt}>{dateTime(comment.createdAt)}</time>{edited(comment.createdAt,comment.updatedAt)&&<span>Đã chỉnh sửa</span>}</div>
        </div>
        <div className="feed-comment-actions">
          {comment.canEdit&&<button className="icon-button" type="button" aria-label="Sửa bình luận" title="Sửa bình luận" disabled={locked} onClick={()=>p.onEditStart({type:'comment',postId:post.id,commentId:comment.id,content:comment.content})}><Icon name="edit"/></button>}
          {comment.canDelete&&<button className="icon-button" type="button" aria-label="Xóa bình luận" title="Xóa bình luận" disabled={locked} onClick={()=>p.onDeleteStart({type:'comment',postId:post.id,commentId:comment.id})}><Icon name="trash"/></button>}
        </div>
      </div>)}</div>
      {p.canParticipate&&<form className="feed-reply-box" onSubmit={event=>{event.preventDefault();if(!locked&&draft.trim())p.onCreateComment(post.id);}}>
        <label className="sr-only" htmlFor={`feed-reply-${post.id}`}>Viết bình luận cho bài viết của {post.authorName}</label>
        <textarea id={`feed-reply-${post.id}`} placeholder="Viết bình luận…" rows={2} maxLength={10000} value={draft} disabled={p.busy}
          onChange={event=>p.onCommentDraftChange(post.id,event.target.value)} onKeyDown={event=>submitShortcut(event,()=>p.onCreateComment(post.id),locked||!draft.trim())}/>
        <button className="button primary" type="submit" disabled={locked||!draft.trim()}><Icon name="send"/>Gửi</button>
        <small>Enter để xuống dòng · Ctrl + Enter để gửi</small>
      </form>}
    </section>
  </article>;
}

export function ClassFeedView(p:ClassFeedViewProps){
  const [search,setSearch]=useState(''),[limit,setLimit]=useState(10);
  const focusedLink=useRef<string|null>(null);
  const targetKey=[p.highlightedPostId,p.highlightedCommentId].join(':');
  // Run once per notification target; routine synchronization must not steal focus or scroll.
  useEffect(()=>{
    if(p.loadState!=='ready'||!p.highlightedPostId||focusedLink.current===targetKey)return;
    const node=document.getElementById(p.highlightedCommentId?`feed-comment-${p.highlightedCommentId}`:`feed-post-${p.highlightedPostId}`);
    if(!node)return;
    focusedLink.current=targetKey;node.scrollIntoView({block:'center',behavior:'instant'});node.focus({preventScroll:true});
  },[targetKey,p.loadState,p.posts]);
  const needle=search.trim().toLocaleLowerCase('vi');
  const matching=p.posts.filter(post=>!needle||[post.content,post.authorName,...post.comments.map(comment=>comment.content)].some(text=>text.toLocaleLowerCase('vi').includes(needle)));
  const visible=matching.filter((post,index)=>index<limit||post.id===p.highlightedPostId);
  const locked=p.busy||p.unknown||!p.canParticipate;
  const refreshButton=<button className="button" type="button" disabled={p.busy||p.syncing} onClick={p.unknown?p.onReconcile:p.onRefresh}><Icon name="clock"/>{p.syncing?'Đang đồng bộ…':'Làm mới bảng tin'}</button>;
  const unknownNotice=p.unknown?<div className="feed-status is-warning" role="alert"><Icon name="info"/><div><strong>Chưa xác định kết quả thao tác.</strong><p>Kiểm tra nội dung hiện hành trước khi gửi lại. Bản nháp của bạn được giữ nguyên.</p><button className="button" type="button" disabled={p.busy||p.syncing} onClick={p.onReconcile}>Tải lại bảng tin</button></div></div>:null;
  if(p.loadState==='loading')return <div className="lumi-feed"><StatePanel busy title="Đang tải bảng tin…" message="Đang lấy bài viết và bình luận của lớp."/></div>;
  if(p.loadState==='unavailable')return <div className="lumi-feed"><StatePanel title="Chưa mở được bảng tin" message={p.loadMessage}>{refreshButton}</StatePanel></div>;
  return <div className="lumi-feed">
    <header className="feed-toolbar"><div><p className="feed-eyebrow">TRAO ĐỔI TRONG LỚP</p><h1>Bảng tin lớp</h1><p className="feed-sync-label">{p.syncing?'Đang đồng bộ bài viết và bình luận…':p.lastSyncedAt?`Cập nhật lúc ${new Date(p.lastSyncedAt).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})} · Tự cập nhật khi mở tab`:'Chưa có lần đồng bộ thành công'}</p></div>{refreshButton}</header>
    {p.readOnlyReason&&<div className="feed-status" role="status"><Icon name="lock"/><p>{p.readOnlyReason}</p></div>}
    {p.linkedPostMissing&&<div className="feed-status" role="status"><Icon name="info"/><p>Bài viết hoặc bình luận trong thông báo không còn khả dụng. Nội dung có thể đã bị xóa hoặc quyền truy cập đã thay đổi.</p></div>}
    {unknownNotice}
    {!p.unknown&&<ErrorNotice message={p.issue}/>}
    {p.canParticipate&&<section className="feed-composer-card" aria-label="Tạo bài viết">
      <div className="feed-composer-header"><span className="feed-avatar is-own" aria-hidden="true">{initials(p.actorName)}</span><div><strong>{p.actorName}</strong><span>{p.actorRole} · Chia sẻ với lớp</span></div></div>
      <form onSubmit={event=>{event.preventDefault();if(!locked&&p.draft.trim())p.onCreatePost();}}>
        <label className="sr-only" htmlFor="feed-new-post">Nội dung bài viết mới</label>
        <textarea id="feed-new-post" rows={3} maxLength={10000} placeholder="Đặt câu hỏi hoặc chia sẻ nội dung học tập với lớp…" value={p.draft} disabled={p.busy}
          onChange={event=>p.onDraftChange(event.target.value)} onKeyDown={event=>submitShortcut(event,p.onCreatePost,locked||!p.draft.trim())}/>
        <div className="feed-composer-footer"><small>Bài viết hiển thị với thành viên có quyền truy cập lớp.</small><button className="button primary" type="submit" disabled={locked||!p.draft.trim()}><Icon name="send"/>{p.busy?'Đang xử lý…':'Đăng bài viết'}</button></div>
      </form>
    </section>}
    <div className="feed-stream-toolbar"><h3>{p.posts.length} bài viết <span>· Mới nhất trước</span></h3><label className="feed-search"><span className="sr-only">Tìm bài viết và bình luận</span><input type="search" placeholder="Tìm trong bảng tin…" value={search} onChange={event=>{setSearch(event.target.value);setLimit(10);}}/></label></div>
    <div className="feed-posts-stream">{visible.map(post=><PostCard key={post.id} post={post} p={p}/>)}</div>
    {matching.length===0&&<StatePanel title={needle?'Không tìm thấy nội dung phù hợp':'Lớp chưa có bài viết'} message={needle?'Thử từ khóa khác để tìm trong bài viết và bình luận.':'Bài viết và cuộc trao đổi của lớp sẽ xuất hiện tại đây.'}>{needle&&<button className="button" type="button" onClick={()=>setSearch('')}>Xóa tìm kiếm</button>}</StatePanel>}
    {matching.length>visible.length&&<button className="button feed-load-more" type="button" onClick={()=>setLimit(value=>value+10)}>Xem thêm bài viết ({matching.length-visible.length})</button>}
    <Dialog open={Boolean(p.editTarget)} title={p.editTarget?.type==='comment'?'Sửa bình luận':'Sửa bài viết'} onClose={p.onEditClose} busy={p.busy} className="feed-dialog">
      <form className="form-stack" onSubmit={event=>{event.preventDefault();if(!locked&&p.editTarget?.content.trim())p.onEditSave();}}>
        <label htmlFor="feed-edit-content">Nội dung</label><textarea id="feed-edit-content" rows={6} maxLength={10000} value={p.editTarget?.content??''} disabled={p.busy} onChange={event=>p.onEditContent(event.target.value)}/>
        {unknownNotice}{!p.unknown&&<ErrorNotice message={p.issue}/>}
        <div className="actions"><button type="button" className="button" disabled={p.busy} onClick={p.onEditClose}>Hủy</button><button type="submit" className="button primary" disabled={locked||!p.editTarget?.content.trim()}>{p.editTarget?.type==='comment'?'Lưu bình luận':'Lưu bài viết'}</button></div>
      </form>
    </Dialog>
    <Dialog open={Boolean(p.deleteTarget)} title={p.deleteTarget?.type==='comment'?'Xóa bình luận?':'Xóa bài viết?'} onClose={p.onDeleteClose} busy={p.busy} className="feed-dialog">
      <p>{p.deleteTarget?.type==='comment'?'Bình luận sẽ không còn hiển thị trong cuộc trao đổi.':'Bài viết và các bình luận thuộc bài viết sẽ không còn hiển thị trên bảng tin.'}</p>
      {unknownNotice}{!p.unknown&&<ErrorNotice message={p.issue}/>}
      <div className="actions"><button type="button" className="button" disabled={p.busy} onClick={p.onDeleteClose}>Hủy</button><button type="button" className="button danger" disabled={locked} onClick={p.onDeleteConfirm}>Xác nhận xóa</button></div>
    </Dialog>
  </div>;
}
