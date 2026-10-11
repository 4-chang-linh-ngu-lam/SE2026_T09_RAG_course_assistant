# TASK-004: Identity Public Interface & Data Request Management

- **Mã Task:** `TASK-004`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Business Rules liên quan:** `K1`, `K4`, `O8`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#auth--user), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#5-luồng-phụ-thuộc-và-quy-tắc-import)

---

## 1. Mục tiêu
Thiết lập giao diện lập trình nội bộ (`public.py`) chuẩn mực để các module khác (Classroom, Administration, Notification) gọi và sử dụng thông tin Identity mà không vi phạm ranh giới kiến trúc. Đồng thời xây dựng tính năng người dùng yêu cầu truy cập, xuất hoặc xóa dữ liệu cá nhân theo quy định GDPR/quyền riêng tư.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `public.py`
Xuất khẩu các hàm công khai ổn định (Internal Python Interface):
- `get_user_summary(user_id: UUID) -> Optional[UserSummaryDTO]`: Lấy thông tin cơ bản (id, email, status).
- `get_users_summaries(user_ids: list[UUID]) -> dict[UUID, UserSummaryDTO]`: Batch fetch để chống N+1 query.
- `verify_user_active(user_id: UUID) -> bool`: Kiểm tra người dùng có đang hoạt động và không bị khóa.
- `get_user_roles(user_id: UUID) -> list[str]`: Lấy danh sách vai trò hệ thống của người dùng.
- `check_user_is_lecturer(user_id: UUID) -> bool`: Kiểm tra quyền giảng viên toàn hệ thống.
- `admin_create_user(email: str, roles: list[str]) -> tuple[User, str]`: Hàm nội bộ để `administration` gọi khi Admin tạo tài khoản.
- `admin_set_user_status(user_id: UUID, status: str) -> None`: Hàm nội bộ để Admin khóa/mở khóa tài khoản.

### 2.2. Quản lý Yêu cầu dữ liệu cá nhân (`Data Requests`)
- Bảng ORM `data_requests`:
  - `id: UUID` (PK)
  - `user_id: UUID` (FK `users.id`)
  - `request_type: Enum` (`ACCESS`, `EXPORT`, `DELETE`)
  - `reason: Optional[str]`
  - `status: Enum` (`PENDING`, `IN_REVIEW`, `COMPLETED`, `REJECTED`)
  - `resolution_note: Optional[str]`
  - `created_at`, `updated_at: datetime` (UTC)
- Endpoint cho người dùng:
  - `GET /api/v1/users/me/data-requests`: Xem danh sách yêu cầu của bản thân (paginated).
  - `POST /api/v1/users/me/data-requests`: Gửi yêu cầu mới (`request_type`, `reason`). Trả về `201 Created`.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Module `administration` hoặc test bên ngoài có thể gọi `public.get_user_summary()` mà không cần import ORM model hay repository của Identity.
- [ ] Sinh viên/Giảng viên có thể tạo yêu cầu `EXPORT` hoặc `DELETE` dữ liệu và xem lại trạng thái yêu cầu của chính mình.
- [ ] Sinh viên A không thể xem yêu cầu dữ liệu của Sinh viên B (kiểm tra phân quyền).
- [ ] Unit test cho toàn bộ hàm trong `public.py` đạt 100% độ bao phủ.
