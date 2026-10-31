# BRD — TÀI LIỆU YÊU CẦU NGHIỆP VỤ

**Mã:** LUMI-BRD-001 · **Phiên bản:** 2.1-DRAFT · **Nguồn chuẩn:** Business Rules A–O · **Trạng thái:** Quy tắc nghiệp vụ đã được xác lập; các chỉ số định lượng đề xuất cần phê duyệt.

## 1. Tóm tắt điều hành

Lumi là nền tảng hỗ trợ quá trình giảng dạy, học tập và quản trị lớp học chính khóa tại **một trường THCS/THPT (khối 6–12)**. Bài toán không dừng ở việc xây dựng một ứng dụng trao đổi trực tuyến; hệ thống cần mô hình hóa quan hệ trường–lớp hành chính–lớp môn học–giáo viên–học sinh, quản lý quyền truy cập thay đổi theo thời gian, giữ lịch sử học tập, đồng thời hỗ trợ các hoạt động đăng bài, lịch, tài liệu, luyện tập, đánh giá, báo cáo và kiểm soát dữ liệu cá nhân.

Trong giai đoạn này, Dịch vụ trí tuệ nhân tạo chưa hoàn tất nghiên cứu và **không thuộc phạm vi đặc tả kỹ thuật của hồ sơ này**. Những định hướng liên quan trong bộ quy tắc nghiệp vụ chỉ được giữ làm bối cảnh phát triển dài hạn, không được coi là yêu cầu triển khai hiện tại.

## 2. Vấn đề và cơ hội

| ID | Vấn đề nghiệp vụ | Tác động nếu không giải quyết | Năng lực hệ thống hướng tới |
|---|---|---|---|
| BP-01 | Hoạt động cấp tài khoản và quản lý quyền truy cập lớp học thiếu sự phân định trách nhiệm | Có nguy cơ cấp sai quyền, khó truy vết người thực hiện | Quản trị viên cấp tài khoản, quản lý danh sách học sinh và phân công giáo viên theo phạm vi trường, lớp |
| BP-02 | Danh sách học sinh thay đổi theo lớp hành chính và các trường hợp ngoại lệ | Có thể ghi danh trùng, sai lớp hoặc mất lịch sử | Ghi danh tự động hoặc thủ công, xem trước tác động, đồng bộ và chuyển lớp có lưu lịch sử |
| BP-03 | Hoạt động trên bảng tin, bình luận, lịch học và thông báo chưa được liên kết thống nhất | Học sinh dễ bỏ lỡ thông tin, giáo viên khó điều phối | Quản lý bảng tin, bình luận, lịch hoạt động và thông báo trong cùng hệ thống |
| BP-04 | Tài liệu được dùng chung cho nhiều lớp, có cập nhật phiên bản và thu hồi chia sẻ | Truy cập sai nguồn hoặc gián đoạn khi phiên bản mới lỗi | Thư viện tài liệu, quản lý phiên bản, cấp và thu hồi quyền chia sẻ, ghi chú cá nhân |
| BP-05 | Bài luyện tập, bài đánh giá chính thức và bài tập được giao có quy trình khác nhau | Kết quả thiếu minh bạch, có nguy cơ ghi trùng khi gửi lại | Thiết kế ba nhóm hoạt động học tập riêng, có phê duyệt và lưu lịch sử điều chỉnh |
| BP-06 | Bằng chứng tiến độ học tập phân tán, chưa đủ điều kiện để đưa ra kết luận | Gợi ý thiếu căn cứ và có thể ảnh hưởng quyền riêng tư | Ghi nhận nguồn bằng chứng, thể hiện trạng thái chưa đủ dữ liệu, kiểm soát thống kê tổng hợp |
| BP-07 | Các yêu cầu truy cập, xuất, chỉnh sửa hoặc xóa dữ liệu cá nhân cần quy trình kiểm soát | Có nguy cơ xử lý sai yêu cầu, xóa nhầm hoặc tiết lộ dữ liệu | Tiếp nhận, xác minh, áp dụng chính sách, thực hiện và ghi nhận kết quả xử lý |

