# TASK-014: Core Database Migrations & Seed Data

- **Mã Task:** `TASK-014`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `TV4` (Phối hợp với `TV1`, `TV2`, `TV3`)
- **Module:** `services/core/migrations/`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#3-schema-logic), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#4-quy-tắc-giảm-git-conflict-cho-4-người)

---

## 1. Mục tiêu
Thiết lập bộ di chuyển cơ sở dữ liệu (Alembic Migrations) hoàn chỉnh cho schema `core` trong PostgreSQL, kết nối toàn bộ ORM models của 5 module nội bộ Core và xây dựng script khởi tạo dữ liệu mẫu (Seed Data) cho môi trường kiểm thử/phát triển.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. Cấu hình Alembic `migrations/env.py`
- Kết nối `target_metadata` đến `Base.metadata` của SQLAlchemy chứa tất cả models:
  - `User`, `RoleAssignment`, `AuthSession`, `OneTimeToken`, `DataRequest`
  - `Course`, `Class`, `ClassMembership`, `JoinRequest`, `CoLecturerInvitation`
  - `ClassPost`, `PostComment`, `CalendarEvent`
  - `Notification`, `OutboxEvent`, `AuditEvent`
- Đảm bảo migration chạy bên trong schema `core` (`version_table_schema='core'`, `include_schemas=True`).

### 2.2. Tạo Revision Migration
- Tạo migration file `0002_create_core_domain_tables.py` bao gồm:
  - Tất cả các bảng, khóa ngoại (FK chỉ nội bộ trong Core).
  - Các chỉ mục tối ưu hóa (indexes).
  - Các partial unique indexes:
    - `idx_unique_active_member`: `UNIQUE(class_id, user_id) WHERE status = 'ACTIVE'`
    - `idx_unique_pending_join_request`: `UNIQUE(class_id, student_id) WHERE status = 'PENDING'`
  - Các constraints: `starts_at <= ends_at`, v.v.
- **Quy tắc bất biến:** Không sửa đổi các revision đã merge/áp dụng vào môi trường chung. Nếu có nhiều nhánh tạo migration song song, sử dụng lệnh `alembic merge heads` để tạo revision hợp nhất.

### 2.3. Script Seed Data (`scripts/seed_core.py` hoặc CLI command)
- Tạo tài khoản Admin mặc định: `admin@example.com` (mật khẩu an toàn theo Argon2id).
- Tạo 2 tài khoản Giảng viên: `lecturer1@example.com`, `lecturer2@example.com`.
- Tạo 5 tài khoản Sinh viên: `student1@example.com` đến `student5@example.com`.
- Tạo 1 Khóa học mẫu (`CS101 - Introduction to Programming`) và 1 Lớp học mẫu (`CS101-K21`).
- Gán thành viên mẫu, bài đăng mẫu, bình luận mẫu để phục vụ kiểm thử tích hợp.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Chạy lệnh `alembic upgrade head` trên một cơ sở dữ liệu PostgreSQL mới tinh thành công 100% không có lỗi.
- [ ] Chạy lệnh `alembic downgrade base` và sau đó `alembic upgrade head` lại thành công, chứng minh tính đảo ngược sạch sẽ của schema.
- [ ] Khởi chạy script seed tạo thành công dữ liệu mẫu mà không vi phạm bất kỳ constraint hay foreign key nào.
- [ ] Kiểm tra thực tế trong PostgreSQL: schema `core` chứa đầy đủ 12 bảng và toàn bộ chỉ mục đã thiết kế.
