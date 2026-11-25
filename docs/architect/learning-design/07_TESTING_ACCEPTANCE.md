# 32 tiêu chí nghiệm thu — LRN-T09
Chưa chạy test. Mock và real evidence riêng; real AI bắt buộc nghiệm thu AI.
| ID | Điều kiện đạt |
|---|---|
| L-AC01 | Question CRUD đúng quyền |
| L-AC02 | Validate loại/đáp án/rubric |
| L-AC03 | Version bất biến khi đã sử dụng |
| L-AC04 | AI question validate và teacher review đề chính thức |
| L-AC05 | Publish đề hợp lệ |
| L-AC06 | Snapshot không đổi khi sửa question |
| L-AC07 | Policy riêng practice/assessment/assignment |
| L-AC08 | Chỉ teacher có quyền publish |
| L-AC09 | Server deadline/time limit |
| L-AC10 | Giới hạn lượt làm concurrent |
| L-AC11 | Autosave revision chống ghi đè |
| L-AC12 | Submit idempotent và khóa bài |
| L-AC13 | Concurrent submit/save không mất dữ liệu |
| L-AC14 | Restart/mất mạng recovery không vượt deadline |
| L-AC15 | Single choice exact grading |
| L-AC16 | Multiple choice exact set grading |
| L-AC17 | Essay AI proposal cần teacher confirm |
| L-AC18 | Sửa điểm audit và decimal/range |
| L-AC19 | Publish điểm đúng policy |
| L-AC20 | Student không đọc bài người khác |
| L-AC21 | RBAC/membership hiện hành, fail closed |
| L-AC22 | Không lộ answer key/rubric/điểm sớm |
| L-AC23 | Internal JWT sai scope/audience/expiry bị chặn |
| L-AC24 | D6 policy check trước xử lý/trả kết quả |
| L-AC25 | AI job durable restart |
| L-AC26 | Retry dedup, conflicting payload |
| L-AC27 | Validate AI schema/source/scope |
| L-AC28 | AI offline vẫn làm bài và chấm tự động |
| L-AC29 | Analytics đúng metric, thiếu dữ liệu không đánh đồng yếu |
| L-AC30 | Analytics giới hạn quyền |
| L-AC31 | Notification offline/recovery/dedup |
| L-AC32 | Real AI generation/grading và D6 integration |
Unit/contract/integration PostgreSQL/E2E/fault injection; static checks, no secrets, evidence, TL review; workload 358 user cần chốt. AC chi tiết hóa từ nhóm đã accepted, chưa verified.