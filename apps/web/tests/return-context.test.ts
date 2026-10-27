import test from 'node:test';
import assert from 'node:assert/strict';
import { safeReturnTo, withSafeRouteQuery } from '../src/lib/navigation';
test('login return keeps allowed source page/version and Tutor draft context', () => {
 const reader='/student/classes/class-1/documents/doc-1';
 assert.equal(safeReturnTo(reader+'?page=3&version=2', ['STUDENT'], '/student'), reader+'?version=2&page=3');
 assert.equal(safeReturnTo('/student/classes/class-1/tutor?compose=new&conversationId=conv-2', ['STUDENT'], '/student'), '/student/classes/class-1/tutor?conversationId=conv-2&compose=new');
 assert.equal(withSafeRouteQuery(reader,{page:'3',version:'2',documentId:'another-doc'}),reader+'?version=2&page=3');
});
test('login return discards secret/redirect/role queries and fragments without widening route access', () => {
 assert.equal(safeReturnTo('/student/classes?token=secret&role=ADMIN&next=https:evil&search=toan#private',['STUDENT'],'/student'),'/student/classes?search=toan');
 for(const path of ['/admin/accounts?page=2','/login?next=/admin/accounts','//evil.example/path','/student/classes/../../admin/accounts','/student/classes/class%2Fsecret/documents']) assert.equal(safeReturnTo(path,['STUDENT'],'/student'),'/student');
});
