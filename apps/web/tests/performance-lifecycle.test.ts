import {test} from 'node:test';
import assert from 'node:assert/strict';
import {canonicalParams,featureOwnsRead,resourceParamsKey} from '../src/lib/route-load-plan';
import {SaveController} from '../src/features/learning/lib/save-controller';
import {adapter} from '../dev/mocks/adapter';
import type {PracticeAnswer} from '../src/lib/domain';
import {ApiError} from '../src/lib/api/errors';
const answer=(value:string):Record<string,PracticeAnswer>=>({q:{questionId:'q',shortAnswerValue:value}});
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));

test('route read identity ignores position but respects resource/version/conversation',()=>{
 assert.equal(canonicalParams({b:'2',a:'1'}),canonicalParams({a:'1',b:'2'}));
 assert.equal(resourceParamsKey('s.practiceAttempt',{classId:'c',practiceId:'p',attemptId:'a',question:'1'}),resourceParamsKey('s.practiceAttempt',{attemptId:'a',classId:'c',practiceId:'p',question:'2'}));
 assert.equal(resourceParamsKey('s.reader',{classId:'c',documentId:'d',version:'1',page:'1'}),resourceParamsKey('s.reader',{classId:'c',documentId:'d',version:'1',page:'2'}));
 assert.notEqual(resourceParamsKey('s.reader',{classId:'c',documentId:'d',version:'1'}),resourceParamsKey('s.reader',{classId:'c',documentId:'d',version:'2'}));
 assert.notEqual(resourceParamsKey('s.tutor',{classId:'c',conversationId:'1'}),resourceParamsKey('s.tutor',{classId:'c',conversationId:'2'}));
 assert.notEqual(resourceParamsKey('s.assignments',{classId:'c'}),resourceParamsKey('s.assignments',{classId:'d'}));
 assert.ok(featureOwnsRead('s.progress'));assert.ok(featureOwnsRead('a.importNew'));assert.ok(featureOwnsRead('t.practiceEditor'));assert.ok(!featureOwnsRead('s.reader'));
});

test('Practice restores pending snapshot before explicit check/finish barrier',async()=>{
 const writes:Record<string,PracticeAnswer>[]=[];
 const c=new SaveController({saveFn:async a=>{writes.push(a);return {savedAt:'now'};}});
 c.unblockAndReconcile(answer('old'));
 await c.flushAnswers(answer('restored local'));
 assert.deepEqual(writes,[answer('restored local')]);assert.deepEqual(c.getLastSavedAnswers(),answer('restored local'));
 await c.flushAnswers(answer('restored local'));assert.equal(writes.length,1);c.dispose();
});

test('Practice acknowledges intermediate confirmed answers even if the next write is unknown',async()=>{
 let resolve!:(value:{savedAt:string})=>void;let count=0;const ack:Record<string,PracticeAnswer>[]=[];
 const c=new SaveController({saveFn:()=>++count===1?new Promise(r=>{resolve=r;}):Promise.reject(new ApiError('NETWORK','unknown',0,'unknown')),onAcknowledged:a=>ack.push(a)});
 c.queueSave(answer('A'));c.queueSave(answer('B'));const done=assert.rejects(c.flush());resolve({savedAt:'A saved'});await done;
 assert.deepEqual(ack,[answer('A')]);assert.deepEqual(c.getLastSavedAnswers(),answer('A'));assert.ok(c.isBlocked());assert.equal(count,2);
 c.queueSave(answer('C'));await tick();assert.equal(count,2);c.dispose();
});

test('Practice short-answer delay coalesces, flush forces ACK and dispose cancels queued work',async()=>{
 const writes:Record<string,PracticeAnswer>[]=[];const c=new SaveController({saveFn:async a=>{writes.push(a);return {savedAt:'now'};}});
 c.queueSave(answer('a'),1000);c.queueSave(answer('abc'),1000);assert.equal(writes.length,0);
 await c.flush();assert.deepEqual(writes,[answer('abc')]);
 c.queueSave(answer('never sent'),20);c.dispose();await new Promise(r=>setTimeout(r,35));assert.equal(writes.length,1);
});

test('Practice unknown outcome requires explicit reconcile and action, never timer replay',async()=>{
 let count=0;const c=new SaveController({saveFn:async()=>{if(++count===1)throw new ApiError('NETWORK','unknown',0,'unknown');return {savedAt:'now'};}});
 await assert.rejects(c.flushAnswers(answer('A')));c.queueSave(answer('B'),10);await new Promise(r=>setTimeout(r,20));assert.equal(count,1);
 c.unblockAndReconcile(answer('A'));await tick();assert.equal(count,1);await c.flushAnswers(answer('B'));assert.equal(count,2);c.dispose();
});
test('Practice confirmed reconciliation clears the stale queued snapshot before flush',async()=>{
 let writes=0;const c=new SaveController({saveFn:async()=>{writes++;return {savedAt:'now'};}});
 c.block(new ApiError('NETWORK','unknown',0,'unknown'));c.queueSave(answer('confirmed'));
 c.unblockAndReconcile(answer('confirmed'));await c.flushAnswers(answer('confirmed'));
 assert.equal(writes,0);assert.deepEqual(c.getLastSavedAnswers(),answer('confirmed'));c.dispose();
});

const classId='00000000-0000-4000-8000-000000000101';
test('domain-owned reads carry current authorized class header without workspace round trip',async()=>{
 await adapter.identity.login({email:'minh.tran@lumi.example',password:'preview'});
 const assessment=await adapter.assessment.load('t.assessmentEditor',{classId,assessmentId:'exam-open-preview'});
 if(assessment.kind==='ready')assert.equal(assessment.classSummary?.teachingRole,'ASSISTING');else assert.fail('assessment unavailable');
 const analytics=await adapter.intelligence.load('t.analytics',{classId});if(analytics.kind==='class')assert.equal(analytics.classSummary.teachingRole,'ASSISTING');else assert.fail('analytics unavailable');
 await adapter.identity.login({username:'minh.anh10a1',password:'preview'});
 const assignments=await adapter.assignment.load('s.assignments',{classId});if(assignments.kind==='list')assert.equal(assignments.classSummary.membershipStatus,'ACTIVE');else assert.fail('assignment unavailable');
 await assert.rejects(adapter.intelligence.load('t.analytics',{classId}));
});

test('aborted domain reads fail closed rather than publishing an obsolete snapshot',async()=>{
 const controller=new AbortController();controller.abort();
 await assert.rejects(adapter.assessment.load('s.assessments',{classId},controller.signal),{name:'AbortError'});
 await assert.rejects(adapter.assignment.load('s.assignments',{classId},controller.signal),{name:'AbortError'});
 await assert.rejects(adapter.intelligence.load('s.progress',{classId},{},controller.signal),{name:'AbortError'});
 await assert.rejects(adapter.practiceAuthoring.load({classId,practiceId:'unused'},controller.signal),{name:'AbortError'});
});
