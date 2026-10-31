# SRS — ĐẶC TẢ YÊU CẦU PHẦN MỀM

**Mã:** LUMI-SRS-001 · **Phiên bản:** 1.0-DRAFT · **Phạm vi:** Core/Web hiện có và service Document/Learning/Intelligence đề xuất; loại AI Service.

## 1. Giới thiệu

Tài liệu này chuyển Business Rules thành các yêu cầu có ID, điều kiện kiểm chứng và nguồn gốc. Không phải các FR dưới đây đều đã được triển khai. Trạng thái release xác định theo `00_INDEX.md` và bảng trạng thái trong RTM.

### 1.1 Thuật ngữ

- **FR:** Yêu cầu chức năng; **NFR:** Yêu cầu phi chức năng; **BR:** Quy tắc nghiệp vụ; **AC:** Tiêu chí nghiệm thu.
- **School scope:** Phạm vi trường lấy từ backend/identity, không nhận từ UI làm căn cứ cấp quyền.
- **Enrollment episode:** Một khoảng tham gia lớp có thể kết thúc và được lưu lịch sử.
- **PRIMARY/ASSISTING:** Vai trò giáo viên trong từng lớp, không phải global user role.
- **Core MVP:** Bản minh họa các luồng Core/Web, không đồng nhất với Product MVP đầy đủ.

### 1.2 Actors và hệ thống liên quan

Actors: Admin, Lecturer (PRIMARY/ASSISTING), Student, operator được ủy quyền. Ngoài hệ thống: SMTP cho staff, browser, PostgreSQL và môi trường triển khai. Document/Learning/Intelligence là các service nội bộ trong giai đoạn sau. Không thiết kế actor riêng cho Nhà trường/Phụ huynh.

## 2. Functional Requirements — Core Identity & Administration

| ID | Yêu cầu bắt buộc, kiểm chứng được | Rule | Release |
|---|---|---|---|
| FR-ID-01 | Student chỉ được tạo bởi Admin, có username duy nhất, không yêu cầu email; không cho tự đăng ký | F1 | Core |
| FR-ID-02 | Student PENDING kích hoạt bằng code một lần có hạn, đặt mật khẩu; code sai/hết hạn/replay bị từ chối; LOCKED không tự mở | F1 | Core |
| FR-ID-03 | Staff đăng nhập email, Student username; login trả access token và HttpOnly refresh cookie; phiên được revoke khi cần | F1,K2 | Core |
| FR-ID-04 | Hỗ trợ login, refresh rotation, logout, logout-all, password reset theo đúng loại tài khoản và xác thực | F1 | Core |
| FR-ID-05 | Admin cùng trường tìm/lọc danh sách tài khoản, đổi role/status, ghi audit và thu hồi phiên liên quan | F1,F7 | Core |
| FR-ID-06 | Import CSV/XLSX phải preview lỗi/trùng, confirm, chống double-submit và không tạo trùng sau retry | F1,F2 | Core |
| FR-ID-07 | Admin duyệt được data requests theo trạng thái; không báo COMPLETED nếu chưa có policy/executor có bằng chứng | F4,K1,K4,O8 | Core/Policy |
| FR-ID-08 | Quyền nhạy cảm chỉ được cấp khi user còn ACTIVE, role/school hiện hành hợp lệ | F1,K2 | Core |

## 3. Functional Requirements — Classroom

| ID | Yêu cầu bắt buộc, kiểm chứng được | Rule | Release |
|---|---|---|---|
| FR-CL-01 | Chỉ Admin tạo course/homeroom/subject class; lớp gắn môn, khối, năm học/học kỳ, mode và giáo viên | A3,A7,A8 | Core |
| FR-CL-02 | AUTO đồng bộ theo roster hành chính; MANUAL do Admin chỉ định; không có Student self-join/leave | A1,A5,A6 | Core |
| FR-CL-03 | Cho xem trước thay đổi và kiểm tra version trước sync/mode switch; stale phải trả conflict và không ghi đè | A1,F2 | Core |
| FR-CL-04 | Admin thêm/kết thúc/chuyển membership, giữ lịch sử episode; bảo toàn kết quả cá nhân hợp lệ | A4,L2,M1 | Core + Learning |
| FR-CL-05 | Admin phân công PRIMARY/ASSISTING, không để trống PRIMARY khi cần thay; teacher không sửa roster/assignment | A3,H1,H2,M2 | Core |
| FR-CL-06 | Chỉ Admin archive/restore, ngừng hoạt động mới khi archived, kiểm tra lại quyền hiện hành khi restore | F5,M5 | Core |
| FR-CL-07 | Member/Teacher/Admin chỉ đọc tài nguyên theo trường, lớp, trạng thái, action hợp lệ; chặn class_id giả/chuyển | A4,L2 | Core |

## 4. Functional Requirements — Social, Calendar, Notification

