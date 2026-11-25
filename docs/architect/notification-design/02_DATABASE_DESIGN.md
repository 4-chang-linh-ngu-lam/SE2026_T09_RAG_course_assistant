# Database logic
| Bảng | Trường |
|---|---|
| notifications | id, recipient_id, event_id, type, title, body, resource_type, resource_id, created_at, read_at |
| event_inbox | event_id, source, event_type, event_version, payload, status, received_at |
| notification_jobs | id, event_id, status, attempt_count, next_action_at, lease_token, lease_until, error_code |
| notification_preferences | user_id, event_type, enabled, updated_at |
Unique event_id; unique(event_id,recipient_id); unique(user_id,event_type); index recipient_id,created_at; partial unread index; job status,next_action_at. ID Core theo contract; TIMESTAMPTZ. FK nội bộ, không FK xuyên DB. Đề xuất unique job/event, payload fingerprint, fencing, completed_at, tombstone hoặc retention dedup để xóa thông báo không bị replay tái tạo. Schema vật lý và retention cần review.