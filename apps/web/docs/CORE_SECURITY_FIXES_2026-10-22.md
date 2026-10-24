# Sửa xác thực, bảo mật và phân quyền Web–Core — 22/10/2026

> Kiểm thử mới sau đồng bộ Windows Time: xem [full verification](FULL_VERIFICATION_2026-10-22.md). Toàn bộ 356 Core test đạt với NTP vẫn bật; các ghi chú môi trường/UAC bên dưới phản ánh đợt kiểm chứng cũ.

> Follow-up: [đợt tích hợp tiếp theo](CORE_INTEGRATION_FOLLOWUP_2026-10-22.md) đã bổ sung kiểm tra actor sau refresh (kể cả logout-all), dùng chung session cho Notifications và cập nhật bằng chứng mới. Các số test bên dưới giữ lại kết quả của đợt bảo mật ban đầu.

Phạm vi: các lỗi trong audit kết nối, session Identity, giới hạn truy cập Social và đường truyền danh tính client cho rate limit. Codex thực hiện logic và kiểm thử theo skill `lumi-frontend-orchestrator`; không sinh UI qua AGY. Không thay Business Rules, migration đã áp dụng hoặc mở các API đang `blocked-contract`.

## Thay đổi

| Vấn đề | Hành vi sau sửa | Bằng chứng |
|---|---|---|
| F1: logout-all dùng access token hết hạn | Refresh trước khi thu hồi; chỉ retry một lần khi có 401 xác định; không replay kết quả mutation unknown; hiển thị lỗi khi chưa xác nhận thu hồi mọi phiên | `tests/auth-security.test.ts`, HTTP smoke |
| F2: login unknown không thể đối soát | Cho phép refresh/me để xác minh đúng username/email đã yêu cầu; chặn đọc/ghi và logout-all trước đối soát; không tự khôi phục tài khoản khác từ cookie cũ | `tests/auth-security.test.ts`, HTTP smoke |
| Credential race | Serialize login/refresh/logout/activate/reset/invitation; generation guard loại phản hồi phiên cũ; xóa dữ liệu actor cũ khi đổi phiên | `tests/auth-security.test.ts`, các test live-session có sẵn |
| F3: Core chỉ thấy IP của Next | Node listener ký IP TCP peer bằng HMAC SHA-256, kèm method/path/thời gian; Web và Core xác minh bằng khóa server riêng. Ghi đè metadata browser, bỏ raw forwarded IP; fail closed với context sai | `tests/client-identity.test.ts`, Core `tests/identity/test_http_security.py`, HTTP smoke |
| F4: lỗi proxy thiếu correlation | Lỗi local có UUID trong body/header; upstream giữ correlation và Retry-After | `tests/client-identity.test.ts`, HTTP smoke |
| Teacher sửa bài người khác | Chỉ tác giả được sửa; moderation chỉ cho xóa theo scope hiện hành; kiểm tra ACTIVE account/class/membership/teaching assignment trong presentation guards và handler; mock adapter đồng bộ | `tests/social-access.test.ts`, backend Social/security tests |

Quyền cuối cùng vẫn do Core kiểm tra từ trạng thái DB hiện tại; metadata IP không cấp vai trò hoặc quyền tài nguyên. Admin không có quyền đọc Social chỉ nhờ vai trò toàn cục, không có quyền đọc chat riêng tư được thêm vào.

## Cấu hình và hợp đồng

- Chạy Web bằng `npm.cmd run dev` hoặc `npm.cmd start` để dùng `server.mjs`; lệnh Next CLI trực tiếp không tạo attestation và API fail closed.
- `CORE_PROXY_SECRET` tối thiểu 32 ký tự, giống nhau giữa Core/Web, khác khóa JWT/service; chỉ lưu phía server. Compose, Dockerfile, env examples và README đã cập nhật. Không đưa khóa vào `NEXT_PUBLIC_*` hoặc Git.
- Protocol nội bộ đã ghi trong Core [API_CONTRACT](../../../docs/architect/microservices-v1/core/API_CONTRACT.md) và [DESIGN](../../../docs/architect/microservices-v1/core/DESIGN.md). Owner cần review khi tạo PR: Core.Identity/Common và Web transport/session. Chưa tạo PR/commit.
- Listener hiện xác thực peer trực tiếp. Nếu đặt ingress/reverse proxy trước Web, phải thiết kế trust boundary tương ứng trước khi triển khai; không tin tùy ý `X-Forwarded-For`.

## Kiểm chứng

