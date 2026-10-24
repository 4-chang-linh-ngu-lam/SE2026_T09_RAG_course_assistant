# Tích hợp 38 API Core đã duyệt — 22/10/2026

Người dùng chốt **“Duyệt 38 API hiện có theo đề xuất”** trong [phạm vi hợp đồng](CORE_REMAINING_CONTRACT_REVIEW_2026-10-22.md). Web hiện có **55 operation** trong allowlist: 14 Identity + 3 Notifications + 17 Classroom + 8 Social + 4 Calendar + 9 Administration/import. Core vẫn là một service với các module nội bộ trong monorepo năm service. Không thêm endpoint, sửa Business Rules, migration hoặc quyền backend trong đợt tích hợp này.

Branch `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8` cộng working tree chưa commit có sẵn và thay đổi tích hợp. Codex thực hiện transport/decoder/adapter/controller/tests theo [skill repository](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md), giữ thay đổi của người dùng. Không commit/push/PR/deploy hoặc thay model/provider.

## Phần đã nối

| Phần | Kết quả và giới hạn |
|---|---|
| Transport | Đúng 55 path/method, UUID cho mọi resource lồng nhau, PUT/DELETE, query whitelist riêng, X-Admin-Reason enum đúng operation. Health/internal/register đóng với browser. Giữ Origin/HMAC TCP-peer context, HttpOnly refresh và error/correlation/unknown semantics |
| Wire API | `adapter.core` và strict decoder cho cả 38 operation mới. DTO thật, nullable/enums/timestamps/cursor/version; kiểm tra receipt khớp parent/resource/student/destination/preview. Không tạo revision, teacher role/name, class code hoặc generic Idempotency-Key |
| Danh sách lớp | Student/teacher đọc đủ trang trong phạm vi backend; bỏ badge/nhãn không có dữ liệu. Không suy ra quyền ghi từ danh sách metadata Admin |
| Feed/comments | Đọc posts/comments qua lớp thật, phân trang và deadline/cancel/actor guard. Create/update/delete qua adapter; post update giữ comments đã đọc. Author-only edit, current membership/assignment và ACTIVE class; moderation delete riêng. Không gán role/email tác giả khi wire không có |
| Calendar | Lịch lớp và lịch tài khoản đọc dữ liệu có scope, CRUD CORE-origin; LEARNING chỉ đọc. ISO có timezone, clear description bằng null, không gửi location chưa hỗ trợ. Sửa tiêu đề/mô tả giữ nguyên thời gian gốc/seconds/sự kiện nhiều ngày; form một ngày từ chối đổi giờ sự kiện nhiều ngày |
| Admin audit | Nối màn hình audit hiện có qua Core.Administration. Cursor traversal, actor ID thật, reason code allowlist; không render arbitrary metadata hoặc tự dựng tên staff. Các trang Intelligence khác vẫn unavailable |
| Session/mutations | Tất cả dùng shared credential queue/session. Không actor đã xác nhận thì không tự refresh rồi ghi. Đổi actor/cancel/timeout không trả partial workspace. Response mutation sai hợp đồng là unknown, không tự replay; Feed/Calendar có cảnh báo và GET tải mới để kiểm tra |
| Ba form quản trị | Đã nối live mời staff, upload nguyên file CSV/XLSX, confirm/re-confirm import và list/detail/review data-request. Code một lần chỉ volatile, xóa khi bàn giao/dispose; replay không dựng lại code. AGY tạo một file trình bày, Codex nối session/controller/navigation/route và kiểm chứng; [chi tiết](CORE_ADMIN_FORMS_INTEGRATION_2026-10-22.md) |

`updateComment` và các mutation quản trị chưa có màn hình tương thích vẫn dùng typed Core port; readiness operation không được coi là completion UI. Chi tiết request/response từng API tại [matrix](CORE_API_MATRIX_2026-10-22.md), [public snapshot](../tests/contracts/core-approved-openapi.json), [Core contract](../../../docs/architect/microservices-v1/core/API_CONTRACT.md) và schema/router sở hữu.

## Kiểm chứng đã chạy

