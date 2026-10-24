import test from 'node:test';
import assert from 'node:assert/strict';
import {createClassFeedController} from '../src/lib/class-feed-controller';
import {ApiError} from '../src/lib/api/errors';
import type {FeedPost,User,WorkspaceData} from '../src/lib/domain';
import type {DataAdapter} from '../src/lib/data/port';

const user:User={id:'student',roles:['STUDENT'],status:'ACTIVE',school_id:null,email:null,username:null,display_name:null};
const post=(content='original',authorId=user.id):FeedPost=>({id:'post',classId:'class',authorId,authorName:'Member',content,createdAt:'2026-10-23T00:00:00Z',comments:[]});
const data=(posts=[post()],archived=false):WorkspaceData=>({kind:'ready',classSummary:{id:'class',code:'',name:'Class',metadata:'',status:archived?'ARCHIVED':'ACTIVE',membershipStatus:'ACTIVE'},feedPosts:posts});
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(reason:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function harness(){
  let next:()=>Promise<WorkspaceData>=async()=>data(),writes=0;
  let mutation:()=>Promise<FeedPost>=async()=>post('created');
  const social:DataAdapter['social']={createPost:async()=>{writes++;return mutation();},updatePost:async()=>{writes++;return mutation();},deletePost:async()=>{writes++;},createComment:async()=>{throw new Error('unused');},updateComment:async()=>{throw new Error('unused');},deleteComment:async()=>{writes++;}};
  const controller=createClassFeedController({user,classId:'class',social,load:()=>next()});
  return {controller,writes:()=>writes,load:(run:typeof next)=>{next=run;},mutation:(run:typeof mutation)=>{mutation=run;}};
}

test('polling uses one read; a write invalidates an older GET before merging its acknowledgement',async()=>{
  const h=harness();await h.controller.refresh();
  const old=deferred<WorkspaceData>();let reads=0;h.load(()=>{reads++;return old.promise;});
  const read=h.controller.refresh();await h.controller.refresh();assert.equal(reads,1);
  const fresh=deferred<WorkspaceData>();h.mutation(async()=>{h.load(()=>fresh.promise);return post('new');});
  assert.equal(await h.controller.execute({type:'createPost',content:'new'}),true);
  old.resolve(data([post('stale')]));await read;
  assert.equal(h.controller.getState().posts[0].content,'new');
  fresh.resolve(data([post('new')]));await Promise.resolve();
});

test('unknown write is never replayed by polling and requires an explicit fresh reconciliation',async()=>{
  const h=harness();await h.controller.refresh();let reads=0;h.load(async()=>{reads++;return data();});
  h.mutation(async()=>{throw new ApiError('OFFLINE','unknown',0,'unknown');});
  assert.equal(await h.controller.execute({type:'createPost',content:'draft'}),false);
  await h.controller.refresh();assert.equal(reads,0);assert.equal(h.controller.getState().unknown,true);
  assert.equal(await h.controller.execute({type:'createPost',content:'draft'}),false);assert.equal(h.writes(),1);
  h.load(async()=>{throw new ApiError('OFFLINE','offline');});await h.controller.refresh(true);
  assert.equal(h.controller.getState().unknown,true);
  h.load(async()=>data());await h.controller.refresh(true);assert.equal(h.controller.getState().unknown,false);assert.equal(h.writes(),1);
});

test('busy prevents duplicate writes and author/archived/stale permissions fail closed',async()=>{
  const h=harness();await h.controller.refresh();const gate=deferred<FeedPost>();h.mutation(()=>gate.promise);
  const write=h.controller.execute({type:'createPost',content:'one'});
  assert.equal(await h.controller.execute({type:'createPost',content:'two'}),false);gate.resolve(post());await write;
  h.load(async()=>data([post('other','another')]));await Promise.resolve();await h.controller.refresh();
  assert.equal(await h.controller.execute({type:'deletePost',postId:'post'}),false);
  h.load(async()=>data([],true));await h.controller.refresh();assert.equal(await h.controller.execute({type:'createPost',content:'x'}),false);
  h.load(async()=>{throw new ApiError('OFFLINE','offline');});await h.controller.refresh();assert.equal(h.controller.getState().stale,true);
  assert.equal(await h.controller.execute({type:'createPost',content:'x'}),false);
});

test('revoked access discards cached class content; disposed actors ignore late loads and writes',async()=>{
  const h=harness();await h.controller.refresh();h.load(async()=>{throw new ApiError('FORBIDDEN','denied',403);});await h.controller.refresh();
  assert.deepEqual(h.controller.getState().posts,[]);assert.equal(h.controller.getState().summary,undefined);
  const other=harness();const gate=deferred<WorkspaceData>();other.load(()=>gate.promise);
  const pending=other.controller.refresh();other.controller.dispose();gate.resolve(data());await pending;
  assert.equal(other.controller.getState().loaded,false);
  assert.equal(await other.controller.execute({type:'createPost',content:'x'}),false);
});
