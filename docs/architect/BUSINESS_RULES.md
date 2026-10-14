# Lumi — Business Rules Baseline

**Status:** Baseline hiện hành | **Ngày hệ thống hóa ban đầu:** 2026-10-10

Tài liệu này ghi lại các quyết định nghiệp vụ đã được nhóm sản phẩm thống nhất qua trao đổi. **Không tự ý sửa rule để thuận tiện triển khai.** Khi có thay đổi, xác định Rule ID bị tác động, review và cập nhật trực tiếp các tài liệu hiện hành gồm Architecture/Tasks. Những chi tiết triển khai chưa được chốt phải được ghi là đề xuất, không được ngầm coi là business rule.

## Phạm vi và vai trò

Lumi phục vụ các lớp môn học chính khóa THCS/THPT (khối 6–12); không bao gồm tiểu học, đại học hoặc lớp học thêm trong MVP. **Admin**, **Lecturer**, **Student** là ba vai trò kỹ thuật đăng nhập; giao diện hiển thị Quản trị viên, Giáo viên, Học sinh. Nhà trường là stakeholder nhận báo cáo thông qua Admin, không có tài khoản riêng. Chỉ Admin tạo lớp và phân công giáo viên; giáo viên chỉ quản lý hoạt động giảng dạy được giao.

## A. Lớp học và thành viên
- **A1** Học sinh được ghi danh tự động theo lớp hành chính (AUTO) hoặc do Admin quản lý (MANUAL); không dùng mã lớp trong MVP.
- **A2** Một học sinh có thể tham gia nhiều lớp môn học, kể cả nhiều lớp cùng môn khi Admin phân công; mỗi lớp phải tuân thủ chế độ ghi danh AUTO/MANUAL và không được tự ý tham gia.
- **A3** Chỉ Admin phân công giáo viên chính và giáo viên phối hợp; giáo viên không tự mời đồng giáo viên.
- **A4** Chỉ Admin điều chỉnh thành viên chính thức, chuyển lớp hoặc kết thúc ghi danh; giữ lịch sử học tập.
- **A5** Học sinh không tự rời lớp chính khóa; Admin xử lý chuyển lớp/kết thúc ghi danh, bảo toàn kết quả cá nhân.
- **A6** Không sử dụng join code/join request trong MVP chính khóa.
- **A7** Lớp môn học gắn môn, khối 6–12, năm học, học kỳ và lớp hành chính tương ứng; trường hợp ghép/tự chọn dùng MANUAL. Lớp môn học được tạo mới mỗi năm học, lớp cũ archive theo quyền Admin.
- **A8** Chỉ Admin tạo lớp môn học chính khóa và phân công giáo viên; giáo viên quản lý hoạt động giảng dạy trong lớp được giao.

## B. Tài liệu
- **B1** Giáo viên có thư viện tài liệu cá nhân, có thể chia sẻ một tài liệu cho nhiều lớp.
- **B2** Giáo viên chính và đồng phụ trách được thêm tài liệu vào lớp; chủ sở hữu kiểm soát tài liệu nguồn.
- **B3** Hỗ trợ PDF, PPTX, DOCX, TXT và Markdown.
- **B4** Lưu lịch sử phiên bản; lớp sử dụng phiên bản mới nhất đã xử lý thành công.
- **B5** Có trạng thái xử lý, thông báo lỗi và chức năng thử lại.
- **B6** Thu hồi chia sẻ có hiệu lực ngay; cảnh báo trước khi xóa tài liệu dùng ở nhiều lớp.
- **B7** Truy hồi chỉ được dùng tài liệu hiện đang được cấp quyền cho lớp đang chọn.

## C. AI Tutor
- **C1** RAG ưu tiên căn cứ từ tài liệu lớp; kiến thức chung bổ sung phải được phân biệt rõ.
- **C2** Trích dẫn tên tài liệu và vị trí trang/slide/mục khi có thể xác định đáng tin cậy.
- **C3** Khi thiếu căn cứ phải nói rõ, không bịa trích dẫn.
- **C4** Có hai chế độ: hỏi đáp nhanh và hướng dẫn từng bước; lời giải, ví dụ, từ vựng phải phù hợp khối 6–12, ưu tiên gợi mở thay vì làm hộ.
- **C5** Hội thoại gắn với một lớp; đổi lớp đồng nghĩa đổi phạm vi truy hồi.
- **C6** Giáo viên cấu hình hướng dẫn AI trong giới hạn chính sách hệ thống.

