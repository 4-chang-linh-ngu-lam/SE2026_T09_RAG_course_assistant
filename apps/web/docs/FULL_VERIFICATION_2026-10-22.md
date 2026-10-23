# Kiểm thử đầy đủ Web–Core — 22/10/2026

Yêu cầu: “oke giờ test all”. Kiểm thử trên working tree hiện tại của `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8`, gồm các thay đổi chưa commit có sẵn. Codex chạy các gate hiện có theo `lumi-frontend-orchestrator`; không tạo UI mới, không đổi nghiệp vụ, migration hay API/permission.

## Kết quả thực chạy

| Gate / lệnh | Kết quả |
|---|---|
| Web `npm.cmd run check` | **266/266**, 0 fail/skip/cancelled; boundaries và TypeScript đạt |
| Web `NEXT_PUBLIC_DATA_MODE=live npm.cmd run build` | Đạt production build và release canary; không chứa marker fixture preview |
| Core `python -m ruff check app tests migrations` | Đạt |
| Core `python -m ruff format --check app tests migrations` | **139 file** đạt; bản sao Linux riêng chuẩn hóa mode 0644 để tránh executable bit giả từ bind mount Windows |
| Core `python -m pytest -q -W error -p no:cacheprovider --cov=app --cov-branch --cov-report=xml:… --junitxml=…` | **356/356**, 0 fail/error/skip, **509,89 giây**; PostgreSQL 16 thật, không tắt NTP |
| Coverage Core từ XML | Dòng **93,53%**, nhánh **78,51%**; không suy diễn thành coverage toàn hệ thống |
| `pytest tests/identity/test_openapi.py -q -W error -p no:cacheprovider` | **2/2** đạt; cũng nằm trong bộ 356 test |
| `pytest tests/identity/test_public.py -q -W error -p no:cacheprovider --cov=app.modules.identity.public --cov-branch --cov-fail-under=100` | **17/17**, coverage dòng/nhánh **100%**; cũng nằm trong bộ 356 test |
| `python tests/security/evidence.py --junit … --performance … --output …` | 356 case, 0 skip, **13 scenario passed / 3 pending / 0 failed**; scenario chưa đủ dịch vụ vẫn pending |
| `docker compose -p <project-test> --env-file <env-test> build` | Đạt Core/migrate/notification-worker/Web; Web Docker build live cũng qua release canary |
| Compose `up -d --wait` | Stack sạch khởi động được; migration hoàn tất; Core readiness đạt |
| Runtime / migration | Core UID **10001**, import app từ **site-packages**; `python -m alembic check`: **No new upgrade operations detected** |
| Seed offline trên DB test mới | Lần đầu `created:true`, lặp cùng school `created:false`; không tạo trùng |
| `node --import tsx scripts/core-notification-smoke.ts` | **7/7 nhóm HTTP** qua Web production → Core → PostgreSQL/worker |
| `node --import tsx scripts/core-security-smoke.ts` | **8/8 nhóm HTTP** qua Web production → Core |
| Dừng/khởi động DB test | Ready **503 / SERVICE_UNAVAILABLE**, live **200** khi DB dừng; ready phục hồi **200** sau khởi động |
| Web dev :3000 và Web production test :13002 | `/login` **200**; GET inbox không token **401**, GET classes chưa mở **404**, POST read-all sai Origin **403**; lỗi có correlation ID |
| Worker inspect | Read-only, drop ALL capabilities, no-new-privileges, không publish port; chỉ nhận DATABASE_URL trong các biến cấu hình DB/secret của ứng dụng |
| `python tests/performance/class_list_load.py --duration-seconds 600 --warmup-seconds 30 --users 100 --output …` | **Đạt ngưỡng Core backend**, 606,68 giây thực đo; **cảnh báo độ trễ client**, xem bên dưới |

Các test HTTP Notifications xác nhận worker phát đúng người nhận, 101 thông báo vượt cursor 100, unread count/ACK, người khác không đánh dấu hộ, mất response mark-one/mark-all được đối soát bằng GET mà không replay, đổi cookie giữa tab không đổi actor inbox hoặc revoke nhầm người, thu hồi session làm mất phiên đúng tài khoản.

