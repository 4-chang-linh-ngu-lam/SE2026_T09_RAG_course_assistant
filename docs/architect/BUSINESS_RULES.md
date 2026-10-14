# Lumi — Business Rules Baseline

**Status:** Baseline hiện hành | **Ngày hệ thống hóa ban đầu:** 2026-10-10

> **Cập nhật 2026-10-14:** phần “Baseline nghiệp vụ Lumi — 20 quyết định” cuối tài liệu là quy tắc mới nhất, ưu tiên khi phần lịch sử phía trên mâu thuẫn.

Tài liệu này ghi lại các quyết định nghiệp vụ đã được nhóm sản phẩm thống nhất qua trao đổi. **Không tự ý sửa rule để thuận tiện triển khai.** Khi có thay đổi, xác định Rule ID bị tác động, review và cập nhật trực tiếp các tài liệu hiện hành gồm Architecture/Tasks. Những chi tiết triển khai chưa được chốt phải được ghi là đề xuất, không được ngầm coi là business rule.

## Phạm vi và vai trò

Lumi phục vụ các lớp môn học chính khóa THCS/THPT (khối 6–12); không bao gồm tiểu học, đại học hoặc lớp học thêm trong MVP. **Admin**, **Lecturer**, **Student** là ba vai trò kỹ thuật đăng nhập; giao diện hiển thị Quản trị viên, Giáo viên, Học sinh. Nhà trường là stakeholder nhận báo cáo thông qua Admin, không có tài khoản riêng. Chỉ Admin tạo lớp và phân công giáo viên; giáo viên chỉ quản lý hoạt động giảng dạy được giao.

## A. Lớp học và thành viên
- **A1** Học sinh được ghi danh tự động theo lớp hành chính (AUTO) hoặc do Admin quản lý (MANUAL); không dùng mã lớp trong MVP.
- **A2** Một học sinh được tham gia nhiều lớp, kể cả nhiều lớp của cùng một môn.
- **A3** Chỉ Admin phân công giáo viên chính và giáo viên phối hợp; giáo viên không tự mời đồng giáo viên.
- **A4** Chỉ Admin điều chỉnh thành viên chính thức, chuyển lớp hoặc kết thúc ghi danh; giữ lịch sử học tập.
- **A5** Học sinh không tự rời lớp chính khóa; Admin xử lý chuyển lớp/kết thúc ghi danh, bảo toàn kết quả cá nhân.
- **A6** Không sử dụng join code/join request trong MVP chính khóa.
- **A7** Lớp môn học gắn môn học, khối 6–12, năm học và tham chiếu lớp hành chính nếu có. Metadata tổ chức không tự tạo thêm role Admin theo trường.
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
- **D1** Câu hỏi AI sinh phải được giáo viên duyệt trước khi dùng chính thức.
- **D2** Hỗ trợ một đáp án, nhiều đáp án, đúng/sai và trả lời ngắn.
- **D3** Practice Quiz chấm/giải thích ngay, không tính là điểm chính thức.
- **D4** Assessment tự chấm câu khách quan, giáo viên duyệt câu chủ quan.
- **D5** Assignment do giáo viên quyết định điểm cuối; AI chỉ hỗ trợ phản hồi.
- **D6** Tắt AI Tutor tích hợp khi học sinh làm Assessment chính thức; không tuyên bố ngăn được công cụ AI bên ngoài.
- **D7** Giáo viên thiết lập hạn, thời lượng, số lượt và thời điểm công bố điểm.
- **D8** Kết quả luyện tập và kết quả chính thức lưu riêng; cả hai có thể phục vụ analytics theo đúng ngữ cảnh.

## E. Analytics
- **E1** Học sinh xem điểm, tiến độ, lịch sử luyện tập và mức độ nắm vững chủ đề.
- **E2** Giáo viên xem thống kê lớp và tiến độ cá nhân trong lớp mình quản lý.
- **E3** Phát hiện điểm yếu dựa trên kết quả gắn chủ đề, hoạt động luyện tập, mức hoàn thành và bằng chứng.
- **E4** AI có thể đề xuất chủ đề, tài liệu, bài luyện tập; học sinh tự quyết định.
- **E5** Giáo viên chỉ xem tổng hợp chủ đề AI Tutor, không mặc định xem nguyên văn chat riêng tư.
- **E6** Cảnh báo nguy cơ học tập chỉ khi đủ bằng chứng; mang tính hỗ trợ, không trừng phạt hoặc gắn nhãn năng lực cố định.

