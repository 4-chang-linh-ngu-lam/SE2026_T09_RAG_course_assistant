# Hoàn thiện kết nối Web–Core — 22/10/2026

> Kiểm thử lại sau khi đồng bộ Windows Time: [full verification](FULL_VERIFICATION_2026-10-22.md) ghi nhận 356/356 Core và 266/266 Web đạt với NTP hoạt động, cùng production Compose/HTTP. Nhận định clock và giới hạn bộ test bên dưới là lịch sử của đợt tích hợp trước.

Người dùng yêu cầu xử lý tiếp các vấn đề kết nối sau đợt sửa bảo mật, và đã duyệt riêng ba operation Notifications theo [đề xuất cụ thể](CORE_NOTIFICATION_CONTRACT_REVIEW_2026-10-22.md). Codex thực hiện transport, session, controller, mapping và kiểm thử theo `lumi-frontend-orchestrator`; không sinh layout/UI mới qua AGY. Giữ nguyên các thay đổi backend có sẵn, không sửa Business Rules/migration hoặc tạo endpoint mới.

## Đã xử lý

| Phần | Kết quả / giới hạn |
|---|---|
| Notifications | **Implemented, HTTP verified**: GET inbox với cursor/limit, PATCH một ID đã đọc, POST read-all. Allowlist tăng từ 14 lên 17 operation. Ngoài Identity/Notifications vẫn đóng |
| Decode/mapping | Kiểm tra wire DTO, UUID, bool, timestamp, count và cursor; chống trang/row lặp. Nội dung hiển thị lấy từ nhãn hệ thống theo type; không dùng raw payload, HTML, URL hoặc user_id do payload đưa vào. Type lạ hiển thị generic. Chưa tạo deep link tới các workspace chưa nối |
| Pagination/count | Tải cursor tới hết, deadline chung 15 giây/tối đa 100 trang; lỗi/hủy không công bố dữ liệu dở dang. Count là `unread_count` từ Core, kể cả có hàng chưa render; chỉ snapshot mới cập nhật số toàn inbox. Mark-all vẫn hoạt động khi count > 0 nhưng chưa có hàng hiển thị |
| Read controller | Chỉ ACK hợp lệ mới đổi flag; mark-one phải ACK đúng ID/read:true. Lost response giữ unknown, không tự replay; GET có ticket/actor phù hợp mới đối soát. Đổi actor/unmount hủy request cũ |
| Shared session | Notifications và Identity dùng chung credential queue/token trong bộ nhớ, refresh single-flight và generation guard. Nếu cookie bị một tab khác đổi tài khoản, `/me` sau refresh phải khớp actor đã xác nhận trước khi cài token hoặc logout-all; không đọc inbox/revoke nhầm tài khoản mới |
| Worker | **Implemented, runtime verified**: Compose chạy module worker có sẵn sau migration, cùng Core image/DB; read-only/tmpfs, drop ALL capabilities/no-new-privileges, restart unless-stopped. Không publish host port hoặc nhận JWT/service/proxy secret; không sửa audience/retry/dedup |
| HTTP errors | Correlation/Retry-After giữ được cả khi body lỗi rỗng/HTML/JSON hỏng hoặc success sai status. 4xx bị từ chối vẫn rejected; mutation 5xx/success hỏng vẫn unknown. Error code/message sai kiểu không được đưa vào ApiError. UUID path sai bị từ chối trước network |
| Calendar | **Logic fixed, HTTP blocked-contract**: ngày và đủ hai giờ nhập vào được chuyển từ giờ local của browser thành ISO instants, không hardcode 07:00Z; kiểm tra ngày/giờ thực, DST gap và start < end. Sửa/xóa mang classId; preview từ chối event khác lớp và vẫn bảo vệ deadline read-only. Reset draft/dialog khi đổi class context. Không mở API Calendar |
| Hướng dẫn chạy | Sửa tên env cũ thành CORE_API_URL server-side, WEB_ORIGIN/CORS_ORIGINS. Core README mô tả đúng Identity + Notifications, worker đã có thật trong Compose |

