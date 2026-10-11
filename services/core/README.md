# Core FastAPI service

Chuẩn bị môi trường theo `.env.example` tại root repo (chỉ mẫu local, không chứa credential production), rồi chạy tại root: `docker compose up --build -d`. Dùng Docker Compose v2 trở lên, Linux containers. Compose chờ PostgreSQL healthy → chạy service `migrate` một lần → chỉ khởi động Core khi migration thành công → khởi động Web khi Core healthy. Không sửa/xóa volume có sẵn để xử lý lỗi migration.

- Liveness: http://localhost:8000/health/live
- Readiness (kiểm tra DB): http://localhost:8000/health/ready
- OpenAPI: http://localhost:8000/docs
- Migration: `docker compose exec core alembic upgrade head`
- Test cục bộ: `cd services/core && pip install -e '.[dev]' && pytest -q`

Health contract: `/health/live` trả `{status:"live"}` (thay `{status:"ok"}` từ skeleton theo TASK-016); `/health/ready` trả `{status:"ready",db:"connected"}` khi kết nối và quyền USAGE schema `core` hợp lệ, ngược lại trả 503 error envelope. Liveness không phụ thuộc DB. Timeout kết nối/pool cấu hình bằng `DATABASE_CONNECT_TIMEOUT_SECONDS` và `DATABASE_POOL_TIMEOUT_SECONDS` (mặc định 3 giây).

Common và Identity auth/profile/data-request API đã triển khai. Classroom, Social, Notification và các endpoint Admin chưa triển khai. Migration 0001 khởi tạo baseline; 0002 tạo `core.audit_events`; 0003 tạo bốn bảng xác thực Identity; 0004 tạo `core.data_requests`. Không dùng mật khẩu DB mặc định trong production.

## Common foundation (TASK-001)

- Cấu hình qua biến môi trường: `DATABASE_URL`, `CORS_ORIGINS` (JSON array), `SECRET_KEY`, `ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES=15`, `REFRESH_TOKEN_EXPIRE_DAYS=7`, `INTERNAL_SERVICE_SECRET`, `COOKIE_SECURE=true`, `COOKIE_HTTPONLY=true`, `COOKIE_SAMESITE=lax`.
- Hai secret phải được cung cấp riêng, tối thiểu 32 ký tự; không có secret mặc định. Health/migration vẫn chạy khi thiếu key; xác thực từ chối an toàn. Chỉ dùng `COOKIE_SECURE=false` cho HTTP local. Identity API áp dụng cấu hình cookie và kiểm tra Origin/Referer ở TASK-003.
- `get_current_user` dùng `get_user_lookup` để lấy `CurrentUser` hiện hành. Bootstrap đã nối dependency này với `identity.public.get_identity_user_lookup` truy vấn DB. Ứng dụng không dùng bootstrap vẫn fail closed khi chưa nối lookup. `require_roles` dùng role hiện hành từ lookup; quyền theo lớp vẫn do Classroom kiểm tra.
- Request nội bộ dùng `X-Service-Key`, so sánh constant-time với `INTERNAL_SERVICE_SECRET`; dependency trả scope `core:check_access`. Endpoint nội bộ phải kiểm tra action/quyền lớp; không dùng JWT người dùng thay credential service.
- Mọi response có `X-Correlation-ID` UUID; giữ UUID hợp lệ từ request hoặc sinh mới. Lỗi HTTP/validation/server trả envelope `error` và không phản chiếu input nhạy cảm. Resource ngoài quyền cần chủ động trả `AppError(404)`.
- `get_pagination` giới hạn 1..100 (mặc định 20). Cursor mã hóa UUID cuối; truy vấn phải sắp xếp theo UUID và lọc `id > cursor`, lấy `limit + 1` để xác định `next_cursor`. Cursor không cấp quyền truy cập.
- `get_db` cung cấp session; `transaction(session)` commit/rollback unit of work do caller sở hữu. Không lồng transaction này vào transaction khác. UUID dùng `uuid4` phía Python và `gen_random_uuid()` có sẵn trên PostgreSQL 16, không cần extension `uuid-ossp`.
- `record_audit` thêm event vào cùng transaction, không tự commit. Chỉ truyền action/target type định danh từ code và `AuditMetadata` đã allowlist; không truyền mô tả tự do, token, mật khẩu, nội dung chat/tài liệu. Mở rộng metadata phải review theo K5/F7.

