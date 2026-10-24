# Ba form quản trị Core đã nối live — 22/10/2026

Sau quyết định **“Cho phép AGY theo phạm vi này”**, AGY Flash tạo đúng một file trình bày và sửa một lượt theo review Codex. Codex nối controller/session/route/navigation, sửa guard, chạy kiểm thử và production integration. Quyền chia sẻ mã nguồn trước đó đã được giải quyết; không còn chờ quyền AGY cho ba form này. [Phạm vi đã duyệt và review](CORE_ADMIN_FORMS_REVIEW_2026-10-22.md).

Branch `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8` cộng working tree chưa commit. Giữ nguyên **55 operation đã duyệt**; không thêm endpoint/DB schema/migration/Business Rule, không đổi quyền backend, không commit/push/deploy. Gói [8 read API bổ sung](CORE_MISSING_READS_PROPOSAL_2026-10-22.md) vẫn chưa duyệt/chưa triển khai.

## Route và hành vi

| Route | Luồng live hiện có | Giới hạn |
|---|---|---|
| `/admin/accounts/staff/invitations` | Email + ADMIN/LECTURER + reason enum → POST /admin/users; hiển thị đúng UserSummaryDTO xác nhận | Cần SMTP server thực được cấu hình để vận hành. Không có token giả, danh sách/resend/revoke invitation hoặc cam kết thư đã tới hộp thư ngoài |
| `/admin/imports/new` | Chọn nguyên file CSV/XLSX → preview server → xem toàn bộ lỗi/action → xác nhận có chủ ý → receipt từng dòng và code lần đầu → xác nhận bàn giao để xóa code | 2.000.000 byte, 100 dòng, username dạng text, cột theo parser hiện có. Không nhập từng phần, không tạo mapping/job/history/read-resume giả |
| `/admin/data-requests` | GET danh sách đủ trang, GET chi tiết, PATCH quyết định + note enum + xác nhận danh tính cần thiết + reason | Chỉ review Core; COMPLETED có thể thực trả IN_REVIEW/POLICY_PENDING. Không có executor/download/xóa hoặc xuất toàn hệ thống |

Ba route có entry trong điều hướng Admin, gồm mục mới **Mời nhân sự**; người dùng không cần đi qua account list chưa có API đọc. Mock preview vẫn dùng feature/port preview riêng; live không fallback vào dữ liệu mẫu.

## Logic và các lỗi đã xử lý

- Wrapper chỉ tạo controller cho phiên authenticated, actor ACTIVE có ADMIN và school scope. State được ràng buộc theo actor/school/roles/route; đổi actor hoặc unmount hủy request, xóa receipt/code và không nhận phản hồi cũ. Backend tiếp tục xác thực quyền hiện hành ở mỗi request.
- Busy chặn double submit; mutation unknown không tự gửi lại. Staff unknown cần đối soát trước lần tạo khác. Data-request unknown chỉ mở đọc trạng thái hiện tại để Admin kiểm tra, không replay PATCH.
- Import unknown confirm có nút **xác nhận lại có chủ ý với cùng preview/reason** theo receipt bền vững của Core. Nhãn/hướng dẫn nói rõ có thể hoàn tất lần nhập; không giả thành GET kiểm tra trạng thái. Replay code=null không tạo lại code.
- Khi đã có preview, khóa đổi file; “Chọn tệp khác” xóa preview/ack/file rồi mới kiểm tra lại. Hai file trùng tên cũng không thể vô tình dùng chung xác nhận cũ.
- Chọn request mới xóa selected cũ trước GET. Lỗi chọn/404 không để yêu cầu của người khác còn thao tác được; read 401/403 xóa dữ liệu đang hiển thị. Ô xác nhận danh tính/draft reset khi request ID đổi.
- Code chỉ nằm trong controller/React memory và được hiển thị từ receipt thật. Không local/session storage, draft store, tự download, tự email hoặc log code. Guard rời trang bảo vệ preview/receipt/unknown đang mở; clear/dispose xóa mã.
- Nội dung người dùng/correlation ID render bằng text; test kiểm tra escaping. Giao diện dùng hướng dẫn tiếng Việt, không đưa endpoint/triển khai backend vào luồng sản phẩm. Bảng cuộn và UUID wrap; chưa có chứng nhận visual browser.
- Sửa thêm guard tab lớp dùng assignment đã xác minh (`isAssignedTeacher`) khi ClassResponse không có nhãn PRIMARY/ASSISTING; không tự gán nhãn đó hoặc mở tab cho Admin metadata. Bỏ badge code lớp trống. Đây là logic hiển thị, không cấp thêm quyền backend.

