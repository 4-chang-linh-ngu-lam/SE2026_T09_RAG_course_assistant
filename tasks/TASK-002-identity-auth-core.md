# TASK-002: Identity Models, Repository & Core Auth Service

- **Mã Task:** `TASK-002`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Business Rules liên quan:** `F1`, `K2`, `K4`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Student provisioning/activation/recovery và migration 0006–0007 đã có trong workspace; phần email Student/self-registration cũ chỉ là lịch sử, không phải onboarding được phát hành.

**Cần sửa/bổ sung:**
- Mô tả model/schema theo code hiện tại: email nullable, username unique/lowercase, school_id, activated_at; token purpose Student tách staff. Login nhận đúng một username/email, không dùng điều kiện email_verified chung cho mọi Student.
- Giữ chuyển đổi legacy có chủ đích: Admin cùng trường gán username, giữ UUID/hash/dữ liệu, thu hồi phiên/token cũ; pending cần activation, LOCKED không tự mở. Không backfill ngẫu nhiên hoặc bật lại email login Student.
- Để TASK-013 điều phối import/role/data-request workflows qua public interface; Identity sở hữu user/token, Classroom sở hữu School/roster. PR #33 gắn import preview cache với user/school/session và không tái dùng cache chứa mã một lần qua phiên khác.
- Hoàn thiện mapping School theo TASK-005/014 và quy trình xác minh recovery được người vận hành duyệt; `identity_verified=true` chỉ là xác nhận của Admin.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TASK-013/014 kiểm thử chuyển dữ liệu cũ có mapping thật được duyệt, giữ ID/hash/trạng thái và không cấp quyền chéo trường.
- [x] Chạy lại Identity/Core suite và migration drift checks trên PostgreSQL 16 trong GitHub CI, PR #33 head `b8c9a6d` (360 passed, 0 skipped).

**Kiểm chứng hiện hành (2026-10-29):** Identity scenarios thuộc Core CI PostgreSQL 16 trên PR #33 head `b8c9a6d` đạt trong bộ 360 test; migration drift gate xanh. Đây là evidence của PR branch, không chứng minh Gmail SMTP thật, legacy School mapping hoặc production onboarding. Xem [tasks/README](README.md).

---

## 1. Mục tiêu

**Trạng thái Lumi (2026-10-14):** phần email/self-registration bên dưới là lịch sử. Public register bị chặn; migration 0006 thêm username/email nullable/school_id/activated_at, 0007 thêm Student activation/reset purposes. Đã triển khai Admin provision, kích hoạt mã 24 giờ cấu hình được, username login, refresh không cần email và Admin recovery sau xác minh; Student không dùng email login/verify/reset. Chuyển legacy chỉ qua Admin gán username, giữ ID/hash/dữ liệu, thu hồi phiên/token cũ, audit. Thiết kế chi tiết và phạm vi chưa triển khai (School mapping/bulk import) theo API Contract/Core README.
Hiện thực hóa tầng lưu trữ dữ liệu (ORM models, repository) và nghiệp vụ cốt lõi (service) của phân hệ Identity, bao gồm quản lý người dùng, vai trò, phiên xác thực, refresh token rotation và vòng đời tài khoản.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng các bảng trong schema `core`:
- `User`:
  - `id: UUID` (PK)
  - `email: Optional[str]` (unique/lowercase; Student mới không cần email)
  - `username: Optional[str]` (unique/lowercase cho Student), `school_id: Optional[UUID]` (mapping/FK theo TASK-005/014)
  - `activated_at: Optional[datetime]`
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
  - `purpose: Enum` (`EMAIL_VERIFICATION`, `PASSWORD_RESET`, `ADMIN_INVITATION` cho staff; `STUDENT_ACTIVATION`, `STUDENT_PASSWORD_RESET` cho Student)
  - `token_hash: str` (Unique)
  - `expires_at: datetime`
  - `consumed_at: Optional[datetime]`

### 2.2. `schemas.py`
- Pydantic models cho input/output:
  - `RegisterRequest` (legacy route chỉ trả 403): `email` (EmailStr), `password` (12..128 ký tự theo API contract; chính sách độ phức tạp chi tiết chưa được chốt, không tự thêm quy tắc ký tự).
  - `RegisterResponse` (schema legacy nội bộ, không dùng làm kết quả HTTP đăng ký thành công): `user_id`, `email`, `status`
  - `VerifyEmailRequest`: `token`
  - `LoginRequest`: đúng một `username`/`email` và `password`
  - Student provision/issue-code/activate và DTO theo API Contract hiện hành; không tự đổi schema đã có
  - `TokenResponse`: `access_token`, `token_type` ("bearer"), `expires_in` (900)
  - `ForgotPasswordRequest`: `email`
  - `ResetPasswordRequest`: `token`, `new_password`
  - **Lưu ý:** Tuyệt đối không bao giờ trả về `password_hash`, `refresh_hash` hay `token_hash` trong schemas.

