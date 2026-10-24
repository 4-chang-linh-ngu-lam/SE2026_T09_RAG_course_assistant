import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveIdentity } from '../src/lib/data/live-identity';
import { ApiError } from '../src/lib/api/errors';
const user = (id = 'a') => ({id,email:null,username:id,school_id:'school',display_name:id,roles:['STUDENT'],status:'ACTIVE'});
const json = (body:unknown,status=200) => Response.json(body,{status});
const access = (value:string,expires_in=600) => json({access_token:value,token_type:'bearer',expires_in});
const pending = () => {let resolve!:(response:Response)=>void;const promise=new Promise<Response>(done=>{resolve=done;});return {promise,resolve};};
const tick = () => new Promise<void>(resolve=>setImmediate(resolve));
function fetcher(run:(path:string,init:RequestInit)=>Promise<Response>|Response):typeof fetch {return ((url,init={})=>Promise.resolve(run(String(url),init))) as typeof fetch;}

for(const operation of ['requests','logoutAll'] as const)test(`refresh cannot switch a confirmed actor before ${operation}`,async()=>{
  let now=0,profiles=0,protectedCalls=0;
  const identity=createLiveIdentity({now:()=>now,onLost(){},fetcher:fetcher(path=>{
    if(path.endsWith('/login')||path.endsWith('/refresh'))return access('synthetic',1);
    if(path.endsWith('/users/me'))return json(user(profiles++===0?'a':'another-tab'));
    protectedCalls++;return new Response(null,{status:204});
  })});
  await identity.login({username:'a',password:'synthetic'});now=2000;
  await assert.rejects(identity[operation](),(error:unknown)=>error instanceof ApiError&&error.code==='SESSION_CHANGED');
  assert.equal(protectedCalls,0);assert.equal(await identity.restore(),null);
});

test('a refreshed token stays private until the original actor is verified',async()=>{
  let now=0,profiles=0,reads=0;const gate=pending();
  const identity=createLiveIdentity({now:()=>now,onLost(){},fetcher:fetcher(path=>{
    if(path.endsWith('/login')||path.endsWith('/refresh'))return access('synthetic',1);
    if(path.endsWith('/users/me'))return profiles++===0?json(user()):gate.promise;
    reads++;return json({items:[],next_cursor:null});
  })});
  await identity.login({username:'a',password:'synthetic'});now=2000;
  const first=identity.requests();await tick();const second=identity.requests();await tick();
  assert.equal(reads,0);gate.resolve(json(user()));await Promise.all([first,second]);assert.equal(reads,2);
});

test('logout-all renews expired credentials before revocation and stays signed out',async()=>{
  let now=0;const calls:string[]=[];
  const identity=createLiveIdentity({now:()=>now,onLost(){},fetcher:fetcher((path,init)=>{
    calls.push(path);
    if(path.endsWith('/login'))return access('expired',1);
    if(path.endsWith('/refresh'))return access('renewed');
    if(path.endsWith('/logout-all')){assert.equal(new Headers(init.headers).get('Authorization'),'Bearer renewed');return new Response(null,{status:204});}
    return json(user());
  })});
  await identity.login({username:'a',password:'p'});now=1001;await identity.logoutAll();
  assert.deepEqual(calls.slice(-3),['/api/v1/auth/refresh','/api/v1/users/me','/api/v1/auth/logout-all']);
  assert.equal(await identity.restore(),null);
});

test('unknown logout-all is never replayed and a later login waits for revocation',async()=>{
  const gate=pending();const calls:string[]=[];
  const identity=createLiveIdentity({onLost(){},fetcher:fetcher(path=>{
    calls.push(path);
    if(path.endsWith('/login'))return access('current');
    if(path.endsWith('/logout-all'))return gate.promise;
    return json(user());
  })});
  await identity.login({username:'a',password:'p'});
  const signout=identity.logoutAll();await tick();const login=identity.login({username:'a',password:'p'});await tick();
  assert.equal(calls.filter(p=>p.endsWith('/login')).length,1);
  const rejected=assert.rejects(signout,(e:unknown)=>e instanceof ApiError&&e.outcome==='unknown');
  gate.resolve(json({error:{code:'UPSTREAM_UNAVAILABLE',message:'Unavailable'}},503));
  await rejected;assert.equal((await login).id,'a');assert.equal(calls.filter(p=>p.endsWith('/logout-all')).length,1);
});

