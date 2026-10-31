# PHẦN A — HỆ THỐNG SƠ ĐỒ KIẾN TRÚC LUMI

**Mã:** LUMI-ARC-ATLAS-002 · **Phiên bản:** 2.0-DRAFT · **Ngày:** 31/10/2026  
**Mốc đối chiếu mã nguồn:** nhánh `main`, commit `55324dc37c85c111d439a22f57f5e26544de9ce6` (tại thời điểm đối chiếu).  
**Phạm vi:** Giao diện web và phần lõi đang triển khai; chỉ xác định ranh giới nghiệp vụ của các dịch vụ Tài liệu, Học tập và Phân tích học tập. Dịch vụ trí tuệ nhân tạo được hoãn nghiên cứu, không có thiết kế kỹ thuật, cơ sở dữ liệu, giao diện lập trình hay kế hoạch kiểm thử chi tiết trong hồ sơ này.

> **Đọc sơ đồ đúng cách:** Không có một sơ đồ duy nhất được gọi là “kiến trúc tổng thể” cho mọi mục đích. Kiến trúc hệ thống phải được trình bày bằng nhiều góc nhìn bổ trợ lẫn nhau. Một tầng xử lý về mặt logic không đồng nghĩa với một dịch vụ độc lập, một tiến trình hay một máy chủ vật lý. Đường liền thể hiện quan hệ đã được xác lập trong thiết kế hiện hành; đường nét đứt thể hiện định hướng hoặc nội dung chưa có bằng chứng triển khai. Mọi thành phần chưa được quyết định phải được ghi nhận rõ là đề xuất hoặc đang chờ xác nhận.

## A1. Bản đồ các góc nhìn và mục đích

| Mã hình | Loại sơ đồ | Mục đích trình bày | Căn cứ đối chiếu | Mức độ xác nhận |
|---|---|---|---|---|
| A01 | Ngữ cảnh hệ thống | Những ai và hệ thống ngoài nào đang tương tác với Lumi? | Business Rules, Next.js, Core config | VERIFIED-DESIGN |
| A02 | Bản đồ năng lực | Hệ thống cung cấp năng lực gì; nội dung nào đang hoạt động? | Business Rules, task 001–020, integrations registry | BASELINE |
| A03 | Kiến trúc phân tầng | Các trách nhiệm được phân theo tầng nào? | Web proxy, FastAPI, DB, deployment | LOGICAL VIEW |
| A04 | Tiến trình và đơn vị triển khai | Những tiến trình nào thực sự vận hành? | `compose.yaml`, `app.background_worker` | CODE-GROUNDED |
| A05 | Cấu trúc các phân hệ | Các phân hệ trong phần lõi và ranh giới phụ thuộc? | `services/core/app/bootstrap.py`, `modules/*` | CODE-GROUNDED |
| A06 | Triển khai tại máy phát triển | Cấu trúc chạy Docker Compose trên máy phát triển? | `compose.yaml`, `.env.example` | CODE-GROUNDED |
| A07 | Môi trường tích hợp liên tục | Những phép kiểm tra tự động được chạy và lưu bằng chứng? | `.github/workflows/core-ci.yml` | CODE-GROUNDED |
| A08 | Triển khai trên nền tảng đám mây | Môi trường thử nghiệm trực tuyến được kết nối như thế nào? | `SYSTEM_DESIGN.md`, `tasks/README.md` | REPORTED, NOT LIVE-RECHECKED |
| A09 | Ranh giới bảo mật | Ranh giới tin cậy nằm ở đâu? Thành phần nào kiểm tra quyền? | Core API contract, Web proxy, JWT/cookies | DESIGN/CODE |
| A10–A11 | Trình tự xử lý | Các giao dịch quan trọng đi qua những bước nào? | Identity, Classroom, Notification contracts | DESIGN/CODE |
| A12 | Miền dữ liệu | Các đối tượng nghiệp vụ thuộc quyền quản lý của phân hệ nào? | Migration/core ERD | LOGICAL, NOT FULL PHYSICAL ERD |
| A13–A14 | Phát hành và thực nghiệm | Từ thay đổi mã nguồn đến triển khai, bằng chứng được thu thập ra sao? | CI, Compose, QAS/Test Plan | MIXED: EXISTING/PROPOSED |
| A15 | Ranh giới dịch vụ | Dữ liệu và trách nhiệm của dịch vụ trong tương lai được tách thế nào? | ADR-001/Business Rules | PROPOSED |
| A16 | Xử lý sự cố | Khi xảy ra sự cố, hệ thống được cô lập và khôi phục như thế nào? | OPS/QAS | PROPOSED RUNBOOK |

