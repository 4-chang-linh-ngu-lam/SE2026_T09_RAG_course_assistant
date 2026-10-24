'use client';
import {useEffect,useRef,useState} from 'react';
import {adapter} from '@/lib/data';
import {createCoreAdminController,type CoreAdminController,type CoreAdminState} from '@/lib/core-admin-controller';
import {coreAdminScope,type CoreAdminRoute} from '@/lib/core-admin-routing';
import {useSession} from '@/components/session-provider';
import {useUnsavedChanges} from '@/components/unsaved-changes';
import {StatePanel} from '@/components/ui';
import {CoreStaffInviteView,CoreImportView,CoreDataRequestsView} from './core-admin-views';
import '../accounts/accounts.css';

type Entry={scope:string;controller:CoreAdminController;state:CoreAdminState};
export function CoreAdminFeature({routeId}:{routeId:CoreAdminRoute}){
  const session=useSession(),latest=useRef(session);
  latest.current=session;
  const scope=session.status==='authenticated'?coreAdminScope(session.user,routeId):null;
  const [entry,setEntry]=useState<Entry|null>(null);
  const api=adapter.source==='live'?adapter.core:undefined;
  useEffect(()=>{
    if(!scope||!api)return;
    const controller=createCoreAdminController(api,()=>latest.current.status==='authenticated'&&coreAdminScope(latest.current.user,routeId)===scope);
    const update=()=>setEntry({scope,controller,state:controller.getState()});
    const unsubscribe=controller.subscribe(update);update();
    if(routeId==='a.dataRequests')void controller.loadRequests();
    return()=>{unsubscribe();controller.dispose();};
  },[scope,routeId,api]);
  const current=entry?.scope===scope?entry:null;
  useUnsavedChanges(Boolean(current&&(current.state.busy||current.state.unknown||current.state.preview||current.state.receipt)));
  if(!scope)return <StatePanel busy={session.status==='loading'} title={session.status==='loading'?'Đang kiểm tra phiên…':'Cần quyền quản trị hiện hành của nhà trường'}/>;
  if(!api)return <StatePanel title="Chức năng quản trị chưa sẵn sàng"/>;
  if(!current)return <StatePanel busy title="Đang mở chức năng quản trị…"/>;
  const {state,controller}=current;
  return <div className="accounts-workspace" aria-busy={state.busy}>
    {routeId==='a.staffInvite'?<CoreStaffInviteView state={state} onSubmit={input=>{void controller.invite(input);}}/>:
      routeId==='a.importNew'?<CoreImportView state={state} onPreview={file=>{void controller.previewFile(file);}} onConfirm={reason=>{void controller.confirmImport(reason);}} onReconfirm={reason=>{void controller.confirmImport(reason,true);}} onClearCodes={()=>controller.clearCodes()}/>:
      <CoreDataRequestsView state={state} onReload={()=>{void controller.loadRequests();}} onSelect={id=>{void controller.selectRequest(id);}} onResolve={input=>{void controller.resolve(input);}}/>}
  </div>;
}
