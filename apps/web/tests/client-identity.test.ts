import test from 'node:test';
import assert from 'node:assert/strict';
import type {IncomingMessage} from 'node:http';
import {attestClientRequest,signClientContext,verifyClientContext,CLIENT_CONTEXT_HEADER} from '../config/client-identity.mjs';
import {createCoreProxy} from '../src/lib/api/proxy';
const secret='test-only-proxy-key-'+ 'x'.repeat(32);
const path='/api/v1/auth/login';
test('socket attestation overwrites spoofed context and forwarded IP headers',()=>{
  const req={url:path,method:'POST',headers:{[CLIENT_CONTEXT_HEADER]:'forged','x-forwarded-for':'198.51.100.8','x-real-ip':'198.51.100.9'},socket:{remoteAddress:'::ffff:192.0.2.1'}} as unknown as IncomingMessage;
  attestClientRequest(req,secret,100000);
  assert.equal(req.headers['x-forwarded-for'],undefined);assert.equal(req.headers['x-real-ip'],undefined);
  assert.equal(verifyClientContext(req.headers[CLIENT_CONTEXT_HEADER],'POST',path,secret,100000),true);
  const claim=JSON.parse(Buffer.from(String(req.headers[CLIENT_CONTEXT_HEADER]).split('.')[0],'base64url').toString());
  assert.equal(claim.ip,'192.0.2.1');
});
test('attestation rejects tampering, wrong method/path/key and stale/future metadata',()=>{
  const value=signClientContext('2001:db8::1','POST',path,secret,100000);
  assert.equal(verifyClientContext(value,'POST',path,secret,100000),true);
  for(const [signed,method,target,key,now]of [[value+'x','POST',path,secret,100000],[value,'GET',path,secret,100000],[value,'POST','/api/v1/auth/refresh',secret,100000],[value,'POST',path,'y'.repeat(32),100000],[value,'POST',path,secret,131000],[value,'POST',path,secret,69000]] as const)assert.equal(verifyClientContext(signed,method,target,key,now),false);
  assert.throws(()=>signClientContext('not-an-ip','POST',path,secret));
  assert.throws(()=>signClientContext('127.0.0.1','POST',path,'short'));
});
test('strict proxy blocks missing/forged attestations and forwards only verified server metadata',async()=>{
  let forwarded:Headers|undefined,calls=0;
  const proxy=createCoreProxy(()=> 'http://core:8000',(async(_url,init)=>{calls++;forwarded=new Headers(init?.headers);return Response.json({});}) as typeof fetch,()=> 'http://localhost:3000',()=>secret);
  const make=(context?:string)=>new Request('http://localhost:3000'+path,{method:'POST',headers:{Origin:'http://localhost:3000',...(context?{[CLIENT_CONTEXT_HEADER]:context}:{}),'X-Service-Key':'untrusted','X-Forwarded-For':'untrusted'},body:'{}'});
  for(const context of [undefined,'forged'])assert.equal((await proxy(make(context),['auth','login'])).status,403);
  const signed=signClientContext('192.0.2.1','POST',path,secret);
  assert.equal((await proxy(make(signed),['auth','login'])).status,200);assert.equal(calls,1);
  assert.equal(forwarded!.get(CLIENT_CONTEXT_HEADER),signed);assert.equal(forwarded!.has('X-Service-Key'),false);assert.equal(forwarded!.has('X-Forwarded-For'),false);
  const missing=createCoreProxy(()=> 'http://core:8000',fetch,()=> 'http://localhost:3000',()=>undefined);
  assert.equal((await missing(make(signed),['auth','login'])).status,503);
});
test('all proxy failures have a valid matching correlation ID, without reflecting invalid input',async()=>{
  const proxy=createCoreProxy(()=>undefined);
  for(const input of [undefined,'bad-id','00000000-0000-4000-8000-000000000123']){
    const response=await proxy(new Request('http://localhost:3000/api/v1/classes',{headers:input?{'X-Correlation-ID':input}:{}}),['classes']);
    const body=await response.json();const id=response.headers.get('X-Correlation-ID');
    assert.match(id!,/^[0-9a-f-]{36}$/i);assert.equal(body.error.correlation_id,id);assert.equal(response.headers.get('Cache-Control'),'no-store');
    if(input&&input!=='bad-id')assert.equal(id,input);
  }
});
