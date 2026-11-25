# Nghiệp vụ
| Event | Recipient dự kiến |
|---|---|
| classroom.post_created | Thành viên phù hợp |
| classroom.comment_created | Tác giả bài |
| classroom.member_joined | Owner/teacher có quyền |
| classroom.member_removed/archived/owner_transferred | Người liên quan theo policy |
| learning.assignment_published | Học sinh được giao |
| learning.assignment_due_soon | Học sinh chưa hoàn thành |
| learning.submission_received | Giáo viên phụ trách |
| learning.grade_published/grade_updated | Học sinh tương ứng |
| Document ingestion success/failure | Chủ sở hữu tài liệu |
Worker xác minh quyền hiện hành, áp dụng preferences, tạo notification dedup và đánh dấu hoàn tất. Không gửi điểm/đáp án/nội dung file nhạy cảm; link tài nguyên phải kiểm tra quyền lại. Event names Document, actor exclusion, mandatory types, recipient snapshot/paging, reminder scheduling cần chốt. Không HTTP trong transaction; khi fanout lớn dùng batch idempotent và durable progress (đề xuất).