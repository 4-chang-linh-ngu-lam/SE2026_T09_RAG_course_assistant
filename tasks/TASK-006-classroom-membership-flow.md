# TASK-006: Classroom Membership & Join Request Workflow

- **Mã Task:** `TASK-006`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `A1`, `A4`, `A5`, `L2`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#course--class--membership), [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#4-state-machine)

---

## 1. Mục tiêu
Xây dựng toàn bộ luồng xử lý yêu cầu tham gia lớp học (Join Request) và quản lý thành viên (Membership Lifecycle). Đảm bảo tính an toàn cạnh tranh (concurrency control), chống lặp dữ liệu và tuân thủ chặt chẽ các trạng thái `PENDING` $\to$ `APPROVED`/`REJECTED`/`CANCELLED` cũng như `ACTIVE` $\to$ `LEFT`/`REMOVED`.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `service.py`
Xử lý các nghiệp vụ:
- **Tạo yêu cầu tham gia (`create_join_request`):**
  - Nhận `join_code` từ Sinh viên.
  - Tìm lớp theo hash mã tham gia. Kiểm tra lớp có tồn tại, `status == ACTIVE`, `join_enabled == True`.
  - Kiểm tra xem sinh viên đã là thành viên `ACTIVE` chưa (nếu có $\to$ lỗi `409 CONFLICT`).
  - Kiểm tra xem sinh viên từng bị loại (`REMOVED`) khỏi lớp chưa: sinh viên bị `REMOVED` chỉ được vào lại khi giảng viên chủ động cho phép/mời lại (Rule A1, L2).
  - Kiểm tra có yêu cầu `PENDING` nào trước đó chưa (nếu có $\to$ báo lỗi 409).
  - Tạo `JoinRequest` trạng thái `PENDING`.
  - Kích hoạt sự kiện Outbox thông báo cho Giảng viên (phối hợp Module Notification).

- **Duyệt / Từ chối yêu cầu (`approve_join_request` / `reject_join_request`):**
  - Người thực hiện: `OWNER`, `CO_LECTURER` của lớp, hoặc `ADMIN` can thiệp.
  - Sử dụng transaction với khóa dòng (`SELECT FOR UPDATE`) hoặc cơ chế chống trùng lặp.
  - Nếu request đã ở trạng thái `APPROVED` $\to$ Trả về `200 OK` idempotent với thông tin membership đã có.
  - Nếu request ở trạng thái terminal khác (`REJECTED`, `CANCELLED`) $\to$ Trả về `409 CONFLICT`.
  - Khi `APPROVED`: Chuyển trạng thái request sang `APPROVED`, tạo bản ghi `ClassMembership` mới với `class_role = STUDENT`, `status = ACTIVE`, `joined_at = UTC NOW`. Ghi sự kiện thông báo cho Sinh viên.

- **Sinh viên hủy yêu cầu (`cancel_join_request`):**
  - Chỉ chính sinh viên tạo yêu cầu mới được hủy khi trạng thái còn `PENDING`.

- **Sinh viên tự rời lớp (`leave_class`):**
  - Cập nhật `ClassMembership.status = LEFT`, `ended_at = UTC NOW`.
  - Quy tắc: Chủ lớp (`OWNER`) không thể tự rời lớp nếu chưa chuyển quyền chủ sở hữu cho người khác (Rule H2).

- **Giảng viên loại sinh viên khỏi lớp (`remove_member`):**
  - `OWNER`, `CO_LECTURER` hoặc `ADMIN` can thiệp có quyền loại sinh viên khỏi lớp.
  - Cập nhật `ClassMembership.status = REMOVED`, `ended_at = UTC NOW`.
  - Sinh viên bị xóa lập tức mất quyền truy cập nội dung lớp (Rule L2, fail-closed).

### 2.2. `router.py`
Hiện thực các endpoint theo chuẩn hợp đồng:
- `POST /api/v1/classes/join-requests` (Student gửi join_code)
- `GET /api/v1/classes/{class_id}/join-requests` (Owner/Co-lecturer xem danh sách chờ)
- `POST /api/v1/classes/{class_id}/join-requests/{id}/approve`
- `POST /api/v1/classes/{class_id}/join-requests/{id}/reject`
- `POST /api/v1/classes/{class_id}/join-requests/{id}/cancel`
- `GET /api/v1/classes/{class_id}/members` (Thành viên ACTIVE xem danh sách lớp)
- `DELETE /api/v1/classes/{class_id}/members/me` (Sinh viên tự rời lớp)
- `DELETE /api/v1/classes/{class_id}/members/{user_id}` (Giảng viên loại sinh viên)

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Test concurrency: Gửi 100 request duyệt đồng thời trên cùng một `JoinRequest` chỉ tạo duy nhất 1 bản ghi `ClassMembership` `ACTIVE` (không sinh duplicate membership).
- [ ] Test Rule H2: Giảng viên chính (`OWNER`) gọi `DELETE /classes/{class_id}/members/me` bị từ chối `400 BAD_REQUEST` với thông báo yêu cầu chuyển quyền chủ lớp trước.
- [ ] Test Rule L2: Ngay sau khi bị xóa (`REMOVED`), sinh viên gọi API lấy danh sách thành viên hay bài viết của lớp bị trả về `404 NOT_FOUND` hoặc `403 FORBIDDEN`.
- [ ] Sinh viên chưa được duyệt (`PENDING`) tuyệt đối không thể xem nội dung hay thành viên trong lớp.