Kiểm tra tại `services/core`: `ruff check app/common/`, `pytest tests/test_common.py -W error`; kiểm tra toàn Core: `ruff check app tests migrations`, `pytest -W error`.

Test PostgreSQL tại `tests/integration/test_common_db.py` chạy khi có `TEST_DATABASE_URL` trỏ đến database test riêng có thể bỏ đi. Test áp dụng migration, kiểm tra schema drift, lưu audit/UUID/timestamp và rollback; không dùng database production. Khi thiếu biến này, test DB được skip và không được coi là đã kiểm chứng.

## Identity auth core (TASK-002)

- `IdentityService(Session)` nhận session riêng cho từng request; các mutation auth/profile/data request tự commit/rollback, không bao trong transaction khác. Admin helpers dùng savepoint và để public interface/caller quyết định commit. Repository không tự commit. Models thuộc schema `core`: `users`, `role_assignments`, `auth_sessions`, `one_time_tokens`, `data_requests`.
- `register(RegisterRequest)` tạo Student chờ xác minh, trả `RegistrationResult` gồm response an toàn và `TokenDelivery` nội bộ. `verify_email`, `login`, `refresh`, `logout`, `logout_all`, `forgot_password`, `reset_password` xử lý vòng đời xác thực. Module khác phải dùng `identity.public.admin_set_user_status` có kiểm tra quyền/audit, không gọi trực tiếp `set_user_status` nội bộ.
- Request dùng `EmailStr`, email lowercase, mật khẩu mới dài 12..128 ký tự theo API contract. Chưa có chính sách chi tiết về độ phức tạp; không tự thêm yêu cầu ký tự ngoài hợp đồng. Password/token input dùng `SecretStr`; response không chứa hash.
- Token xác minh mặc định 24 giờ (`EMAIL_VERIFICATION_EXPIRE_HOURS`), reset mặc định 60 phút (`PASSWORD_RESET_EXPIRE_MINUTES`), cả hai cấu hình được và chỉ dùng một lần. Đây là thời hạn kỹ thuật, không phải retention dữ liệu. Yêu cầu reset mới vô hiệu hóa token reset cũ; reset thành công tăng session version và thu hồi toàn bộ refresh session.
- Refresh rotation giữ family và hạn hết hạn gốc 7 ngày; phát hiện token revoked được dùng lại sẽ commit thu hồi cả family rồi trả lỗi. Khóa người dùng trước session/token để xử lý cạnh tranh. Logout thu hồi refresh hiện tại; access JWT còn hiệu lực đến hết hạn trừ khi session version/trạng thái thay đổi. Logout-all, đổi mật khẩu và thay đổi trạng thái thu hồi mọi phiên.
- `TokenDelivery` và refresh token chỉ là dữ liệu bàn giao nội bộ, không được trả qua JSON hoặc log. HTTP router truyền callback SMTP vào register/forgot-password; lỗi gửi làm rollback thay đổi DB của thao tác đó. Forgot-password luôn trả phản hồi chung, dù service có/không có delivery.
- `get_current_user_snapshot` và dependency `get_identity_user_lookup` chỉ đọc ID/status/version/roles, không truy vấn password hash. Public interface/data requests đã bổ sung ở TASK-004 bên dưới.

Test Identity: `pytest tests/identity -W error`. Các test service cần `TEST_DATABASE_URL` là PostgreSQL test riêng; kiểm tra migration, schema drift, vòng đời tài khoản, replay, logout-all và request đồng thời. Thiếu biến này thì test service skip; test schema vẫn chạy.

## Identity HTTP API (TASK-003)