Các vấn đề trên là **khái quát nghiệp vụ dựa trên Business Rules**, không phải kết quả khảo sát định lượng đã thực hiện tại trường.

## 3. Mục tiêu nghiệp vụ

- **BO-01:** Quản trị có kiểm soát các tài khoản và vòng đời lớp học; mọi thao tác quản trị quan trọng xác định được người thực hiện và có nhật ký kiểm toán (F1, F2, F7).
- **BO-02:** Học sinh chỉ nhìn thấy tài nguyên đúng quyền hiện hành, nhưng vẫn giữ lịch sử cá nhân hợp lệ sau chuyển lớp (A4, L2, M1).
- **BO-03:** Giáo viên trao đổi hoạt động lớp, bài đăng và lịch theo đúng phân công; không được tự chuyển quyền quản trị (A3, A8, M2, G1–G4).
- **BO-04:** Tài liệu học tập có quyền chia sẻ, version và xử lý lỗi rõ ràng, với chính sách revoke thắng bản cache/phiên bản cũ (B1–B7, H3).
- **BO-05:** Thực hiện luyện tập/đánh giá minh bạch, phân quyền duyệt kết quả nhạy cảm và không mất câu trả lời đã xác nhận lưu (D0–D8, I1–I7).
- **BO-06:** Báo cáo và gợi ý dựa trên bằng chứng có thể truy vết; không kết luận khi thiếu dữ liệu (E1–E6, J1–J5, F6).
- **BO-07:** Bảo vệ dữ liệu học sinh, không xem việc khóa tài khoản là xóa dữ liệu, có quy trình xác minh và xử lý yêu cầu (F4, K1–K6).

### 3.1 Chỉ số đánh giá đề xuất — chưa duyệt

| Chỉ số | Cách đo | Trạng thái |
|---|---|---|
| Tỷ lệ kịch bản nghiệp vụ phần lõi được kiểm thử xuyên suốt thành công | Số kịch bản trên trình duyệt và cơ sở dữ liệu thực đạt yêu cầu chia cho tổng số kịch bản bắt buộc | PROPOSED; cần chốt ngưỡng nghiệm thu |
| Tỷ lệ thao tác thay đổi danh sách học sinh được ghi nhật ký kiểm toán | Audit đủ actor, action, scope, thời điểm trên tập ca đã kiểm thử | PROPOSED; mục tiêu phải chốt cùng QA |
| Số trường hợp truy cập dữ liệu trái phép giữa các lớp trong bộ kiểm thử | Test negative access cases | Mục tiêu 0 lỗi trong bộ thử hữu hạn, không bảo đảm tuyệt đối |
| Độ trễ p95 khi truy vấn danh sách lớp | QAS-05 trong TP-01 | **≤500 ms backend** là mục tiêu đã ghi trong Quality Attributes |
| Mức độ bao phủ các tình huống sử dụng | Use cases đã có test/evidence so với use cases thuộc release | PROPOSED; chưa có ngưỡng cụ thể |

## 4. Phạm vi nghiệp vụ

### 4.1 Phạm vi phiên bản thử nghiệm phần lõi

| Nhóm nghiệp vụ | Chức năng | Mức ưu tiên |
|---|---|---|
| Danh tính và xác thực | Đăng nhập nhân sự, học sinh; kích hoạt tài khoản; làm mới phiên; đăng xuất; thông tin cá nhân; khóa/mở tài khoản | P0 |
| Quản trị hệ thống | Cấp tài khoản; nhập dữ liệu CSV/XLSX; quản lý vai trò; ghi nhật ký kiểm toán; tiếp nhận và xem xét yêu cầu dữ liệu | P0 |
| Quản lý lớp học | Phạm vi trường, danh sách lớp hành chính, môn học, lớp môn học, phân công giáo viên, ghi danh, chuyển và lưu trữ lớp | P0 |
| Hoạt động lớp học | Bảng tin, bình luận và kiểm soát nội dung | P0 |
| Lịch hoạt động | Các sự kiện lớp học thuộc phạm vi phần lõi | P0 |
| Thông báo | Nhận, xem, đánh dấu đã đọc; phát thông báo đúng đối tượng | P0 |
| Giao diện web | Trang theo vai trò; kết nối API thật; xử lý lỗi, phiên truy cập và quyền hiển thị | P0 |

