# TASK-004: Identity Public Interface & Data Request Management

- **Mã Task:** `TASK-004`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Business Rules liên quan:** `K1`, `K4`, `O8`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#5-luồng-phụ-thuộc-và-quy-tắc-import)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Public interface an toàn, ba helper Student và ACCESS/EXPORT/CORRECTION/DELETE đã có; Administration xử lý kết quả yêu cầu còn thiếu.

**Cần sửa/bổ sung:**
- Consumer dùng chữ ký/DTO tại Core README, gồm `admin_create_student`, `admin_issue_student_code`, `admin_assign_student_username`; `admin_create_user` chỉ mời staff. Không import ORM/repository hoặc serialize SecretStr ra ngoài luồng giao mã đã chốt.
- TASK-013 hiện dùng Identity public operations cho user/role/status, staff invitation, Student import và data-request review; chỉ thêm helper mới khi có consumer/contract cụ thể, không query bảng Identity trực tiếp.
- Giữ transaction/audit do owner quản lý, không audit trùng; summary/role/verify_active không thay thế school/resource permission.
- Data request chỉ tiếp nhận/xem yêu cầu; thao tác correction/export/delete thực tế và retention thuộc workflow xác minh, không tự động cascade/xóa liên service.

**Phụ thuộc và nghiệm thu bổ sung:**
- Public contracts và Administration consumers đã được triển khai; owner review TV1/TV4/shared còn chờ ghi nhận.
- [x] Public interface 100% line/branch coverage gate chạy trong GitHub CI; coverage này không thay thế nghiệm thu Classroom/Administration.
- [ ] Fulfillment ACCESS/EXPORT/CORRECTION/DELETE và retention tiếp tục fail-safe/chờ policy-executor theo issue #15; School mapping theo issue #13.

**Kiểm chứng hiện hành (2026-10-29):** PR #33 head `b8c9a6d` chạy PostgreSQL 16 Core CI đạt 360 passed/0 skipped và public interface 100% coverage gate xanh. Đây là branch evidence, không chứng minh đã xuất/xóa dữ liệu hoặc chốt policy. Xem [tasks/README](README.md).

---

## 1. Mục tiêu

**Cập nhật Lumi (2026-10-14):** DTO/profile có username/school_id và email nullable; lookup lấy school từ DB, Admin helpers fail closed khi thiếu/khác trường. Thêm `admin_create_student`, `admin_issue_student_code`, `admin_assign_student_username` và StudentCode DTO chứa SecretStr; authorization/audit/caller-owned transaction được giữ. `admin_create_user` chỉ dùng email invitation staff, không nhận STUDENT. Migration 0005 thêm CORRECTION (thủ công); không tự backfill trường/chuyển tài khoản cũ. Contract/chữ ký tại Core README; bulk CSV/Excel và quản lý School vẫn thuộc workflow tiếp theo.
Thiết lập giao diện lập trình nội bộ (`public.py`) chuẩn mực để các module khác (Classroom, Administration, Notification) gọi và sử dụng thông tin Identity mà không vi phạm ranh giới kiến trúc. Đồng thời ghi nhận/xem yêu cầu truy cập, xuất, chỉnh sửa hoặc xóa dữ liệu cá nhân theo baseline K1/K4/O8; không coi triển khai này là xác nhận tuân thủ pháp lý.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `public.py`
Xuất khẩu các hàm công khai ổn định (Internal Python Interface):
- `get_user_summary(user_id: UUID) -> Optional[UserSummaryDTO]`: Lấy thông tin cơ bản (id, email nullable, username, school_id, display_name nullable, status).
- `get_users_summaries(user_ids: list[UUID]) -> dict[UUID, UserSummaryDTO]`: Batch fetch để chống N+1 query.
  Consumer Social chỉ dùng `id`/`display_name` khi dựng author response; không đưa email/username đăng nhập ra feed. DTO trả `display_name` từ DB trong cùng một query; trường này có thể null cho tài khoản cũ/chưa đặt tên.
