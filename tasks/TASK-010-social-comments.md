# TASK-010: Social Comments Module

- **Mã Task:** `TASK-010`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV3`
- **Module:** `services/core/app/modules/social/comments/`
- **Business Rules liên quan:** `G2`, `L1`, `L5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Comments mới có skeleton; cần đồng bộ Feed và action access trước triển khai.

**Cần sửa/bổ sung:**
- Sửa giới hạn body từ 5.000 thành **1..10.000** theo Core API Contract; author DTO xử lý Student email null và dùng public interface đã chốt.
- Xác minh chuỗi class → post → comment trong mọi route, kể cả sửa/xóa; tác giả vẫn cần quyền hiện hành. Bài đã xóa phải chặn cả đọc/tạo/sửa bình luận, không chỉ create.
- Dùng phân công PRIMARY/ASSISTING cho moderation; Admin can thiệp có lý do/audit. ARCHIVED chặn ghi hoạt động chung, không dựa vào global role hoặc quyền tác giả đơn thuần.
- Comments cần interface công khai tối thiểu của Feed để xác minh post; không import repository/model Feed để thực hiện nghiệp vụ. Comment tạo thành công ghi outbox cùng transaction; TASK-012 xử lý recipient/dedup và kiểm tra quyền khi mở link.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TASK-008/009/012/014 thống nhất DTO, transaction và notification contract; test parent ID giả, cross-school/class, post/comment đã xóa và tác giả mất quyền.
- [ ] Test biên body 1/10.000/10.001, LOCKED/ENDED/ARCHIVED, moderation có audit và notification lỗi không rollback comment đã commit.

---

## 1. Mục tiêu
Xây dựng tính năng bình luận bài đăng (`Post Comments`) trong lớp học, hỗ trợ tạo bình luận, xem danh sách bình luận theo bài đăng, chỉnh sửa bình luận của bản thân và xóa (soft-delete) bởi tác giả hoặc giảng viên kiểm duyệt.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng bảng trong schema `core`:
- `PostComment`:
  - `id: UUID` (PK)
  - `post_id: UUID` (FK `class_posts.id`, ondelete CASCADE)
  - `author_id: UUID` (FK `users.id`, ondelete RESTRICT)
  - `body: str` (1 đến 10,000 ký tự)
  - `deleted_at: Optional[datetime]` (UTC, soft-delete)
  - `created_at`, `updated_at: datetime` (UTC)
  - Index: `Index('idx_comments_post_created', post_id, created_at.asc())`

### 2.2. `schemas.py`
- `CommentCreateRequest`: `body: str`
- `CommentUpdateRequest`: `body: str`
- `CommentResponse`: `id: UUID`, `post_id: UUID`, `author: PostAuthorSummary`, `body: str`, `created_at: datetime`, `updated_at: datetime`
- `CommentListResponse`: `items: list[CommentResponse]`, `next_cursor: Optional[str]`

### 2.3. `service.py` & Kiểm tra quyền
- **Tạo bình luận (`create_comment`):**
  - Xác minh membership hoặc teaching assignment hiện hành theo action và scope lớp chứa bài đăng (gọi qua `classroom.public`).
  - Xác minh bài đăng tồn tại và chưa bị xóa (`deleted_at IS NULL`).
  - Kiểm tra trạng thái lớp: nếu `ARCHIVED` $\to$ từ chối (Rule H5).
  - Lưu bình luận mới.
  - Gửi thông báo đến tác giả bài viết (nếu người bình luận khác tác giả bài viết).
- **Xem bình luận (`list_comments`):**
  - Xác minh người dùng có quyền xem lớp và bài viết.
  - Chỉ lấy bình luận có `deleted_at IS NULL` (Rule L1).
- **Chỉnh sửa bình luận (`update_comment`):**
  - Chỉ chính tác giả bình luận mới có quyền sửa.
- **Xóa bình luận (`delete_comment`):**
  - Tác giả bình luận có quyền tự xóa.
  - Giảng viên phụ trách lớp (PRIMARY/ASSISTING hiện hành) hoặc `ADMIN` can thiệp có quyền xóa bình luận vi phạm và hệ thống ghi lại audit log (Rule L5).
  - Thực hiện soft-delete: Đặt `deleted_at = UTC NOW`.

### 2.4. `router.py`
- `GET /api/v1/classes/{class_id}/posts/{post_id}/comments`
- `POST /api/v1/classes/{class_id}/posts/{post_id}/comments`
- `PATCH /api/v1/classes/{class_id}/posts/{post_id}/comments/{id}`
- `DELETE /api/v1/classes/{class_id}/posts/{post_id}/comments/{id}`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Thành viên `ACTIVE` có thể bình luận vào bài đăng hợp lệ; học sinh khác lớp hoặc chưa được ghi danh bị chặn 403.
- [ ] Không thể bình luận vào bài viết đã bị xóa (trả về `404 NOT_FOUND`).
- [ ] Bình luận đã bị soft-delete không còn xuất hiện trong danh sách `GET /comments`.
- [ ] Giảng viên có thể xóa bình luận không phù hợp của sinh viên và có log kiểm toán trong `audit_events`.
- [ ] Không thể bình luận khi lớp ở trạng thái `ARCHIVED`.