## F. Quản trị
- **F1** Admin tạo, khóa/mở tài khoản và quản lý vai trò. Với học sinh chưa thành niên, cơ chế cấp/kích hoạt tài khoản và điều kiện đồng ý/đại diện hợp lệ phải được xác định trước khi phát hành thực tế.
- **F2** Admin quản lý lớp/thành viên, xử lý vi phạm, ghi log can thiệp.
- **F3** Admin và giáo viên không mặc định được đọc hội thoại AI riêng tư.
- **F4** Xác minh và xử lý yêu cầu xóa dữ liệu, thông báo kết quả theo retention policy.
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
- **I4** Assessment đã công bố là bất biến; chỉnh sửa phải tạo phiên bản mới và xử lý người đã làm.
- **I5** Giáo viên đặt chính sách nộp Assignment muộn.
- **I6** Sửa điểm cần lý do, audit và cập nhật dữ liệu liên quan.
- **I7** Học sinh yêu cầu xem xét điểm; giáo viên phản hồi và kết luận.

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
- **K4** Người dùng xem dữ liệu cá nhân và yêu cầu xuất dữ liệu.
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
- **M4** Câu hỏi Assessment sai: giáo viên có thể vô hiệu hóa, chấm lại hoặc ra câu thay thế; thông báo và audit.
- **M5** Chỉ Admin khôi phục lớp lưu trữ; ghi log và áp dụng lại quyền hiện hành.

## O. Các quyết định bổ sung đã chốt
- **O1** Đồng giáo viên được thêm/gỡ chia sẻ tài liệu trong lớp, không sửa/xóa tài liệu gốc hay phiên bản của người khác.
- **O2** Lớp lưu trữ cho học sinh sửa ghi chú/bookmark của chính mình đối với nguồn còn quyền, không tạo hoạt động chung hoặc hỏi AI mới.
- **O3** Mỗi attempt gắn một phiên bản đề bất biến; phiên bản mới chỉ áp dụng cho lượt giao tiếp theo; xử lý công bằng theo M4.
- **O4** Học sinh đã chuyển lớp/kết thúc ghi danh vẫn được yêu cầu xem xét điểm bài đã nộp trong thời hạn phúc khảo, bằng quyền truy cập giới hạn.
- **O5** Gia hạn deadline chỉ áp dụng cho lần nộp tương lai; không tự thay đổi số lượt/chính sách nộp lại; phải cấu hình và thông báo.
- **O6** Không kết luận mastery nếu thiếu bằng chứng độc lập/độ bao phủ chủ đề. Ẩn thống kê AI Tutor với nhóm dưới **5 học sinh tham gia phân biệt**, áp dụng ẩn ô bổ sung để tránh suy luận ngược. Mốc 5 là chính sách sản phẩm đề xuất, không bảo đảm ẩn danh tuyệt đối.
- **O7** Retention chia theo tài khoản, chat, notes, docs, bài nộp/điểm, logs; thời hạn cụ thể phải được người vận hành duyệt, không tự bịa thời hạn pháp lý.
- **O8** MVP có báo cáo tổng hợp PDF/Excel; người dùng xem dữ liệu và yêu cầu xuất, Admin xử lý thủ công và phản hồi, chưa yêu cầu export tự động toàn bộ.

## 5 nguyên tắc xuyên suốt
1. Quyền hiện tại ưu tiên hơn quyền lịch sử, trừ ngoại lệ kết quả cá nhân được cho phép.
2. Assessment phải truy vết được phiên bản, attempt, lịch sử điểm.
3. AI không quyết định điểm chính thức; giáo viên duyệt đề, điểm chủ quan/Assignment và sửa điểm.
4. Không đưa ra kết luận analytics chắc chắn khi dữ liệu không đủ.
5. Hành động quan trọng có trách nhiệm giải trình, log và thông báo phù hợp.

