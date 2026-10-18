# TASK-012: Notification Module with Transactional Outbox & Dedup

- **Mã Task:** `TASK-012`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV4`
- **Module:** `services/core/app/modules/notification/`
- **Business Rules liên quan:** `G4`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Notification/outbox chưa triển khai; SMTP Identity hiện gửi callback trước commit, chưa dùng outbox của task này.

**Cần sửa/bổ sung:**
- Thay ví dụ JOIN_REQUEST_* bằng nghiệp vụ Admin enrollment/transfer/assignment/archive và feed/deadline theo contract producer đã duyệt; không khôi phục onboarding bằng mã lớp.
- Chốt ownership public enqueue/outbox, envelope version/event ID/aggregate version và transaction với TASK-006/007/009–011/013. Producer không import repository Notification; không ghi event sau commit rồi coi là transactional.
- Worker chỉ xử lý event đã commit, retry có kiểm soát và consumer idempotent; crash giữa tạo notification/đánh dấu published không được tạo bản sao. Việc ghi outbox lỗi trong transaction phải làm mutation thất bại, khác với lỗi delivery sau commit.
- Notification thuộc người nhận; payload tối thiểu, không mã kích hoạt/reset, token, nguyên văn chat/tài liệu. Link không cấp quyền: khi mở phải kiểm tra school/class/grant hiện hành.
- Thiết kế thứ tự/read watermark cho read-all cạnh tranh; không tự thêm broker hoặc gộp SMTP credential delivery vào payload nếu chưa có thiết kế bảo mật riêng.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TV1/TV2/TV3/TV4 review enqueue/event contracts, migration ở TASK-014 và integration ở TASK-015.
- [ ] Test duplicate/replay/out-of-order, rollback producer, worker crash/retry, recipient-only và thu hồi quyền sau notification; không nhân đôi hoặc làm mất thông báo đã nhận xử lý.

---

## 1. Mục tiêu
Xây dựng phân hệ Thông báo trong ứng dụng (`In-app Notifications`) với khả năng chống trùng lặp (`dedup_key`), cơ chế Transactional Outbox đảm bảo sự tin cậy (lỗi gửi thông báo không làm rollback thao tác nghiệp vụ chính), và API cho người dùng đọc/đánh dấu đã đọc.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng các bảng trong schema `core`:
- `Notification`:
  - `id: UUID` (PK)
  - `recipient_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `type: str` (Ví dụ: các loại enrollment/assignment/feed/deadline sau khi chốt contract)
  - `payload_json: dict` (Nội dung thông báo, liên kết, tên người tác động)
  - `dedup_key: str` (Unique index, chuỗi băm chống gửi trùng thông báo)
  - `read_at: Optional[datetime]` (UTC)
  - `created_at: datetime` (UTC)
  - Index: `Index('idx_notifications_recipient_created', recipient_id, created_at.desc())`
- `OutboxEvent`:
  - `id: UUID` (PK)
  - `event_type: str`
  - `aggregate_id: str`
  - `payload_json: dict`
  - `created_at: datetime` (UTC)
  - `published_at: Optional[datetime]`
  - Index: `Index('idx_outbox_unpublished', published_at, postgresql_where=(published_at == None))`

### 2.2. `schemas.py`
- `NotificationResponse`: `id: UUID`, `type: str`, `payload_json: dict`, `read: bool`, `created_at: datetime`
- `NotificationListResponse`: `items: list[NotificationResponse]`, `unread_count: int`, `next_cursor: Optional[str]`
- `MarkReadResponse`: `id: UUID`, `read: bool`

### 2.3. `service.py` & Cơ chế hoạt động
- **Tạo thông báo an toàn (`create_notification`):**
  - Sinh `dedup_key` duy nhất theo ngữ cảnh: ví dụ `hash(recipient_id + type + event_id)`.
  - Nếu bản ghi với `dedup_key` đã tồn tại $\to$ bỏ qua (idempotent), không gây lỗi.
- **Transactional Outbox Publisher:**
  - Khi một thao tác nghiệp vụ cần phát thông báo (ví dụ Admin đồng bộ ghi danh), ghi bản ghi vào `outbox_events` trong **cùng transaction cơ sở dữ liệu** với thao tác đó.
  - Background task định kỳ hoặc sau commit sẽ quét các `outbox_events` chưa xuất bản (`published_at IS NULL`), chuyển đổi thành `Notification` và đánh dấu `published_at = UTC NOW`.
  - Đảm bảo tính nhất quán: Nếu gửi thông báo thất bại, dữ liệu nghiệp vụ chính không bị rollback.
- **Người dùng quản lý thông báo:**
  - `list_notifications(user_id, cursor, limit)`: Lấy thông báo của chính user đó.
  - `mark_as_read(notification_id, user_id)`: Đặt `read_at = UTC NOW`.
  - `mark_all_as_read(user_id)`: Đặt `read_at = UTC NOW` cho tất cả thông báo chưa đọc của user.

### 2.4. `router.py`
- `GET /api/v1/notifications` (Query pagination `cursor`, `limit`)
- `PATCH /api/v1/notifications/{id}/read`
- `POST /api/v1/notifications/read-all`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Người dùng chỉ nhìn thấy thông báo của chính mình; cố gắng đọc hoặc mark-read thông báo của người khác trả về `404 NOT_FOUND` hoặc `403 FORBIDDEN`.
- [ ] Tính năng Dedup hoạt động: phát 2 sự kiện với cùng một `dedup_key` chỉ sinh ra đúng 1 thông báo duy nhất trong DB.
- [ ] Outbox pattern: Thao tác Admin đồng bộ ghi danh commit thành công sinh ra bản ghi outbox; background worker xử lý chuyển thành notification thành công.
- [ ] `POST /notifications/read-all` cập nhật chính xác số lượng `unread_count = 0`.