- Các route `/api/v1/auth/*` theo [API contract](../../docs/architect/microservices-v1/core/API_CONTRACT.md) đã đăng ký trong bootstrap; `GET/PATCH /api/v1/users/me` dùng Bearer JWT và quyền hiện hành. PATCH bỏ qua `display_name` thì giữ nguyên, `null` thì xóa tên hiển thị; không cho sửa role/status qua profile.
- Refresh cookie tên `refresh_token`, `HttpOnly`, `Secure`, `SameSite=lax`, path `/api/v1/auth`, expiry/max-age theo hạn phiên DB. Login/refresh trả access token JSON với `Cache-Control: no-store`; logout/logout-all/reset xóa cookie cùng path. Không có endpoint trả refresh token hoặc one-time token qua JSON.
- Refresh/logout bắt buộc `Origin` hợp lệ hoặc, khi thiếu Origin, `Referer` thuộc origin trong `CORS_ORIGINS`. Origin có mặt nhưng sai không được fallback sang Referer. Login cũng kiểm tra Origin nếu client gửi header. Client dùng cookie cần gửi credentials; Bearer requests không cần cookie.
- Login tối đa 5 lần thất bại/60 giây theo cả IP và email; register tối đa 3 request/3600 giây theo IP; forgot-password tối đa 3/3600 giây theo IP; verify/reset tối đa 5/60 giây theo IP. 429 có `Retry-After`. Thành công/lỗi hạ tầng không tính thành login sai. Không tin `X-Forwarded-For` tự gửi; chỉ cấu hình trusted proxy ở server khi triển khai.
- Các giới hạn cấu hình qua `AUTH_LOGIN_MAX_FAILURES`, `AUTH_LOGIN_WINDOW_SECONDS`, `AUTH_REGISTER_LIMIT`, `AUTH_FORGOT_LIMIT`, `AUTH_REQUEST_WINDOW_SECONDS`, `AUTH_RESET_LIMIT`, `AUTH_RATE_LIMIT_MAX_KEYS` (10000).
- Mutations nhận `Idempotency-Key` UUID tùy chọn; giữ kết quả thành công 24 giờ và trả 409 khi cùng scope/key khác payload. Scope là user đối với Bearer/refresh, email chuẩn hóa đối với register/login/forgot, token hash đối với verify/reset/logout. Payload chỉ lưu digest, credential responses chỉ giữ trong RAM. Cache login/refresh kiểm tra lại trạng thái, password/session version, expiry và revocation trước replay; key cũ có thể trả 401 khi quyền/phiên đã thay đổi, cần dùng key mới cho lần đăng nhập mới. Bearer authorization luôn chạy trước replay.
- Rate limiter và idempotency cache **chỉ hỗ trợ một process Core**, mất trạng thái khi restart; nhiều worker/replica cần backend dùng chung trước khi triển khai. Cache tối đa `AUTH_IDEMPOTENCY_MAX_KEYS` (1000); đầy capacity trả 503, không tự xóa record chưa hết 24 giờ. Đây chưa phải bảo đảm idempotency bền vững qua restart.

### Cấu hình gửi email

Cung cấp `SMTP_HOST`, `SMTP_FROM` (email hợp lệ), `SMTP_PORT` (mặc định 587), `SMTP_SECURITY=starttls` hoặc `tls` (TLS trực tiếp), `SMTP_TIMEOUT_SECONDS` (10). Nếu SMTP cần đăng nhập, cung cấp đồng thời `SMTP_USERNAME` và `SMTP_PASSWORD`; không ghi credential vào code/log. Compose chuyển tiếp các biến SMTP, `SECRET_KEY`, `INTERNAL_SERVICE_SECRET`, `COOKIE_SECURE` từ môi trường mà không đặt secret mặc định. Khi chạy local HTTP phải chủ động đặt `COOKIE_SECURE=false`.

Thiếu cấu hình SMTP, register/forgot trả 503 trước khi tạo tài khoản/token. Adapter gửi mã một lần và thời gian hết hạn bằng SMTP có xác minh chứng chỉ TLS; chưa có frontend link xác minh/reset. Không gửi email thật trong bộ test.

