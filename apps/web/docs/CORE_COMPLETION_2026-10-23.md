# Hoàn thiện phạm vi Core — 23/10/2026

Cập nhật tiếp nối: [runtime, phương pháp tải và hồi quy Core/Web](CORE_RUNTIME_FOLLOWUP_2026-10-23.md). Các số dưới đây là bằng chứng của lần chạy trước; xem báo cáo tiếp nối trước khi đánh giá hiệu năng hiện tại.

Phạm vi: Core và kết nối Web–Core theo các API đã được duyệt, trên nhánh `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8` cùng thay đổi chưa commit có sẵn. Giữ nguyên Business Rules, migration đã áp dụng và dữ liệu local. Không commit/push/deploy.

## Thay đổi đã triển khai

- Tám GET trong [đề xuất đã được cho phép](CORE_MISSING_READS_PROPOSAL_2026-10-22.md): courses, academic years/semesters, homerooms/roster, teaching assignments, accounts/list/detail. OpenAPI thực tế có 67 operation; Web mở đúng 63, tiếp tục đóng register/health/internal ở proxy sản phẩm. [Ma trận request/response](CORE_API_MATRIX_2026-10-22.md), [Core contract](../../../docs/architect/microservices-v1/core/API_CONTRACT.md).
- Backend kiểm tra ACTIVE ADMIN và trường hiện hành. Classroom giữ cursor theo collection/trường/năm; Identity chỉ trả bảy trường account an toàn qua public interface. Không truy cập model/repository chéo module, không cấp quyền Social/chat từ metadata Admin. Roster đọc cùng phiên bản bằng khóa parent; assignment chỉ gồm phân công đang hiệu lực.
- Mười route quản trị live dùng dữ liệu thật, không chuyển đổi thành preview revision/lastAdmin/OVERRIDE hoặc tạo DTO giả. Lưu status và roles riêng; xem tác động MANUAL→AUTO theo class/roster versions; sync AUTO theo roster hiện hành. Chỉ hiển thị lớp đích phù hợp contract; giáo viên mất điều kiện vẫn hiển thị để Admin thay/bỏ rõ ràng. Roster giữ ID chưa đọc được account cho tới khi Admin bỏ chọn.
- Controller ràng buộc actor/trường/role/route; hủy response muộn sau đổi phiên; chặn gửi lặp khi busy, mutation unknown hoặc chưa reload sau ACK. Đối chiếu là read riêng và cần xác nhận người dùng trước khi mở thao tác mới. Biểu mẫu chỉ xóa draft sau ACK thực, có bảo vệ điều hướng; activation/reset code chỉ ở bộ nhớ và phải xác nhận bàn giao.
- Sửa bình luận được nối vào Social adapter/UI hiện có, chỉ tác giả còn quyền tham gia lớp được sửa; quyền moderation không cho phép sửa lời người khác. Không gắn nhãn Học sinh khi Core không trả role của tác giả.
- Identity auth lookup dùng Session đọc ngắn trên cùng bind và trả connection trước khi endpoint chờ thread. Giữ snapshot DB hiện hành, không cache quyền giữa request. Regression PostgreSQL với pool chỉ một connection xác nhận connection được trả và lần đọc sau thấy trạng thái LOCKED.

## Route đã nối

| Route ID | Nội dung dùng contract thực |
|---|---|
| a.accounts / a.account | Danh sách/chi tiết, status/roles riêng, cấp lại mã Student đủ điều kiện |
| a.catalog | Đọc năm/học kỳ/môn, khối 6–12; tạo môn bằng API hiện có |
| a.homerooms / a.homeroom | Tạo lớp hành chính, thay roster có xác nhận, chuyển học sinh |
| a.classes / a.newClass | Danh sách/tạo lớp môn học, chọn môn/năm/khối/homeroom/giáo viên thật |
| a.classSettings | Đọc metadata, thay PRIMARY/ASSISTING đủ điều kiện |
| a.enrollment | Preview, AUTO/MANUAL, sync, thêm/kết thúc/chuyển membership |
| a.lifecycle | Archive/restore có xác nhận và lý do |

Identity, Notifications, lớp Student/Teacher, feed, lịch, audit và ba form staff invite/import/review dữ liệu cá nhân vẫn sử dụng live adapter. Mock chỉ là preview riêng; các port preview cũ không được dùng để giả lập live workspaces mới.

## Kiểm chứng đã chạy

