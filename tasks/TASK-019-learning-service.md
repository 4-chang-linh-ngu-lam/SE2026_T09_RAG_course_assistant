# TASK-019: Learning Service Specification & Implementation (G4)

- **Mã Task:** `TASK-019`
- **Giai đoạn:** `G4 — Learning`
- **Owner chính:** Phụ trách Service Learning
- **Business Rules liên quan:** `D0-D8`, `I1-I7`, `M1-M4`, `O3`, `O4`, `O5`, `QAS-03`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#d-quiz-assessment-assignment), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** chưa có Learning Service. Bảng/enum và trường kỹ thuật bên dưới là draft, không phải schema được duyệt; không mặc định gộp ba nghiệp vụ vào một bảng hoặc áp công thức phạt nộp muộn cố định.

**Cần sửa/bổ sung:**
- Trước code chốt thiết kế/API/state machine Practice/Assessment/Assignment và contracts với TASK-008/011/012/018/020; không SQL xuyên service.
- PRIMARY phê duyệt công bố Assessment, sửa/hủy điểm đã công bố và quyết định nhạy cảm; ASSISTING tạo nháp/đề xuất/chấm được phân công. Kiểm tra assignment hiện hành, không cho bất kỳ LECTURER tự phê duyệt; Admin chỉ can thiệp ngoại lệ có lý do/audit.
- Bổ sung đủ 4 loại câu hỏi D2; duyệt câu hỏi AI trước dùng, AI không quyết định điểm cuối Assignment/tự luận. Tách practice với điểm chính thức theo D8.
- Attempt ghim phiên bản đề bất biến; version mới áp dụng cho lượt giao tiếp theo (O3), có phương án công bằng M4 cho đề sai. Đồng bộ sửa điểm đã xác nhận bằng event có version để analytics không dùng điểm cũ.
- Chốt transfer cutoff, bài/attempt dở và quyền grade_submitted_work/read_own_history cùng TASK-006/008: bài đã nộp tiếp tục chấm, owner xem kết quả/phúc khảo giới hạn dù enrollment kết thúc; không tự đặt hạn phúc khảo.
- Timer/resume/auto-submit dùng câu trả lời đã lưu thành công; idempotency không nhân đôi submission/grade/evidence. Hạn, best/latest/average, late policy, số lượt/bản được chấm phải cấu hình; gia hạn không tự đổi lượt hoặc trạng thái đã nộp.
- Learning là nguồn deadline/Assessment state; phát outbox cho Calendar/Notification/analytics và cung cấp trạng thái chặn Tutor tích hợp D6. Không dời quyền quyết định điểm sang Core hoặc AI.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] Thiết kế và action/approval/event contracts được review sau Core G2/G3; pending transfer policy được chốt trước mutation liên quan.
- [ ] Test PRIMARY approval, ASSISTING denied, exceptional Admin audit, cross-school/class, transfer/appeal và immutable version.
- [ ] QAS-03 1.000 tình huống retry/cạnh tranh, timer/resume, grade version/out-of-order và deadline notification có bằng chứng; đo QAS-05 theo TP-01.

---

## 1. Mục tiêu
Thiết kế và triển khai Learning Service (`services/learning/`) độc lập trong monorepo, quản lý Practice Quiz, Assessment chính thức và Assignment, quản lý lượt làm bài (attempts) gắn phiên bản đề bất biến, xử lý nộp bài/hết giờ, chấm điểm, sửa điểm có audit và quản lý phúc khảo.

---

## 2. Bản nháp kỹ thuật — cần thiết kế và review trước triển khai

### 2.1. Mô hình dữ liệu tham khảo — chưa chốt schema vật lý
- `Assessment`:
  - `id: UUID`, `class_id: UUID`, `type: Enum` (`PRACTICE_QUIZ`, `OFFICIAL_ASSESSMENT`, `ASSIGNMENT`)
  - `title: str`, `time_limit_minutes: Optional[int]`, `max_attempts: int`
  - `grading_policy: Enum` (`BEST`, `LATEST`, `AVERAGE`, Rule I3)
  - Hạn và chính sách nộp muộn theo cấu hình được duyệt; chưa chốt field hoặc công thức phạt
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
- **Phê duyệt câu hỏi AI (Rule D1):** Câu hỏi AI cần giáo viên duyệt trước khi dùng; công bố Assessment chính thức cần giáo viên chính phê duyệt.
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
- [ ] Sửa điểm: Giáo viên đề xuất sửa điểm đã công bố $\to$ Giáo viên chính phê duyệt, bắt buộc lý do/audit; giữ GradeHistory và chỉ phiên bản đã xác nhận mới có hiệu lực.
- [ ] Học sinh đã kết thúc ghi danh (trạng thái kỹ thuật theo contract Core được duyệt) vẫn đăng nhập vào xem được điểm bài thi cũ và gửi được phúc khảo (Rule M1/O4).
