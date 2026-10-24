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

Email onboarding (23/10/2026): Core dùng `WEB_ORIGIN` được cấu hình để gửi link `/staff/invitation#token=...` cho ADMIN_INVITATION, `/reset-password#token=...` cho PASSWORD_RESET. Token được URL-encode trong fragment, không đi trong request URL/Referer; Web đưa vào bộ nhớ rồi xóa khỏi URL. Mở link không tiêu thụ token: người dùng phải gửi mật khẩu mới tới endpoint reset hiện có. Origin chỉ HTTP(S), không credential/path/query/fragment; thiếu origin không gửi email. Login chỉ hiển thị `/activate` với nhãn rõ Học sinh ở tab Học sinh; tab nhân sự dùng email mời. Student vẫn dùng username/mã Admin bàn giao, không chuyển sang onboarding email. Owner review: Core.Identity/Common, Web.Identity và Compose; không thêm endpoint, DTO hoặc thay permission/purpose policy.

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

Access action hiện gồm `read_class_content`, `participate_current_class`, `moderate_class_content`, `manage_class_calendar`, `read_own_history`, `read_document_source`, `use_ai_tutor`, `grade_submitted_work`. Đọc lịch sử cá nhân không cấp quyền xem nội dung lớp mới hoặc mở nguồn bị thu hồi; consumer vẫn phải xác minh chủ tài nguyên/Document grant/Learning assignment. Action sai trả validation error; DB/service không xác minh được trả lỗi hạ tầng và consumer fail closed. Khi từ chối, access-check trả thêm `class_status` nếu lớp tồn tại và cùng trường với user (consumer phân biệt lớp archived → 409 với lớp không thấy/khác trường → 404-che); trường hợp không tìm thấy hoặc khác trường vẫn bỏ `class_status`. Consumer ghi dữ liệu có thể yêu cầu khóa chia sẻ hàng lớp (`FOR SHARE`) trong transaction ghi của mình qua tùy chọn lock của check, để mutation Classroom đang giữ `FOR UPDATE` kịp commit trước khi quyết định quyền — không tự sửa bảng Classroom.

**TASK-015 backend hardening:** replay của cache Classroom vẫn phải kiểm tra Admin hiện hành và school scope của tài nguyên nguồn/đích (kể cả response 204), hoặc course/homeroom/class đã tạo; scope thay đổi hoặc resource không còn hợp lệ trả 404, không phát lại body cũ. Không mở rộng cam kết cache process-local thành idempotency bền vững. Classroom lấy `Mutation/get_mutation` qua Identity public thay vì import nội bộ.

Core HTTP `/api/*` và `/internal/*` có admission queue trước dependency đồng bộ, giữ permit đến khi cleanup session xong. Capacity mỗi process = `max(1, DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW - 1)`; pool mặc định 5+10, timeout 3 giây. Chờ quá `DATABASE_POOL_TIMEOUT_SECONDS` trả 503 envelope chuẩn, no-store, `Retry-After:1`. Health/OpenAPI không bị queue này chặn; auth/permission vẫn chạy trên request được nhận. Đây là giới hạn hạ tầng, không cấp thêm quyền hoặc thay rule nghiệp vụ.

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

Social kiểm tra quyền đọc trước khi tra tài nguyên: ngoài quyền/trường/lớp, parent sai scope hoặc đã soft-delete trả 404; thiếu action ghi trả 403; lớp ARCHIVED vẫn đọc nhưng mọi ghi trả 409. Mọi thao tác ghi Social khóa chia sẻ hàng lớp qua access-check trong cùng transaction với mutation. Cursor không hợp lệ hoặc thuộc parent khác trả 400. Body post/comment 1..10.000 và không toàn khoảng trắng; title 1..200; datetime phải có timezone và `starts_at < ends_at`; validation trả 422. LEARNING-origin PATCH/DELETE trả 400. Mọi response Social có `Cache-Control: no-store`; author chỉ gồm `id,display_name`, không lộ email/username. Admin không được đọc Social; Admin cùng trường chỉ đi nhánh moderation DELETE và ghi audit, khác trường trả 404.

