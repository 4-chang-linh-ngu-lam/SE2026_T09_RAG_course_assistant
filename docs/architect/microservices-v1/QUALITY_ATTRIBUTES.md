# Microservices v1 — Thuộc tính chất lượng và tiêu chí nghiệm thu

**Phiên bản:** 1.0.0-draft | **Ngày:** 10/10/2026 | **Trạng thái:** Đã chốt mức ưu tiên; ngưỡng đo còn là đề xuất.

**Kiến trúc liên quan:** [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Cấu hình kiểm thử TP-01
100 người dùng đồng thời, 10 lớp, 50 sinh viên mỗi lớp, 20 tài liệu mỗi lớp, tệp trung bình 10 MB, 30 câu mỗi bài đánh giá; đo tải ổn định trong 10 phút sau khi khởi động. Khi thử nghiệm phải ghi cấu hình CPU/RAM, cơ sở dữ liệu, hàng đợi, mạng, vùng triển khai và mô hình AI. Đây là **tải kiểm thử mục tiêu**, không phải số liệu năng lực thực tế.

Mỗi kịch bản gồm: **Nguồn tác động, Sự kiện, Môi trường, Thành phần chịu tác động, Phản ứng mong đợi, Chỉ số đo**.

## 2. Kịch bản ưu tiên P0
### QAS-01 — Tính sẵn sàng (Availability)
- **Nguồn/sự kiện:** nhà cung cấp mô hình ngôn ngữ không phản hồi trong 60 giây.
- **Môi trường/thành phần:** TP-01; AI và các chức năng không phụ thuộc AI.
- **Phản ứng:** trợ giảng thông báo tạm thời không khả dụng; xem tài liệu đã sẵn sàng, quản lý lớp và nộp bài vẫn hoạt động.
- **Đo:** mọi yêu cầu hợp lệ không phụ thuộc AI trong bài thử lỗi có kiểm soát hoàn thành; không có lỗi máy chủ do sự cố AI; độ trễ đạt QAS-05.

### QAS-02 — Cô lập lỗi (Fault Isolation)
- **Nguồn/sự kiện:** người vận hành dừng cưỡng bức tiến trình AI hoặc AI sử dụng hết tài nguyên được cấp.
- **Môi trường/thành phần:** TP-01; Learning API.
- **Phản ứng:** lỗi không lan sang Learning; không cần khởi động lại Learning.
- **Đo:** ít nhất 99% yêu cầu Learning hợp lệ thành công và đáp ứng QAS-05.

### QAS-03 — Toàn vẹn dữ liệu (Data Integrity)
- **Nguồn/sự kiện:** gửi đồng thời nhiều lần nộp bài, mất phản hồi sau khi lưu, sự kiện được phát lại.
- **Môi trường/thành phần:** Learning và dữ liệu năng lực.
- **Phản ứng:** một lần nộp hợp lệ theo phạm vi khóa chống lặp; không nhân đôi điểm hay bằng chứng.
- **Đo:** không có bản ghi nghiệp vụ trùng hoặc mất trong ít nhất 1.000 tình huống thử lại/cạnh tranh có kiểm soát; đối soát đúng.

### QAS-04 — Bảo mật và quyền riêng tư (Security & Privacy)
- **Nguồn/sự kiện:** sinh viên thay mã lớp, tài liệu, bài làm, người dùng; quyền tài liệu bị thu hồi.
- **Môi trường/thành phần:** API, truy hồi, mở nguồn.
- **Phản ứng:** từ chối truy cập trái phép, không đưa nguồn không có quyền vào lời nhắc mô hình; từ chối khi không xác minh được quyền.
- **Đo:** 100% trường hợp trái phép trong bộ kiểm thử bị chặn; không rò rỉ dữ liệu xuyên lớp; quyền thu hồi được thực thi tại lần kiểm tra mới.

### QAS-05 — Hiệu năng (Performance)
- **Nguồn/sự kiện:** TP-01 tạo tải thao tác hỗn hợp.
- **Môi trường/thành phần:** API nghiệp vụ hoạt động bình thường.
- **Phản ứng/đo:** độ trễ bách phân vị 95 (p95) từ khi Backend nhận đến khi hoàn thành phản hồi:
  - Danh sách lớp: không quá **500 ms**.
  - Tải bài luyện tập: không quá **1.000 ms**.
  - Lưu câu trả lời: không quá **1.000 ms**.
  - Nộp bài đánh giá: không quá **2.000 ms**.
  - Đọc mô hình năng lực đã tính sẵn: không quá **1.000 ms**.
  - Ít nhất **99%** yêu cầu hợp lệ thành công.
- Thời gian token đầu tiên, tổng thời gian AI, độ chính xác truy hồi và chi phí được đo riêng; chưa đặt ngưỡng cứng khi chưa chốt mô hình/hạ tầng.

### QAS-06 — Chất lượng RAG (RAG Quality)
- **Nguồn/sự kiện:** ít nhất 100 câu hỏi gồm có đáp án, thiếu bằng chứng, nhiều nguồn và nguồn không được phép.
- **Môi trường/thành phần:** hệ thống truy hồi và trợ giảng AI.
- **Phản ứng:** trả lời dựa trên bằng chứng được cấp quyền, trích dẫn đúng hoặc nói rõ khi không đủ dữ liệu.
- **Đo đề xuất:** độ đúng trích dẫn ≥90%; mức độ bám sát nguồn ≥90%; từ chối trả lời đúng khi thiếu chứng cứ ≥90%; không rò rỉ dữ liệu xuyên lớp trong bộ kiểm thử.

## 3. Kịch bản ưu tiên P1
### QAS-07 — Khả năng mở rộng (Scalability)
Lưu lượng AI tăng gấp 3 trong khi Learning vẫn ở tải TP-01. Có thể tăng năng lực xử lý AI mà không triển khai lại Learning. Đo thông lượng, độ trễ AI và p95 Learning trước/sau khi tăng tài nguyên; Learning vẫn phải đạt QAS-05. Chưa giả định tốc độ tăng tuyến tính.

### QAS-08 — Khả năng triển khai độc lập (Deployability)
Nhà phát triển phát hành phiên bản AI mới qua CI/CD. Không cần thay đổi ảnh đóng gói hoặc triển khai lại Learning. Kiểm thử hợp đồng và kiểm thử nhanh phải đạt; ghi thời gian triển khai.

### QAS-09 — Khả năng thay đổi (Modifiability)
Thay thuật toán ước lượng năng lực trong Learner Intelligence mà không sửa mã nộp bài/chấm điểm của Learning. Kiểm thử hợp đồng và đối soát bằng chứng đạt.

### QAS-10 — Khả năng phục hồi (Recoverability)
Tiến trình xử lý tài liệu lỗi giữa lúc lập chỉ mục. Tệp gốc và phiên bản hợp lệ trước đó vẫn còn; thử lại an toàn; không công bố chỉ mục chưa hoàn chỉnh. Đo thời gian phục hồi và độ trễ hàng đợi. RPO/RTO cụ thể chưa chốt.

### QAS-11 — Chất lượng gợi ý (Recommendation Quality)
Tối thiểu 50 tình huống học tập do giảng viên kiểm tra. Gợi ý phải phù hợp chủ đề yếu, có bằng chứng, có thể giải thích và không kết luận năng lực khi dữ liệu thiếu. Báo cáo mức phù hợp, khả năng truy vết bằng chứng và từ chối khi thiếu dữ liệu. Ngưỡng phần trăm chờ phê duyệt thang chấm.

## 4. Bộ thử nghiệm kiến trúc
| Mã | Thử nghiệm | Mục tiêu |
|---|---|---|
| FT-01 | Dừng AI | Kiểm tra Learning, tài liệu và lớp vẫn hoạt động |
| FT-02 | Nộp bài trùng đồng thời | Không tạo trùng bài nộp, điểm và bằng chứng |
| FT-03 | Truy cập chéo lớp, thu hồi quyền giữa truy hồi | Không đưa nội dung trái phép vào mô hình |
| FT-04 | Chỉ triển khai AI | Không triển khai lại Learning, hợp đồng tương thích |
| FT-05 | Dừng tiến trình lập chỉ mục | Không mất tệp, không công bố chỉ mục dở dang |
| FT-06 | Phát sự kiện sửa điểm sai thứ tự | Chỉ phiên bản điểm mới nhất có hiệu lực |
| FT-07 | Ngắt nguồn xác minh quyền | Thao tác nhạy cảm từ chối an toàn |

## 5. Quy trình nghiệm thu
1. Nhóm review kịch bản và cách đo.
2. Duyệt hoặc điều chỉnh các ngưỡng dự kiến và cấu hình môi trường.
3. Triển khai đo đạc, kiểm thử lỗi, tải, bảo mật và đánh giá RAG.
4. Lưu kết quả thực tế, bằng chứng và sai lệch; chỉ đánh dấu **đã kiểm chứng** khi có kết quả.

**Lưu ý:** 0 lỗi trong một bộ kiểm thử hữu hạn không chứng minh hệ thống tuyệt đối không thể xảy ra lỗi.
