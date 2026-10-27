import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyLifecycleObservation, type PendingLifecycleMutation } from '../src/features/classroom-admin/lifecycle-reconciliation';
import type { ManagedClass } from '../src/lib/classroom-admin';
import { resolveVolatileDraftSnapshot } from '../src/components/volatile-draft';
import { draftStore } from '../src/lib/draft-store';

const pending:PendingLifecycleMutation={classId:'class-1',revision:7,previousStatus:'ACTIVE',targetStatus:'ARCHIVED'};
function observed(revision:number,status:ManagedClass['summary']['status'],id='class-1'):ManagedClass{return{summary:{id,code:'C1',name:'Class 1',status,metadata:''},revision,courseId:'course',yearId:'year',semesterId:'semester',grade:10,homeroomId:null,mode:'MANUAL',primaryTeacherId:'teacher',assistingTeacherIds:[],members:[],manualIncludes:[],manualExcludes:[]};}

test('lifecycle reconciliation confirms only the requested status at a newer revision',()=>{
 assert.equal(classifyLifecycleObservation(pending,observed(8,'ARCHIVED')),'APPLIED');
});

test('unchanged, conflicting, older, and mismatched observations keep the mutation outcome unknown',()=>{
 assert.equal(classifyLifecycleObservation(pending,observed(7,'ACTIVE')),'UNKNOWN');
 assert.equal(classifyLifecycleObservation(pending,observed(8,'ACTIVE')),'UNKNOWN');
 assert.equal(classifyLifecycleObservation(pending,observed(8,'ARCHIVED','other-class')),'UNKNOWN');
 assert.equal(classifyLifecycleObservation(pending,observed(6,'ARCHIVED')),'UNKNOWN');
});


test('unknown lifecycle mutation remains scoped in session memory when the view remounts',()=>{
 draftStore.clearAll();
 const key='test-actor:classroom-lifecycle:class-1:pending';
 draftStore.set(key,pending);
 const remounted=resolveVolatileDraftSnapshot({key:'other-scope',value:null,baseline:null},key,null);
 assert.deepEqual(remounted.value,pending);
 draftStore.clearAll();
});
