import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {CoreStaffInviteView,CoreImportView,CoreDataRequestsView} from '../src/features/administration/core-admin-views';
import type {CoreAdminState} from '../src/lib/core-admin-controller';
const a='00000000-0000-4000-8000-000000000001',b='00000000-0000-4000-8000-000000000002';
const stamp='2026-10-22T12:00:00Z',once='SYNTHETIC-ONCE-DISCLOSURE';
const initial=():CoreAdminState=>({busy:false,unknown:null,issue:null,staff:null,filename:null,preview:null,receipt:null,requests:[],selected:null,loaded:false});
const preview={valid:true,preview_id:a,expires_at:stamp,items:[{row:2,action:'CREATE' as const,username:'synthetic',user_id:null}],errors:[]};
const student={id:b,email:null,username:'synthetic',school_id:a,display_name:null,status:'PENDING_VERIFICATION' as const};
const receipt={preview_id:a,status:'COMPLETED' as const,replayed:false,items:[{row:2,outcome:'CREATED' as const,student,code:once,expires_at:stamp}]};
const noCommand=()=>{throw new Error('Rendering must not invoke a command');};
const importActions={onPreview:noCommand,onConfirm:noCommand,onReconfirm:noCommand,onClearCodes:noCommand};
const button=(html:string,label:string)=>{
  const text=label.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const match=new RegExp('<button\\b([^>]*)>[^<]*'+text+'[^<]*</button>').exec(html);assert.ok(match,'Expected action button');return match[1];
};
test('staff acknowledgement uses actual returned fields; unknown locks input and never renders a raw invitation code',()=>{
  const html=renderToStaticMarkup(React.createElement(CoreStaffInviteView,{state:{...initial(),staff:{...student,email:'staff@fixture.example.com'}},onSubmit:noCommand}));
  assert.ok(html.includes(b));assert.ok(html.includes('staff@fixture.example.com'));assert.equal(html.includes(once),false);
  const unknown=renderToStaticMarkup(React.createElement(CoreStaffInviteView,{state:{...initial(),unknown:'staff',issue:{message:'<script>synthetic</script>',correlationId:a}},onSubmit:noCommand}));
  assert.match(unknown,/<input[^>]*type="email"[^>]*disabled=""/);assert.match(button(unknown,'Gửi lời mời nhân sự'),/disabled/);
  assert.equal(unknown.includes('<script>'),false);assert.ok(unknown.includes('&lt;script&gt;'));assert.ok(unknown.includes(a));
});
test('a rendered preview locks file changes until explicit discard, even if a replacement could have the same filename',()=>{
  const html=renderToStaticMarkup(React.createElement(CoreImportView,{state:{...initial(),filename:'students.csv',preview},...importActions}));
  assert.match(html,/<input[^>]*type="file"[^>]*disabled=""/);assert.doesNotMatch(button(html,'Chọn tệp khác'),/disabled/);
  assert.ok(html.includes('students.csv'));assert.ok(html.includes(a));assert.equal(html.includes(once),false);
});
test('import renders actual first-disclosure codes; replay null never produces a replacement code',()=>{
  const html=renderToStaticMarkup(React.createElement(CoreImportView,{state:{...initial(),receipt},...importActions}));assert.ok(html.includes(once));
  const replay=renderToStaticMarkup(React.createElement(CoreImportView,{state:{...initial(),receipt:{...receipt,replayed:true,items:receipt.items.map(item=>({...item,code:null,expires_at:null}))}},...importActions}));
  assert.equal(replay.includes(once),false);assert.ok(replay.includes(b));assert.match(replay,/Mã đã phát hành sẽ không hiển thị lại/);
});
test('unknown import offers deliberate same-preview re-confirmation and locks unrelated file/confirmation actions',()=>{
  const html=renderToStaticMarkup(React.createElement(CoreImportView,{state:{...initial(),preview,unknown:'confirm'},...importActions}));
  assert.doesNotMatch(button(html,'Xác nhận lại theo mã phiên nhập'),/disabled/);
  assert.match(button(html,'Xác nhận nhập danh sách'),/disabled/);assert.match(html,/<input[^>]*type="file"[^>]*disabled=""/);
});
test('data-request UI displays server IN_REVIEW and safe text, blocking writes during unknown reconciliation',()=>{
  const selected={id:a,user_id:b,type:'EXPORT' as const,reason:'<img src=x onerror=synthetic>',status:'IN_REVIEW' as const,resolution_note:'POLICY_PENDING',created_at:stamp,updated_at:stamp};
  const html=renderToStaticMarkup(React.createElement(CoreDataRequestsView,{state:{...initial(),loaded:true,requests:[selected],selected,unknown:'resolve'},onReload:noCommand,onSelect:noCommand,onResolve:noCommand}));
  assert.match(html,/<h1[^>]*>Yêu cầu dữ liệu cá nhân<\/h1>/);assert.ok(html.includes('Đang xem xét'));assert.equal(html.includes('<img'),false);assert.ok(html.includes('&lt;img'));
  assert.match(button(html,'Xác nhận xử lý yêu cầu'),/disabled/);assert.doesNotMatch(button(html,'Tải lại danh sách để đối soát'),/disabled/);
  assert.doesNotMatch(html,/<strong[^>]*>Đã hoàn thành<\/strong>/);
});