Các GET phân trang là từng transaction riêng; thay đổi từ thiết bị khác trong lúc đọc có thể cần refresh. Không khẳng định một snapshot transaction xuyên tất cả trang hoặc SLA cho mọi kích thước inbox.

## Bằng chứng thực chạy

| Lệnh / kiểm tra | Kết quả |
|---|---|
| Baseline `npm.cmd run check` trong apps/web | Exit 0, 242 tests |
| Final `npm.cmd run check` | Exit 0, **266/266 tests**, 0 skip; boundaries và TypeScript đạt |
| `npm.cmd run build` ở live mode | Exit 0; production build và release fixture canary đạt |
| `python -m pytest tests/notification -q -W error -p no:cacheprovider --junitxml=...` với PostgreSQL riêng | **31/31 tests**, 0 skip, 60,26 giây; backend không sửa Python trong đợt này |
| `node --import tsx scripts/core-notification-smoke.ts` | **7 nhóm HTTP thật** qua PostgreSQL → worker → Core → Web production. Tạo 101 post tổng hợp để vượt cursor 100; recipient isolation, ACK, lost mark-one/all reconciliation, cross-tab cookie actor, revocation đạt |
| `node --import tsx scripts/core-security-smoke.ts` | **8 nhóm auth HTTP hồi quy** đạt, có refresh/profile trước logout-all |
| Compose config và inspect worker dev | Đúng module command, Running, read-only; 0 host port binding, chỉ truyền DATABASE_URL |
| HTTP cấu hình dev sau dọn fixture | Web `/login` 200, `/api/v1/notifications` 401 có correlation, `/api/v1/classes` 404, POST read-all sai Origin 403; Core readiness 200 |
| `git diff --check` | Đạt |

Hai script smoke yêu cầu `CORE_SECURITY_TEST_MODE=synthetic`, loopback HTTP và `CORE_SECURITY_WEB_URL`, `CORE_SECURITY_API_URL`, `CORE_SECURITY_ADMIN_EMAIL`, `CORE_SECURITY_ADMIN_PASSWORD` trỏ vào database test mới được seed theo runbook. Không chạy trên database dev đang sử dụng hoặc dữ liệu thật. Không xuất password, JWT/cookie, raw payload hoặc nội dung chat vào báo cáo.

Không có browser/app được kết nối trong inventory công cụ của phiên này. Đây là bằng chứng HTTP/DB/state machine, chưa chứng nhận tương tác UI bằng browser. Chưa chạy lại toàn bộ backend suite trong đợt này; 31 test Notifications là phạm vi xác minh mới.

Các container/database tổng hợp đã được dọn và file runtime chứa credential test đã xóa. NTP Ubuntu được phục hồi trạng thái active. Core/DB dev healthy, notification-worker dev running; Web dev chạy lại tại localhost:3000 bằng listener có attestation và Turbopack.

## Phần còn lại

- **38 operation public ngoài Identity/Notifications** vẫn chưa nối live. Classroom còn thiếu catalog/teacher/user/homeroom read APIs, mutation tên lớp và semantics preview/revision phù hợp port; không tự bù bằng fixture. Social/Calendar và Administration/import cần chốt wire contract cùng phần thiếu như audit đã chỉ ra.
- SMTP chưa cấu hình; chưa chứng nhận gửi email forgot/invitation. Không thêm provider/credential hoặc báo gửi thành công giả.
- Clock Windows/WSL vẫn cần thao tác Administrator đã nêu ở đợt trước (UAC bị hủy). Kiểm thử DB/HTTP lần này tạm dừng NTP Ubuntu để loại bước nhảy ±12,6 giây, giữ nguyên JWT validation; dịch vụ được phục hồi sau kiểm chứng. Không coi kiểm thử trong clock ổn định là đã sửa đồng hồ hệ thống.
- Owner cần review khi tạo PR: Core.Notification/Common runtime, Web transport/session/controller và Calendar frontend port. Chưa tạo commit/push/PR; không thay API nghiệp vụ hoặc quyền backend.

Ma trận cập nhật nằm tại [CORE_API_MATRIX_2026-10-22.md](CORE_API_MATRIX_2026-10-22.md). Audit cũ giữ lại snapshot trước sửa và liên kết tới tài liệu này.
