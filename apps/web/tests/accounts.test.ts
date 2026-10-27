import test from 'node:test';
import assert from 'node:assert/strict';
import { createPreviewAccountStore } from '../dev/mocks/accounts';
import { parseCsv, fromRows, importErrorsCsv, normalizeImportCells } from '../src/features/accounts/import-file';
import type { User } from '../src/lib/domain';
import { ApiError } from '../src/lib/api/errors';
const seeds: User[] = [
  { id: 'admin', email: 'admin@school.example', username: null, school_id: 'school', display_name: 'Admin', roles: ['ADMIN'], status: 'ACTIVE' },
  { id: 'student', email: null, username: 'existing', school_id: 'school', display_name: 'Student', roles: ['STUDENT'], status: 'ACTIVE' },
  { id: 'teacher', email: 'teacher@school.example', username: null, school_id: 'school', display_name: 'Teacher', roles: ['LECTURER'], status: 'ACTIVE' },
  { id: 'foreign', email: null, username: 'foreign', school_id: 'elsewhere', display_name: 'Foreign', roles: ['STUDENT'], status: 'ACTIVE' },
  { id: 'legacy', email: 'legacy@school.example', username: null, school_id: 'school', display_name: 'Legacy', roles: ['STUDENT'], status: 'LOCKED' },
];
const rejected = (code: string) => (error: unknown) => error instanceof ApiError && error.code === code;
const password = 'New-password-12345';
test('preview provision -> activation -> exact login; replay, wrong purpose and expired codes fail', () => {
  let now = 1_700_000_000_000; const store = createPreviewAccountStore(seeds, () => now);
  const created = store.createStudent('admin', ' 001245 ', 'Nguyễn An, Bình');
  assert.equal(created.student.username, '001245'); assert.equal(store.user(created.student.id)?.status, 'PENDING_VERIFICATION');
  assert.throws(() => store.login({ username: '001245', password }), rejected('UNAUTHENTICATED'));
  assert.throws(() => store.reset(created.code, password), rejected('VALIDATION_ERROR'));
  store.activate({ username: '001245', activation_code: created.code, new_password: password });
  assert.equal(store.login({ username: '001245', password }).id, created.student.id);
  assert.throws(() => store.login({ username: '001245', password: 'other-password' }), rejected('UNAUTHENTICATED'));
  assert.throws(() => store.activate({ username: '001245', activation_code: created.code, new_password: password }), rejected('VALIDATION_ERROR'));
  assert.throws(() => store.issueCode('admin', created.student.id, false), rejected('VALIDATION_ERROR'));
  const reset = store.issueCode('admin', created.student.id, true); now += 61 * 60 * 1000;
  assert.throws(() => store.reset(reset.code, password), rejected('VALIDATION_ERROR'));
});
test('reissued and locked codes cannot activate; legacy migration preserves ID and locked state', () => {
  const store = createPreviewAccountStore(seeds); const created = store.createStudent('admin', 'pending');
  const replacement = store.issueCode('admin', created.student.id, false);
  assert.throws(() => store.activate({ username: 'pending', activation_code: created.code, new_password: password }), rejected('VALIDATION_ERROR'));
  const revision = store.workspace('admin', 'a.account', { userId: created.student.id }).account!.revision;
  store.updateAccount('admin', { userId: created.student.id, revision, roles: ['STUDENT'], status: 'LOCKED', reason: 'Kiểm tra' });
  assert.throws(() => store.activate({ username: 'pending', activation_code: replacement.code, new_password: password }), rejected('VALIDATION_ERROR'));
  assert.throws(() => store.issueCode('admin', created.student.id, true), rejected('VALIDATION_ERROR'));
  const legacy = store.workspace('admin', 'a.account', { userId: 'legacy' }).account!;
  const converted = store.assignLegacyUsername('admin', { userId: legacy.id, revision: legacy.revision, username: 'legacy.name' });
  assert.equal(converted.id, legacy.id); assert.equal(converted.email, legacy.email); assert.equal(converted.status, 'LOCKED');
});
test('every admin method enforces current actor + school; last administrator and stale version protected', () => {
  const store = createPreviewAccountStore(seeds);
  assert.throws(() => store.workspace('teacher', 'a.accounts', {}), rejected('FORBIDDEN'));
  assert.throws(() => store.workspace('student', 'a.accounts', {}), rejected('FORBIDDEN'));
  assert.throws(() => store.issueCode('admin', 'foreign', true), rejected('NOT_FOUND'));
  assert.throws(() => store.createStudent('teacher', 'x'), rejected('FORBIDDEN'));
  assert.throws(() => store.updateAccount('admin', { userId: 'admin', revision: 1, roles: ['LECTURER'], status: 'ACTIVE', reason: 'Change' }), rejected('CONFLICT'));
  store.updateAccount('admin', { userId: 'student', revision: 1, roles: ['STUDENT'], status: 'LOCKED', reason: 'Change' });
  assert.throws(() => store.login({ username: 'existing', password }), rejected('UNAUTHENTICATED'));
  assert.throws(() => store.updateAccount('admin', { userId: 'student', revision: 1, roles: ['STUDENT'], status: 'ACTIVE', reason: 'Change' }), rejected('CONFLICT'));
  store.updateProfile('teacher', 'Tên mới'); assert.equal(store.login({ email: 'teacher@school.example', password }).display_name, 'Tên mới');
});
test('staff invitations have distinct purpose, reissue invalidates old and cannot unlock locked user', () => {
  const store = createPreviewAccountStore(seeds);
  const first = store.inviteStaff('admin', { email: 'new@school.example', displayName: 'New teacher', roles: ['LECTURER'] });
  const second = store.resendInvitation('admin', first.invitation.id);
  assert.throws(() => store.acceptInvitation(first.code, password), rejected('VALIDATION_ERROR'));
  store.acceptInvitation(second.code, password);
  assert.equal(store.login({ email: 'new@school.example', password }).id, first.invitation.userId);
  assert.throws(() => store.acceptInvitation(second.code, password), rejected('VALIDATION_ERROR'));
  const locked = store.inviteStaff('admin', { email: 'locked@school.example', displayName: 'Locked', roles: ['ADMIN'] });
  store.updateAccount('admin', { userId: locked.invitation.userId, revision: 1, roles: ['ADMIN'], status: 'LOCKED', reason: 'Lock' });
  assert.throws(() => store.acceptInvitation(locked.code, password), rejected('VALIDATION_ERROR'));
  assert.throws(() => store.resendInvitation('admin', locked.invitation.id), rejected('CONFLICT'));
});
test('CSV preserves BOM, CRLF, quoted commas, escaped quotes, embedded newline and source lines', () => {
  const file = parseCsv('\uFEFFusername,display_name\r\n001245,"Nguyễn An, Bình"\r\n\r\nsecond,"Tên ""đặc biệt""\nDòng hai"\r\n', 'students.csv');
  assert.deepEqual(file.headers, ['username', 'display_name']); assert.equal(file.rows.length, 2);
  assert.equal(file.rows[0].cells[0], '001245'); assert.equal(file.rows[0].cells[1], 'Nguyễn An, Bình');
  assert.equal(file.rows[1].rowNumber, 4); assert.equal(file.rows[1].cells[1], 'Tên "đặc biệt"\nDòng hai');
  assert.throws(() => parseCsv('username,name\nx,"unclosed', 'bad.csv'), /Chưa đóng/);
  assert.throws(() => parseCsv('username,name\nx,"closed"extra', 'bad.csv'), /sau dấu nháy/);
  assert.throws(() => parseCsv('username,username\nx,y', 'bad.csv'), /bị trùng/);
});
test('import validates selected rows, rejects numeric identifiers, binds preview to revision and reconciles exactly once', () => {
  const store = createPreviewAccountStore(seeds); const file = fromRows([
    { rowNumber: 1, cells: ['username', 'name'] }, { rowNumber: 2, cells: ['001245', 'Nguyễn An, Bình'] },
    { rowNumber: 3, cells: ['second', 'Học sinh thứ hai'] }, { rowNumber: 4, cells: ['001245', 'Trùng'] },
    { rowNumber: 5, cells: [123, 'Số bị mất 0'] }, { rowNumber: 6, cells: ['existing', 'Đã có'] },
  ], 'students.xlsx');
  const preview = store.previewImport('admin', { file, mapping: { username: 0, displayName: 1 } });
  assert.equal(preview.rows.length, 5); assert.equal(preview.rows.filter(row => row.status === 'VALID').length, 1);
  assert.equal(preview.rejectedCount, 4); assert.ok(preview.rows[3].errors.some(error => error.includes('ô văn bản')));
  const before = store.allUsers().length;
  const result = store.confirmImport('admin', { importId: preview.id, revision: preview.revision, reason: 'Approved roster' });
  assert.equal(result.createdCount, 1); assert.equal(store.allUsers().length, before + 1);
  assert.equal(store.confirmImport('admin', { importId: preview.id, revision: preview.revision, reason: 'Repeat' }).createdCount, 1);
  assert.equal(store.reconcileImport('admin', preview.id).status, 'COMPLETED'); assert.equal(store.allUsers().length, before + 1);
  assert.equal(store.user(result.rows.find(row => row.status === 'CREATED')!.userId!)?.status, 'PENDING_VERIFICATION');
  assert.throws(() => store.reconcileImport('teacher', preview.id), rejected('FORBIDDEN'));
  const next = store.previewImport('admin', { file: parseCsv('username,name\nthird,Third', 'next.csv'), mapping: { username: 0, displayName: 1 } });
  store.createStudent('admin', 'intervening');
  assert.throws(() => store.confirmImport('admin', { importId: next.id, revision: next.revision, reason: 'Approve' }), rejected('CONFLICT'));
});
test('error CSV is an actual quoted file and defuses spreadsheet formulas', () => {
  const csv = importErrorsCsv([{ rowNumber: 2, username: '=cmd()', displayName: 'A,"B"', errors: ['Một, hai'] }]);
  assert.ok(csv.includes('"\'=cmd()"')); assert.ok(csv.includes('"A,""B"""')); assert.equal(parseCsv(csv, 'errors.csv').rows.length, 1);
});

