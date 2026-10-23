# Core API Contract v1

**Trạng thái:** Identity auth/profile/data requests và Student provisioning/activation/recovery **IMPLEMENTED**; public register **BLOCKED — LEGACY**. Sau ba API Notifications và 38 operation hiện có đã duyệt, người dùng cho phép hoàn thiện Core theo [đề xuất tám GET quản trị](../../../../apps/web/docs/CORE_MISSING_READS_PROPOSAL_2026-10-22.md). Tổng Web allowlist: **63 operation**; OpenAPI có 67 operation tính cả register bị chặn, hai health và một internal. Mutation, schema DB và Business Rules giữ nguyên; kết quả kiểm chứng được ghi riêng.

## Quy ước
Health không dùng prefix `/api/v1`: `GET /health/live` → 200 `{status:"live"}`; `GET /health/ready` → 200 `{status:"ready",db:"connected"}` khi DB/schema Core dùng được, hoặc 503 `SERVICE_UNAVAILABLE`. Giá trị live thay `ok` của skeleton theo TASK-016. Health schemas được sinh trong OpenAPI.

- Public `/api/v1`, HTTP/JSON, Bearer access JWT; refresh/logout qua HttpOnly Secure cookie + CSRF/Origin protection.
- UUID cho ID; ISO-8601 UTC cho thời gian. List: `?limit=20&cursor=<opaque>`, limit 1..100; `{"items":[],"next_cursor":null}`.
- `200` đọc/cập nhật, `201` tạo, `204` xóa; lỗi `400 BAD_REQUEST`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`.
- Error: `{"error":{"code":"FORBIDDEN","message":"Không có quyền","correlation_id":"uuid"}}`. Che tài nguyên ngoài quyền bằng 404.
- Mọi response có `X-Correlation-ID`; giữ UUID hợp lệ từ request hoặc sinh UUID mới. Lỗi không dự kiến trả `500 INTERNAL_ERROR`, dependency xác thực/DB không khả dụng có thể trả `503 SERVICE_UNAVAILABLE`; không phản chiếu nội dung nhạy cảm trong lỗi. Cập nhật runtime 23/10: correlation dùng ASGI trực tiếp; dependency tạo callable/service và pagination không chạy SQL trên event loop. Wire contract/quyền không đổi, tra hồi quy tại báo cáo Core runtime follow-up.
- Không có idempotency chung cho mọi router. Identity/Classroom hỗ trợ cache process-local cho các operation được triển khai, không bền vững qua restart/nhiều worker. Student create/issue-code/activate từ chối `Idempotency-Key` trước mutation; import confirm dùng receipt bền vững theo preview_id và không tiết lộ lại code khi replay. Web không gửi generic Idempotency-Key hoặc tự replay mutation. Hoạt động mới trong lớp cần quyền hiện hành; đọc lịch sử cá nhân kiểm tra riêng theo action và quyền nguồn hiện hành.

## Auth / User — IMPLEMENTED

> Student không tự đăng ký; Admin cấp tài khoản/mã theo mục Student bên dưới. Email login/verify/forgot/reset chỉ dành cho tài khoản có role Lecturer/Admin; tài khoản có cả role staff và Student dùng credential staff, không đi qua Student activation.
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /auth/register | Deprecated; {email,password} → 403 FORBIDDEN; không gọi DB/SMTP hoặc tạo Student |
| POST | /auth/verify-email | Public; token email của staff → 200 {verified:true} |
| POST | /auth/login | Public; đúng một trong {username,password} Student hoặc {email,password} staff → 200 access + refresh cookie; cả hai/không có identifier trả 422 |
| POST | /auth/activate | Public; {username,activation_code,new_password} → 204; chỉ Student pending, không cần SMTP |
| POST | /auth/refresh | Refresh cookie + CSRF → 200 access + rotated cookie |
| POST | /auth/logout | Refresh cookie + CSRF → 204, revoke/clear |
| POST | /auth/logout-all | Bearer → 204 |
| POST | /auth/password/forgot | Public; {email} → 200 generic; không phát token email cho Student |
| POST | /auth/password/reset | Public; {token,new_password} → 204 |
| GET/PATCH | /users/me | Bearer; GET profile, PATCH {display_name?} |
| GET/POST | /users/me/data-requests | Bearer; GET list, POST {type:ACCESS/EXPORT/CORRECTION/DELETE,reason?} → 201 PENDING |

Refresh cookie tên `refresh_token`, path `/api/v1/auth`, HttpOnly/Secure/SameSite=Lax. Refresh/logout kiểm tra Origin hoặc fallback Referer khi Origin vắng mặt, đối chiếu `CORS_ORIGINS`; sai/thiếu origin trả 403. Login cũng chặn Origin sai nếu được gửi. Responses auth/profile dùng `Cache-Control: no-store`; logout/logout-all/reset xóa cookie cùng path.

Profile trả `{id,email,username,school_id,display_name,roles,status}`, không chứa hash; email/username/school_id có thể null cho tài khoản chưa chuyển đổi. PATCH không gửi `display_name` giữ nguyên, `null` xóa tên. Forgot-password trả `{message}` generic, không lộ token hoặc việc tài khoản tồn tại; thiếu cấu hình SMTP trả 503. Register bị chặn 403, không phụ thuộc SMTP.

Password/reset nhận PASSWORD_RESET/ADMIN_INVITATION cho staff hoặc STUDENT_PASSWORD_RESET do Admin đã xác minh cấp cho Student ACTIVE. Lời mời staff chỉ đặt mật khẩu/xác minh tài khoản PENDING, không mở LOCKED. Activation token chỉ dùng tại /auth/activate, reset token không thay activation; token email cũ không được dùng cho Student. Token một lần, đúng purpose/hạn; reset không trả token qua response.

Data requests POST dùng `type` chuẩn (alias `request_type` được chấp nhận), reason tùy chọn tối đa 10000 ký tự; trả `{id,user_id,type,reason,status:PENDING,resolution_note:null,created_at,updated_at}`. GET trả `{items,next_cursor}` theo limit/cursor và UUID tăng dần, chỉ của người dùng xác thực. Không nhận user_id/status/resolution_note do người dùng đặt. DELETE là loại yêu cầu xử lý thủ công, không tự xóa dữ liệu hoặc khóa tài khoản.

Rate limit mặc định: login 5 lần sai/60 giây theo IP và identifier chuẩn hóa (namespace username/email); forgot 3 request/3600 giây theo IP; activate/verify/reset 5/60 giây theo IP. 429 có `Retry-After`. Register bị chặn mọi lần gọi, không replay response 201 từ cache.

### Danh tính client qua Web proxy (security fix 2026-10-22)

Web live chạy bằng Node entry point `apps/web/server.mjs` (`npm run dev`/`npm start`). Listener lấy địa chỉ từ TCP socket, xóa header IP/context do caller cung cấp và tạo header server-to-server `X-Lumi-Client-Context`. Next route handler xác minh rồi chỉ chuyển context hợp lệ tới Core. Không sử dụng `X-Forwarded-For`/`X-Real-IP` do browser gửi.

Context là `<base64url(JSON UTF-8)>.<HMAC-SHA256-hex của phần base64url>`, JSON có `{v:1,ip,at,method,path}`; `at` là epoch giây, độ lệch tối đa 30 giây; method và path phải khớp request đích. IPv4-mapped IPv6 được chuẩn hóa thành IPv4 cho rate-limit bucket. Header tối đa 1024 ký tự, không được log/echo về browser. Key `CORE_PROXY_SECRET` là secret server-only riêng, ít nhất 32 ký tự, cùng giá trị ở Core và Web; không dùng key JWT hoặc `X-Service-Key` cho mục đích này.

Core nhận context sai/chữ ký sai/hết hạn/sai method hoặc path trả 403; có context nhưng chưa cấu hình key trả 503. Request trực tiếp Core không có context tiếp tục dùng địa chỉ peer và vẫn áp dụng rate limit theo identifier. Context chỉ xác định bucket client, không xác thực user, không cấp role/school/class permission. Origin/cookie/Bearer và quyền hiện hành vẫn được kiểm tra độc lập.

Topology hiện tại kết thúc kết nối browser tại Node listener. Nếu thêm reverse proxy/load balancer phía trước, phải thiết kế trust tại ingress tương ứng trước khi sử dụng IP chuyển tiếp; không bật tin header tùy ý. Uvicorn vẫn tắt proxy headers. Thay đổi shared config/Identity transport này cần owner Core.Identity/Common và Web review khi tạo PR.

Identity idempotency hiện dùng RAM một process, TTL 24 giờ; không bền vững qua restart/nhiều worker. Scope anonymous dùng identifier chuẩn hóa/token hash, refresh/Bearer dùng user. Token cookie được tính vào payload; cookie đã đổi với cùng key có thể trả 409. Cache credential responses phải kiểm tra quyền/phiên hiện hành, trả 401 khi stale; dùng key mới cho lần xác thực mới. Chi tiết cấu hình và giới hạn tại [Core README](../../../../services/core/README.md#identity-http-api-task-003).

## Course / Class / Membership — IMPLEMENTED, wire contract được duyệt 2026-10-22
**DECIDED:** Chỉ Admin tạo lớp môn học, roster, phân công giáo viên, ghi danh AUTO/MANUAL, archive/restore. Không có join code, join-request, giáo viên tự tạo lớp, teacher invitation/ownership transfer, Student tự leave trong MVP.

17 operation hiện có được duyệt; prefix `/api/v1`. Request/response/constraints đầy đủ tại [API matrix](../../../../apps/web/docs/CORE_API_MATRIX_2026-10-22.md) và [snapshot public OpenAPI](../../../../apps/web/tests/contracts/core-approved-openapi.json), đối chiếu router/schema Core hiện hành.

| Method | Endpoint | Request → Response |
|---|---|---|
| GET | /classes | cursor/limit → 200 Page[ClassResponse] trong phạm vi hiện hành |
| GET | /classes/{class_id} | → 200 ClassResponse |
| GET | /classes/{class_id}/members | → 200 MembershipResponse[] |
| POST | /admin/courses | {code,name} → 201 CourseResponse |
| POST | /admin/homeroom-classes | {name,academic_year,grade_level} → 201 HomeroomResponse |
| PUT | /admin/homeroom-classes/{id}/roster | {student_ids} → 200 RosterResponse |
| POST | /admin/homeroom-classes/{id}/students/{student_id}/transfer | {destination_homeroom_id} → 200 RosterResponse của lớp đích |
| POST | /admin/classes | ClassCreateRequest → 201 ClassResponse |
| PUT | /admin/classes/{id}/teaching-assignments | {primary_lecturer_id,assisting_lecturer_ids?} → 200 TeachingAssignmentResponse[] |
| POST | /admin/classes/{id}/enrollment/preview | không body → 200 EnrollmentPreviewResponse |
| POST | /admin/classes/{id}/enrollment/sync | không body → 200 ClassResponse |
| PATCH | /admin/classes/{id}/enrollment-mode | {mode,expected_class_version?,expected_roster_version?} → 200 ClassResponse |
| POST | /admin/classes/{id}/members | {student_id} → 201 MembershipResponse |
| DELETE | /admin/classes/{id}/members/{student_id} | → 204 |
| POST | /admin/classes/{id}/members/{student_id}/transfer | {destination_class_id} → 200 MembershipResponse của lớp đích |
| POST | /admin/classes/{id}/archive | → 200 ClassResponse |
| POST | /admin/classes/{id}/restore | → 200 ClassResponse |

Các mutation quản trị yêu cầu reason enum như API matrix; không suy ra từ OpenAPI vì một số Classroom headers được kiểm tra thủ công. MANUAL→AUTO dùng class_version/roster_version của preview thực tế; không có preview token/revision do Web tự đặt. Đồng bộ AUTO áp dụng roster hiện hành tại thời điểm xác nhận; endpoint sync không nhận expected versions nên không bảo đảm giữ nguyên tác động của preview cũ. Không thêm idempotency bền vững hoặc contract cho service khác. Endpoint join-request/owner transfer cũ **SUPERSEDED/OUT OF MVP**; giữ lịch sử source/migration.

## Metadata quản trị — tám GET bổ sung được duyệt khi hoàn thiện Core

Tất cả có prefix `/api/v1`, Bearer actor ACTIVE/ADMIN và trường hiện hành từ DB; không nhận school_id tùy ý. Không có quyền Admin đọc Social/chat từ metadata này. Không yêu cầu reason, không ghi audit/outbox hoặc mutation ngầm; success/error no-store và correlation ID theo Common.

| GET | Response 200 | Owner |
|---|---|---|
| /admin/courses | Page[CourseResponse `{id,school_id,code,name}`] | Classroom |
| /admin/academic-years | Page[AcademicYearResponse `{id,school_id,label}`] | Classroom |
| /admin/academic-years/{year_id}/semesters | Page[SemesterResponse `{id,academic_year_id,name}`] | Classroom |
| /admin/homeroom-classes | Page[HomeroomResponse hiện có] | Classroom |
| /admin/homeroom-classes/{homeroom_id}/roster | RosterResponse hiện có | Classroom |
| /admin/classes/{class_id}/teaching-assignments | TeachingAssignmentResponse[] còn hiệu lực (`ended_at=null`) | Classroom |
| /admin/users | Page[AdminUserReadDTO] | Identity public interface / Administration router |
| /admin/users/{id} | AdminUserReadDTO | Identity public interface / Administration router |

AdminUserReadDTO chỉ có `{id,email,username,school_id,display_name,status,roles}`; nullable giữ nguyên. roles lấy toàn bộ assignment thực từ DB, có thể rỗng ở dữ liệu legacy để Admin sửa; không dùng DTO này cấp phiên. Không trả password/hash/token/session_version hoặc private chat. Administration chỉ gọi `identity.public.admin_list_users` / `admin_get_user`, không import repository/model chéo module. Mutation UserSummaryDTO vẫn không có roles.

Page theo UUID tăng dần, cursor canonical opaque 22 ký tự, limit1..100 mặc định20, không có search/filter mới. Sai định dạng cursor400, limit/UUID sai422. Classroom cursor không thuộc collection/trường/năm trả400; account cursor không tồn tại/ngoài trường trả404 theo account scope hiện có. Resource/parent ngoài trường404, actor khác role403, phiên thu hồi/không ACTIVE401. Roster đọc khóa parent FOR SHARE để student_ids và roster_version nhất quán với writer FOR UPDATE; archived vẫn cho Admin đọc metadata. Không đổi migration.

Owner cần review PR: Core.Identity, Classroom, Administration, Common contract/security và Web transport/controller. Không có thao tác gửi thông báo hay tạo PR tự động trong thay đổi này.

## Feed / Comments / Calendar — IMPLEMENTED, wire contract được duyệt 2026-10-22
| Method | Endpoint | Quyền / Body |
|---|---|---|
| GET/POST | /classes/{class_id}/posts | ACTIVE member; POST {body} |
| PATCH | /classes/{class_id}/posts/{post_id} | Author còn quyền hiện hành |
| DELETE | /classes/{class_id}/posts/{post_id} | Author còn quyền hoặc giáo viên được phân công moderation; Admin can thiệp có audit |
| GET/POST | /classes/{class_id}/posts/{post_id}/comments | ACTIVE member; POST {body} |
| PATCH | /classes/{class_id}/posts/{post_id}/comments/{id} | Author còn quyền hiện hành |
| DELETE | /classes/{class_id}/posts/{post_id}/comments/{id} | Author còn quyền hoặc giáo viên được phân công moderation; Admin can thiệp có audit |
| GET | /classes/{class_id}/calendar | ACTIVE member; ?from=ISO&to=ISO |
| POST | /classes/{class_id}/calendar | Giáo viên PRIMARY/ASSISTING hiện hành; {title,starts_at,ends_at} |
| PATCH/DELETE | /classes/{class_id}/calendar/{id} | Giáo viên PRIMARY/ASSISTING hiện hành; chỉ CORE-origin event |

12 operation Social/Calendar hiện có được người dùng duyệt. PostResponse/CommentResponse có author `{id,display_name}`, không có email/role. CalendarEventResponse có title, description nullable, starts_at/ends_at có timezone, origin và external_ref; PATCH cho phép clear description bằng null. Parent class/post/comment phải cùng scope, dữ liệu đã soft delete không lộ qua list/detail; archived từ chối hoạt động ghi chung. Deadline LEARNING chỉ đồng bộ qua integration, không chỉnh tại Core. Quyền Admin đọc metadata lớp không cấp quyền đọc Social. Payload/status chi tiết tại API matrix và public snapshot ở trên.

## Notifications — IMPLEMENTED, wire contract được người dùng duyệt 2026-10-22

Owner liên quan: Core.Notification và Web transport/session/controller; cần review khi tạo PR. Người dùng đã duyệt nối đúng ba operation hiện có theo [phạm vi duyệt](../../../../apps/web/docs/CORE_NOTIFICATION_CONTRACT_REVIEW_2026-10-22.md). Quyết định này không mở Classroom/Social/Calendar/Administration hoặc các service khác.

| Method | Endpoint | Request → Response |
|---|---|---|
| GET | `/api/v1/notifications` | Bearer; `cursor?` opaque, `limit?` 1–100 (mặc định 20) → 200 `{items:[{id:UUID,type:string,payload_json:object,read:boolean,created_at:datetime}],unread_count:integer>=0,next_cursor:string|null}` |
| PATCH | `/api/v1/notifications/{id}/read` | Bearer; UUID, không body → 200 `{id:UUID,read:true}` |
| POST | `/api/v1/notifications/read-all` | Bearer; không body → 204 |

Recipient luôn lấy từ actor DB, không nhận `user_id` từ browser. Phiên bị thu hồi/tài khoản không ACTIVE trả 401; mark ID không thuộc mình trả 404. Cursor sai/không thuộc inbox trả 400; limit/UUID sai trả 422. Success/error no-store; error envelope/correlation theo Common. Mark-one idempotent, không đổi read_at đã có; mark-all đánh dấu các row tới watermark trong transaction, notification mới hơn vẫn unread. `unread_count` là toàn inbox tại GET đó, độc lập số item trên trang.

Web chỉ map event type thành nội dung hệ thống, không render raw payload/HTML, không nhận đường dẫn/quyền từ payload; type lạ hiển thị generic. Các workspace đích chưa nối nên không tự tạo deep link. Proxy chỉ mở ba path/method này, chỉ chuyển query cursor/limit và vẫn giữ Origin/Bearer/attestation. Read mutation unknown phải đối soát bằng GET mới; không tự replay. Worker `python -m app.modules.notification.worker` chạy cùng Core image/database trong Compose, đợi migration, không mở cổng hay cần JWT/service key. Không thay audience, retry hoặc dedup.

## Administration — IMPLEMENTED, 9 public operation được duyệt 2026-10-22; Internal chỉ service-to-service
| Method | Endpoint | Quyền / Body |
|---|---|---|
| POST | /admin/users | Admin {email,roles:ADMIN/LECTURER} → 201, gửi link đặt mật khẩu; Student dùng provisioning riêng |
| PATCH | /admin/users/{id}/status | Admin {status:ACTIVE/LOCKED} + audit |
| PUT | /admin/users/{id}/roles | Admin {roles:[...]} + audit; không xóa Admin cuối |
| GET | /admin/audit-events | Admin; paginated redacted audit |
| GET/PATCH | /admin/data-requests/{id} | Admin; PATCH {status:IN_REVIEW/COMPLETED/REJECTED,resolution_note} |
| GET | /admin/data-requests | Admin; paginated |
| POST | /admin/students/imports/preview | Admin; {format:CSV/XLSX,content_base64,homeroom_class_id?} → 200 ImportPreviewResponse |
| POST | /admin/students/imports/confirm | Admin + X-Admin-Reason; {preview_id} → 200 ImportConfirmResponse |
| GET | /internal/v1/classes/{class_id}/access?user_id=&action= | Authenticated service scope core:check_access → {allowed,class_id,user_id,action} |

Admin can thiệp lớp cần `X-Admin-Reason` và audit; không tự có quyền xem chat riêng tư. Common AuditMetadata hiện chỉ hỗ trợ allowlist/reason_code; cách lưu lý do tự do cần được thiết kế/redact ở TASK-013, không tự ghi nguyên header. Internal API không chấp nhận browser trực tiếp; fail closed.

UserSummaryDTO không chứa roles; status PATCH trả 204, roles PUT là transaction riêng và không phải save atomic status+roles. Audit list hỗ trợ actor_id/action/since/until/cursor/limit. Data-request PATCH dùng resolution_note enum theo schema; yêu cầu COMPLETED có thể trả IN_REVIEW/POLICY_PENDING khi executor/policy chưa có, Web phải giữ trạng thái server. Import preview nhận file bytes base64, trả preview_id/expiry/items/errors. Confirm chỉ tiết lộ activation code lần đầu; replayed=true trả code=null. Không tự tạo resend/revoke/list staff invitation hoặc download/executor dữ liệu cá nhân.

Credential nội bộ hiện dùng header `X-Service-Key` so với `INTERNAL_SERVICE_SECRET`, cấp scope `core:check_access`. Không dùng Bearer JWT của người dùng thay service credential; `user_id` chỉ được tin sau khi xác thực service, và endpoint vẫn phải kiểm tra quyền hiện hành/action.

Python public interface Identity cho consumer Core được đặc tả tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004). Admin mutation bắt buộc actor/correlation ID, trả DTO thay ORM và ghi audit cùng transaction; consumer không import model/repository Identity hoặc ghi audit trùng.

## Validation / Contract tests
- **IMPLEMENTED Identity:** email lowercase; username trim/lowercase, 1..200 ký tự, không whitespace hoặc @, unique toàn hệ thống; mật khẩu mới 12..128 ký tự. Student không cần email. Không expose hash; chỉ Admin nhận mã một lần trong response Student create/issue-code có `Cache-Control: no-store`. Post/comment 1..10000, title/name 1..200, starts_at < ends_at là contract các module tương ứng.
- Test: unauthorized/cross-school/cross-class, LOCKED/ENDED/ARCHIVED, Admin-only mutations, AUTO/MANUAL concurrency, activation replay, JWT replay/revoke, CSRF, post/comment delete, notification dedup, calendar LEARNING read-only, Admin audit, internal auth.
- FastAPI sinh OpenAPI cho router hiện có; Web snapshot/test đối chiếu chính xác 63 public operation đã duyệt, loại health/internal/register. Web có decoder/proxy/session tests và runner HTTP/PostgreSQL production cho 46 operation Classroom/Social/Calendar/Administration + Notifications/Identity. Bằng chứng trước thay đổi nằm tại [báo cáo tích hợp](../../../../apps/web/docs/CORE_APPROVED_INTEGRATION_2026-10-22.md); không thay thế test Core hoặc browser acceptance.

## Ghi chú tương thích — phạm vi Lumi THCS/THPT chính khóa
Đối tượng: học sinh khối 6–12 trong lớp chính khóa. Giữ các enum/API role kỹ thuật `ADMIN`, `LECTURER`, `STUDENT` để tương thích code; UI hiển thị Quản trị viên/Giáo viên/Học sinh. Những route hiện được mô tả ở trên là **contract hiện hành hoặc dự kiến**, không phải toàn bộ đã triển khai.

- `POST /auth/register` **BLOCKED — LEGACY**: giữ route deprecated nhưng trả 403 cho request hợp lệ; không tạo Student. Logic đăng ký nội bộ cũ được giữ để tương thích/kiểm thử tài khoản lịch sử, không export qua Identity public interface.
- Lecturer `POST /classes` là **SUPERSEDED DRAFT**, không được triển khai theo quyền Lecturer; chỉ Admin tạo lớp môn học.
- `/classes/join-requests*` là **SUPERSEDED DRAFT/OUT OF MVP**; không dùng mã lớp hoặc teacher approval.
- `DELETE /classes/{class_id}/members/me` là **SUPERSEDED DRAFT/OUT OF MVP**; Student không tự rời lớp.
- Các API quản trị, dữ liệu cá nhân, điểm, quyền và audit tiếp tục phải tuân thủ Business Rules; không tự thêm role Phụ huynh/Admin theo trường.


## Ghi chú mục tiêu cũ và phạm vi chưa duyệt
- Import preview/confirm đã triển khai và được duyệt như mục Administration; không ghi mã kích hoạt vào log.
- Nhóm homeroom/roster/classes/teaching-assignments hiện có đã được duyệt theo mục trên; roster dùng PUT, không có contract POST tương đương được duyệt. API đọc bổ sung cần thiết cho workspace quản trị vẫn chưa nằm trong quyết định này.
- `POST /admin/classes/{id}/enrollment/preview`, `POST /admin/classes/{id}/enrollment/sync`, `PATCH /admin/classes/{id}/enrollment-mode`, `POST /admin/classes/{id}/members`, `DELETE /admin/classes/{id}/members/{student_id}`: chỉ Admin, đồng bộ AUTO/MANUAL, audit, giữ lịch sử; MANUAL→AUTO phải preview/confirm.
- `POST /admin/classes/{id}/archive`, `POST /admin/classes/{id}/restore`: chỉ Admin.
- Các route `/classes/join-requests*`, `/classes/{id}/co-lecturers/invitations*`, `/classes/{id}/ownership-transfer`, Lecturer `POST /classes`, Lecturer membership mutation, Owner archive/restore, public Student `/auth/register` là **legacy/ngoài phạm vi MVP**; không coi chúng là API được phép phát hành. Không xóa source/migration chỉ vì đổi contract.
- Learning phải có quyền nháp → duyệt/công bố assessment, chấm được phân công → đề xuất/phê duyệt sửa điểm, attempt transfer cutoff; các service dùng access check theo hành động, không dựa độc nhất membership ACTIVE.
- Kiểm thử: cross-school/cross-class, role Admin-only, Student no self-register/join, AUTO/MANUAL, idempotent bulk import, activation token expiry/replay, historical read vs source revoke, transfer attempt, grade approval/audit.

## Phạm vi chuyển đổi Identity hiện tại
- Migration 0005 bổ sung `CORRECTION` cho yêu cầu xử lý thủ công; không tự sửa dữ liệu.
- Migration 0006 bổ sung `users.username` unique/lowercase, `school_id`, `activated_at`; email nullable. Không backfill trường/username hoặc tự kích hoạt tài khoản cũ. `school_id` chưa có FK vì entity School thuộc Classroom chưa được triển khai.
- Identity lookup lấy school_id từ DB hiện hành, không từ JWT/body. Admin tạo tài khoản qua public helper kế thừa school_id của actor. Các Admin helpers yêu cầu school scope; mutation status che tài khoản ngoài trường hoặc thiếu scope bằng 404, kể cả hai phía đều null. Trước khi sử dụng Admin helpers phải có mapping trường được duyệt cho tài khoản cũ; migration không tự gán trường.
- Migration 0007 bổ sung purpose STUDENT_ACTIVATION/STUDENT_PASSWORD_RESET, giữ token lịch sử. Student onboarding/recovery đã triển khai theo quyết định kỹ thuật được người dùng duyệt 2026-10-14; bulk import hiện có được duyệt 2026-10-22. Tài khoản Student cũ giữ ID/password/dữ liệu nhưng cần Admin gán username qua public interface trước khi đăng nhập lại; không fallback email cho Student.

## Student provisioning / activation / recovery — IMPLEMENTED
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /admin/students | Admin cùng school scope; {username,display_name?} → 201 {student:UserSummaryDTO,purpose:ACTIVATION,code,expires_at} |
| POST | /admin/students/{user_id}/activation-codes | Admin cùng trường; {} cho pending → mã ACTIVATION mới; {identity_verified:true} cho ACTIVE → mã PASSWORD_RESET sau xác minh thủ công |
| POST | /auth/activate | Public; {username,activation_code,new_password} → 204 ACTIVE, thu hồi phiên; sai tên/purpose/hạn/replay/LOCKED trả 400 |

- Mã kích hoạt mặc định 24 giờ (`STUDENT_ACTIVATION_EXPIRE_HOURS`); mã reset dùng `PASSWORD_RESET_EXPIRE_MINUTES` (60 phút). Lưu SHA-256; cấp lại vô hiệu hóa mã trước. Không SMTP/mật khẩu mặc định dùng chung. Mã reset sử dụng `/auth/password/reset`, không tự mở tài khoản LOCKED.
- Admin nhận code trực tiếp một lần, chịu trách nhiệm phân phối an toàn; không có API đọc lại code và không cache code response. Request mất phản hồi: dùng route issue-code để cấp mã mới; tạo lại cùng username trả 409. Ba thao tác create/issue-code/activate từ chối `Idempotency-Key` bằng 400.
- Admin phải xác minh danh tính trước khi gửi `identity_verified:true` cho recovery; Backend kiểm tra role/trạng thái/trường, ghi audit cấp mã và reset; flag là xác nhận thao tác của Admin, không phải xác minh tự động. Cấp mã reset thu hồi các phiên đang mở; hoàn tất reset tiếp tục thu hồi phiên.
- `identity.public.admin_assign_student_username` chuyển Student legacy trong cùng trường: username chưa có mới được gán; giữ UUID/email/hash/status. ACTIVE/LOCKED legacy phải đã verify email, ghi activated_at; LOCKED không tự mở. Pending vẫn phải nhận mã và activate. Thu hồi phiên/token cũ, audit cùng transaction. Consumer Administration dùng public interface; import hiện có hỗ trợ ASSIGN_USERNAME qua preview/confirm, chưa có endpoint chuyển đổi đơn lẻ được duyệt.
