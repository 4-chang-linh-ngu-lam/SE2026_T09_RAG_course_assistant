import type {DocumentVersion} from './domain';
export function documentVersionState(versions:readonly DocumentVersion[]){
  const ordered=[...versions].sort((a,b)=>b.versionNumber-a.versionNumber);
  const latest=ordered[0]??null;
  const serving=ordered.find(v=>v.status==='READY')??null;
  const failed=latest?.status==='FAILED'&&(!serving||latest.versionNumber>serving.versionNumber)?latest:null;
  return {ordered,latest,serving,failed};
}
