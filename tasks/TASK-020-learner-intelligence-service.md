# TASK-020: Learner Intelligence Service & MVP Reporting (G5)

- **Mã Task:** `TASK-020`
- **Giai đoạn:** `G5 — Learner Intelligence + Hoàn thiện MVP`
- **Owner chính:** Phụ trách Service Learner Intelligence & Tích hợp MVP
- **Business Rules liên quan:** `E1-E6`, `F6`, `J1-J5`, `O6`, `O8`, `QAS-11`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#e-analytics), [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#qas-11--chất-lượng-gợi-ý-recommendation-quality), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** chưa có Learner Intelligence hoặc báo cáo liên service. Model/score/weight/confidence bên dưới là draft, không phải thuật toán/schema đã được duyệt.

**Cần sửa/bổ sung:**
- Chốt thiết kế evidence/provenance/version, API/event contracts và mô hình đánh giá sau Core G2, Document/AI G3 và Learning G4; không đọc SQL service khác.
- Thu nhận bằng chứng idempotent, xử lý duplicate/out-of-order và grade correction đã xác nhận mới nhất (J3); giữ lịch sử khi chuyển lớp, tách practice/chính thức.
- “Đủ bằng chứng” cần độc lập và bao phủ chủ đề, không chỉ đếm bài hoặc tin nhắn. Trọng số/ngưỡng mastery phải được đánh giá/phê duyệt, không tự biến số draft thành rule.
- Giới hạn teacher analytics theo assignment/trường/lớp, student chỉ xem dữ liệu mình; không dùng raw private chat. Thống kê chủ đề AI chỉ tổng hợp và ẩn nhóm dưới 5 học sinh tham gia phân biệt, có complementary suppression chống suy luận ngược; đủ 5 không tự bảo đảm công bố an toàn.
- Gợi ý tự nguyện, diễn đạt “Chủ đề cần ôn tập/Chưa đủ dữ liệu”; cảnh báo tự động nâng cao thuộc Future/conditional, không thêm vào MVP bắt buộc hoặc dùng để tự chấm điểm/kỷ luật.
- Admin xuất báo cáo tổng hợp PDF/Excel cho nhà trường, có scope/audit/redaction và kiểm tra quyền khi tải. Không thêm tài khoản Nhà trường/Phụ huynh; yêu cầu dữ liệu/retention phối hợp TASK-013 theo policy được duyệt.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TASK-013/017–019 và Core access contracts cung cấp dữ liệu được phép; thiết kế/evaluation được review trước triển khai.
- [ ] Test grade sửa/event lặp/sai thứ tự, transfer/history, cross-school/owner-only và suppression cả dashboard/PDF/Excel.
- [ ] QAS-11 ít nhất 50 tình huống giáo viên đánh giá có bằng chứng/giải thích/thiếu dữ liệu; QAS-09 thay mô hình không sửa luồng nộp/chấm Learning.
- [ ] Báo cáo PDF/Excel khớp dữ liệu hợp lệ, không lộ nhóm nhỏ/private chat; tích hợp G5 và tiêu chí chất lượng đo thật, không tuyên bố trước khi chạy.

---

## 1. Mục tiêu
Thiết kế và triển khai Learner Intelligence Service (`services/learner_intelligence/`) độc lập trong monorepo, xây dựng mô hình thu thập bằng chứng học tập (learning evidence), ước lượng mức độ nắm vững chủ đề (mastery snapshots), hệ thống gợi ý học tập (recommendations) mang tính hỗ trợ, thực hiện quy tắc bảo vệ riêng tư nhóm nhỏ (< 5 sinh viên), và hoàn thiện tính năng xuất báo cáo tổng hợp PDF/Excel cho Nhà trường thông qua Admin.

---

## 2. Bản nháp kỹ thuật — cần thiết kế và review trước triển khai

### 2.1. Mô hình dữ liệu tham khảo — chưa chốt schema vật lý
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
- [ ] Thử nghiệm chất lượng gợi ý (QAS-11): 50 tình huống học tập mẫu $\to$ Hệ thống đưa ra gợi ý phù hợp chủ đề yếu, có thể giải thích được lý do (traceable reasoning), và hiển thị "Chưa đủ dữ liệu" khi thiếu bằng chứng độc lập hoặc độ bao phủ theo mô hình được duyệt.
- [ ] Kiểm tra Rule O6: Lớp có 4 sinh viên hỏi AI $\to$ Giảng viên xem báo cáo chủ đề AI thấy hiển thị "Số lượng người tham gia chưa đủ để hiển thị thống kê tổng hợp (nhỏ hơn 5)". Khi có học sinh thứ 5 hỏi, chỉ hiển thị nếu kiểm tra rủi ro tái định danh và complementary suppression cho phép.
- [ ] Xuất file: Admin gọi chức năng xuất báo cáo cho lớp $\to$ Sinh ra tệp PDF và Excel hợp lệ, mở được trên MS Excel / Adobe Acrobat, số liệu khớp với cơ sở dữ liệu.
- [ ] Tích hợp toàn diện: Toàn bộ hệ thống 5 microservices đáp ứng contract và các tiêu chí đo đã duyệt qua test tích hợp cuối cùng của giai đoạn G5.