Gửi SMTP đồng bộ trước DB commit để rollback khi gửi thất bại; nếu SMTP đã nhận email nhưng DB commit sau đó lỗi, email có thể chứa token không hợp lệ. Đây không phải giao dịch nguyên tử giữa SMTP và DB hoặc cơ chế outbox/retry bền vững. Với forgot-password, lỗi gửi trả body generic như tài khoản không tồn tại và ghi log lỗi đã bỏ nội dung nhạy cảm; thao tác DB bị rollback để giữ token reset cũ.

Kiểm thử HTTP/security/SMTP giả: `pytest tests/identity/test_router.py tests/identity/test_http_security.py -W error` (HTTP cần `TEST_DATABASE_URL`). Contract snapshot tại `tests/identity/openapi_contract.json` được kiểm tra bởi `test_openapi.py` trong CI hiện tại; chỉ cập nhật snapshot khi thay đổi API đã được review. SMTP thật, Compose/PostgreSQL 16 và tải nhiều process chưa được kiểm chứng trong TASK-003.

## Identity public interface và data requests (TASK-004)

Module khác chỉ import từ `app.modules.identity.public`; `UserSummaryDTO` gồm `id,email,status`, không chứa ORM/hash. Public read functions: `get_user_summary`, `get_users_summaries`, `verify_user_active`, `get_user_roles`, `check_user_is_lecturer`. Batch fetch dùng một query, bỏ ID không tồn tại, không đọc hash; check lecturer yêu cầu trạng thái ACTIVE và role hiện hành. Tất cả nhận `session=` tùy chọn; khi bỏ qua, interface tự mở/đóng session. DB errors được truyền lên, không tự cấp quyền khi không xác minh được.

`admin_create_user(email, roles, *, actor_id, correlation_id, session=None, deliver=None)` trả `(UserSummaryDTO, SecretStr)`; `admin_set_user_status(user_id, status, *, actor_id, correlation_id, session=None)` nhận ACTIVE/LOCKED. Actor phải là tài khoản ACTIVE đã xác minh, có ADMIN hiện hành; lấy actor từ backend authentication, không từ body do browser gửi. Hai thao tác ghi audit tối thiểu cùng transaction; không tạo audit trùng ở consumer. Nếu cung cấp session, caller commit/rollback unit of work; nếu không, public interface tự commit. Actor/target được khóa theo UUID để tránh đảo thứ tự lock.

Tài khoản Admin tạo có mật khẩu ngẫu nhiên không được bàn giao, trạng thái PENDING_VERIFICATION và token ADMIN_INVITATION lưu hash. Token hết hạn sau `ADMIN_INVITATION_EXPIRE_HOURS` (mặc định 24 giờ), chỉ dùng một lần tại endpoint `/api/v1/auth/password/reset`: đặt mật khẩu, xác minh email và chuyển ACTIVE. Callback `deliver` nhận `TokenDelivery` nội bộ trước commit để gửi SMTP; không callback thì caller chịu trách nhiệm bàn giao token qua kênh an toàn, không JSON/log. Token không kích hoạt được tài khoản LOCKED. API Admin và quản lý role tiếp tục ở TASK-013; không có endpoint Admin mới trong TASK-004.

Data request API:

- `POST /api/v1/users/me/data-requests`: Bearer, `{type: ACCESS|EXPORT|DELETE, reason?}` → 201 `{id,user_id,type,reason,status:PENDING,resolution_note:null,created_at,updated_at}`. Chấp nhận alias input `request_type`; không chấp nhận đồng thời hai tên hoặc các trường user_id/status/resolution_note. Reason tối đa 10000 ký tự. POST hỗ trợ idempotency theo user+endpoint.
- `GET /api/v1/users/me/data-requests?limit=20&cursor=...`: Bearer, `{items,next_cursor}`, chỉ lọc bằng ID người dùng xác thực; thứ tự UUID tăng dần, limit 1..100. Cursor không cấp quyền đọc của người khác.

POST chỉ ghi nhận yêu cầu; không tự xuất/xóa/ẩn danh dữ liệu, khóa tài khoản hoặc đặt thời hạn retention pháp lý. Admin phân loại/xử lý thủ công và ghi resolution ở TASK-013 theo K1/K4/O8. FK không cascade xóa yêu cầu khi xóa user; luồng xóa thật phải xử lý lịch sử theo retention đã duyệt.

