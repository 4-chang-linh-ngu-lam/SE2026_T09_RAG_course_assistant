# Lumi — Business Rules Baseline

**Status:** Baseline hiện hành | **Ngày hệ thống hóa ban đầu:** 2026-10-10

Tài liệu này ghi lại các quyết định nghiệp vụ đã được nhóm sản phẩm thống nhất qua trao đổi. **Không tự ý sửa rule để thuận tiện triển khai.** Khi có thay đổi, xác định Rule ID bị tác động, review và cập nhật trực tiếp các tài liệu hiện hành gồm Architecture/Tasks. Những chi tiết triển khai chưa được chốt phải được ghi là đề xuất, không được ngầm coi là business rule.

## Phạm vi và vai trò

Lumi phục vụ các lớp môn học chính khóa THCS/THPT (khối 6–12); không bao gồm tiểu học, đại học hoặc lớp học thêm trong MVP. **Admin**, **Lecturer**, **Student** là ba vai trò kỹ thuật đăng nhập; giao diện hiển thị Quản trị viên, Giáo viên, Học sinh. Nhà trường là stakeholder nhận báo cáo thông qua Admin, không có tài khoản riêng. Giáo viên tạo lớp trong phạm vi phân công được xác minh; cơ chế xác minh còn cần chốt.

## A. Lớp học và thành viên
- **A1** Học sinh được ghi danh bởi giáo viên/Admin có thẩm quyền; mã lớp là tùy chọn và cần giáo viên duyệt; khi chờ duyệt chưa được truy cập nội dung.
- **A2** Một học sinh được tham gia nhiều lớp, kể cả nhiều lớp của cùng một môn.
- **A3** Giảng viên chính mời giảng viên đồng phụ trách.
- **A4** Giảng viên được loại sinh viên khỏi lớp; Admin có quyền can thiệp.
- **A5** Học sinh không tự rời lớp chính khóa; giáo viên/Admin xử lý chuyển lớp hoặc kết thúc ghi danh. Kết quả học tập không tự động bị xóa.
- **A6** Giáo viên bật/tắt tiếp nhận yêu cầu bằng mã; không ảnh hưởng ghi danh theo phân công.

## B. Tài liệu
- **B1** Giảng viên có thư viện tài liệu cá nhân, có thể chia sẻ một tài liệu cho nhiều lớp.
- **B2** Giảng viên chính và đồng phụ trách được thêm tài liệu vào lớp; chủ sở hữu kiểm soát tài liệu nguồn.
- **B3** Hỗ trợ PDF, PPTX, DOCX, TXT và Markdown.
- **B4** Lưu lịch sử phiên bản; lớp sử dụng phiên bản mới nhất đã xử lý thành công.
- **B5** Có trạng thái xử lý, thông báo lỗi và chức năng thử lại.
- **B6** Thu hồi chia sẻ có hiệu lực ngay; cảnh báo trước khi xóa tài liệu dùng ở nhiều lớp.
- **B7** Truy hồi chỉ được dùng tài liệu hiện đang được cấp quyền cho lớp đang chọn.

## C. AI Tutor
- **C1** RAG ưu tiên căn cứ từ tài liệu lớp; kiến thức chung bổ sung phải được phân biệt rõ.
- **C2** Trích dẫn tên tài liệu và vị trí trang/slide/mục khi có thể xác định đáng tin cậy.
- **C3** Khi thiếu căn cứ phải nói rõ, không bịa trích dẫn.
- **C4** Có hai chế độ: hỏi đáp nhanh và hướng dẫn từng bước.
- **C5** Hội thoại gắn với một lớp; đổi lớp đồng nghĩa đổi phạm vi truy hồi.
- **C6** Giảng viên cấu hình hướng dẫn AI trong giới hạn chính sách hệ thống.

## D. Quiz, Assessment, Assignment
- **D0** Sản phẩm có cả Practice Quiz, Assessment chính thức và Assignment.
- **D1** Câu hỏi AI sinh phải được giảng viên duyệt trước khi dùng chính thức.
- **D2** Hỗ trợ một đáp án, nhiều đáp án, đúng/sai và trả lời ngắn.
- **D3** Practice Quiz chấm/giải thích ngay, không tính là điểm chính thức.
- **D4** Assessment tự chấm câu khách quan, giảng viên duyệt câu chủ quan.
- **D5** Assignment do giảng viên quyết định điểm cuối; AI chỉ hỗ trợ phản hồi.
- **D6** Tắt AI Tutor tích hợp khi sinh viên làm Assessment chính thức; không tuyên bố ngăn được công cụ AI bên ngoài.
- **D7** Giảng viên thiết lập hạn, thời lượng, số lượt và thời điểm công bố điểm.
- **D8** Kết quả luyện tập và kết quả chính thức lưu riêng; cả hai có thể phục vụ analytics theo đúng ngữ cảnh.

