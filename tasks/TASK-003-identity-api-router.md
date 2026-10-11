# TASK-003: Identity API Router & Rate Limiting

- **Mã Task:** `TASK-003`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV1`
- **Module:** `services/core/app/modules/identity/`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#auth--user), [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#1-công-nghệ-và-xác-thực)

---

## 1. Mục tiêu
Hiện thực các endpoint REST API HTTP của phân hệ Identity, thiết lập cơ chế lưu trữ refresh token an toàn qua HttpOnly Secure cookie, phòng chống CSRF/Origin và tích hợp rate limiting cho các thao tác xác thực nhạy cảm.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `router.py`
Xây dựng các route thuộc prefix `/api/v1/auth`:
- `POST /auth/register`: Tiếp nhận email, password $\to$ Trả về `201 Created` kèm thông tin user `PENDING_VERIFICATION`.
- `POST /auth/verify-email`: Tiếp nhận verification token $\to$ Trả về `200 OK` `{verified: true}`.
- `POST /auth/login`: Tiếp nhận credentials $\to$ Trả về `200 OK` với body `{access_token, token_type, expires_in: 900}` và thiết lập `Set-Cookie` cho refresh token (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`).
- `POST /auth/refresh`: Đọc cookie refresh token $\to$ Thực hiện rotation, trả về access token mới và ghi đè cookie refresh token mới.
- `POST /auth/logout`: Thu hồi phiên hiện tại, xóa refresh cookie (`Max-Age=0`).
- `POST /auth/logout-all`: Yêu cầu Bearer auth $\to$ Thu hồi tất cả phiên của user, xóa cookie hiện tại.
- `POST /auth/password/forgot`: Nhận email $\to$ Trả về `200 OK` phản hồi chung chung (generic response để chống user enumeration).
- `POST /auth/password/reset`: Nhận reset token và mật khẩu mới $\to$ Trả về `204 No Content`.
- `GET /users/me`: Yêu cầu Bearer auth $\to$ Trả về profile của người dùng hiện tại (id, email, roles, status).
- `PATCH /users/me`: Yêu cầu Bearer auth $\to$ Cập nhật thông tin hiển thị (`display_name`).

### 2.2. Bảo mật Cookie & CSRF/Origin Protection
- Kiểm tra Origin/Referer header cho các mutations sử dụng cookie (`/auth/refresh`, `/auth/logout`) để chống CSRF.
- Đảm bảo cookie không thể bị JavaScript truy cập (`HttpOnly = True`).

### 2.3. Rate Limiting
- Áp dụng rate limiting (bằng thư viện `slowapi` hoặc Redis/in-memory limiter):
  - `/auth/login`: Tối đa 5 lần thử sai / phút trên một địa chỉ IP / email.
  - `/auth/register`: Tối đa 3 lần đăng ký / giờ trên một IP.
  - `/auth/password/forgot`: Tối đa 3 lần yêu cầu / giờ.

### 2.4. Đăng ký Router vào hệ thống
- Cập nhật hàm bootstrap tại `services/core/app/bootstrap.py` để đăng ký router của identity vào ứng dụng FastAPI chính.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Kiểm thử luồng đăng ký $\to$ đăng nhập $\to$ nhận JWT và cookie Set-Cookie thành công.
- [ ] Kiểm thử luồng gọi `/auth/refresh` bằng cookie thành công và nhận được token mới.
- [ ] Kiểm thử tấn công CSRF: request thiếu header Origin/Referer hợp lệ bị chặn 403.
- [ ] Rate limit hoạt động: gửi quá 5 request login lỗi trả về `429 RATE_LIMITED`.
- [ ] Sinh OpenAPI schema đầy đủ, phản ánh chính xác cấu trúc request/response của các endpoint trên.
