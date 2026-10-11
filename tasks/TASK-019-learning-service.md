# TASK-019: Learning Service Specification & Implementation (G4)

- **Mã Task:** `TASK-019`
- **Giai đoạn:** `G4 — Learning`
- **Owner chính:** Phụ trách Service Learning
- **Business Rules liên quan:** `D0-D8`, `I1-I7`, `M1-M4`, `O3`, `O4`, `O5`, `QAS-03`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#d-quiz-assessment-assignment), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership)

---

## 1. Mục tiêu
Thiết kế và triển khai Learning Service (`services/learning/`) độc lập trong monorepo, quản lý Practice Quiz, Assessment chính thức và Assignment, quản lý lượt làm bài (attempts) gắn phiên bản đề bất biến, xử lý nộp bài/hết giờ, chấm điểm, sửa điểm có audit và quản lý phúc khảo.

---

## 2. Chi tiết kỹ thuật

### 2.1. Sở hữu dữ liệu (Schema `learning`)
- `Assessment`:
  - `id: UUID`, `class_id: UUID`, `type: Enum` (`PRACTICE_QUIZ`, `OFFICIAL_ASSESSMENT`, `ASSIGNMENT`)
  - `title: str`, `time_limit_minutes: Optional[int]`, `max_attempts: int`
  - `grading_policy: Enum` (`BEST`, `LATEST`, `AVERAGE`, Rule I3)
  - `due_at: datetime`, `allow_late_submission: bool`, `late_penalty_percent: float`
  - `is_published: bool`, `current_version_id: UUID`
- `AssessmentVersion`:
  - `id: UUID`, `assessment_id: UUID`, `version_number: int`, `content_json: dict` (Bộ câu hỏi đã được Giảng viên duyệt, Rule D1)
  - `is_immutable: bool` (Rule I4: Đề đã công bố là bất biến)
- `AssessmentAttempt`:
  - `id: UUID`, `assessment_version_id: UUID`, `student_id: UUID`, `attempt_number: int`
  - `started_at: datetime`, `submitted_at: Optional[datetime]`
  - `saved_answers_json: dict` (Lưu câu trả lời từng phần, Rule I1)
  - `status: Enum` (`IN_PROGRESS`, `SUBMITTED`, `AUTO_SUBMITTED`, `GRADED`)
- `AssignmentSubmission`:
  - `id: UUID`, `assignment_id: UUID`, `student_id: UUID`, `submission_number: int`
  - `file_url: str`, `submitted_at: datetime`, `is_late: bool`
- `Grade`:
  - `id: UUID`, `target_id: UUID` (Attempt hoặc Submission), `student_id: UUID`
  - `score: float`, `feedback: Optional[str]`, `graded_by: UUID`, `is_final: bool`
  - `version: int` (Tăng mỗi khi sửa điểm)
- `GradeHistory` / `GradeAudit`:
  - Lưu lại lịch sử sửa điểm, lý do sửa (`reason`), người sửa (Rule I6).
- `GradeAppeal`:
  - `id: UUID`, `grade_id: UUID`, `student_id: UUID`, `appeal_reason: str`, `status: Enum` (`PENDING`, `RESOLVED`), `resolution_note: str` (Rule I7, O4).

### 2.2. Các quy tắc nghiệp vụ bắt buộc
- **Phê duyệt câu hỏi AI (Rule D1):** Câu hỏi do AI sinh ra phải được Giảng viên xem và duyệt trước khi dùng chính thức.
- **Tách biệt dữ liệu (Rule D8):** Kết quả luyện tập (`Practice Quiz`) và kết quả chính thức (`Assessment/Assignment`) lưu riêng biệt. Practice Quiz chấm ngay và không tính vào điểm tổng kết (Rule D3).
- **AI không quyết định điểm chính thức (Rule D5, 5 nguyên tắc):** Giảng viên là người quyết định điểm cuối cùng cho câu hỏi tự luận và Assignment. AI chỉ đóng vai trò hỗ trợ gợi ý phản hồi.
- **Ngoại lệ khi làm bài:**
  - Mất kết nối (Rule I1): Lưu câu trả lời từng câu (`saved_answers_json`), cho phép tiếp tục nếu còn thời gian.
  - Hết giờ (Rule I2): Hệ thống tự động nộp bài (`AUTO_SUBMITTED`) với các câu trả lời đã lưu.
  - Sinh viên đã rời lớp (Rule M1, O4): Giảng viên vẫn chấm bài đã nộp trước đó; sinh viên vẫn được quyền xem kết quả cá nhân và gửi yêu cầu phúc khảo trong thời hạn cho phép.
- **Tính toàn vẹn & Chống nộp trùng (QAS-03):** Áp dụng khóa chống lặp (`Idempotency-Key` / unique index theo attempt); không nhân đôi điểm hay bài nộp khi mạng chập chờn.
- **Phát sự kiện đồng bộ Deadline:** Khi tạo hoặc đổi deadline, phát sự kiện Outbox sang Core để cập nhật bản chiếu lịch (Core Calendar) và thông báo cho sinh viên (Rule L3).

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria & QAS-03)
- [ ] Kịch bản nộp bài đồng thời: 1000 lượt thử nộp trùng/thử lại có kiểm soát $\to$ Không có bản ghi trùng lặp nào, điểm số chính xác (QAS-03).
- [ ] Kịch bản hết giờ: Tạo attempt có thời lượng 10 phút, kiểm tra sau 10 phút hệ thống tự chuyển trạng thái sang `AUTO_SUBMITTED` kèm câu trả lời đã lưu.
- [ ] Sửa điểm: Giảng viên sửa điểm bài làm $\to$ Bắt buộc nhập lý do, hệ thống sinh ra bản ghi `GradeHistory` và phiên bản điểm mới nhất có hiệu lực.
- [ ] Sinh viên đã rời lớp (`status = LEFT` ở Core) vẫn đăng nhập vào xem được điểm bài thi cũ và gửi được phúc khảo (Rule M1/O4).
