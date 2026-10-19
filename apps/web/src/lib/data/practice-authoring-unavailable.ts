import { ApiError } from '../api/errors';
import type { PracticeAuthoringPort } from '../practice-authoring';
export function createUnavailablePracticeAuthoringPort(): PracticeAuthoringPort {
  const unavailable = async (): Promise<never> => { throw new ApiError('UNAVAILABLE', 'Chức năng soạn bài chưa sẵn sàng. Vui lòng quay lại sau.', 503); };
  return { load: unavailable, save: unavailable, review: unavailable, publish: unavailable, propose: unavailable };
}