| ID | Yêu cầu | Rule | Release |
|---|---|---|---|
| FR-SO-01 | Thành viên hiện hành xem/đăng feed theo quyền; sửa bài của mình; xóa mềm và ẩn nội dung đã xóa | G1,L1 | Core |
| FR-SO-02 | Bình luận trên post còn hiển thị; author sửa; moderation hợp lệ ẩn/xóa với audit | G2,L1,L5 | Core |
| FR-SO-03 | Giáo viên được phân công tạo/sửa/xóa Core calendar event; Student đọc trong lớp | G3 | Core |
| FR-SO-04 | Không cho đăng/sửa hoạt động chung mới trong lớp archived | F5,M5 | Core |
| FR-NO-01 | Người dùng xem inbox của chính mình, mark-read/read-all; không xem notification người khác | G4,K5 | Core |
| FR-NO-02 | Notification phát tới audience đúng thời điểm sự kiện; dedup/retry không gửi nhầm người nhận | F7,L3 | Core |
| FR-NO-03 | Payload notification không chứa password, token, nội dung chat riêng tư, tài liệu nguyên văn | F3,K5 | Core |

## 5. Functional Requirements — Document (**PROPOSED, chưa triển khai**)

| ID | Yêu cầu | Rule |
|---|---|---|
| FR-DOC-01 | Lecturer có thư viện cá nhân và sở hữu nguồn; một nguồn chia sẻ nhiều lớp | B1,B2 |
| FR-DOC-02 | Hỗ trợ PDF/PPTX/DOCX/TXT/Markdown với xử lý/validation và thông tin lỗi | B3,B5 |
| FR-DOC-03 | Quản lý version, chỉ công bố version đã SUCCESS; khi bản mới lỗi dùng bản thành công trước | B4,H3 |
| FR-DOC-04 | PRIMARY/ASSISTING được grant/revoke vào lớp theo quyền hiện hành; không sửa tệp nguồn người khác | B2,B6,O1 |
| FR-DOC-05 | Revoke chặn nguồn tại lần kiểm tra mới, không chỉ ẩn giao diện; cảnh báo trước xóa nguồn dùng nhiều lớp | B6,B7 |
| FR-DOC-06 | Student/teacher lưu notes/bookmarks chỉ chủ sở hữu xem/sửa; giữ chữ tự viết và che quote/source khi mất quyền | G5,H6,L6,O2 |
| FR-DOC-07 | Xử lý crash/retry không làm mất file gốc/previous successful version | H3,QAS-10 |

## 6. Functional Requirements — Learning (**PROPOSED, chưa triển khai**)

| ID | Yêu cầu | Rule |
|---|---|---|
| FR-LE-01 | Tách Practice, Assessment và Assignment, tách kết quả luyện tập khỏi điểm chính thức | D0,D3,D8 |
| FR-LE-02 | Bốn loại câu hỏi: single, multiple, true/false, short answer | D2 |
| FR-LE-03 | Nội dung assessment đã công bố bất biến; mỗi attempt gắn một đề version cụ thể | I4,O3 |
| FR-LE-04 | PRIMARY duyệt công bố chính thức, sửa/hủy điểm nhạy cảm; ASSISTING chỉ thao tác theo phân công | D1,D4,D7,I6,M2,M4 |
| FR-LE-05 | Lưu thành công câu trả lời từng phần, resume khi còn giờ; auto-submit khi hết giờ những gì đã lưu | I1,I2 |
| FR-LE-06 | Double submit/retry/timeout không nhân đôi attempt/submission/grade/evidence | QAS-03 |
| FR-LE-07 | Late policy, resubmission, best/latest/average do giáo viên cấu hình trong giới hạn rule; gia hạn không tự đổi lượt | I3,I5,M3,O5 |
| FR-LE-08 | Người đã chuyển lớp vẫn có quyền giới hạn với kết quả/bài đã nộp/phúc khảo hợp lệ | L2,M1,O4 |
| FR-LE-09 | Điểm cuối cùng của Assignment và câu chủ quan do giáo viên quyết định; sửa điểm lưu version và audit | D4,D5,I6,J3 |
| FR-LE-10 | Learning là nguồn deadline chính thức; thay đổi deadline phát thông báo/bản chiếu lịch có kiểm soát | L3,O5 |

## 7. Functional Requirements — Learner Intelligence (**PROPOSED, chưa triển khai**)

