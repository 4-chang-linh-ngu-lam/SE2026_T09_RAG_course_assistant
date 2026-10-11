# TASK-007: Classroom Lifecycle & Co-Lecturer Management

- **Mã Task:** `TASK-007`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `A3`, `H1`, `H2`, `H5`, `M2`, `M5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#4-state-machine), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#course--class--membership)

---

## 1. Mục tiêu
Xây dựng vòng đời của lớp học (Class Lifecycle: Active, Archive, Restore), quy trình mời và quản lý đồng giảng viên (Co-Lecturer), và quy trình chuyển quyền chủ sở hữu lớp học (Ownership Transfer) an toàn trong một transaction duy nhất.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `permissions.py`
Xây dựng bộ kiểm tra quyền hạn chi tiết trong ngữ cảnh lớp học:
- `require_class_member(class_id, current_user)`: Xác minh là thành viên `ACTIVE`.
- `require_class_owner(class_id, current_user)`: Chỉ chủ lớp (`OWNER`) hoặc Admin can thiệp.
- `require_class_lecturer(class_id, current_user)`: `OWNER` hoặc `CO_LECTURER` hoặc Admin can thiệp.
- Rule M2: Đồng giảng viên (`CO_LECTURER`) có quyền quản lý thành viên, tài liệu nhưng **không** được chuyển quyền chủ sở hữu hoặc xóa/lưu trữ lớp.

### 2.2. Vòng đời lớp học (Archive / Restore)
- `POST /api/v1/classes/{class_id}/archive`:
  - Quyền: Chỉ `OWNER` hoặc `ADMIN` can thiệp.
  - Cập nhật `Class.status = ARCHIVED`.
  - Hiệu lực: Lớp chuyển sang chỉ đọc. Chặn mọi thao tác tạo bài đăng mới, bình luận mới, thêm thành viên mới, nộp bài mới (Rule H5).
- `POST /api/v1/classes/{class_id}/restore`:
  - Quyền: Chỉ `OWNER` hoặc `ADMIN` can thiệp.
  - Cập nhật `Class.status = ACTIVE`. Khôi phục trạng thái hoạt động bình thường (Rule M5).

### 2.3. Quản lý Đồng giảng viên (Co-Lecturer Workflow)
- `POST /api/v1/classes/{class_id}/co-lecturers/invitations`:
  - Quyền: `OWNER` hoặc `ADMIN`.
  - Kiểm tra `lecturer_id` phải có vai trò toàn hệ thống là `LECTURER`.
  - Tạo bản ghi `CoLecturerInvitation` trạng thái `PENDING`.
- `POST /api/v1/classes/{class_id}/co-lecturers/invitations/{id}/accept`:
  - Quyền: Chính giảng viên được mời (`invitee`).
  - Chuyển trạng thái sang `ACCEPTED`.
  - Tạo hoặc cập nhật `ClassMembership`: `class_role = CO_LECTURER`, `status = ACTIVE`.
- `POST /api/v1/classes/{class_id}/co-lecturers/invitations/{id}/reject`:
  - Chuyển trạng thái sang `REJECTED`.

### 2.4. Chuyển quyền chủ lớp (Ownership Transfer)
- `POST /api/v1/classes/{class_id}/ownership-transfer`:
  - Body: `{new_owner_user_id: UUID}`
  - Quyền: Chỉ `OWNER` hiện tại hoặc `ADMIN` can thiệp.
  - Điều kiện: `new_owner_user_id` phải đang là `CO_LECTURER` có `status == ACTIVE` trong lớp đó.
  - **Transaction nguyên tử (Atomicity):**
    1. Cập nhật `Class.owner_user_id = new_owner_user_id`.
    2. Cập nhật `ClassMembership` của chủ cũ thành `class_role = CO_LECTURER`.
    3. Cập nhật `ClassMembership` của người mới thành `class_role = OWNER`.
    4. Ghi `audit_events` ghi nhận chuyển giao quyền sở hữu.
  - Đảm bảo bất biến: Tại mọi thời điểm, một lớp học **chỉ có duy nhất một OWNER**.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Test chuyển quyền chủ lớp: Xác nhận trong DB chủ cũ chuyển thành `CO_LECTURER`, người mới thành `OWNER`, và trường `classes.owner_user_id` cập nhật chính xác.
- [ ] Test thất bại: Cố gắng chuyển quyền cho một sinh viên hoặc người chưa tham gia lớp phải trả về lỗi `400 BAD_REQUEST`.
- [ ] Test Rule H5: Khi lớp ở trạng thái `ARCHIVED`, cố gắng gọi các API thêm thành viên mới, tạo post mới đều bị từ chối `400` hoặc `403`.
- [ ] Test Rule M2: Tài khoản `CO_LECTURER` cố gắng gọi API chuyển quyền hoặc archive lớp bị trả về `403 FORBIDDEN`.
