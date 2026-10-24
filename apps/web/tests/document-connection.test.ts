import test from 'node:test';
import assert from 'node:assert/strict';
import {createDocumentProxy} from '../src/lib/api/document-proxy';
import {createDocumentHttpClient} from '../src/lib/api/document-http';
import {documentOperations,documentPath,matchDocumentOperation} from '../src/lib/api/document-operations';
import {decodeContent,decodeNote} from '../src/lib/api/document-decoders';
import {createLiveCoreSession} from '../src/lib/data/live-identity';
import {signClientContext,CLIENT_CONTEXT_HEADER} from '../config/client-identity.mjs';
import {ApiError} from '../src/lib/api/errors';
import {notificationTarget} from '../src/lib/notification-target';
import {decodeNotificationPage} from '../src/lib/api/notification-decoders';
const doc='10000000-0000-4000-8000-000000000001',klass='10000000-0000-4000-8000-000000000002',requestId='10000000-0000-4000-8000-000000000003';
const secret='synthetic-document-proxy-'+ 'x'.repeat(32),web='http://localhost:3000';
const params={documentId:doc,classId:klass,version:1,locatorId:'1',noteId:doc,bookmarkId:doc,requestId};
const json=(value:unknown,status=200)=>Response.json(value,{status});
const rejected=(outcome:string)=>(error:unknown)=>error instanceof ApiError&&error.outcome===outcome;

test('Document has exactly 27 browser operations; internal and traversal are rejected',()=>{
  assert.equal(Object.keys(documentOperations).length,27);
  for(const [id,[method]]of Object.entries(documentOperations)){
    const path=documentPath(id as keyof typeof documentOperations,params);
    assert.equal(matchDocumentOperation(method,path),id);
  }
  for(const path of ['/internal/v1/events','/documents/../notes','/documents/'+doc+'/versions/0/file','/documents/not-uuid','/auth/login'])assert.equal(matchDocumentOperation('GET',path),null);
});

test('Document proxy forwards original binary multipart without cookies or service credentials',async()=>{
  const binary=new Uint8Array([0,255,254,13,10,65]),body=new FormData();body.set('file',new File([binary],'source.pdf'));body.set('title','Binary upload');
  let calls=0;
  const proxy=createDocumentProxy(()=> 'http://document:8200',(async(url,init)=>{
    calls++;assert.equal(String(url),'http://document:8200/api/v1/documents');
    const headers=new Headers(init?.headers);assert.equal(headers.get('Authorization'),'Bearer test');assert.equal(headers.get('Idempotency-Key'),requestId);
    for(const name of ['cookie','x-service-key',CLIENT_CONTEXT_HEADER,'x-forwarded-for'])assert.equal(headers.has(name),false);
    const received=await new Response(init?.body,{headers}).formData();const file=received.get('file');assert.ok(file instanceof File);
    assert.deepEqual(new Uint8Array(await file.arrayBuffer()),binary);assert.equal(received.get('title'),'Binary upload');
    return new Response('{"data":{}}',{status:201,headers:{'Content-Type':'application/json','Set-Cookie':'untrusted=1'}});
  }) as typeof fetch,()=>web,()=>secret);
  const path='/api/document/v1/documents';
  const request=new Request(web+path,{method:'POST',headers:{Origin:web,Authorization:'Bearer test','Idempotency-Key':requestId,Cookie:'refresh=private','X-Service-Key':'untrusted',[CLIENT_CONTEXT_HEADER]:signClientContext('127.0.0.1','POST',path,secret)},body});
  const response=await proxy(request,['documents']);assert.equal(response.status,201);assert.equal(calls,1);assert.equal(response.headers.has('Set-Cookie'),false);assert.equal(response.headers.get('Cache-Control'),'no-store');
});

test('Document proxy denies forged listener context, wrong origin, unapproved queries and over-limit lengths',async()=>{
  let calls=0;const proxy=createDocumentProxy(()=> 'http://document:8200',(async()=>{calls++;return json({});}) as typeof fetch,()=>web,()=>secret);
  const path='/api/document/v1/documents',signed=signClientContext('127.0.0.1','POST',path,secret);
  for(const [extra,status]of [[{Origin:'https://external.example'},403],[{[CLIENT_CONTEXT_HEADER]:'forged'},403],[{'Content-Length':String(51*1024*1024)},413]] as const){
    const headers=new Headers({Origin:web,Authorization:'Bearer test',[CLIENT_CONTEXT_HEADER]:signed});for(const [key,value]of Object.entries(extra))if(value!==undefined)headers.set(key,value);
    const request=new Request(web+path,{method:'POST',headers,body:'{}'});
    assert.equal((await proxy(request,['documents'])).status,status);
  }
  const query=new Request(web+path+'?user_id='+doc,{headers:{Authorization:'Bearer test',[CLIENT_CONTEXT_HEADER]:signClientContext('127.0.0.1','GET',path,secret)}});
  assert.equal((await proxy(query,['documents'])).status,422);assert.equal(calls,0);
});