Các test HTTP bảo mật xác nhận staff/Student login/activation/profile, Admin-only và quyền dữ liệu cá nhân, chặn Student chưa có membership và Admin đọc Social không có quyền lớp, đối soát login mất response, khôi phục Student thu hồi token cũ, logout-all sau access hết hạn, Origin/attestation/allowlist và rate limit sau năm lần đăng nhập sai.

## Kết quả tải và vấn đề cần theo dõi

Bài đo đủ 100 người dùng / 10 lớp / 500 Student ghi nhận **6.269 request**, **6.262 HTTP 200** và **7 transport_or_contract_error**; tỷ lệ thành công **99,888%**, **0 response sai phạm vi**. Backend p95 **38,18 ms**, đạt ngưỡng Core ≤500 ms, success ≥99% và wrong-scope = 0 theo gate hiện có.

**Client p95 27.232,60 ms**, max **88.470,90 ms**; thông lượng khoảng **10,33 request/giây**. Không coi ngưỡng backend đạt là hiệu năng trải nghiệm người dùng đạt. Timeout 15 giây của HTTPX là timeout theo pha, không phải deadline tổng của một request; không suy diễn max vượt 15 giây thành ứng dụng bỏ qua deadline tổng đã cấu hình. Bảy lỗi được runner gộp chung transport/contract, không đủ dữ liệu để gán toàn bộ cho một loại lỗi.

Probe chẩn đoán 20 giây, 100 người dùng, không warmup, tái hiện client p95 **13,83 giây**, phần chờ trước trace HTTP đầu tiên p95 **13,24 giây**, client event-loop lag p95 **602 ms**. Đây là bằng chứng có độ trễ phía client/điều phối kết nối; chưa xác định nguyên nhân cuối cùng, không khẳng định Core hay mạng là nguồn duy nhất và không dùng probe ngắn làm Core-06 acceptance. Mã ứng dụng, pool/permission/JWT và ngưỡng gate không được sửa để làm đẹp kết quả.

So sánh cùng probe sau khi sao chép dependency/app sang filesystem Linux cho **680 request**, client p95 **7,79 giây**, backend p95 **56,41 ms**, client event-loop lag p95 **219 ms**. Có cải thiện nhưng độ trễ vẫn cao; bind mount không được coi là nguyên nhân duy nhất. Hai probe không có warmup và khác thời điểm, chỉ phục vụ chẩn đoán, không thay số liệu bài đo đủ 600 giây. Raw aggregate của hai probe: [Windows bind](../../../services/core/test-evidence/full-verification-2026-10-22/client-diagnostic-20s-windows-bind.json), [Linux copy](../../../services/core/test-evidence/full-verification-2026-10-22/client-diagnostic-20s-linux-copy.json). Cần phép đo tiếp theo với load generator/server tách process và trace hàng đợi kết nối trước khi kết luận hiệu năng đầu cuối.

Bằng chứng tổng hợp: [verification.json](../../../services/core/test-evidence/full-verification-2026-10-22/verification.json), [core-load.json](../../../services/core/test-evidence/full-verification-2026-10-22/core-load.json), [rule-results.json](../../../services/core/test-evidence/full-verification-2026-10-22/rule-results.json). Ba scenario pending trong catalog backend TASK-015 vẫn là dịch vụ ngoài Core, full mixed-service TP-01 và Web E2E; kết quả Web/HTTP của đợt này được ghi riêng ở bảng trên, chưa có browser E2E.

## Lỗi phát hiện và sửa trong đợt test

Workflow `.github/workflows/core-ci.yml` chỉ tạo SECRET_KEY và INTERNAL_SERVICE_SECRET, thiếu CORE_PROXY_SECRET mà Web listener hiện yêu cầu. Đã bổ sung khóa proxy vào cùng vòng sinh khóa ngẫu nhiên, độc lập và được mask. Thực chạy nguyên block shell trong container xác nhận ba khóa khác nhau, mỗi khóa 256 bit và đều được mask; không in giá trị. Web production không có khóa đã được chạy thử và từ chối khởi động; stack có ba khóa khởi động và qua toàn bộ HTTP smoke.