Tạo post/comment ghi outbox và snapshot người nhận trong cùng transaction; lỗi ghi outbox làm rollback mutation. Payload không chứa body. Projection deadline Learning chỉ có helper nội bộ chờ contract TASK-019, dedup bằng `external_ref` và bỏ qua version trùng/cũ; không có HTTP sync endpoint. Calendar CORE dùng hard-delete vì DESIGN chưa yêu cầu giữ lịch sử xóa.

## Notifications — IMPLEMENTED, wire contract được người dùng duyệt 2026-10-22

Owner liên quan: Core.Notification và Web transport/session/controller; cần review khi tạo PR. Người dùng đã duyệt nối đúng ba operation hiện có theo [phạm vi duyệt](../../../../apps/web/docs/CORE_NOTIFICATION_CONTRACT_REVIEW_2026-10-22.md). Quyết định này không mở Classroom/Social/Calendar/Administration hoặc các service khác.

| Method | Endpoint | Request → Response |
|---|---|---|
| GET | `/api/v1/notifications` | Bearer; `cursor?` opaque, `limit?` 1–100 (mặc định 20) → 200 `{items:[{id:UUID,type:string,payload_json:object,read:boolean,created_at:datetime}],unread_count:integer>=0,next_cursor:string|null}` |
| PATCH | `/api/v1/notifications/{id}/read` | Bearer; UUID, không body → 200 `{id:UUID,read:true}` |
| POST | `/api/v1/notifications/read-all` | Bearer; không body → 204 |

Recipient luôn lấy từ actor DB, không nhận `user_id` từ browser. Phiên bị thu hồi/tài khoản không ACTIVE trả 401; mark ID không thuộc mình trả 404. Cursor sai/không thuộc inbox trả 400; limit/UUID sai trả 422. Success/error no-store; error envelope/correlation theo Common. Mark-one idempotent, không đổi read_at đã có; mark-all đánh dấu các row tới watermark trong transaction, notification mới hơn vẫn unread. `unread_count` là toàn inbox tại GET đó, độc lập số item trên trang.

Web map event type thành nội dung hệ thống, không render raw payload/HTML hoặc nhận URL/quyền từ payload; type lạ hiển thị generic. Với type đã biết, Web chỉ lấy UUID hợp lệ (`class_id`, `destination_class_id`, `post_id`, `comment_id`) và tự dựng đường dẫn từ route hiện có theo vai trò. Quyền đọc metadata của Admin không cấp link đọc Social/Calendar. Backend kiểm tra quyền tài nguyên hiện hành khi mở đích; dữ liệu đã xóa hoặc mất quyền phải được hiển thị như nội dung không còn khả dụng. Không thêm endpoint.

Proxy chỉ mở ba path/method này, chỉ chuyển query cursor/limit và vẫn giữ Origin/Bearer/attestation. Read mutation unknown phải đối soát bằng GET mới; không tự replay. Worker `python -m app.modules.notification.worker` chạy cùng Core image/database trong Compose, đợi migration, không mở cổng hay cần JWT/service key. Không thay audience, retry hoặc dedup. Worker bỏ qua bài/bình luận đã soft delete trước khi phát; đối chiếu tác giả từ `social.feed.public.get_visible_post_ref` và `social.comments.public.get_visible_comment_ref`. Public comment ref chỉ trả `{id,post_id,author_id}` cho đúng parent/chưa xóa, dùng transaction caller, không commit hay tự cấp quyền. Owner cần review: Core.Social, Core.Notification và Web session/navigation.

### Notification inbox và event snapshot v2 (TASK-012)

