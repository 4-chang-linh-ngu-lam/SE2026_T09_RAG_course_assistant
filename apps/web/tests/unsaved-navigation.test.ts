import test from 'node:test';
import assert from 'node:assert/strict';
import {createUnsavedCoordinator,guardsAnchor,leavesDraftScope} from '../src/lib/unsaved-navigation';
const current='https://lumi.example/teacher/library?tab=all';
const click={button:0,defaultPrevented:false,ctrlKey:false,metaKey:false,shiftKey:false,altKey:false};
const anchor={href:'/account',target:'',download:false,external:false};
test('LF-106 one confirmation protects multiple dirty editors and respects Cancel/Confirm',()=>{
 const guard=createUnsavedCoordinator();let dirty=true,calls=0;
 const remove1=guard.register({dirty:()=>dirty}),remove2=guard.register({dirty:()=>true});
 assert.equal(guard.confirm(current,'/account',()=>{calls++;return false;}),false);assert.equal(calls,1);
 assert.equal(guard.confirm(current,'/account',()=>{calls++;return true;}),true);assert.equal(calls,2);
 remove2();dirty=false;assert.equal(guard.hasDirty(),false);assert.equal(guard.confirm(current,'/account',()=>{throw Error('Must not prompt');}),true);
 remove1();assert.equal(guard.size,0);
});
test('LF-106 links ignore modifier/middle-click, downloads, external, non-http, same URL and hashes',()=>{
 assert.equal(guardsAnchor(click,anchor,current),true);
 for(const change of [{button:1},{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{defaultPrevented:true}])assert.equal(guardsAnchor({...click,...change},anchor,current),false);
 for(const change of [{target:'_blank'},{download:true},{external:true},{href:'mailto:help@lumi.example'},{href:'blob:https://lumi.example/test'},{href:'https://other.example'},{href:current+'#main'},{href:current}])assert.equal(guardsAnchor(click,{...anchor,...change},current),false);
});
test('LF-106 only declared persisted intra-feature query changes bypass exit protection',()=>{
 const from='https://lumi.example/student/classes/c/documents/d?page=1&version=2';
 assert.equal(leavesDraftScope(from,'?page=2&version=2',['page','version']),false);
 assert.equal(leavesDraftScope(from,'?page=2&version=2'),true);
 assert.equal(leavesDraftScope(from,'?page=2&version=3',['page','version']),false);
 assert.equal(leavesDraftScope(from,'?page=2&version=2&classId=other',['page','version']),true);
 assert.equal(leavesDraftScope(from,'/student/classes/other/documents/d?page=2',['page','version']),true);
 const guard=createUnsavedCoordinator();guard.register({dirty:()=>true,queryKeys:()=>['page','version']});
 assert.equal(guard.confirm(from,'?page=2&version=2',()=>{throw Error('Intra-document draft must remain usable');}),true);
 assert.equal(guard.confirm(from,'/account',()=>false),false);
});