Đây là sửa cấu hình kết nối đã được yêu cầu trước đó. Không giảm điều kiện khởi động hay dùng chung JWT/internal/proxy key. Owner CI/Common/Web cần review khi tạo PR. Chưa chạy GitHub Actions từ xa; local parity không phải bằng chứng remote CI.

Probe outage đầu dùng PowerShell không đọc được body của HTTP error response, nên assertion của probe thất bại. Kiểm tra lại bằng `curl.exe` ghi riêng body/status xác nhận response ứng dụng đúng 503/SERVICE_UNAVAILABLE và liveness 200; không sửa ứng dụng để làm probe đạt.

## Đồng hồ và cách ly dữ liệu

Windows W32Time và Ubuntu systemd-timesyncd vẫn hoạt động trong toàn bộ lần kiểm chứng này. Đo ban đầu 40 giây: không có bước nhảy trên 100 ms; stripchart NTP có hai mẫu thành công lệch khoảng 9–27 ms và một timeout. [Monitor Docker liên tục](../../../services/core/test-evidence/full-verification-2026-10-22/clock.json) ghi **1.535,72 giây**, **0 bước nhảy trên 100 ms**, chênh lệch wall/monotonic lớn nhất **23,492 ms**. Không tắt NTP, nới JWT leeway hoặc đổi thời gian fixture để vượt qua test; chưa tái hiện lỗi clock/JWT cũ trong đợt này, không bảo đảm đồng hồ sẽ luôn ổn định về sau.

Benchmark dùng một Uvicorn worker và client HTTP loopback bên trong container, PostgreSQL 16 qua Docker bridge riêng; pool 15, overflow 0, closed-loop/think 1 giây. Không đồng thời chạy build/full suite trong giai đoạn đo tải; các dịch vụ dev và workload khác của máy vẫn chạy, không có cách ly tài nguyên. Trường `environment.database` và `background_activity` trong JSON của runner là mô tả tĩnh từ script; cấu hình thực của lần chạy này được nêu tại đây. Không ngoại suy năng lực production hoặc hiệu năng mạng người dùng từ bài đo cục bộ.

Project Compose riêng, database `test_http`/`test_full` riêng và mật khẩu/khóa ngẫu nhiên chỉ phục vụ kiểm thử. Full suite tạo/drop thêm database con theo fixture. Không chạy provisioning, thu hồi phiên hay outage trên database dev đang sử dụng. Log/JUnit/coverage thô lưu ở thư mục tạm ngoài repo; chỉ giữ bằng chứng tổng hợp không chứa credential/token/cookie/raw payload trong repo.

Sau kiểm thử đã xóa toàn bộ container/network/volume của project test và file credential tổng hợp. Core/DB dev vẫn healthy, notification-worker dev running, Web `/login` tại localhost:3000 trả 200 và Core localhost:8000 ready. W32Time vẫn Running, Ubuntu timesyncd vẫn active. `git diff --check` đạt; cảnh báo LF/CRLF của package.json có sẵn không phải lỗi whitespace.

## Phạm vi chưa xác minh

- Inventory repository chỉ có bộ chạy `apps/web/package.json` và `services/core/pyproject.toml`. Các dịch vụ Document/AI/Learning/Learner Intelligence chưa có bộ chạy tương ứng để chứng nhận toàn hệ thống; `complete_core_g2` và `full_tp01_verified` vẫn false.
- Browser inventory không có app/browser được kết nối. Các test HTTP/state machine không thay thế kiểm thử tương tác UI bằng browser.
- SMTP thật chưa cấu hình; chưa chứng nhận gửi email tới hộp thư thật.
- **38 public operation ngoài Identity/Notifications vẫn blocked-contract ở Web**, theo [API matrix](CORE_API_MATRIX_2026-10-22.md). Backend có test không đồng nghĩa các luồng Web đó đã được nối live.
- Chưa commit, push, tạo PR hoặc chạy remote CI.