- `NotificationResponse`: `{id:UUID,type,payload_json,read:bool,created_at:UTC datetime}`. `unread_count` tính toàn inbox, không chỉ trang hiện tại. Limit mặc định 20; cursor UUID mã hóa theo Common, tra sequence trong đúng inbox; cursor ngoài inbox trả 400. Sắp theo sequence giao nhận DESC. Bearer/Identity hiện hành bắt buộc; ID không tồn tại hoặc không thuộc recipient trả 404. Tất cả response thành công có `Cache-Control: no-store`; read-all trả 204 không body.
- Read-all khóa transaction theo recipient và lấy watermark sequence, đánh dấu đúng các hàng đến trước ranh giới khóa. Insert mới sau ranh giới vẫn unread. Mark-read lặp giữ timestamp đầu tiên. Không có endpoint tạo notification cho browser hoặc chọn recipient qua request.
- Public enqueue thuộc `common.outbox.record_outbox_event`; caller sở hữu transaction, event UUID có ngay khi enqueue. Producer hiện hành ghi envelope `schema_version=2` với snapshot người nhận. V1 được dành cho event cũ trước khi có audience snapshot; worker chỉ xử lý V2. DB giữ server default V1 để instance ứng dụng cũ trong rolling deployment không phát event thiếu snapshot vào hàng đợi mới. Envelope còn lưu `id,event_type,aggregate_id,aggregate_version?,created_at`; worker bổ sung `attempts,available_at,published_at,last_error_code`. `aggregate_version` lấy từ `payload.version` nếu caller không truyền. Không dùng outbox làm nơi lưu credential delivery.
- Snapshot mới gồm `class_id,school_id,recipient_ids` cùng các ID/phiên bản của event bên dưới. Classroom thêm người vừa mất membership/assignment khi phát thông báo thay đổi. `notification.public.snapshot_audience(session,class_id)` và `classroom.public.get_notification_audience(class_id,*,session=None,homeroom=False)` chỉ trả DTO ID, không cấp quyền tài nguyên; caller không được commit trước snapshot/enqueue. Payload không có body, tên, mã, token hoặc chat/tài liệu. V2 payload được validate theo allowlist, trường lạ làm event retry với `INVALID_EVENT`. Pending V1 từ trước khi worker được triển khai vẫn giữ để kiểm toán nhưng không được gửi lại bằng audience hiện tại.

| Event type | Aggregate / payload đặc thù | Người nhận |
|---|---|---|
| CLASS_ENROLLMENT_CHANGED / CLASS_ENROLLMENT_MODE_CHANGED | class_id; version | Snapshot thành viên/giáo viên và người vừa kết thúc enrollment |
| CLASS_TEACHERS_CHANGED | class_id; version | Snapshot thành viên, giáo viên mới và giáo viên vừa kết thúc assignment |
| CLASS_STATUS_CHANGED | class_id; version, status ACTIVE/ARCHIVED (status nullable cho event legacy) | Snapshot thành viên/giáo viên |
| CLASS_STUDENT_TRANSFERRED | source class_id; destination_class_id, student_id, effective_at UTC, version (nullable legacy) | Student chuyển lớp |
| HOMEROOM_STUDENT_TRANSFERRED | source homeroom ID trong class_id legacy; destination_homeroom_id, student_id, effective_at UTC | Student chuyển lớp hành chính |
| SOCIAL_POST_CREATED | post_id; class_id, author_id | Snapshot thành viên/giáo viên, trừ tác giả, còn quyền đọc lớp khi giao |
| SOCIAL_COMMENT_CREATED | comment_id; class_id, post_id, author_id, post_author_id | Tác giả post, khác tác giả comment, trong snapshot và còn quyền đọc |
| CALENDAR_DEADLINE_CHANGED | calendar event_id; class_id, external_ref, version | Snapshot thành viên/giáo viên còn quyền đọc |
| DOCUMENT_GRANT_CHANGED | grant_id; class_id, document_id, owner_user_id, actor_user_id, grant_revision, is_active, document_version? | Snapshot lớp, kiểm tra lại READ_DOCUMENT_SOURCE khi giao; intake riêng theo TASK-017 |

