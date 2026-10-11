# TASK-008: Classroom Public Interface & Internal Access Check API

- **Mã Task:** `TASK-008`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `Fail-closed`, `QAS-04`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#admin--internal), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#5-luồng-phụ-thuộc-và-quy-tắc-import)

---

## 1. Mục tiêu
Thiết lập Python public interface (`classroom/public.py`) cho các module nội bộ của Core (như Social, Administration) và hiện thực REST endpoint `/internal/v1/classes/{class_id}/access` phục vụ các microservices khác (Document, AI, Learning) kiểm tra quyền truy cập của người dùng với nguyên tắc **fail-closed**.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `public.py` (Internal Python Interface trong Core)
- Cung cấp các hàm kiểm tra nhanh, không phụ thuộc HTTP:
  - `check_user_in_class(class_id: UUID, user_id: UUID) -> Optional[ClassMembershipDTO]`
  - `is_active_member(class_id: UUID, user_id: UUID) -> bool`
  - `is_class_lecturer(class_id: UUID, user_id: UUID) -> bool` (Trả về True nếu là OWNER hoặc CO_LECTURER)
  - `get_class_status(class_id: UUID) -> Optional[str]` (`ACTIVE` hoặc `ARCHIVED`)
  - `get_class_lecturer_ids(class_id: UUID) -> list[UUID]` (Dùng cho Notification gửi thông báo cho toàn bộ giảng viên phụ trách)

### 2.2. Endpoint Kiểm tra quyền liên Microservice (`Internal Service API`)
- `GET /internal/v1/classes/{class_id}/access?user_id={user_id}&action={action}`
- **Bảo mật:**
  - Bắt buộc header `X-Internal-Service-Key` hoặc service-to-service Bearer token với scope `core:check_access`.
  - Từ chối ngay lập tức các yêu cầu trực tiếp từ trình duyệt của người dùng cuối.
- **Quy tắc xử lý:**
  - Kiểm tra xem `class_id` có tồn tại và trạng thái là gì.
  - Lấy trạng thái membership của `user_id`.
  - Phân tích quyền theo `action` (ví dụ: `READ_DOCUMENTS`, `SUBMIT_ASSESSMENT`, `ASK_AI`, v.v.).
  - Nếu lớp ở trạng thái `ARCHIVED` và `action` là `ASK_AI` $\to$ `allowed: false` (Rule H5).
  - Nếu sinh viên đang ở trạng thái `LEFT` hoặc `REMOVED` $\to$ `allowed: false`.
  - Nếu có bất kỳ lỗi nào không xác minh được (DB timeout, tham số sai) $\to$ **Fail closed: Trả về `allowed: false`**.
- **Response Format:**
  ```json
  {
    "allowed": true,
    "class_id": "uuid",
    "user_id": "uuid",
    "action": "READ_DOCUMENTS",
    "class_role": "STUDENT",
    "class_status": "ACTIVE"
  }
  ```

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Module `social` có thể gọi `classroom/public.py` để kiểm tra quyền thành viên thành công mà không import `models.py` hay `repository.py` của classroom.
- [ ] Endpoint `/internal/v1/classes/{class_id}/access` từ chối `401/403` nếu thiếu header bảo mật liên service.
- [ ] Khi sinh viên đã rời lớp (`LEFT`) hoặc bị đuổi (`REMOVED`), endpoint internal trả về `"allowed": false`.
- [ ] Khi lớp bị lưu trữ (`ARCHIVED`), action `ASK_AI` trả về `"allowed": false`.
- [ ] Contract test cho endpoint `/internal/v1/...` đạt 100%.