### 2.3. `repository.py`
- Các hàm truy vấn chuyên biệt:
  - `get_by_email(email: str) -> Optional[User]`, `get_by_username(username: str) -> Optional[User]`
  - `get_by_id(user_id: UUID) -> Optional[User]`
  - `create_user(user: User) -> User`
  - `get_user_roles(user_id: UUID) -> list[str]`
  - `create_session(session: AuthSession) -> AuthSession`
  - `get_session_by_refresh_hash(hash: str) -> Optional[AuthSession]`
  - `revoke_session_family(family_id: UUID) -> None`
  - `revoke_all_user_sessions(user_id: UUID) -> None`
  - `create_one_time_token(...)`, `consume_one_time_token(...)`

### 2.4. `service.py`
- **Đăng ký legacy:** logic nội bộ cũ được giữ để tương thích/test dữ liệu lịch sử; không export hoặc dùng onboarding. HTTP register hợp lệ trả 403.
- **Student:** Admin cùng trường provision pending, học sinh activate bằng mã một lần/đặt mật khẩu, Admin xác minh để cấp mã recovery; dùng purpose riêng không SMTP.
- **Xác minh Email staff:** kiểm tra purpose/hạn/single-use/status; token email không kích hoạt Student hoặc mở LOCKED.
- **Đăng nhập:** Student thuần dùng username và activated_at/school hợp lệ; staff dùng email đã verify, staff role ưu tiên trên tài khoản legacy đa role. Chặn pending/LOCKED, sinh Access JWT + refresh family mới.
- **Refresh Token Rotation:** Kiểm tra refresh token. Nếu phát hiện token đã revoked trong cùng family_id $\to$ thu hồi toàn bộ family (chống tấn công trộm token). Nếu hợp lệ $\to$ revoke token cũ, sinh token mới trong cùng family.
- **Đăng xuất / Logout-all:** Đánh dấu revoked refresh token hiện tại hoặc tăng `session_version` của User để vô hiệu hóa toàn bộ access tokens đang lưu hành.

---

## 3. Tiêu chí nghiệm thu lịch sử (email legacy)

**Nghiệm thu Lumi bổ sung:** provision/activation/reset không email, mã đúng purpose/hạn/single-use; chuyển legacy giữ ID/hash và thu hồi phiên; Student email auth bị chặn, staff email giữ hoạt động; concurrency không trùng username hoặc sử dụng mã hai lần. Các ca này đã chạy trong bộ 153 test PostgreSQL 18 tạm (2026-10-14); xem Core README. Schema/migration mới chưa áp dụng DB demo.
- [x] Test đăng ký thành công tạo user với role `STUDENT` và status `PENDING_VERIFICATION`.
- [x] Test đăng nhập bị từ chối khi status là `PENDING_VERIFICATION` hoặc `LOCKED`.
- [x] Test refresh token rotation: sau khi refresh, token cũ không thể dùng lại; nếu cố tình dùng lại token cũ sẽ kích hoạt thu hồi toàn bộ family_id.
- [x] Test `logout_all`: tăng `session_version` và vô hiệu hóa mọi access token cũ.
- [x] Query lấy quyền hiện hành chỉ select ID/status/version/role, không select hash; DTO response không chứa hash. Query xác thực chỉ dùng model sở hữu bởi Identity.

**Bằng chứng lịch sử (2026-10-11):** Python 3.12.14, PostgreSQL 18 tạm; identity tests và migration 0003 checks đạt. Evidence PostgreSQL 16 mới nhất được ghi ở mục kiểm chứng hiện hành.

**Phạm vi tiếp theo:** TASK-003 đã triển khai router, cookie/CSRF/rate limit và SMTP adapter (test bằng bộ gửi giả, chưa gửi email thật). TASK-004 mở rộng public workflows/data requests; TASK-013 kiểm tra quyền/audit thao tác Admin. Chưa kiểm chứng Compose/PostgreSQL 16. Hướng dẫn gọi service, cấu hình expiry và transaction tại [Core README](../services/core/README.md#identity-auth-core-task-002).
