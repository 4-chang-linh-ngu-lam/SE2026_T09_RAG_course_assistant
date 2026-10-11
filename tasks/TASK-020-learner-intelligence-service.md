# TASK-020: Learner Intelligence Service & MVP Reporting (G5)

- **Mã Task:** `TASK-020`
- **Giai đoạn:** `G5 — Learner Intelligence + Hoàn thiện MVP`
- **Owner chính:** Phụ trách Service Learner Intelligence & Tích hợp MVP
- **Business Rules liên quan:** `E1-E6`, `F6`, `J1-J5`, `O6`, `O8`, `QAS-11`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#e-analytics), [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#qas-11--chất-lượng-gợi-ý-recommendation-quality), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership)

---

## 1. Mục tiêu
Thiết kế và triển khai Learner Intelligence Service (`services/learner_intelligence/`) độc lập trong monorepo, xây dựng mô hình thu thập bằng chứng học tập (learning evidence), ước lượng mức độ nắm vững chủ đề (mastery snapshots), hệ thống gợi ý học tập (recommendations) mang tính hỗ trợ, thực hiện quy tắc bảo vệ riêng tư nhóm nhỏ (< 5 sinh viên), và hoàn thiện tính năng xuất báo cáo tổng hợp PDF/Excel cho Nhà trường thông qua Admin.

---

## 2. Chi tiết kỹ thuật

### 2.1. Sở hữu dữ liệu (Schema `learner_intelligence`)
- `LearningEvidence`:
  - `id: UUID`, `student_id: UUID`, `class_id: UUID`, `topic_id: str`
  - `source_type: Enum` (`ASSESSMENT_RESULT`, `PRACTICE_RESULT`, `ASSIGNMENT_RESULT`)
  - `score: float`, `weight: float`, `observed_at: datetime`
- `MasterySnapshot`:
  - `id: UUID`, `student_id: UUID`, `class_id: UUID`, `topic_id: str`
  - `mastery_score: float` (Thang điểm 0.0 - 1.0)
  - `confidence_level: Enum` (`INSUFFICIENT_DATA`, `LOW`, `MEDIUM`, `HIGH`, Rule J1)
  - `evidence_count: int`
  - `calculated_at: datetime`
- `LearningRecommendation`:
  - `id: UUID`, `student_id: UUID`, `class_id: UUID`, `topic_id: str`
  - `recommended_type: Enum` (`REVIEW_DOCUMENT`, `PRACTICE_TOPIC`)
  - `resource_ref: str`, `reasoning: str`
  - `created_at: datetime`
- `AggregateReportExport`:
  - `id: UUID`, `requested_by: UUID`, `format: Enum` (`PDF`, `EXCEL`), `file_url: str`, `status: Enum`

### 2.2. Các quy tắc nghiệp vụ bắt buộc
- **Bằng chứng độc lập (Rule E3, J1, J2, O6):**
  - Chỉ kết luận sinh viên nắm vững hoặc yếu chủ đề khi có đủ bằng chứng độc lập và độ bao phủ chủ đề.
  - Nếu thiếu dữ liệu: Hiển thị "Chưa đủ dữ liệu", **không được vội vã kết luận mastery** (Rule J1).
  - Sinh viên hỏi lặp lại một câu hỏi trong chat AI **không được tính là bằng chứng độc lập** (Rule J2).
- **Gợi ý học tập mang tính hỗ trợ (Rule E4, E6, J5):**
  - Gợi ý tài liệu, chủ đề ôn tập mang tính định hướng; sinh viên có toàn quyền tự quyết định.
  - Cảnh báo rủi ro học tập (at-risk warning) chỉ phát khi có đủ bằng chứng xác thực và chỉ nhằm mục đích hỗ trợ sinh viên, **không được dùng để trừng phạt hoặc tự động trừ điểm**.
- **Quy tắc bảo vệ danh tính nhóm nhỏ (Rule E5, J4, O6):**
  - Khi hiển thị thống kê tổng hợp chủ đề hỏi đáp AI Tutor cho Giảng viên: **Bắt buộc ẩn số liệu nếu nhóm có dưới 5 sinh viên tham gia phân biệt**.
  - Áp dụng kỹ thuật làm mờ/ẩn ô bổ sung để chống việc Giảng viên suy luận ngược danh tính sinh viên hỏi bài.
- **Xuất báo cáo tổng hợp PDF/Excel (Rule F6, O8):**
  - Admin có chức năng xuất báo cáo tổng hợp hoạt động học tập, tỷ lệ hoàn thành, phân bố điểm số theo định dạng PDF hoặc Excel để gửi cho Nhà trường.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria & QAS-11)
- [ ] Thử nghiệm chất lượng gợi ý (QAS-11): 50 tình huống học tập mẫu $\to$ Hệ thống đưa ra gợi ý phù hợp chủ đề yếu, có thể giải thích được lý do (traceable reasoning), và hiển thị "Chưa đủ dữ liệu" khi số lượng bài tập < ngưỡng tin cậy.
- [ ] Kiểm tra Rule O6: Lớp có 4 sinh viên hỏi AI $\to$ Giảng viên xem báo cáo chủ đề AI thấy hiển thị "Số lượng người tham gia chưa đủ để hiển thị thống kê tổng hợp (nhỏ hơn 5)". Khi có sinh viên thứ 5 hỏi $\to$ Số liệu tổng hợp mới xuất hiện.
- [ ] Xuất file: Admin gọi chức năng xuất báo cáo cho lớp $\to$ Sinh ra tệp PDF và Excel hợp lệ, mở được trên MS Excel / Adobe Acrobat, số liệu khớp với cơ sở dữ liệu.
- [ ] Tích hợp toàn diện: Toàn bộ hệ thống 5 microservices tương tác mượt mà qua các bài test tích hợp cuối cùng của giai đoạn G5.
