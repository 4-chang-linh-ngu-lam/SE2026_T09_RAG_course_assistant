'use client';
import {useEffect,useState} from 'react';
import {adapter} from '@/lib/data';
import {createDataRequestController} from '@/lib/data-request-controller';
import {useSession} from '@/components/session-provider';
import {useUnsavedChanges} from '@/components/unsaved-changes';

export function useDataRequestsState(){
 const {user}=useSession();
 const [entry,setEntry]=useState<{actorId:string;controller:ReturnType<typeof createDataRequestController>;state:ReturnType<ReturnType<typeof createDataRequestController>['getState']>}|null>(null);
 useEffect(()=>{
  if(!user)return;
  const controller=createDataRequestController({actorId:user.id,listRequests:cursor=>adapter.identity.requests(cursor),createRequest:(type,reason)=>adapter.identity.createRequest(type,reason)});
  const update=()=>setEntry({actorId:user.id,controller,state:controller.getState()});
  const unsubscribe=controller.subscribe(update);update();void controller.refreshList();
  return()=>{unsubscribe();controller.dispose();};
 },[user?.id]);
 const current=entry?.actorId===user?.id?entry:null;
 useUnsavedChanges(Boolean(current&&(current.state.draft.reason.trim()||current.state.draft.type!=='ACCESS'||['submitting','unknown'].includes(current.state.mutation))));
 return current;
}
