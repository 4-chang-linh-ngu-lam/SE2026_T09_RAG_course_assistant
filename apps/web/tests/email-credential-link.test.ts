import test from 'node:test';
import assert from 'node:assert/strict';
import {readEmailCredentialLink} from '../src/lib/email-credential-link';

test('invitation fragment becomes a memory credential and disappears from navigation',()=>{
  const result=readEmailCredentialLink('https://school.example/staff/invitation#token=synthetic%2Bopaque%2Fvalue');
  assert.deepEqual(result,{token:'synthetic+opaque/value',cleanPath:'/staff/invitation'});
});
test('reset links support legacy query credentials and remove them',()=>{
  assert.deepEqual(readEmailCredentialLink('http://localhost:3100/reset-password?token=synthetic&source=email'),{token:'synthetic',cleanPath:'/reset-password?source=email'});
});
test('fragment takes precedence and both credential locations are scrubbed',()=>{
  assert.deepEqual(readEmailCredentialLink('https://school.example/staff/invitation?token=old#token=current&other=keep'),{token:'current',cleanPath:'/staff/invitation#other=keep'});
});
test('cleanup is relative and never installs a redirect from email parameters',()=>{
  assert.deepEqual(readEmailCredentialLink('https://school.example/reset-password?next=https%3A%2F%2Fother.example#token=synthetic'),{token:'synthetic',cleanPath:'/reset-password?next=https%3A%2F%2Fother.example'});
});
test('missing and oversized credentials remain empty and are removed',()=>{
  assert.deepEqual(readEmailCredentialLink('https://school.example/staff/invitation'),{token:'',cleanPath:'/staff/invitation'});
  assert.deepEqual(readEmailCredentialLink('https://school.example/reset-password#token='+'x'.repeat(257)),{token:'',cleanPath:'/reset-password'});
});
