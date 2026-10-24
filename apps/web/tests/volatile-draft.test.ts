import test from 'node:test';
import assert from 'node:assert/strict';
import { draftStore } from '../src/lib/draft-store';
import { persistVolatileDraftSnapshot, resolveVolatileDraftSnapshot } from '../src/components/volatile-draft';

test('volatile draft key changes load only that scope and never copy the old revision into it', () => {
  draftStore.clearAll();
  const oldKey='test-actor:class-lifecycle:class-1:rev-4';
  const newKey='test-actor:class-lifecycle:class-1:rev-5';
  draftStore.set(oldKey,'old revision reason');
  const oldSnapshot={key:oldKey,value:'edited old revision reason',baseline:''};
  persistVolatileDraftSnapshot(newKey,oldSnapshot,'');
  assert.equal(draftStore.get(newKey),null);
  assert.equal(draftStore.get(oldKey),'old revision reason');

  draftStore.set(newKey,'new revision draft');
  const next=resolveVolatileDraftSnapshot(oldSnapshot,newKey,'');
  assert.deepEqual(next,{key:newKey,value:'new revision draft',baseline:''});
  persistVolatileDraftSnapshot(newKey,next,'');
  assert.equal(draftStore.get(newKey),'new revision draft');
  assert.equal(draftStore.get(oldKey),'old revision reason');
  draftStore.clearAll();
});

test('volatile draft key change uses the new baseline when there is no draft for that scope', () => {
  draftStore.clearAll();
  const previous={key:'actor:class:old-revision',value:'stale reason',baseline:''};
  const next=resolveVolatileDraftSnapshot(previous,'actor:class:new-revision','');
  assert.deepEqual(next,{key:'actor:class:new-revision',value:'',baseline:''});
  persistVolatileDraftSnapshot(next.key,previous,'');
  assert.equal(draftStore.get(next.key),null);
  draftStore.clearAll();
});


test('volatile draft adopts a changed baseline only when the prior value was untouched', () => {
  draftStore.clearAll();
  const untouched={key:'actor:class:stable-key',value:'Server version 1',baseline:'Server version 1'};
  draftStore.set(untouched.key,'Server version 1');
  const nextBaseline=resolveVolatileDraftSnapshot(untouched,untouched.key,'Server version 2');
  assert.deepEqual(nextBaseline,{key:untouched.key,value:'Server version 2',baseline:'Server version 2'});
  persistVolatileDraftSnapshot(untouched.key,untouched,'Server version 2');
  assert.equal(draftStore.get(untouched.key),'Server version 1');
  persistVolatileDraftSnapshot(nextBaseline.key,nextBaseline,'Server version 2');
  assert.equal(draftStore.get(nextBaseline.key),null);
  const edited={key:'actor:class:stable-key',value:'My draft',baseline:'Server version 1'};
  const editedNext=resolveVolatileDraftSnapshot(edited,edited.key,'Server version 2');
  assert.deepEqual(editedNext,{key:edited.key,value:'My draft',baseline:'Server version 2'});
  persistVolatileDraftSnapshot(editedNext.key,editedNext,'Server version 2');
  assert.equal(draftStore.get(editedNext.key),'My draft');
  draftStore.clearAll();
});