## E. Analytics
- **E1** Sinh viên xem điểm, tiến độ, lịch sử luyện tập và mức độ nắm vững chủ đề.
- **E2** Giảng viên xem thống kê lớp và tiến độ cá nhân trong lớp mình quản lý.
- **E3** Phát hiện điểm yếu dựa trên kết quả gắn chủ đề, hoạt động luyện tập, mức hoàn thành và bằng chứng.
- **E4** AI có thể đề xuất chủ đề, tài liệu, bài luyện tập; sinh viên tự quyết định.
- **E5** Giảng viên chỉ xem tổng hợp chủ đề AI Tutor, không mặc định xem nguyên văn chat riêng tư.
- **E6** Cảnh báo nguy cơ học tập chỉ khi đủ bằng chứng; mang tính hỗ trợ, không trừng phạt.

## F. Quản trị
- **F1** Admin tạo, khóa/mở tài khoản và quản lý vai trò.
- **F2** Admin quản lý lớp/thành viên, xử lý vi phạm, ghi log can thiệp.
- **F3** Admin và giảng viên không mặc định được đọc hội thoại AI riêng tư.
- **F4** Xác minh và xử lý yêu cầu xóa dữ liệu, thông báo kết quả theo retention policy.
- **F5** Giảng viên lưu trữ lớp ở chế độ chỉ đọc, không thêm bài nộp/thành viên mới.
- **F6** Admin xuất báo cáo tổng hợp PDF/Excel cho nhà trường.
- **F7** Audit các thao tác Admin, quyền, điểm, tài liệu và lỗi RAG quan trọng.

## G. Classroom trong MVP
- **G1** Bảng tin lớp; **G2** bình luận bài đăng; **G3** lịch và deadline; **G4** thông báo trong ứng dụng; **G5** ghi chú/bookmark cá nhân. Diễn đàn thảo luận độc lập thuộc Future.

## H. Vòng đời và quyền
- **H1** Giảng viên chính chuyển quyền chủ lớp cho đồng giảng viên; Admin có thể can thiệp; ghi log.
- **H2** Giảng viên chính phải chuyển quyền trước khi rời lớp.
- **H3** Nếu phiên bản tài liệu mới xử lý lỗi, tiếp tục dùng phiên bản xử lý thành công gần nhất, thông báo và cho retry; trừ khi quyền truy cập đã bị thu hồi.
- **H4** Người còn quyền xem được lịch sử chat cũ, nhưng không truy hồi mới hoặc mở nguồn đã mất quyền.
- **H5** Lớp lưu trữ chỉ được xem chat cũ, không đặt câu hỏi AI mới.
- **H6** Ghi chú tự viết còn sau khi nguồn bị thu hồi/xóa; không mở được nguồn.

## I. Ngoại lệ Assessment
- **I1** Mất kết nối: giữ câu trả lời đã lưu thành công, cho tiếp tục nếu còn giờ.
- **I2** Hết giờ: tự nộp các câu trả lời đã lưu.
- **I3** Giảng viên chọn best/latest/average cho nhiều lượt ngay khi tạo bài.
- **I4** Assessment đã công bố là bất biến; chỉnh sửa phải tạo phiên bản mới và xử lý người đã làm.
- **I5** Giảng viên đặt chính sách nộp Assignment muộn.
- **I6** Sửa điểm cần lý do, audit và cập nhật dữ liệu liên quan.
- **I7** Sinh viên yêu cầu xem xét điểm; giảng viên phản hồi và kết luận.

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
- **L2** Chuyển lớp/kết thúc ghi danh/bị xóa khỏi lớp làm mất quyền xem nội dung lớp; kết quả xử lý theo retention.
- **L3** Đổi deadline phải thông báo và giữ trạng thái đã nộp.
- **L4** Giảng viên quyết định bài đã giao có áp dụng cho sinh viên vào muộn không.
- **L5** Giảng viên ẩn/xóa bình luận vi phạm; Admin can thiệp và ghi log.
- **L6** Giữ ghi chú tự viết nhưng che trích đoạn nguyên văn từ tài liệu bị thu hồi.

## M. Ngoại lệ cuối
- **M1** Giáo viên vẫn chấm bài đã nộp sau khi học sinh chuyển lớp/kết thúc ghi danh; học sinh xem kết quả cá nhân theo quyền được cấp.
- **M2** Đồng giảng viên quản lý tài liệu/thành viên/hoạt động nhưng không chuyển chủ lớp hoặc xóa lớp.
- **M3** Giảng viên thiết lập số lượt và hạn nộp lại Assignment; xác định rõ bản được chấm.
- **M4** Câu hỏi Assessment sai: giảng viên có thể vô hiệu hóa, chấm lại hoặc ra câu thay thế; thông báo và audit.
- **M5** Giảng viên chính/Admin khôi phục lớp lưu trữ; ghi log và áp dụng lại quyền hiện tại.

