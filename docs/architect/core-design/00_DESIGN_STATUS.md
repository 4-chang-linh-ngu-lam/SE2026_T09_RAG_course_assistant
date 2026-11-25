# Core Service — Quyết định thiết kế

Ngày phê duyệt: 25/11/2026. CORE-D01–08 ACCEPTED theo xác nhận của người dùng.

| ID | Quyết định |
|---|---|
| CORE-D01 | Core sở hữu User, Classroom, Membership, RBAC, Feed, Comment; không truy vấn DB xuyên service. |
| CORE-D02 | Email/password, JWT access/refresh, rotation, hash refresh token, logout revoke session, rate limit; ưu tiên tái sử dụng auth an toàn hiện có. Argon2id, access 15 phút, refresh 7 ngày là đề xuất cấu hình. |
| CORE-D03 | System roles ADMIN/LECTURER/STUDENT; class roles are Student membership and Lecturer teaching assignments PRIMARY/ASSISTING. No OWNER/TEACHER role. Admin manages official class/roster/assignments; Lecturer teaches only in assigned classes per Business Rules. |
| CORE-D04 | SubjectClass ACTIVE/ARCHIVED; archived is read-only and Admin may restore. Admin manages AUTO/MANUAL roster, preserving history. No join code, join request, invitation self-join, Student self-leave, class OWNER or owner-transfer. Class hard-delete/retention is not defined; account deletion is separate in CORE-D08. |
| CORE-D05 | POST /internal/v1/authorization/check theo DOC-T04: user_id, resource_type, resource_id, action -> allowed. Core xác minh quyền hiện hành, service sở hữu tài nguyên kiểm tra quyền bổ sung; fail closed. |
| CORE-D06 | Feed/comment thuộc Core, hỗ trợ tạo/sửa/xóa/báo cáo vi phạm; Notification nhận sự kiện. |
| CORE-D07 | Transactional Outbox + async REST, durable retry, event_id dedup ở Notification; không broker Increment 1. |
| CORE-D08 | Account ACTIVE/SUSPENDED/DELETION_PENDING/DELETED; Core điều phối xóa dữ liệu, mỗi service xử lý dữ liệu mình sở hữu; không cascade xuyên DB. |

## Giới hạn
Thiết kế mục tiêu, chưa xác minh đầy đủ implementation hiện tại. Không thay đổi application code. Chi tiết schema, DTO, key management, retention, role policy và backlog còn chờ technical design/đối chiếu repository. Kế thừa DOC-T01/T04/T05/T06 khi phù hợp.

## Technical Design — ACCEPTED 25/11/2026
CORE-T01: PostgreSQL database/credential riêng; reuse current Core schema/migrations. Class entities are subject_classes, class_memberships, teaching_assignments; no classroom.owner_id/classroom_invites.
CORE-T02: Public API /api/v1 follows the current Core API Contract; Admin-managed class/roster/assignment routes only. Join, invite, self-leave and owner-transfer drafts are superseded.
CORE-T03: POST /internal/v1/authorization/check/action registry; keep check_class_action behind a Core adapter and retain GET class-access as a compatibility route during migration.
CORE-T04: JWT, refresh rotation, service credentials, audit, fail closed.
CORE-T05: Transaction boundaries for Admin class+assignment creation, Admin roster/AUTO-MANUAL changes, teaching-assignment changes, member removal, Social, Identity sessions and deletion; no join-code or owner-transfer transaction.
CORE-T06: Versioned event envelope, per-target outbox delivery and dedup. Use current roster/teaching-assignment producers; no self-join or owner_transferred event.
CORE-T07: Fault isolation, durable retry, lease, circuit breaker.
CORE-T08: Distributed account deletion revokes access immediately; each service cleans its owned data and Core completes only after required per-target obligations. Retention/completion remain pending; not a class-owner workflow.
Chi tiết trong các tài liệu 01–08. Acceptance criteria và roadmap là đề xuất triển khai, chưa kiểm thử; policy retention, quyền đồng giáo viên, tương thích code và key management cần xác minh.

## CORE-CR01–04 — Traceability correction

- CORE-CR01 supersedes join-code/invitation/self-join content in CORE-D04, CORE-T01/T02/T05 and C-AC06; C-AC06 now tests Business-Rule-authorized roster changes and self-join denial.
- CORE-CR02 supersedes class OWNER/owner-transfer content in CORE-D03/D04, CORE-T01–03/T05/T06/T08 and related AC; retain ADMIN/LECTURER/STUDENT and PRIMARY/ASSISTING.
- CORE-CR03 retains check_class_action and adds CORE-T03 POST via adapter; keep legacy GET during controlled migration.
- CORE-CR04 reuses compatible implementation/migrations; do not rewrite 0001–0014.
- C-AC01 valid public registration remains a separate mismatch with Business Rules/API Contract; it is not silently changed by CORE-CR01–04 and requires Technical Lead decision.