### 4.2 Các dịch vụ được đặc tả định hướng cho giai đoạn tiếp theo

- **Dịch vụ Tài liệu (G3):** thư viện tài liệu, quản lý phiên bản, chia sẻ lớp, ghi chú, dấu trang, xử lý tệp và thu hồi quyền.
- **Dịch vụ Học tập (G4):** luyện tập, đánh giá chính thức, bài tập; phiên bản đề bất biến, lượt làm bài, chấm điểm, điều chỉnh kết quả và phúc khảo.
- **Dịch vụ Phân tích học tập (G5):** tiếp nhận bằng chứng học tập, ước lượng mức độ nắm vững, hỗ trợ gợi ý và lập báo cáo tổng hợp PDF/Excel.

### 4.3 Ngoài phạm vi tài liệu hiện tại

- **Dịch vụ trí tuệ nhân tạo:** không đặc tả giao diện lập trình, dữ liệu, quy trình xử lý, thuật toán hoặc kiểm thử.
- Mobile app; diễn đàn độc lập; đa trường; proctoring và cảnh báo học tập tự động nâng cao, trừ khi có change request.
- Các integration với LMS/SIS bên thứ ba chưa được thống nhất.

## 5. Các bên liên quan

| Bên liên quan | Vai trò trong hệ thống | Nhu cầu chính | Phạm vi quyết định |
|---|---|---|---|
| Nhà trường | Bên thụ hưởng quản trị, không có role riêng | Tài khoản, lớp, báo cáo, kiểm soát dữ liệu | Quy định vận hành qua Admin/operator được chỉ định |
| Quản trị viên | Quản lý hệ thống tại trường | Cấp tài khoản, quản lý học sinh, phân công giáo viên, xử lý yêu cầu dữ liệu | Quản trị trong phạm vi trường và chính sách đã phê duyệt |
| Giáo viên | Thực hiện hoạt động giảng dạy trong lớp được phân công | Tổ chức hoạt động lớp, quản lý tài liệu và đánh giá | Quyền giáo viên chính/phối hợp theo phân công |
| Học sinh | Tham gia lớp học chính khóa | Truy cập lớp, hoạt động học tập, kết quả cá nhân và yêu cầu dữ liệu | Không tự ghi danh hoặc chuyển lớp |
| Đại diện sản phẩm và đơn vị vận hành | Phê duyệt chính sách và quy trình vận hành | Lưu giữ dữ liệu, xác minh danh tính, xử lý sự cố | Phải được phê duyệt bởi người có thẩm quyền |
| Nhóm phát triển và kiểm thử | Xây dựng và xác nhận hệ thống | Đặc tả giao diện, bằng chứng kiểm thử và giám sát | Quyết định kỹ thuật trong phạm vi được duyệt |

## 6. Các năng lực nghiệp vụ và quy trình xử lý xuyên suốt

**BC-01 Onboarding:** Admin xác định school scope → tạo Student PENDING hoặc staff invitation → bàn giao one-time code / email → kích hoạt/đặt mật khẩu → thiết lập role/status → audit.

**BC-02 Classroom lifecycle:** Tạo catalog/năm học/lớp hành chính → roster → lớp môn học → giáo viên PRIMARY/ASSISTING → enrollment AUTO/MANUAL → social/calendar → transfer/archive/restore → tra cứu lịch sử hợp lệ.

**BC-03 Content:** Giáo viên sở hữu tài liệu → tải/version/process → chia sẻ vào các lớp đã phân công → học sinh có quyền xem → thu hồi/quyền thay đổi → notes tự viết vẫn tồn tại nhưng nguồn bị che.

