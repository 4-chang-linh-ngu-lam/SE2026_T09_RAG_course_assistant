# TASK-004: Identity Public Interface & Data Request Management

- **Mã Task:** `TASK-004`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Business Rules liên quan:** `K1`, `K4`, `O8`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#auth--user), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#5-luồng-phụ-thuộc-và-quy-tắc-import)

---

## 1. Mục tiêu
Thiết lập giao diện lập trình nội bộ (`public.py`) chuẩn mực để các module khác (Classroom, Administration, Notification) gọi và sử dụng thông tin Identity mà không vi phạm ranh giới kiến trúc. Đồng thời ghi nhận/xem yêu cầu truy cập, xuất hoặc xóa dữ liệu cá nhân theo baseline K1/K4/O8; không coi triển khai này là xác nhận tuân thủ pháp lý.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `public.py`
Xuất khẩu các hàm công khai ổn định (Internal Python Interface):
- `get_user_summary(user_id: UUID) -> Optional[UserSummaryDTO]`: Lấy thông tin cơ bản (id, email, status).
- `get_users_summaries(user_ids: list[UUID]) -> dict[UUID, UserSummaryDTO]`: Batch fetch để chống N+1 query.
- `verify_user_active(user_id: UUID) -> bool`: Kiểm tra người dùng có đang hoạt động và không bị khóa.
- `get_user_roles(user_id: UUID) -> list[str]`: Lấy danh sách vai trò hệ thống của người dùng.
- `check_user_is_lecturer(user_id: UUID) -> bool`: Kiểm tra quyền giảng viên toàn hệ thống.
- `admin_create_user(email: str, roles: list[str], *, actor_id: UUID, correlation_id: UUID, session=None, deliver=None) -> tuple[UserSummaryDTO, SecretStr]`: Hàm nội bộ tạo tài khoản/lời mời, không bàn giao ORM/hash hoặc mật khẩu mặc định.
- `admin_set_user_status(user_id: UUID, status: str, *, actor_id: UUID, correlation_id: UUID, session=None) -> None`: Hàm nội bộ khóa/mở tài khoản; kiểm tra Admin hiện hành, thu hồi phiên và audit cùng transaction.

Read functions hỗ trợ `session=` tùy chọn; bỏ qua thì tự mở/đóng session. Với mutation, session được cung cấp thuộc caller (caller commit/rollback); bỏ qua thì public interface tự commit. Actor phải lấy từ backend authentication, không từ body của browser. Admin invitation một lần được chấp nhận qua `/auth/password/reset`; không tạo endpoint mới ngoài API contract.

### 2.2. Quản lý Yêu cầu dữ liệu cá nhân (`Data Requests`)
- Bảng ORM `data_requests` (migration 0004, Identity sở hữu):
  - `id: UUID` (PK)
  - `user_id: UUID` (FK `users.id`)
  - `request_type: Enum` (`ACCESS`, `EXPORT`, `DELETE`)
  - `reason: Optional[str]`
  - `status: Enum` (`PENDING`, `IN_REVIEW`, `COMPLETED`, `REJECTED`)
  - `resolution_note: Optional[str]`
  - `created_at`, `updated_at: datetime` (UTC)
- Endpoint cho người dùng:
  - `GET /api/v1/users/me/data-requests`: Xem danh sách yêu cầu của bản thân (paginated).
  - `POST /api/v1/users/me/data-requests`: Gửi yêu cầu mới (`type`, `reason`; chấp nhận alias input `request_type`). Trả về `201 Created` với trạng thái `PENDING`; không tự xóa/xuất dữ liệu.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Module `administration` hoặc test bên ngoài có thể gọi `public.get_user_summary()` mà không cần import ORM model hay repository của Identity.
- [x] Sinh viên/Giảng viên có thể tạo yêu cầu `EXPORT` hoặc `DELETE` dữ liệu và xem lại trạng thái yêu cầu của chính mình.
- [x] Sinh viên A không thể xem yêu cầu dữ liệu của Sinh viên B (kiểm tra phân quyền).
- [x] Unit test cho toàn bộ hàm trong `public.py` đạt 100% line/branch coverage, không loại trừ code; CI kiểm tra ngưỡng này.

**Bằng chứng (2026-10-11):** Python 3.12.14, PostgreSQL 18 tạm; 12 unit tests public đạt 100% line/branch coverage (58 statements, 0 missing). Toàn Core `pytest -q -W error --cov=app.modules.identity.public --cov-branch --cov-fail-under=100` với `TEST_DATABASE_URL` đạt 119/119, lint đạt. Đã kiểm chứng batch một query không lấy hash, Admin authorization/audit, transaction caller rollback, invitation expiry/single-use/LOCKED, data request paging/idempotency/alias/cross-user. Migration 0004 downgrade/upgrade và `alembic check` đạt; snapshot OpenAPI cập nhật.

**Phần còn lại:** Admin HTTP/role management và xử lý/resolve/export/delete thật thuộc TASK-013; retention cụ thể cần người vận hành duyệt. Chưa kiểm chứng SMTP thật, Compose/PostgreSQL 16 hoặc CI chạy trên GitHub. Các public/shared contracts và CI cần reviewer TV1/TV4 khi mở PR. Hướng dẫn chính tại [Core README](../services/core/README.md#identity-public-interface-và-data-requests-task-004).