| ID | Yêu cầu | Rule |
|---|---|---|
| FR-LI-01 | Nhận và đối soát learning evidence có provenance, version, idempotency; không lấy điểm cũ đã sửa | E3,J3 |
| FR-LI-02 | Không kết luận mastery nếu thiếu evidence độc lập hoặc coverage; hiển thị “Chưa đủ dữ liệu” | J1,J2,O6 |
| FR-LI-03 | Student xem dữ liệu mình; teacher xem lớp được phân công; không lộ dữ liệu chat riêng tư | E1,E2,E5 |
| FR-LI-04 | Gợi ý tự nguyện, giải thích được căn cứ, không tự chấm/trừng phạt hoặc gắn nhãn cố định | E4,E6,J5 |
| FR-LI-05 | Báo cáo aggregate PDF/Excel qua Admin, có school scope/redaction/audit | F6,O8 |
| FR-LI-06 | Thống kê nhóm liên quan hoạt động AI nếu về sau được cung cấp phải ẩn nhóm dưới 5 và ẩn ô bổ sung; **không triển khai nguồn AI trong đợt này** | J4,O6 |

## 8. Non-functional Requirements (NFR)

| ID | Thuộc tính | Điều kiện kiểm chứng, nguồn | Phạm vi |
|---|---|---|---|
| NFR-SEC-01 | Authentication & session | Hash credential, HttpOnly cookie, CSRF/Origin, revoke session; Core-03 | Core |
| NFR-SEC-02 | Authorization | Không có data leak trên bộ thử cross-school/class/action, fail closed; QAS-04/Core-01 | Toàn hệ thống |
| NFR-SEC-03 | Privacy | Không log/chat/token trong audit/notification; policy data request; K1–K6 | Toàn hệ thống |
| NFR-DI-01 | Data integrity | 0 duplicate/lost operations trên test concurrency có kiểm soát, QAS-03 1.000 case khi Learning triển khai | Core/Learning |
| NFR-PERF-01 | Performance | Class-list backend p95 ≤500ms trong TP-01; mục tiêu Learning riêng theo QAS-05 | Toàn hệ thống |
| NFR-AV-01 | Availability/isolation | Lỗi service độc lập không kéo sập Core functions; các phép đo QAS-01/02 cần điều chỉnh phạm vi vì AI đang hoãn | Toàn hệ thống |
| NFR-REC-01 | Recoverability | Xử lý version lỗi/retry không mất nguồn thành công gần nhất; QAS-10 | Document |
| NFR-SCAL-01 | Scale | 100 CCU / 10 lớp / 50 Student/lớp / 20 docs/lớp, TP-01; không tự nhận đã đạt 358 CCU | Toàn hệ thống |
| NFR-DEP-01 | Deployability | Web/Core CI, migration, health, Compose smoke và version trace | Core/Web |
| NFR-MOD-01 | Modifiability | Thuật toán Intelligence thay mà không sửa logic chấm điểm Learning, QAS-09 | LI/Learning |
| NFR-UX-01 | Accessibility & responsiveness | Bàn phím, nhãn trường, trạng thái tải/lỗi; browser/viewport test thuộc kế hoạch, chưa có mục tiêu WCAG chính thức | Web |
| NFR-OBS-01 | Observability | Correlation ID, audit cấu trúc, version ghi trong evidence, health/readiness | Core |

### 8.1 Phân biệt mục tiêu và bằng chứng

`QUALITY_ATTRIBUTES.md` mô tả mục tiêu, không phải báo cáo đã đạt. Các số test/benchmark từng PR trong repo chỉ chứng minh phạm vi tương ứng. Chưa có full mixed-service TP-01; không suy ra từ `web-build` hoặc class-list subset.

## 9. Interface Requirements

- **IR-01 Web→Core:** same-origin `/api/v1` proxy, JSON, Bearer access, refresh HttpOnly, Origin/CSRF; khớp OpenAPI tại phiên bản đang chạy.
- **IR-02 Core DB:** PostgreSQL schema `core`, Alembic migration; không chỉnh migration cũ.
- **IR-03 SMTP:** chỉ cho staff invitation/recovery; Student nhận mã từ Admin, không yêu cầu email.
- **IR-04 Service→Core:** kiểm tra action-based access bằng service authentication, không tin user_id/class_id từ client làm authority.
- **IR-05 Cross-service events:** version, event ID, idempotent consumer và provenance; contract cho Document/Learning/LI đang PROPOSED.
- **IR-06 UI:** 3 vai trò, error codes có thể xử lý 401/403/404/409/422, không fallback từ live sang mock.

## 10. External constraints và chưa chốt

- Retention và pháp lý dữ liệu người chưa thành niên: cần operator/product duyệt; không tự định thời gian.
- Thời hạn late appeal, công thức chấm/độ tin cậy mastery, cấu hình storage/queue future services: cần thiết kế riêng.
- Các route AI tồn tại trong Web prototype không tạo ra nghĩa vụ triển khai API trong tài liệu này.
- Nếu use case cần quyền lịch sử, điều kiện từng action phải được mô tả trong contract và test negative.

## 11. Acceptance và truy vết

Mỗi FR yêu cầu ít nhất một test và một nơi thiết kế; FR chưa có backend được ghi `PROPOSED`, không tick accepted. Mapping ở `18_Traceability.md`.