**BC-04 Assessment:** Giáo viên tạo đề → duyệt chính thức → học sinh thực hiện và lưu đáp án → submit/hết giờ → chấm/duyệt → công bố → sửa điểm/phúc khảo với audit; Practice tách khỏi điểm chính thức.

**BC-05 Reporting:** Hệ thống nhận evidence từ nguồn có thẩm quyền → đối soát revision/sửa điểm → xác định đủ dữ liệu hay không → báo cáo/gợi ý → export có phạm vi và audit.

## 7. Các chính sách nghiệp vụ chưa đủ căn cứ để xác lập

- Căn cứ, đại diện hợp lệ và quy trình xác minh danh tính học sinh cụ thể khi vận hành thực tế.
- Retention cụ thể theo từng loại dữ liệu, ngoại lệ pháp lý và xử lý backup.
- Chính sách câu hỏi/chấm điểm, thời hạn phúc khảo, công thức tính điểm, late penalty và trọng số mastery.
- Phương án chuyển lớp khi đang có Assessment/Assignment dở và ngưỡng công bố thống kê tổng hợp ngoài chính sách O6.

Những điểm này bắt buộc có quyết định trước khi hệ thống vận hành với dữ liệu thật. Xem [19_Decisions_Gaps.md](19_Decisions_Gaps.md).

## 8. Ràng buộc và giả định

- Một trường trong MVP nhưng `school_id` dùng làm hàng rào dữ liệu; không cung cấp cross-school admin (Architecture).
- Frontend Next.js, Core FastAPI/PostgreSQL/Compose là công nghệ triển khai hiện có; công nghệ cho Document/Learning/Intelligence chưa được chốt (HLD).
- Không dùng mã tham gia lớp; giáo viên không tự tạo lớp và học sinh không tự rời lớp (A1–A8).
- Một số tính năng giai đoạn sau hiện mới là task design; không gọi chúng là IMPLEMENTED.
- Chi tiết vận hành hiện tại như production mock và staging chỉ là trạng thái tại commit tham chiếu, không phải cam kết SLA.

## 9. Rủi ro và điều kiện phụ thuộc

| ID | Rủi ro | Hệ quả | Kiểm soát đề xuất |
|---|---|---|---|
| R-01 | Trộn trạng thái mock/live | Nghiệm thu nhầm | Test live-only, cấu hình build từ chối mock production |
| R-02 | Đồng nhất quyền lịch sử và quyền hiện hành | Rò rỉ nội dung mới | Action-based policy + kiểm tra tại thời điểm truy cập |
| R-03 | Không có policy xóa dữ liệu | Xóa sai/giả completed | Giữ IN_REVIEW cho DELETE cho đến khi có executor |
| R-04 | Version/retry không nguyên tử | Mất nội dung/bài làm | Transaction/version/unique/idempotency và retry tests |
| R-05 | Tài liệu chưa có contract approved | Code lệch thiết kế | Review contract, ownership, schema và threat model trước triển khai |

## 10. Điều kiện nghiệm thu theo từng giai đoạn

**Core MVP:** Admin → Lecturer → Student hoạt động bằng Web/Core/PostgreSQL thật; phân quyền, lỗi, archive, notification và audit có bằng chứng. Kết quả `TECHNICALLY READY` khác với operator acceptance.

**Document:** đa định dạng, xử lý lỗi/version fallback, grant/revoke có hiệu lực tại truy cập mới, owner-only notes/bookmarks, test crash/retry.

**Learning:** immutable attempts, phê duyệt, retry không trùng, transfer/history/appeal, grading và deadline events; có bằng chứng trên PostgreSQL.

**Intelligence:** đủ/thiếu bằng chứng đúng, grade correction version, suppression và export có quyền; QAS-11 đo thật trên bộ tình huống được duyệt.

## 11. Truy vết

Business Objectives BO-01..07 → FR trong SRS → Use Cases → HLD/LLD → Test Cases → RTM. Không tính các mục AI đang loại khỏi phạm vi.