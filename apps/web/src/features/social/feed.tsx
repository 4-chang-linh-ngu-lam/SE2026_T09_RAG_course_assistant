'use client';
import {useEffect,useRef,useState} from 'react';
import type {Role,RouteParams,User,WorkspaceData} from '@/lib/domain';
import {adapter} from '@/lib/data';
import {resourceUuid} from '@/lib/api/operations';
import {socialAccess} from '@/lib/social-access';
import {createClassFeedController,type ClassFeedState,type FeedCommand} from '@/lib/class-feed-controller';
import {subscribeForegroundSync} from '@/lib/foreground-sync';
import {useClassSummary} from '@/components/class-summary-context';
import {ClassFeedView} from './feed-view';
import type {FeedDeleteTarget,FeedEditTarget} from './feed-view-model';

type Props={data:WorkspaceData|null;role:Role;user:User;params:RouteParams;reload():void};
export function ClassFeedFeature({role,user,params}:Props){
  const classId=params.classId;
  const actorKey=JSON.stringify([user.id,user.school_id,user.roles]);
  const scope=JSON.stringify([actorKey,classId,role]);
  const controllerRef=useRef<ReturnType<typeof createClassFeedController>|null>(null);
  const [snapshot,setSnapshot]=useState<{scope:string;state:ClassFeedState}|null>(null);
  const state:ClassFeedState=snapshot?.scope===scope?snapshot.state:{posts:[],summary:undefined,loaded:false,syncing:true,busy:false,unknown:false,issue:null,stale:false,lastSyncedAt:null};
  const [draft,setDraft]=useState(''),[commentDrafts,setCommentDrafts]=useState<Record<string,string>>({});
  const [editTarget,setEditTarget]=useState<FeedEditTarget|null>(null),[deleteTarget,setDeleteTarget]=useState<FeedDeleteTarget|null>(null);
  useEffect(()=>{
    const controller=createClassFeedController({user,classId,social:adapter.social,
      load:signal=>adapter.workspace.load(role==='LECTURER'?'t.feed':'s.feed',{classId},signal)});
    controllerRef.current=controller;
    const publish=()=>setSnapshot({scope,state:controller.getState()});
    const unsubscribe=controller.subscribe(publish);publish();
    const stop=subscribeForegroundSync(()=>{void controller.refresh();});
    return()=>{stop();unsubscribe();controller.dispose();if(controllerRef.current===controller)controllerRef.current=null;};
  },[scope]);
  useClassSummary(state.summary,!state.loaded&&state.syncing);
  const access=socialAccess(user,state.summary,classId),participate=access.participate&&!state.stale;
  const ownName=user.display_name??user.username??'Bạn';
  const posts=state.posts.map(post=>({...post,own:post.authorId===user.id,authorName:post.authorId===user.id?'Bạn':post.authorName,
    canEdit:participate&&post.authorId===user.id&&post.canEdit!==false,
    canDelete:participate&&post.canDelete!==false&&(access.moderate||post.authorId===user.id),
    comments:post.comments.map(comment=>({...comment,own:comment.authorId===user.id,authorName:comment.authorId===user.id?'Bạn':comment.authorName,
      canEdit:participate&&comment.authorId===user.id,canDelete:participate&&comment.canDelete!==false&&(access.moderate||comment.authorId===user.id)}))}));
  const postId=resourceUuid.test(params.postId??'')?params.postId.toLowerCase():undefined;
  const commentId=resourceUuid.test(params.commentId??'')?params.commentId.toLowerCase():undefined;
  const linkedPost=posts.find(post=>post.id===postId);
  const linkedPostMissing=state.loaded&&Boolean(postId)&&(!linkedPost||Boolean(commentId)&&!linkedPost.comments.some(comment=>comment.id===commentId));
  async function send(command:FeedCommand,confirmed:()=>void){if(await controllerRef.current?.execute(command))confirmed();}
  return <ClassFeedView loadState={state.loaded?'ready':state.issue?'unavailable':'loading'} loadMessage={state.issue??undefined}
    className={state.summary?.name??'Bảng tin lớp'} actorName={ownName} actorRole={role==='LECTURER'?'Giáo viên':'Học sinh'}
    posts={posts} canParticipate={participate} readOnlyReason={participate?null:state.stale?'Chưa kiểm tra được trạng thái lớp hiện hành. Tải lại trước khi gửi.':state.summary?.status==='ARCHIVED'?'Lớp đã lưu trữ. Bạn có thể đọc lại nội dung.':'Bạn không có quyền tham gia bảng tin lớp này.'}
    busy={state.busy} syncing={state.syncing} lastSyncedAt={state.lastSyncedAt} issue={state.issue} unknown={state.unknown}
    draft={draft} commentDrafts={commentDrafts} editTarget={editTarget} deleteTarget={deleteTarget}
    highlightedPostId={postId} highlightedCommentId={commentId} linkedPostMissing={linkedPostMissing}
    onRefresh={()=>{void controllerRef.current?.refresh();}} onReconcile={()=>{void controllerRef.current?.refresh(true);}} onDraftChange={setDraft}
    onCreatePost={()=>{void send({type:'createPost',content:draft},()=>setDraft(''));}}
    onCommentDraftChange={(id,value)=>setCommentDrafts(previous=>({...previous,[id]:value}))}
    onCreateComment={id=>{void send({type:'createComment',postId:id,content:commentDrafts[id]??''},()=>setCommentDrafts(previous=>({...previous,[id]:''})));}}
    onEditStart={setEditTarget} onEditContent={content=>setEditTarget(previous=>previous?{...previous,content}:null)}
    onEditClose={()=>{if(!state.busy)setEditTarget(null);}}
    onEditSave={()=>{if(!editTarget)return;const command:FeedCommand=editTarget.type==='post'?{type:'updatePost',postId:editTarget.postId,content:editTarget.content}:{type:'updateComment',postId:editTarget.postId,commentId:editTarget.commentId!,content:editTarget.content};void send(command,()=>setEditTarget(null));}}
    onDeleteStart={setDeleteTarget} onDeleteClose={()=>{if(!state.busy)setDeleteTarget(null);}}
    onDeleteConfirm={()=>{if(!deleteTarget)return;const command:FeedCommand=deleteTarget.type==='post'?{type:'deletePost',postId:deleteTarget.postId}:{type:'deleteComment',postId:deleteTarget.postId,commentId:deleteTarget.commentId!};void send(command,()=>setDeleteTarget(null));}}/>;
}
