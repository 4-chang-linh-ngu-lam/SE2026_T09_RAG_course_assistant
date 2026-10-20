export type ResourceSelectionMode = 'ALL' | 'EXPLICIT';
export function activitySelection(ids:readonly string[]=[],mode?:ResourceSelectionMode){
  const selectionMode=mode??(ids.length?'EXPLICIT':'ALL');
  return {resourceSelectionMode:selectionMode,resourceIds:selectionMode==='ALL'?[]:[...new Set(ids)]};
}
export function activityIncluded(id:string,ids:readonly string[],mode:ResourceSelectionMode){return mode==='ALL'||ids.includes(id);}
export function toggleActivity(ids:readonly string[],id:string){return ids.includes(id)?ids.filter(value=>value!==id):[...ids,id];}