## O. Các quyết định bổ sung đã chốt
- **O1** Đồng giảng viên được thêm/gỡ chia sẻ tài liệu trong lớp, không sửa/xóa tài liệu gốc hay phiên bản của người khác.
- **O2** Lớp lưu trữ cho sinh viên sửa ghi chú/bookmark của chính mình đối với nguồn còn quyền, không tạo hoạt động chung hoặc hỏi AI mới.
- **O3** Mỗi attempt gắn một phiên bản đề bất biến; phiên bản mới chỉ áp dụng cho lượt giao tiếp theo; xử lý công bằng theo M4.
- **O4** Học sinh đã chuyển lớp/kết thúc ghi danh vẫn được yêu cầu xem xét điểm bài đã nộp trong thời hạn phúc khảo, bằng quyền truy cập giới hạn.
- **O5** Gia hạn deadline chỉ áp dụng cho lần nộp tương lai; không tự thay đổi số lượt/chính sách nộp lại; phải cấu hình và thông báo.
- **O6** Không kết luận mastery nếu thiếu bằng chứng độc lập/độ bao phủ chủ đề. Ẩn thống kê AI Tutor với nhóm dưới **5 sinh viên tham gia phân biệt**, áp dụng ẩn ô bổ sung để tránh suy luận ngược. Mốc 5 là chính sách sản phẩm đề xuất, không bảo đảm ẩn danh tuyệt đối.
- **O7** Retention chia theo tài khoản, chat, notes, docs, bài nộp/điểm, logs; thời hạn cụ thể phải được người vận hành duyệt, không tự bịa thời hạn pháp lý.
- **O8** MVP có báo cáo tổng hợp PDF/Excel; người dùng xem dữ liệu và yêu cầu xuất, Admin xử lý thủ công và phản hồi, chưa yêu cầu export tự động toàn bộ.

## 5 nguyên tắc xuyên suốt
1. Quyền hiện tại ưu tiên hơn quyền lịch sử, trừ ngoại lệ kết quả cá nhân được cho phép.
2. Assessment phải truy vết được phiên bản, attempt, lịch sử điểm.
3. AI không quyết định điểm chính thức; giảng viên duyệt đề, điểm chủ quan/Assignment và sửa điểm.
4. Không đưa ra kết luận analytics chắc chắn khi dữ liệu không đủ.
5. Hành động quan trọng có trách nhiệm giải trình, log và thông báo phù hợp.

## MVP và Future
**MVP:** quản lý lớp/thành viên/đồng giảng viên, feed/comments/calendar/in-app notifications; thư viện và chia sẻ tài liệu 5 định dạng, xử lý, version, access control; grounded RAG với citations, 2 chế độ Tutor; Practice Quiz và quy trình duyệt câu hỏi AI; Assessment có timer/resume/version/correction; Assignment có nộp lại/nộp muộn/chấm điểm; dashboard cơ bản có bằng chứng và bảo vệ quyền riêng tư; notes/bookmarks; Admin quản lý tài khoản/quyền, audit, yêu cầu dữ liệu cá nhân, báo cáo tổng hợp PDF/Excel.

**Future/conditional:** diễn đàn độc lập, learning path nâng cao, cảnh báo at-risk tự động, thống kê chủ đề AI nâng cao, ngân hàng câu hỏi/rubric nâng cao, bulk admin; ứng dụng Mobile **sau khi Web ổn định và còn thời gian**. Các ràng buộc an toàn của E4–E6 vẫn phải tuân thủ nếu triển khai các chức năng tương ứng.

## Traceability và quản lý thay đổi
- Mỗi Task tham chiếu Rule ID; test/acceptance criteria kiểm tra các rule có liên quan.
- Nếu rule mơ hồ, ghi Open Question; không tự biến giả định kỹ thuật thành rule.
- Baseline này là tài liệu tham chiếu nghiệp vụ, không phải tuyên bố đã được chuyên gia pháp lý xác minh.

## Ràng buộc triển khai và phạm vi áp dụng — Lumi phổ thông chính khóa
- Đối tượng: học sinh THCS/THPT (lớp 6–12), giáo viên và Admin; không bao gồm tiểu học, đại học, lớp học thêm trong MVP.
- Giữ đúng ba vai trò kỹ thuật `ADMIN`, `LECTURER`, `STUDENT`; trên UI gọi lần lượt là **Quản trị viên**, **Giáo viên**, **Học sinh**. Nhà trường tiếp tục là stakeholder nhận báo cáo qua Admin, không có tài khoản đăng nhập riêng. Không bổ sung Parent hay School Admin.
- Các quy tắc hiện có về bảo mật, trích dẫn RAG, chấm điểm chính thức, audit, retention, lưu vết phiên bản và xử lý ngoại lệ vẫn có hiệu lực trừ các điều chỉnh được ghi rõ dưới đây.

