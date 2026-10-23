import test from 'node:test';
import assert from 'node:assert/strict';
import {createHttpClient} from '../src/lib/api/http';
import {ApiError} from '../src/lib/api/errors';

const metadata = {'X-Correlation-ID':'00000000-0000-4000-8000-000000000123','Retry-After':'7'};
function client(response: () => Response) {
  let calls = 0;
  return {request:createHttpClient(()=>null,(async()=>{calls++;return response();}) as typeof fetch),count:()=>calls};
}
for (const status of [401,422,429,503]) test(`non-JSON ${status} preserves status, diagnostics and mutation certainty`,async()=>{
  const http=client(()=>new Response('<html>gateway</html>',{status,headers:metadata}));
  await assert.rejects(http.request('createDataRequest',{body:{type:'EXPORT'}}),(error:unknown)=>{
    assert.ok(error instanceof ApiError);assert.equal(error.status,status);assert.equal(error.code,'INVALID_RESPONSE');
    assert.equal(error.outcome,status>=500?'unknown':'rejected');assert.equal(error.correlationId,metadata['X-Correlation-ID']);assert.equal(error.retryAfter,'7');return true;
  });
  assert.equal(http.count(),1);
});
test('successful malformed or unexpected mutation response remains unknown with correlation',async()=>{
  for(const response of [()=>new Response('',{status:201,headers:metadata}),()=>Response.json({},{status:202,headers:metadata})]){
    const http=client(response);
    await assert.rejects(http.request('createDataRequest'),(error:unknown)=>error instanceof ApiError&&error.outcome==='unknown'&&error.correlationId===metadata['X-Correlation-ID']);assert.equal(http.count(),1);
  }
});
test('malformed error envelopes do not install non-string codes or messages',async()=>{
  for(const error of [false,[],null,{code:123,message:{}},{code:'',message:42}]){
    const http=client(()=>Response.json({error},{status:422,headers:metadata}));
    await assert.rejects(http.request('createDataRequest'),(error:unknown)=>error instanceof ApiError&&error.code==='REQUEST_FAILED'&&error.outcome==='rejected'&&error.correlationId===metadata['X-Correlation-ID']);
  }
});
test('GET malformed response is rejected, preserves diagnostics and never retries',async()=>{
  const http=client(()=>new Response('bad',{status:503,headers:metadata}));
  await assert.rejects(http.request('me'),(error:unknown)=>error instanceof ApiError&&error.outcome==='rejected'&&error.status===503&&error.retryAfter==='7');assert.equal(http.count(),1);
});
