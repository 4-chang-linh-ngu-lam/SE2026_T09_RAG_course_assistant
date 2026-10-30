# Core FastAPI service

Chuẩn bị môi trường theo `.env.example` tại root repo (chỉ mẫu local, không chứa credential production), rồi chạy tại root: `docker compose up --build -d`. Dùng Docker Compose v2 trở lên, Linux containers. Compose chờ PostgreSQL healthy → chạy service `migrate` một lần → chỉ khởi động Core khi migration thành công → khởi động Web khi Core healthy. Không sửa/xóa volume có sẵn để xử lý lỗi migration.

- Liveness: http://localhost:8000/health/live
- Readiness (kiểm tra DB): http://localhost:8000/health/ready
- OpenAPI: http://localhost:8000/docs
- Migration: `docker compose exec core alembic upgrade head`
- Test cục bộ: `cd services/core && pip install -e '.[dev]' && pytest -q`

Health contract: `/health/live` trả `{status:"live"}` (thay `{status:"ok"}` từ skeleton theo TASK-016); `/health/ready` trả `{status:"ready",db:"connected"}` khi kết nối và quyền USAGE schema `core` hợp lệ, ngược lại trả 503 error envelope. Liveness không phụ thuộc DB. Timeout kết nối/pool cấu hình bằng `DATABASE_CONNECT_TIMEOUT_SECONDS` và `DATABASE_POOL_TIMEOUT_SECONDS` (mặc định 3 giây).

Common, Identity, Classroom Admin/access, Social, Notification và Administration backend đã triển khai. ACCESS/EXPORT/CORRECTION có quy trình xác minh và attestation thủ công; DELETE giữ IN_REVIEW đến khi có retention/dọn dữ liệu liên service. Core không tự xóa hoặc xuất dữ liệu liên service. Migration 0001 khởi tạo baseline; 0002 tạo `core.audit_events`; 0003 tạo bốn bảng xác thực Identity; 0004 tạo `core.data_requests`; 0005 thêm CORRECTION; 0006 thêm username/school_id/activated_at và email nullable; 0007 thêm Student token purposes; 0008 tạo Classroom theo Lumi; 0009 tạo outbox; 0010 tạo feed, comments và calendar; 0011 tạo inbox và envelope/retry; 0012 thêm audit school scope/index và import drafts/results; 0013 thêm durable staff/reset email delivery; 0014 thêm nullable FK `users.school_id → schools.id` với quy trình validate sau mapping. Không dùng mật khẩu DB mặc định trong production.

## Classroom (TASK-005–008)

- Admin cùng trường tạo môn, lớp hành chính, roster, lớp môn học và phân công PRIMARY/ASSISTING. Học sinh không tự join/leave; giáo viên không tự tạo lớp, mời/chuyển chủ hay sửa roster. API thực tế theo [Core API Contract](../../docs/architect/microservices-v1/core/API_CONTRACT.md).
- `AUTO` đồng bộ membership từ roster; `MANUAL` do Admin quản lý. Đổi MANUAL→AUTO cần preview và xác nhận đúng `class_version`/`roster_version`, stale trả 409. Chuyển học sinh giữa lớp MANUAL hoặc giữa hai lớp hành chính cùng năm/khối ghi mốc UTC và giữ từng đợt membership; AUTO đi theo roster. Lớp ARCHIVED chỉ đọc hoạt động chung, quyền lịch sử cá nhân vẫn kiểm tra riêng.
- School row chỉ được tạo từ `school_id` đã có trong Identity của Admin; không tự map user cũ thiếu trường. Backend kiểm tra role/status/trường hiện hành; các service khác dùng `classroom.public.check_class_action` hoặc internal API với `X-Service-Key` và scope `core:check_access`. Document/Learning/AI vẫn phải kiểm tra quyền nguồn, chủ dữ liệu lịch sử và phân công bài nộp tương ứng.
- Mutation quản trị quan trọng yêu cầu `X-Admin-Reason` thuộc `ADMIN_INTERVENTION`, `POLICY_VIOLATION`, `USER_REQUEST`; audit ghi reason_code đã kiểm tra. Outbox và snapshot người nhận ghi cùng transaction; worker Notification xử lý sau commit. Classroom HTTP Idempotency-Key hiện dùng RAM một process, còn cần cơ chế bền vững nếu chạy nhiều worker. Import CSV/XLSX đã có durable preview_id; mapping School legacy và policy Learning đối với attempt dở còn pending.
- Kiểm tra contract/unit: `pytest tests/classroom/test_contract.py -W error`. Integration cần `TEST_DATABASE_URL` trỏ đến PostgreSQL test riêng: `pytest tests/classroom/test_integration.py -W error`; thiếu DB thì test bị skip và không được tính là bằng chứng đã chạy.

## Social (TASK-009–011)

