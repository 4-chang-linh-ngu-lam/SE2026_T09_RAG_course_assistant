import type {ClassSummary,FeedPost,User,WorkspaceData} from './domain';
import type {DataAdapter} from './data/port';
import {ApiError,errorMessage} from './api/errors';
import {socialAccess} from './social-access';

export type FeedCommand=
  |{type:'createPost';content:string}
  |{type:'updatePost';postId:string;content:string}
  |{type:'deletePost';postId:string}
  |{type:'createComment';postId:string;content:string}
  |{type:'updateComment';postId:string;commentId:string;content:string}
  |{type:'deleteComment';postId:string;commentId:string};
export type ClassFeedState={
  posts:FeedPost[];summary:ClassSummary|undefined;loaded:boolean;syncing:boolean;
  busy:boolean;unknown:boolean;issue:string|null;stale:boolean;lastSyncedAt:number|null;
};

/** A class/actor lifetime owns all reads and writes. Old snapshots cannot replace a confirmed write. */
export function createClassFeedController(deps:{user:User;classId:string;load(signal:AbortSignal):Promise<WorkspaceData>;social:DataAdapter['social']}){
  let state:ClassFeedState={posts:[],summary:undefined,loaded:false,syncing:false,busy:false,unknown:false,issue:null,stale:false,lastSyncedAt:null};
  let disposed=false,sequence=0,pending:AbortController|null=null;
  let mutationIssue:string|null=null;
  const listeners=new Set<()=>void>();
  const emit=(patch:Partial<ClassFeedState>)=>{if(disposed)return;state={...state,...patch};for(const listener of listeners)listener();};
  async function refresh(reconcile=false){
    if(disposed||state.busy||pending||state.unknown&&!reconcile)return;
    const request=new AbortController(),ticket=++sequence;pending=request;emit({syncing:true});
    try{
      const data=await deps.load(request.signal);
      if(disposed||request.signal.aborted||ticket!==sequence)return;
      if(data.kind!=='ready')throw new ApiError('UNAVAILABLE',data.message,503);
      if(reconcile)mutationIssue=null;
      emit({posts:data.feedPosts??[],summary:data.classSummary,loaded:true,stale:false,issue:mutationIssue,
        lastSyncedAt:Date.now(),...(reconcile?{unknown:false}:{})});
    }catch(error){
      if(disposed||request.signal.aborted||ticket!==sequence)return;
      // An authorization failure must immediately discard the previous class projection.
      const denied=error instanceof ApiError&&[401,403,404].includes(error.status);
      emit({stale:true,issue:errorMessage(error),...(denied?{posts:[],summary:undefined,loaded:false}:{})});
    }finally{
      if(pending===request){pending=null;emit({syncing:false});}
    }
  }
  function allowed(command:FeedCommand){
    if(!state.loaded||state.stale||!socialAccess(deps.user,state.summary,deps.classId).participate)return false;
    if('content'in command&&!command.content.trim())return false;
    if(command.type==='createPost')return true;
    const post=state.posts.find(row=>row.id===command.postId);
    if(!post)return false;
    if(command.type==='createComment')return true;
    const target='commentId'in command?post.comments.find(row=>row.id===command.commentId):post;
    if(!target)return false;
    const own=target.authorId===deps.user.id;
    if(command.type==='updatePost')return own&&post.canEdit!==false;
    if(command.type==='updateComment')return own;
    return target.canDelete!==false&&(own||socialAccess(deps.user,state.summary,deps.classId).moderate);
  }
  async function execute(command:FeedCommand):Promise<boolean>{
    if(disposed||state.busy||state.unknown||!allowed(command))return false;
    pending?.abort();pending=null;++sequence;mutationIssue=null;emit({busy:true,syncing:false,issue:null});
    const social=deps.social,klass=deps.classId;
    try{
      if(command.type==='createPost'){
        const created=await social.createPost(klass,command.content.trim());
        emit({posts:[created,...state.posts]});
      }else if(command.type==='updatePost'){
        const updated=await social.updatePost(klass,command.postId,command.content.trim());
        emit({posts:state.posts.map(row=>row.id===command.postId?{...updated,comments:row.comments}:row)});
      }else if(command.type==='deletePost'){
        await social.deletePost(klass,command.postId);emit({posts:state.posts.filter(row=>row.id!==command.postId)});
      }else if(command.type==='createComment'){
        const created=await social.createComment(klass,command.postId,command.content.trim());
        emit({posts:state.posts.map(row=>row.id===command.postId?{...row,comments:[...row.comments,created]}:row)});
      }else if(command.type==='updateComment'){
        const updated=await social.updateComment(klass,command.postId,command.commentId,command.content.trim());
        emit({posts:state.posts.map(row=>row.id===command.postId?{...row,comments:row.comments.map(comment=>comment.id===command.commentId?updated:comment)}:row)});
      }else{
        await social.deleteComment(klass,command.postId,command.commentId);
        emit({posts:state.posts.map(row=>row.id===command.postId?{...row,comments:row.comments.filter(comment=>comment.id!==command.commentId)}:row)});
      }
      if(disposed)return false;
      emit({busy:false});void refresh();return true;
    }catch(error){
      if(disposed)return false;
      const unknown=error instanceof ApiError&&error.outcome==='unknown';
      mutationIssue=errorMessage(error);
      emit({busy:false,unknown,issue:mutationIssue});
      // Permission/content may have changed since the previous snapshot. Re-read, never replay a write.
      if(!unknown)void refresh();
      return false;
    }
  }
  return {getState:()=>state,subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener);};},refresh,execute,
    dispose(){disposed=true;++sequence;pending?.abort();pending=null;listeners.clear();}};
}