## D. Quiz, Assessment, Assignment
- **D0** Sản phẩm có cả Practice Quiz, Assessment chính thức và Assignment.
- **D1** Câu hỏi AI sinh phải được giáo viên duyệt trước khi dùng; công bố Assessment chính thức cần giáo viên chính phê duyệt.
- **D2** Hỗ trợ một đáp án, nhiều đáp án, đúng/sai và trả lời ngắn.
- **D3** Practice Quiz chấm/giải thích ngay, không tính là điểm chính thức.
- **D4** Assessment tự chấm câu khách quan; giáo viên được phân công chấm/duyệt câu chủ quan; giáo viên chính chịu trách nhiệm phê duyệt công bố kết quả nhạy cảm.
- **D5** Assignment do giáo viên quyết định điểm cuối; AI chỉ hỗ trợ phản hồi.
- **D6** Tắt AI Tutor tích hợp khi học sinh làm Assessment chính thức; không tuyên bố ngăn được công cụ AI bên ngoài.
- **D7** Giáo viên được phân công có thể cấu hình bản nháp hạn, thời lượng, số lượt, thời điểm công bố điểm; giáo viên chính phê duyệt công bố Assessment chính thức.
- **D8** Kết quả luyện tập và kết quả chính thức lưu riêng; cả hai có thể phục vụ analytics theo đúng ngữ cảnh.

## E. Analytics
- **E1** Học sinh xem điểm, tiến độ, lịch sử luyện tập và mức độ nắm vững chủ đề.
- **E2** Giáo viên xem thống kê lớp và tiến độ cá nhân trong lớp mình quản lý.
- **E3** Phát hiện điểm yếu dựa trên kết quả gắn chủ đề, hoạt động luyện tập, mức hoàn thành và bằng chứng.
- **E4** AI có thể đề xuất chủ đề, tài liệu, bài luyện tập; học sinh tự quyết định.
- **E5** Giáo viên chỉ xem tổng hợp chủ đề AI Tutor, không mặc định xem nguyên văn chat riêng tư.
- **E6** Cảnh báo nguy cơ học tập chỉ khi đủ bằng chứng; mang tính hỗ trợ, không trừng phạt hoặc gắn nhãn năng lực cố định.

## F. Quản trị
- **F1** Admin cấp tài khoản Student (không yêu cầu email), username duy nhất và mã kích hoạt một lần có hạn; học sinh đặt mật khẩu khi kích hoạt, không tự đăng ký. Khôi phục mật khẩu Student qua Admin sau xác minh. Admin khóa/mở tài khoản, quản lý vai trò. Chính sách xử lý dữ liệu người chưa thành niên phải được xác định trước vận hành thật.
- **F2** Admin quản lý lớp hành chính, roster, lớp môn học, phân công giáo viên, ghi danh AUTO/MANUAL, xử lý vi phạm và ghi log can thiệp.
- **F3** Admin và giáo viên không mặc định được đọc hội thoại AI riêng tư.
- **F4** Admin tiếp nhận, xác minh và xử lý yêu cầu xem/xuất/chỉnh sửa/xóa dữ liệu theo loại dữ liệu và chính sách retention; ghi kết quả và lý do.
- **F5** Chỉ Admin lưu trữ/khôi phục lớp; lớp lưu trữ chỉ đọc và không nhận hoạt động mới.
- **F6** Admin xuất báo cáo tổng hợp PDF/Excel cho nhà trường.
- **F7** Audit các thao tác Admin, quyền, điểm, tài liệu và lỗi RAG quan trọng.

## G. Classroom trong MVP
- **G1** Bảng tin lớp; **G2** bình luận bài đăng; **G3** lịch và deadline; **G4** thông báo trong ứng dụng; **G5** ghi chú/bookmark cá nhân. Diễn đàn thảo luận độc lập thuộc Future.

