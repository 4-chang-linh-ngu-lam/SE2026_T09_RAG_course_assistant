# PHẠM VI THIẾT KẾ CHI TIẾT CỦA CÁC DỊCH VỤ CHƯA TRIỂN KHAI

**Mã tài liệu:** LUMI-LLD-FUT-001 · **Trạng thái:** Chưa phê duyệt thiết kế chi tiết.

Các dịch vụ Quản lý tài liệu, Học tập và Phân tích học tập chưa có triển khai phía máy chủ tại mốc đối chiếu. Vì vậy, hồ sơ chuẩn **không ban hành mô hình cơ sở dữ liệu vật lý, API hoặc cấu hình hạ tầng** cho các dịch vụ này.

## Nội dung được quyết định ở mức nghiệp vụ

- Quản lý tài liệu: xem [Đặc tả chức năng tài liệu](04_FRS_Document.md), các quy tắc B1–B7, H3, H6, L6 và O1–O2.
- Học tập: xem [Đặc tả chức năng học tập](05_FRS_Learning.md), các quy tắc D0–D8, I1–I7, M1–M4 và O3–O5.
- Phân tích học tập: xem [Đặc tả chức năng phân tích](06_FRS_Intelligence.md), các quy tắc E1–E6, J1–J5 và O6–O8.
- Ranh giới trách nhiệm được mô tả trong [kiến trúc tổng thể](08_HLD.md) và [sơ đồ các phân hệ](21_ARCHITECTURE_ATLAS.md).

## Điều kiện thiết kế chi tiết

Trước khi chuyển từ đặc tả nghiệp vụ sang thiết kế triển khai, mỗi dịch vụ cần có quyết định về mô hình dữ liệu, quyền truy cập, giao tiếp giữa dịch vụ, xử lý lỗi, cơ chế phục hồi, bảo mật, phương án triển khai và bộ kiểm thử. Mọi nội dung đề xuất phải có người phê duyệt và được kiểm tra đối chiếu với quy tắc nghiệp vụ hiện hành.

**Dịch vụ trí tuệ nhân tạo không thuộc phạm vi thiết kế của bộ hồ sơ này.**