// A real ZIP/XML workbook, parsed by the installed XLSX reader (not a renamed CSV).
test('real XLSX parses its two rows and retains text identifier leading zeroes', async () => {
  const { readSheet } = await import('read-excel-file/node');
  const rows = await readSheet(Buffer.from('UEsDBBQAAAAIAMYAU11bma6u5QAAAAsCAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbK2RvVLDMBCEX0WjNhOdk4KCsZ0i0AYKXuCQz7HG+hudEszbIzuBggnQUN1Iu3vfalTvJmfFmRKb4Bu5UZXctfXLeyQWRfHcyCHneA/AeiCHrEIkX5Q+JIe5HNMRIuoRjwTbqroDHXwmn9d53iHb+oF6PNksHqdyfaEksizF/mKcWY3EGK3RmIsOZ999o6yvBFWSi4cHE3lVDBJuEmblZ8A191SenUxH4hlTPqArLpgsvIU0voYwqt+X3GgZ+t5o6oI+uRJRHBNhxwNRdlYtUzk0fvU3fzEzLGPzz0W+9n/2gOW72w9QSwMEFAAAAAgAxgBTXUuDozqWAAAABQEAAAsAAABfcmVscy8ucmVsc43PPQ7CMAwF4KtEPkDdMjCgpl1YuiIuEFL3R23iyAlQbk9GihgY/fz0Wa7bza3qQRJn9hqqooS2qS+0mpSDOM0hqtzwUcOUUjghRjuRM7HgQD5vBhZnUh5lxGDsYkbCQ1keUT4N2Juq6zVI11egrq9A/9g8DLOlM9u7I59+nPhqZNnISEnDtuKTZbkxL0VGAZsadw82b1BLAwQUAAAACADGAFNdof7wYaEAAAD7AAAADwAAAHhsL3dvcmtib29rLnhtbI2PPQ6DMAyFrxL5AAQ6dEAhLF2Ye4KUmCaCJMgObY/fCMreyT9P77Of6j9hES8k9il20FQ19Fq9E82PlGZRxMgduJzXVkoeHQbDVVoxFmVKFEwuIz0lr4TGskPMYZGXur7KYHyEg9DSP4w0TX7EWxq3gDEfEMLF5PIaO78yaLVf4F8V0QTs4J43WwwMYt8OtuQAQa0vDQ22AamVPI3yzKa/UEsDBBQAAAAIAMYAU11tNul0mgAAAAYBAAAaAAAAeGwvX3JlbHMvd29ya2Jvb2sueG1sLnJlbHONzzsOwjAMBuCrRD5A3TIwoKZdWFgRF4hSt6naPBSb1+2JGBCVGJgs/7Y+y23/8Ku6UeY5Bg1NVUPftWdajZSA3ZxYlY3AGpxIOiCydeQNVzFRKJMxZm+ktHnCZOxiJsJdXe8xfxuwNdVp0JBPQwPq8kz0jx3HcbZ0jPbqKciPE3iPeWFHJAU1eSLR8IkY36WpigrYtbj5sHsBUEsDBBQAAAAIAMYAU12xCmfaIAEAAKUCAAAYAAAAeGwvd29ya3NoZWV0cy9zaGVldDEueG1slZIxTsQwEEWvYrmGOMkCQivHq10hREXDUlAhKxkSi2QcbO8uOQAnoaDhBKGg4CS5CU6EIiQipFS2/3jevGL46rkqyR6MVRoTGgUhJYCpzhTmCb3dXh6fU2KdxEyWGiGhDVi6EvygzaMtABzx/WgTWjhXLxmzaQGVtIGuAX3lQZtKOv80ObO1AZkNTVXJ4jA8Y5VUSAUfsgvppOBGH4jxHj5N+8s6osQlVGGpEG6c8bmygg9jl7aWqVfyXAtmD1Ts/ImyAs6c4Kz/yNIf0GYWKFO2LmVz/xfGvOGoGY+a8Rz6kwzCMIqnLGdxrvNd0328IFnjEdl8vWPxj+tidF3MmdGLnpxOqc7CbE3XviG56tpXRe669hOnVNmvTWDjiolvUEsBAhQAFAAAAAgAxgBTXVuZrq7lAAAACwIAABMAAAAAAAAAAAAAAIABAAAAAFtDb250ZW50X1R5cGVzXS54bWxQSwECFAAUAAAACADGAFNdS4OjOpYAAAAFAQAACwAAAAAAAAAAAAAAgAEWAQAAX3JlbHMvLnJlbHNQSwECFAAUAAAACADGAFNdof7wYaEAAAD7AAAADwAAAAAAAAAAAAAAgAHVAQAAeGwvd29ya2Jvb2sueG1sUEsBAhQAFAAAAAgAxgBTXW026XSaAAAABgEAABoAAAAAAAAAAAAAAIABowIAAHhsL19yZWxzL3dvcmtib29rLnhtbC5yZWxzUEsBAhQAFAAAAAgAxgBTXbEKZ9ogAQAApQIAABgAAAAAAAAAAAAAAIABdQMAAHhsL3dvcmtzaGVldHMvc2hlZXQxLnhtbFBLBQYAAAAABQAFAEUBAADLBAAAAAA=', 'base64'));
  const file = fromRows(rows.map((cells, index) => ({ rowNumber: index + 1, cells: normalizeImportCells(cells) })), 'two-students.xlsx');
  assert.equal(file.rows.length, 2);
  assert.ok(file.rows.some(row => row.cells[0] === '001245'));
  assert.ok(file.rows.some(row => row.cells.includes('Nguyễn An, Bình')));
});

test('hybrid Student/staff uses staff credential and remains manageable without Student activation', () => {
  const hybrid: User = { id: 'hybrid', email: 'hybrid@school.example', username: null, school_id: 'school', display_name: 'Hybrid staff', roles: ['STUDENT', 'LECTURER'], status: 'ACTIVE' };
  const store = createPreviewAccountStore([...seeds, hybrid]);
  assert.equal(store.login({ email: 'hybrid@school.example', password }).id, hybrid.id);
  assert.equal(store.workspace('admin', 'a.account', { userId: hybrid.id }).account?.legacy, false);
  store.updateAccount('admin', { userId: hybrid.id, revision: 1, roles: ['STUDENT', 'LECTURER'], status: 'LOCKED', reason: 'Verified intervention' });
  assert.throws(() => store.login({ email: 'hybrid@school.example', password }), rejected('UNAUTHENTICATED'));
  assert.throws(() => store.issueCode('admin', hybrid.id, true), rejected('VALIDATION_ERROR'));
});
