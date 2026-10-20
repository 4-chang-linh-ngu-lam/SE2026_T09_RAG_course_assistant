'use client';
import {useLayoutEffect,useState} from 'react';
import {draftStore} from '@/lib/draft-store';
// Session memory only. The key must include actor and resource/revision where applicable.
// Never pass passwords, activation/recovery/invitation codes or tokens here.
export function useVolatileDraft<T>(key:string,baseline:T){
 const [value,setValue]=useState<T>(()=>draftStore.get<T>(key)??baseline);
 const clean=JSON.stringify(value)===JSON.stringify(baseline);
 useLayoutEffect(()=>{if(clean)draftStore.remove(key);else draftStore.set(key,value);},[key,value,clean]);
 return [value,setValue] as const;
}
