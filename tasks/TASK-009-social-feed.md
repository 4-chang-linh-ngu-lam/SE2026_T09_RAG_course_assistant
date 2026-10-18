# TASK-009: Social Feed Module

- **Mã Task:** `TASK-009`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV3`
- **Module:** `services/core/app/modules/social/feed/`
- **Business Rules liên quan:** `G1`, `L1`, `L5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng tại ngày 2026-10-16:** Feed mới có skeleton; nhận định này đã được thay thế sau khi PR #8 triển khai Social.

**Cần sửa/bổ sung:**
- Phụ thuộc action policy TASK-008 và phân công PRIMARY/ASSISTING TASK-007; không suy quyền từ OWNER/CO_LECTURER legacy hoặc global LECTURER.
- Mọi list/get/update/delete đều kiểm tra trường/lớp và quan hệ post–class; tác giả đã kết thúc ghi danh không giữ quyền sửa chỉ nhờ author_id. ARCHIVED chặn sửa/xóa hoạt động chung theo contract đã duyệt.
- Identity public DTO đã có `display_name` nullable qua batch lookup; Social chỉ dùng `id` và tên hiển thị trong author response, không trả email/username đăng nhập và không query Identity model.
- Chốt pagination trước code: Common hiện dùng cursor UUID, chưa hỗ trợ thứ tự created_at mới nhất. Nếu giữ yêu cầu mới nhất, thiết kế cursor/sort nhất quán và test không trùng/bỏ sót, không dùng cursor UUID với query created_at khác thứ tự.
- Không mở quyền đọc toàn feed cũ bằng read_own_history; ngoại lệ lịch sử cá nhân không phải quyền xem nội dung mới của lớp. Soft delete ẩn cả list/detail; notification qua outbox và moderation audit tối thiểu.

**Phụ thuộc và nghiệm thu bổ sung:**
- [x] TASK-004/005/007/008/014 được tích hợp; cross-school/class, post thuộc lớp khác, LOCKED/ENDED/ARCHIVED và quyền tác giả cũ đều có test.
- [ ] Test DTO không phụ thuộc email Student, phân trang ổn định và bài đã xóa không lộ qua detail/comments; TV1/TV2 review public contracts.

**Bằng chứng 2026-10-18:** `pytest tests/social -q -W error` → 35 passed; toàn Core không có `TEST_DATABASE_URL` → 135 passed, 62 skipped. Test PostgreSQL 16/TV1–TV2 review chưa hoàn tất nên checklist review giữ nguyên.

**Cập nhật sau PR #8 (2026-10-19):** Feed hiện đã có trong `main`; full Core PostgreSQL 16 suite trên commit sau PR #10 đạt 342 passed, 0 skipped. CI PR #10 cũng xanh. Các con số 135/62 và nhận định chưa triển khai ở trên là bằng chứng lịch sử, không phải trạng thái mới. Owner review cho shared/action contracts vẫn cần ghi nhận riêng.

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
- `PostAuthorSummary`: `id: UUID`, `display_name: Optional[str]`; không trả email/username đăng nhập
- `PostResponse`: `id: UUID`, `class_id: UUID`, `author: PostAuthorSummary`, `body: str`, `created_at: datetime`, `updated_at: datetime`
- `PostListResponse`: `items: list[PostResponse]`, `next_cursor: Optional[str]`

### 2.3. `service.py` & Kiểm tra quyền
- **Đăng bài (`create_post`):**
  - Gọi Classroom public theo action contract TASK-008, kiểm tra membership hoặc teaching assignment hiện hành, school/class và user status; che tài nguyên ngoài quyền theo API Contract.
  - Chặn ARCHIVED; không chỉ kiểm tra global role hoặc author_id.
  - Lưu bài viết mới.
- **Xem bảng tin (`list_posts`):**
  - Xác minh membership hoặc teaching assignment hiện hành và quyền đọc feed; không suy ra từ read_own_history.
  - Chỉ lọc các bài đăng có `deleted_at IS NULL` (Rule L1: Bài đã xóa không hiển thị trên giao diện).
  - Hỗ trợ phân trang bằng cursor.
- **Sửa bài (`update_post`):**
  - Chỉ tác giả (`author_id == current_user.id`) còn quyền hiện hành, lớp không ARCHIVED và post đúng class mới được sửa.
- **Xóa bài (`delete_post`):**
  - Tác giả được tự xóa bài của mình.
  - Giảng viên phụ trách (PRIMARY/ASSISTING hiện hành) hoặc `ADMIN` can thiệp có quyền xóa bài vi phạm (Rule L5: Giảng viên ẩn/xóa nội dung vi phạm, có ghi audit).
  - Thực hiện soft-delete: Đặt `deleted_at = UTC NOW`.

### 2.4. `router.py`
- `GET /api/v1/classes/{class_id}/posts`
- `POST /api/v1/classes/{class_id}/posts`
- `PATCH /api/v1/classes/{class_id}/posts/{post_id}`
- `DELETE /api/v1/classes/{class_id}/posts/{post_id}`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Thành viên `ACTIVE` có thể đăng bài và đọc danh sách bài đăng theo thứ tự mới nhất.
- [ ] Học sinh chưa được Admin ghi danh hoặc đã kết thúc ghi danh không thể đăng bài hay đọc bảng tin; tài nguyên ngoài quyền được che theo API Contract.
- [ ] Khi một bài viết bị xóa (soft delete), gọi `GET /posts` không còn nhìn thấy bài viết đó (Rule L1).
- [ ] Giảng viên có thể xóa bài viết của sinh viên khác và hệ thống ghi lại sự kiện vào `audit_events` (Rule L5).
- [ ] Khi lớp bị `ARCHIVED`, yêu cầu `POST /posts` bị từ chối với thông báo lỗi thích hợp.