test('a definite server expiry allows one refresh, never a loop after refresh rejection',async()=>{
  let refreshes=0,revocations=0;
  const identity=createLiveIdentity({onLost(){},fetcher:fetcher(path=>{
    if(path.endsWith('/login'))return access('locally-current');
    if(path.endsWith('/refresh')){refreshes++;return json({error:{code:'UNAUTHENTICATED',message:'Revoked'}},401);}
    if(path.endsWith('/logout-all')){revocations++;return json({error:{code:'UNAUTHENTICATED',message:'Expired'}},401);}
    return json(user());
  })});
  await identity.login({username:'a',password:'p'});
  await assert.rejects(identity.logoutAll(),(e:unknown)=>e instanceof ApiError&&e.status===401);
  assert.equal(refreshes,1);assert.equal(revocations,1);assert.equal(await identity.restore(),null);
});

test('unknown login reconciles a matching cookie actor without resubmitting credentials',async()=>{
  const calls:string[]=[];
  const identity=createLiveIdentity({onLost(){},fetcher:fetcher(path=>{
    calls.push(path);
    if(path.endsWith('/login'))return json({token_type:'bearer',expires_in:600});
    if(path.endsWith('/refresh'))return access('recovered');
    return json(user());
  })});
  await assert.rejects(identity.login({username:' A ',password:'p'}),(e:unknown)=>e instanceof ApiError&&e.outcome==='unknown');
  assert.equal((await identity.restore())?.id,'a');
  assert.deepEqual(calls,['/api/v1/auth/login','/api/v1/auth/refresh','/api/v1/users/me']);
});

test('unknown login cannot recover a prior cookie actor with a different identity',async()=>{
  const identity=createLiveIdentity({onLost(){},fetcher:fetcher(path=>{
    if(path.endsWith('/login'))throw new TypeError('response lost');
    if(path.endsWith('/refresh'))return access('previous');
    return json(user('previous'));
  })});
  await assert.rejects(identity.login({username:'new',password:'p'}));
  assert.equal(await identity.restore(),null);
  await assert.rejects(identity.createRequest('EXPORT'),(e:unknown)=>e instanceof ApiError&&e.code==='SESSION_CHANGED');
});

test('unconfirmed login cannot read or mutate a previous cookie actor before explicit reconciliation',async()=>{
  const calls:string[]=[];
  const identity=createLiveIdentity({onLost(){},fetcher:fetcher(path=>{
    calls.push(path);
    if(path.endsWith('/login'))throw new TypeError('response lost');
    return new Response(null,{status:204});
  })});
  await assert.rejects(identity.login({username:'new',password:'p'}));
  await assert.rejects(identity.requests(),(e:unknown)=>e instanceof ApiError&&e.code==='SESSION_UNCONFIRMED');
  await assert.rejects(identity.createStudent('synthetic'),(e:unknown)=>e instanceof ApiError&&e.code==='SESSION_UNCONFIRMED');
  assert.deepEqual(calls,['/api/v1/auth/login']);
  await assert.rejects(identity.logoutAll(),(e:unknown)=>e instanceof ApiError&&e.code==='SESSION_UNCONFIRMED');
  assert.deepEqual(calls,['/api/v1/auth/login','/api/v1/auth/logout']);
});

test('profile outage after accepted login is recoverable but rejected credentials stay suspended',async()=>{
  let profiles=0;
  const identity=createLiveIdentity({onLost(){},fetcher:fetcher(path=>{
    if(path.endsWith('/login')||path.endsWith('/refresh'))return access('accepted');
    if(profiles++===0)throw new TypeError('profile unavailable');
    return json(user());
  })});
  await assert.rejects(identity.login({username:'a',password:'p'}),(e:unknown)=>e instanceof ApiError&&e.outcome==='unknown');
  assert.equal((await identity.restore())?.id,'a');
  let calls=0;
  const denied=createLiveIdentity({onLost(){},fetcher:fetcher(()=>{calls++;return json({error:{code:'UNAUTHENTICATED',message:'Invalid'}},401);})});
  await assert.rejects(denied.login({username:'a',password:'p'}));assert.equal(await denied.restore(),null);assert.equal(calls,1);
});

for(const operation of ['activate','reset','acceptInvitation'] as const)test(`${operation} invalidates the actor and clears cookies before a newer login`,async()=>{
  const gate=pending();const calls:string[]=[];let losses=0;
  const identity=createLiveIdentity({onLost(){losses++;},fetcher:fetcher(path=>{
    calls.push(path);
    if(path.endsWith('/activate')||path.endsWith('/reset'))return gate.promise;
    if(path.endsWith('/login'))return access('new');
    return json(user('new'));
  })});
  const changing=operation==='activate'?identity.activate({username:'new',activation_code:'synthetic',new_password:'synthetic-password'}):identity[operation]('synthetic','synthetic-password');
  await tick();assert.equal(await identity.restore(),null);
  const login=identity.login({username:'new',password:'p'});await tick();assert.equal(calls.length,1);
  gate.resolve(new Response(null,{status:204}));await changing;assert.equal((await login).id,'new');assert.equal(losses,1);
});