## A2. Sơ đồ ngữ cảnh hệ thống

![A01 - Ngữ cảnh hệ thống](diagrams_arch/A01_System_Context_Current.png)

### A2.1. Chủ thể

- **Admin:** là tài khoản quản trị trong phạm vi trường đã xác minh; có quyền cấp tài khoản, quản lý lớp và quản trị theo API được bảo vệ. Không có super-admin đa trường trong MVP.
- **Lecturer (giáo viên):** quản lý hoạt động lớp được phân công, không tạo lớp môn học chính khóa hoặc tự điều chỉnh roster. PRIMARY/ASSISTING là assignment theo lớp, không tạo thêm global role.
- **Student (học sinh):** được Admin cấp username và mã kích hoạt một lần; không có self-register/self-join/self-leave.
- **Nhà trường:** bên nhận báo cáo qua Admin, không có role thứ tư.

### A2.2. Các hệ thống và hạ tầng bên ngoài

- **SMTP provider:** hỗ trợ staff invitation/recovery; không gửi student activation. Trạng thái provider cần được phân biệt với trạng thái token trong DB.
- **PostgreSQL Core:** dữ liệu authoritative cho phạm vi Core; public DB connection không phải giao diện phục vụ người dùng.
- **Cloud hosting:** Vercel/Cloud Run/Neon chỉ là hạ tầng của môi trường được báo cáo; không phải yêu cầu bắt buộc để mọi doanh nghiệp sử dụng Lumi.

**Không vẽ** Student gửi yêu cầu trực tiếp vào DB; không đưa AI, search index, vector DB vào luồng đã triển khai; không suy diễn trường học khác là tenant tự phục vụ.

## A3. Bản đồ năng lực nghiệp vụ

![A02 - Bản đồ năng lực nghiệp vụ](diagrams_arch/A02_Capability_Map.png)

**Tách hai khái niệm MVP.** `Core MVP 0.1` có Identity, Classroom, Administration, Social, Calendar và Notifications. Sản phẩm đầy đủ trong Business Rules còn có Document, Learning, Intelligence; những service đó chưa có phía máy chủ live được chứng thực ở baseline. Vì AI Service bị hoãn nghiên cứu, sơ đồ chỉ giữ một ô không thiết kế, không có cạnh kỹ thuật sang các service khác.

**Kiểm tra đối chiếu:** `apps/web/src/lib/data/integrations.ts` có trạng thái `contracted`, `pending-adapter`, `pending-history-api`, `pending-service`, `pending-contract` cho từng năng lực. Việc UI đã có route không có nghĩa tất cả các adapter/live phía máy chủ đã được nghiệm thu.

## A4. Kiến trúc tổng thể theo tầng xử lý

![A03 - Kiến trúc phân tầng](diagrams_arch/A03_Layered_Architecture.png)

### A4.1. Diễn giải từng tầng

