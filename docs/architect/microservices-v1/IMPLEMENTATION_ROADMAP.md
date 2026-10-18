# Lộ trình — Core hoàn chỉnh trước

**Trạng thái:** BASELINE KẾ HOẠCH · **Ngày:** 2026-10-11. Các giai đoạn là tiêu chí để nghiệm thu, không phải đã hoàn thành.

| Giai đoạn | Phạm vi | Điều kiện chuyển |
|---|---|---|
| **G0 — Contract Core** | ERD, state machines, RBAC, API, folder ownership, mock | Nhóm review hợp đồng và phân công |
| **G1 — Core chức năng đầy đủ** | Identity/JWT, user/role, School/roster/lớp môn học, enrollment AUTO/MANUAL, Admin teaching assignment/transfer/archive, feed/comments/calendar, notification, Core admin/audit | Web → Core → DB thực hiện được các luồng, có test quyền |
| **G2 — Core tích hợp** | Compose, migration, CI, health, security, concurrency, API/contract/integration test | Demo toàn bộ Core trên môi trường sạch, có bằng chứng kiểm thử |
| **G3 — Document + AI** | File/version/grant/processing, source-bound notes/bookmarks, RAG Tutor | Quyền nguồn, thu hồi, citation/abstention được kiểm thử |
| **G4 — Learning** | Practice, Assessment, Assignment, grading, deadlines, appeal | Test deadline, attempt/version, audit, sửa điểm |
| **G5 — Learner Intelligence + MVP** | Evidence/mastery/recommendations, dashboard, báo cáo PDF/Excel và tích hợp | Kiểm tra Business Rules và Quality Attributes |

**Không chuyển G3 khi chỉ hoàn thành Core Foundation.** Notes/bookmarks gắn nguồn thuộc Document ở G3; báo cáo tổng hợp nhiều service được tích hợp G5, không loại khỏi MVP.

## Phân công G1–G2
- TV1: Identity/auth/security; TV2: Classroom/membership/permission.
- TV3: Social (feed/comments/calendar); TV4: Notification/administration/audit, CI và test tích hợp.
- Mỗi người thực hiện UI/API/test theo feature; shared files có reviewer; contract/mock cho phép làm song song.

## Thứ tự thực hiện
1. Chốt API/ERD/quyền và mock; tạo skeleton.
2. Dựng auth, database, migration, frontend shell.
3. Hoàn thiện identity/classroom public interface, triển khai social/notification/admin song song.
4. Tích hợp từng luồng, test cross-class, locked, archived, teacher assignment, enrollment sync, concurrent requests.
5. Chạy Compose từ môi trường sạch, CI, security/contract tests, lưu kết quả rồi mới sang G3.

## Checklist nghiệm thu Core

**Trạng thái backend trên `main` `2f7d70a` (2026-10-19):** Các luồng backend 001–016 đã triển khai; full Core PostgreSQL 16 đạt **342 passed, 0 skipped**. CI PR #10 đạt `core-tests`, `compose-smoke`, `web-build` trên head `bb7f88d` trước squash merge. Đo tải follow-up Core subset đạt ngưỡng backend (p95 18,79 ms), client p95 1,17 giây; đây chưa phải chứng nhận user-facing SLO/full TP-01. Checklist dưới đây vẫn là gate ký nghiệm thu Core G2: School mapping dữ liệu thật/FK, data-request policy/executor, owner review và consumer liên service còn pending. Web nghiệp vụ không nằm trong phạm vi backend đã chốt; `apps/web` build xanh không phải Web E2E.

- [ ] Admin provision/Student activate/login/refresh/logout/revoke, Admin account/roles/lock.
- [ ] Admin tạo lớp môn học gắn lớp hành chính/năm học, phân công giáo viên, nhập CSV/Excel, ghi danh AUTO/MANUAL, chuyển lớp và archive/restore; Student không tự join/leave; Lecturer không tạo lớp.
- [ ] Feed/comments/calendar/notifications và Core admin/audit end-to-end.
- [ ] OpenAPI, migration, Compose, health, CI, test quyền/tích hợp có bằng chứng.

[Core Design](core/DESIGN.md) · [Core API](core/API_CONTRACT.md) · [Quality Attributes](QUALITY_ATTRIBUTES.md).

## Điều chỉnh phạm vi sản phẩm và thứ tự ưu tiên
MVP Lumi hướng tới lớp chính khóa THCS/THPT (khối 6–12), không phải đại học hoặc lớp học thêm. Giữ 5 service và các mốc G1–G5. Trước khi hoàn thành Classroom/Core G1, cần chốt và kiểm thử metadata môn/khối/năm học/lớp hành chính, phân công giáo viên, ghi danh do Admin quản lý, không dùng mã lớp và **cấm học sinh tự rời lớp chính khóa**. Trước khi phát hành Identity cho học sinh thật, triển khai Admin provisioning + username/activation và phê duyệt chính sách bảo vệ dữ liệu người chưa thành niên. Không viết lại các task Identity đã hoàn thành chỉ vì đổi tên hiển thị; thay đổi hành vi/schema phải có task, migration, contract test riêng.


### Nghiệm thu mục tiêu theo 20 quyết định (chưa hoàn thành)
- **G0:** chốt ERD school/year/semester/homeroom/subject class, AUTO/MANUAL, teaching assignment, Student activation, action-based access, API legacy-vs-target.
- **G1:** Admin cấp tài khoản và nhập CSV/Excel có preview/confirm; username activation; Admin tạo lớp/phân công/ghi danh/sync/archive; Student không self-register/join/leave; không Lecturer tạo lớp. Tích hợp feed/calendar/notification như kế hoạch.
- **G2:** migration mới và contract/security/integration tests cho cross-school, cross-class, AUTO/MANUAL, bulk idempotency, activation expiry/replay, transfer/archive; CI/Compose.
- **G3:** tài liệu có grant và thu hồi, notes/bookmarks và chat lịch sử riêng tư, AI Tutor chỉ ở lớp hiện hành.
- **G4:** assessment draft/approval, grade proposal/approval, chuyển lớp với pending submission/attempt, lịch sử/phúc khảo.
- **G5:** analytics lịch sử và sửa điểm, yêu cầu dữ liệu Admin xử lý có audit, báo cáo PDF/Excel.
- Các dòng checklist cũ về join/approve/reject, Lecturer enrollment, owner transfer/archive và public Student registration được **thay thế** bởi baseline này; các phần code hiện có chưa được coi là hoàn tất nghiệp vụ mục tiêu.

## Backlog đồng bộ

[Danh mục task](../../../tasks/README.md) ghi hiện trạng, phần cần sửa và phụ thuộc của TASK-001–020 sau rà soát 2026-10-16. Các checklist trên tiếp tục là gate nghiệm thu; hạ tầng TASK-016 hoặc Identity đã chạy test không thay thế toàn bộ G1/G2.