### Điều chỉnh A — lớp học chính khóa
- **A1 (điều chỉnh)** Lớp thuộc hoạt động dạy học chính khóa. Giáo viên/Admin có thể ghi danh học sinh theo danh sách được phép quản lý; nếu cho phép mã tham gia, học sinh gửi yêu cầu và giáo viên duyệt trước khi truy cập. Không coi tự tham gia bằng mã là con đường bắt buộc duy nhất.
- **A2 (giữ)** Học sinh có thể học nhiều lớp môn học, kể cả nhiều lớp của cùng một môn nếu được phân công hợp lệ.
- **A3–A4 (giữ phạm vi quyền)** Giáo viên phụ trách có thể mời giáo viên phối hợp và quản lý thành viên trong phạm vi lớp; can thiệp của Admin phải được ghi audit.
- **A5 (điều chỉnh)** Học sinh không tự ý rời lớp chính khóa qua chức năng tự rời. Việc chuyển lớp, kết thúc ghi danh hoặc loại khỏi lớp do giáo viên/Admin có thẩm quyền thực hiện và phải giữ nguyên lịch sử kết quả theo chính sách lưu giữ.
- **A6 (điều chỉnh)** Giáo viên có thể bật/tắt nhận yêu cầu bằng mã nếu lớp cho phép; tắt mã không ngăn việc ghi danh theo phân công.
- **A7 (bổ sung)** Mỗi lớp môn học gắn môn học, khối 6–12, năm học và định danh lớp hành chính nếu có. Mô hình trường/lớp hành chính là metadata tổ chức phục vụ chính khóa, **không tự tạo role Admin theo trường**. Cần chốt mô hình dữ liệu và quyền trước khi triển khai API.
- **A8 (bổ sung)** Giáo viên tạo/quản lý lớp theo phân công hoặc phạm vi được Admin xác nhận; không mặc định mọi tài khoản giáo viên được tạo lớp chính khóa không giới hạn. Cơ chế xác minh phân công là quyết định triển khai còn mở.

### Điều chỉnh tài khoản và người chưa thành niên
- **F1/K1–K6 (bổ sung ràng buộc)** Học sinh lớp 6–12 có thể chưa thành niên. Trước khi triển khai thực tế phải xác định cơ chế cấp/kích hoạt tài khoản, thông báo quyền riêng tư phù hợp độ tuổi, quy trình đồng ý/đại diện hợp lệ khi pháp luật yêu cầu, kiểm soát truy cập, xử lý yêu cầu dữ liệu và thời hạn lưu giữ đã được phê duyệt. Không suy đoán ngưỡng tuổi hay thời hạn pháp lý.
- **Identity (quyết định chuyển tiếp)** Email/password và self-registration `STUDENT` vẫn là hành vi kỹ thuật hiện có; **chưa mặc định đây là luồng onboarding phù hợp để phát hành cho học sinh phổ thông**. Phương án cấp tài khoản bởi Admin/nhà trường và xác minh quyền đại diện phải được quyết định, đặc tả, kiểm thử trước khi mở cho học sinh thật. Không bổ sung role Phụ huynh trong MVP.

### Điều chỉnh AI và phân tích học tập
- **C4/C6 (bổ sung)** AI Tutor điều chỉnh độ dài, từ vựng, ví dụ và mức hướng dẫn theo khối lớp 6–12, ưu tiên gợi mở từng bước, tránh thay học sinh hoàn thành bài; giáo viên vẫn cấu hình hướng dẫn trong giới hạn chính sách hệ thống.
- **D6 (giữ)** Không cung cấp AI Tutor tích hợp trong phiên Assessment chính thức; không tuyên bố ngăn được công cụ bên ngoài.
- **E3/E6/J1/J5 (bổ sung)** Phân tích tiến độ phải gắn bằng chứng, không tự động gắn nhãn năng lực cố định hay kỷ luật học sinh. UI ưu tiên diễn đạt “Chủ đề cần ôn tập” và “Chưa đủ dữ liệu”; quyền xem dữ liệu cá nhân phải theo vai trò và phạm vi lớp.

### Tác động và giới hạn triển khai
Các thay đổi A1/A5/A7/A8 và onboarding học sinh **chưa được triển khai trong Core**. Các endpoint tự rời lớp, tự đăng ký, tự tạo lớp hiện có trong API Contract được đánh dấu cần điều chỉnh trước khi phát hành cho đối tượng mới. Không được coi việc sửa tài liệu là đã cập nhật schema, migration, backend hoặc UI. Giữ nguyên Rule ID hiện có để traceability; cập nhật acceptance criteria/test tương ứng trước khi nghiệm thu.
