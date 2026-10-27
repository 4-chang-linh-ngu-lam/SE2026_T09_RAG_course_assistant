'use client';
import {useCallback,useLayoutEffect,useState,type Dispatch,type SetStateAction} from 'react';
import {draftStore} from '@/lib/draft-store';
// Session memory only. The key must include actor and resource/revision where applicable.
// Never pass passwords, activation/recovery/invitation codes or tokens here.
export type VolatileDraftSnapshot<T> = { key: string; value: T; baseline: T };
const sameValue = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);

export function resolveVolatileDraftSnapshot<T>(state: VolatileDraftSnapshot<T>, key: string, baseline: T): VolatileDraftSnapshot<T> {
 if (state.key !== key) return { key, value: draftStore.get<T>(key) ?? baseline, baseline };
 if (sameValue(state.baseline, baseline)) return state;
 const value = sameValue(state.value, state.baseline) ? baseline : state.value;
 return { key, value, baseline };
}

export function persistVolatileDraftSnapshot<T>(key: string, state: VolatileDraftSnapshot<T>, baseline: T): void {
 // A render can observe a new key before React has synchronized the snapshot.
 // Never write the previous scope's value into that new key.
 if (state.key !== key || !sameValue(state.baseline, baseline)) return;
 if (sameValue(state.value, baseline)) draftStore.remove(key);
 else draftStore.set(key, state.value);
}

export function useVolatileDraft<T>(key:string,baseline:T): readonly [T, Dispatch<SetStateAction<T>>] {
 const [snapshot,setSnapshot]=useState<VolatileDraftSnapshot<T>>(()=>({key,value:draftStore.get<T>(key)??baseline,baseline}));
 const current = resolveVolatileDraftSnapshot(snapshot,key,baseline).value;
 useLayoutEffect(()=>{
   const resolved=resolveVolatileDraftSnapshot(snapshot,key,baseline);
   if(resolved!==snapshot){setSnapshot(resolved);return;}
   persistVolatileDraftSnapshot(key,snapshot,baseline);
 },[key,snapshot,baseline]);
 const setValue=useCallback<Dispatch<SetStateAction<T>>>(next=>{
   setSnapshot(previous=>{
     const previousValue=resolveVolatileDraftSnapshot(previous,key,baseline).value;
     return {key,value:typeof next==='function'?(next as (value:T)=>T)(previousValue):next,baseline};
   });
 },[key,baseline]);
 return [current,setValue] as const;
}
