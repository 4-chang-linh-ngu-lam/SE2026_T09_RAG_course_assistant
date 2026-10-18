# TASK-011: Social Calendar Module

- **Mã Task:** `TASK-011`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV3`
- **Module:** `services/core/app/modules/social/calendar/`
- **Business Rules liên quan:** `G3`, `L3`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Calendar chưa triển khai; Learning chưa có API/event, chỉ chốt ranh giới deadline.

**Cần sửa/bổ sung:**
- Thay OWNER/CO_LECTURER bằng assignment PRIMARY/ASSISTING hiện hành; kiểm tra school/class ở mọi thao tác. ARCHIVED chặn ghi sự kiện chung; lịch lớp không trở thành cách đọc nội dung mới sau chuyển lớp.
- Đồng bộ constraint thành `starts_at < ends_at` đúng Core API Contract, gồm PATCH một trường phải so với giá trị còn lại; dùng datetime UTC có timezone.
- Chốt nguồn/thứ tự event deadline với TASK-019: external_ref, version và dedup không được đoán; Core không tạo/sửa điểm, lượt nộp hay deadline chính thức của Learning.
- Event trùng/cũ không ghi đè version mới; thay deadline phát notification theo L3 nhưng không đổi trạng thái bài đã nộp, số lượt hoặc chính sách nộp lại (O5). Chưa có Learning thì chỉ kiểm thử contract/projection bằng fixture được duyệt.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TASK-005/007/008/012/014 hoàn thành cho Calendar Core; hợp đồng liên service được review trước tích hợp TASK-019.
- [x] Test thời gian bằng nhau/đảo chiều, PATCH, giả class/event ID, ARCHIVED và LEARNING-origin read-only; duplicate/out-of-order không tạo nhiều sự kiện hoặc thông báo.

**Bằng chứng 2026-10-18:** unit/contract Social → 35 passed; `alembic upgrade head --sql` sinh DDL tới 0010 thành công. Integration test PostgreSQL đã được thêm nhưng PostgreSQL 16 Compose chưa chạy do Docker daemon không có; contract TASK-019 vẫn chưa được review nên checklist phụ thuộc giữ nguyên.

---

## 1. Mục tiêu
Xây dựng phân hệ Lịch và Deadline lớp học (`Calendar & Deadlines`). Phân định ranh giới rõ ràng: Core Calendar sở hữu các sự kiện chung của lớp (`origin = CORE`) và chỉ phản chiếu (read-only projection) các deadline do Learning Service sở hữu (`origin = LEARNING`).

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng bảng trong schema `core`:
- `CalendarEvent`:
  - `id: UUID` (PK)
  - `class_id: UUID` (FK `classes.id`, ondelete CASCADE)
  - `title: str` (1 đến 200 ký tự)
  - `description: Optional[str]`
  - `starts_at: datetime` (UTC)
  - `ends_at: datetime` (UTC, ràng buộc `starts_at < ends_at`)
  - `origin: Enum` (`CORE`, `LEARNING`)
  - `external_ref: Optional[str]` (ID tham chiếu của bài Assessment/Assignment bên Learning)
  - `version: int` (Default: 1, phục vụ đồng bộ cập nhật hạn chót có version)
  - `created_at`, `updated_at: datetime` (UTC)
  - Ràng buộc: `UniqueConstraint('origin', 'external_ref', name='uq_calendar_origin_ext_ref')` (Chỉ áp dụng khi `external_ref IS NOT NULL`)
  - Index: `Index('idx_calendar_class_time', class_id, starts_at, ends_at)`

### 2.2. `schemas.py`
- `CalendarEventCreateRequest`: `title: str`, `description: Optional[str]`, `starts_at: datetime`, `ends_at: datetime`
- `CalendarEventUpdateRequest`: `title: Optional[str]`, `description: Optional[str]`, `starts_at: Optional[datetime]`, `ends_at: Optional[datetime]`
- `CalendarEventResponse`: `id: UUID`, `class_id: UUID`, `title: str`, `description: Optional[str]`, `starts_at: datetime`, `ends_at: datetime`, `origin: str`, `external_ref: Optional[str]`

### 2.3. `service.py` & Quy tắc ràng buộc
- **Xem lịch (`get_calendar_events`):**
  - Xác minh quyền đọc theo membership hoặc teaching assignment hiện hành, school/class và user status.
  - Hỗ trợ lọc theo khoảng thời gian: `?from=ISO&to=ISO`.
- **Tạo sự kiện lớp (`create_calendar_event`):**
  - Chỉ giáo viên PRIMARY/ASSISTING hiện hành của lớp mới được tạo sự kiện.
  - Luôn gán `origin = CORE` và `external_ref = None`.
- **Sửa / Xóa sự kiện (`update_event`, `delete_event`):**
  - Chỉ giảng viên phụ trách mới có quyền sửa.
  - **Quy tắc bắt buộc:** Nếu `origin == LEARNING`, **từ chối sửa/xóa trực tiếp tại Core API** (trả về lỗi `400 BAD_REQUEST: Deadline từ Learning chỉ được đồng bộ tự động, không chỉnh sửa trực tiếp`).
- **Đồng bộ sự kiện từ Learning (Internal Sync Helper):**
  - Hàm nội bộ nhận event từ Learning (ví dụ qua outbox / message consumer khi tích hợp):
  - Cập nhật deadline tương ứng, kiểm tra `version` để tránh nhận event sai thứ tự (out-of-order).

### 2.4. `router.py`
- `GET /api/v1/classes/{class_id}/calendar` (Query `from`, `to`)
- `POST /api/v1/classes/{class_id}/calendar`
- `PATCH /api/v1/classes/{class_id}/calendar/{id}`
- `DELETE /api/v1/classes/{class_id}/calendar/{id}`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Giảng viên có thể tạo sự kiện học tập trên lịch lớp học; sinh viên có thể xem lịch trong khoảng thời gian xác định.
- [ ] Thử nghiệm sửa hoặc xóa một sự kiện có `origin = LEARNING` qua API Core bị từ chối và giải thích rõ ràng lý do.
- [ ] Ràng buộc thời gian: gửi `starts_at >= ends_at` bị từ chối bằng lỗi `422 VALIDATION_ERROR`.
- [ ] Thành viên không thuộc lớp hoặc đã bị xóa không thể xem lịch của lớp.
