import {createLiveCoreAudit} from './live-core-audit';
import { createLiveCoreSession } from './live-identity';
import { createLiveNotifications } from './live-notifications';
import {createLiveCoreApi} from './live-core';
import {createLiveClassroomSocial} from './live-classroom-social';
import {createLiveDocument} from './live-document';
import { createUnavailableClassroomAdminPort } from './classroom-admin-unavailable';
import { createUnavailablePracticeAuthoringPort } from './practice-authoring-unavailable';
import { createUnavailableAccountsPort } from './accounts-unavailable';
import { createUnavailableAssignmentPort } from './assignment-unavailable';
import { createUnavailableAssessmentPort } from './assessment-unavailable';
import type { DataAdapter } from './port';
import { ApiError } from '../api/errors';

const core = createLiveCoreSession();
const notifications = createLiveNotifications(core);
const coreApi=createLiveCoreApi(core);
const classroomSocial=createLiveClassroomSocial(core,coreApi);
const documentService=createLiveDocument(core,coreApi);

export const adapter: DataAdapter = {
  core:coreApi,
  source: 'live',
  personalData: { async download() { throw new ApiError('UNAVAILABLE', 'Vui lòng xem hướng dẫn bàn giao trong ghi chú xử lý hoặc liên hệ nhà trường để nhận bản sao.', 503); } },
  intelligence: createLiveCoreAudit(core,coreApi),
  classroom: createUnavailableClassroomAdminPort(),
  practiceAuthoring: createUnavailablePracticeAuthoringPort(),
  accounts: createUnavailableAccountsPort(),
  assignment: createUnavailableAssignmentPort(),
  assessment: createUnavailableAssessmentPort(),
  identity: core.identity,
  social:classroomSocial.social,
  calendar:classroomSocial.calendar,
  notifications: notifications.port,
  document: documentService.port,
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
  workspace: {
    async load(routeId, params, signal) {
      if (routeId === 'account.notifications') return notifications.load(signal);
      if(documentService.supports(routeId))return documentService.load(routeId,params,signal);
      if(classroomSocial.supports(routeId))return classroomSocial.load(routeId,params,signal);
      // No invented wire DTOs or endpoints for uncontracted services.
      return { kind: 'unavailable', message: 'Nội dung này chưa sẵn sàng trên máy chủ. Vui lòng quay lại sau.' };
    },
  },
};