Worker xác minh school hiện hành qua public Identity/Classroom và bỏ qua post/comment đã xóa. Pending V1 từ 0009/0010 được giữ nhưng không gửi bằng audience hiện hành; `drain_outbox` chỉ chọn schema V2. Hàm chuẩn bị delivery có nhánh tương thích payload legacy, không làm worker nhận V1. Event thiếu scope nguồn hoặc khác trường được giữ để retry; event type ngoài allowlist không bị worker này đánh dấu published. Intake Document có hợp đồng riêng ở cuối tài liệu và không đưa credential/nội dung nguồn vào inbox.


Inbox payload chỉ chứa ID/phiên bản/trạng thái/thời điểm trong allowlist, thêm `event_id,schema_version`; không trả school_id, recipient_ids, post_author_id hoặc external_ref. Homeroom dùng `homeroom_id` trong inbox. Link từ ID không cấp quyền; mọi API tài nguyên vẫn kiểm tra quyền hiện hành.

Consumer dedup theo SHA-256 của recipient + schema version + type + aggregate/version; event không có aggregate version dùng UUID event. Notification bất biến theo từng sự kiện; xử lý out-of-order không ghi đè phiên bản mới và không mất các event khác phiên bản. Worker giữ khóa outbox `SKIP LOCKED`, insert inbox và đánh dấu published cùng transaction. Lỗi delivery sau commit không rollback nghiệp vụ; retry dùng đồng hồ DB và backoff giới hạn 300 giây. Import Administration đi qua Classroom public để sinh các event enrollment hiện có; không phát event mới hoặc đưa SMTP credential delivery vào allowlist.



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

Các route Administration `/api/v1/admin/*` dùng Bearer với role/status hiện hành. Ngoài role ADMIN, Identity public kiểm tra actor ACTIVE, email đã xác minh và school scope trong DB; thiếu scope/khác trường trả 404, Student/Lecturer trả 403, token đã revoke/LOCKED trả 401. Response có `Cache-Control: no-store`. POST user, PATCH status, PUT roles, PATCH data request và confirm import bắt buộc `X-Admin-Reason` thuộc `ADMIN_INTERVENTION`, `POLICY_VIOLATION`, `USER_REQUEST`; thiếu header 422, giá trị lạ 400. Không nhận lý do tự do trong body/header. Audit chỉ lưu code đã kiểm tra và trường cấu trúc, không chép nguyên input.

**Vai trò/trạng thái:** serialize các thay đổi có thể gỡ/khóa Admin bằng advisory transaction lock trước khi khóa user theo UUID. Không gỡ hoặc khóa Admin khi không còn Admin ACTIVE khác, đã verify email và có school scope trong hệ thống (400), kể cả request đồng thời. Staff role yêu cầu email; chuyển sang Student-only cần username/activation hợp lệ, không biến đổi credential âm thầm (409). Mutation role/status thu hồi refresh và session version; ACTIVE không bypass activation. Staff SMTP callback vẫn trước commit theo Identity hiện có: SMTP lỗi rollback user/invitation/audit; DB commit lỗi sau khi gửi có thể làm invitation không dùng được, không coi SMTP là exactly-once.

**Audit:** migration 0012 thêm `AuditEvent.school_id` nullable và index school/time, actor/time, action/time; không tạo bảng audit trùng. Identity/Classroom/Social/Administration ghi scope từ backend. Event legacy chưa có tenant-at-event-time giữ null và không được trả bởi Admin API; không suy scope lịch sử từ actor hiện tại. Cursor phải khớp school và bộ lọc, sắp `occurred_at DESC,id DESC`; sai cursor 400, datetime không timezone hoặc since > until 422. Metadata legacy không qua allowlist được trả `{}`. Audit các mutation và việc đọc audit/data requests, không ghi trùng audit đã do Identity/Classroom public tạo.

