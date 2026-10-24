'use client';
import {useEffect,useRef,useState} from 'react';
import {useSession} from '@/components/session-provider';
import {useUnsavedChanges} from '@/components/ui';
import {ApiError,errorMessage} from '@/lib/api/errors';

/** A lost mutation response never becomes a second unlocked submit. */
export function useDocumentWrite(resource:string){
  const {user}=useSession(),key=JSON.stringify([user?.id,resource]);
  const current=useRef(key);current.current=key;
  useEffect(()=>{current.current=key;return()=>{if(current.current===key)current.current='unmounted';};},[key]);
  const flight=useRef<string|null>(null);
  const original=useRef<{key:string;work:()=>Promise<unknown>;confirmed?:(value:unknown)=>void}|null>(null);
  const [snapshot,setSnapshot]=useState<{key:string;busy:boolean;unknown:boolean;error:string|null;receiptId?:string}>({key,busy:false,unknown:false,error:null});
  const state=snapshot.key===key?snapshot:{key,busy:false,unknown:false,error:null};
  useUnsavedChanges(state.busy||state.unknown);
  async function run<T>(work:()=>Promise<T>,confirmed?:(result:T)=>void,receiptId?:string){
    if(flight.current===key||state.unknown)return;
    const scope=key;flight.current=scope;setSnapshot({key:scope,busy:true,unknown:false,error:null,receiptId});
    original.current={key:scope,work,confirmed:value=>confirmed?.(value as T)};
    try{const result=await work();if(current.current!==scope)return;setSnapshot({key:scope,busy:false,unknown:false,error:null});confirmed?.(result);}
    catch(error){if(current.current!==scope)return;setSnapshot({key:scope,busy:false,unknown:error instanceof ApiError?error.outcome==='unknown':true,error:errorMessage(error),receiptId});}
    finally{if(flight.current===scope)flight.current=null;}
  }
  async function reconcile(check:()=>Promise<boolean>,confirmed?:()=>void){
    if(flight.current===key||!state.unknown)return;const scope=key;flight.current=scope;setSnapshot({...state,busy:true});
    try{const known=await check();if(current.current!==scope)return;if(known){setSnapshot({key:scope,busy:false,unknown:false,error:null});confirmed?.();}else setSnapshot({...state,busy:false,error:'Chưa có xác nhận đủ chắc chắn. Giữ nguyên thao tác và kiểm tra lại; không gửi một yêu cầu mới.'});}
    catch(error){if(current.current===scope)setSnapshot({...state,busy:false,error:error instanceof Error?error.message:'Chưa đối soát được kết quả.'});}
    finally{if(flight.current===scope)flight.current=null;}
  }
  async function retryOriginal(){
    const captured=original.current;if(!state.unknown||!captured||captured.key!==key)return;
    let result:unknown;await reconcile(async()=>{result=await captured.work();return true;},()=>captured.confirmed?.(result));
  }
  return {...state,blocked:state.busy||state.unknown,run,reconcile,retryOriginal,clearError:()=>{if(!state.unknown&&!state.busy)setSnapshot({...state,error:null});}};
}