| Tầng | Thành phần được thể hiện | Trách nhiệm chính | Giới hạn trách nhiệm | Căn cứ đối chiếu |
|---|---|---|---|---|
| 1. Người sử dụng | Quản trị viên, giáo viên và học sinh | Gửi yêu cầu, tiếp nhận kết quả và xác nhận thao tác | Không tự xác lập vai trò, trường học hoặc quyền truy cập | Quy tắc nghiệp vụ A1–A8, F1 |
| 2. Trình bày | Giao diện Next.js trên trình duyệt | Hiển thị nội dung theo vai trò; kiểm tra biểu mẫu; trình bày trạng thái và lỗi | Không thay thế việc kiểm tra phân quyền tại máy chủ | Mã nguồn giao diện và danh mục tích hợp |
| 3. Tiếp nhận và chuyển tiếp yêu cầu | Bộ chuyển tiếp API thuộc ứng dụng web | Chỉ chuyển tiếp các thao tác được phép; kiểm tra nguồn yêu cầu và cấu hình kết nối | Không tự cấp quyền, bỏ qua xác thực hoặc sử dụng dữ liệu giả lập khi dịch vụ lõi gặp lỗi | Thiết kế giao tiếp và bộ chuyển tiếp API |
| 4. Xử lý nghiệp vụ | Dịch vụ lõi FastAPI với các phân hệ Danh tính, Lớp học, Bảng tin, Thông báo và Quản trị | Thực thi quy tắc nghiệp vụ, kiểm soát quyền, quản lý giao dịch và chuẩn hóa phản hồi | Không truy vấn trực tiếp dữ liệu thuộc dịch vụ độc lập khác | Thiết kế dịch vụ lõi và hợp đồng API |
| 5. Lưu trữ và xử lý nền | PostgreSQL, kho sự kiện, hộp thông báo và tác vụ nền | Bảo toàn dữ liệu, ghi nhận sự kiện, xử lý thông báo và thay đổi cấu trúc dữ liệu | Không cung cấp giao diện truy vấn cơ sở dữ liệu trực tiếp cho người dùng | Tài liệu di trú dữ liệu và cấu hình triển khai |
| 6. Hạ tầng và vận hành | Docker Compose, các môi trường thử nghiệm và hạ tầng đám mây đã được ghi nhận | Đóng gói, triển khai, kiểm tra sức khỏe, quan sát và lưu bằng chứng kiểm thử | Không đồng nhất kết quả kiểm thử tự động với năng lực vận hành thực tế | Cấu hình triển khai và quy trình tích hợp liên tục |

**Cần phân biệt hai góc nhìn:** sơ đồ A03 mô tả sự phân chia trách nhiệm xử lý; các sơ đồ A06–A08 mô tả vị trí triển khai những tiến trình cụ thể. Hiện tại, các phân hệ ở tầng dịch vụ ứng dụng cùng vận hành trong **một dịch vụ lõi FastAPI**, không phải các dịch vụ độc lập. Tiến trình xử lý nền sử dụng chung cấu trúc dữ liệu của dịch vụ lõi.

### A4.2. Quy tắc phụ thuộc và thông điệp lỗi

- Giao diện web gửi yêu cầu thông qua **bộ chuyển tiếp cùng miền**. Bộ chuyển tiếp kết nối đến dịch vụ lõi trong môi trường Docker Compose hoặc địa chỉ dịch vụ tại môi trường đám mây. Trình duyệt không được nhận thông tin bí mật dùng giữa các dịch vụ hoặc thông tin truy cập cơ sở dữ liệu.
- Dịch vụ lõi xác minh thông tin phiên đăng nhập, trạng thái tài khoản, vai trò, phạm vi trường học và quyền thao tác trên tài nguyên. Mã định danh lớp trong yêu cầu chỉ dùng để xác định đối tượng cần xử lý, không tự tạo ra quyền truy cập.
- Khi trạng thái lớp, tài khoản, vai trò hoặc quan hệ ghi danh thay đổi, yêu cầu truy cập tiếp theo phải áp dụng quyền mới. Chỉ ẩn chức năng trên giao diện là không đủ để bảo đảm an toàn.
- Các mã lỗi HTTP 401, 403, 404, 409 và 422 phải được diễn giải thành thông báo phù hợp với từng tình huống. Hệ thống không được tự chuyển sang dữ liệu giả lập để che giấu lỗi từ máy chủ.

## A5. Kiến trúc các đơn vị triển khai và phân hệ ứng dụng

![A04 - Các đơn vị triển khai](diagrams_arch/A04_Container_Runtime.png)

![A05 - Các phân hệ của dịch vụ lõi](diagrams_arch/A05_Core_Component.png)

### A5.1. Các tiến trình và dịch vụ của phần lõi

