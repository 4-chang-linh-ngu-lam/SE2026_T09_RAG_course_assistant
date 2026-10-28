import { createUnavailableIntelligencePort } from './intelligence-unavailable';
import { createLiveIdentitySession } from './live-identity';
import { createLiveCore } from './live-core';
import { createLiveAccounts } from './live-accounts';
import { createLiveClassroomAdminPort } from './live-classroom-admin';
import { createUnavailablePracticeAuthoringPort } from './practice-authoring-unavailable';
import { createUnavailableAssignmentPort } from './assignment-unavailable';
import { createUnavailableAssessmentPort } from './assessment-unavailable';
import type { DataAdapter } from './port';
import { ApiError } from '../api/errors';

const session = createLiveIdentitySession();
const core = createLiveCore(session);
const accounts = createLiveAccounts(session);

export const adapter: DataAdapter = {
  source: 'live',
  personalData: { async download() { throw new ApiError('UNAVAILABLE', 'Vui lòng xem hướng dẫn bàn giao trong ghi chú xử lý hoặc liên hệ nhà trường để nhận bản sao.', 503); } },
  intelligence: createUnavailableIntelligencePort(),
  classroom: createLiveClassroomAdminPort(session),
  practiceAuthoring: createUnavailablePracticeAuthoringPort(),
  accounts,
  assignment: createUnavailableAssignmentPort(),
  assessment: createUnavailableAssessmentPort(),
  identity: core.identity,
  social: core.social,
  calendar: core.calendar,
  notifications: core.notifications,
  document: {
    async previewClassSource() { throw new ApiError('UNAVAILABLE', 'Nguồn tài liệu chưa sẵn sàng. Vui lòng quay lại sau.', 503); },
    async uploadDocument() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ tải lên tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
    async uploadVersion() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ cập nhật phiên bản tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
    async retryProcessing() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ xử lý tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
    async shareDocument() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ chia sẻ tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
    async revokeShare() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ thu hồi chia sẻ tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
    async deleteDocument() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ xóa tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
    async saveNote() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ lưu ghi chú chưa sẵn sàng trên máy chủ.', 503);
    },
    async deleteNote() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ xóa ghi chú chưa sẵn sàng trên máy chủ.', 503);
    },
    async toggleBookmark() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ đánh dấu tài liệu chưa sẵn sàng trên máy chủ.', 503);
    },
  },
  tutor: {
    async updateConfig() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ cấu hình trợ lý Lumi chưa sẵn sàng trên máy chủ.', 503);
    },
    async createConversation() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ trợ lý Lumi chưa sẵn sàng trên máy chủ.', 503);
    },
    async sendMessage() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ hỏi đáp Lumi chưa sẵn sàng trên máy chủ.', 503);
    },
    async stopStreaming() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ dừng câu trả lời chưa sẵn sàng trên máy chủ.', 503);
    },
  },
  learning: {
    async startPracticeAttempt() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ bắt đầu lượt luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async checkPracticeAnswer() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ kiểm tra đáp án luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async savePracticeDraft() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ lưu bài làm luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async finishPracticeAttempt() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ hoàn tất luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async createPracticeDraft() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ khởi tạo bài luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async savePracticeEditorDraft() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ lưu bản nháp bài luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async publishPractice() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ công bố bài luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
    async reviewEditorQuestion() {
      throw new ApiError('UNAVAILABLE', 'Dịch vụ rà soát câu hỏi luyện tập chưa sẵn sàng trên máy chủ.', 503);
    },
  },
  workspace: core.workspace,
};
