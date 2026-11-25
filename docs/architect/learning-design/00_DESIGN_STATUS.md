# Learning Service — Design Status

25/11/2026: LRN-D01–10 ACCEPTED theo xác nhận người dùng.

| ID | Quyết định |
|---|---|
| LRN-D01 | Learning sở hữu câu hỏi, đề, assignment, submission, grading, analytics; DB riêng; Core sở hữu membership, Document sở hữu nguồn, AI sinh nội dung. |
| LRN-D02 | Question bank: single choice, multiple choice, essay; giáo viên hoặc AI tạo; bảo toàn phiên bản đề/đáp án. |
| LRN-D03 | Practice cá nhân, phản hồi sau trả lời, không tự thành điểm chính thức. |
| LRN-D04 | Assessment Engine dùng chung cho Practice/Assessment/Assignment, policy riêng về deadline, thời gian, lượt làm, công bố đáp án. |
| LRN-D05 | IN_PROGRESS/SUBMITTED/GRADING/GRADED/PUBLISHED; autosave, server clock, submit idempotent, snapshot, không sửa bài nộp trừ khi mở lại hợp lệ. |
| LRN-D06 | Chấm trắc nghiệm xác định; AI đề xuất tự luận, giáo viên xác nhận; audit old_score/new_score/changed_by/reason/changed_at. |
| LRN-D07 | Sinh câu hỏi và hỗ trợ chấm qua async REST durable job; giải thích/recommendation REST, async nếu dài; validate schema/quyền/nguồn trước lưu; AI không ghi DB Learning. |
| LRN-D08 | AI kiểm tra Learning qua POST /internal/v1/assessment-policy/check; ALLOW/HINT_ONLY/BLOCK đề xuất; fail closed khi không xác minh policy bắt buộc. Phải đối chiếu D6; không cam kết HINT_ONLY tuyệt đối. |
| LRN-D09 | Analytics SQL, recommendation rule-based theo chủ đề yếu/lịch sử, chưa cần model riêng. |
| LRN-D10 | AI offline vẫn làm bài có sẵn/chấm trắc nghiệm; Notification outbox retry; Document offline dùng snapshot nếu quyền hợp lệ; Core offline fail closed; worker recovery; local draft không vượt deadline. |

Thiết kế mục tiêu, chưa đối chiếu đầy đủ code và business rules D6, deadline, công bố điểm, quyền đồng giáo viên. Chi tiết kỹ thuật chờ phê duyệt. Không sửa application code.
