import test from 'node:test';
import assert from 'node:assert/strict';
import {coreAdminScope,usesCoreAdminUi} from '../src/lib/core-admin-routing';
import type {User} from '../src/lib/domain';
import {sidebars} from '../src/config/navigation';
import {getRoute} from '../src/config/routes';
const user:User={id:'00000000-0000-4000-8000-000000000001',school_id:'00000000-0000-4000-8000-000000000002',email:'synthetic@fixture.example.com',username:null,display_name:null,status:'ACTIVE',roles:['ADMIN']};
test('only the three approved live Core forms use the new UI; preview and import history remain separate',()=>{
  for(const id of ['a.staffInvite','a.importNew','a.dataRequests']){assert.equal(usesCoreAdminUi('live',id),true);assert.equal(usesCoreAdminUi('mock',id),false);}
  for(const id of ['a.import','a.account','a.accounts','a.audit','a.newStudent','s.feed'])assert.equal(usesCoreAdminUi('live',id),false);
});
test('form scope requires current ACTIVE Admin and a school, failing closed before mounting a controller',()=>{
  assert.equal(coreAdminScope(null,'a.importNew'),null);
  for(const actor of [{...user,status:'LOCKED' as const},{...user,status:'PENDING_VERIFICATION' as const},{...user,roles:['LECTURER' as const]},{...user,school_id:null}])assert.equal(coreAdminScope(actor,'a.importNew'),null);
  assert.ok(coreAdminScope(user,'a.importNew'));
});
test('form state keys change with actor, school, roles and route; equivalent role order preserves the scope',()=>{
  const initial=coreAdminScope(user,'a.importNew');
  for(const actor of [{...user,id:'00000000-0000-4000-8000-000000000003'},{...user,school_id:'00000000-0000-4000-8000-000000000004'},{...user,roles:['ADMIN' as const,'LECTURER' as const]}])assert.notEqual(coreAdminScope(actor,'a.importNew'),initial);
  assert.notEqual(coreAdminScope(user,'a.staffInvite'),initial);
  assert.equal(coreAdminScope({...user,roles:['ADMIN','LECTURER']},'a.importNew'),coreAdminScope({...user,roles:['LECTURER','ADMIN']},'a.importNew'));
});
test('all three live Admin forms are reachable from existing Admin-only navigation routes',()=>{
  for(const routeId of ['a.staffInvite','a.importNew','a.dataRequests']){
    assert.ok(sidebars.ADMIN.some(([,id])=>id===routeId));
    assert.deepEqual(getRoute(routeId).allowedRoles,['ADMIN']);
    assert.equal(sidebars.STUDENT.some(([,id])=>String(id)===routeId),false);
    assert.equal(sidebars.LECTURER.some(([,id])=>String(id)===routeId),false);
  }
});
