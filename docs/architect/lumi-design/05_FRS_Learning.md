# FRS-LEARNING — PRACTICE, ASSESSMENT, ASSIGNMENT

**Mã:** LUMI-FRS-LE-001 · **Trạng thái:** **PROPOSED / DESIGN REVIEW REQUIRED**, chưa có Learning Service theo TASK-019.

## 1. Tách ba nghiệp vụ

| Thuộc tính | Practice | Assessment chính thức | Assignment |
|---|---|---|---|
| Mục tiêu | Ôn luyện, phản hồi ngay | Đánh giá có phê duyệt | Bài tập giáo viên giao |
| Điểm | Không phải điểm chính thức | Điểm có thể công bố sau quy trình duyệt | Giáo viên quyết định điểm cuối |
| Phiên bản | Lưu revision được sử dụng để giải thích | Attempt gắn đề version bất biến | Giữ đề/rubric/bài nộp phiên bản tương ứng |
| Hạn và số lượt | Theo cấu hình | Theo cấu hình và chính sách chặt hơn | Hỗ trợ nộp lại/nộp muộn theo chính sách |
| Căn cứ | D0,D3,D8 | D1,D2,D4,D7,I1–I4,O3 | D5,I5,M3,O5 |

## 2. FRS-L01 — Soạn và công bố nội dung

- Giáo viên được phân công tạo nháp, định nghĩa loại bài, title, mô tả, câu hỏi, topic và time/due policy; validation theo hợp đồng đã duyệt.
- Hỗ trợ single-choice, multiple-choice, true/false và short answer. Không áp dụng công thức điểm mặc định nếu chưa duyệt.
- Assessment công bố chính thức bắt buộc PRIMARY phê duyệt; ASSISTING chỉ được tạo nháp/đề xuất/chấm phần đã phân công.
- Nội dung do công cụ bên ngoài hỗ trợ tạo, nếu xuất hiện ở tương lai, vẫn phải được giáo viên duyệt; bộ tài liệu này không thiết kế AI.
- Khi publish, đóng băng version; sửa sau publish tạo version mới, không mutate ngầm attempt cũ.
- **AC:** LE-T01–LE-T04.

## 3. FRS-L02 — Attempt, save/resume và timer

- Tạo attempt cho student được phép theo class/member state và thời điểm; lưu `assessment_version_id` bất biến.
- Nút Lưu/tiếp tục phải ghi server acknowledgment; client không được đánh dấu “Đã lưu” trước response thành công.
- Mất mạng: dữ liệu đã được server xác nhận vẫn tồn tại; dữ liệu chưa ACK được hiển thị là chưa đồng bộ.
- Khi hết thời gian theo clock authoritative của server, auto-submit **những câu trả lời đã lưu thành công**, không dùng state chưa đồng bộ để tạo điểm.
- Retry/double-click submit dùng idempotency và uniqueness theo attempt; không sinh hai submission/grade.
- **AC:** LE-T05–LE-T09.

## 4. FRS-L03 — Chấm điểm và phê duyệt

- Câu khách quan auto-grade theo answer key đã duyệt; câu chủ quan và Assignment cần giáo viên được phân công chấm/duyệt.
- PRIMARY duyệt các quyết định nhạy cảm: publish Assessment, sửa/hủy điểm đã công bố, xử lý đề sai.
- ASSISTING có thể đề xuất và chấm theo assignment hiện hành; không tự phê duyệt chính thức.
- Mọi grade correction có `version`, actor, lý do hợp lệ, thời điểm, before/after và audit. Analytics chỉ tiêu thụ revision xác nhận mới nhất.
- Admin can thiệp ngoại lệ có lý do/audit chứ không mặc định thành giáo viên chính.
- **AC:** LE-T10–LE-T14.

## 5. FRS-L04 — Assignment, late policy và resubmission

- Giáo viên cấu hình thời hạn, số lượt nộp lại, bản được chấm, nộp muộn và cách tính điểm theo policy được duyệt.
- Học sinh chỉ submit nếu đủ quyền, đúng phiên bản giao bài và thời gian/attempt policy.
- Gia hạn áp dụng cho lần nộp tương lai, không tự sửa bài đã nộp hoặc lượt đã dùng; thông báo deadline đã đổi.
- Không tự đặt phạt %/ngày hoặc mặc định “bản mới nhất” nếu người dùng chưa quyết định.
- **AC:** LE-T15–LE-T18.

## 6. FRS-L05 — Transfer, archive và historical access

- Khi membership kết thúc, block hoạt động mới của lớp cũ, nhưng giữ bài đã nộp/điểm/phúc khảo hợp lệ.
- Lecturer có assignment hợp lệ để chấm bài đã nộp trước transfer; action `grade_submitted_work` cần contract riêng.
- Chính sách attempt IN_PROGRESS khi transfer phải chốt cutoff: allow finish, close hoặc transfer? Không tự đoán.
- Học sinh yêu cầu xem xét điểm trong thời hạn phúc khảo được phê duyệt, không tự suy ra vô thời hạn.
- **AC:** LE-T19–LE-T22.

## 7. FRS-L06 — Deadline và bản chiếu Calendar

- Learning là nguồn `due_at`, `published_at`, `version` của bài; Core Calendar chỉ chứa projection có source/version và không được sửa qua Core calendar CRUD.
- Thay deadline phát event versioned, consumer dedup/out-of-order; không xóa trạng thái đã nộp.
- Notification gắn audience và quyền tại thời điểm phát, không dùng danh sách người nhận khác thời điểm.
- **AC:** LE-T23–LE-T25.

## 8. Các quyết định mở

- Mô hình question/rubric/schema; quy ước grading, điểm scale và answer key; phương án xử lý bài sai công bằng.
- Thời gian auto-submit khi device offline hoàn toàn; server job vs lazy close; timeout/retry cutoff.
- Nguồn phiên bản, policy nộp lại, phúc khảo, giới hạn file, anti-malware.
- Contract chuyển lớp với pending attempts, late policy và classroom access.
- Hợp đồng event sang Calendar/Notification/Intelligence; không đọc SQL service khác.

**Không code service dựa trên các field trong TASK-019 trước khi review schema và API proposal.**