Coverage public interface: `pytest tests/identity/test_public.py -W error --cov=app.modules.identity.public --cov-branch --cov-report=term-missing --cov-fail-under=100`. Test PostgreSQL/HTTP nằm trong `test_service.py` và `test_router.py`, cần `TEST_DATABASE_URL` là DB test riêng.

## Docker, migration và CI (TASK-016)

- Core image multi-stage Python 3.12-slim: builder tạo wheel có `app`, runtime chỉ cài wheel/dependencies và copy migrations. Runtime UID/GID 10001, root filesystem read-only, `/tmp` tmpfs, drop capabilities/no-new-privileges. Một Uvicorn worker vì limiter/idempotency còn process-local; proxy headers tắt đến khi có cấu hình proxy tin cậy. Không tự tăng worker khi chưa có backend limiter/cache dùng chung.
- PostgreSQL 16 dùng named volume `pgdata` theo project, port chỉ bind loopback. Các port cấu hình bằng `POSTGRES_PORT` (5432), `CORE_PORT` (8000), `WEB_PORT` (3000); cập nhật `NEXT_PUBLIC_CORE_API_URL` và `CORS_ORIGINS` tương ứng khi đổi port. `CORE_IMAGE` tùy chọn cho tag test độc lập, mặc định `rag-course-core:local`.
- DB credentials và `DATABASE_URL` cần khớp; URL-encode ký tự đặc biệt trong credential. Các default trong mẫu chỉ dùng local. Thay môi trường không tự đổi credential của volume PostgreSQL đã khởi tạo. Stack này chưa phải cấu hình production HA hoặc phân quyền DB cho cả năm service.
- Kiểm tra cấu hình bằng `docker compose config --quiet` (không xuất nội dung secret). Xem trạng thái bằng `docker compose ps -a`; retry migration sau khi sửa nguyên nhân bằng `docker compose run --rm migrate`. Thay đổi schema luôn tạo revision mới; không sửa migration đã áp dụng.
- `.github/workflows/core-ci.yml` chạy trên mọi PR và push main/feature/fix/codex: lint/format, PostgreSQL 16, upgrade/drift check, OpenAPI snapshot, toàn bộ tests có DB và coverage/JUnit artifact, public coverage 100%, Web build và Compose smoke riêng. Smoke kiểm tra non-root/package/migration/health/Web, dừng DB rồi kiểm tra 503/live và phục hồi. Cleanup chỉ project CI riêng, không prune Docker toàn cục.
- Formatter giữ nguyên migration 0001 đã áp dụng bằng exclusion riêng (baseline cũ không được format); lint vẫn kiểm tra file đó. Không có cấu hình mypy hiện tại nên chưa thêm type-check Python; Next build có kiểm tra TypeScript.

Kiểm tra tương đương CI tại `services/core` với `DATABASE_URL`/`TEST_DATABASE_URL` trỏ đến DB test riêng đã cấu hình: `ruff check app tests migrations`, `ruff format --check app tests migrations`, `alembic upgrade head`, `alembic check`, `pytest -W error --cov=app --cov-branch --cov-report=xml --junitxml=test-results.xml`. Không chạy các integration test trên DB có dữ liệu cần giữ. Reports local không được track.

**Bằng chứng local 2026-10-12:** Docker 29.8.2/Compose 5.5.1 Linux engine, project/volume/cổng/image tag riêng từ môi trường sạch; Core UID 10001, wheel/migrations đúng; live/ready/Web đạt. PostgreSQL 16 chạy toàn bộ 124 test, không warning; coverage app 96%, public 100%. Dừng/khởi động DB giữ schema, ready 503→200 và live vẫn 200. GitHub Actions chưa được chạy từ remote ở bước này. Checklist toàn Core còn chờ Classroom, Social, Notification, Admin và các test tương ứng; không coi TASK-016 là nghiệm thu G2/G3.
