import { ApiError } from '../api/errors';
import type { AssignmentPort } from '../assignment';
export function createUnavailableAssignmentPort(): AssignmentPort {
  const unavailable = async (): Promise<never> => { throw new ApiError('CAPABILITY_UNAVAILABLE', 'Chức năng bài tập và chấm bài đang chờ kết nối dịch vụ. Nội dung và kết quả sẽ hiển thị khi có dữ liệu được xác nhận.', 503); };
  return { listCalendarEvents: unavailable, listTeacherActivities: unavailable, createDraft: unavailable, setRecipients: unavailable, load: unavailable, upload: unavailable, submit: unavailable, reconcile: unavailable, readFile: unavailable, saveDraft: unavailable, grade: unavailable, gradeHint: unavailable, appeal: unavailable, propose: unavailable, decide: unavailable };
}
