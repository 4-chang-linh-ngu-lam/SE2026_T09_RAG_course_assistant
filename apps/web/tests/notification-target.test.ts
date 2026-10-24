import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeNotificationPage} from '../src/lib/api/notification-decoders';
import {notificationTarget} from '../src/lib/notification-target';
import {withSafeRouteQuery} from '../src/lib/navigation';

const klass='abcdefab-cdef-4abc-8def-abcdefabcdef',post='abcdefab-cdef-4abc-8def-abcdefabcdea',comment='abcdefab-cdef-4abc-8def-abcdefabcdeb';
function decode(type='SOCIAL_COMMENT_CREATED',payload:object={class_id:klass,post_id:post,comment_id:comment}){
  return decodeNotificationPage({items:[{id:comment,type,payload_json:payload,read:false,created_at:'2026-10-23T00:00:00Z'}],unread_count:1,next_cursor:null},klass).items[0];
}
test('social notifications use approved routes and UUIDs, retaining post/comment location across login',()=>{
  const item=decode();const target=notificationTarget(item,['STUDENT']);
  assert.equal(target.targetHref,`/student/classes/${klass}/feed?postId=${post}&commentId=${comment}`);
  assert.equal(notificationTarget(item,['LECTURER']).targetHref,`/teacher/classes/${klass}/feed?postId=${post}&commentId=${comment}`);
  assert.equal(notificationTarget(item,['ADMIN']).targetHref,undefined);
  assert.equal(withSafeRouteQuery('/student/classes/'+klass+'/feed',{postId:post,commentId:comment,token:'secret'}),target.targetHref);
});
test('untrusted URLs and malformed/unknown payload identities never become a navigation target',()=>{
  for(const payload of [{class_id:'https://bad.example',post_id:post},{class_id:klass,post_id:'../../admin'},{class_id:klass,targetHref:'https://bad.example'}]){
    const item=decode('SOCIAL_POST_CREATED',payload);assert.equal(notificationTarget(item,['STUDENT']).targetHref,undefined);
  }
  assert.equal(notificationTarget(decode('UNKNOWN'),['STUDENT']).targetHref,undefined);
});
test('transfer opens destination class; Admin metadata permissions never grant social/calendar content',()=>{
  const item=decode('CLASS_STUDENT_TRANSFERRED',{class_id:post,destination_class_id:klass});
  assert.equal(notificationTarget(item,['STUDENT']).targetHref,`/student/classes/${klass}/overview`);
  assert.equal(notificationTarget(item,['ADMIN']).targetHref?.includes(klass),true);
  assert.equal(notificationTarget(decode('CALENDAR_DEADLINE_CHANGED',{class_id:klass}),['ADMIN']).targetHref,undefined);
});
