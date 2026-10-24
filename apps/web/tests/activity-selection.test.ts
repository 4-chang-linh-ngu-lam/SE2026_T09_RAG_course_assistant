import test from 'node:test';
import assert from 'node:assert/strict';
import {activitySelection,activityIncluded,toggleActivity} from '../src/lib/activity-selection';
test('LF-105 one, multiple, deselect last and explicit reset never conflate none with all',()=>{
 let selection=activitySelection();assert.equal(selection.resourceSelectionMode,'ALL');assert.ok(activityIncluded('a',selection.resourceIds,selection.resourceSelectionMode));
 selection=activitySelection(toggleActivity([], 'a'),'EXPLICIT');assert.deepEqual(selection.resourceIds,['a']);
 selection=activitySelection(toggleActivity(selection.resourceIds,'b'),'EXPLICIT');assert.deepEqual(selection.resourceIds,['a','b']);
 selection=activitySelection(toggleActivity(selection.resourceIds,'a'),'EXPLICIT');assert.deepEqual(selection.resourceIds,['b']);
 selection=activitySelection(toggleActivity(selection.resourceIds,'b'),'EXPLICIT');assert.deepEqual(selection.resourceIds,[]);assert.equal(selection.resourceSelectionMode,'EXPLICIT');assert.equal(activityIncluded('a',selection.resourceIds,selection.resourceSelectionMode),false);
 selection=activitySelection();assert.equal(selection.resourceSelectionMode,'ALL');assert.equal(activityIncluded('a',selection.resourceIds,selection.resourceSelectionMode),true);
});
