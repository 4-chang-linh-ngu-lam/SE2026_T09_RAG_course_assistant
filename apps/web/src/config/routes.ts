import type { Role } from '@/lib/domain';
export type RouteDefinition = { id: string; path: string; title: string; layout: string; allowedRoles: readonly (Role | 'public')[]; capabilityIds: readonly string[]; screenKeys: readonly string[]; fallbackParentRouteId: string | null; contextClassTabRouteId: string | null; renderClassTabs: boolean };
export const routes = [
  {
    "id": "auth.login",
    "path": "/login",
    "title": "Đăng nhập",
    "layout": "AuthLayout",
    "allowedRoles": [
      "public"
    ],
    "capabilityIds": [
      "identity"
    ],
    "screenKeys": [
      "base-cbdfa8d0"
    ],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "auth.activate",
    "path": "/activate",
    "title": "Kích hoạt học sinh",
    "layout": "AuthLayout",
    "allowedRoles": [
      "public"
    ],
    "capabilityIds": [
      "identity"
    ],
    "screenKeys": [
      "base-3d1dd2e0"
    ],
    "fallbackParentRouteId": "auth.login",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "auth.invitation",
    "path": "/staff/invitation",
    "title": "Nhận lời mời nhân sự",
    "layout": "AuthLayout",
    "allowedRoles": [
      "public"
    ],
    "capabilityIds": [
      "identity",
      "administration"
    ],
    "screenKeys": [
      "base-836f3a8c",
      "base-3ad6cef9"
    ],
    "fallbackParentRouteId": "auth.login",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "auth.recover",
    "path": "/recover",
    "title": "Khôi phục Student/Staff",
    "layout": "AuthLayout",
    "allowedRoles": [
      "public"
    ],
    "capabilityIds": [
      "identity"
    ],
    "screenKeys": [
      "base-4a626528",
      "base-cddb52d7"
    ],
    "fallbackParentRouteId": "auth.login",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "auth.reset",
    "path": "/reset-password",
    "title": "Đặt lại mật khẩu từ link nhân sự",
    "layout": "AuthLayout",
    "allowedRoles": [
      "public"
    ],
    "capabilityIds": [
      "identity"
    ],
    "screenKeys": [
      "C04c-staff-reset",
      "C04d-staff-reset-complete",
      "C04e-staff-reset-invalid"
    ],
    "fallbackParentRouteId": "auth.login",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "s.home",
    "path": "/student",
    "title": "Trang chủ học sinh",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning",
      "intelligence"
    ],
    "screenKeys": [
      "SH_C01-home",
      "SH_R01"
    ],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "s.classes",
    "path": "/student/classes",
    "title": "Lớp học của tôi",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "base-fef514df"
    ],
    "fallbackParentRouteId": "s.home",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "s.overview",
    "path": "/student/classes/:classId/overview",
    "title": "Tổng quan lớp",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "SH_C02-overview"
    ],
    "fallbackParentRouteId": "s.classes",
    "contextClassTabRouteId": "s.overview",
    "renderClassTabs": true
  },
  {
    "id": "s.feed",
    "path": "/student/classes/:classId/feed",
    "title": "Bảng tin học sinh",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "social"
    ],
    "screenKeys": [
      "SH_F01-feed"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.feed",
    "renderClassTabs": true
  },
  {
    "id": "s.documents",
    "path": "/student/classes/:classId/documents",
    "title": "Tài liệu lớp",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "document"
    ],
    "screenKeys": [
      "base-e93071d9"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.documents",
    "renderClassTabs": true
  },
  {
    "id": "s.reader",
    "path": "/student/classes/:classId/documents/:documentId",
    "title": "Đọc nguồn và ghi chú",
    "layout": "ReaderLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "document"
    ],
    "screenKeys": [
      "base-41d6544a",
      "base-ae547183",
      "SH_R02"
    ],
    "fallbackParentRouteId": "s.documents",
    "contextClassTabRouteId": "s.documents",
    "renderClassTabs": false
  },
  {
    "id": "s.tutor",
    "path": "/student/classes/:classId/tutor",
    "title": "Hỏi Lumi",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "document",
      "tutor",
      "learning"
    ],
    "screenKeys": [
      "base-5d1ab390",
      "AI01",
      "AI02",
      "AI03",
      "AI04",
      "AI05",
      "SH_R03"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.tutor",
    "renderClassTabs": true
  },
  {
    "id": "s.practice",
    "path": "/student/classes/:classId/practice",
    "title": "Danh sách luyện tập",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "CP01-variant"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.practice",
    "renderClassTabs": true
  },
  {
    "id": "s.practiceAttempt",
    "path": "/student/classes/:classId/practice/:practiceId/attempts/:attemptId",
    "title": "Lượt luyện tập",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning",
      "tutor"
    ],
    "screenKeys": [
      "LS01"
    ],
    "fallbackParentRouteId": "s.practice",
    "contextClassTabRouteId": "s.practice",
    "renderClassTabs": false
  },
  {
    "id": "s.practiceResult",
    "path": "/student/classes/:classId/practice/:practiceId/attempts/:attemptId/result",
    "title": "Kết quả luyện tập",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "base-2ff2012c"
    ],
    "fallbackParentRouteId": "s.practice",
    "contextClassTabRouteId": "s.practice",
    "renderClassTabs": true
  },
  {
    "id": "s.assessments",
    "path": "/student/classes/:classId/assessments",
    "title": "Danh sách kiểm tra",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "CP03-variant"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.assessments",
    "renderClassTabs": true
  },
  {
    "id": "s.assessment",
    "path": "/student/classes/:classId/assessments/:assessmentId",
    "title": "Thông tin và điều kiện kiểm tra",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "CP04-variant",
      "CP04-ready"
    ],
    "fallbackParentRouteId": "s.assessments",
    "contextClassTabRouteId": "s.assessments",
    "renderClassTabs": true
  },
  {
    "id": "s.examAttempt",
    "path": "/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId",
    "title": "Làm kiểm tra chính thức",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LS02",
      "LS03",
      "SH_R04"
    ],
    "fallbackParentRouteId": "s.assessment",
    "contextClassTabRouteId": "s.assessments",
    "renderClassTabs": false
  },
  {
    "id": "s.receipt",
    "path": "/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId/receipt",
    "title": "Biên nhận kiểm tra",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "learning"
    ],
    "screenKeys": [
      "LS04",
      "LS04-manual-receipt"
    ],
    "fallbackParentRouteId": "s.assessment",
    "contextClassTabRouteId": "s.assessments",
    "renderClassTabs": false
  },
  {
    "id": "s.examResult",
    "path": "/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId/result",
    "title": "Kết quả và phản hồi điểm",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LS05"
    ],
    "fallbackParentRouteId": "s.assessments",
    "contextClassTabRouteId": "s.assessments",
    "renderClassTabs": true
  },
  {
    "id": "s.assignments",
    "path": "/student/classes/:classId/assignments",
    "title": "Danh sách bài tập",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LS07"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.assignments",
    "renderClassTabs": true
  },
  {
    "id": "s.assignment",
    "path": "/student/classes/:classId/assignments/:assignmentId",
    "title": "Chi tiết/nộp/kết quả bài tập",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LS08",
      "LS09",
      "SH_R05"
    ],
    "fallbackParentRouteId": "s.assignments",
    "contextClassTabRouteId": "s.assignments",
    "renderClassTabs": true
  },
  {
    "id": "s.calendar",
    "path": "/student/classes/:classId/calendar",
    "title": "Lịch của một lớp",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "calendar",
      "learning"
    ],
    "screenKeys": [
      "SH_C03-calendar"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.calendar",
    "renderClassTabs": true
  },
  {
    "id": "s.progress",
    "path": "/student/classes/:classId/progress",
    "title": "Tiến độ cá nhân trong lớp",
    "layout": "StudentClassLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "learning",
      "intelligence"
    ],
    "screenKeys": [
      "S06a"
    ],
    "fallbackParentRouteId": "s.overview",
    "contextClassTabRouteId": "s.progress",
    "renderClassTabs": true
  },
  {
    "id": "s.notes",
    "path": "/student/notes",
    "title": "Ghi chú & Đã lưu",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "document"
    ],
    "screenKeys": [
      "S07"
    ],
    "fallbackParentRouteId": "s.home",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "s.history",
    "path": "/student/history/classes/:classId",
    "title": "Lịch sử lớp cũ của chính mình",
    "layout": "HistoryLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "classroom",
      "document",
      "learning",
      "tutor"
    ],
    "screenKeys": [
      "S08a",
      "S08b"
    ],
    "fallbackParentRouteId": "s.classes",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "s.historyResult",
    "path": "/student/history/results/:resultId",
    "title": "Kết quả và lịch sử điểm được giữ",
    "layout": "HistoryLayout",
    "allowedRoles": [
      "STUDENT"
    ],
    "capabilityIds": [
      "learning"
    ],
    "screenKeys": [
      "LS06"
    ],
    "fallbackParentRouteId": "s.history",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "account.profile",
    "path": "/account",
    "title": "Hồ sơ và bảo mật",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT",
      "LECTURER",
      "ADMIN"
    ],
    "capabilityIds": [
      "identity"
    ],
    "screenKeys": [
      "SH_C04-profile"
    ],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "account.requests",
    "path": "/account/data-requests",
    "title": "Yêu cầu dữ liệu của tôi",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT",
      "LECTURER",
      "ADMIN"
    ],
    "capabilityIds": [
      "personalData"
    ],
    "screenKeys": [
      "base-1772afa8"
    ],
    "fallbackParentRouteId": "account.profile",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "account.notifications",
    "path": "/notifications",
    "title": "Thông báo của tôi",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT",
      "LECTURER",
      "ADMIN"
    ],
    "capabilityIds": [
      "notification"
    ],
    "screenKeys": [
      "base-7c9ef0e9"
    ],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "account.calendar",
    "path": "/calendar",
    "title": "Lịch tổng hợp các lớp còn quyền",
    "layout": "AppLayout",
    "allowedRoles": [
      "STUDENT",
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "calendar",
      "learning"
    ],
    "screenKeys": [],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "t.home",
    "path": "/teacher",
    "title": "Tổng quan giảng dạy",
    "layout": "AppLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "social",
      "calendar"
    ],
    "screenKeys": [
      "base-37714fad"
    ],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "t.classes",
    "path": "/teacher/classes",
    "title": "Lớp phụ trách",
    "layout": "AppLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [],
    "fallbackParentRouteId": "t.home",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "t.overview",
    "path": "/teacher/classes/:classId/overview",
    "title": "Tổng quan lớp giáo viên",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning",
      "intelligence"
    ],
    "screenKeys": [],
    "fallbackParentRouteId": "t.classes",
    "contextClassTabRouteId": "t.overview",
    "renderClassTabs": true
  },
  {
    "id": "t.feed",
    "path": "/teacher/classes/:classId/feed",
    "title": "Bảng tin giáo viên",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "social"
    ],
    "screenKeys": [
      "base-d77da8b0"
    ],
    "fallbackParentRouteId": "t.overview",
    "contextClassTabRouteId": "t.feed",
    "renderClassTabs": true
  },
  {
    "id": "t.calendar",
    "path": "/teacher/classes/:classId/calendar",
    "title": "Lịch lớp giáo viên",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "calendar",
      "learning"
    ],
    "screenKeys": [
      "SH_C05-teacher-calendar"
    ],
    "fallbackParentRouteId": "t.overview",
    "contextClassTabRouteId": "t.calendar",
    "renderClassTabs": true
  },
  {
    "id": "t.documents",
    "path": "/teacher/classes/:classId/documents",
    "title": "Tài liệu được chia sẻ theo lớp",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "document"
    ],
    "screenKeys": [
      "D07"
    ],
    "fallbackParentRouteId": "t.overview",
    "contextClassTabRouteId": "t.documents",
    "renderClassTabs": true
  },
  {
    "id": "t.tutor",
    "path": "/teacher/classes/:classId/tutor",
    "title": "Hướng dẫn Lumi theo lớp",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "tutor",
      "document"
    ],
    "screenKeys": [
      "D08"
    ],
    "fallbackParentRouteId": "t.overview",
    "contextClassTabRouteId": "t.tutor",
    "renderClassTabs": true
  },
  {
    "id": "t.activities",
    "path": "/teacher/classes/:classId/activities",
    "title": "Hoạt động học tập",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT01"
    ],
    "fallbackParentRouteId": "t.overview",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": true
  },
  {
    "id": "t.practiceEditor",
    "path": "/teacher/classes/:classId/practice/:practiceId/edit",
    "title": "Soạn câu hỏi luyện tập",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning",
      "document"
    ],
    "screenKeys": [
      "LT02"
    ],
    "fallbackParentRouteId": "t.activities",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": false
  },
  {
    "id": "t.assessmentEditor",
    "path": "/teacher/classes/:classId/assessments/:assessmentId/edit",
    "title": "Cấu hình kiểm tra",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT03"
    ],
    "fallbackParentRouteId": "t.activities",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": true
  },
  {
    "id": "t.assessmentApproval",
    "path": "/teacher/classes/:classId/assessments/:assessmentId/review",
    "title": "Duyệt đề và phiên bản",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT04"
    ],
    "fallbackParentRouteId": "t.activities",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": true
  },
  {
    "id": "t.assignmentEditor",
    "path": "/teacher/classes/:classId/assignments/:assignmentId/edit",
    "title": "Soạn bài tập",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT05"
    ],
    "fallbackParentRouteId": "t.activities",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": true
  },
  {
    "id": "t.gradingQueue",
    "path": "/teacher/classes/:classId/grading",
    "title": "Hàng chờ chấm theo phân công",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT06"
    ],
    "fallbackParentRouteId": "t.activities",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": true
  },
  {
    "id": "t.assignmentGrading",
    "path": "/teacher/classes/:classId/assignments/:assignmentId/submissions/:submissionId/grade",
    "title": "Chấm bài tập",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT07"
    ],
    "fallbackParentRouteId": "t.gradingQueue",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": false
  },
  {
    "id": "t.examGrading",
    "path": "/teacher/classes/:classId/assessments/:assessmentId/attempts/:attemptId/grade",
    "title": "Chấm câu chủ quan",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT08"
    ],
    "fallbackParentRouteId": "t.gradingQueue",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": false
  },
  {
    "id": "t.correction",
    "path": "/teacher/classes/:classId/appeals/:appealId",
    "title": "Xem xét và đề xuất sửa điểm",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT09",
      "SH_R06"
    ],
    "fallbackParentRouteId": "t.gradingQueue",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": false
  },
  {
    "id": "t.correctionApproval",
    "path": "/teacher/classes/:classId/grade-proposals/:proposalId/review",
    "title": "Duyệt đề xuất sửa điểm",
    "layout": "FocusedTaskLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "learning"
    ],
    "screenKeys": [
      "LT10"
    ],
    "fallbackParentRouteId": "t.gradingQueue",
    "contextClassTabRouteId": "t.activities",
    "renderClassTabs": false
  },
  {
    "id": "t.analytics",
    "path": "/teacher/classes/:classId/analytics",
    "title": "Thống kê lớp",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "intelligence",
      "learning"
    ],
    "screenKeys": [
      "T12a"
    ],
    "fallbackParentRouteId": "t.overview",
    "contextClassTabRouteId": "t.analytics",
    "renderClassTabs": true
  },
  {
    "id": "t.studentAnalytics",
    "path": "/teacher/classes/:classId/analytics/students/:studentId",
    "title": "Tiến độ học sinh trong lớp",
    "layout": "TeacherClassLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "classroom",
      "intelligence",
      "learning"
    ],
    "screenKeys": [
      "T12b"
    ],
    "fallbackParentRouteId": "t.analytics",
    "contextClassTabRouteId": "t.analytics",
    "renderClassTabs": true
  },
  {
    "id": "t.library",
    "path": "/teacher/library",
    "title": "Thư viện cá nhân",
    "layout": "AppLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "document"
    ],
    "screenKeys": [
      "D01",
      "D02"
    ],
    "fallbackParentRouteId": "t.home",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "t.libraryDocument",
    "path": "/teacher/library/:documentId",
    "title": "Tài liệu nguồn và phiên bản",
    "layout": "AppLayout",
    "allowedRoles": [
      "LECTURER"
    ],
    "capabilityIds": [
      "document"
    ],
    "screenKeys": [
      "D03",
      "D04",
      "D05",
      "D06"
    ],
    "fallbackParentRouteId": "t.library",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.accounts",
    "path": "/admin/accounts",
    "title": "Danh sách tài khoản",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "administration",
      "studentProvisioning"
    ],
    "screenKeys": [
      "base-e9a4475b"
    ],
    "fallbackParentRouteId": null,
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.account",
    "path": "/admin/accounts/:userId",
    "title": "Vai trò và trạng thái nhân sự",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "administration"
    ],
    "screenKeys": [
      "base-7ee52a4b"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.legacy",
    "path": "/admin/accounts/legacy",
    "title": "Chuẩn hóa Student legacy",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "administration"
    ],
    "screenKeys": [
      "base-fe6d95ed"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.newStudent",
    "path": "/admin/accounts/students/new",
    "title": "Cấp học sinh và bàn giao mã",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "studentProvisioning"
    ],
    "screenKeys": [
      "base-ffc6e022",
      "base-f0c48fcb"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.staffInvite",
    "path": "/admin/accounts/staff/invitations",
    "title": "Mời và theo dõi nhân sự",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "administration"
    ],
    "screenKeys": [
      "base-e2b87c7f"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.importNew",
    "path": "/admin/imports/new",
    "title": "Chọn tệp nhập học sinh",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "bulkImport"
    ],
    "screenKeys": [
      "A04-import-start"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.import",
    "path": "/admin/imports/:importId",
    "title": "Kiểm tra/preview/kết quả nhập",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "bulkImport"
    ],
    "screenKeys": [
      "base-aa0546a2",
      "base-afaa2419",
      "base-42a4e687",
      "SH_R07"
    ],
    "fallbackParentRouteId": "a.importNew",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.catalog",
    "path": "/admin/catalog",
    "title": "Danh mục học vụ",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "base-097de5a7"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.homerooms",
    "path": "/admin/homerooms",
    "title": "Danh sách lớp hành chính",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.homeroom",
    "path": "/admin/homerooms/:homeroomId",
    "title": "Roster và chuyển lớp hành chính",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "base-22aae3e9"
    ],
    "fallbackParentRouteId": "a.homerooms",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.classes",
    "path": "/admin/classes",
    "title": "Danh sách lớp môn học",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "A06b-class-list"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.newClass",
    "path": "/admin/classes/new",
    "title": "Tạo lớp môn học",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "A07b-class-create"
    ],
    "fallbackParentRouteId": "a.classes",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.classSettings",
    "path": "/admin/classes/:classId/settings",
    "title": "Cấu hình lớp/phân công",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "base-35c54045"
    ],
    "fallbackParentRouteId": "a.classes",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.enrollment",
    "path": "/admin/classes/:classId/enrollment",
    "title": "AUTO/MANUAL và tác động",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "base-c1d2d4dd",
      "base-afa3945e"
    ],
    "fallbackParentRouteId": "a.classSettings",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.lifecycle",
    "path": "/admin/classes/:classId/lifecycle",
    "title": "Lưu trữ/khôi phục lớp",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "classroom"
    ],
    "screenKeys": [
      "base-a58b17f3"
    ],
    "fallbackParentRouteId": "a.classSettings",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.dataRequests",
    "path": "/admin/data-requests",
    "title": "Tiếp nhận yêu cầu dữ liệu",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "administration"
    ],
    "screenKeys": [
      "base-75f0224f"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.audit",
    "path": "/admin/audit",
    "title": "Nhật ký hệ thống",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "administration"
    ],
    "screenKeys": [
      "base-d692dd94"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.reports",
    "path": "/admin/reports",
    "title": "Báo cáo tổng hợp",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "intelligence",
      "administration"
    ],
    "screenKeys": [
      "A12a"
    ],
    "fallbackParentRouteId": "a.accounts",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  },
  {
    "id": "a.exports",
    "path": "/admin/reports/exports",
    "title": "Theo dõi xuất báo cáo",
    "layout": "AppLayout",
    "allowedRoles": [
      "ADMIN"
    ],
    "capabilityIds": [
      "intelligence",
      "administration"
    ],
    "screenKeys": [
      "A12b"
    ],
    "fallbackParentRouteId": "a.reports",
    "contextClassTabRouteId": null,
    "renderClassTabs": false
  }
] as const satisfies readonly RouteDefinition[];
export type RouteId = typeof routes[number]['id'];
export function getRoute(id: string): RouteDefinition { const route = routes.find(r => r.id === id); if (!route) throw new Error('Unknown route'); return route; }
export function routeHref(id: string, params: Record<string, string> = {}) {
  const route = getRoute(id);
  if (route.path.match(/:(\w+)/g)?.some(key => !params[key.slice(1)])) return null;
  return route.path.replace(/:(\w+)/g, (_, key: string) => encodeURIComponent(params[key]));
}
export function homeFor(roles: readonly Role[]) { return roles.includes('ADMIN') ? '/admin/accounts' : roles.includes('LECTURER') ? '/teacher' : '/student'; }