1. `db`: PostgreSQL 16 Alpine, có health check và volume `pgdata`.
2. `migrate`: job Alembic `upgrade head`, chạy sau DB healthy và trước Core API; `restart: no`.
3. `core`: FastAPI image Core; health/readiness riêng; ràng buộc read-only root filesystem, drop capabilities, no-new-privileges.
4. `notification-worker`: cùng Core image; chạy `python -m app.background_worker`; dùng chung schema Core, xử lý notification và credential delivery.
5. `web`: Next.js server; `NEXT_PUBLIC_DATA_MODE=live` trong Compose bình thường; same-origin API proxy.

Danh tính, chức năng dùng chung, quản lý lớp học, bảng tin, thông báo và quản trị là những **phân hệ nội bộ của dịch vụ lõi**. Việc tách các phân hệ này thành dịch vụ triển khai độc lập trong tương lai phải được giải thích và phê duyệt bằng quyết định kiến trúc riêng.

### A5.2. Ranh giới trách nhiệm giữa các phân hệ

| Từ | Đến | Mục đích | Cơ chế | Kiểm soát |
|---|---|---|---|---|
| Administration | Identity public API | Cấp staff, khóa/mở, gán role, hỗ trợ import | Import qua interface công khai nội bộ (Python public helpers) | Current Admin/school scope, audit |
| Social | Classroom | Kiểm tra thành viên và quyền lớp | Classroom access/public interfaces | Không tin class ID từ client |
| Notification worker | Core DB | Xử lý event và ghi inbox | Transaction + V2 snapshot + dedup/retry | Chỉ allowlist payload |
| Student onboarding | Identity | Kích hoạt bằng mã đã cấp | One-time token hash/purpose/status | Single-use, expiry, không log mã |
| Future Document/Learning | Core | Kiểm tra hành động của user theo lớp | Versioned internal access contract (phụ thuộc triển khai) | Fail closed; cần approved service credential |

## A6. Sơ đồ nghiệp vụ động: tương tác thực tế

### A6.1. Cấp và kích hoạt Student

![A10 - Kích hoạt tài khoản học sinh](diagrams_arch/A10_Seq_Student_Activation.png)

- **Tiền điều kiện:** Admin ACTIVE/cùng trường; Student chưa được tạo; username hợp lệ và chưa trùng.
- **Transaction:** ghi User/Role/Token hash/audit; trả `code` đúng một lần và `Cache-Control: no-store`. Mã là bí mật được bàn giao ngoài app.
- **Kích hoạt:** public `/auth/activate` kiểm tra purpose, hạn, single-use, account status, password validation và ghi thay đổi trạng thái.
- **Negative paths:** không cho Student email signup; mã hết hạn/dùng lại, LOCKED, username sai và trường khác bị chặn; không xác nhận tồn tại tài khoản thông qua thông báo quá chi tiết.

### A6.2. Thay đổi lớp và thông báo

![A11 - Thay đổi lớp học và phát thông báo](diagrams_arch/A11_Seq_Class_Notification.png)

- **Admin mutation:** kiểm tra role/school và `expected_class_version`/roster version khi contract yêu cầu. 409 khi version đã cũ; không lặng lẽ ghi đè.
- **Atomic transaction:** thay đổi nghiệp vụ + audit + V2 event chứa recipient snapshot được commit cùng nhau. Nếu một bước thất bại, khôi phục phiên bản trước mutation liên quan.
- **Worker:** nhận event sau commit, chỉ xử lý V2 hợp lệ, `SKIP LOCKED` và dedup/retry. V1 không có snapshot không được phát theo audience của ngày hôm nay.
- **Client:** GET `/notifications` chỉ nhận inbox của user xác thực. Notification không cấp quyền truy cập nội dung lớp/tài liệu nếu quyền đã bị thu hồi.

## A7. Kiến trúc dữ liệu tổng thể

![A12 - Miền dữ liệu của dịch vụ lõi](diagrams_arch/A12_Core_Data_Domains.png)

**Phân biệt dữ liệu logic và vật lý:** hình A12 chỉ biểu thị các đối tượng miền và liên kết chính. Tên bảng/cột, ràng buộc, index, nullability và migration chính xác phải đọc từ SQLAlchemy models và Alembic 0001–0014. Sơ đồ logic không thay thế “bảng thuộc tính từng bảng” trong `09_LLD_Core.md` và `11_ERD_DFD.md`.

