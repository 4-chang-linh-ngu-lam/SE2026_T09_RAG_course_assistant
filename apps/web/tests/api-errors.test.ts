import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError, errorMessage } from '../src/lib/api/errors';

test('technical API codes are shown as clear Vietnamese messages', () => {
  assert.equal(
    errorMessage(new ApiError('SERVICE_UNAVAILABLE', 'SERVICE_UNAVAILABLE', 503)),
    'Dịch vụ đang tạm thời gián đoạn. Vui lòng thử lại sau.',
  );
  assert.equal(
    errorMessage(new ApiError('CONFLICT', 'CONFLICT', 409)),
    'Dữ liệu vừa thay đổi hoặc yêu cầu không còn phù hợp. Vui lòng tải lại rồi thử lại.',
  );
});

test('specific Vietnamese guidance and unknown-outcome safeguards are preserved', () => {
  assert.equal(
    errorMessage(new ApiError('CONFLICT', 'Danh sách lớp đã thay đổi. Hãy xem trước lại.', 409)),
    'Danh sách lớp đã thay đổi. Hãy xem trước lại.',
  );
  assert.equal(
    errorMessage(new ApiError('TIMEOUT', 'TIMEOUT', 0, 'unknown')),
    'Chưa xác định được kết quả. Hãy kiểm tra trạng thái trước khi gửi lại.',
  );
});

test('technical codes embedded in otherwise readable errors are hidden', () => {
  assert.equal(
    errorMessage(new ApiError('CONFLICT', 'CONFLICT: Lớp đã thay đổi.', 409)),
    'Dữ liệu vừa thay đổi hoặc yêu cầu không còn phù hợp. Vui lòng tải lại rồi thử lại.',
  );
  assert.equal(
    errorMessage(new ApiError('CONFLICT', 'Lỗi 4b1b435c-7b39-4b7c-8c75-e1e07cab0172.', 409)),
    'Dữ liệu vừa thay đổi hoặc yêu cầu không còn phù hợp. Vui lòng tải lại rồi thử lại.',
  );
});
