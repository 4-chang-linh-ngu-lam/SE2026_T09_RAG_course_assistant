const ACTION_LABELS: Readonly<Record<string, string>> = {
  ADMIN_VIEW_AUDIT_EVENTS: 'Mở nhật ký quản trị',
  ADMIN_VIEW_DATA_REQUESTS: 'Xem danh sách yêu cầu dữ liệu',
  ADMIN_VIEW_DATA_REQUEST: 'Xem yêu cầu dữ liệu',
  ADMIN_IMPORT_PREVIEW_REJECTED: 'Từ chối bản xem trước danh sách',
  ADMIN_IMPORT_PREVIEW: 'Tạo bản xem trước danh sách học sinh',
  ADMIN_IMPORT_CONFIRMED: 'Xác nhận nhập danh sách học sinh',
  ADMIN_IMPORT_STATUS_READ: 'Kiểm tra trạng thái nhập danh sách',
  ADMIN_CREATE_COURSE: 'Tạo môn học',
  ADMIN_CREATE_HOMEROOM: 'Tạo lớp hành chính',
  ADMIN_UPDATE_ROSTER: 'Cập nhật danh sách lớp hành chính',
  ADMIN_TRANSFER_HOMEROOM_STUDENT: 'Chuyển học sinh sang lớp hành chính khác',
  ADMIN_CREATE_CLASS: 'Tạo lớp môn học',
  ADMIN_SET_TEACHERS: 'Cập nhật phân công giáo viên',
  ADMIN_CHANGE_ENROLLMENT_MODE: 'Thay đổi cách ghi danh học sinh',
  ADMIN_SYNC_ENROLLMENT: 'Đồng bộ danh sách lớp',
  ADMIN_ADD_STUDENT: 'Thêm học sinh vào lớp',
  ADMIN_SET_MANUAL_ROSTER: 'Cập nhật danh sách học sinh lớp',
  ADMIN_END_ENROLLMENT: 'Kết thúc ghi danh học sinh',
  ADMIN_TRANSFER_STUDENT: 'Chuyển học sinh sang lớp khác',
  ADMIN_ARCHIVE_CLASS: 'Lưu trữ lớp',
  ADMIN_RESTORE_CLASS: 'Khôi phục lớp',
  ADMIN_UPDATE_USER: 'Cập nhật tài khoản',
  ADMIN_UPDATE_USER_ROLES: 'Cập nhật vai trò tài khoản',
  ADMIN_CREATE_USER: 'Tạo tài khoản nhân sự',
  ADMIN_REISSUE_INVITATION: 'Gửi lại lời mời nhân sự',
  ADMIN_SET_USER_STATUS: 'Cập nhật trạng thái tài khoản',
  ADMIN_ASSIGN_STUDENT_USERNAME: 'Gán tên đăng nhập cho học sinh',
  ADMIN_CREATE_STUDENT: 'Cấp tài khoản học sinh',
  ADMIN_ISSUE_STUDENT_ACTIVATION_CODE: 'Cấp mã kích hoạt học sinh',
  ADMIN_ISSUE_STUDENT_RESET_CODE: 'Cấp mã khôi phục mật khẩu học sinh',
  STUDENT_ACTIVATED: 'Học sinh kích hoạt tài khoản',
  STUDENT_PASSWORD_RESET: 'Học sinh đặt lại mật khẩu',
  DATA_REQUEST_REVIEWED: 'Cập nhật yêu cầu dữ liệu',
  DATA_REQUEST_DEFERRED: 'Tạm hoãn xử lý yêu cầu dữ liệu',
  DATA_REQUEST_FULFILLED_MANUALLY: 'Ghi nhận xử lý thủ công yêu cầu dữ liệu',
  LEGACY_ASSIGN_SCHOOL: 'Gán trường cho tài khoản cũ',
  LEGACY_REVIEW_SCHOOL: 'Rà soát trường của tài khoản cũ',
  LEGACY_VERIFICATION_REQUIRED: 'Yêu cầu xác minh tài khoản cũ',
  PRODUCTION_BOOTSTRAP_ADMIN: 'Khởi tạo tài khoản quản trị cho trường thử nghiệm',
  STAGING_BOOTSTRAP_ADMIN: 'Khởi tạo tài khoản quản trị môi trường thử nghiệm',
  STAGING_BOOTSTRAP_ADMIN_EMAIL_CORRECTED: 'Cập nhật email lời mời quản trị thử nghiệm',
  DEV_SEED_COMPLETED: 'Khởi tạo dữ liệu môi trường kiểm thử',
  MODERATE_DELETE_COMMENT: 'Gỡ bình luận vi phạm',
  MODERATE_DELETE_POST: 'Gỡ bài viết vi phạm',
  CREATE: 'Tạo tài khoản học sinh',
  ASSIGN_USERNAME: 'Gán tên đăng nhập cho học sinh',
  EXISTING: 'Đối chiếu tài khoản đã có',
  ERROR: 'Ghi nhận dòng nhập cần kiểm tra',
};

const RESOURCE_LABELS: Readonly<Record<string, string>> = {
  USER: 'Tài khoản',
  STUDENT: 'Học sinh',
  DATA_REQUEST: 'Yêu cầu dữ liệu',
  IMPORT: 'Danh sách nhập',
  IMPORT_BATCH: 'Lượt nhập danh sách',
  COURSE: 'Môn học',
  HOMEROOM: 'Lớp hành chính',
  CLASS: 'Lớp môn học',
  POST: 'Bài viết',
  COMMENT: 'Bình luận',
  SCHOOL: 'Trường',
};

const REASON_LABELS: Readonly<Record<string, string>> = {
  ADMIN_INTERVENTION: 'Theo quyết định của quản trị viên',
  USER_REQUEST: 'Theo yêu cầu của người dùng',
  POLICY_VIOLATION: 'Để xử lý nội dung vi phạm chính sách',
  POLICY_PENDING: 'Chờ quy trình hoặc căn cứ được phê duyệt',
  'Không có mã lý do trong bản ghi': 'Không có ghi chú bổ sung',
};

export function auditActionLabel(action: string): string {
  return ACTION_LABELS[action] ?? 'Thao tác quản trị khác';
}

export function auditResourceLabel(resourceType: string): string {
  return RESOURCE_LABELS[resourceType] ?? 'Thông tin liên quan';
}

export function auditReasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? (/[À-ỹ]/u.test(reason) ? reason : 'Không có ghi chú bổ sung');
}