**Yêu cầu dữ liệu:** PATCH `{status:IN_REVIEW/COMPLETED/REJECTED,resolution_note,identity_verified?:bool}`. `resolution_note` là code trong `VERIFICATION_IN_PROGRESS`, `POLICY_PENDING`, `OUTSIDE_CORE_SCOPE`, `INSUFFICIENT_VERIFICATION`, `REQUEST_REJECTED`, `DUPLICATE_REQUEST`, không chứa raw chat/token hoặc text tự do. COMPLETED/REJECTED yêu cầu `identity_verified:true` (xác nhận kiểm tra thủ công của Admin, không xác minh tự động); thiếu trả 409. Theo quyết định người dùng 2026-10-18, khi chưa có policy/executor xử lý thật cho ACCESS/EXPORT/CORRECTION/DELETE, yêu cầu COMPLETED trả **trạng thái thực IN_REVIEW**, note `POLICY_PENDING`, audit `DATA_REQUEST_DEFERRED`; không xóa, sửa hay xuất dữ liệu liên service hoặc đọc chat. REJECTED có audit, terminal không được mở lại; retry cùng quyết định không ghi trùng. Audit ghi cờ verification có cấu trúc, không copy reason của chủ request.

### Student import CSV/XLSX

- CSV UTF-8 (có/không BOM) hoặc một worksheet XLSX; header bắt buộc `username`, tùy chọn `display_name,user_id`. Chỉ text, không formula/column lạ/duplicate header. Tối đa 100 dòng dữ liệu, file decoded 2 MB, ZIP XML expanded 10 MB/100 entries; parser có defusedxml và chặn DTD/entity. `user_id` dùng để gán username cho Student legacy cùng trường; không tự mapping School hoặc đổi hash/UUID/trạng thái.
- Preview chuẩn hóa username theo Identity, kiểm tra dòng lỗi/trùng username/user_id, đối soát username unique. Tài khoản đã có chỉ được dùng nếu cùng trường, Student-only, username/display_name khớp; không tự ghi đè hồ sơ. Kết quả `CREATE/EXISTING/ASSIGN_USERNAME`; lỗi chỉ `{row,code}`, không phản chiếu raw input hoặc danh tính ngoài trường. File lỗi trả 422; row/business errors trả 200 `valid:false,preview_id:null`.
- Preview hợp lệ lưu draft trong DB, gắn actor + school, hết hạn kỹ thuật sau 30 phút theo đồng hồ DB. Confirm khóa draft và các user liên quan theo UUID, recheck actor/row fingerprints và roster_version; account/roster đổi hoặc hết hạn trả 409, actor khác/cross-school trả 404. Tất cả dòng là một batch atomic: lỗi một dòng/roster/audit/outbox rollback toàn bộ, draft vẫn có thể retry nếu còn hợp lệ.
- `homeroom_class_id` tùy chọn thêm các Student vào roster qua Classroom public, giữ thành viên có sẵn; AUTO sync/outbox do Classroom sở hữu, không ghi đè MANUAL. Confirm không tự kết thúc roster, không đổi teaching assignment hoặc phục hồi join code. Import phân công/metadata lớp khác dùng API Classroom đã có.
- `preview_id` là khóa chống lặp bền vững. Confirm đầu trả code một lần chỉ cho Student mới tạo, qua `items[{row,outcome,student,code?,expires_at?}]`. Code không vào draft/results/audit/log/cache. Retry/restart cùng preview trả `replayed:true`, cùng user IDs và `code:null`; mất mã dùng API issue-code hiện có. Re-import file mới dùng EXISTING và không tự cấp/reset code. Sau commit xóa staging rows, chỉ giữ IDs/outcome/fingerprint; hạn preview không được xem là policy retention pháp lý.

**Public boundaries:** Identity `admin_actor`, `admin_update_user_roles`, `admin_check_student_import`, `admin_list_data_requests`, `admin_get_data_request`, `admin_resolve_data_request` trả DTO; hỗ trợ `session=` caller sở hữu. Classroom `admin_preview_roster(...,session,lock=False) -> RosterImportSnapshot` và `admin_append_roster(...,expected_roster_version,actor_id,correlation_id,reason_code,session)` không commit. Administration không import model/repository Identity/Classroom hoặc SQL sang service khác.

