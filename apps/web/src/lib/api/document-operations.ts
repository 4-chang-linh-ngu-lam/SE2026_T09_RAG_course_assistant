import {resourceUuid} from './operations';

export const documentOperations = {
  capabilities:['GET','/capabilities',200],documents:['GET','/documents',200],upload:['POST','/documents',201],
  detail:['GET','/documents/:documentId',200],edit:['PATCH','/documents/:documentId',200],delete:['DELETE','/documents/:documentId',200],
  versions:['GET','/documents/:documentId/versions',200],uploadVersion:['POST','/documents/:documentId/versions',201],
  retry:['POST','/documents/:documentId/versions/:version/retry',202],ownerContent:['GET','/documents/:documentId/versions/:version/content',200],
  ownerFile:['GET','/documents/:documentId/versions/:version/file',200],grants:['GET','/documents/:documentId/grants',200],
  share:['POST','/documents/:documentId/grants',200],classDocuments:['GET','/classes/:classId/documents',200],
  classDocument:['GET','/classes/:classId/documents/:documentId',200],addGrant:['PUT','/classes/:classId/documents/:documentId/grant',200],
  revoke:['DELETE','/classes/:classId/documents/:documentId/grant',200],classContent:['GET','/classes/:classId/documents/:documentId/versions/:version/content',200],
  classFile:['GET','/classes/:classId/documents/:documentId/versions/:version/file',200],notes:['GET','/notes',200],
  createNote:['POST','/classes/:classId/documents/:documentId/notes',201],editNote:['PATCH','/notes/:noteId',200],deleteNote:['DELETE','/notes/:noteId',200],
  bookmarks:['GET','/bookmarks',200],setBookmark:['PUT','/classes/:classId/documents/:documentId/bookmarks/:version/:locatorId',200],
  deleteBookmark:['DELETE','/bookmarks/:bookmarkId',200],receipt:['GET','/uploads/:requestId',200],
} as const;
export type DocumentOperation=keyof typeof documentOperations;
export type DocumentParams={documentId?:string;classId?:string;version?:number;locatorId?:string;noteId?:string;bookmarkId?:string;requestId?:string};
export const documentQueryKeys=(operation:DocumentOperation):readonly string[]=>
  operation==='documents'?['cursor','limit','search','format','status']:
  operation==='classDocuments'?['cursor','limit','search','format']:
  operation==='notes'||operation==='bookmarks'?['cursor','limit','class_id','document_id']:
  ['versions','grants','ownerContent','classContent'].includes(operation)?['cursor','limit']:[];
export function documentPath(operation:DocumentOperation,params:DocumentParams={}){
  return documentOperations[operation][1].replace(/:([a-zA-Z]+)/g,(_,key:keyof DocumentParams)=>{
    const value=params[key];
    if(key==='version'||key==='locatorId'){
      if(!/^[1-9][0-9]{0,3}$/.test(String(value)))throw new Error('Invalid locator/version');
    }else if(typeof value!=='string'||!resourceUuid.test(value))throw new Error('Invalid resource');
    return String(value);
  });
}
export function matchDocumentOperation(method:string,path:string):DocumentOperation|null{
  for(const [id,[verb,pattern]]of Object.entries(documentOperations)){
    if(method!==verb)continue;
    const keys:string[]=[];
    const regex=new RegExp('^'+pattern.replace(/:([a-zA-Z]+)/g,(_,key)=>{keys.push(key);return '([^/]+)';})+'$');
    const match=regex.exec(path);if(!match)continue;
    if(keys.every((key,index)=>key==='version'||key==='locatorId'?/^[1-9][0-9]{0,3}$/.test(match[index+1]):resourceUuid.test(match[index+1])))return id as DocumentOperation;
  }
  return null;
}
