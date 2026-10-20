export type UnsavedGuard = {dirty():boolean;queryKeys?():readonly string[]|undefined};
export function leavesDraftScope(current:string,target:string,queryKeys:readonly string[]=[]):boolean {
  const from=new URL(current),to=new URL(target,current);
  if(from.origin!==to.origin||from.pathname!==to.pathname)return true;
  const keys=new Set([...from.searchParams.keys(),...to.searchParams.keys()]);
  const changed=[...keys].filter(key=>JSON.stringify(from.searchParams.getAll(key))!==JSON.stringify(to.searchParams.getAll(key)));
  return changed.some(key=>!queryKeys.includes(key));
}
export type NavigationClick={button:number;defaultPrevented:boolean;ctrlKey:boolean;metaKey:boolean;shiftKey:boolean;altKey:boolean};
export function guardsAnchor(click:NavigationClick,anchor:{href:string;target?:string;download:boolean;external:boolean},current:string):boolean {
  if(click.defaultPrevented||click.button!==0||click.ctrlKey||click.metaKey||click.shiftKey||click.altKey||anchor.download||anchor.external||(anchor.target&&anchor.target.toLowerCase()!=='_self'))return false;
  try {const target=new URL(anchor.href,current),from=new URL(current);return ['http:','https:'].includes(target.protocol)&&target.origin===from.origin&&leavesDraftScope(current,target.href);}
  catch{return false;}
}
export function createUnsavedCoordinator(){
 const guards=new Set<UnsavedGuard>();
 return {
  register(guard:UnsavedGuard){guards.add(guard);return()=>{guards.delete(guard);};},
  get size(){return guards.size;},
  hasDirty(){return [...guards].some(g=>g.dirty());},
  confirm(current:string,target:string|undefined,ask:()=>boolean){return ![...guards].some(g=>g.dirty()&&(!target||leavesDraftScope(current,target,g.queryKeys?.())))||ask();},
 };
}
