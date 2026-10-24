import test from 'node:test';
import assert from 'node:assert/strict';
import {createDataRequestController} from '../src/lib/data-request-controller';
import {draftStore} from '../src/lib/draft-store';
import {ApiError} from '../src/lib/api/errors';
import type {DataRequest,Page} from '../src/lib/domain';

function deferred<T>(){let resolve!:(value:T)=>void,reject!:(error:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
function row(id='r1',user_id='actor-a'):DataRequest{return{id,user_id,type:'ACCESS',reason:'Nội dung',status:'PENDING',resolution_note:null,created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'};}
function harness(){
 draftStore.bindActor(null);draftStore.bindActor('actor-a');
 const gate=deferred<DataRequest>(),calls:string[]=[];
 const deps={actorId:'actor-a',listRequests:async(_cursor?:string):Promise<Page<DataRequest>>=>({items:[],next_cursor:null}),createRequest:async()=>{calls.push('POST');return gate.promise;}};
 const c=createDataRequestController(deps);return{c,gate,calls,deps};
}
test('data request: exact ACK confirms once, clears intent input, and deduplicates pages',async()=>{
 const h=harness();h.c.setDraftReason('  Nội dung  ');const pending=h.c.submit();assert.equal(h.c.getState().mutation,'submitting');assert.equal(await h.c.submit(),'ignored');assert.deepEqual(h.calls,['POST']);h.gate.resolve(row());assert.equal(await pending,'confirmed');assert.equal(h.c.getState().draft.reason,'');assert.equal(h.c.getState().lastConfirmedRequest?.id,'r1');
 h.deps.listRequests=async()=>({items:[row(),row('r2'),row('foreign','actor-b')],next_cursor:null});await h.c.refreshList();assert.deepEqual(h.c.getState().items.map(r=>r.id),['r1','r2']);h.c.dispose();
});
test('data request: known rejection retains editable intent and actual correlation only',async()=>{
 const h=harness();h.c.setDraftReason('Nội dung');const p=h.c.submit();h.gate.reject(new ApiError('DENIED','Nhà trường từ chối.',403,'rejected',' server-123 '));assert.equal(await p,'rejected');assert.equal(h.c.getState().mutationIssue?.correlationId,'server-123');assert.equal(h.c.getState().draft.reason,'Nội dung');h.c.setDraftReason('Chỉnh lại');assert.equal(h.c.getState().mutation,'idle');assert.equal(h.c.getState().draft.reason,'Chỉnh lại');h.c.dispose();
});
test('data request: unknown freezes intent; matching or empty GET does not prove POST outcome',async()=>{
 const h=harness();h.c.setDraftReason('Nội dung');const p=h.c.submit();h.gate.reject(new ApiError('NETWORK','Mất kết nối.',0,'unknown'));assert.equal(await p,'unknown');h.c.setDraftType('DELETE');h.c.setDraftReason('Khác');assert.equal(h.c.getState().draft.type,'ACCESS');assert.equal(h.c.getState().draft.reason,'Nội dung');assert.equal(await h.c.submit(),'ignored');
 h.deps.listRequests=async()=>({items:[row()],next_cursor:null});await h.c.refreshList();assert.equal(h.c.getState().mutation,'unknown');assert.equal(h.c.getState().mutationIssue?.correlationId,undefined);h.deps.listRequests=async()=>({items:[],next_cursor:null});await h.c.refreshList();assert.equal(h.c.getState().mutation,'unknown');assert.deepEqual(h.calls,['POST']);h.c.dispose();
});
test('data request: list failure is separate, unknown survives SPA remount and refresh',async()=>{
 const h=harness();const p=h.c.submit();h.gate.reject(new ApiError('BAD_ACK','Phản hồi chưa rõ.',500,'unknown','post-id'));await p;h.c.dispose();
 const c=createDataRequestController(h.deps);assert.equal(c.getState().mutation,'unknown');h.deps.listRequests=async()=>{throw new ApiError('LIST_FAILED','Chưa tải được danh sách.',503,'rejected','get-id');};await c.refreshList();assert.equal(c.getState().mutationIssue?.correlationId,'post-id');assert.equal(c.getState().listError?.correlationId,'get-id');assert.equal(c.getState().mutation,'unknown');assert.equal(await c.submit(),'ignored');c.dispose();
});
test('data request: pending remount is uncertain; exact original late ACK can reconcile, never a list match',async()=>{
 const h=harness();h.c.setDraftReason('Nội dung');const p=h.c.submit();h.c.dispose();const c=createDataRequestController(h.deps);assert.equal(c.getState().mutation,'unknown');h.gate.resolve(row());await p;await c.refreshList();assert.equal(c.getState().mutation,'confirmed');assert.equal(c.getState().lastConfirmedRequest?.id,'r1');assert.deepEqual(h.calls,['POST']);c.dispose();
});
test('data request: actor/epoch switch discards delayed writes even after switch back',async()=>{
 const h=harness();const p=h.c.submit();draftStore.bindActor('actor-b');draftStore.bindActor('actor-a');h.gate.resolve(row());assert.equal(await p,'ignored');const c=createDataRequestController(h.deps);assert.equal(c.getState().mutation,'idle');assert.equal(c.getState().items.length,0);c.dispose();h.c.dispose();
});
test('data request: refresh invalidates stale pagination, deduplicates and stops cursor cycles',async()=>{
 const h=harness();h.deps.listRequests=async()=>({items:[row('first')],next_cursor:'cursor-1'});await h.c.refreshList();const old=deferred<Page<DataRequest>>();h.deps.listRequests=async cursor=>cursor?old.promise:{items:[row('fresh')],next_cursor:'cursor-2'};const page=h.c.loadMore();await h.c.refreshList();old.resolve({items:[row('stale')],next_cursor:'cursor-3'});await page;assert.deepEqual(h.c.getState().items.map(r=>r.id),['fresh']);
 h.deps.listRequests=async()=>({items:[row('fresh'),row('second')],next_cursor:'cursor-2'});await h.c.loadMore();assert.deepEqual(h.c.getState().items.map(r=>r.id),['fresh','second']);assert.equal(h.c.getState().nextCursor,null);assert.match(h.c.getState().listError!.message,/lặp/);h.c.dispose();
});
test('data request: wrong-actor ACK and ordinary thrown errors remain unknown, never confirmed',async()=>{
 const h=harness();const p=h.c.submit();h.gate.resolve(row('foreign','actor-b'));assert.equal(await p,'unknown');assert.equal(h.c.getState().lastConfirmedRequest,undefined);h.c.dispose();const x=harness();const other=x.c.submit();x.gate.reject(new Error('transport'));assert.equal(await other,'unknown');assert.equal(x.c.getState().mutationIssue?.correlationId,undefined);x.c.dispose();
});
test('data request: dispose suppresses list updates; oversized intent never reaches adapter',async()=>{
 const h=harness();const page=deferred<Page<DataRequest>>();h.deps.listRequests=async()=>page.promise;const load=h.c.refreshList();h.c.dispose();page.resolve({items:[row()],next_cursor:null});await load;assert.equal(h.c.getState().items.length,0);
 const x=harness();x.c.setDraftReason('x'.repeat(10001));assert.equal(await x.c.submit(),'rejected');assert.equal(x.calls.length,0);x.c.dispose();
});
