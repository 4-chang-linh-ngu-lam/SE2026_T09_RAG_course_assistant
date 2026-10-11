# TASK-001: Core Common & Security Foundation

- **Mã Task:** `TASK-001`
- **Giai đoạn:** `G0 — Contract Core / Foundation`
- **Owner chính:** `TV1` (Phối hợp toàn đội)
- **Module:** `services/core/app/common/`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md), [ADR-001](../docs/architect/microservices-v1/ADR-001.md)

---

## 1. Mục tiêu
Xây dựng lớp hạ tầng kỹ thuật dùng chung cho toàn bộ Core service bên trong `services/core/app/common/`, đảm bảo tính thống nhất về xử lý lỗi, xác thực JWT, hash mật khẩu Argon2id, phân trang, truy vấn cơ sở dữ liệu và ghi audit.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `app/common/config.py`
- Đọc biến môi trường an toàn qua Pydantic `BaseSettings`:
  - `DATABASE_URL` (PostgreSQL async/sync connection string)
  - `SECRET_KEY`, `ALGORITHM` (HS256)
  - `ACCESS_TOKEN_EXPIRE_MINUTES = 15`
  - `REFRESH_TOKEN_EXPIRE_DAYS = 7`
  - `INTERNAL_SERVICE_SECRET` (dùng cho service-to-service auth)
  - Cấu hình Cookie: `SECURE=True` (False in local dev), `HTTPONLY=True`, `SAMESITE="Lax"`

### 2.2. `app/common/security.py`
- Hash mật khẩu bằng **Argon2id** (`passlib.context.CryptContext` hoặc thư viện `argon2-cffi`).
- Tạo và xác thực Access JWT:
  - Payload bắt buộc: `sub` (User ID UUID), `roles` (list string), `token_version` / `session_version`, `exp`, `iat`.
- Refresh token helpers:
  - Sinh random opaque token chuỗi an toàn cao (32 bytes hex).
  - Hash refresh token bằng SHA-256 trước khi lưu DB (`refresh_hash`).

### 2.3. `app/common/auth_dependencies.py`
- `get_current_user`: Trích xuất Bearer token từ header `Authorization`, verify chữ ký và hạn sử dụng.
- Kiểm tra trạng thái người dùng trong DB: `status == ACTIVE`, không bị khóa (`LOCKED`), session version khớp.
- `require_roles(*roles)`: Dependency kiểm tra vai trò toàn hệ thống (`STUDENT`, `LECTURER`, `ADMIN`).
- `verify_internal_service_key`: Dependency xác thực các request gọi từ microservice khác vào `/internal/v1/*`.

### 2.4. `app/common/errors.py`
- Định nghĩa các Custom Exception và Exception Handler chuẩn hóa:
  - Format response: `{"error": {"code": "...", "message": "...", "correlation_id": "uuid"}}`
  - Mã lỗi chuẩn: `BAD_REQUEST`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `VALIDATION_ERROR`, `RATE_LIMITED`.
  - Che giấu tài nguyên không có quyền bằng `404 NOT_FOUND` thay vì `403` để chống enumeration.

### 2.5. `app/common/pagination.py`
- Trình phân trang bằng con trỏ (opaque cursor) hoặc limit-offset chuẩn hóa:
  - Query params: `limit: int = Query(default=20, ge=1, le=100)`, `cursor: Optional[str] = None`.
  - Output schema: `{"items": [...], "next_cursor": Optional[str]}`.

### 2.6. `app/common/audit.py`
- Hàm tiện ích ghi nhận sự kiện kiểm toán (`audit_events`):
  - Tham số: `actor_id`, `action`, `target_type`, `target_id`, `correlation_id`, `metadata_json`.
  - **Quy tắc bắt buộc:** Tuyệt đối không lưu token, mật khẩu, chat riêng tư hoặc dữ liệu nhạy cảm.

### 2.7. `app/common/db.py`
- Base Model Declarative SQLAlchemy với:
  - `id: UUID` làm khóa chính mặc định (`uuid4` phía Python, `gen_random_uuid()` có sẵn trong PostgreSQL 16; không cần extension `uuid-ossp`).
  - `created_at`, `updated_at` (UTC timestamp).
- Quản lý transaction context manager.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Chạy unit test hash Argon2id: xác minh mật khẩu đúng, từ chối mật khẩu sai, dùng hash một chiều Argon2id với salt riêng (test không chứng minh tính không thể đảo ngược).
- [x] Chạy unit test JWT: sinh token đúng thời hạn 15 phút, từ chối token hết hạn hoặc giả mạo.
- [x] Middleware trích xuất hoặc sinh mới `correlation_id` cho mọi request.
- [x] Exception handler trả về đúng định dạng JSON lỗi chuẩn hóa cho mọi lỗi HTTP (400, 401, 403, 404, 409, 422).
- [x] `ruff check app/common/` và `pytest tests/test_common.py -W error` đạt, không cảnh báo.

**Bằng chứng kiểm thử (2026-10-11):** Python 3.12.14; unit Common 36/36 đạt; toàn Core `pytest -q -W error` với `TEST_DATABASE_URL` đạt 38/38; `ruff check app tests migrations` đạt. Integration test dùng PostgreSQL 18 tạm, kiểm tra migration 0002, schema drift, audit persistence, UUID/timestamp UTC và rollback. Chưa kiểm chứng Docker Compose/PostgreSQL 16 ở bước này.

**Điểm tích hợp:** TASK-002 đã nối lookup Identity DB hiện hành cho `get_current_user`; ứng dụng chưa nối lookup vẫn fail closed. TASK-003 đã áp dụng cookie/CSRF tại endpoint; TASK-004 mở rộng public workflows. Đây là hoàn thành Common foundation, chưa phải hoàn thành toàn bộ Identity. Hướng dẫn cấu hình và interface tại [Core README](../services/core/README.md#common-foundation-task-001).