## MVP và Future
**MVP:** quản lý lớp/thành viên/đồng giáo viên, feed/comments/calendar/in-app notifications; thư viện và chia sẻ tài liệu 5 định dạng, xử lý, version, access control; grounded RAG với citations, 2 chế độ Tutor; Practice Quiz và quy trình duyệt câu hỏi AI; Assessment có timer/resume/version/correction; Assignment có nộp lại/nộp muộn/chấm điểm; dashboard cơ bản có bằng chứng và bảo vệ quyền riêng tư; notes/bookmarks; Admin quản lý tài khoản/quyền, audit, yêu cầu dữ liệu cá nhân, báo cáo tổng hợp PDF/Excel.

**Future/conditional:** diễn đàn độc lập, learning path nâng cao, cảnh báo at-risk tự động, thống kê chủ đề AI nâng cao, ngân hàng câu hỏi/rubric nâng cao, quản trị đa trường; ứng dụng Mobile **sau khi Web ổn định và còn thời gian**. Các ràng buộc an toàn của E4–E6 vẫn phải tuân thủ nếu triển khai các chức năng tương ứng.

## Traceability và quản lý thay đổi
- Mỗi Task tham chiếu Rule ID; test/acceptance criteria kiểm tra các rule có liên quan.
- Nếu rule mơ hồ, ghi Open Question; không tự biến giả định kỹ thuật thành rule.
- Baseline này là tài liệu tham chiếu nghiệp vụ, không phải tuyên bố đã được chuyên gia pháp lý xác minh.

## Điều kiện triển khai còn mở
- **Identity:** Email/password và self-registration STUDENT đang tồn tại về mặt kỹ thuật, nhưng chưa được duyệt làm luồng onboarding mặc định cho học sinh phổ thông. Cần chốt phương thức cấp/kích hoạt tài khoản, thông báo quyền riêng tư và quy trình đồng ý/đại diện khi cần; không thêm role Phụ huynh trong MVP.
- **Classroom:** Cần chốt cách xác minh phân công giáo viên và schema metadata môn/khối/năm học/lớp hành chính; luồng ghi danh trực tiếp chưa được triển khai. Không được mở API tự rời lớp cho Student.
- **Bảo vệ dữ liệu:** Xác định thời hạn lưu giữ và quyền xử lý dữ liệu học sinh theo yêu cầu áp dụng trước khi phát hành; không tự suy đoán thời hạn hoặc ngưỡng tuổi pháp lý.
- **Triển khai:** Tài liệu mô tả nghiệp vụ mục tiêu, không xác nhận schema, migration, API, test hay UI đã hoàn thành. Các thay đổi phải được phản ánh trong Core Design, API Contract và acceptance criteria trước nghiệm thu.


## Baseline nghiệp vụ Lumi — 20 quyết định chốt 2026-10-14

**Phạm vi:** MVP một trường THCS/THPT (khối 6–12), thiết kế sẵn `school_id` cho mở rộng; chỉ ba role kỹ thuật `ADMIN`, `LECTURER`, `STUDENT`. Các quy tắc dưới đây **thay thế mô tả cũ mâu thuẫn** về self-registration Student, giáo viên tạo lớp/ghi danh, join code, mời giáo viên, chuyển chủ lớp, archive/restore. Đây là **thiết kế mục tiêu**, không khẳng định code/migration đã hoàn thành.