- Feed: `GET/POST /api/v1/classes/{class_id}/posts`, `PATCH/DELETE /api/v1/classes/{class_id}/posts/{post_id}`. Comments lồng dưới post với GET/POST/PATCH/DELETE. Calendar dùng `GET/POST /api/v1/classes/{class_id}/calendar` và `PATCH/DELETE .../{event_id}`. Không có detail GET cho post và không có HTTP endpoint đồng bộ Learning.
- Tất cả quyền lớp đi qua `classroom.public.check_class_action`; Comments chỉ xác minh post qua `social.feed.public.get_visible_post_ref`, không import model/repository Feed. Author response chỉ có `id,display_name`; Identity được batch lookup một lần mỗi trang, user không còn tồn tại trả tên null.
- Người mất membership/assignment hiện hành không đọc hoặc ghi Social. ARCHIVED vẫn đọc, mọi ghi trả 409. Admin không được đọc; Admin cùng trường chỉ moderation DELETE, ghi audit reason code `POLICY_VIOLATION`. Post/comment soft-delete; CORE calendar event hard-delete; LEARNING projection read-only qua API.
- Cursor là UUID bản ghi cuối trang nhưng repository tra timestamp trong đúng parent trước khi tiếp tục: Feed sắp `created_at DESC,id DESC`; Comments `created_at ASC,id ASC`; Calendar `starts_at ASC,id ASC`. Cursor parent khác trả 400.
- Tạo post ghi `SOCIAL_POST_CREATED`; tạo comment cho tác giả khác ghi `SOCIAL_COMMENT_CREATED`; tạo/cập nhật projection deadline ghi `CALENDAR_DEADLINE_CHANGED`. Outbox và snapshot người nhận cùng transaction, payload không chứa body; recipient/delivery theo TASK-012 bên dưới.
- Public Feed interface: `get_visible_post_ref(class_id, post_id, *, session=None) -> PostRefDTO | None`, chỉ trả `{id,class_id,author_id}` cho post chưa xóa. Internal Calendar helper `upsert_learning_deadline(...)` đang chờ contract TASK-019; event trùng/cũ không ghi đè.
- Test nhanh: `pytest tests/social -q -W error`. Integration/migration: đặt `TEST_DATABASE_URL` tới PostgreSQL test riêng rồi chạy `pytest tests/integration/test_social.py -q -W error`; không có DB thì bị skip và không được tính là bằng chứng PostgreSQL.

## Notification (TASK-012)

- API đã đăng ký: `GET /api/v1/notifications?limit=&cursor=` → `{items,unread_count,next_cursor}`; `PATCH /api/v1/notifications/{id}/read` → `{id,read:true}`; `POST /api/v1/notifications/read-all` → 204. Bearer authentication lấy user hiện hành từ Identity; chỉ đọc/sửa inbox của chính mình. ID người khác/không tồn tại trả 404, cursor ngoài inbox trả 400. Response có `Cache-Control: no-store`.
- Outbox thuộc Common: `record_outbox_event(session, *, event_type, aggregate_id, payload_json, schema_version=2, aggregate_version=None)` thêm event có UUID ổn định, không commit. `aggregate_version` mặc định lấy `payload.version`. V1 được dành cho event cũ không có snapshot người nhận và worker bỏ qua; V2 producer phải ghi snapshot cùng mutation trong một transaction. Lỗi enqueue phải rollback mutation. Không đưa token, activation/reset code hoặc nội dung riêng tư vào event.
- `notification.public.snapshot_audience(session, class_id)` trả `{school_id,recipient_ids}` từ `classroom.public.get_notification_audience(class_id, *, session=None, homeroom=False) -> NotificationAudienceDTO | None`. Classroom bổ sung người vừa kết thúc membership/assignment vào snapshot thông báo thay đổi. Worker kiểm tra lại trường của từng người nhận qua Identity public; Social còn kiểm tra quyền lớp hiện hành và post chưa xóa. Thông báo chỉ chứa ID/phiên bản, không cấp quyền mở nguồn.
- Worker chạy tự động trong Compose sau migration: `docker compose logs notification-worker`. Compose dùng `python -m app.background_worker` để xử lý cả notification outbox và credential email queue; Cloud Scheduler có thể gọi một batch bằng `python -m app.background_worker --once --batch-size 100`. Worker notification độc lập vẫn chạy được bằng `python -m app.modules.notification.worker`. Poll Compose mặc định 2 giây; notification không cần broker/SMTP. Nhiều worker dùng `FOR UPDATE SKIP LOCKED`; insert inbox và `published_at` commit cùng nhau. Crash rollback cả hai, retry không tạo bản sao nhờ unique dedup key.
- Retry dùng thời gian PostgreSQL, backoff 2..300 giây, không tự loại event sau một số lần thử. `attempts/available_at/last_error_code` hỗ trợ vận hành; log chỉ có event UUID và mã lỗi cố định. Event không thuộc allowlist để nguyên cho consumer tương ứng, envelope/payload không hợp lệ được giữ lại để kiểm tra và retry.
- Inbox sắp theo sequence giao nhận giảm dần. Worker và API khóa transaction theo recipient; read-all chốt watermark sau khi lấy khóa, chỉ đánh dấu các thông báo đến trước ranh giới đó. Thông báo commit sau read-all vẫn unread. Event phiên bản cũ/trùng không ghi đè thông báo đã nhận; replay cùng type/aggregate/version được dedup, sự kiện không có version dùng event UUID.
- Test: `pytest tests/notification -q -W error`. Test PostgreSQL cần `TEST_DATABASE_URL` trỏ server test riêng và account có `CREATEDB`: mỗi test tạo database tên `notification_test_<UUID>` rồi xóa đúng database đó. Không đặt biến này tới server production. Không có DB thì integration bị skip. Phạm vi API/schema/event tại [Core contract](../../docs/architect/microservices-v1/core/API_CONTRACT.md); Learning service đầy đủ còn ngoài task này.

## Administration (TASK-013)

