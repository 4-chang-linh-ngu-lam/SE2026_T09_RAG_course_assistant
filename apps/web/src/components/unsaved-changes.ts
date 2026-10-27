'use client';
import {useEffect,useMemo,useRef} from 'react';
import {useRouter} from 'next/navigation';
import {createUnsavedCoordinator,guardsAnchor} from '@/lib/unsaved-navigation';

const coordinator=createUnsavedCoordinator();
const message='Bạn còn thay đổi chưa lưu. Rời trang?';
type GuardOptions={queryKeys?:readonly string[]};
type TraverseEvent=Event&{navigationType:string;hashChange?:boolean;destination?:{url:string;sameDocument:boolean}};
function browserNavigation(){return (window as Window&{navigation?:EventTarget}).navigation;}
function confirmNavigation(href?:string){
 if(typeof window==='undefined')return true;
 // Full document navigation has its own native beforeunload confirmation.
 if(href&&new URL(href,location.href).origin!==location.origin)return true;
 return coordinator.confirm(location.href,href,()=>window.confirm(message));
}
let detach:(()=>void)|undefined;
function attach(){
 if(detach)return;
 const click=(event:MouseEvent)=>{
  const element=event.target instanceof Element?event.target:event.target instanceof Node?event.target.parentElement:null;
  const anchor=element?.closest<HTMLAnchorElement>('a[href]');
  if(!anchor||!guardsAnchor(event,{href:anchor.href,target:anchor.target,download:anchor.hasAttribute('download'),external:anchor.rel.split(/\s+/).includes('external')},location.href))return;
  if(!confirmNavigation(anchor.href)){event.preventDefault();event.stopImmediatePropagation();}
 };
 const unload=(event:BeforeUnloadEvent)=>{if(coordinator.hasDirty()){event.preventDefault();event.returnValue='';}};
 const traverse=(event:Event)=>{
  const e=event as TraverseEvent;
  if(e.navigationType!=='traverse'||!e.cancelable||e.hashChange||e.destination?.sameDocument===false)return;
  if(!confirmNavigation(e.destination?.url))e.preventDefault();
 };
 const navigation=browserNavigation();
 document.addEventListener('click',click,true);window.addEventListener('beforeunload',unload);navigation?.addEventListener('navigate',traverse);
 detach=()=>{document.removeEventListener('click',click,true);window.removeEventListener('beforeunload',unload);navigation?.removeEventListener('navigate',traverse);detach=undefined;};
}
export function useUnsavedChanges(dirty:boolean,options:GuardOptions={}){
 const latest=useRef({dirty,options});latest.current={dirty,options};
 useEffect(()=>{
  const unregister=coordinator.register({dirty:()=>latest.current.dirty,queryKeys:()=>latest.current.options.queryKeys});attach();
  return()=>{unregister();if(!coordinator.size)detach?.();};
 },[]);
 return {confirmDiscard:()=>!latest.current.dirty||window.confirm('Bỏ các thay đổi chưa lưu trong biểu mẫu này?')};
}
export function useGuardedRouter(){
 const router=useRouter();
 return useMemo(()=>({
  ...router,
  push(...args:Parameters<typeof router.push>){if(confirmNavigation(args[0]))router.push(...args);},
  replace(...args:Parameters<typeof router.replace>){if(confirmNavigation(args[0]))router.replace(...args);},
  back(){if(browserNavigation()||confirmNavigation())router.back();},
  forward(){if(browserNavigation()||confirmNavigation())router.forward();},
  // Call only after a verified ACK, or the user's explicit leave confirmation.
  pushConfirmed(...args:Parameters<typeof router.push>){router.push(...args);},
  replaceConfirmed(...args:Parameters<typeof router.replace>){router.replace(...args);},
 }),[router]);
}
