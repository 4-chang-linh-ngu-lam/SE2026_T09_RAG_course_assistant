import {routeHref} from '../config/routes';
import {resourceUuid} from './api/operations';
import type {NotificationItem,Role} from './domain';

/** Routes are built from our route table and validated IDs. Backend still checks current resource access. */
export function notificationTarget(item:Readonly<NotificationItem>,roles:readonly Role[]):NotificationItem{
  const {targetHref:_href,targetLabel:_label,...safe}=item;
  if(!item.classId||!resourceUuid.test(item.classId)||!item.targetKind)return safe;
  const role=roles.includes('LECTURER')?'t':roles.includes('STUDENT')?'s':null;
  if(item.targetKind==='document'){
    if(!role||!item.documentId||!resourceUuid.test(item.documentId))return safe;
    const href=routeHref(role==='t'?'t.documents':'s.reader',{classId:item.classId,documentId:item.documentId});
    return href?{...safe,targetHref:href,targetLabel:'Mở tài liệu của lớp'}:safe;
  }
  if(item.targetKind==='post'){
    if(!role||!item.postId||!resourceUuid.test(item.postId))return safe;
    const query=new URLSearchParams({postId:item.postId});
    if(item.commentId&&resourceUuid.test(item.commentId))query.set('commentId',item.commentId);
    const href=routeHref(role==='t'?'t.feed':'s.feed',{classId:item.classId});
    return href?{...safe,targetHref:href+'?'+query,targetLabel:'Mở bài viết trong lớp'}:safe;
  }
  if(role)return {...safe,targetHref:routeHref(item.targetKind==='calendar'?(role==='t'?'t.calendar':'s.calendar'):(role==='t'?'t.overview':'s.overview'),{classId:item.classId})??undefined,targetLabel:item.targetKind==='calendar'?'Mở lịch lớp':'Mở lớp học'};
  if(roles.includes('ADMIN')&&item.targetKind==='class')return {...safe,targetHref:routeHref('a.classSettings',{classId:item.classId})??undefined,targetLabel:'Mở quản lý lớp'};
  return safe;
}
