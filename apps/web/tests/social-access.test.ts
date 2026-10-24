import test from 'node:test';
import assert from 'node:assert/strict';
import {socialAccess,classroomTabsAllowed} from '../src/lib/social-access';
import type {ClassSummary,User} from '../src/lib/domain';
const summary:ClassSummary={id:'class',code:'subject',name:'Class',metadata:'',status:'ACTIVE',membershipStatus:'ACTIVE'};
const student:Pick<User,'roles'|'status'>={roles:['STUDENT'],status:'ACTIVE'};
test('social guards reject missing, mismatched, archived, ended and locked access',()=>{
  assert.deepEqual(socialAccess(student,summary,'class'),{participate:true,moderate:false});
  for(const value of [undefined,{...summary,id:'other'},{...summary,status:'ARCHIVED' as const},{...summary,membershipStatus:'ENDED' as const}])assert.deepEqual(socialAccess(student,value,'class'),{participate:false,moderate:false});
  assert.equal(socialAccess({...student,status:'LOCKED'},summary,'class').participate,false);
});
test('teacher/admin system roles cannot substitute for current class assignment',()=>{
  const teacher:Pick<User,'roles'|'status'>={roles:['LECTURER'],status:'ACTIVE'};
  assert.deepEqual(socialAccess(teacher,summary,'class'),{participate:false,moderate:false});
  assert.equal(socialAccess({roles:['ADMIN'],status:'ACTIVE'},summary,'class').participate,false);
  for(const teachingRole of ['PRIMARY','ASSISTING'] as const)assert.deepEqual(socialAccess(teacher,{...summary,teachingRole},'class'),{participate:true,moderate:true});
});
test('live class tabs accept a verified assignment without guessing its PRIMARY/ASSISTING label',()=>{
  const verified={...summary,teachingRole:undefined,isAssignedTeacher:true};
  assert.equal(classroomTabsAllowed('LECTURER',verified),true);
  assert.equal(classroomTabsAllowed('LECTURER',{...verified,isAssignedTeacher:false}),false);
  assert.equal(classroomTabsAllowed('LECTURER',{...verified,status:'ARCHIVED'}),false);
  assert.equal(classroomTabsAllowed('ADMIN',verified),false);
  assert.equal(classroomTabsAllowed('STUDENT',{...verified,membershipStatus:'ENDED'}),false);
});
