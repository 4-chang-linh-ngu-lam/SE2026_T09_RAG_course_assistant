'use client';
import {createContext,useContext,useEffect,type ReactNode} from 'react';
import type {ClassSummary} from '@/lib/domain';

export type ClassSummaryState={summary:ClassSummary|undefined;pending:boolean};
type Publish=(state:ClassSummaryState)=>void;
const Context=createContext<Publish|null>(null);

export function ClassSummaryProvider({publish,children}:{publish:Publish;children:ReactNode}){
  return <Context.Provider value={publish}>{children}</Context.Provider>;
}

/** Publish the same authorized projection the feature consumes; never a separate permission cache. */
export function useClassSummary(summary:ClassSummary|undefined,pending=false):void{
  const publish=useContext(Context);
  useEffect(()=>{publish?.({summary:pending?undefined:summary,pending});},[publish,summary,pending]);
}