## H. Vòng đời và quyền
- **H1** Chỉ Admin thay đổi giáo viên chính hoặc giáo viên phối hợp, có audit; không có chuyển quyền chủ lớp do giáo viên thực hiện.
- **H2** Khi giáo viên chính rời lớp, Admin phân công người thay thế trước khi thay đổi có hiệu lực.
- **H3** Nếu phiên bản tài liệu mới xử lý lỗi, tiếp tục dùng phiên bản xử lý thành công gần nhất, thông báo và cho retry; trừ khi quyền truy cập đã bị thu hồi.
- **H4** Người còn quyền xem được lịch sử chat cũ, nhưng không truy hồi mới hoặc mở nguồn đã mất quyền.
- **H5** Lớp lưu trữ chỉ được xem chat cũ, không đặt câu hỏi AI mới.
- **H6** Ghi chú tự viết còn sau khi nguồn bị thu hồi/xóa; không mở được nguồn.

## I. Ngoại lệ Assessment
- **I1** Mất kết nối: giữ câu trả lời đã lưu thành công, cho tiếp tục nếu còn giờ.
- **I2** Hết giờ: tự nộp các câu trả lời đã lưu.
- **I3** Giáo viên chọn best/latest/average cho nhiều lượt ngay khi tạo bài.
- **I4** Assessment đã công bố là bất biến; chỉnh sửa phải tạo phiên bản mới, giáo viên chính phê duyệt và xử lý công bằng với người đã làm.
- **I5** Giáo viên đặt chính sách nộp Assignment muộn.
- **I6** Sửa điểm đã công bố hoặc hủy/điều chỉnh kết quả cần giáo viên chính phê duyệt, lý do, audit và cập nhật dữ liệu liên quan; Admin chỉ can thiệp ngoại lệ có audit.
- **I7** Học sinh yêu cầu xem xét điểm; giáo viên được phân công xử lý, quyết định nhạy cảm do giáo viên chính phê duyệt.

## J. Ngoại lệ Analytics
- **J1** Thiếu bằng chứng hiển thị “Chưa đủ dữ liệu”, không kết luận mastery.
- **J2** Hỏi lặp một câu không được coi là bằng chứng mastery độc lập.
- **J3** Analytics dùng điểm sửa đã xác nhận mới nhất; giữ lịch sử.
- **J4** Ẩn thống kê chủ đề AI nếu nhóm nhỏ hoặc có nguy cơ tái định danh.
- **J5** Cảnh báo rủi ro phải có căn cứ, chỉ hỗ trợ; không tự động chấm điểm/kỷ luật.

## K. Quyền riêng tư và lưu giữ
- **K1** Yêu cầu xóa dữ liệu phân loại xóa/ẩn danh/giữ lại, giải thích lý do.
- **K2** Khóa tài khoản chặn truy cập nhưng không tự xóa dữ liệu.
- **K3** Giữ lịch sử chat hợp lệ nhưng che nội dung nguyên văn/nguồn không còn được cấp quyền.
- **K4** Người dùng xem dữ liệu cá nhân và gửi yêu cầu xem/xuất/chỉnh sửa/xóa; Admin xác minh và xử lý có kiểm soát, không tự động xóa mọi loại dữ liệu.
- **K5** Audit tối thiểu, hạn chế người xem, mặc định không ghi nội dung chat riêng tư.
- **K6** Retention theo loại dữ liệu, mục đích, nghĩa vụ; xóa/ẩn danh khi hết hạn.

## L. Ngoại lệ Classroom
- **L1** Bài đăng/bình luận đã xóa không còn hiển thị; giữ audit cần thiết.
- **L2** Chuyển lớp/kết thúc ghi danh làm mất quyền tham gia lớp cũ và xem nội dung mới, nhưng vẫn giữ quyền xem lịch sử cá nhân hợp lệ; nguồn tài liệu kiểm tra grant hiện hành.
- **L3** Đổi deadline phải thông báo và giữ trạng thái đã nộp.
- **L4** Giáo viên quyết định bài đã giao có áp dụng cho học sinh vào muộn không.
- **L5** Giáo viên ẩn/xóa bình luận vi phạm; Admin can thiệp và ghi log.
- **L6** Giữ ghi chú tự viết nhưng che trích đoạn nguyên văn từ tài liệu bị thu hồi.

