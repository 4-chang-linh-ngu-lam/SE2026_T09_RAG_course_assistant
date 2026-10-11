# TASK-002: Identity Models, Repository & Core Auth Service

- **Mã Task:** `TASK-002`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Business Rules liên quan:** `F1`, `K2`, `K4`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#3-schema-logic), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#auth--user)

---

## 1. Mục tiêu
Hiện thực hóa tầng lưu trữ dữ liệu (ORM models, repository) và nghiệp vụ cốt lõi (service) của phân hệ Identity, bao gồm quản lý người dùng, vai trò, phiên xác thực, refresh token rotation và vòng đời tài khoản.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng các bảng trong schema `core`:
- `User`:
  - `id: UUID` (PK)
  - `email: str` (Unique, index, chuẩn hóa lowercase)
  - `password_hash: str` (Argon2id)
  - `status: Enum` (`PENDING_VERIFICATION`, `ACTIVE`, `LOCKED`)
  - `email_verified_at: Optional[datetime]`
  - `session_version: int` (Default: 1, dùng để thu hồi toàn bộ token phiên)
  - `created_at`, `updated_at: datetime` (UTC)
- `RoleAssignment`:
  - `id: UUID` (PK)
  - `user_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `role: Enum` (`STUDENT`, `LECTURER`, `ADMIN`)
  - Ràng buộc: `UniqueConstraint('user_id', 'role')`
- `AuthSession`:
  - `id: UUID` (PK)
  - `user_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `refresh_hash: str` (Unique, index)
  - `family_id: UUID` (Nhận diện chuỗi rotation để phát hiện tái sử dụng token)
  - `expires_at: datetime` (UTC)
  - `revoked_at: Optional[datetime]`
- `OneTimeToken`:
  - `id: UUID` (PK)
  - `user_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `purpose: Enum` (`EMAIL_VERIFICATION`, `PASSWORD_RESET`, `ADMIN_INVITATION`)
  - `token_hash: str` (Unique)
  - `expires_at: datetime`
  - `consumed_at: Optional[datetime]`

### 2.2. `schemas.py`
- Pydantic models cho input/output:
  - `RegisterRequest`: `email` (EmailStr), `password` (12..128 ký tự, đủ độ phức tạp)
  - `RegisterResponse`: `user_id`, `email`, `status`
  - `VerifyEmailRequest`: `token`
  - `LoginRequest`: `email`, `password`
  - `TokenResponse`: `access_token`, `token_type` ("bearer"), `expires_in` (900)
  - `ForgotPasswordRequest`: `email`
  - `ResetPasswordRequest`: `token`, `new_password`
  - **Lưu ý:** Tuyệt đối không bao giờ trả về `password_hash`, `refresh_hash` hay `token_hash` trong schemas.

### 2.3. `repository.py`
- Các hàm truy vấn chuyên biệt:
  - `get_by_email(email: str) -> Optional[User]`
  - `get_by_id(user_id: UUID) -> Optional[User]`
  - `create_user(user: User) -> User`
  - `get_user_roles(user_id: UUID) -> list[str]`
  - `create_session(session: AuthSession) -> AuthSession`
  - `get_session_by_refresh_hash(hash: str) -> Optional[AuthSession]`
  - `revoke_session_family(family_id: UUID) -> None`
  - `revoke_all_user_sessions(user_id: UUID) -> None`
  - `create_one_time_token(...)`, `consume_one_time_token(...)`

### 2.4. `service.py`
- **Đăng ký (Self-registration):** Tạo User trạng thái `PENDING_VERIFICATION`, gán vai trò `STUDENT`, sinh `OneTimeToken` xác minh email.
- **Xác minh Email:** Kiểm tra token, đánh dấu `consumed_at`, đổi status thành `ACTIVE`.
- **Đăng nhập:** Xác thực email/password. Từ chối nếu user chưa verify email hoặc bị `LOCKED`. Sinh Access JWT + Refresh Token (kèm family ID mới).
- **Refresh Token Rotation:** Kiểm tra refresh token. Nếu phát hiện token đã revoked trong cùng family_id $\to$ thu hồi toàn bộ family (chống tấn công trộm token). Nếu hợp lệ $\to$ revoke token cũ, sinh token mới trong cùng family.
- **Đăng xuất / Logout-all:** Đánh dấu revoked refresh token hiện tại hoặc tăng `session_version` của User để vô hiệu hóa toàn bộ access tokens đang lưu hành.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Test đăng ký thành công tạo user với role `STUDENT` và status `PENDING_VERIFICATION`.
- [ ] Test đăng nhập bị từ chối khi status là `PENDING_VERIFICATION` hoặc `LOCKED`.
- [ ] Test refresh token rotation: sau khi refresh, token cũ không thể dùng lại; nếu cố tình dùng lại token cũ sẽ kích hoạt thu hồi toàn bộ family_id.
- [ ] Test `logout_all`: tăng `session_version` và vô hiệu hóa mọi access token cũ.
- [ ] Không có query nào select thừa hoặc để lộ hash mật khẩu ra bên ngoài service.
