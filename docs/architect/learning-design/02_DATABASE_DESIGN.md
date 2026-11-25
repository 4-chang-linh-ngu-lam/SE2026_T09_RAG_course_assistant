# Database logic — LRN-T01
15 bảng mục tiêu, ID Core theo contract thực tế, TIMESTAMPTZ, decimal điểm.
| Bảng | Trường chính |
|---|---|
| questions | id, classroom_id, author_id, type, status |
| question_versions | id, question_id, version_number, content, answer_key, rubric, source_refs |
| topics | id, classroom_id, name |
| question_topics | question_id, topic_id |
| assessments | id, classroom_id, creator_id, type, title, status |
| assessment_versions | id, assessment_id, version_number, policy |
| assessment_items | id, assessment_version_id, question_version_id, position, max_score |
| assignments | id, assessment_version_id, classroom_id, opens_at, due_at, status |
| attempts | id, user_id, assignment_id, assessment_version_id, status, started_at, expires_at |
| attempt_answers | id, attempt_id, assessment_item_id, answer, revision |
| grades | id, attempt_id, assessment_item_id, score, feedback, graded_by |
| grade_history | id, grade_id, old_score, new_score, reason, changed_by, changed_at |
| ai_jobs | id, type, status, idempotency_key, ai_job_id, next_action_at |
| outbox_events | id, event_type, payload, status, next_action_at |
| learning_progress | user_id, topic_id, attempts_count, correct_count, updated_at |
Immutable versions đã sử dụng; unique(parent,version_number), unique(attempt,item) cho answer/grade, item phải thuộc version của attempt, score 0..max_score, max_score dương, idempotency và khóa kiểm tra số lượt concurrent. Progress rebuildable. Index theo lớp, user, assignment, status/next_action_at. Bổ sung audit timestamps, job payload/result/error/lease/fencing, outbox delivery theo CORE-T06. Cần review trước migration: attempt practice không assignment, lưu thứ tự shuffle, submitted_at/published_at, idempotency start/submit, snapshot đối tượng được giao để tính completion, version policy và reopening. Đây là chi tiết đề xuất để đáp ứng quyết định, chưa phê duyệt schema vật lý.