## M. Ngoại lệ cuối
- **M1** Giáo viên vẫn chấm bài đã nộp sau khi học sinh chuyển lớp/kết thúc ghi danh; học sinh xem kết quả cá nhân theo quyền được cấp.
- **M2** Giáo viên phối hợp quản lý tài liệu và hoạt động giảng dạy trong phạm vi lớp, chấm bài được phân công; không sửa roster, phân công giáo viên hay tự phê duyệt đánh giá nhạy cảm.
- **M3** Giáo viên thiết lập số lượt và hạn nộp lại Assignment; xác định rõ bản được chấm.
- **M4** Câu hỏi Assessment sai: giáo viên phối hợp có thể đề xuất vô hiệu hóa/chấm lại/ra câu thay thế; giáo viên chính phê duyệt quyết định chính thức, thông báo và audit; Admin can thiệp ngoại lệ.
- **M5** Chỉ Admin khôi phục lớp lưu trữ; ghi log và áp dụng lại quyền hiện hành.

## O. Các quyết định bổ sung đã chốt
- **O1** Giáo viên phối hợp được thêm/gỡ chia sẻ tài liệu trong lớp theo grant hợp lệ, không sửa/xóa tài liệu gốc hay phiên bản của người khác.
- **O2** Lớp lưu trữ cho học sinh sửa ghi chú/bookmark của chính mình đối với nguồn còn quyền, không tạo hoạt động chung hoặc hỏi AI mới.
- **O3** Mỗi attempt gắn một phiên bản đề bất biến; phiên bản mới chỉ áp dụng cho lượt giao tiếp theo; xử lý công bằng theo M4.
- **O4** Học sinh đã chuyển lớp/kết thúc ghi danh vẫn được yêu cầu xem xét điểm bài đã nộp trong thời hạn phúc khảo, bằng quyền truy cập giới hạn.
- **O5** Gia hạn deadline chỉ áp dụng cho lần nộp tương lai; không tự thay đổi số lượt/chính sách nộp lại; phải cấu hình và thông báo.
- **O6** Không kết luận mastery nếu thiếu bằng chứng độc lập/độ bao phủ chủ đề. Ẩn thống kê AI Tutor với nhóm dưới **5 học sinh tham gia phân biệt**, áp dụng ẩn ô bổ sung để tránh suy luận ngược. Mốc 5 là chính sách sản phẩm đề xuất, không bảo đảm ẩn danh tuyệt đối.
- **O7** Retention chia theo tài khoản, chat, notes, docs, bài nộp/điểm, logs; thời hạn cụ thể phải được người vận hành duyệt, không tự bịa thời hạn pháp lý.
- **O8** MVP có báo cáo tổng hợp PDF/Excel; người dùng xem dữ liệu và yêu cầu xuất/chỉnh sửa/xóa, Admin xử lý có audit, chưa bắt buộc xuất/xóa tự động toàn bộ.

## 5 nguyên tắc xuyên suốt
1. Quyền hiện tại ưu tiên hơn quyền lịch sử, trừ ngoại lệ kết quả cá nhân được cho phép.
2. Assessment phải truy vết được phiên bản, attempt, lịch sử điểm.
3. AI không quyết định điểm chính thức; giáo viên duyệt đề, điểm chủ quan/Assignment và sửa điểm.
4. Không đưa ra kết luận analytics chắc chắn khi dữ liệu không đủ.
5. Hành động quan trọng có trách nhiệm giải trình, log và thông báo phù hợp.

## MVP và Future
**MVP:** quản lý lớp hành chính/lớp môn học/roster, ghi danh AUTO/MANUAL và chuyển lớp, phân công giáo viên chính/phối hợp, Admin archive/restore; Admin cấp tài khoản Student username + mã kích hoạt, nhập CSV/Excel có kiểm tra lỗi/trùng, quản lý yêu cầu dữ liệu; feed/comments/calendar/in-app notifications; thư viện tài liệu 5 định dạng, xử lý, version, access control; grounded RAG có citations và 2 chế độ Tutor, chat riêng tư; Practice Quiz và duyệt câu hỏi AI; Assessment có timer/resume/version/correction và phê duyệt giáo viên chính; Assignment có nộp lại/nộp muộn/chấm điểm; dashboard có bằng chứng, bảo vệ riêng tư; notes/bookmarks và lịch sử cá nhân; audit, báo cáo tổng hợp PDF/Excel.

