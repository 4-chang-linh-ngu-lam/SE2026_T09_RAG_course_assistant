# FRS-LEARNER INTELLIGENCE — BẰNG CHỨNG, TIẾN ĐỘ, BÁO CÁO

**Mã:** LUMI-FRS-LI-001 · **Trạng thái:** **PROPOSED / DESIGN REVIEW REQUIRED**, chưa có Learner Intelligence Service theo TASK-020.

## 1. Nguồn dữ liệu được dùng trong đợt này

Chỉ đặc tả evidence từ nguồn Learning có provenance đã xác nhận: Practice result, Assessment result và Assignment result. Không đặc tả AI messages, chat topics, embedding hay AI-derived evidence. Chính sách nhóm nhỏ O6 được giữ như ràng buộc nếu về sau có loại thống kê tương ứng, nhưng **không triển khai nguồn AI**.

## 2. FRS-LI01 — Tiếp nhận và đối soát evidence

- Producer Learning phát kết quả có `source_type`, `source_id`, `version`, `student_id`, `class_id`, `topic_id` và thời điểm.
- Consumer xác thực nguồn và quyền, xử lý idempotent event ID, dedup theo source/version; không nhân đôi bằng chứng khi replay.
- Grade correction version mới thay effective value nhưng không xóa provenance/history; out-of-order revision cũ không ghi đè revision mới.
- Practice và official grade không tự gộp cùng trọng số nếu chưa có mô hình được duyệt.
- **AC:** LI-T01–LI-T04.

## 3. FRS-LI02 — Xác định đủ dữ liệu

- Mỗi ước lượng topic phải truy vết evidence độc lập, coverage của topic và thời điểm quan sát; không dùng số lần cùng một câu hỏi để tăng tự tin.
- Nếu thiếu bằng chứng, hiển thị đúng thông điệp **“Chưa đủ dữ liệu”** thay vì điểm mastery định lượng.
- Thuật toán, trọng số, ngưỡng evidence/coverage/confidence phải qua thiết kế và đánh giá; không tự áp dụng ngưỡng tùy ý từ code mẫu.
- **AC:** LI-T05–LI-T07.

## 4. FRS-LI03 — Gợi ý hỗ trợ

- Đưa ra “Chủ đề cần ôn tập”/bài Practice hoặc tài liệu có quyền; hiển thị lý do từ evidence được phép.
- Student có quyền bỏ qua. Không tự đánh giá đạo đức, kỷ luật hoặc tự sửa điểm.
- Nếu evidence thiếu, chỉ gợi ý hoạt động bổ sung dữ liệu trung tính; không khẳng định học sinh yếu.
- Không mặc định cá nhân hóa dựa trên chat riêng tư.
- **AC:** LI-T08–LI-T10.

## 5. FRS-LI04 — Dashboard

| Đối tượng | Dữ liệu | Điều kiện |
|---|---|---|
| Student | Điểm/kết quả/historic/practice/evidence của mình | Owner-only; source access theo quyền |
| Lecturer | Thống kê lớp và tiến độ học sinh được phép | Teacher assignment và class scope hiện hành, ngoại lệ lịch sử được duyệt |
| Admin | Tổng hợp trường/khối/lớp và báo cáo đã cấp phép | School scope, audit mỗi thao tác export |

Không để UI quyết định quyền truy xuất; aggregation phải thực hiện suppression trên server trước khi trả JSON/file.

## 6. FRS-LI05 — Privacy suppression

- O6 quy định thống kê chủ đề liên quan AI Tutor ẩn với **<5 người tham gia phân biệt**, sau đó áp dụng complementary suppression để chống suy luận ngược. Vì nguồn AI hoãn, đây là constraint bảo lưu, không phải tính năng đang chạy.
- Với mọi thống kê nhạy cảm khác, privacy threshold là **PENDING POLICY**; không áp dụng mặc định 5 cho mọi loại dữ liệu nếu chưa duyệt.
- Không tiết lộ raw private chat, token hay định danh nhóm nhỏ trong export.
- **AC:** LI-T11–LI-T13 (khi nguồn tương ứng khả dụng).

## 7. FRS-LI06 — Xuất PDF/Excel

- **Actor:** Admin cùng trường; chỉ dữ liệu aggregate đã qua permission/suppression.
- **Flow:** chọn phạm vi báo cáo → xem preview mô tả phạm vi → yêu cầu export → hệ thống sinh file → kiểm tra quyền tại download → audit actor/filter/time.
- **Validation:** định dạng PDF/Excel; formula injection mitigation khi export workbook; không nhúng raw chat; không dùng đường dẫn công khai không hạn/không kiểm soát.
- **Error:** quá ít dữ liệu, nguồn không khả dụng, job timeout, actor mất quyền sau khi bắt đầu.
- **AC:** LI-T14–LI-T16.

## 8. Cần chốt trước triển khai

- Topic taxonomy, evidence identity & version semantics, algorithm/threshold/validation dataset, fairness và coverage.
- API service credential, source allowlist, retention và deletion coordination.
- Quyền truy cập lịch sử sau chuyển lớp; dashboard teacher khi mất assignment.
- Xuất báo cáo và suppression khi nhiều bộ lọc cho phép suy luận ngược; audit tải file.

Không tuyên bố QAS-11 đạt cho tới khi đánh giá ít nhất 50 tình huống được giáo viên duyệt và công bố số liệu thật.