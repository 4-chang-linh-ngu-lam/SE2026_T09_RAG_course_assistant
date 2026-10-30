import assert from 'node:assert/strict';
import test from 'node:test';
import { auditActionLabel, auditReasonLabel, auditResourceLabel } from '../src/lib/audit-copy';

test('audit display labels explain common Admin actions in Vietnamese', () => {
  assert.equal(auditActionLabel('ADMIN_TRANSFER_STUDENT'), 'Chuyển học sinh sang lớp khác');
  assert.equal(auditActionLabel('DATA_REQUEST_DEFERRED'), 'Tạm hoãn xử lý yêu cầu dữ liệu');
  assert.equal(auditActionLabel('UNKNOWN_ACTION'), 'Thao tác quản trị khác');
});

test('audit resource and reason labels do not expose internal codes', () => {
  assert.equal(auditResourceLabel('DATA_REQUEST'), 'Yêu cầu dữ liệu');
  assert.equal(auditResourceLabel('UNKNOWN_RESOURCE'), 'Thông tin liên quan');
  assert.equal(auditReasonLabel('USER_REQUEST'), 'Theo yêu cầu của người dùng');
  assert.equal(auditReasonLabel('POLICY_PENDING'), 'Chờ quy trình hoặc căn cứ được phê duyệt');
  assert.equal(auditReasonLabel('UNKNOWN_REASON'), 'Không có ghi chú bổ sung');
});
