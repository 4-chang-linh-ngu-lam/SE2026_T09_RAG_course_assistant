# TASK-009: Social Feed Module

- **Mã Task:** `TASK-009`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV3`
- **Module:** `services/core/app/modules/social/feed/`
- **Business Rules liên quan:** `G1`, `L1`, `L5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#2-module-và-ownership), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#feed--comments--calendar--notifications)

---

## 1. Mục tiêu
Xây dựng phân hệ Bảng tin lớp học (`Class Feed Posts`), cho phép thành viên hoạt động (`ACTIVE`) đăng bài, chỉnh sửa bài đăng của chính mình, và cho phép tác giả hoặc giảng viên phụ trách thực hiện xóa bài (soft-delete).

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng bảng trong schema `core`:
- `ClassPost`:
  - `id: UUID` (PK)
  - `class_id: UUID` (FK `classes.id`, ondelete CASCADE)
  - `author_id: UUID` (FK `users.id`, ondelete RESTRICT)
  - `body: str` (Độ dài từ 1 đến 10,000 ký tự)
  - `deleted_at: Optional[datetime]` (UTC, phục vụ soft-delete)
  - `created_at`, `updated_at: datetime` (UTC)
  - Index: `Index('idx_posts_class_created', class_id, created_at.desc())`

### 2.2. `schemas.py`
- `PostCreateRequest`: `body: str`
- `PostUpdateRequest`: `body: str`
- `PostAuthorSummary`: `id: UUID`, `display_name: str`, `email: str`
- `PostResponse`: `id: UUID`, `class_id: UUID`, `author: PostAuthorSummary`, `body: str`, `created_at: datetime`, `updated_at: datetime`
- `PostListResponse`: `items: list[PostResponse]`, `next_cursor: Optional[str]`

### 2.3. `service.py` & Kiểm tra quyền
- **Đăng bài (`create_post`):**
  - Gọi `classroom.public.is_active_member(class_id, current_user.id)`. Nếu không $\to$ `403 FORBIDDEN`.
  - Gọi `classroom.public.get_class_status(class_id)`. Nếu `ARCHIVED` $\to$ `400 BAD_REQUEST` (Lớp lưu trữ không cho đăng bài mới).
  - Lưu bài viết mới.
- **Xem bảng tin (`list_posts`):**
  - Xác minh thành viên `ACTIVE`.
  - Chỉ lọc các bài đăng có `deleted_at IS NULL` (Rule L1: Bài đã xóa không hiển thị trên giao diện).
  - Hỗ trợ phân trang bằng cursor.
- **Sửa bài (`update_post`):**
  - Chỉ chính tác giả bài viết (`author_id == current_user.id`) mới được chỉnh sửa.
- **Xóa bài (`delete_post`):**
  - Tác giả được tự xóa bài của mình.
  - Giảng viên phụ trách (`OWNER`, `CO_LECTURER`) hoặc `ADMIN` can thiệp có quyền xóa bài vi phạm (Rule L5: Giảng viên ẩn/xóa nội dung vi phạm, có ghi audit).
  - Thực hiện soft-delete: Đặt `deleted_at = UTC NOW`.

### 2.4. `router.py`
- `GET /api/v1/classes/{class_id}/posts`
- `POST /api/v1/classes/{class_id}/posts`
- `PATCH /api/v1/classes/{class_id}/posts/{post_id}`
- `DELETE /api/v1/classes/{class_id}/posts/{post_id}`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Thành viên `ACTIVE` có thể đăng bài và đọc danh sách bài đăng theo thứ tự mới nhất.
- [ ] Sinh viên chưa duyệt (`PENDING`) hoặc đã rời lớp (`LEFT`) không thể đăng bài hay đọc bảng tin.
- [ ] Khi một bài viết bị xóa (soft delete), gọi `GET /posts` không còn nhìn thấy bài viết đó (Rule L1).
- [ ] Giảng viên có thể xóa bài viết của sinh viên khác và hệ thống ghi lại sự kiện vào `audit_events` (Rule L5).
- [ ] Khi lớp bị `ARCHIVED`, yêu cầu `POST /posts` bị từ chối với thông báo lỗi thích hợp.