## Tệp và ownership

| Owner | Tệp chính |
|---|---|
| AGY `gemini-3.8-flash-high` | `src/features/administration/core-admin-views.tsx` — ba component trình bày; lần sinh và một lượt sửa đều SUCCESS/exit 0 |
| Codex | `core-admin-feature.tsx`, `features/index.tsx`, `config/navigation.ts`, `lib/core-admin-routing.ts`, controller, tests và HTTP renderer |
| Codex / shared Web | `components/shell.tsx`, `lib/social-access.ts`, test guard tab lớp và readiness/docs |

AGY chạy qua [skill repository](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md), không shell/test/Git. Task không cung cấp .env, token hay dữ liệu thật. Snapshot hash trước worker được đối chiếu với các thay đổi Codex đã biết; không thấy thay đổi ngoài phạm vi đó trong source được theo dõi. Không đổi global model/provider hoặc cài dependency mới. Log AGY giữ riêng ngoài repo; task sửa dùng một lần đã xóa khỏi workspace.

## Kiểm chứng đã chạy

| Kiểm tra | Bằng chứng |
|---|---|
| `npm.cmd run check` | Exit **0**, boundaries + TypeScript + **298/298 tests**, 0 fail/skip/cancelled |
| `npm.cmd run test:core` | Exit **0**; **21 nhóm HTTP**: 38 API mới trong 6 nhóm + 7 Notifications + 8 Identity/security; production Compose và PostgreSQL riêng |
| Web build | Dockerfile chạy `npm run build` live, Next/type validation và fixture-canary release scan đạt; không ghi đè output dev |
| Ba route production | GET các trang thật trả 200. Đây là kiểm tra availability, không phải click/hydration browser |
| Ba view với dữ liệu backend thật | Renderer React nhận state từ controller sau HTTP thật: staff receipt/email, data-request thực IN_REVIEW, import code lần đầu và replay null. Không callback mutation nào chạy từ render; không lưu HTML/code vào report |
| SMTP | SMTPS sink tổng hợp riêng, certificate verification với CA test, accept invitation thật qua HTTP; không gửi email ra ngoài hoặc đổi SMTP dev |
| Runtime/DB | Non-root, wheel install, Alembic check, seed repeat, ready503/live200 khi mất DB và ready200 khi phục hồi |
| Cleanup | Stack/network/volume riêng, env credential, TLS key/cert và mail spool được xóa; chỉ giữ log riêng và summary tổng hợp |
| Browser | Không có app/browser kết nối trong inventory; chưa có bằng chứng click/keyboard/hydration/visual live browser |

Lần check đầu có **295/296**: test mong câu thông báo replay theo thứ tự từ cũ, trong khi UI đã đổi sang “Mã đã phát hành sẽ không hiển thị lại”. Kiểm tra code không xuất hiện đã đúng; đã sửa assertion theo nội dung được review rồi chạy full suite đạt 298. Không bỏ test hoặc nới điều kiện code/null. Bộ backend đầy đủ 356 tests ở báo cáo trước là evidence lịch sử, không được tính là chạy lại đợt này.

[Evidence tổng hợp lần này](evidence/core-admin-forms-integration-2026-10-22.json) không có secret/payload/mail/HTML. SMTP gửi ra ngoài, browser visual/hydration, benchmark hiệu năng và các service ngoài Core vẫn có giới hạn kiểm chứng riêng. Các workspace cần read API chưa được chốt tiếp tục hiện unavailable, không tạo fixture hoặc revision giả.

Owner cần review khi có PR: Web.Administration/accounts/Identity, shared Web session/navigation, Core.Administration/Identity và Common transport. Không có PR hoặc thông báo bên ngoài được gửi tự động.