| Lệnh/kiểm tra | Kết quả |
|---|---|
| `npm.cmd run check` trong apps/web | Exit **0**, boundaries + TypeScript + **298/298 tests**, không fail/skip/cancelled |
| `npm.cmd run test:core` | Production Web/Core/worker + PostgreSQL riêng; **21 nhóm HTTP**: 6 nhóm phủ đủ 38 operation mới, 7 Notifications, 8 Identity/security; xem evidence tổng hợp cho lần chạy cuối |
| Live build | Dockerfile Web chạy `npm run build`: boundaries, Next production/type validation, fixture-canary release scan. Không ghi đè `.next` của dev đang mở |
| Staff email | Core SMTP sender thật kiểm tra certificate TLS với CA test riêng, nhận thư trong SMTPS sink nội bộ, decode MIME và accept invitation qua HTTP. Không tắt SSL verification, không forward email ra ngoài, không đổi SMTP dev |
| Roster/enrollment/lifecycle | Version thực; preview MANUAL→AUTO, sync, roster và cả hai transfer; archive chặn ghi 409, restore; Student không quản trị, hết membership không đọc lớp cũ |
| Social/Calendar | Cả 12 operation thật; parent scope 404, author edit, Admin metadata không đọc Social, Student không tạo lịch; description null và class/global live loaders |
| Administration/import | Lock thu hồi phiên; unlock/roles transaction riêng. Audit filters; yêu cầu COMPLETED thực trả IN_REVIEW/POLICY_PENDING. CSV valid/error và confirm/replay thực, code replay null. Ba controller + ba view render state nhận từ HTTP thật; ba route production trả 200, không coi đó là browser click/hydration |
| Runtime | Non-root, package cài từ wheel, Alembic drift check, guarded seed + repeat safety |
| DB outage | ready503/live200 khi DB dừng; ready200 sau phục hồi |
| Cleanup | finally xóa test containers/network/volume, env credentials, TLS key/cert và mail spool; giữ log riêng ngoài repo và summary không chứa payload/secret |
| Dev sau kiểm tra | Core/DB healthy, worker running; Core ready/connected, Web `/login` 200; `/api/v1/classes` không credential trả 401, `/api/v1/documents` vẫn 404. W32Time Running, WSL timesyncd active |
| Browser | Inventory không có app/browser kết nối; **chưa kiểm chứng thao tác/visual live UI** trong đợt này |

Một lần smoke ban đầu lỗi fixture vì đọc raw MIME làm token quoted-printable bị ngắt dòng; đã sửa bằng parser chuẩn rồi chạy lại thành công. Runner dọn stack/credential/key/mail ở cả lần lỗi đó. Không coi lỗi fixture là lỗi API hoặc bỏ qua test. Backend Python không thay đổi trong đợt này; bộ Core 356 tests ở báo cáo trước là evidence lịch sử, không phải lần chạy mới.

[Evidence trước UI](evidence/core-approved-integration-2026-10-22.json) giữ mốc 286 tests; [evidence mới nhất](evidence/core-admin-forms-integration-2026-10-22.json) ghi 298 tests và ba form đã nối. Chỉ ghi số liệu/trạng thái. Log riêng chứa fixture tổng hợp nằm ngoài repo theo đường dẫn runner in; không chép token, mật khẩu, mã kích hoạt, mail hoặc keys vào báo cáo.

## UI AGY đã được duyệt và tích hợp

[Phạm vi ba form cụ thể](CORE_ADMIN_FORMS_REVIEW_2026-10-22.md) được người dùng cho phép rõ việc dùng AGY sau lần bị chặn ban đầu. Skill [lumi-frontend-orchestrator](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md) phân công **“AGY authors UI, Codex owns logic and integration”**. AGY `gemini-3.8-flash-high` đã tạo đúng một file và sửa một lượt theo review, cả hai SUCCESS/exit 0; Codex đã nối và kiểm chứng ba form tại [báo cáo riêng](CORE_ADMIN_FORMS_INTEGRATION_2026-10-22.md).

Lý do từ chối trước đây đã được giải quyết bằng câu trả lời **“Cho phép AGY theo phạm vi này”**; không thử lách lệnh hoặc thay quyền/global model. Task loại trừ .env, token và dữ liệu thật. Ba route hiện đã có UI và guard, kiểm tra source/React rendering/HTTP thật; browser trực tiếp vẫn chưa được kiểm chứng do không có kết nối.

## Phần tiếp theo cần hợp đồng, không được giả dữ liệu

- Classroom administration/accounts còn thiếu catalog/year/semester/homeroom/roster/teaching-assignment/account reads. [Đề xuất 8 GET riêng](CORE_MISSING_READS_PROPOSAL_2026-10-22.md) ghi DTO/quyền/tests; **chưa duyệt/chưa mở proxy**. Preview còn có các mutation không tồn tại như sửa catalog/tên lớp, OVERRIDE, invitation resend/revoke/list; phải giữ unavailable hoặc có đề xuất riêng.
- Ba form Core đã hoàn tất trong phạm vi wire hiện có. Import job/history/resume và executor/download dữ liệu cá nhân vẫn thiếu contract. Requested COMPLETED không chứng nhận đã xử lý/xóa/xuất dữ liệu toàn hệ thống.
- Không suy PRIMARY/ASSISTING cho tài khoản nhiều role hoặc Admin chỉ từ quyền đọc metadata; metadata lớp không cấp quyền xem Social/chat. Chưa có catalog/profile read phù hợp thì không dựng teacher name/count/revision để làm màn hình trông đầy đủ.
- SMTP TLS nội bộ đã kiểm chứng; **SMTP gửi email bên ngoài chưa kiểm chứng**. Browser, AI/RAG và các service Document/AI/Learning/Learner Intelligence chưa có bằng chứng fullstack hoặc thiết kế API đủ để tự triển khai.
- Benchmark hiệu năng trước vẫn chưa giải quyết; không tuyên bố đạt KPI từ HTTP smoke hoặc diagnostics ngắn. [Báo cáo trước](FULLSTACK_PROGRESS_2026-10-22.md) giữ số liệu gốc.

Owner cần review khi có PR: Core.Classroom, Core.Social, Core.Administration/Identity, Common transport và Web. Đây là hoàn tất phạm vi wire đã duyệt với các màn hình live nêu rõ, chưa phải toàn sản phẩm năm service sẵn sàng production.
