'use client';
import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {adapter} from '@/lib/data';
import {ApiError} from '@/lib/api/errors';
import {createNotificationReadController,type NotificationReadController,type NotificationReadState,type NotificationSnapshotRequest} from '@/lib/notification-read-controller';
import {subscribeForegroundSync} from '@/lib/foreground-sync';
import {notificationTarget} from '@/lib/notification-target';
import {useSession} from './session-provider';

type Snapshot={key:string;state:NotificationReadState;loaded:boolean;syncing:boolean;lastSyncedAt:number|null};
type Value={state:NotificationReadState;loaded:boolean;syncing:boolean;lastSyncedAt:number|null;controller:NotificationReadController|null};
const empty=(actorId:string):NotificationReadState=>({actorId,items:[],unreadCount:0,busy:false,reconciling:false,issue:null,snapshotError:null});
const Context=createContext<Value|null>(null);

/** One inbox per active session, shared by the shell bell and the center. No browser storage. */
export function NotificationSyncProvider({children}:{children:ReactNode}){
  const session=useSession(),user=session.status==='authenticated'?session.user:null;
  const key=JSON.stringify([user?.id,user?.school_id,user?.roles]);
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
  const controllerRef=useRef<NotificationReadController|null>(null);
  useEffect(()=>{
    if(!user){controllerRef.current=null;setSnapshot(null);return;}
    let alive=true,loaded=false,syncing=false,lastSyncedAt:number|null=null,pending:AbortController|null=null;
    let controller:NotificationReadController;
    const publish=()=>{if(alive)setSnapshot({key,state:controller.getState(),loaded,syncing,lastSyncedAt});};
    async function receive(ticket:NotificationSnapshotRequest){
      pending?.abort();const request=new AbortController();pending=request;syncing=true;publish();
      try{
        const data=await adapter.workspace.load('account.notifications',{},request.signal);
        if(!alive||request.signal.aborted)return;
        if(data.kind==='unavailable')throw new ApiError('UNAVAILABLE',data.message,503);
        if(controller.receiveSnapshot(data.kind==='ready'?data.notifications??[]:[],ticket,data.kind==='ready'?data.notificationUnreadCount:0)){
          loaded=true;lastSyncedAt=Date.now();
        }
      }catch(error){if(alive&&!request.signal.aborted)controller.rejectSnapshot(error,ticket);}
      finally{if(pending===request){pending=null;syncing=false;publish();}}
    }
    controller=createNotificationReadController({actorId:user.id,markOne:id=>adapter.notifications.markAsRead(id),markAll:()=>adapter.notifications.markAllAsRead(),reload:receive});
    controllerRef.current=controller;const unsubscribe=controller.subscribe(publish);publish();
    const stop=subscribeForegroundSync(()=>{const state=controller.getState();if(!pending&&!state.busy&&state.issue?.outcome!=='unknown')controller.refresh();});
    return()=>{alive=false;stop();pending?.abort();unsubscribe();controller.dispose();if(controllerRef.current===controller)controllerRef.current=null;};
  },[key]);
  const current=snapshot?.key===key?snapshot:null;
  const raw=current?.state??empty(user?.id??'');
  const state={...raw,items:raw.items.map(item=>notificationTarget(item,user?.roles??[]))};
  return <Context.Provider value={{state,loaded:current?.loaded??false,syncing:current?.syncing??false,lastSyncedAt:current?.lastSyncedAt??null,controller:current?controllerRef.current:null}}>{children}</Context.Provider>;
}
export function useNotificationSync(){const value=useContext(Context);if(!value)throw new Error('NotificationSyncProvider required');return value;}