**Future/conditional:** diễn đàn độc lập, learning path nâng cao, cảnh báo at-risk tự động, thống kê chủ đề AI nâng cao, ngân hàng câu hỏi/rubric nâng cao, quản trị đa trường; ứng dụng Mobile **sau khi Web ổn định và còn thời gian**. Các ràng buộc an toàn của E4–E6 vẫn phải tuân thủ nếu triển khai các chức năng tương ứng.

## Traceability và quản lý thay đổi
- Mỗi Task tham chiếu Rule ID; test/acceptance criteria kiểm tra các rule có liên quan.
- Nếu rule mơ hồ, ghi Open Question; không tự biến giả định kỹ thuật thành rule.
- Baseline này là tài liệu tham chiếu nghiệp vụ, không phải tuyên bố đã được chuyên gia pháp lý xác minh.

## Điều kiện triển khai còn mở
- **Identity:** **DECIDED** Student do Admin cấp username + mã kích hoạt một lần có hạn, không cần email; self-registration Student bằng email là **IMPLEMENTED — LEGACY**, không được dùng làm onboarding MVP. **PENDING DESIGN:** TTL, phân phối mã, quy trình xác minh khôi phục, cơ chế chuyển đổi tài khoản cũ, căn cứ xử lý dữ liệu học sinh.
- **Classroom:** **DECIDED** Admin tạo lớp môn học, quản lý lớp hành chính/roster/phân công và ghi danh AUTO/MANUAL; không join code, không giáo viên tự tạo lớp. **PENDING DESIGN:** schema/endpoint cụ thể, hiệu lực chuyển lớp, đồng bộ sự kiện và cơ chế preview khi đổi MANUAL→AUTO. Luồng mới chưa triển khai.
- **Bảo vệ dữ liệu:** Xác định thời hạn lưu giữ và quyền xử lý dữ liệu học sinh theo yêu cầu áp dụng trước khi phát hành; không tự suy đoán thời hạn hoặc ngưỡng tuổi pháp lý.
- **Triển khai:** Tài liệu mô tả nghiệp vụ mục tiêu, không xác nhận schema, migration, API, test hay UI đã hoàn thành. Các thay đổi phải được phản ánh trong Core Design, API Contract và acceptance criteria trước nghiệm thu.



## Ma trận 20 quyết định (DECIDED)

| # | Quyết định | Quy tắc |
|---|---|---|
| 1 | Lớp môn học liên kết lớp hành chính | DECIDED |
| 2 | Chỉ Admin tạo lớp/phân công | DECIDED |
| 3 | Roster hành chính tự động ghi danh | DECIDED |
| 4 | Admin cấp tài khoản Student | DECIDED |
| 5 | Lớp mới mỗi năm học | DECIDED |
| 6 | Admin phân công giáo viên phối hợp | DECIDED |
| 7 | Admin xử lý ngoại lệ ghi danh | DECIDED |
| 8 | Username + mã kích hoạt, không email Student | DECIDED |
| 9 | Chỉ Admin archive/restore | DECIDED |
| 10 | Giữ kết quả cá nhân khi chuyển lớp | DECIDED |
| 11 | Chat AI riêng tư mặc định | DECIDED |
| 12 | Retention theo loại và yêu cầu dữ liệu có xác minh | DECIDED |
| 13 | MVP một trường, chuẩn bị school_id | DECIDED |
| 14 | Không join code | DECIDED |
| 15 | Chuyển lớp xử lý bài/attempt dở | DECIDED |
| 16 | Quyền giáo viên phối hợp có giới hạn | DECIDED |
| 17 | Giáo viên chính phê duyệt nhạy cảm | DECIDED |
| 18 | AUTO/MANUAL theo lớp môn học | DECIDED |
| 19 | Giữ notes/chat cá nhân, nguồn theo grant | DECIDED |
| 20 | MVP quản trị thiết yếu + nhập CSV/Excel | DECIDED |

**PENDING DESIGN:** hiệu lực chuyển lớp, chi tiết kích hoạt/khôi phục, retention và đại diện hợp lệ, import retry và API/schema cụ thể. Không tự xem chúng là nghiệp vụ đã chốt.
