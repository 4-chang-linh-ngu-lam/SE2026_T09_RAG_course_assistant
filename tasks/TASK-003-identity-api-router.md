# TASK-003: Identity API Router & Rate Limiting

- **Mã Task:** `TASK-003`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Business Rules liên quan:** `F1`, `K2`, `K4`, `K5`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md), [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng tại ngày 2026-10-16:** Router auth/profile, Student create/issue-code/activate và OpenAPI snapshot đã có; các Admin API còn lại chưa triển khai ở thời điểm đó. TASK-013 sau này đã bổ sung Admin routes.

**Cần sửa/bổ sung:**
- Lấy danh sách endpoint/schema từ Core API Contract và OpenAPI hiện tại; thêm đầy đủ username/school_id/email nullable vào mô tả profile. Không triển khai lại register trả 201 hoặc quên route Student đã có.
- Giữ create/issue-code/activate trả no-store, từ chối Idempotency-Key trước mutation; cache auth không được vượt quyền/phiên hiện hành. Staff SMTP và Student activation là hai luồng riêng.
- Dùng limiter/idempotency hiện có, một process; không tự thêm slowapi/Redis. Nếu cần nhiều worker hoặc import bền vững, thiết kế backend chia sẻ và hợp đồng retry riêng trước khi mở rộng.
- Khi TASK-013 bổ sung router Admin, thống nhất ownership/đăng ký bootstrap để không trùng hai endpoint Student hiện do Identity phục vụ.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] Contract test bao phủ đúng một identifier, register 403, no-store/no-cache mã, current-role/school checks, activation/reset replay và cookie/CSRF.
- [ ] TASK-013/016 tích hợp API thật; SMTP staff cần kiểm thử gửi thật riêng khi có cấu hình, không suy ra từ callback giả hoặc demo Student.

---

## 1. Mục tiêu

