import type {createLiveCoreSession} from './live-identity';
import {coreDecoders,type CoreApiPort,type CoreOperation,type CoreOptions,type CoreResponse} from '../api/core-contract';
import {operations} from '../api/operations';
import {decodeMutation} from '../api/decoders';
import {ApiError} from '../api/errors';

const sameId=(actual:unknown,expected:string)=>typeof actual==='string'&&actual.toLowerCase()===expected.toLowerCase();

export function createLiveCoreApi(session:Pick<ReturnType<typeof createLiveCoreSession>,'authenticated'|'getActorId'>):CoreApiPort{
  return {request<K extends CoreOperation>(id:K,options:CoreOptions<K>):Promise<CoreResponse<K>>{
    if(!session.getActorId())return Promise.reject(new ApiError('SESSION_UNCONFIRMED','Cần xác nhận tài khoản trước khi tiếp tục.',401));
    const mutation=operations[id][0]!=='GET';
    return session.authenticated(async request=>{
      const value=await request(id,options);
      const decode=(value:unknown)=>{
        const result=coreDecoders[id](value);
        // Parent relationships and returned IDs are part of the receipt contract.
        const rows=Array.isArray(result)?result:result&&typeof result==='object'&&'items'in result?result.items:[result];
        for(const row of rows){
          if(row&&typeof row==='object'){
            const r=row as Record<string,unknown>;
            const expectedClass=id==='transferMember'?(options.body as {destination_class_id:string}).destination_class_id:options.classId;
            if(expectedClass&&'class_id'in r&&!sameId(r.class_id,expectedClass))throw new ApiError('CONTRACT_MISMATCH','Phản hồi không khớp lớp yêu cầu.');
            if(options.postId&&'post_id'in r&&!sameId(r.post_id,options.postId))throw new ApiError('CONTRACT_MISMATCH','Phản hồi không khớp bài đăng.');
            const student=id==='addMember'?(options.body as {student_id:string}).student_id:id==='transferMember'?options.studentId:undefined;
            if(student&&'student_id'in r&&!sameId(r.student_id,student))throw new ApiError('CONTRACT_MISMATCH','Xác nhận không khớp học sinh.');
            const homeroom=id==='transferHomeroom'?(options.body as {destination_homeroom_id:string}).destination_homeroom_id:options.homeroomId;
            if(homeroom&&'homeroom_class_id'in r&&!sameId(r.homeroom_class_id,homeroom))throw new ApiError('CONTRACT_MISMATCH','Xác nhận không khớp lớp hành chính.');
            if(options.yearId&&'academic_year_id'in r&&!sameId(r.academic_year_id,options.yearId))throw new ApiError('CONTRACT_MISMATCH','Phản hồi không khớp năm học.');
          }
        }
        const expected=id==='transferMember'?undefined:options.eventId??options.commentId??(['updatePost'].includes(id)?options.postId:undefined)??(['classDetail','syncEnrollment','setEnrollmentMode','archiveClass','restoreClass'].includes(id)?options.classId:undefined)??(['setUserRoles','adminUser'].includes(id)?options.userId:undefined)??(['adminDataRequest','resolveDataRequest'].includes(id)?options.requestId:undefined);
        if(expected&&result&&typeof result==='object'&&'id'in result&&!sameId(result.id,expected))throw new ApiError('CONTRACT_MISMATCH','Xác nhận không khớp tài nguyên.');
        if(id==='confirmImport'&&result&&typeof result==='object'&&'preview_id'in result&&!sameId(result.preview_id,(options.body as {preview_id:string}).preview_id))throw new ApiError('CONTRACT_MISMATCH','Xác nhận không khớp lần nhập.');
        return result as CoreResponse<K>;
      };
      return mutation?decodeMutation(decode,value):decode(value);
    },mutation);
  }};
}
