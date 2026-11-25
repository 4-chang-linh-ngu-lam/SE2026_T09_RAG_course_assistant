# Database logic — CORE-T01

CORE-T01 về database/credential riêng và reuse schema hiện có vẫn giữ. CORE-CR01/02 supersede class owner/invite entries trong logical draft. Physical truth là ORM và Alembic hiện hành; không sửa applied migration.

## Class entities hiện tại

| Table | Trường/quan hệ chính | Quy tắc |
|---|---|---|
| subject_classes | school_id, academic_year_id, semester_id, course_id, homeroom_class_id, grade_level, enrollment_mode, status, version | Class entity; không owner_id |
| class_memberships | class_id, student_id, source AUTO/MANUAL, status ACTIVE/ENDED, joined_at, ended_at | Student roster/history; không role OWNER/TEACHER |
| teaching_assignments | class_id, lecturer_id, role PRIMARY/ASSISTING, assigned_at, ended_at | Teacher assignment hiện tại và history |
| homeroom_rosters | homeroom_class_id, student_id, joined_at, ended_at | Roster hành chính do Admin quản lý |

Các entity trên được tạo trong migration 0008; Core hiện tới migration 0014. Identity, school/course/calendar, Social, Notification, audit và outbox tiếp tục thuộc schema Core hiện có.

## Draft class schema bị supersede

- classrooms.owner_id và invariant “một owner”: không có trong physical SubjectClass model; dùng TeachingAssignment PRIMARY/ASSISTING theo H1.
- classroom_memberships.role: physical ClassMembership chỉ giữ student/source/status; teacher role nằm trong teaching_assignments.
- classroom_invites/code_hash: không phù hợp BR-A6, không tạo bảng/API join.
- account_deletion_jobs là CORE-D08 design concept, chưa có model/migration hiện hành; cần CORE-07 và retention/completion decision.
- CORE-T01 không yêu cầu tạo bảng trùng hoặc sửa lịch sử migration; mọi schema delta cần task/AC được duyệt.
