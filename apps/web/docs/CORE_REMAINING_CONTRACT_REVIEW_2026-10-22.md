# Đề xuất nối các API Core còn lại — 22/10/2026

**Trạng thái: người dùng đã duyệt ngày 22/10/2026 — “Duyệt 38 API hiện có theo đề xuất”.** Quyết định mở đúng proxy/decoder/live adapter của 38 operation dưới đây, giữ nguyên wire contract/quyền backend; không thêm endpoint hoặc nghiệp vụ. Kết quả triển khai/kiểm chứng và workspace còn thiếu dữ liệu được ghi riêng tại [báo cáo tích hợp](CORE_APPROVED_INTEGRATION_2026-10-22.md).

## Phạm vi đề nghị duyệt

Nối đúng **38 public operation đã có implementation**, request/response/status/validation theo [API matrix hiện tại](CORE_API_MATRIX_2026-10-22.md), schema từ router Core và snapshot OpenAPI. Giữ nguyên 17 operation Identity/Notifications đã chốt. Không mở health/internal cho browser, không mở register, không thêm endpoint trong quyết định này.

| Nhóm | Số operation | Request/response được đề nghị chốt |
|---|---:|---|
| Classroom | 17 | GET classes phân trang, GET class, GET memberships; tạo course/homeroom/class; PUT roster/teaching assignments; preview/sync/đổi enrollment mode; add/end/transfer membership và transfer homeroom; archive/restore. Dùng đúng UUID và DTO ClassResponse/MembershipResponse/RosterResponse/TeachingAssignmentResponse/EnrollmentPreviewResponse hiện tại |
| Social Feed/Comments | 8 | List phân trang; create/PATCH gửi `{body}` 1–10000 ký tự, không blank; response PostResponse/CommentResponse có author `{id,display_name}` và timestamps; DELETE 204. Không gán email/role tác giả từ suy đoán |
| Calendar | 4 | List phân trang, lọc `from`/`to` ISO có timezone; create `{title,description?,starts_at,ends_at}`, PATCH các field hiện tại, DELETE 204. Response CalendarEventResponse; chỉ CORE-origin được sửa, LEARNING là projection chỉ đọc |
| Administration | 9 | Staff invitation `{email,roles}` trả UserSummaryDTO, không trả raw invitation code; status PATCH 204; roles PUT trả UserSummaryDTO; audit/data-request list/detail/resolve; import preview base64 CSV/XLSX và confirm theo preview_id. Payload/response chi tiết như matrix |

## Ràng buộc khi triển khai

- Quyền/backend/current school/class/membership/assignment vẫn là nguồn quyết định. Author edit khác moderation delete; Admin xem metadata lớp không tự có quyền đọc Social hoặc chat riêng tư. Archived chặn ghi hoạt động chung; kết thúc membership không mở lại content lớp cũ.
- Chỉ mở từng path/method cụ thể, gồm PUT/DELETE cần thiết; UUID bắt buộc. Query whitelist riêng từng operation; không chuyển tùy ý user_id/action/filter. `X-Admin-Reason` chỉ enum ADMIN_INTERVENTION/POLICY_VIOLATION/USER_REQUEST tại operation yêu cầu, không lý do tự do. Không chuyển service key hoặc tin forwarded headers từ browser.
- Giữ shared session, actor/generation guard, cancellation/deadline và unknown outcome. Không tự retry mutation; không thêm generic Idempotency-Key. Cache process-local hiện có của Classroom không được coi là receipt bền vững.
- Enrollment preview dùng class_version/roster_version/add_student_ids/end_student_ids thực tế; không bịa preview_id/revision hoặc cơ chế override. Import code chỉ nhận lần disclosure đầu, replay code null không tạo lại mã.
- Status và roles là hai transaction riêng; không hiển thị như một save atomic. Staff invitation không có API resend/revoke/list; không mô phỏng các thao tác đó bằng success giả.
- Admin data-request COMPLETED không được hiển thị hoàn thành nếu server thực tế trả IN_REVIEW/POLICY_PENDING. Không tự xây retention/pháp lý hoặc executor xuất/xóa toàn bộ.
- Mapping frontend thích nghi với DTO thật. Trường UI không có dữ liệu được bỏ/hiển thị chưa hỗ trợ, không dùng fixture/đoán role/name/count. Workspace thiếu catalog/user/teacher/homeroom reads vẫn ghi rõ blocked; các read endpoint mới sẽ cần đề xuất riêng có schema/quyền/test cụ thể.

## Tiêu chí nghiệm thu

Từng lát chức năng phải có decoder/proxy/adapter tests, kiểm chứng HTTP + PostgreSQL thật và live build. Bao gồm actor đổi, 401/403/404/409/422, pagination, cross-school/class/resource, archived/revoked membership, mutation unknown và malformed response. Chỉ cập nhật readiness cho operation/workspace đã nối và được kiểm chứng; browser/SMTP không có môi trường phải ghi unverified.

Owner review khi tạo PR: Core.Classroom, Core.Social, Core.Administration/Identity, Common transport và Web. Không sửa BUSINESS_RULES, migration đã áp dụng, không commit/push/deploy tự động. Document/AI/Learning/Learner Intelligence không nằm trong quyết định wire contract này vì chưa có thiết kế API chi tiết.

## Nguồn yêu cầu chốt contract

[apps/web/AGENTS.md](../AGENTS.md) quy định: “Contract approval is required before extending service proxy/decoders.” [Skill repository](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md) quy định: “Do not turn `pending-contract` into live calls or invent API/schema/policies.” Các nhóm trên từng được đánh dấu PROPOSED trong Core API_CONTRACT. Quyết định rõ ràng của người dùng ở đầu tài liệu đã đáp ứng điều kiện này cho đúng 38 operation hiện có; không cần xin lại quyền triển khai phạm vi đó.