### A7.1. Luồng dữ liệu authoritative và derived

- Identity sở hữu user/credential/session/role; Classroom sở hữu roster/membership/teaching assignment/class trạng thái.
- Social sở hữu post/comment/calendar CORE; Notification sở hữu notification inbox; Common quản lý shared outbox/audit primitives.
- Learning về sau sẽ là nguồn chính thức của attempt/submission/grade/deadline; Core Calendar chỉ là projection của deadline khi contract Learning được duyệt.
- Learner Intelligence về sau nhận evidence versioned; không đọc bảng điểm trực tiếp từ DB Learning, không suy mức độ năng lực từ số lần chat.
- Document về sau sở hữu source/version/grant/note; Core class/course metadata không thay thế permission cấp tài liệu.

### A7.2. Dữ liệu nhạy cảm

- Password/refresh/one-time codes được hash; không chụp token thật vào sơ đồ, issue hoặc test report.
- Audit event cần school-at-event-time nếu có; audit legacy thiếu scope không được đoán scope bằng trạng thái hiện tại.
- Mọi danh sách Admin giới hạn school và role; không expose hash/token hoặc dữ liệu riêng tư không thuộc chức năng.
- School mapping legacy phải dùng manifest có thẩm quyền; migration FK nullable không tự tạo nghĩa vụ backfill dữ liệu thật.

## A8. Ranh giới tương lai — không tự thiết kế công nghệ

![A15 - Ranh giới các dịch vụ](diagrams_arch/A15_Logical_Service_Boundaries.png)

Dựa trên kiến trúc đã duyệt, chỉ ghi nhận ownership: Document (file/version/grant/note), Learning (practice/assessment/assignment/grade) và Learner Intelligence (evidence/recommendation/report). `TASK-017`, `TASK-019`, `TASK-020` mới là bản **đề xuất** cho endpoint/schema/processing. Các thành phần chưa được triển khai phải được vẽ nét đứt và tránh đóng dấu `IMPLEMENTED`.

Không có sơ đồ AI internals trong bộ hồ sơ này; không đặt vector database/embedding pipeline/model provider, không phát biểu giả định chất lượng RAG như bằng chứng triển khai.

## A9. Hướng dẫn sử dụng sơ đồ trong quá trình thẩm định

- **Architect/PM:** xem A01–A03, A08, A15; xác nhận phạm vi, ranh giới và target vs current.
- **Giao diện web engineer:** xem A03–A05, A09–A11; xác nhận route/mutation/lỗi/phiên.
- **Phía máy chủ engineer:** xem A04–A05, A11–A12; đối chiếu transaction, event, access và migration.
- **QA:** xem A07, A10–A14; xây scenario và xác định kết quả đo thực.
- **Ops:** xem A06–A09, A13–A16; xác định secrets, deploy, drift, backup, khôi phục phiên bản trước.

### Chú giải chung

| Ký hiệu | Diễn giải |
|---|---|
| Đường liền | Quan hệ/luồng được mô tả trong baseline triển khai hoặc thiết kế đã xác minh |
| Đường nét đứt | Service/contract tương lai, bước đề xuất hoặc nơi chưa có live evidence |
| `IMPLEMENTED` | Có code trong baseline; không tự khẳng định đã nghiệm thu production |
| `VERIFIED` | Có bằng chứng theo commit/môi trường của một phép kiểm tra cụ thể |
| `PROPOSED` | Đề xuất cần review trước khi trở thành thiết kế được duyệt |
| `NOT DESIGNED` | Chưa được phép/đủ thông tin để thiết kế, không dùng làm đặc tả triển khai |

**Nguồn đối chiếu chính:** Business Rules, ADR-001, `SYSTEM_DESIGN.md`, `core/DESIGN.md`, `core/API_CONTRACT.md`, `compose.yaml`, `.github/workflows/core-ci.yml`, `apps/web/src/lib/api/proxy.ts`, `apps/web/src/lib/data/integrations.ts` ở commit nêu đầu tài liệu. Bản vẽ là sản phẩm biên soạn mới cho Lumi, không sao chép hình minh họa của công ty tham khảo.