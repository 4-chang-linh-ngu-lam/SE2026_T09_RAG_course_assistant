# Lộ trình triển khai Microservices — Core-first

**Trạng thái:** [ĐỀ XUẤT] kế hoạch triển khai; **[ĐÃ CHỐT]** định hướng Microservices. **Ngày:** 11/10/2026.

> Tài liệu dành cho nhóm 4 sinh viên. Các giai đoạn là increment có thể demo, không phải thay đổi quy tắc nghiệp vụ. [BUSINESS_RULES.md](../BUSINESS_RULES.md) là nguồn nghiệp vụ có hiệu lực; [ARCHITECTURE.md](ARCHITECTURE.md) là kiến trúc tổng quan; [QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md) là tiêu chí chất lượng. Tech stack tại Architecture mục 10 vẫn [ĐỀ XUẤT].

## 1. Cách đọc
- **Làm gì?** Một lát cắt có UI → API → dữ liệu → kiểm thử.
- **Xong khi nào?** Có demo end-to-end, test tự động và người khác có thể chạy theo README.
- **Chưa làm?** Không tự coi tính năng chưa triển khai là đã được kiểm chứng.
- Mỗi giai đoạn có thể chia nhiều PR nhỏ, tích hợp liên tục; không chờ hoàn thiện toàn bộ sản phẩm mới thử nghiệm.

## 2. Lộ trình
| Giai đoạn | Phạm vi chính | Kết quả kiểm chứng | Điều kiện chuyển giai đoạn |
|---|---|---|---|
| **G1 — Core chức năng** | Tài khoản, vai trò, lớp, yêu cầu tham gia/duyệt, đồng giảng viên, rời/loại thành viên, chuyển chủ, lưu trữ/khôi phục; audit quyền tối thiểu | Người dùng thao tác được từ Web đến Core và DB | API có contract; test phân quyền và nghiệp vụ trọng tâm đạt; demo thành công |
| **G2 — Tích hợp Core** | Gateway, Docker Compose, migration, CI, test tích hợp, log, health check, kiểm thử lỗi | Một lệnh dựng môi trường, chạy được bộ test và demo trên máy khác | Tái lập được triển khai, không rò quyền giữa lớp, có hướng dẫn và bằng chứng kiểm thử |
| **G3 — Document + AI** | Thư viện giảng viên, chia sẻ, phiên bản, xử lý tài liệu, RAG Tutor theo lớp, trích dẫn và từ chối khi thiếu căn cứ | Hỏi đáp trên tài liệu được phép, thu hồi quyền có hiệu lực | Test quyền hiện hành, lỗi xử lý, chỉ mục và đánh giá RAG theo QAS liên quan |
| **G4 — Learning** | Practice, Assessment, Assignment, nộp bài, chấm/sửa điểm và lịch sử | Luồng học tập và đánh giá không phụ thuộc AI khi nộp/chấm | Test deadline, idempotency, phiên bản đề, audit và lỗi AI |
| **G5 — Learner Intelligence** | Bằng chứng, mastery, dashboard, gợi ý | Gợi ý dựa trên bằng chứng, không kết luận khi thiếu dữ liệu | Test cập nhật điểm sửa, chống sự kiện trùng/sai thứ tự, ẩn thống kê nhóm nhỏ |

**Lưu ý phạm vi Core:** Bảng tin, bình luận, lịch, thông báo, ghi chú và quản trị mở rộng thuộc phạm vi MVP đã thống nhất nhưng có thể chia thành increment sau G2, trước khi tuyên bố hoàn thành toàn bộ Core/MVP. Hoãn thứ tự triển khai **không đồng nghĩa loại bỏ** các yêu cầu G1–G5, F1–F7, K1–K6. Cần ghi rõ backlog và kiểm tra dependency trước khi tích hợp Document/AI.

## 3. Phân công nhóm 4 người — [ĐỀ XUẤT]
| Vai trò thực hiện | Công việc ở G1–G2 | Điểm phối hợp |
|---|---|---|
| TV1 | Auth, users, roles, session, khóa tài khoản | Thống nhất identity/authorization contract |
| TV2 | Course/class, membership, co-lecturer, archive/ownership | Dùng API xác thực từ TV1 |
| TV3 | Frontend đăng nhập, dashboard, quản lý lớp | Tích hợp OpenAPI/mock sớm |
| TV4 | Docker Compose, gateway, migration/CI, test tích hợp và bảo mật | Cùng các TV viết test; không chỉ làm DevOps |

Phân công là sở hữu chính, **không** cấm pair programming hay review chéo. Chốt người phụ trách và ước lượng khi nhóm họp.

## 4. Thứ tự tích hợp Core
1. Thống nhất [thiết kế Core](core/DESIGN.md) và [hợp đồng API](core/API_CONTRACT.md); đóng băng một phiên bản thử nghiệm cho frontend.
2. Dựng skeleton Core, health endpoint, database migration, Gateway và frontend mock.
3. Hoàn thiện đăng nhập → tạo lớp → gửi yêu cầu → duyệt → xem lớp được cấp quyền.
4. Thêm các trường hợp rời/loại, đồng giảng viên, chuyển chủ, lưu trữ/khôi phục, audit.
5. Chạy unit, integration, end-to-end, test truy cập chéo lớp; ghi lại kết quả thực tế.
6. Review các tính năng Core còn lại, chuyển sang G3 khi G1–G2 đủ tiêu chí; không tự đánh dấu hoàn thành các tính năng chưa làm.

## 5. Tiêu chí nghiệm thu G1–G2
- [ ] Đăng nhập/đăng xuất, session và quyền Admin/Lecturer/Student đúng; tài khoản bị khóa không được tiếp tục truy cập (F1, K2).
- [ ] Sinh viên vào bằng mã lớp phải chờ duyệt; chưa duyệt không xem nội dung (A1).
- [ ] Một sinh viên vào nhiều lớp; giảng viên chính quản lý đồng giảng viên, thành viên và quyền chủ lớp đúng (A2–A6, H1–H2, M2).
- [ ] Rời/loại lớp mất quyền xem nội dung; không xóa điểm theo thao tác rời lớp (A5, L2).
- [ ] Lớp lưu trữ/khôi phục đúng quyền và có audit (F5, M5).
- [ ] Không có truy cập trái phép giữa các lớp; thao tác quản trị/quyền quan trọng có audit (F2, F7).
- [ ] Frontend ↔ Gateway ↔ Core ↔ DB chạy qua Docker Compose, migration và test tự động.
- [ ] README tái lập được môi trường; có bằng chứng test và người review.

## 6. Chưa chốt
Công nghệ cụ thể, cách quản lý phiên đăng nhập, cách mời đồng giảng viên, định dạng mã lớp, chính sách hết hạn token, cấu hình VPS, KPI hiệu năng Core và phân bổ thời gian. **Không tự biến đề xuất API/DB thành quy tắc nghiệp vụ.**

## 7. Liên kết
- [Thiết kế Core](core/DESIGN.md)
- [Hợp đồng API Core](core/API_CONTRACT.md)
- Backlog chi tiết quản lý qua GitHub Issues/Project khi bắt đầu triển khai; lộ trình này là tài liệu điều phối duy nhất trong docs. Kế hoạch phân công cũ đã được loại khỏi nhánh main để tránh mâu thuẫn.
