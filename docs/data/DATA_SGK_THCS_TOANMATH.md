# Thu thập dữ liệu sách giáo khoa từ THCS ToanMath

## Mục đích
Thu thập sách giáo khoa (SGK) làm nguồn dữ liệu ban đầu cho Document Service và AI Tutor (RAG) — xem [TASK-017](../../tasks/TASK-017-document-service-design-impl.md), [TASK-018](../../tasks/TASK-018-ai-service-rag-tutor.md).

## Nguồn
- Website: THCS ToanMath — https://thcs.toanmath.com
- Cách làm: tìm kiếm và tải thủ công file SGK theo từng bộ sách, sắp xếp vào thư mục tương ứng.

## Nơi lưu trữ
Dữ liệu **không commit vào repo** (dung lượng lớn, bản quyền thuộc nhà xuất bản). Toàn bộ file lưu trên Google Drive:

**Thư mục `DataSGK`:** link nội bộ, không công khai trong repo — liên hệ người phụ trách dữ liệu hoặc xem kênh chat của nhóm. Thư mục chỉ chia sẻ cho thành viên nhóm.

| Bộ sách | Thư mục trên Drive |
|---|---|
| Cánh Diều | `DataSGK/CanhDieu` |
| Chân Trời Sáng Tạo | `DataSGK/ChanTroi` |
| Kết Nối Tri Thức với Cuộc Sống | `DataSGK/KetNoiTriThuc` |

## Thống kê dữ liệu đã tải
Kiểm tra trực tiếp thư mục Drive ngày 2026-11-06. Môn: **Toán**, lớp 6–12. Tất cả là file PDF, mỗi đầu sách gồm Tập 1 + Tập 2.

**Tổng: 74 file PDF = 37 đầu sách (SGK 21, SBT 15, Hướng dẫn giải 1).**

| Bộ sách | SGK (lớp) | Sách bài tập (lớp) | Khác | Số file |
|---|---|---|---|---|
| Cánh Diều | 6, 7, 8, 9, 10, 11, 12 | 6, 7, 10, 11, 12 | Hướng dẫn giải bài tập SGK Toán 8 | 26 |
| Chân Trời Sáng Tạo | 6, 7, 8, 9, 10, 11, 12 | 7, 8, 10, 11 | — | 22 |
| Kết Nối Tri Thức | 6, 7, 8, 9, 10, 11, 12 | 6, 7, 8, 9, 10, 11 | — | 26 |

Ma trận chi tiết (✓ = đủ 2 tập, ✗ = chưa có):

| Lớp | CD SGK | CD SBT | CTST SGK | CTST SBT | KNTT SGK | KNTT SBT |
|---|---|---|---|---|---|---|
| 6 | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| 7 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 8 | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| 9 | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ |
| 10 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 11 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 12 | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |

**Còn thiếu:** SBT Toán 8, 9 (Cánh Diều); SBT Toán 6, 9, 12 (Chân Trời); SBT Toán 12 (Kết Nối).

**Ghi chú đặt tên:** lớp 6 (và Hướng dẫn giải Toán 8 CD) giữ tên gốc từ website (`sach-giao-khoa-toan-6-tap-1-...pdf`); các lớp khác đặt dạng `SGK Toan <lớp> - Tap <n>.pdf` / `SBT Toan <lớp> - Tap <n>.pdf`. Nên thống nhất một quy ước trước khi đưa vào pipeline.

## Lưu ý sử dụng
- SGK thuộc bản quyền nhà xuất bản; chỉ dùng cho mục đích học tập/nghiên cứu trong đồ án, không phân phối lại.
- Quyền truy cập thư mục Drive do người thu thập quản lý; xin quyền nếu cần.
- Chưa xử lý (trích xuất văn bản, chia chunk, embedding); bước này thuộc Document/AI Service khi bắt đầu G3.
