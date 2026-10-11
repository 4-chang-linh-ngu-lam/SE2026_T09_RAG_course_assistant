# TASK-005: Classroom Models & Schema

- **Mã Task:** `TASK-005`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `A1`, `A2`, `A3`, `A4`, `A5`, `A6`, `H1`, `H2`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md#3-schema-logic), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#course--class--membership)

---

## 1. Mục tiêu
Thiết kế và triển khai cấu trúc dữ liệu ORM (SQLAlchemy) và Pydantic schemas cho phân hệ Classroom, bao gồm Khóa học (Course), Lớp học (Class), Thành viên (ClassMembership), Yêu cầu tham gia (JoinRequest) và Lời mời đồng giảng viên (CoLecturerInvitation).

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. `models.py`
Xây dựng các bảng trong schema `core`:
- `Course`:
  - `id: UUID` (PK)
  - `code: str` (Unique, index, ví dụ: "CS101")
  - `name: str` (Tên môn học)
  - `description: Optional[str]`
  - `created_at`, `updated_at: datetime` (UTC)
- `Class`:
  - `id: UUID` (PK)
  - `course_id: UUID` (FK `courses.id`, ondelete RESTRICT)
  - `owner_user_id: UUID` (FK `users.id`, ondelete RESTRICT)
  - `name: str` (Tên lớp, ví dụ: "CS101-K21")
  - `join_code_hash: str` (Unique, index, hash chuỗi mã tham gia lớp học)
  - `join_enabled: bool` (Default: True, Rule A6: bật/tắt nhận yêu cầu tham gia)
  - `status: Enum` (`ACTIVE`, `ARCHIVED`, Default: `ACTIVE`)
  - `created_at`, `updated_at: datetime` (UTC)
- `ClassMembership`:
  - `id: UUID` (PK)
  - `class_id: UUID` (FK `classes.id`, ondelete CASCADE)
  - `user_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `class_role: Enum` (`OWNER`, `CO_LECTURER`, `STUDENT`)
  - `status: Enum` (`ACTIVE`, `LEFT`, `REMOVED`)
  - `joined_at: datetime` (UTC)
  - `ended_at: Optional[datetime]`
  - Ràng buộc: `Index('idx_unique_active_member', class_id, user_id, unique=True, postgresql_where=(status == 'ACTIVE'))` (Đảm bảo chỉ có duy nhất 1 bản ghi ACTIVE cho mỗi cặp user-class).
- `JoinRequest`:
  - `id: UUID` (PK)
  - `class_id: UUID` (FK `classes.id`, ondelete CASCADE)
  - `student_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `status: Enum` (`PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`)
  - `decided_by: Optional[UUID]` (FK `users.id`)
  - `decided_at: Optional[datetime]`
  - `created_at: datetime` (UTC)
  - Ràng buộc: `Index('idx_unique_pending_join_request', class_id, student_id, unique=True, postgresql_where=(status == 'PENDING'))`
- `CoLecturerInvitation`:
  - `id: UUID` (PK)
  - `class_id: UUID` (FK `classes.id`, ondelete CASCADE)
  - `lecturer_id: UUID` (FK `users.id`, ondelete CASCADE)
  - `status: Enum` (`PENDING`, `ACCEPTED`, `REJECTED`, `CANCELLED`)
  - `expires_at: datetime`
  - `created_at: datetime`

### 2.2. `schemas.py`
- Pydantic DTOs cho Course & Class:
  - `CourseCreateRequest`: `code`, `name`, `description`
  - `CourseResponse`: `id`, `code`, `name`, `description`, `created_at`
  - `ClassCreateRequest`: `course_id`, `name`
  - `ClassResponse`: `id`, `course_id`, `name`, `owner_user_id`, `join_enabled`, `status`, `created_at`
  - `ClassUpdateRequest`: `name: Optional[str]`, `join_enabled: Optional[bool]`
  - `JoinRequestCreate`: `join_code: str`
  - `JoinRequestResponse`: `id`, `class_id`, `student_id`, `status`, `created_at`
  - `MembershipResponse`: `id`, `class_id`, `user_id`, `class_role`, `status`, `joined_at`

### 2.3. `repository.py`
- Các truy vấn chuyên biệt với tối ưu hóa chỉ mục:
  - `get_course_by_code`, `list_courses`
  - `get_class_by_id`, `list_user_classes(user_id: UUID)`
  - `find_class_by_join_code_hash(code_hash: str)`
  - `get_active_membership(class_id: UUID, user_id: UUID) -> Optional[ClassMembership]`
  - `get_pending_join_request(class_id: UUID, student_id: UUID) -> Optional[JoinRequest]`

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Partial unique index hoạt động: một sinh viên chỉ có thể có tối đa một bản ghi `ACTIVE` trong cùng một lớp; khi rời lớp (`LEFT`) có thể tham gia lại tạo bản ghi mới mà không bị lỗi unique.
- [ ] Partial unique index cho `JoinRequest`: sinh viên chỉ có tối đa một yêu cầu `PENDING` cho một lớp.
- [ ] Schema Pydantic không bao giờ lộ `join_code_hash` (chỉ trả `join_code` nguyên bản cho Giảng viên sở hữu khi cần).
- [ ] Unit test cho models và repository đạt 100% pass với DB SQLite / PostgreSQL test runner.