- `verify_user_active(user_id: UUID) -> bool`: Kiểm tra người dùng có đang hoạt động và không bị khóa.
- `get_user_roles(user_id: UUID) -> list[str]`: Lấy danh sách vai trò hệ thống của người dùng.
- `check_user_is_lecturer(user_id: UUID) -> bool`: Kiểm tra quyền giảng viên toàn hệ thống.
- `admin_create_user(email: str, roles: list[str], *, actor_id: UUID, correlation_id: UUID, session=None, reason_code=None) -> tuple[UserSummaryDTO, TokenDelivery]`: Tạo user và durable invitation trong Identity transaction; TokenDelivery chỉ là handoff nội bộ, không bàn giao ORM/hash hoặc mật khẩu mặc định.
- `admin_reissue_user_invitation(user_id: UUID, *, actor_id: UUID, correlation_id: UUID, session=None, reason_code=None) -> tuple[UserSummaryDTO, TokenDelivery]`: Chỉ Admin cùng trường cấp lại invitation cho staff đang pending; ghi audit và vô hiệu token trước.
- `attempt_token_delivery(token_id: UUID, deliver: Callable[[TokenDelivery], None], *, session=None) -> str`: Gửi một delivery đến hạn; lỗi SMTP 503 giữ nguyên token để worker retry.
- `admin_set_user_status(user_id: UUID, status: str, *, actor_id: UUID, correlation_id: UUID, session=None) -> None`: Hàm nội bộ khóa/mở tài khoản; kiểm tra Admin hiện hành, thu hồi phiên và audit cùng transaction.

Read functions hỗ trợ `session=` tùy chọn; bỏ qua thì tự mở/đóng session. Mutation nhận session caller hoặc tự commit khi không cung cấp. Actor lấy từ backend authentication, không từ body browser. Staff invitation dùng `/auth/password/reset`; Student activation/reset dùng purpose riêng, không SMTP. Credential email có bảng trạng thái riêng, lưu token hash; mã được tái tạo bằng HMAC domain-separated từ SECRET_KEY và không đi qua Notification outbox. Các route Student đã cập nhật API Contract cùng OpenAPI; consumer không import Identity models/repository hoặc ghi audit trùng.

### 2.2. Quản lý Yêu cầu dữ liệu cá nhân (`Data Requests`)
- Bảng ORM `data_requests` (migration 0004, Identity sở hữu):
  - `id: UUID` (PK)
  - `user_id: UUID` (FK `users.id`)
  - `request_type: Enum` (`ACCESS`, `EXPORT`, `CORRECTION`, `DELETE`; CORRECTION bổ sung bằng migration 0005)
  - `reason: Optional[str]`
  - `status: Enum` (`PENDING`, `IN_REVIEW`, `COMPLETED`, `REJECTED`)
  - `resolution_note: Optional[str]`
  - `created_at`, `updated_at: datetime` (UTC)
- Endpoint cho người dùng:
  - `GET /api/v1/users/me/data-requests`: Xem danh sách yêu cầu của bản thân (paginated).
  - `POST /api/v1/users/me/data-requests`: Gửi yêu cầu mới (`type`, `reason`; chấp nhận alias input `request_type`). Trả về `201 Created` với trạng thái `PENDING`; không tự xóa/xuất dữ liệu.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)

**Bằng chứng Lumi bổ sung (2026-10-14):** public helpers Student có role/school checks, DTO/SecretStr an toàn và transaction rollback; DTO email null, CORRECTION và ownership được kiểm thử; toàn Core 153 test đạt, public line/branch coverage 100%. Bulk import, mapping trường và Admin resolution/export/delete thực tế không nằm trong nghiệm thu này.
- [x] Module `administration` hoặc test bên ngoài có thể gọi `public.get_user_summary()` mà không cần import ORM model hay repository của Identity.
- [x] Sinh viên/Giảng viên có thể tạo yêu cầu `EXPORT` hoặc `DELETE` dữ liệu và xem lại trạng thái yêu cầu của chính mình.
- [x] Sinh viên A không thể xem yêu cầu dữ liệu của Sinh viên B (kiểm tra phân quyền).
- [x] Unit test cho toàn bộ hàm trong `public.py` đạt 100% line/branch coverage, không loại trừ code; CI kiểm tra ngưỡng này.

**Bằng chứng lịch sử (2026-10-11):** Python 3.12.14, PostgreSQL 18 tạm; public helpers khi đó đạt 100% line/branch coverage. Evidence PostgreSQL 16 mới nhất được ghi ở mục kiểm chứng hiện hành.

**Phần còn lại:** Admin HTTP/role management và Student import được TASK-013 tích hợp qua Identity public helpers. Real data correction/export/delete, retention và SMTP provider chưa nghiệm thu; School mapping legacy cần owner duyệt. Hướng dẫn chính tại [Core README](../services/core/README.md#identity-public-interface-và-data-requests-task-004).