**Cập nhật Lumi (2026-10-14):** `/auth/register` deprecated, trả 403 trước DB/SMTP/cache. Đã có `/auth/activate`, login đúng một username/email, `/admin/students` và `/admin/students/{user_id}/activation-codes`. Student không cần email/SMTP, staff dùng email. Cookie/CSRF/refresh giữ nguyên; login limit theo namespace identifier, activate 5/60 giây theo IP. Student create/issue-code/activate không cache mã và từ chối Idempotency-Key trước mutation. OpenAPI gồm các endpoint/schema mới. Test staff email và Student onboarding độc lập; xem contract hiện hành thay cho tiêu chí email lịch sử.
Hiện thực các endpoint REST API HTTP của phân hệ Identity, thiết lập cơ chế lưu trữ refresh token an toàn qua HttpOnly Secure cookie, phòng chống CSRF/Origin và tích hợp rate limiting cho các thao tác xác thực nhạy cảm.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `router.py`
Xây dựng các route thuộc prefix `/api/v1/auth`:
- `POST /auth/register`: Route legacy deprecated; request email/password hợp lệ trả `403 FORBIDDEN`, không tạo user/token/email.
- `POST /auth/activate`: Student username/activation_code/new_password → 204; không SMTP.
- `POST /admin/students` và `POST /admin/students/{user_id}/activation-codes`: Admin cùng trường, code chỉ trả một lần/no-store theo API Contract.
- `POST /auth/verify-email`: Tiếp nhận staff verification token $\to$ Trả về `200 OK` `{verified: true}`.
- `POST /auth/login`: Tiếp nhận credentials $\to$ Trả về `200 OK` với body `{access_token, token_type, expires_in: 900}` và thiết lập `Set-Cookie` cho refresh token (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`).
- `POST /auth/refresh`: Đọc cookie refresh token $\to$ Thực hiện rotation, trả về access token mới và ghi đè cookie refresh token mới.
- `POST /auth/logout`: Thu hồi phiên hiện tại, xóa refresh cookie (`Max-Age=0`).
- `POST /auth/logout-all`: Yêu cầu Bearer auth $\to$ Thu hồi tất cả phiên của user, xóa cookie hiện tại.
- `POST /auth/password/forgot`: Nhận email $\to$ Trả về `200 OK` phản hồi chung chung (generic response để chống user enumeration); email chỉ dùng cho staff.
- `POST /auth/password/reset`: Nhận reset token và mật khẩu mới $\to$ Trả về `204 No Content`.
- `GET /users/me`: Yêu cầu Bearer auth $\to$ Trả về profile của người dùng hiện tại (id, email nullable, username, school_id, display_name, roles, status).
- `PATCH /users/me`: Yêu cầu Bearer auth $\to$ Cập nhật thông tin hiển thị (`display_name`).

### 2.2. Bảo mật Cookie & CSRF/Origin Protection
- Kiểm tra Origin/Referer header cho các mutations sử dụng cookie (`/auth/refresh`, `/auth/logout`) để chống CSRF.
- Đảm bảo cookie không thể bị JavaScript truy cập (`HttpOnly = True`).

### 2.3. Rate Limiting
- Dùng limiter RAM hiện có cho một process; không thêm dependency nếu chưa chốt thiết kế mở rộng:
  - `/auth/login`: tối đa 5 lần sai/60 giây theo IP và identifier chuẩn hóa có namespace username/email.
  - `/auth/register`: luôn bị chặn; activate/verify/reset tối đa 5 request/60 giây theo IP.
  - `/auth/password/forgot`: Tối đa 3 lần yêu cầu / giờ.

### 2.4. Đăng ký Router vào hệ thống
- Cập nhật hàm bootstrap tại `services/core/app/bootstrap.py` để đăng ký router của identity vào ứng dụng FastAPI chính.

---

## 3. Tiêu chí nghiệm thu lịch sử (email legacy)

**Nghiệm thu Lumi bổ sung (2026-10-14):** API Student create/activate/login/refresh/recovery/profile/data requests đạt trên DB test; Student không gọi Admin API, chéo trường 404, code không cache/log, activation rate limit/CSRF/cookie giữ đúng; OpenAPI snapshot cập nhật. Toàn Core 153 test đạt; Compose config hợp lệ, runtime PostgreSQL 16/Docker chưa chạy cho thay đổi này.
- [x] Kiểm thử luồng đăng ký $\to$ xác minh email $\to$ đăng nhập $\to$ nhận JWT và cookie Set-Cookie thành công.
- [x] Kiểm thử luồng gọi `/auth/refresh` bằng cookie thành công và nhận được token mới.
- [x] Kiểm thử tấn công CSRF: request thiếu header Origin/Referer hợp lệ bị chặn 403.
- [x] Rate limit hoạt động: gửi quá 5 request login lỗi trả về `429 RATE_LIMITED`.
- [x] Sinh OpenAPI schema đầy đủ, phản ánh chính xác cấu trúc request/response/error của các endpoint trên; snapshot được kiểm tra cùng pytest trong CI.

**Bằng chứng (2026-10-11):** Python 3.12.14, PostgreSQL 18 tạm; các test HTTP/security/SMTP giả/OpenAPI mới đạt 38/38, toàn Core `pytest -q -W error` với `TEST_DATABASE_URL` đạt 98/98; `ruff check app tests migrations` đạt. Đã kiểm tra cookie attributes/rotation/clear, CSRF Origin/Referer, limit login/register/forgot, reset/logout-all vô hiệu hóa token cũ, quyền profile, rollback khi gửi email thất bại, idempotency replay/conflict và cache không vượt quyền/phiên hiện hành.

**Cập nhật follow-up issue #16 (2026-10-28, nhánh chưa merge):** Staff invitation/password-reset nay lưu delivery state bền vững trước SMTP; worker retry cùng token, Admin reissue invitation có audit. Chi tiết hiện hành tại [Core README](../services/core/README.md#identity-http-api-task-003) và [API Contract](../docs/architect/microservices-v1/core/API_CONTRACT.md). Chưa có SMTP secret trong Cloud Run nên chưa xác minh Gmail thật; các test tích hợp PostgreSQL cũng cần CI hoặc DB test riêng.

**Giới hạn còn lại:** Rate limiter và idempotency TTL 24 giờ dùng RAM một process, không bền vững qua restart/multi-worker. SMTP thật chưa được kiểm chứng; test không gửi email ra ngoài. Full Core PostgreSQL 16 và Compose CI đã chạy sau TASK-015/PR #10, nhưng không kiểm chứng SMTP provider. Các biến cấu hình, phạm vi key và cách chạy tại [Core README](../services/core/README.md#identity-http-api-task-003). Shared files/Compose và API contract vẫn cần owner review.
