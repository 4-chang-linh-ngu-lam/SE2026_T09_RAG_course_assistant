'use client';
import {useEffect,useRef,useState} from 'react';
import {adapter} from '@/lib/data';
import {useSession} from '@/components/session-provider';
import {useUnsavedChanges} from '@/components/unsaved-changes';
import {StatePanel} from '@/components/ui';
import {createCoreManagementController,type CoreManagementController,type CoreManagementRoute,type CoreManagementState} from '@/lib/core-management-controller';
import type {RouteParams} from '@/lib/domain';
import {CoreManagementView} from './core-management-views';
import '../accounts/accounts.css';

type Entry={scope:string;controller:CoreManagementController;state:CoreManagementState};
export function CoreManagementFeature({routeId,params}:{routeId:CoreManagementRoute;params:RouteParams}){
  const session=useSession(),latest=useRef(session);latest.current=session;
  const user=session.status==='authenticated'?session.user:null;
  const scope=user?.status==='ACTIVE'&&user.roles.includes('ADMIN')&&user.school_id?JSON.stringify([routeId,params,user.id,user.school_id,[...user.roles].sort()]):null;
  const [entry,setEntry]=useState<Entry|null>(null),[draftDirty,setDraftDirty]=useState(false),api=adapter.source==='live'?adapter.core:undefined;
  useEffect(()=>{
    if(!scope||!api)return;
    const [boundRoute,boundParams,boundUser,schoolId,boundRoles]=JSON.parse(scope) as [CoreManagementRoute,RouteParams,string,string,string[]];
    const controller=createCoreManagementController(api,{routeId:boundRoute,params:boundParams,schoolId,issueCode:adapter.identity.issueCode,isCurrentActor:()=>{
      const current=latest.current;return current.status==='authenticated'&&Boolean(current.user&&current.user.id===boundUser&&current.user.status==='ACTIVE'&&current.user.school_id===schoolId&&JSON.stringify([...current.user.roles].sort())===JSON.stringify(boundRoles));
    }});
    const update=()=>setEntry({scope,controller,state:controller.getState()});const unsubscribe=controller.subscribe(update);update();void controller.load();
    return()=>{unsubscribe();controller.dispose();};
  },[scope,api]);
  const current=entry?.scope===scope?entry:null;
  useEffect(()=>{setDraftDirty(false);},[scope,current?.state.account,current?.state.roster,current?.state.teachers,current?.state.classes,current?.state.courses]);
  useUnsavedChanges(Boolean(current&&(draftDirty||current.state.busy||current.state.unknown||current.state.issued)));
  if(!scope)return <StatePanel busy={session.status==='loading'} title="Cần quyền quản trị hiện hành của nhà trường"/>;
  if(!api)return <StatePanel title="Chức năng quản trị chưa sẵn sàng"/>;
  if(!current)return <StatePanel busy title="Đang tải dữ liệu quản trị…"/>;
  const {state,controller}=current;
  return <div onChangeCapture={event=>{if((event.target as Element).closest('form'))setDraftDirty(true);}}><CoreManagementView key={scope} routeId={routeId} params={params} state={state} onReload={()=>{if(!draftDirty||window.confirm('Tải lại sẽ bỏ nội dung biểu mẫu chưa lưu. Tiếp tục tải lại?'))void controller.load();}} onAcknowledgeUnknown={()=>controller.acknowledgeUnknown()} onCommand={(operation,options)=>{void controller.command(operation,options);}} onPreview={()=>{void controller.previewEnrollment();}} onIssueCode={verified=>{void controller.issueCode(verified);}} onClearCode={()=>controller.clearCode()}/></div>;
}
