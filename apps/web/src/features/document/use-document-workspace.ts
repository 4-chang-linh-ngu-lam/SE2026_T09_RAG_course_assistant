'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {adapter} from '@/lib/data';
import {useSession} from '@/components/session-provider';
import {useClassSummary} from '@/components/class-summary-context';
import {errorMessage} from '@/lib/api/errors';
import {subscribeForegroundSync} from '@/lib/foreground-sync';
import type {RouteParams,WorkspaceData} from '@/lib/domain';
import {resourceParamsKey} from '@/lib/route-load-plan';

export function useDocumentWorkspace(routeId:string,params:RouteParams){
  const {user}=useSession(),key=JSON.stringify([user?.id,user?.roles,routeId,resourceParamsKey(routeId,params)]);
  const latestParams=useRef(params);latestParams.current=params;
  const scope=useRef(key);scope.current=key;
  const [snapshot,setSnapshot]=useState<{key:string;data:WorkspaceData;updatedAt:string}|null>(null);
  const refreshRef=useRef<(force:boolean)=>void>(()=>undefined);
  useEffect(()=>{
    let disposed=false,generation=0,flight:AbortController|null=null;
    const refresh=(force:boolean)=>{
      if(flight&&!force)return;flight?.abort();
      const controller=new AbortController(),expected=++generation;flight=controller;
      void adapter.workspace.load(routeId,latestParams.current,controller.signal).then(data=>{
        if(!disposed&&scope.current===key&&expected===generation&&!controller.signal.aborted)setSnapshot({key,data,updatedAt:new Date().toISOString()});
      }).catch(error=>{
        if(!disposed&&scope.current===key&&expected===generation&&!controller.signal.aborted)setSnapshot({key,data:{kind:'unavailable',message:errorMessage(error)},updatedAt:new Date().toISOString()});
      }).finally(()=>{if(flight===controller)flight=null;});
    };
    refreshRef.current=refresh;
    const unsubscribe=subscribeForegroundSync(()=>refresh(false),10000);
    refresh(false);
    return()=>{disposed=true;generation++;flight?.abort();unsubscribe();};
  },[key]);
  const data=snapshot?.key===key?snapshot.data:null;
  useClassSummary(data?.kind==='ready'?data.classSummary:undefined,data===null);
  return {data,reload:useCallback(()=>refreshRef.current(true),[]),updatedAt:snapshot?.key===key?snapshot.updatedAt:undefined};
}