| Lệnh / kiểm tra | Kết quả |
|---|---|
| `npm.cmd run check` trong `apps/web` | 242 test đạt, 0 skip; TypeScript và boundary checks đạt |
| `npm.cmd run build` (live) | Build production và release fixture canary đạt |
| `node --check server.mjs` | Đạt |
| Web dev HTTP `/login`, Core `/health/ready`, Web `/users/me`, route ngoài allowlist | 200/200/401/404 đúng dự kiến; error body/header correlation khớp |
| Web dev `/_next/webpack-hmr` | WebSocket handshake đạt; Next tự quản lý upgrade, không thêm handler trùng |
| `python -m ruff check app tests migrations` và `python -m ruff format --check app tests migrations` | Đạt trên 139 file Python; snapshot riêng chuẩn hóa quyền file POSIX do Windows bind mount đánh dấu executable |
| `node --import tsx scripts/core-security-smoke.ts` | 8 nhóm HTTP thật đạt trên PostgreSQL/Core/Web fixture riêng, tài khoản tổng hợp |
| `python -m pytest -q -W error -p no:cacheprovider --junitxml=/tmp/security-results.xml` với PostgreSQL | 356/356 đạt, 0 skip, 516,19 giây, trên database riêng và đồng hồ ổn định |
| `python tests/security/evidence.py --junit ... --output ...` | 356 cases, 0 skip, 0 scenario thất bại; các service/KPI chưa kiểm chứng vẫn pending |

Smoke HTTP kiểm tra login/profile, HttpOnly refresh cookie/path/SameSite, Student activation, Admin-only rejection, ownership của data requests, scope lớp, Admin Social rejection, mất response login và khôi phục không replay, reset thu hồi access cũ, logout-all sau access expiry, thu hồi session thứ hai, Origin, attestation giả, allowlist và 429/Retry-After. Lệnh yêu cầu `CORE_SECURITY_TEST_MODE=synthetic` và các biến `CORE_SECURITY_*` trỏ vào fixture local riêng; không dùng database vận hành.

Lần chạy backend ban đầu có 401 ngẫu nhiên và một test worker không xử lý hết event tại thời điểm poll. Chẩn đoán JWT chỉ ghi loại lỗi và độ lệch thời gian, không ghi token: `ImmatureSignatureError`, `iat` đi trước khoảng 12 giây. Phép đo riêng ghi nhận wall clock nhảy ±12,5 giây so với monotonic. Ubuntu `systemd-timesyncd` và cập nhật giờ WSL dùng chung kernel Docker xung đột; tạm dừng NTP Ubuntu loại bước nhảy trong phép đo tiếp theo. Lần kiểm chứng lại sử dụng database mới và nguồn giờ ổn định. Không thêm JWT leeway, bỏ kiểm tra `iat`, đổi lịch worker hoặc backdate fixture để che lỗi này. Nguồn clock WSL thử nghiệm đã trả về `tsc` ban đầu; không sửa cấu hình clock lâu dài trong repo.

Các container/database tổng hợp đã được dọn, không thay dữ liệu DB dev để tạo bằng chứng. Core dev cổng 8000 và Web dev cổng 3000 tiếp tục chạy. NTP Ubuntu được phục hồi sau kiểm chứng. Người dùng đã cho phép đồng bộ Windows Time/WSL; phiên hiện tại không có quyền Admin, Windows từ chối mở W32Time. Helper giới hạn tác vụ đã được gửi qua UAC, nhưng Windows trả `The operation was canceled by the user`; helper chưa chạy, chưa sửa Windows Time/nguồn NTP. Đo NTP độc lập xác nhận Windows nhanh khoảng 12,6 giây; máy không thuộc domain và không có W32Time Group Policy. Cần khởi động/resync W32Time trong PowerShell Administrator theo [Core README](../../../services/core/README.md#kết-nối-core-docker-với-web-local-windows), rồi đo lại ít nhất một chu kỳ NTP. Khi hai nguồn giờ còn xung đột, lỗi JWT do clock có thể tái xuất hiện dù code và các test đã đạt trong môi trường ổn định.

Không có browser kết nối trong phiên này: bằng chứng là HTTP cùng state machine/DB tests, chưa chứng nhận thao tác UI hoặc cookie policy bằng browser. SMTP, worker thông báo và 41 operation public ngoài Identity chưa được tích hợp live trong phạm vi sửa bảo mật này. Chi tiết khoảng trống giữ tại [audit](CORE_INTEGRATION_AUDIT_2026-10-22.md) và [API matrix](CORE_API_MATRIX_2026-10-22.md).
