# TASK-013: Administration Workflows & Core Audit Logging

- **Mã Task:** `TASK-013`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV4` (Phối hợp với `TV1`, `TV2`)
- **Module:** `services/core/app/modules/administration/`
- **Business Rules liên quan:** `F1`, `F2`, `F4`, `F7`, `K1`, `K5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#5-quyền), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#admin--internal)

---

## 1. Mục tiêu
Xây dựng các chức năng quản trị hệ thống (`Administration`), bao gồm tạo tài khoản bởi Admin (gửi lời mời đặt mật khẩu), khóa/mở khóa tài khoản, phân bổ vai trò người dùng, xử lý các yêu cầu dữ liệu cá nhân (Data Requests), và hệ thống ghi nhận sự kiện kiểm toán (`Audit Logging`) với yêu cầu ghi nhận lý do can thiệp (`X-Admin-Reason`).

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py` (hoặc tích hợp trong `common/audit.py`)
Bảng kiểm toán trong schema `core`:
- `AuditEvent`:
  - `id: UUID` (PK)
  - `actor_id: Optional[UUID]` (FK `users.id`, người thực hiện hành động, NULL nếu hệ thống)
  - `action: str` (Ví dụ: `ADMIN_LOCK_USER`, `ADMIN_ASSIGN_ROLE`, `ADMIN_INTERVENE_CLASS`, `DATA_REQUEST_PROCESSED`)
  - `target_type: str` (`USER`, `CLASS`, `DATA_REQUEST`)
  - `target_id: str`
  - `correlation_id: Optional[str]`
  - `metadata_json: dict` (Ghi lý do can thiệp, thông tin thay đổi)
  - `occurred_at: datetime` (UTC)
  - Index: `Index('idx_audit_actor_time', actor_id, occurred_at.desc())`, `Index('idx_audit_target', target_type, target_id)`
  - **Quy tắc bảo mật bất biến:** Tuyệt đối không lưu token, mật khẩu, chat riêng tư vào `metadata_json` (Rule K5, F3).

### 2.2. `schemas.py`
- `AdminCreateUserRequest`: `email: str`, `roles: list[str]` (STUDENT, LECTURER, ADMIN)
- `AdminUpdateUserStatusRequest`: `status: str` (ACTIVE, LOCKED), `reason: str`
- `AdminUpdateUserRolesRequest`: `roles: list[str]`, `reason: str`
- `AdminDataRequestResolve`: `status: str` (IN_REVIEW, COMPLETED, REJECTED), `resolution_note: str`
- `AuditEventResponse`: `id: UUID`, `actor_id: Optional[UUID]`, `action: str`, `target_type: str`, `target_id: str`, `metadata_json: dict`, `occurred_at: datetime`

### 2.3. `service.py` & Quy trình nghiệp vụ
- **Admin tạo người dùng (`admin_create_user`):**
  - Kiểm tra quyền: Chỉ tài khoản có vai trò `ADMIN`.
  - Gọi `identity.public.admin_create_user(...)`. Sinh link đặt mật khẩu một lần (OneTimeToken).
  - Ghi audit log.
- **Khóa / Mở khóa tài khoản (`set_user_status`):**
  - Cập nhật trạng thái người dùng sang `LOCKED` hoặc `ACTIVE`.
  - Khi khóa: ngay lập tức vô hiệu hóa các phiên đăng nhập hiện tại bằng cách gọi hàm thu hồi token của Identity.
  - Ghi audit log kèm lý do.
- **Quản lý vai trò (`update_user_roles`):**
  - Quy tắc an toàn: Không được phép gỡ bỏ quyền `ADMIN` của tài khoản Admin cuối cùng trong hệ thống.
  - Ghi audit log.
- **Can thiệp lớp học của Admin:**
  - Khi Admin thực hiện các thao tác quản trị trên lớp (như duyệt/xóa thành viên, đổi chủ lớp, lưu trữ lớp), yêu cầu header HTTP `X-Admin-Reason`.
  - Tự động ghi nhận `X-Admin-Reason` vào `audit_events`.
- **Xử lý yêu cầu dữ liệu cá nhân (`resolve_data_request`):**
  - Phân loại yêu cầu: `ACCESS`, `EXPORT`, `DELETE`.
  - Ghi chú giải thích lý do xử lý, cập nhật trạng thái `COMPLETED` hoặc `REJECTED` (Rule K1, F4).

### 2.4. `router.py`
Các route dưới prefix `/api/v1/admin`:
- `POST /admin/users`
- `PATCH /admin/users/{id}/status`
- `PUT /admin/users/{id}/roles`
- `GET /admin/audit-events` (Phân trang, lọc theo actor/action/thời gian)
- `GET /admin/data-requests`
- `GET/PATCH /admin/data-requests/{id}`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Chỉ tài khoản có vai trò hệ thống `ADMIN` mới được gọi các endpoint `/admin/*`. Tài khoản `LECTURER` hay `STUDENT` bị chặn `403 FORBIDDEN`.
- [ ] Khi Admin khóa một tài khoản (`LOCKED`), người dùng đó lập tức không thể đăng nhập hoặc dùng access token cũ để gọi API.
- [ ] Không thể gỡ quyền `ADMIN` của Admin duy nhất còn lại trong hệ thống (báo lỗi `400 BAD_REQUEST`).
- [ ] Mọi hành động của Admin đều sinh ra bản ghi kiểm toán tương ứng trong `audit_events`.
- [ ] Dữ liệu trong `audit_events` không bao giờ chứa thông tin bí mật hay chat riêng tư.