1. Lớp môn học gắn môn/khối/năm học/học kỳ và lớp hành chính; tạo lớp mới mỗi năm học; lớp cũ lưu trữ, lịch sử cá nhân vẫn còn.
2. **Chỉ Admin** tạo lớp môn học, quản lý lớp hành chính/danh sách, phân công giáo viên chính và phối hợp, điều chỉnh ghi danh, chuyển lớp, archive/restore; giáo viên không tự tạo lớp, mời giáo viên, chuyển quyền chủ lớp hay quản lý roster chính thức.
3. Ghi danh lớp môn học theo `AUTO` (đồng bộ roster lớp hành chính) hoặc `MANUAL` (Admin quản lý danh sách riêng cho lớp ghép/tự chọn/ngoại lệ). Lớp AUTO muốn điều chỉnh ngoại lệ cá nhân phải chuyển MANUAL trước. Chuyển MANUAL→AUTO phải xem trước tác động và xác nhận. Đồng bộ idempotent, audit, giữ lịch sử; Student không tự rời lớp.
4. **Không dùng join code/join request trong MVP chính khóa**; route/schema cũ nếu có phải đánh dấu legacy/ngoài phạm vi, không mở cho người dùng, không xóa source/migration lịch sử khi cập nhật tài liệu.
5. Admin tạo tài khoản Student (ưu tiên CSV/Excel có preview, kiểm tra trùng/lỗi, nhập lại an toàn); Student không cần email và không tự đăng ký; cấp username duy nhất + mã kích hoạt một lần có hạn, học sinh tự đặt mật khẩu. Quên mật khẩu do Admin xác minh và hỗ trợ. Lecturer/Admin có thể giữ luồng email. Không dùng mật khẩu mặc định chung.
6. Co-lecturer được đăng tài liệu/chia sẻ trong phạm vi quyền nguồn, tạo bài tập/luyện tập, tạo nháp assessment, chấm bài được phân công, xem analytics trong lớp. **Giáo viên chính** phê duyệt/công bố assessment chính thức, phê duyệt sửa điểm đã công bố/hủy hay điều chỉnh kết quả; co-lecturer chỉ đề xuất. Mọi sửa điểm nhạy cảm có lý do/audit; Admin chỉ can thiệp ngoại lệ có lý do/audit. Không thêm role toàn cục CO_LECTURER.
7. Khi chuyển lớp, quyền tham gia lớp cũ chấm dứt theo hiệu lực chuyển; bài đã nộp vẫn được giáo viên cũ chấm, điểm/lịch sử/phúc khảo còn theo quyền cá nhân; bài chưa nộp đóng, attempt đang dở kết thúc theo chính sách, không tự coi là hoàn thành. Admin xử lý ngoại lệ có audit; không tự chuyển điểm sang lớp mới.
8. Student xem điểm, bài nộp, tiến độ, nhận xét, ghi chú tự viết và hội thoại AI cá nhân cũ; có thể sửa ghi chú. Bookmark giữ lại nhưng mở tài liệu/trích đoạn gốc chỉ khi quyền nguồn còn hiệu lực; nguồn thu hồi phải che trích đoạn; không hỏi AI mới hay tham gia hoạt động mới của lớp cũ. Quyền xem lịch sử cá nhân **khác** membership ACTIVE.
9. AI chat riêng tư mặc định; học sinh chủ động chia sẻ cuộc hội thoại cụ thể với giáo viên; giáo viên chỉ thấy analytics tổng hợp, Admin không mặc định đọc chat. Kiểm tra ngoại lệ phải có thẩm quyền, phạm vi, lý do và audit.
10. Dữ liệu phân loại (hồ sơ giáo dục chính thức, chat, notes, tài liệu, điểm/bài nộp, log); yêu cầu xem/xuất/chỉnh sửa/xóa được xác minh và xử lý có kiểm soát; khóa tài khoản không đồng nghĩa xóa. MVP có admin workflow xử lý thủ công, audit và nhập CSV/Excel; chưa yêu cầu xuất/xóa tự động liên dịch vụ, cổng phụ huynh, đa trường. Thời hạn retention, căn cứ xử lý dữ liệu học sinh, đại diện/đồng ý nếu áp dụng phải được phê duyệt trước khi vận hành dữ liệu thật; **không tự đặt thời hạn pháp lý**.

**Open questions triển khai:** thời điểm hiệu lực chuyển lớp; TTL/phân phối/xác minh mã kích hoạt; retention/căn cứ xử lý/đại diện; quy tắc nhập lại CSV/Excel. Các phần Identity đã triển khai theo email và các migration cũ phải được mô tả đúng trạng thái; thay đổi cần task, migration mới, API contract và kiểm thử quyền.