test('Document transport marks lost upload and invalid acknowledgements unknown without replay',async()=>{
  for(const response of [null,new Response('not-json',{status:201}),json({error:{code:'UNAVAILABLE',message:'failed'}},503)]){
    let calls=0;const request=createDocumentHttpClient(()=> 'test',(async()=>{calls++;if(!response)throw new TypeError('offline');return response;}) as typeof fetch);
    const fileBody=new FormData();fileBody.set('file',new File(['bytes'],'source.txt'));
    await assert.rejects(request('upload',{fileBody,idempotencyKey:requestId}),rejected('unknown'));assert.equal(calls,1);
  }
});

test('Core and Document share one credential refresh and expose no token getter',async()=>{
  let now=0,refreshes=0;const seen:string[]=[];
  const user={id:doc,username:'teacher',email:null,school_id:klass,roles:['LECTURER'],status:'ACTIVE',display_name:'Synthetic'};
  const session=createLiveCoreSession({now:()=>now,onLost(){},fetcher:(async(path,init)=>{
    if(String(path).endsWith('/login'))return json({access_token:'first',token_type:'bearer',expires_in:1});
    if(String(path).endsWith('/refresh')){refreshes++;return json({access_token:'renewed',token_type:'bearer',expires_in:600});}
    seen.push(new Headers(init?.headers).get('Authorization')??'');
    return String(path).endsWith('/me')?json(user):json({data:{},items:[],next_cursor:null});
  }) as typeof fetch});
  await session.identity.login({username:'teacher',password:'synthetic'});now=1001;
  await Promise.all([session.documentAuthenticated(request=>request('capabilities')),session.authenticated(request=>request('dataRequests'))]);
  assert.equal(refreshes,1);assert.deepEqual(seen.slice(-2),['Bearer renewed','Bearer renewed']);assert.equal('getToken' in session,false);
});

test('a late Document mutation cannot update a new actor after login changes',async()=>{
  let complete!:(value:Response)=>void;const gate=new Promise<Response>(resolve=>complete=resolve);let actor='first';
  const session=createLiveCoreSession({onLost(){},fetcher:(async(path)=>{
    if(String(path).endsWith('/login'))return json({access_token:actor,token_type:'bearer',expires_in:600});
    if(String(path).endsWith('/me'))return json({id:actor,email:null,username:actor,school_id:klass,roles:['STUDENT'],status:'ACTIVE',display_name:actor});
    return gate;
  }) as typeof fetch});
  await session.identity.login({username:'first',password:'synthetic'});
  const write=session.documentAuthenticated(request=>request('deleteBookmark',{bookmarkId:doc}),true);
  await new Promise(resolve=>setImmediate(resolve));actor='second';await session.identity.login({username:'second',password:'synthetic'});complete(json({data:{deleted:true}}));
  await assert.rejects(write,(error:unknown)=>error instanceof ApiError&&error.code==='SESSION_CHANGED'&&error.outcome==='unknown');
});

test('Document decoders reject a source quote exposed after revoke and a response from another version',()=>{
  const note={id:doc,document_id:doc,document_title:'Synthetic',document_format:'TXT',version:1,class_id:klass,class_name:'Historical class',locator_id:'1',locator_label:'Mục 1',source_access:'REVOKED',source_quote:'must not be exposed',note_text:'my own text',revision:1,updated_at:new Date().toISOString(),client_request_id:requestId};
  assert.throws(()=>decodeNote(note),ApiError);
  const safe=decodeNote({...note,source_quote:null});assert.equal(safe.noteText,'my own text');assert.equal(safe.sourceQuote,undefined);assert.equal(safe.isSourceAccessible,false);
  assert.throws(()=>decodeContent({data:{document_id:doc,version:2,locators:[]}},doc,1),ApiError);
});

test('Document notifications build local role-scoped source links and ignore raw URLs',()=>{
  const value={items:[{id:doc,type:'DOCUMENT_GRANT_CHANGED',read:false,created_at:new Date().toISOString(),payload_json:{class_id:klass,document_id:doc,url:'https://external.example/private'}}],unread_count:1,next_cursor:null};
  const item=decodeNotificationPage(value,requestId).items[0];
  assert.equal(notificationTarget(item,['STUDENT']).targetHref,`/student/classes/${klass}/documents/${doc}`);
  assert.equal(notificationTarget(item,['LECTURER']).targetHref,`/teacher/classes/${klass}/documents`);
  assert.equal(notificationTarget(item,['ADMIN']).targetHref,undefined);
});