| Gate | Kết quả |
|---|---|
| Toàn Core, PostgreSQL16, pytest -W error, coverage/JUnit | 386 passed, không skip/failure; suite 680.56 giây |
| Regression lifetime connection PostgreSQL pool1 | 1 passed; chạy riêng sau khi thêm test, không cộng như một test mới vào suite đã thu thập |
| `app.modules.identity.public` facade | 17 passed; line/branch coverage100% |
| Ruff check + format trên bản sao Linux | Đạt, 141 file; tránh cờ executable giả của Windows bind mount |
| npm.cmd run check | Boundary + TypeScript + 314 tests passed, không skip/failure |
| npm.cmd run test:core | Production live build/release scan và 22 nhóm HTTP: 7 Core (46 operation), 7 Notifications, 8 Identity/security |
| Giao diện quản trị | 10 route + 3 form render từ HTTP state/receipts thực; HTTP page200 |
| Runtime production fixture | Non-root, wheel installed, migration/drift, seed lặp, worker, TLS SMTP có xác minh CA, DB outage ready503/live200 và recovery200 |
| Runtime local sau cập nhật | Core8000 ready/DB connected, 67 operation; Web3000/login200 |

Lệnh backend tương đương tại `services/core` với `TEST_DATABASE_URL` disposable PostgreSQL/account CREATEDB: `python -m pytest -q -W error -p no:cacheprovider --cov=app --cov-branch --cov-report=xml --junitxml=test-results.xml`. Không dùng DB vận hành. Lệnh public: `python -m pytest tests/identity/test_public.py -q -W error --cov=app.modules.identity.public --cov-branch --cov-fail-under=100`. Lint/format theo `services/core/tests/README.md`. Web chạy hai npm command trong bảng từ `apps/web`; runner HTTP tự cấp project/cổng/DB/secret riêng và dọn sau cả thành công/thất bại.

Bằng chứng thô nằm trong Windows Temp, không chép JUnit/log/payload/code/token vào repository. [Aggregate không chứa secret](evidence/core-completion-2026-10-23.json), [phép đo tải](../../../services/core/test-evidence/core-completion-2026-10-23/core-load.json) và [Rule traceability](../../../services/core/test-evidence/core-completion-2026-10-23/rule-results.json) lưu số liệu thực. Các lượt tích hợp trước chỉ là baseline; không thay thế kết quả cuối.

## Hiệu năng và giới hạn nghiệm thu

Phép đo cuối: 100 users, 10 lớp/500 Student, warmup30 giây, cấu hình đo600 giây, elapsed601,54 giây, think1 giây. Server Uvicorn và bộ phát HTTPX tách process/GIL; mỗi user giữ pool riêng. Kết quả: **18.342 request; 18.289 HTTP200; backendp95=477,15ms; success=99,711%; wrong-scope=0**. Đạt gate Core backendp95≤500ms, success≥99%, zero wrong-scope. Rule traceability:386 cases, zero skips, zero failed scenarios. Không dùng phép đo20 giây để chứng nhận KPI.

**Clientp95=3.827,51ms; có53 RemoteProtocolError (0,289%)**. Không loại lỗi khỏi mẫu, không retry để làm đẹp số liệu và không thay client time bằng backend time. Các lỗi transport và thời gian chờ phía client vẫn là mục cần chẩn đoán nếu yêu cầu trải nghiệm đồng thời chặt hơn; gate Core vượt qua không chứng nhận độ trễ end-to-end. Đây là tải closed-loop nên throughput không mặc định100 request/giây. Shared development host không dành riêng CPU/RAM; không suy ra năng lực production/full TP-01 từ lượt này.

Không có browser được kết nối trong lượt này: HTTP/React render không chứng nhận click, hydration hay mọi viewport. SMTP đã kiểm chứng là sink TLS riêng với tài khoản giả; chưa chứng nhận email tới hệ thống ngoài. Chưa deploy. Document/AI/Learning/Learner Intelligence và full mixed-service TP-01 thuộc phạm vi khác. `complete_core_g2` của catalog traceability giữ nguyên giới hạn đã định, không tự đổi sang true.

Không bổ sung catalog edit/class rename/year dates/OVERRIDE, invitation list/resend/revoke, import history/job GET hoặc data-copy/deletion executor/retention. Legacy Student có thể đi qua import hiện có; không tự mở endpoint chuyển đổi đơn lẻ.

## Ownership và AGY

Core.Identity, Classroom, Administration, Common/security và Web transport/controller cần review hợp đồng/public interface khi tạo PR. Chưa tự gửi thông báo hay tạo PR.

AGY Flash `gemini-3.8-flash-high` tạo duy nhất `core-management-views.tsx` theo quyền chia sẻ người dùng đã chốt; Codex giữ API/logic/permission/tests và sửa các ánh xạ trạng thái trong repo. Bộ duyệt tự động chặn lượt AGY repair vì diễn giải quyền trước chỉ cho phép tạo file; Codex hoàn thành sửa cục bộ, không gửi thêm nguồn. Không gửi .env, token hoặc dữ liệu thật. Workflow: [.agents skill](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md).
