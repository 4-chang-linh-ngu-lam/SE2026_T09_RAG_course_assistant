import test from 'node:test';
import assert from 'node:assert/strict';
import {createReaderOperationScope, settleReaderOperation, type ReaderOperationIdentity} from '../src/features/document/reader-operation-scope';
import {stopTutorStream} from '../src/features/tutor/stop-stream';
function deferred<T>() {
  let resolve!: (value:T)=>void;
  let reject!: (reason:unknown)=>void;
  const promise = new Promise<T>((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
const identity: ReaderOperationIdentity = {actorId:'student-a',classId:'class-a',documentId:'document-a',version:2,page:3};

test('late Reader save ACK keeps the next page editor and both scoped drafts intact',async()=>{
  const scope=createReaderOperationScope();const token=scope.enter(identity);const pending=deferred<void>();
  const drafts=new Map([[3,'page 3 text'],[4,'page 4 text']]);let editor='page 3 text';let reloads=0;let settled=0;
  const operation=settleReaderOperation({scope,token,work:()=>pending.promise,confirmed:()=>{drafts.delete(3);editor='';reloads++;},failed:()=>assert.fail('unexpected error'),settled:()=>{settled++;}});
  scope.enter({...identity,page:4});editor=drafts.get(4)!;pending.resolve();
  assert.equal(await operation,'stale');assert.equal(editor,'page 4 text');assert.equal(drafts.get(3),'page 3 text');assert.equal(drafts.get(4),'page 4 text');assert.equal(reloads,0);assert.equal(settled,0);
});

test('every Reader identity field invalidates an outstanding operation, including a round trip',()=>{
  for(const changed of [{actorId:'student-b'},{classId:'class-b'},{documentId:'document-b'},{version:3},{page:4}]) {
    const scope=createReaderOperationScope();const old=scope.enter(identity);scope.enter({...identity,...changed});scope.enter(identity);
    assert.equal(scope.isCurrent(old),false,JSON.stringify(changed));
  }
});

test('Reader scope snapshots are immutable and an old cleanup cannot cancel a new page',()=>{
  const mutable={...identity};const scope=createReaderOperationScope();const old=scope.enter(mutable);mutable.page=99;
  assert.equal(old.identity.page,3);const current=scope.enter({...identity,page:4});scope.invalidate(old);assert.equal(scope.isCurrent(current),true);
  scope.invalidate(current);assert.equal(scope.isCurrent(current),false);
});

test('late Reader rejection after unmount does not set error, reload, or settle a new scope',async()=>{
  const scope=createReaderOperationScope();const token=scope.enter(identity);const pending=deferred<void>();const events:string[]=[];
  const operation=settleReaderOperation({scope,token,work:()=>pending.promise,confirmed:()=>events.push('confirmed'),failed:()=>events.push('failed'),settled:()=>events.push('settled')});
  scope.invalidate(token);scope.enter(identity);pending.reject(new Error('old request failed'));
  assert.equal(await operation,'stale');assert.deepEqual(events,[]);
});

test('owned Reader ACK and failure invoke only their confirmed or error branch',async()=>{
  const scope=createReaderOperationScope();const token=scope.enter(identity);const events:string[]=[];
  assert.equal(await settleReaderOperation({scope,token,work:async()=>42,confirmed:value=>events.push(String(value)),failed:()=>assert.fail(),settled:()=>events.push('settled')}),'confirmed');
  const failure=new Error('save unavailable');
  assert.equal(await settleReaderOperation({scope,token,work:async()=>{throw failure;},confirmed:()=>assert.fail(),failed:error=>{assert.equal(error,failure);events.push('failed');},settled:()=>events.push('settled')}),'failed');
  assert.deepEqual(events,['42','settled','failed','settled']);
});

test('Reader confirmed callback navigation suppresses a stale final update',async()=>{
  const scope=createReaderOperationScope();const token=scope.enter(identity);let settled=false;
  await settleReaderOperation({scope,token,work:async()=>undefined,confirmed:()=>{scope.enter({...identity,page:4});},failed:()=>assert.fail(),settled:()=>{settled=true;}});
  assert.equal(settled,false);
});

test('Tutor stop cancels locally immediately and reports a failed remote ACK honestly',async()=>{
  const pending=deferred<void>();const events:string[]=[];const failure=new Error('network outcome unknown');
  const operation=stopTutorStream({conversationId:'conversation-a',stopLocally:()=>events.push('local abort'),stopRemote:async id=>{events.push(id);return pending.promise;},isCurrent:()=>true});
  assert.deepEqual(events,['local abort','conversation-a']);pending.reject(failure);
  assert.deepEqual(await operation,{kind:'unconfirmed',error:failure});
});

test('Tutor late stop ACK or failure never applies to a switched conversation',async()=>{
  for(const rejected of [false,true]) {
    const pending=deferred<void>();let current=true;
    const operation=stopTutorStream({conversationId:'conversation-a',stopLocally:()=>{},stopRemote:()=>pending.promise,isCurrent:()=>current});
    current=false;if(rejected)pending.reject(new Error('old request'));else pending.resolve();
    assert.deepEqual(await operation,{kind:'stale'});
  }
});

test('Tutor stop before conversation creation has no invented remote request; confirmed stop waits for ACK',async()=>{
  let calls=0;
  assert.deepEqual(await stopTutorStream({conversationId:null,stopLocally:()=>{},stopRemote:async()=>{calls++;},isCurrent:()=>true}),{kind:'not-started'});assert.equal(calls,0);
  const pending=deferred<void>();const operation=stopTutorStream({conversationId:'actual-conversation',stopLocally:()=>{},stopRemote:()=>pending.promise,isCurrent:()=>true});
  pending.resolve();assert.deepEqual(await operation,{kind:'confirmed'});
});
