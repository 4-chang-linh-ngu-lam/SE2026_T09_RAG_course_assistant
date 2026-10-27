import test from 'node:test';
import assert from 'node:assert/strict';
import {AssessmentAnswerSaver} from '../src/features/assessment/answer-save';
import type {AssessmentAnswers,AssessmentAttempt} from '../src/lib/assessment';
const answer=(value:string):AssessmentAnswers=>({q1:{questionId:'q1',value}});
const deferred=<T,>()=>{let resolve!:(v:T)=>void;let reject!:(e:unknown)=>void;const promise=new Promise<T>((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const ack=(value:string,revision:number)=>({savedRevision:revision,savedAnswers:answer(value)} as AssessmentAttempt);

test('PERF-010 submit flush coalesces the identical active snapshot and its ACK',async()=>{
 const gate=deferred<AssessmentAttempt>();let writes=0;
 const saver=new AssessmentAnswerSaver(0,async()=>{writes++;return gate.promise;},()=>{},{});
 saver.enqueue(answer('A'));saver.enqueue(answer('A'));const flushed=saver.flush();
 assert.equal(writes,1);gate.resolve(ack('A',1));await flushed;
 saver.enqueue(answer('A'));await saver.flush();assert.equal(writes,1);assert.equal(saver.currentRevision,1);
});
test('PERF-010 latest A to B to A while A is active discards obsolete queued B',async()=>{
 const gate=deferred<AssessmentAttempt>();let writes=0;
 const saver=new AssessmentAnswerSaver(0,async()=>{writes++;return gate.promise;},()=>{});
 saver.enqueue(answer('A'));saver.enqueue(answer('B'));saver.enqueue(answer('A'));gate.resolve(ack('A',1));await saver.flush();
 assert.equal(writes,1);
});
test('PERF-009 reconcile dirty read unlocks explicit save without automatically replaying unknown',async()=>{
 const failure=new Error('Unknown');let writes=0;let errors=0;
 const saver=new AssessmentAnswerSaver(0,async a=>{writes++;if(writes===1)throw failure;return {savedRevision:1,savedAnswers:a} as AssessmentAttempt;},()=>{}, {},()=>{errors++;});
 saver.enqueue(answer('A'));await assert.rejects(saver.flush());assert.equal(errors,1);
 saver.pause();await saver.waitForIdle();saver.reconcile(0,{});
 assert.equal(saver.isSaving,false);assert.equal(saver.hasPending,true);assert.equal(writes,1);
 saver.enqueue(answer('A'));await saver.flush();assert.equal(writes,2);
});
test('PERF-013 short answer autosave coalesces bursts and flush sends the final snapshot immediately',async()=>{
 const saved:AssessmentAnswers[]=[];
 const saver=new AssessmentAnswerSaver(0,async a=>{saved.push(a);return {savedRevision:saved.length,savedAnswers:a} as AssessmentAttempt;},()=>{},{});
 saver.enqueue(answer('h'),200);saver.enqueue(answer('hello'),200);assert.equal(saved.length,0);
 await saver.flush();assert.deepEqual(saved,[answer('hello')]);assert.equal(saver.isSaving,false);saver.dispose();
});
test('PERF-009 reconcile cannot replace revision while a write is active',async()=>{
 const gate=deferred<AssessmentAttempt>();const saver=new AssessmentAnswerSaver(0,()=>gate.promise,()=>{});
 saver.enqueue(answer('A'));assert.throws(()=>saver.reconcile(5,answer('A')));
 const idle=saver.waitForIdle();gate.resolve(ack('A',1));await idle;saver.reconcile(1,answer('A'));assert.equal(saver.isSaving,false);
});
test('PERF-013 dispose cancels scheduled writes and never fabricates their ACK',async()=>{
 let writes=0;const saver=new AssessmentAnswerSaver(0,async()=>{writes++;return ack('A',1);},()=>assert.fail('Disposed ACK'));
 saver.enqueue(answer('A'),10);saver.dispose();await new Promise(r=>setTimeout(r,20));assert.equal(writes,0);await assert.rejects(saver.flush());
});


test('canonical answer equality dedupes map/order changes and statement/option order',async()=>{
 const {sameAssessmentAnswers}=await import('../src/features/assessment/answer-equality');
 const a={z:{questionId:'z',value:{b:false,a:true}},a:{questionId:'a',value:['B','A']}};
 const b={a:{questionId:'a',value:['A','B']},z:{questionId:'z',value:{a:true,b:false}}};
 assert.ok(sameAssessmentAnswers(a,b));assert.ok(!sameAssessmentAnswers(a,{...b,a:{questionId:'a',value:['A']}}));
 let writes=0;const writer=new AssessmentAnswerSaver(0,async()=>{writes++;return {...ack('A',1),savedAnswers:b};},()=>{},a);
 writer.enqueue(b);await writer.flush();assert.equal(writes,0);writer.dispose();
});

test('monotonic assessment clock can be reanchored by authority and ignores wall clock rollback',async()=>{
 const {createAssessmentClock,assessmentClockRemaining}=await import('../src/features/assessment/countdown');
 const endsAt='2026-10-21T01:00:10Z',clock=createAssessmentClock('2026-10-21T01:00:00Z',100);
 assert.equal(assessmentClockRemaining(endsAt,clock,1100),9000);
 const original=Date.now;Date.now=()=>0;
 try{assert.equal(assessmentClockRemaining(endsAt,clock,10100),0);}finally{Date.now=original;}
 assert.equal(assessmentClockRemaining(endsAt,createAssessmentClock('2026-10-21T01:00:01Z',12000),12000),9000);
});
