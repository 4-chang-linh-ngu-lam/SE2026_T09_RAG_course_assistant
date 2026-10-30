import assert from 'node:assert/strict';
import test from 'node:test';
import { consumeOneTimeTokenLink } from '../src/lib/one-time-token-link';

test('staff email fragment fills token and removes it from the visible URL', () => {
  const result = consumeOneTimeTokenLink(
    new URL('https://lumi.example.vn/staff/invitation#token=one-time-code'),
  );

  assert.equal(result.token, 'one-time-code');
  assert.equal(result.cleanUrl, '/staff/invitation');
});

test('reset link preserves allowed query context and unrelated fragment values', () => {
  const result = consumeOneTimeTokenLink(
    new URL('https://lumi.example.vn/reset-password?next=%2Flogin&token=legacy#source=email'),
  );

  assert.equal(result.token, 'legacy');
  assert.equal(result.cleanUrl, '/reset-password?next=%2Flogin#source=email');
});

test('ordinary auth URLs remain unchanged', () => {
  const result = consumeOneTimeTokenLink(new URL('https://lumi.example.vn/login?next=%2Fstudent'));

  assert.equal(result.token, null);
  assert.equal(result.cleanUrl, '/login?next=%2Fstudent');
});
