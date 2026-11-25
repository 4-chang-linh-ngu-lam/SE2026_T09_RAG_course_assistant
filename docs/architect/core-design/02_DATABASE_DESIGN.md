# Database logic — CORE-T01
Schema mục tiêu, không bắt buộc tạo bảng trùng hiện có. Kiểu ID theo Core hiện hành, timestamps TIMESTAMPTZ.
| Bảng | Trường chính |
|---|---|
| users | id, email, password_hash, system_role, status |
| user_profiles | user_id, display_name, avatar_url |
| refresh_sessions | id, user_id, token_hash, family_id, expires_at, revoked_at |
| classrooms | id, owner_id, name, description, status |
| classroom_memberships | id, classroom_id, user_id, role, joined_at, left_at |
| classroom_invites | id, classroom_id, code_hash, role, expires_at, status |
| posts | id, classroom_id, author_id, content, status |
| comments | id, post_id, author_id, content, status |
| content_reports | id, reporter_id, target_type, target_id, reason, status |
| outbox_events | id, event_type, payload, status, attempt_count, next_action_at, lease_token, lease_until |
| account_deletion_jobs | id, user_id, target_service, status, attempt_count, next_action_at |
Email chuẩn hóa unique; FK nội bộ; partial unique membership hiện hành (classroom_id,user_id); đúng một owner hiện hành, owner_id đồng nhất role, chuyển quyền atomic; token hash unique, rotation đồng thời an toàn. Index membership theo user/lớp, post/comment theo parent/time, job theo status/next_action_at. Đề xuất bổ sung delivery records unique(event_id,target_service) để đáp ứng CORE-T06, lease cho deletion jobs; cần review migration và schema cụ thể trước code. Không FK xuyên DB.