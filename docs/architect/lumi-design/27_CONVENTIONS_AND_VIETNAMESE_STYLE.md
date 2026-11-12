# QUY CHUẨN TRÌNH BÀY VÀ THUẬT NGỮ CỦA HỒ SƠ THIẾT KẾ LUMI

| Thuộc tính | Nội dung |
|---|---|
| Mã tài liệu | LUMI-STYLE-002 |
| Trạng thái | Quy ước biên soạn đề xuất để nhóm rà soát |
| Phạm vi | Tất cả tài liệu trong bộ hồ sơ thiết kế phiên bản 2.1 |

## 1. Nguyên tắc diễn đạt

Tài liệu sử dụng tiếng Việt trang trọng, khách quan và nhất quán. Mỗi phần phải nêu rõ **mục đích, căn cứ, thiết kế và kết quả mong đợi**. Tránh cách diễn đạt mang tính trao đổi, khẩu ngữ hoặc khẳng định vượt quá bằng chứng. Một công việc đang được đề xuất không được trình bày như chức năng đã vận hành.

Trong các chương kiến trúc tổng thể và yêu cầu nghiệp vụ, ưu tiên tên nghiệp vụ dễ hiểu như **quản lý tài khoản**, **quản lý lớp học**, **bảng tin**, **thông báo**, **cơ sở dữ liệu**, **tác vụ nền**, **giao tiếp giữa các dịch vụ**. Tên mô-đun hoặc tên lớp trong mã nguồn chỉ được đưa vào khi cần xác định chính xác trách nhiệm triển khai hoặc lập đường dẫn đối chiếu.

Các thuật ngữ quốc tế đã trở thành quy ước của ngành như **API, REST, HTTP, PostgreSQL, Docker Compose, CI/CD, ERD, DFD, HLD và LLD** được giữ nguyên, có giải thích lần đầu sử dụng tại các phần dành cho người đọc không chuyên kỹ thuật. Không dịch tên công nghệ, tên thư viện hoặc đường dẫn mã nguồn.

## 2. Bảng thuật ngữ khuyến nghị

| Nên dùng trong phần thuyết minh | Hạn chế dùng thay thế | Ghi chú |
|---|---|---|
| Giao diện web | frontend | Có thể viết “Next.js” khi mô tả công nghệ |
| Phía máy chủ / dịch vụ ứng dụng | backend | “Core” là tên riêng của dịch vụ lõi |
| Phân hệ | component, module | Tên kỹ thuật dùng tại phần thiết kế chi tiết |
| Quy trình xử lý / luồng nghiệp vụ | workflow | Giữ “workflow” trong tên công cụ hoặc câu lệnh |
| Cơ sở dữ liệu | DB | Giữ `DATABASE_URL` trong mô tả cấu hình |
| Dữ liệu giả lập | mock, synthetic | Phân biệt “dữ liệu giả lập” với “trình mô phỏng API” |
| Môi trường phát triển | local/dev | Docker Compose là công nghệ triển khai cụ thể |
| Môi trường thử nghiệm tích hợp | staging | Viết “staging” trong bảng đối chiếu tên môi trường nếu cần |
| Môi trường giả lập triển khai chính thức | production mock | Không được nhầm với vận hành cho người dùng thật |
| Phương án đề xuất / chưa phê duyệt | proposed/pending | Có thể kèm nhãn trạng thái trong bảng |
| Bằng chứng kiểm thử | test evidence | Ghi mã báo cáo hoặc lệnh kiểm thử để truy vết |
| Ranh giới tin cậy | trust boundary | Khi trình bày biện pháp an toàn thông tin |
| Khả năng phục hồi và khôi phục | recovery/rollback | Phân biệt khôi phục dữ liệu với trở lại phiên bản phần mềm |
| Tỷ lệ phần trăm thứ 95 về độ trễ | p95 | Có thể dùng “độ trễ p95” sau lần giải thích đầu tiên |

## 3. Quy tắc đặt tên sơ đồ

Một sơ đồ chỉ mô tả một góc nhìn chính; tiêu đề nêu rõ nội dung và phạm vi. Chẳng hạn: **A03 — Kiến trúc tổng thể theo tầng xử lý**, **A06 — Mô hình triển khai tại máy phát triển**, **A08 — Mô hình triển khai trên nền tảng đám mây**, **A14 — Chuỗi môi trường thực nghiệm**.

Ngay sau sơ đồ phải có lời thuyết minh: các đối tượng được thể hiện, trách nhiệm của từng khối, hướng luân chuyển yêu cầu hoặc dữ liệu, ranh giới giữa các khối, trạng thái triển khai và nguồn đối chiếu. Nếu hình dùng đường nét đứt, giải thích rõ phần tương lai hoặc chưa xác minh.

## 4. Cách ghi nhận kết quả và giới hạn

- **Đã quyết định:** có căn cứ trong quy tắc nghiệp vụ hoặc quyết định kiến trúc.
- **Đã triển khai:** có mã nguồn, có thể xác định tại một commit cụ thể.
- **Đã kiểm chứng:** có báo cáo kiểm thử và môi trường phù hợp; không suy rộng kết quả sang môi trường khác.
- **Đề xuất:** có phương án thiết kế nhưng chưa được phê duyệt.
- **Chưa xác định:** chưa đủ thông tin; không tự điền số liệu cấu hình, chi phí, năng lực phục vụ hoặc chính sách lưu giữ dữ liệu.

Mọi kết quả kiểm thử phải ghi ngày, mã nguồn tham chiếu, cấu hình môi trường, phương pháp đo, dữ liệu thử nghiệm và giới hạn sử dụng. Không được gộp “biên dịch thành công”, “kiểm thử tự động thành công” và “nghiệm thu người dùng” thành một trạng thái.

## 5. Kiểm tra chất lượng ngôn ngữ trước khi phát hành

1. Mỗi chương có mở đầu nêu nội dung và phạm vi; tiêu đề thống nhất về cấp độ.
2. Không lạm dụng từ tiếng Anh khi có thuật ngữ tiếng Việt tương đương và không gây mơ hồ.
3. Không để tên lớp, hàm hoặc biến xuất hiện trong tiêu đề kiến trúc tổng thể, trừ khi đó là giao diện chính thức.
4. Các bảng có đơn vị, căn cứ và ghi chú về trạng thái áp dụng.
5. Các sơ đồ có chú thích; mọi sơ đồ mang tính đề xuất được phân biệt với hiện trạng.
6. Đoạn mô tả không chép nguyên văn tài liệu doanh nghiệp tham khảo; chỉ vận dụng cấu trúc và phương pháp.
7. Kiểm tra chính tả, dấu tiếng Việt, tên vai trò và cách viết tắt trước khi kết xuất Word/PDF.