- Chỉ Admin ACTIVE, email verified và school scope hiện hành. Staff create, role/status, audit và data-request API theo [Core contract](../../docs/architect/microservices-v1/core/API_CONTRACT.md#administration--implemented-task-013); Student create/issue-code tiếp tục dùng hai route Identity hiện có. Mutation yêu cầu header reason code, không nhận lý do tự do. Mọi response no-store; Identity/Classroom public chịu trách nhiệm audit nghiệp vụ, không ghi trùng ở Administration.
- `POST /admin/users` nhận staff email + ADMIN/LECTURER, không trả token và báo trạng thái giao qua `X-Token-Delivery-Status`. User, invitation và audit được commit trước khi thử SMTP; lỗi gửi giữ user PENDING cùng delivery để worker retry. `POST /admin/users/{id}/invitation/reissue` là thao tác Admin riêng, có audit, vô hiệu token cũ trước khi cấp token mới. PATCH status/PUT roles thu hồi phiên; không mở ACTIVE để bỏ qua activation hoặc tự chuyển credential Student/staff.
- Role/status mutations có advisory transaction lock chung trước user locks, chống gỡ/khóa Admin ACTIVE cuối cùng đã verify và có school scope, kể cả cạnh tranh. School scope của actor/target lấy từ DB. Audit API chỉ trả `AuditEvent.school_id` cùng trường, lọc actor/action/time, cursor trong đúng filter, metadata allowlist; audit legacy thiếu scope vẫn giữ nguyên và bị ẩn, không tự suy mapping.
- `POST /admin/students/imports/preview`: `{format:"CSV"|"XLSX",content_base64,homeroom_class_id?}`. Header `username` bắt buộc, `display_name,user_id` tùy chọn. Giới hạn 100 dòng, file 2 MB; XLSX một sheet, không formula, XML entity/DTD hoặc archive vượt giới hạn. Parser dùng openpyxl/defusedxml. Preview trả lỗi từng dòng, phát hiện trùng/cross-school, không phản chiếu input nhạy cảm.
- Preview hợp lệ hết hạn 30 phút, lưu DB theo actor/school và fingerprints, không raw upload/code. `POST /admin/students/imports/confirm {preview_id}` recheck trạng thái/roster, commit cả batch accounts + tùy chọn append roster + AUTO sync/audit/outbox. Lỗi bất kỳ bước nào rollback tất cả; roster cũ được giữ, không ảnh hưởng MANUAL. `user_id` cho phép gọi helper chuyển username legacy, giữ UUID/hash/status và revoke phiên.
- Confirm đầu trả mã chỉ cho tài khoản Student mới tạo; response code không vào durable results/cache/log. Retry/restart cùng preview trả user IDs/outcomes và `code:null`, `replayed:true`. Nếu mất response mã, cấp lại bằng route activation-codes đã có. Re-import username đã tồn tại dùng EXISTING, không tự reset code hoặc ghi đè display_name. Kết thúc confirm xóa staging rows, giữ kết quả ID/outcome; TTL preview không phải retention pháp lý.
- Data-request ACCESS/EXPORT/CORRECTION/DELETE: list/detail theo trường và audit. Theo chính sách Admin thủ công đã duyệt, ACCESS/EXPORT chỉ COMPLETED sau khi Admin xác minh danh tính và giao qua kênh an toàn được trường phê duyệt; CORRECTION chỉ COMPLETED sau khi service sở hữu hoàn tất và audit. Cả ba cần `identity_verified:true`, `manual_fulfillment_confirmed:true` và note `MANUAL_FULFILLMENT_CONFIRMED`; Core chỉ ghi attestation, không lưu payload hoặc thực thi thay service. DELETE luôn `IN_REVIEW/POLICY_PENDING` với audit DEFERRED đến khi chốt retention và dọn dữ liệu xuyên service. Không tự đọc chat, xóa hoặc xuất dữ liệu liên service.
- Identity public mở rộng: `admin_actor`, `admin_update_user_roles`, `admin_check_student_import`, `admin_list_data_requests`, `admin_get_data_request`, `admin_resolve_data_request`; DTO/command export từ `identity.public`. `admin_create_user/admin_set_user_status` nhận thêm reason_code tùy chọn, giữ tương thích caller cũ. Explicit session do caller commit/rollback. Classroom public `admin_preview_roster/admin_append_roster` dùng session caller, không commit giữa import.
- Kiểm thử: `pytest tests/administration -q -W error`; đặt TEST_DATABASE_URL tới PostgreSQL test riêng/account CREATEDB để chạy thật. Mỗi test tạo/xóa database `administration_test_<UUID>`. Ngày 2026-10-18: **38 test Administration**, **290 test toàn Core** đạt PostgreSQL 16, không skip; gate `identity.public` đạt 100% branch coverage. Đây là bằng chứng backend local, chưa thay thế CI/review/Web E2E.
- Docker Core build + runtime smoke đạt: wheel trong site-packages, UID 10001, XLSX protection, Administration OpenAPI, migration/no drift và Notification worker --once trên PostgreSQL test.

## Migrations và seed (TASK-014)

Quy trình nâng cấp/rollback, mapping School và seed chính thức tại [runbook](migrations/README.md).
Metadata tập trung tại `app/model_registry.py`; head hiện tại `0014`, không tạo revision
rỗng hoặc sửa revision đã áp dụng. Online downgrade có guard giữ dữ liệu và transaction
chung. CLI `python -m app.maintenance --help` có report, outbox-report, plan/apply mapping
theo manifest và seed-dev cho database riêng `dev_`/`test_`. `outbox-report` chỉ trả tổng số
pending/published theo schema_version; không đọc hoặc in payload, aggregate ID hay recipient
và yêu cầu DB đang ở migration head. Migration 0014 giữ `school_id` nullable; nếu
legacy orphan được phát hiện, FK chờ maintenance apply mapping validate sau khi gán
School có căn cứ. Test-only synthetic UUID không được dùng cho database thật. Mapping
user thực vẫn cần owner xác minh; không tự gán trường, kích hoạt hoặc mở LOCKED.

Seed cần `CORE_SEED_ADMIN_PASSWORD` riêng qua môi trường, không có credential mặc định.
Tạo School/Admin, staff invitation và Student activation, lớp khối 6–12 AUTO/MANUAL,
PRIMARY/ASSISTING bằng workflow sở hữu, giữ audit/outbox; chạy lặp không reset dữ liệu.
Test `pytest tests/maintenance -q -W error -p no:cacheprovider` cần PostgreSQL 16 test
riêng và account CREATEDB. CI có migration/check/report trước tests; Compose vẫn chạy
migrate trước Core/worker, không tự seed lúc startup.

Kiểm chứng 2026-10-19: **313 test toàn Core**, gồm **23 test maintenance**, đạt trên
PostgreSQL 16, không skip; Identity public gate **100%**, Ruff lint/format đạt.
Docker wheel/non-root + migration/check + seed/repeat/report đạt. Xem TASK-014 để
phân biệt bằng chứng local với review mapping dữ liệu thực và remote CI còn chờ.

## Backend security/integration (TASK-015)

[Test guide và ma trận](tests/README.md) mô tả backend-only scope, PostgreSQL 16,
HTTP/public workflows, 100 thao tác cạnh tranh cho mỗi sync/transfer/import,
module-boundary guard và script đo tải 10 phút. `tests/security/evidence.py` tạo
Rule ID → scenario → kết quả từ JUnit; missing/skip không được ghi là đã xác minh.
CI lưu evidence, có job đo tải riêng qua workflow_dispatch. Chưa có remote CI run
khi chưa push; Web E2E và các service chưa triển khai được ghi rõ ngoài phạm vi/pending.

Regression đã phát hiện/sửa: cache Classroom recheck tài nguyên hiện hành trước
replay; request DB được queue trước dependency sync để tránh pool/thread starvation.
Pool cấu hình `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=10`, timeout mặc định
3 giây; capacity request mỗi process chừa một slot khi có thể, queue quá hạn trả
no-store 503/Retry-After. Health/OpenAPI bypass gate. Profile đo Core-06 dùng 15+0
để giữ kết nối thay vì tạo/đóng overflow; báo cáo tách backend p95 khỏi client p95.

Ngày 2026-10-19: **342 test đạt PostgreSQL 16**, không skip, coverage tổng **91%**,
Identity public **100%**, lint/format **139 file** và backend Compose outage/recovery
đạt. Bài đo 10 phút/100 user có backend p95 **96.51 ms**, success **99.9912%**;
client p95 **15.58 giây** trên máy dùng chung với coverage/build, không suy ra hiệu
năng end-user hoặc full TP-01. [Bằng chứng an toàn](test-evidence/task015/verification.json)
và [chi tiết phạm vi](tests/README.md); chưa có remote CI/review.

## Common foundation (TASK-001)

- Cấu hình qua biến môi trường: `DATABASE_URL`, `CORS_ORIGINS` (JSON array), `SECRET_KEY`, `ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES=15`, `REFRESH_TOKEN_EXPIRE_DAYS=7`, `INTERNAL_SERVICE_SECRET`, `COOKIE_SECURE=true`, `COOKIE_HTTPONLY=true`, `COOKIE_SAMESITE=lax`.
- Hai secret phải được cung cấp riêng, tối thiểu 32 ký tự; không có secret mặc định. Health/migration vẫn chạy khi thiếu key; xác thực từ chối an toàn. Chỉ dùng `COOKIE_SECURE=false` cho HTTP local. Identity API áp dụng cấu hình cookie và kiểm tra Origin/Referer ở TASK-003.
- `get_current_user` dùng `get_user_lookup` để lấy `CurrentUser` hiện hành. Bootstrap đã nối dependency này với `identity.public.get_identity_user_lookup` truy vấn DB. Ứng dụng không dùng bootstrap vẫn fail closed khi chưa nối lookup. `require_roles` dùng role hiện hành từ lookup; quyền theo lớp vẫn do Classroom kiểm tra.
- Request nội bộ dùng `X-Service-Key`, so sánh constant-time với `INTERNAL_SERVICE_SECRET`; dependency trả scope `core:check_access`. Endpoint nội bộ phải kiểm tra action/quyền lớp; không dùng JWT người dùng thay credential service.
- Mọi response có `X-Correlation-ID` UUID; giữ UUID hợp lệ từ request hoặc sinh mới. Lỗi HTTP/validation/server trả envelope `error` và không phản chiếu input nhạy cảm. Resource ngoài quyền cần chủ động trả `AppError(404)`.
- `get_pagination` giới hạn 1..100 (mặc định 20). Cursor mã hóa UUID cuối. Truy vấn sắp UUID trực tiếp lọc `id > cursor`; consumer có thứ tự nghiệp vụ khác phải tra UUID trong đúng scope để lấy tuple sắp xếp ổn định (Social dùng thời gian + ID). Luôn lấy `limit + 1` để xác định `next_cursor`; cursor không cấp quyền truy cập.
- `get_db` cung cấp session; `transaction(session)` commit/rollback unit of work do caller sở hữu. Không lồng transaction này vào transaction khác. UUID dùng `uuid4` phía Python và `gen_random_uuid()` có sẵn trên PostgreSQL 16, không cần extension `uuid-ossp`.
- `record_audit` thêm event vào cùng transaction, không tự commit; school_id tùy chọn lấy từ backend, audit không có scope bị ẩn khỏi Admin API. Chỉ truyền action/target type định danh từ code và `AuditMetadata` allowlist (có changed_fields/reason_code và identity_verified cho data review); không truyền mô tả tự do, token, mật khẩu, nội dung chat/tài liệu. Mở rộng metadata phải review theo K5/F7.

Kiểm tra tại `services/core`: `ruff check app/common/`, `pytest tests/test_common.py -W error`; kiểm tra toàn Core: `ruff check app tests migrations`, `pytest -W error`.

Test PostgreSQL tại `tests/integration/test_common_db.py` chạy khi có `TEST_DATABASE_URL` trỏ đến database test riêng có thể bỏ đi. Test áp dụng migration, kiểm tra schema drift, lưu audit/UUID/timestamp và rollback; không dùng database production. Khi thiếu biến này, test DB được skip và không được coi là đã kiểm chứng.

## Identity auth core (TASK-002)

- `IdentityService(Session)` nhận session riêng cho từng request; các mutation auth/profile/data request tự commit/rollback, không bao trong transaction khác. Admin helpers dùng savepoint và để public interface/caller quyết định commit. Repository không tự commit. Models thuộc schema `core`: `users`, `role_assignments`, `auth_sessions`, `one_time_tokens`, `data_requests`.
- `register(RegisterRequest)` là logic nội bộ legacy, không export cho consumer; public `/auth/register` deprecated và trả 403. Student dùng username/activation, staff dùng email login/verify/forgot/reset. Role staff có ưu tiên credential email trên tài khoản legacy nhiều role; Student helper chỉ nhận tài khoản STUDENT thuần. Module khác phải dùng public helpers có kiểm tra quyền/audit, không gọi trực tiếp `set_user_status` nội bộ.
- Request dùng `EmailStr`, email lowercase, mật khẩu mới dài 12..128 ký tự theo API contract. Chưa có chính sách chi tiết về độ phức tạp; không tự thêm yêu cầu ký tự ngoài hợp đồng. Password/token input dùng `SecretStr`; response không chứa hash.
- Token xác minh mặc định 24 giờ (`EMAIL_VERIFICATION_EXPIRE_HOURS`), reset mặc định 60 phút (`PASSWORD_RESET_EXPIRE_MINUTES`), cả hai cấu hình được và chỉ dùng một lần. Đây là thời hạn kỹ thuật, không phải retention dữ liệu. Yêu cầu reset mới vô hiệu hóa token reset cũ; reset thành công tăng session version và thu hồi toàn bộ refresh session.
- Refresh rotation giữ family và hạn hết hạn gốc 7 ngày; phát hiện token revoked được dùng lại sẽ commit thu hồi cả family rồi trả lỗi. Khóa người dùng trước session/token để xử lý cạnh tranh. Logout thu hồi refresh hiện tại; access JWT còn hiệu lực đến hết hạn trừ khi session version/trạng thái thay đổi. Logout-all, đổi mật khẩu và thay đổi trạng thái thu hồi mọi phiên.
- `TokenDelivery` và refresh token chỉ là dữ liệu bàn giao nội bộ, không được trả qua JSON hoặc log. Credential delivery dùng bảng Identity riêng, DB chỉ lưu token hash và trạng thái retry; token email được tái tạo trong memory bằng HMAC domain-separated từ `SECRET_KEY` và metadata token. SMTP lỗi không rollback token; delivery retry cùng mã và không được gửi lại trước `available_at`. Secret-key rotation làm delivery không thể tái tạo mã và chuyển sang `NEEDS_REISSUE` thay vì tự sinh mã khác. Forgot-password luôn trả phản hồi chung.
- `get_current_user_snapshot` và dependency `get_identity_user_lookup` chỉ đọc ID/status/version/roles/school_id, không truy vấn password hash. `CurrentUser.school_id` lấy từ DB hiện hành; `require_school_scope` trả 404 nếu scope thiếu hoặc khác. Không lấy school_id từ JWT hoặc body. Migration không backfill tài khoản cũ khi chưa có mapping trường được duyệt.

Test Identity: `pytest tests/identity -W error`. Các test service cần `TEST_DATABASE_URL` là PostgreSQL test riêng; kiểm tra migration, schema drift, vòng đời tài khoản, replay, logout-all và request đồng thời. Thiếu biến này thì test service skip; test schema vẫn chạy.

## Identity HTTP API (TASK-003)

- Các route `/api/v1/auth/*` theo [API contract](../../docs/architect/microservices-v1/core/API_CONTRACT.md) đã đăng ký trong bootstrap; `GET/PATCH /api/v1/users/me` dùng Bearer JWT và quyền hiện hành. PATCH bỏ qua `display_name` thì giữ nguyên, `null` thì xóa tên hiển thị; không cho sửa role/status qua profile.
- Refresh cookie tên `refresh_token`, `HttpOnly`, `Secure`, `SameSite=lax`, path `/api/v1/auth`, expiry/max-age theo hạn phiên DB. Login/refresh trả access token JSON với `Cache-Control: no-store`; logout/logout-all/reset/activate xóa cookie cùng path. Không trả refresh token/staff token qua JSON; chỉ Admin nhận mã Student trực tiếp một lần ở create/issue-code, không cache/log mã.
- Refresh/logout bắt buộc `Origin` hợp lệ hoặc, khi thiếu Origin, `Referer` thuộc origin trong `CORS_ORIGINS`. Origin có mặt nhưng sai không được fallback sang Referer. Login cũng kiểm tra Origin nếu client gửi header. Client dùng cookie cần gửi credentials; Bearer requests không cần cookie.
- Login nhận đúng một trong username/email và password; cả hai/không có identifier trả 422. Username trim/lowercase, 1..200 ký tự không whitespace/@, unique toàn hệ thống. Login tối đa 5 lần thất bại/60 giây theo IP và identifier có namespace; forgot 3/3600 giây; activate/verify/reset 5/60 giây theo IP. Register bị chặn trước DB/SMTP/cache. 429 có `Retry-After`; thành công/lỗi hạ tầng không tính thành login sai. Không tin `X-Forwarded-For` tự gửi; chỉ cấu hình trusted proxy ở server khi triển khai.
- Các giới hạn cấu hình qua `AUTH_LOGIN_MAX_FAILURES`, `AUTH_LOGIN_WINDOW_SECONDS`, `AUTH_REGISTER_LIMIT`, `AUTH_FORGOT_LIMIT`, `AUTH_REQUEST_WINDOW_SECONDS`, `AUTH_RESET_LIMIT`, `AUTH_RATE_LIMIT_MAX_KEYS` (10000).
- Mutations nhận `Idempotency-Key` UUID tùy chọn; giữ kết quả thành công 24 giờ và trả 409 khi cùng scope/key khác payload. Scope là user cho Bearer/refresh, identifier chuẩn hóa cho login, email cho forgot, token hash cho verify/reset/logout; register không cache. Student create/issue-code/activate từ chối header này bằng 400 trước mutation để không cache mã hoặc kết quả sử dụng mã. Payload chỉ lưu digest, credential responses chỉ giữ trong RAM. Cache login/refresh kiểm tra lại trạng thái, password/session version, expiry và revocation trước replay; key cũ trả 401 khi phiên đã đổi. Bearer authorization chạy trước replay.
- Rate limiter và idempotency cache **chỉ hỗ trợ một process Core**, mất trạng thái khi restart; nhiều worker/replica cần backend dùng chung trước khi triển khai. Cache tối đa `AUTH_IDEMPOTENCY_MAX_KEYS` (1000); đầy capacity trả 503, không tự xóa record chưa hết 24 giờ. Đây chưa phải bảo đảm idempotency bền vững qua restart.

### Cấu hình gửi email

Cung cấp `SMTP_HOST`, `SMTP_FROM` (email hợp lệ), `SMTP_PORT` (mặc định 587), `SMTP_SECURITY=starttls` hoặc `tls` (TLS trực tiếp), `SMTP_TIMEOUT_SECONDS` (10) và `PUBLIC_WEB_URL` (origin Web, ví dụ `https://lumi.example.vn`). `PUBLIC_WEB_URL` không có path/query/fragment; chỉ dùng HTTP với localhost khi phát triển. Nếu SMTP cần đăng nhập, cung cấp đồng thời `SMTP_USERNAME` và `SMTP_PASSWORD`; không ghi credential vào code/log. Email mời Admin/nhân sự và email khôi phục mật khẩu có liên kết một lần đến trang hiện có; token nằm trong URL fragment và được xóa khỏi thanh địa chỉ sau khi trang nhận liên kết. Email cũng có mã dự phòng để người nhận nhập thủ công. Student không nhận email: Admin bàn giao mã kích hoạt/khôi phục trực tiếp theo Business Rules. Compose chuyển tiếp các biến SMTP, `PUBLIC_WEB_URL`, `SECRET_KEY`, `INTERNAL_SERVICE_SECRET`, `COOKIE_SECURE` từ môi trường mà không đặt secret mặc định. Worker phải dùng cùng `SECRET_KEY` ổn định với Core API để tái tạo mã đang chờ giao; với Gmail dùng App Password trong secret store, không dùng mật khẩu tài khoản thường. Khi chạy local HTTP phải chủ động đặt `COOKIE_SECURE=false`.

Thiếu SMTP hoặc `PUBLIC_WEB_URL`, forgot vẫn trả phản hồi chung và lời mời nhân sự vẫn được tạo PENDING; email được giữ để worker thử lại sau khi cấu hình hợp lệ. Register luôn bị chặn 403. SMTP dùng TLS có xác minh chứng chỉ; bộ test chỉ dùng SMTP giả, không gửi email thật.

Core lưu token hash và delivery row trong transaction DB trước khi gửi. Nếu SMTP lỗi, trạng thái retry được commit và worker thử lại cùng mã mỗi 15 phút đến khi hết hạn; gửi mail và cập nhật DB không phải giao dịch nguyên tử nên một email có thể được gửi lặp nếu SMTP nhận thư nhưng kết nối đứt trước phản hồi. Admin reissue invitation là thao tác riêng, có audit và vô hiệu mã cũ. Với reset request đang pending, gọi lại forgot-password không đổi mã và không bỏ qua lịch retry.

Cloud Run worker Job phải chạy cùng image Core với lệnh `python -m app.background_worker --once --batch-size 100`, nhận cùng `DATABASE_URL` và `SECRET_KEY` với Core API cùng các biến SMTP. Cloud Scheduler gọi Job theo chu kỳ 15 phút; không chạy worker liên tục trong Job. Cấu hình secret SMTP bằng Secret Manager; không đưa giá trị vào command line, image hoặc repository.

Kiểm thử HTTP/security/SMTP giả: `pytest tests/identity/test_router.py tests/identity/test_http_security.py -W error` (HTTP cần `TEST_DATABASE_URL`). Contract snapshot tại `tests/identity/openapi_contract.json` được kiểm tra bởi `test_openapi.py` trong CI hiện tại; chỉ cập nhật snapshot khi thay đổi API đã được review. SMTP thật, Compose/PostgreSQL 16 và tải nhiều process chưa được kiểm chứng trong TASK-003.

## Identity public interface và data requests (TASK-004)

Module khác chỉ import từ `app.modules.identity.public`; `UserSummaryDTO` gồm `id,email,username,school_id,display_name,status`, không chứa ORM/hash; email/display_name có thể null, username/school_id có thể null cho tài khoản chưa chuyển đổi. Public read functions: `get_user_summary`, `get_users_summaries`, `verify_user_active`, `get_user_roles`, `check_user_is_lecturer`. Batch fetch dùng một query, bỏ ID không tồn tại, không đọc hash; check lecturer yêu cầu trạng thái ACTIVE và role hiện hành. Tất cả nhận `session=` tùy chọn; khi bỏ qua, interface tự mở/đóng session. DB errors được truyền lên, không tự cấp quyền khi không xác minh được. Consumer Social chỉ đưa `id` và `display_name` vào author response, không đưa email/username đăng nhập ra feed. Summary/role không thay thế kiểm tra quyền tài nguyên/trường của consumer.

`admin_create_user(email, roles, *, actor_id, correlation_id, session=None, reason_code=None)` trả `(UserSummaryDTO, TokenDelivery)` sau khi tạo staff và durable invitation; `admin_reissue_user_invitation(user_id, *, actor_id, correlation_id, session=None, reason_code=None)` chỉ cấp lại invitation staff đang pending; `attempt_token_delivery(token_id, deliver, *, session=None)` thử gửi delivery đến hạn. `TokenDelivery` chỉ là dữ liệu handoff nội bộ và không được trả qua JSON/log. `admin_set_user_status(user_id, status, *, actor_id, correlation_id, session=None)` nhận ACTIVE/LOCKED và yêu cầu cùng trường. Actor phải ACTIVE đã xác minh, có ADMIN hiện hành; lấy actor từ backend authentication, không từ body browser. Thiếu school_id hoặc khác trường trả 404; tài khoản cũ phải được gán trường theo mapping được duyệt trước khi gọi Admin helpers. Helpers ghi audit trong transaction; không tạo audit trùng ở consumer. Nếu cung cấp session, caller commit/rollback; nếu không, interface tự commit. Actor/target được khóa theo UUID để tránh đảo thứ tự lock.

Email invitation qua `admin_create_user` chỉ nhận role ADMIN/LECTURER, từ chối STUDENT. Tài khoản có mật khẩu ngẫu nhiên không được bàn giao, PENDING_VERIFICATION và token ADMIN_INVITATION lưu hash. Email mời nhân sự trỏ tới `/staff/invitation`; email khôi phục mật khẩu trỏ tới `/reset-password`. Token nằm trong URL fragment, được Web xóa khỏi thanh địa chỉ sau khi tự điền vào ô mã; email có mã dự phòng nếu người nhận cần nhập thủ công. Hạn `ADMIN_INVITATION_EXPIRE_HOURS` (24 giờ); dùng một lần ở `/auth/password/reset` để đặt mật khẩu/xác minh email/ACTIVE, không mở LOCKED. Core commit invitation trước khi gửi; worker retry cùng mã mỗi 15 phút. Admin reissue vô hiệu mã cũ trước khi tạo mã mới. Student activation/recovery vẫn qua mã Admin bàn giao trực tiếp, không gửi SMTP. Admin user/role/resolve-data-request HTTP còn thuộc TASK-013; Student APIs đã có trong Identity.

### Student provisioning và chuyển tài khoản cũ

- `POST /api/v1/admin/students`, Bearer Admin: `{username,display_name?}` → 201 `{student,purpose:ACTIVATION,code,expires_at}`. School kế thừa từ actor trong DB; email null, role STUDENT, pending dùng enum PENDING_VERIFICATION chung. Mã mặc định 24 giờ, cấu hình `STUDENT_ACTIVATION_EXPIRE_HOURS` (Compose chuyển tiếp), lưu hash và không cần SMTP.
- `POST /api/v1/auth/activate`: `{username,activation_code,new_password}` → 204 ACTIVE với activated_at. Học sinh tự đặt mật khẩu; kiểm tra purpose/tên/hạn/single-use/status, không mở LOCKED. Sau đó login `{username,password}`, refresh/profile/data requests như bình thường; không yêu cầu verify email.
- `POST /api/v1/admin/students/{user_id}/activation-codes`: `{}` cho pending cấp lại activation; ACTIVE cần `{identity_verified:true}` sau khi Admin xác minh thủ công, trả purpose PASSWORD_RESET. Mã reset hạn `PASSWORD_RESET_EXPIRE_MINUTES` (60 phút), dùng tại `/auth/password/reset`. Cấp lại vô hiệu mã trước; cấp reset/hoàn tất reset thu hồi phiên và có audit. Flag ghi nhận xác nhận của Admin, không tự kiểm tra giấy tờ/danh tính. LOCKED không nhận mã.
- Admin nhận mã một lần qua response no-store, giao trực tiếp qua kênh an toàn; không lưu/log hoặc đọc lại qua API. Mất response tạo tài khoản: username unique ngăn tạo trùng, Admin gọi issue-code để cấp mã mới. Create/issue-code/activate không nhận Idempotency-Key.
- Python public: `admin_create_student(username, *, actor_id, correlation_id, display_name=None, session=None) -> StudentCode`; `admin_issue_student_code(user_id, *, actor_id, correlation_id, identity_verified=False, session=None) -> StudentCode`; `admin_assign_student_username(user_id, username, *, actor_id, correlation_id, session=None) -> UserSummaryDTO`. StudentCode chỉ chứa DTO/SecretStr/expiry/purpose, không ORM; repr giấu code. Transaction ownership giống Admin helpers hiện có.
- Không tự chuyển Student cũ: Admin cùng trường gán username qua public helper (consumer Administration). UUID/email/hash/dữ liệu/status được giữ; ACTIVE/LOCKED phải đã verify email, đặt activated_at; LOCKED không tự mở, pending vẫn cần activation. Thu hồi phiên/token email cũ, audit cùng transaction. Username đã gán không được đổi qua helper; cùng username là no-op. Student không thể tiếp tục email login/forgot/verify/reset dù còn email lịch sử.
- Migration không tự gán school_id; phải có mapping được duyệt trước khi dùng Admin helpers. Bulk CSV/XLSX workflow và legacy username đã được Administration nối qua public interface; School/FK mapping dữ liệu cũ vẫn cần phương án được duyệt. Public summary/role không tự cấp quyền tài nguyên.

Data request API:

- `POST /api/v1/users/me/data-requests`: Bearer, `{type: ACCESS|EXPORT|CORRECTION|DELETE, reason?}` → 201 `{id,user_id,type,reason,status:PENDING,resolution_note:null,created_at,updated_at}`. Chấp nhận alias input `request_type`; không chấp nhận đồng thời hai tên hoặc các trường user_id/status/resolution_note. Reason tối đa 10000 ký tự. POST hỗ trợ idempotency theo user+endpoint.
- `GET /api/v1/users/me/data-requests?limit=20&cursor=...`: Bearer, `{items,next_cursor}`, chỉ lọc bằng ID người dùng xác thực; thứ tự UUID tăng dần, limit 1..100. Cursor không cấp quyền đọc của người khác.

POST chỉ ghi nhận yêu cầu; không tự xuất/xóa/ẩn danh dữ liệu, khóa tài khoản hoặc đặt thời hạn retention pháp lý. Admin phân loại/xử lý thủ công và ghi resolution ở TASK-013 theo K1/K4/O8. FK không cascade xóa yêu cầu khi xóa user; luồng xóa thật phải xử lý lịch sử theo retention đã duyệt.

Coverage public interface: `pytest tests/identity/test_public.py -W error --cov=app.modules.identity.public --cov-branch --cov-report=term-missing --cov-fail-under=100`. Test PostgreSQL/HTTP nằm trong `test_service.py` và `test_router.py`, cần `TEST_DATABASE_URL` là DB test riêng.

**Kiểm chứng Identity Lumi 2026-10-14:** Python 3.12.14, PostgreSQL 18 tạm riêng; toàn Core 153 test đạt với warnings-as-errors, public line/branch coverage 100%; Ruff lint/format và Compose config validation đạt. Bao gồm Student không email/SMTP, activation/recovery expiry/replay/concurrency, provision trùng username, chuyển legacy giữ ID/hash, chéo trường, audit không có mã, CORRECTION, upgrade từ 0004 giữ dữ liệu, migration round trip/drift. Migration chưa áp dụng vào DB demo; PostgreSQL 16/Docker runtime cho thay đổi này chưa chạy do daemon không hoạt động. Bulk import/School workflow vẫn chưa triển khai. Test migration dùng database con riêng và cần quyền CREATE DATABASE trên môi trường test.

## Docker, migration và CI (TASK-016)

- Core image multi-stage Python 3.12-slim: builder tạo wheel có `app`, runtime chỉ cài wheel/dependencies và copy migrations. Runtime UID/GID 10001, root filesystem read-only, `/tmp` tmpfs, drop capabilities/no-new-privileges. Một Uvicorn worker vì limiter/idempotency còn process-local; proxy headers tắt đến khi có cấu hình proxy tin cậy. Không tự tăng worker khi chưa có backend limiter/cache dùng chung.
- PostgreSQL 16 dùng named volume `pgdata` theo project, port chỉ bind loopback. Các port cấu hình bằng `POSTGRES_PORT` (5432), `CORE_PORT` (8000), `WEB_PORT` (3000); Web proxy dùng server-only `CORE_API_URL` (Compose: `http://core:8000`) và `WEB_ORIGIN`, còn Core `CORS_ORIGINS` phải khớp exact browser origin. `NEXT_PUBLIC_CORE_API_URL` không được dùng trong Web live proxy hiện tại. `CORE_IMAGE` tùy chọn cho tag test độc lập, mặc định `rag-course-core:local`.
- DB credentials và `DATABASE_URL` cần khớp; URL-encode ký tự đặc biệt trong credential. Các default trong mẫu chỉ dùng local. Thay môi trường không tự đổi credential của volume PostgreSQL đã khởi tạo. Stack này chưa phải cấu hình production HA hoặc phân quyền DB cho cả năm service.
- Kiểm tra cấu hình bằng `docker compose config --quiet` (không xuất nội dung secret). Xem trạng thái bằng `docker compose ps -a`; retry migration sau khi sửa nguyên nhân bằng `docker compose run --rm migrate`. Thay đổi schema luôn tạo revision mới; không sửa migration đã áp dụng.
- `.github/workflows/core-ci.yml` chạy trên mọi PR và push main/feature/fix/codex: lint/format, PostgreSQL 16, upgrade/drift check, OpenAPI snapshot, toàn bộ tests có DB và coverage/JUnit artifact, public coverage 100%, Web build và Compose smoke riêng. Smoke kiểm tra non-root/package/migration/health/Web, dừng DB rồi kiểm tra 503/live và phục hồi. Cleanup chỉ project CI riêng, không prune Docker toàn cục.
- Formatter giữ nguyên migration 0001 đã áp dụng bằng exclusion riêng (baseline cũ không được format); lint vẫn kiểm tra file đó. Không có cấu hình mypy hiện tại nên chưa thêm type-check Python; Next build có kiểm tra TypeScript.

Kiểm tra tương đương CI tại `services/core` với `DATABASE_URL`/`TEST_DATABASE_URL` trỏ đến DB test riêng đã cấu hình: `ruff check app tests migrations`, `ruff format --check app tests migrations`, `alembic upgrade head`, `alembic check`, `pytest -W error --cov=app --cov-branch --cov-report=xml --junitxml=test-results.xml`. Không chạy các integration test trên DB có dữ liệu cần giữ. Reports local không được track.

**Bằng chứng local 2026-10-12:** Docker 29.8.2/Compose 5.5.1 Linux engine, project/volume/cổng/image tag riêng từ môi trường sạch; Core UID 10001, wheel/migrations đúng; live/ready/Web đạt. PostgreSQL 16 chạy toàn bộ 124 test, không warning; coverage app 96%, public 100%. Dừng/khởi động DB giữ schema, ready 503→200 và live vẫn 200. GitHub Actions chưa được chạy từ remote ở bước này. Checklist toàn Core còn chờ Classroom, Social, Notification, Admin và các test tương ứng; không coi TASK-016 là nghiệm thu G2/G3.
