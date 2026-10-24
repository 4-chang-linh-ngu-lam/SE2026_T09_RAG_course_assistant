import type {createLiveCoreSession} from './live-identity';
import type {CoreApiPort,CoreClass,CorePost,CoreComment,CoreEvent} from '../api/core-contract';
import type {ClassSummary,User,FeedPost,FeedComment,CalendarEvent,Page,WorkspaceData,RouteParams} from '../domain';
import type {DataAdapter} from './port';
import {decodeUser} from '../api/decoders';
import {ApiError} from '../api/errors';
import {canonicalResourceId} from '../api/operations';

type Session=Pick<ReturnType<typeof createLiveCoreSession>,'authenticated'|'getActorId'>;
function mismatch():never{throw new ApiError('CONTRACT_MISMATCH','Dữ liệu không khớp ngữ cảnh. Hãy tải lại.');}
export async function allCorePages<T extends {id:string}>(load:(cursor?:string)=>Promise<Page<T>>,signal:AbortSignal):Promise<T[]>{
  const result:T[]=[],ids=new Set<string>(),cursors=new Set<string>();let cursor:string|undefined;
  do{
    if(signal.aborted)throw new ApiError('CONNECTION_ERROR','Chưa tải được đầy đủ dữ liệu.',0);
    const page=await load(cursor);
    for(const item of page.items){const id=canonicalResourceId(item.id);if(ids.has(id))mismatch();ids.add(id);result.push(item);}
    if(page.next_cursor&&(!page.items.length||cursors.has(page.next_cursor)||cursors.size>=99))mismatch();
    cursor=page.next_cursor??undefined;if(cursor)cursors.add(cursor);
  }while(cursor);
  return result;
}
export function coreClassSummary(row:CoreClass,user:User,verified=false):ClassSummary{
  const teacher=user.roles.includes('LECTURER')&&!user.roles.includes('ADMIN')&&!user.roles.includes('STUDENT');
  return {id:row.id,code:'',name:row.name,status:row.status,metadata:`Khối ${row.grade_level} · ${row.enrollment_mode==='AUTO'?'Ghi danh tự động':'Ghi danh thủ công'}`,
    ...(verified&&teacher?{isAssignedTeacher:true}:{}),...(verified&&user.roles.length===1&&user.roles[0]==='STUDENT'?{membershipStatus:'ACTIVE' as const}:{})};
}
export function corePost(row:CorePost):FeedPost{return {id:row.id,classId:row.class_id,authorId:row.author.id,authorName:row.author.display_name??`Thành viên ${row.author.id.slice(0,8)}`,content:row.body,createdAt:row.created_at,updatedAt:row.updated_at,comments:[]};}
export function coreComment(row:CoreComment):FeedComment{return {id:row.id,postId:row.post_id,authorId:row.author.id,authorName:row.author.display_name??`Thành viên ${row.author.id.slice(0,8)}`,content:row.body,createdAt:row.created_at,updatedAt:row.updated_at};}
export function coreEvent(row:CoreEvent,className?:string):CalendarEvent{
  const start=new Date(row.starts_at),end=new Date(row.ends_at);
  const day=(d:Date)=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const time=(d:Date)=>`${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  return {id:row.id,classId:row.class_id,...(className?{className}:{}),title:row.title,description:row.description??undefined,
    category:row.origin==='CORE'?'CLASS':'OTHER',start:row.starts_at,end:row.ends_at,date:day(start),timeRange:`${time(start)} – ${time(end)}`,readOnly:row.origin==='LEARNING'};
}
export function createLiveClassroomSocial(session:Session,api:CoreApiPort){
  const social:DataAdapter['social']={
    async createPost(classId,content){return corePost(await api.request('createPost',{classId,body:{body:content}}));},
    async updatePost(classId,postId,content){return corePost(await api.request('updatePost',{classId,postId,body:{body:content}}));},
    async deletePost(classId,postId){await api.request('deletePost',{classId,postId});},
    async createComment(classId,postId,content){return coreComment(await api.request('createComment',{classId,postId,body:{body:content}}));},
    async updateComment(classId,postId,commentId,content){return coreComment(await api.request('updateComment',{classId,postId,commentId,body:{body:content}}));},
    async deleteComment(classId,postId,commentId){await api.request('deleteComment',{classId,postId,commentId});},
  };
  const calendar:DataAdapter['calendar']={
    async createEvent(event){
      if(!event.classId||!event.end)throw new ApiError('VALIDATION_ERROR','Cần lớp và đầy đủ giờ bắt đầu/kết thúc.',422);
      return coreEvent(await api.request('createEvent',{classId:event.classId,body:{title:event.title,description:event.description,starts_at:event.start,ends_at:event.end}}));
    },
    async updateEvent(classId,eventId,patch){
      if(patch.location!==undefined)throw new ApiError('VALIDATION_ERROR','API lịch hiện chưa hỗ trợ địa điểm.',422);
      return coreEvent(await api.request('updateEvent',{classId,eventId,body:{...(patch.title===undefined?{}:{title:patch.title}),...(patch.description===undefined?{}:{description:patch.description||null}),...(patch.start===undefined?{}:{starts_at:patch.start}),...(patch.end===undefined?{}:{ends_at:patch.end})}}));
    },
    async deleteEvent(classId,eventId){await api.request('deleteEvent',{classId,eventId});},
  };
  const supported=new Set(['s.home','t.home','s.classes','t.classes','s.overview','t.overview','s.feed','t.feed','s.calendar','t.calendar','account.calendar']);
  async function load(routeId:string,params:RouteParams,signal?:AbortSignal):Promise<WorkspaceData>{
    const deadline=AbortSignal.timeout(15000),bounded=signal?AbortSignal.any([signal,deadline]):deadline;
    const actor=session.getActorId();
    const check=()=>{if(!actor||session.getActorId()!==actor)throw new ApiError('SESSION_CHANGED','Phiên đăng nhập đã thay đổi.',401);if(bounded.aborted)throw new ApiError('CONNECTION_ERROR','Đã dừng tải dữ liệu.',0);};
    check();
    const user=await session.authenticated(async request=>decodeUser(await request('me',{signal:bounded})));check();if(user.id!==actor)mismatch();
    if(['s.home','t.home','s.classes','t.classes'].includes(routeId)){
      const rows=await allCorePages(cursor=>{check();return api.request('classes',{cursor,limit:100,signal:bounded});},bounded);check();
      return {kind:'ready',coreClassroom:true,classes:rows.map(row=>coreClassSummary(row,user))};
    }
    if(routeId==='account.calendar'){
      if(user.roles.includes('ADMIN'))return {kind:'unavailable',message:'Lịch tổng hợp cần phạm vi giảng dạy hoặc ghi danh hiện hành; quyền quản trị metadata không cấp quyền đọc lịch các lớp.'};
      const rows=await allCorePages(cursor=>{check();return api.request('classes',{cursor,limit:100,signal:bounded});},bounded);
      const events:CalendarEvent[]=[],classes:ClassSummary[]=[];
      for(const row of rows){check();const detail=await api.request('classDetail',{classId:row.id,signal:bounded});classes.push(coreClassSummary(detail,user,true));
        const values=await allCorePages(cursor=>{check();return api.request('calendar',{classId:row.id,cursor,limit:100,signal:bounded});},bounded);events.push(...values.map(event=>coreEvent(event,row.name)));}
      check();return {kind:'ready',classes,calendarEvents:events};
    }
    const classId=canonicalResourceId(params.classId);check();
    const detail=await api.request('classDetail',{classId,signal:bounded});check();
    const summary=coreClassSummary(detail,user,true);
    if(routeId==='s.overview'||routeId==='t.overview')return {kind:'ready',coreClassroom:true,classSummary:summary};
    if(routeId.endsWith('.calendar')){
      const rows=await allCorePages(cursor=>{check();return api.request('calendar',{classId,cursor,limit:100,signal:bounded});},bounded);check();
      return {kind:'ready',classSummary:summary,classes:[summary],calendarEvents:rows.map(row=>coreEvent(row,detail.name))};
    }
    const rows=await allCorePages(cursor=>{check();return api.request('posts',{classId,cursor,limit:100,signal:bounded});},bounded);
    const posts:FeedPost[]=[];let missingPost=false;
    for(let index=0;index<rows.length;index+=4){
      const group=await Promise.all(rows.slice(index,index+4).map(async row=>{
        try{
          const comments=await allCorePages(cursor=>{check();return api.request('comments',{classId,postId:row.id,cursor,limit:100,signal:bounded});},bounded);
          return {...corePost(row),comments:comments.map(coreComment)};
        }catch(error){
          // A post can be deleted between the post page and its comment page.
          // Other failures still reject the complete snapshot; never publish partial comments.
          if(error instanceof ApiError&&error.status===404){missingPost=true;return null;}
          throw error;
        }
      }));posts.push(...group.filter((post):post is FeedPost=>post!==null));
    }
    // A 404 can also mean current class access was revoked during fan-out.
    // Verify the content scope again before treating it as a deleted post.
    if(missingPost)await api.request('posts',{classId,limit:1,signal:bounded});
    check();return {kind:'ready',classSummary:summary,feedPosts:posts};
  }
  return {social,calendar,load,supports:(routeId:string)=>supported.has(routeId)};
}