UserSummaryDTO không chứa roles; status PATCH trả 204, roles PUT là transaction riêng và không phải save atomic status+roles. Audit list hỗ trợ actor_id/action/since/until/cursor/limit. Data-request PATCH dùng resolution_note enum theo schema; yêu cầu COMPLETED có thể trả IN_REVIEW/POLICY_PENDING khi executor/policy chưa có, Web phải giữ trạng thái server. Import preview nhận file bytes base64, trả preview_id/expiry/items/errors. Confirm chỉ tiết lộ activation code lần đầu; replayed=true trả code=null. Không tự tạo resend/revoke/list staff invitation hoặc download/executor dữ liệu cá nhân.

Credential nội bộ hiện dùng header `X-Service-Key` so với `INTERNAL_SERVICE_SECRET`, cấp scope `core:check_access`. Không dùng Bearer JWT của người dùng thay service credential; `user_id` chỉ được tin sau khi xác thực service, và endpoint vẫn phải kiểm tra quyền hiện hành/action.

Python public interface Identity cho consumer Core được đặc tả tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004). Admin mutation bắt buộc actor/correlation ID, trả DTO thay ORM và ghi audit cùng transaction; consumer không import model/repository Identity hoặc ghi audit trùng.

**Offline maintenance TASK-014:** không thêm HTTP route. Coordinator gọi `identity.public.maintenance_identity_report`, `maintenance_assign_school`, `bootstrap_dev_identity` và `classroom.public.maintenance_schools`, `maintenance_user_schools`, `maintenance_provision_schools`, `seed_dev_classroom`; mọi helper dùng explicit `session`, caller commit/rollback, DTO chỉ trường an toàn. School mapping cần manifest + plan_sha256 đã review; thiếu/khác scope hoặc lịch sử Classroom mâu thuẫn bị chặn, chỉ gán scope thiếu, revoke phiên và audit `LEGACY_ASSIGN_SCHOOL`. Metadata allowlist thêm changed_fields `school_id`. Bootstrap dev chỉ được gọi bởi seed coordinator sau kiểm tra database riêng/rỗng và khóa; không dùng cho onboarding ứng dụng. Lệnh/điều kiện và FK pending tại [runbook](../../../../services/core/migrations/README.md).

`UserSummaryDTO` nội bộ có `display_name` nullable, được batch lookup cùng các trường an toàn khác. Khi dùng cho feed/bình luận, Social chỉ chiếu `id` và `display_name` sang author response; email/username đăng nhập không tự động công khai. Admin Student create/issue-code trả cùng DTO này trong response của Admin.

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
- Migration 0006 bổ sung `users.username` unique/lowercase, `school_id`, `activated_at`; email nullable. Không backfill trường/username hoặc tự kích hoạt tài khoản cũ. School đã có ở 0008; `users.school_id` chưa có FK vì mapping legacy và contract provision School trước Identity còn cần owner duyệt. TASK-014 có CLI report/plan/apply theo manifest, không tự suy mapping; xem [runbook](../../../../services/core/migrations/README.md).
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


## Document event intake — TASK-017

`POST /internal/v1/document-events` là internal operation mới, không đổi63 public operations và không mở trong proxy Web. Cần `X-Service-Key` khớp key riêng `DOCUMENT_EVENTS_SERVICE_SECRET` (32+ ký tự), scope cố định `core:document_events`, khác JWT/check_access/proxy key. Credential sai trả403; cấu hình thiếu hoặc trùng key khác trả503. Auth trước JSON parsing, body tối đa64 KiB.

Request/three event types/ID-only envelope theo [Document EVENT_CONTRACT](../document/EVENT_CONTRACT.md); cấm field lạ và nội dung file/quote/email/tên tự do. Intake kiểm tra trường actor/owner/class qua Core public interfaces, không đọc bảng Document. Receipt UUID+payload hash và outbox commit cùng transaction. Cùng UUID/hash trả200 `{event_id,accepted:true}`; cùng UUID khác payload409; malformed422; outage không ack thành công. Delivery kiểm tra lại `READ_DOCUMENT_SOURCE` theo audience hiện hành. Thay đổi có migration mới `0013_document_event_receipts`, không sửa revision trước. Owner Document/TV2/TV4/AI review phần liên quan trong PR.
