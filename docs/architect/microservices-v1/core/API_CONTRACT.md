# Core API Contract v1

**Trạng thái:** Identity, Student provisioning/activation/recovery, Classroom Admin/access, Social, Notification và Administration backend **IMPLEMENTED**; public register **BLOCKED — LEGACY**. Data-request fulfillment/retention chưa có policy/executor nên giữ IN_REVIEW khi thiếu điều kiện, theo quyết định người dùng 2026-10-18. Business Rules là nguồn quyết định nghiệp vụ.

## Quy ước
Health không dùng prefix `/api/v1`: `GET /health/live` → 200 `{status:"live"}`; `GET /health/ready` → 200 `{status:"ready",db:"connected"}` khi DB/schema Core dùng được, hoặc 503 `SERVICE_UNAVAILABLE`. Giá trị live thay `ok` của skeleton theo TASK-016. Health schemas được sinh trong OpenAPI.

- Public `/api/v1`, HTTP/JSON, Bearer access JWT; refresh/logout qua HttpOnly Secure cookie + CSRF/Origin protection.
- UUID cho ID; ISO-8601 UTC cho thời gian. List: `?limit=20&cursor=<opaque>`, limit 1..100; `{"items":[],"next_cursor":null}`.
- `200` đọc/cập nhật, `201` tạo, `204` xóa; lỗi `400 BAD_REQUEST`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`.
- Error: `{"error":{"code":"FORBIDDEN","message":"Không có quyền","correlation_id":"uuid"}}`. Che tài nguyên ngoài quyền bằng 404.
- Mọi response có `X-Correlation-ID`; giữ UUID hợp lệ từ request hoặc sinh UUID mới. Lỗi không dự kiến trả `500 INTERNAL_ERROR`, dependency xác thực/DB không khả dụng có thể trả `503 SERVICE_UNAVAILABLE`; không phản chiếu nội dung nhạy cảm trong lỗi.
- Mutations hỗ trợ `Idempotency-Key` UUID (scope user+endpoint, giữ 24h); cùng key khác payload trả 409. Ngoại lệ: Student create/issue-code/activate không cache mã hoặc kết quả sử dụng mã; gửi header này trả 400 trước mutation. Hoạt động mới trong lớp cần membership hiện hành; đọc lịch sử cá nhân kiểm tra quyền riêng theo action và quyền nguồn hiện hành.

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

Profile trả `{id,email,username,school_id,display_name,roles,status}`, không chứa hash; email/username/school_id có thể null cho tài khoản chưa chuyển đổi. PATCH không gửi `display_name` giữ nguyên, `null` xóa tên. Forgot-password luôn trả `{message}` generic, không lộ token hoặc việc tài khoản tồn tại; SMTP chưa cấu hình/lỗi giữ delivery pending để retry. Register bị chặn 403, không phụ thuộc SMTP.

Password/reset nhận PASSWORD_RESET/ADMIN_INVITATION cho staff hoặc STUDENT_PASSWORD_RESET do Admin đã xác minh cấp cho Student ACTIVE. Lời mời staff chỉ đặt mật khẩu/xác minh tài khoản PENDING, không mở LOCKED. Activation token chỉ dùng tại /auth/activate, reset token không thay activation; token email cũ không được dùng cho Student. Token một lần, đúng purpose/hạn; reset không trả token qua response. Forgot-password giữ body generic dù SMTP đang retry; resend khi delivery còn PENDING không đổi token.

Data requests POST dùng `type` chuẩn (alias `request_type` được chấp nhận), reason tùy chọn tối đa 10000 ký tự; trả `{id,user_id,type,reason,status:PENDING,resolution_note:null,created_at,updated_at}`. GET trả `{items,next_cursor}` theo limit/cursor và UUID tăng dần, chỉ của người dùng xác thực. Không nhận user_id/status/resolution_note do người dùng đặt. DELETE là loại yêu cầu xử lý thủ công, không tự xóa dữ liệu hoặc khóa tài khoản.

Rate limit mặc định: login 5 lần sai/60 giây theo IP và identifier chuẩn hóa (namespace username/email); forgot 3 request/3600 giây theo IP; activate/verify/reset 5/60 giây theo IP. 429 có `Retry-After`. Register bị chặn mọi lần gọi, không replay response 201 từ cache.

Credential delivery cho PASSWORD_RESET và ADMIN_INVITATION có hàng đợi bền vững riêng trong Identity, không dùng Notification outbox. DB chỉ lưu token hash và trạng thái/attempt/next-attempt; raw token không được lưu hoặc log. Mã được tái tạo trong memory bằng HMAC domain-separated từ `SECRET_KEY`, token row ID, user, purpose và expiry. Forgot-password trả cùng body generic dù SMTP thiếu/lỗi; khi reset delivery còn pending, request lại dùng cùng token và không bỏ qua lịch retry. SMTP failure không rollback token; invitation giữ `PENDING_VERIFICATION` và response Admin trả UserSummaryDTO cùng `X-Token-Delivery-Status: PENDING`. Worker retry cùng mã mỗi 15 phút đến hết hạn; secret-key rotation chuyển delivery thành `NEEDS_REISSUE`, không tự tạo mã khác. Admin reissue là thao tác riêng, có audit và vô hiệu mã cũ. Legacy EMAIL_VERIFICATION chỉ còn trong internal helper, không phải public self-registration flow.

Identity idempotency hiện dùng RAM một process, TTL 24 giờ; không bền vững qua restart/nhiều worker. Scope anonymous dùng identifier chuẩn hóa/token hash, refresh/Bearer dùng user. Token cookie được tính vào payload; cookie đã đổi với cùng key có thể trả 409. Cache credential responses phải kiểm tra quyền/phiên hiện hành, trả 401 khi stale; dùng key mới cho lần xác thực mới. Chi tiết cấu hình và giới hạn tại [Core README](../../../../services/core/README.md#identity-http-api-task-003).

## Course / Class / Membership — IMPLEMENTED trong Core (PR #6 sau chỉnh sửa)
Chỉ Admin cùng trường tạo môn/lớp hành chính/lớp môn học, phân công giáo viên, ghi danh AUTO/MANUAL, chuyển lớp và archive/restore. Trường của lớp lấy từ actor hiện hành trong Identity DB; thiếu trường hoặc khác trường bị che bằng 404. Không có join code, join request, Lecturer-created class, teacher invitation/ownership transfer hay Student self-leave.

| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /admin/courses | Admin; {code,name} → 201 course trong trường hiện hành |
| GET | /admin/catalog | Admin cùng trường; `{courses,academic_years,semesters,homerooms,grades}`; roster chỉ trả số lượng, không kèm danh sách học sinh |
| POST | /admin/homeroom-classes | Admin; {name,academic_year,grade_level:6..12} → 201 |
| GET | /admin/homeroom-classes/{id}/roster | Admin cùng trường; `{homeroom_class_id,student_ids,roster_version}` |
| PUT | /admin/homeroom-classes/{id}/roster | Admin; `{student_ids:UUID[],expected_roster_version?}` thay roster, đồng bộ lớp AUTO, giữ lịch sử; frontend live gửi version và stale trả 409; field tùy chọn để giữ tương thích caller cũ |
| POST | /admin/homeroom-classes/{id}/students/{student_id}/transfer | Admin; `{destination_homeroom_id,expected_source_roster_version?,expected_destination_roster_version?}` → 200; cùng năm/khối, đổi hai roster và sync AUTO trong một transaction; frontend live gửi cả hai version, stale trả 409 |
| POST | /admin/classes | Admin; `{course_id,name,academic_year,semester,grade_level,homeroom_class_id?,enrollment_mode:AUTO/MANUAL,primary_lecturer_id,assisting_lecturer_ids?}` → 201; kiểm tra mọi Lecturer cùng trường và tạo toàn bộ phân công trong transaction |
| GET | /admin/classes/{id}/management | Admin cùng trường; lớp cùng phân công PRIMARY/ASSISTING hiện hành và membership hiện hành; không trả dữ liệu ngoài phạm vi |
| GET | /classes; /classes/{id}; /classes/{id}/members | Chỉ lớp cùng trường và còn quyền hiện hành; Admin xem trong phạm vi trường. `ClassResponse.teaching_role` chỉ có PRIMARY/ASSISTING cho Lecturer được phân công hiện hành; Student/Admin nhận null. |
| PUT | /admin/classes/{id}/teaching-assignments | Admin; `{primary_lecturer_id,assisting_lecturer_ids:[],expected_class_version?}` → 200; giữ lịch sử PRIMARY/ASSISTING; stale version 409 |
| POST | /admin/classes/{id}/enrollment/preview | Admin; xem add/end và class_version/roster_version trước MANUAL→AUTO |
| PATCH | /admin/classes/{id}/enrollment-mode | Admin; {mode,expected_class_version?,expected_roster_version?}; MANUAL→AUTO buộc version từ preview, stale trả 409 |
| POST | /admin/classes/{id}/enrollment/sync | Admin; `{expected_class_version,expected_roster_version}` từ preview → đồng bộ AUTO; stale 409. Body tùy chọn cho client cũ, frontend live gửi version |
| POST/DELETE | /admin/classes/{id}/members[/{student_id}] | Admin; chỉ MANUAL, thêm/kết thúc membership, không xóa lịch sử |
| PUT | /admin/classes/{id}/members | Admin; `{student_ids,expected_class_version}` thay roster MANUAL nguyên tử, giữ episode đã kết thúc; stale 409 |
| POST | /admin/classes/{id}/members/{student_id}/transfer | Admin; {destination_class_id}; chuyển MANUAL cùng môn/năm/học kỳ trong một transaction |
| POST | /admin/classes/{id}/archive; /admin/classes/{id}/restore | Chỉ Admin; `{expected_class_version?}` chặn thao tác trên bản cũ; archived chặn hoạt động chung mới, restore kiểm tra lại quyền hiện hành |
| GET | /internal/v1/classes/{id}/access?user_id=&action= | Service credential scope core:check_access → quyết định quyền theo action/trường/lớp/trạng thái hiện hành |

Các mutation quản trị quan trọng yêu cầu `X-Admin-Reason` là một trong `ADMIN_INTERVENTION`, `POLICY_VIOLATION`, `USER_REQUEST`; audit chỉ lưu reason_code hợp lệ, không lưu nguyên văn tự do. Roster và membership dùng constraint, version và transaction để chống trùng/mất lịch sử; HTTP Idempotency-Key vẫn dùng RAM một process theo phần Auth, không bảo đảm replay response qua restart. Chuyển lớp hiện có mốc hiệu lực khi transaction ghi dữ liệu; Learning xử lý attempt/bài nộp dở theo hợp đồng riêng chưa triển khai. School row được tạo từ school_id đã gán cho Admin; hệ thống không tự mapping trường cho user legacy.

Access action hiện gồm `read_class_content`, `participate_current_class`, `moderate_class_content`, `manage_class_calendar`, `read_own_history`, `read_document_source`, `use_ai_tutor`, `grade_submitted_work`. Đọc lịch sử cá nhân không cấp quyền xem nội dung lớp mới hoặc mở nguồn bị thu hồi; consumer vẫn phải xác minh chủ tài nguyên/Document grant/Learning assignment. Action sai trả validation error; DB/service không xác minh được trả lỗi hạ tầng và consumer fail closed. Khi từ chối, access-check trả thêm `class_status` nếu lớp tồn tại và cùng trường với user (consumer phân biệt lớp archived → 409 với lớp không thấy/khác trường → 404-che); trường hợp không tìm thấy hoặc khác trường vẫn bỏ `class_status`. Consumer ghi dữ liệu có thể yêu cầu khóa chia sẻ hàng lớp (`FOR SHARE`) trong transaction ghi của mình qua tùy chọn lock của check, để mutation Classroom đang giữ `FOR UPDATE` kịp commit trước khi quyết định quyền — không tự sửa bảng Classroom.

**Còn chờ tích hợp:** xử lý pending attempt theo Learning, policy retention/fulfillment, mapping School cho tài khoản cũ và HTTP idempotency bền vững cho các Classroom mutations ngoài import. Import Student CSV/XLSX đã có preview/confirm bền vững, tùy chọn append roster; Notification worker/recipient đã triển khai tại TASK-012. Những phần còn lại chưa được tính là Core G2 hoàn tất.

**TASK-015 backend hardening:** replay của cache Classroom vẫn phải kiểm tra Admin hiện hành và school scope của tài nguyên nguồn/đích (kể cả response 204), hoặc course/homeroom/class đã tạo; scope thay đổi hoặc resource không còn hợp lệ trả 404, không phát lại body cũ. Không mở rộng cam kết cache process-local thành idempotency bền vững. Classroom lấy `Mutation/get_mutation` qua Identity public thay vì import nội bộ.

Core HTTP `/api/*` và `/internal/*` có admission queue trước dependency đồng bộ, giữ permit đến khi cleanup session xong. Capacity mỗi process = `max(1, DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW - 1)`; pool mặc định 5+10, timeout 3 giây. Chờ quá `DATABASE_POOL_TIMEOUT_SECONDS` trả 503 envelope chuẩn, no-store, `Retry-After:1`. Health/OpenAPI không bị queue này chặn; auth/permission vẫn chạy trên request được nhận. Đây là giới hạn hạ tầng, không cấp thêm quyền hoặc thay rule nghiệp vụ.

## Feed / Comments / Calendar / Notifications — IMPLEMENTED
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| GET/POST | /classes/{class_id}/posts | Thành viên hiện hành; GET `{items,next_cursor}`, POST `{body}` → 201 |
| PATCH | /classes/{class_id}/posts/{post_id} | Tác giả còn quyền hiện hành; `{body}` → 200 |
| DELETE | /classes/{class_id}/posts/{post_id} | Tác giả còn quyền hoặc moderation hiện hành; soft-delete → 204; xóa nội dung người khác có audit |
| GET/POST | /classes/{class_id}/posts/{post_id}/comments | Thành viên hiện hành và post còn hiển thị; GET `{items,next_cursor}`, POST `{body}` → 201 |
| PATCH | /classes/{class_id}/posts/{post_id}/comments/{id} | Tác giả còn quyền hiện hành; `{body}` → 200 |
| DELETE | /classes/{class_id}/posts/{post_id}/comments/{id} | Tác giả còn quyền hoặc moderation hiện hành; soft-delete → 204; xóa nội dung người khác có audit |
| GET | /classes/{class_id}/calendar | Thành viên hiện hành; `?from=ISO&to=ISO&limit=&cursor=` → `{items,next_cursor}` |
| POST | /classes/{class_id}/calendar | Giáo viên PRIMARY/ASSISTING hiện hành; `{title,description?,starts_at,ends_at}` → CORE event 201 |
| PATCH/DELETE | /classes/{class_id}/calendar/{id} | Giáo viên PRIMARY/ASSISTING hiện hành; chỉ CORE-origin event; PATCH → 200, DELETE hard-delete → 204 |
| GET | /notifications | Authenticated; chỉ của mình; `?limit=1..100&cursor=` → `{items,unread_count,next_cursor}` |
| PATCH | /notifications/{id}/read | Recipient → 200 `{id,read:true}`; idempotent, giữ read_at đầu tiên |
| POST | /notifications/read-all | Authenticated → 204 |

Social kiểm tra quyền đọc trước khi tra tài nguyên: ngoài quyền/trường/lớp, parent sai scope hoặc đã soft-delete trả 404; thiếu action ghi trả 403; lớp ARCHIVED vẫn đọc nhưng mọi ghi trả 409. Mọi thao tác ghi Social khóa chia sẻ hàng lớp qua access-check trong cùng transaction với mutation. Cursor không hợp lệ hoặc thuộc parent khác trả 400. Body post/comment 1..10.000 và không toàn khoảng trắng; title 1..200; datetime phải có timezone và `starts_at < ends_at`; validation trả 422. LEARNING-origin PATCH/DELETE trả 400. Mọi response Social có `Cache-Control: no-store`; author chỉ gồm `id,display_name`, không lộ email/username. Admin không được đọc Social; Admin cùng trường chỉ đi nhánh moderation DELETE và ghi audit, khác trường trả 404.

Tạo post/comment ghi outbox và snapshot người nhận trong cùng transaction; lỗi ghi outbox làm rollback mutation. Payload không chứa body. Projection deadline Learning chỉ có helper nội bộ chờ contract TASK-019, dedup bằng `external_ref` và bỏ qua version trùng/cũ; không có HTTP sync endpoint. Calendar CORE dùng hard-delete vì DESIGN chưa yêu cầu giữ lịch sử xóa.

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

Worker xác minh school hiện hành qua public Identity/Classroom; post đã xóa không tạo thông báo Social mới. Event 0009/0010 thiếu snapshot dùng audience hiện hành làm fallback, không thể tái tạo audience lịch sử. Event thiếu scope nguồn hoặc khác trường được giữ để retry; event type ngoài bảng không bị worker này đánh dấu published.

Inbox payload chỉ chứa ID/phiên bản/trạng thái/thời điểm trong allowlist, thêm `event_id,schema_version`; không trả school_id, recipient_ids, post_author_id hoặc external_ref. Homeroom dùng `homeroom_id` trong inbox. Link từ ID không cấp quyền; mọi API tài nguyên vẫn kiểm tra quyền hiện hành.

Consumer dedup theo SHA-256 của recipient + schema version + type + aggregate/version; event không có aggregate version dùng UUID event. Notification bất biến theo từng sự kiện; xử lý out-of-order không ghi đè phiên bản mới và không mất các event khác phiên bản. Worker giữ khóa outbox `SKIP LOCKED`, insert inbox và đánh dấu published cùng transaction. Lỗi delivery sau commit không rollback nghiệp vụ; retry dùng đồng hồ DB và backoff giới hạn 300 giây. Import Administration đi qua Classroom public để sinh các event enrollment hiện có; không phát event mới hoặc đưa SMTP credential delivery vào allowlist.

## Administration — IMPLEMENTED (TASK-013)
| Method | Endpoint | Quyền / Body |
|---|---|---|
| GET | /admin/users | Admin cùng trường; `user_id?,account_type?(STUDENT/STAFF),role?,status?,search?,username_missing?,limit,cursor` → Page[AdminUserListItem]; hỗ trợ tra cứu một tài khoản/nhóm để phân trang server-side; chỉ email/username/display_name/status/roles/revision/timestamp và trạng thái delivery, không có credential/token/hash |
| POST | /admin/users | Admin; `{email,roles:[ADMIN/LECTURER],display_name?}` → 201 UserSummaryDTO; header `X-Token-Delivery-Status: DELIVERED/PENDING/NEEDS_REISSUE`; không trả token |
| PATCH | /admin/users/{id} | Admin cùng trường; `{expected_revision,roles?,status?}` atomically cập nhật các trường đã gửi, revoke phiên một lần và ghi một audit; stale revision trả 409 |
| POST | /admin/users/{id}/invitation/reissue | Admin cùng trường; chỉ invitation staff PENDING; vô hiệu invitation token cũ, tạo token mới và thử gửi; header `X-Token-Delivery-Status: DELIVERED/PENDING/NEEDS_REISSUE`; hỗ trợ Idempotency-Key |
| PATCH | /admin/users/{id}/status | Admin cùng trường; `{status:ACTIVE/LOCKED}` → 204, revoke phiên + audit |
| PUT | /admin/users/{id}/roles | Admin cùng trường; `{roles:[ADMIN/LECTURER/STUDENT]}` → UserSummaryDTO; danh sách không rỗng/trùng; revoke phiên khi đổi |
| GET | /admin/audit-events | Admin; `limit,cursor,actor_id?,action?,since?,until?` → `{items,next_cursor}`, chỉ audit cùng trường, metadata allowlist |
| GET/PATCH | /admin/data-requests/{id} | Admin cùng trường với chủ request; GET DataRequestResponse; PATCH body theo quy trình bên dưới |
| GET | /admin/data-requests | Admin; `limit,cursor` → Page[DataRequestResponse], cùng trường |
| POST | /admin/students/imports/preview | Admin; `{format:CSV/XLSX,content_base64,homeroom_class_id?,username_header?,display_name_header?,user_id_header?}` → `{valid,preview_id?,expires_at?,items,errors}`. Header mapping selects input columns; unselected cells are ignored and never returned. `user_id_header` is not inferred unless explicitly selected; an explicitly selected header missing from the file returns 422 |
| POST | /admin/students/imports/confirm | Admin đã tạo preview; `{preview_id}` → `{preview_id,status:COMPLETED,replayed,items}` |
| GET | /admin/students/imports/{preview_id} | Cùng Admin tạo preview + cùng trường; trả PREVIEW/COMPLETED/EXPIRED và trạng thái dòng để đối chiếu timeout; không trả mã kích hoạt |

Mọi route trên dùng Bearer với role/status hiện hành. Ngoài role ADMIN, Identity public kiểm tra actor ACTIVE, email đã xác minh và school scope trong DB; thiếu scope/khác trường trả 404, Student/Lecturer trả 403, token đã revoke/LOCKED trả 401. Response có `Cache-Control: no-store`. POST user, invitation reissue, PATCH status, PUT roles, PATCH data request và confirm import bắt buộc `X-Admin-Reason` thuộc `ADMIN_INTERVENTION`, `POLICY_VIOLATION`, `USER_REQUEST`; thiếu header 422, giá trị lạ 400. Không nhận lý do tự do trong body/header. Audit chỉ lưu code đã kiểm tra và trường cấu trúc, không chép nguyên input.

**Vai trò/trạng thái:** serialize các thay đổi có thể gỡ/khóa Admin bằng advisory transaction lock trước khi khóa user theo UUID. Không gỡ hoặc khóa Admin khi không còn Admin ACTIVE khác, đã verify email và có school scope trong hệ thống (400), kể cả request đồng thời. Staff role yêu cầu email; chuyển sang Student-only cần username/activation hợp lệ, không biến đổi credential âm thầm (409). Mutation role/status thu hồi refresh và session version; ACTIVE không bypass activation. Staff user, invitation và audit commit trước khi gọi SMTP; lỗi gửi không rollback invitation. DB/SMTP không nguyên tử nên email có thể bị gửi lặp nếu SMTP nhận thư nhưng kết nối đứt trước khi Core đánh dấu DELIVERED.

**Audit:** migration 0012 thêm `AuditEvent.school_id` nullable và index school/time, actor/time, action/time; không tạo bảng audit trùng. Identity/Classroom/Social/Administration ghi scope từ backend. Event legacy chưa có tenant-at-event-time giữ null và không được trả bởi Admin API; không suy scope lịch sử từ actor hiện tại. Cursor phải khớp school và bộ lọc, sắp `occurred_at DESC,id DESC`; sai cursor 400, datetime không timezone hoặc since > until 422. Metadata legacy không qua allowlist được trả `{}`. Audit các mutation và việc đọc audit/data requests, không ghi trùng audit đã do Identity/Classroom public tạo.

**Yêu cầu dữ liệu:** PATCH `{status:IN_REVIEW/COMPLETED/REJECTED,resolution_note,identity_verified?:bool}`. `resolution_note` là code trong `VERIFICATION_IN_PROGRESS`, `POLICY_PENDING`, `OUTSIDE_CORE_SCOPE`, `INSUFFICIENT_VERIFICATION`, `REQUEST_REJECTED`, `DUPLICATE_REQUEST`, không chứa raw chat/token hoặc text tự do. COMPLETED/REJECTED yêu cầu `identity_verified:true` (xác nhận kiểm tra thủ công của Admin, không xác minh tự động); thiếu trả 409. Theo quyết định người dùng 2026-10-18, khi chưa có policy/executor xử lý thật cho ACCESS/EXPORT/CORRECTION/DELETE, yêu cầu COMPLETED trả **trạng thái thực IN_REVIEW**, note `POLICY_PENDING`, audit `DATA_REQUEST_DEFERRED`; không xóa, sửa hay xuất dữ liệu liên service hoặc đọc chat. REJECTED có audit, terminal không được mở lại; retry cùng quyết định không ghi trùng. Audit ghi cờ verification có cấu trúc, không copy reason của chủ request.

### Student import CSV/XLSX

- CSV UTF-8 (có/không BOM) hoặc một worksheet XLSX; header bắt buộc `username`, tùy chọn `display_name,user_id`. Chỉ text, không formula/column lạ/duplicate header. Tối đa 100 dòng dữ liệu, file decoded 2 MB, ZIP XML expanded 10 MB/100 entries; parser có defusedxml và chặn DTD/entity. `user_id` dùng để gán username cho Student legacy cùng trường; không tự mapping School hoặc đổi hash/UUID/trạng thái.
- Preview chuẩn hóa username theo Identity, kiểm tra dòng lỗi/trùng username/user_id, đối soát username unique. Tài khoản đã có chỉ được dùng nếu cùng trường, Student-only, username/display_name khớp; không tự ghi đè hồ sơ. Kết quả `CREATE/EXISTING/ASSIGN_USERNAME`; lỗi chỉ `{row,code}`, không phản chiếu raw input hoặc danh tính ngoài trường. File lỗi trả 422; row/business errors trả 200 `valid:false,preview_id:null`.
- Preview hợp lệ lưu draft trong DB, gắn actor + school, hết hạn kỹ thuật sau 30 phút theo đồng hồ DB. Confirm khóa draft và các user liên quan theo UUID, recheck actor/row fingerprints và roster_version; account/roster đổi hoặc hết hạn trả 409, actor khác/cross-school trả 404. Tất cả dòng là một batch atomic: lỗi một dòng/roster/audit/outbox rollback toàn bộ, draft vẫn có thể retry nếu còn hợp lệ.
- `homeroom_class_id` tùy chọn thêm các Student vào roster qua Classroom public, giữ thành viên có sẵn; AUTO sync/outbox do Classroom sở hữu, không ghi đè MANUAL. Confirm không tự kết thúc roster, không đổi teaching assignment hoặc phục hồi join code. Import phân công/metadata lớp khác dùng API Classroom đã có.
- `preview_id` là khóa chống lặp bền vững. Confirm đầu trả code một lần chỉ cho Student mới tạo, qua `items[{row,outcome,student,code?,expires_at?}]`. Code không vào draft/results/audit/log/cache. Retry/restart cùng preview trả `replayed:true`, cùng user IDs và `code:null`; mất mã dùng API issue-code hiện có. Re-import file mới dùng EXISTING và không tự cấp/reset code. Sau commit xóa staging rows, chỉ giữ IDs/outcome/fingerprint; hạn preview không được xem là policy retention pháp lý.

**Public boundaries:** Identity `admin_actor`, `admin_update_user_roles`, `admin_check_student_import`, `admin_list_data_requests`, `admin_get_data_request`, `admin_resolve_data_request` trả DTO; hỗ trợ `session=` caller sở hữu. Classroom `admin_preview_roster(...,session,lock=False) -> RosterImportSnapshot` và `admin_append_roster(...,expected_roster_version,actor_id,correlation_id,reason_code,session)` không commit. Administration không import model/repository Identity/Classroom hoặc SQL sang service khác.

Credential nội bộ hiện dùng header `X-Service-Key` so với `INTERNAL_SERVICE_SECRET`, cấp scope `core:check_access`. Không dùng Bearer JWT của người dùng thay service credential; `user_id` chỉ được tin sau khi xác thực service, và endpoint vẫn phải kiểm tra quyền hiện hành/action.

Python public interface Identity cho consumer Core được đặc tả tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004). Admin mutation bắt buộc actor/correlation ID, trả DTO thay ORM và ghi audit cùng transaction; consumer không import model/repository Identity hoặc ghi audit trùng.

**Offline maintenance TASK-014:** không thêm HTTP route. Coordinator gọi `identity.public.maintenance_identity_report`, `maintenance_assign_school`, `bootstrap_dev_identity`, `bootstrap_staging_admin`, `maintenance_correct_staging_admin_email` và `classroom.public.maintenance_schools`, `maintenance_user_schools`, `maintenance_provision_schools`, `seed_dev_classroom`; mọi helper dùng explicit `session`, caller commit/rollback, DTO chỉ trường an toàn. School mapping cần manifest + plan_sha256 đã review; thiếu/khác scope hoặc lịch sử Classroom mâu thuẫn bị chặn, chỉ gán scope thiếu, revoke phiên và audit `LEGACY_ASSIGN_SCHOOL`. Metadata allowlist thêm changed_fields `school_id`. Dev/test seed giữ guard database riêng/rỗng. Bootstrap staging là CLI offline một lần, không phải route hoặc production onboarding: chỉ kết nối qua `STAGING_DATABASE_URL`, xác thực hostname cấu hình staging và hostname được xác nhận cùng database name, từ chối URI có query `host`/`hostaddr`/`service`/`servicefile`, yêu cầu environment `staging`, confirmation, empty Core preflight và SMTP config; tạo School + Admin `PENDING_VERIFICATION`, ghi audit và queue invitation durable, không in token/password/email. Nếu recipient bị nhập sai trước lần gửi đầu, helper offline chỉ sửa email của Admin pending với delivery còn hạn và `attempts=0`, giữ token, ghi audit; không thêm HTTP route. Lệnh/điều kiện tại [runbook](../../../../services/core/migrations/README.md); production onboarding/FK vẫn cần runbook riêng và kiểm chứng trên môi trường production-like.

`UserSummaryDTO` nội bộ có `display_name` nullable, được batch lookup cùng các trường an toàn khác. Khi dùng cho feed/bình luận, Social chỉ chiếu `id` và `display_name` sang author response; email/username đăng nhập không tự động công khai. Admin Student create/issue-code trả cùng DTO này trong response của Admin.

## Validation / Contract tests
- **IMPLEMENTED Identity:** email lowercase; username trim/lowercase, 1..200 ký tự, không whitespace hoặc @, unique toàn hệ thống; mật khẩu mới 12..128 ký tự. Student không cần email. Không expose hash; chỉ Admin nhận mã một lần trong response Student create/issue-code có `Cache-Control: no-store`. Post/comment 1..10000, title/name 1..200, starts_at < ends_at là contract các module tương ứng.
- Test: unauthorized/cross-school/cross-class, LOCKED/ENDED/ARCHIVED, Admin-only mutations, AUTO/MANUAL concurrency, activation replay, JWT replay/revoke, CSRF, post/comment delete, notification dedup, calendar LEARNING read-only, Admin audit, internal auth.
- FastAPI sinh OpenAPI cho Identity, Classroom, Social, Notification và Administration; Identity/Social có snapshot, Classroom/Notification/Administration có contract/security test. Snapshot Identity không bao gồm hai import route do Administration sở hữu; CI chạy test liên quan cùng pytest.

## Ghi chú tương thích — phạm vi Lumi THCS/THPT chính khóa
Đối tượng: học sinh khối 6–12 trong lớp chính khóa. Giữ các enum/API role kỹ thuật `ADMIN`, `LECTURER`, `STUDENT` để tương thích code; UI hiển thị Quản trị viên/Giáo viên/Học sinh. Những route hiện được mô tả ở trên là **contract hiện hành hoặc dự kiến**, không phải toàn bộ đã triển khai.

- `POST /auth/register` **BLOCKED — LEGACY**: giữ route deprecated nhưng trả 403 cho request hợp lệ; không tạo Student. Logic đăng ký nội bộ cũ được giữ để tương thích/kiểm thử tài khoản lịch sử, không export qua Identity public interface.
- Lecturer `POST /classes` là **SUPERSEDED DRAFT**, không được triển khai theo quyền Lecturer; chỉ Admin tạo lớp môn học.
- `/classes/join-requests*` là **SUPERSEDED DRAFT/OUT OF MVP**; không dùng mã lớp hoặc teacher approval.
- `DELETE /classes/{class_id}/members/me` là **SUPERSEDED DRAFT/OUT OF MVP**; Student không tự rời lớp.
- Các API quản trị, dữ liệu cá nhân, điểm, quyền và audit tiếp tục phải tuân thủ Business Rules; không tự thêm role Phụ huynh/Admin theo trường.


## API mục tiêu còn lại (PROPOSED, chưa triển khai)
- `POST /admin/students/imports/preview` và `POST /admin/students/imports/confirm` đã triển khai ở mục Administration; fulfillment liên service và retention còn chờ chính sách, giữ IN_REVIEW.
- Classroom routes và quyền đã triển khai theo mục Course / Class / Membership ở trên; các consumer Social/Document/AI/Learning phải dùng public/internal action check, không đọc repository Classroom.
- Các route `/classes/join-requests*`, `/classes/{id}/co-lecturers/invitations*`, `/classes/{id}/ownership-transfer`, Lecturer `POST /classes`, Lecturer membership mutation, Owner archive/restore, public Student `/auth/register` là **legacy/ngoài phạm vi MVP**; không coi chúng là API được phép phát hành. Không xóa source/migration chỉ vì đổi contract.
- Learning phải có quyền nháp → duyệt/công bố assessment, chấm được phân công → đề xuất/phê duyệt sửa điểm, attempt transfer cutoff; các service dùng access check theo hành động, không dựa độc nhất membership ACTIVE.
- Kiểm thử: cross-school/cross-class, role Admin-only, Student no self-register/join, AUTO/MANUAL, idempotent bulk import, activation token expiry/replay, historical read vs source revoke, transfer attempt, grade approval/audit.

## Phạm vi chuyển đổi Identity hiện tại
- Migration 0005 bổ sung `CORRECTION` cho yêu cầu xử lý thủ công; không tự sửa dữ liệu.
- Migration 0006 bổ sung `users.username` unique/lowercase, `school_id`, `activated_at`; email nullable. Không backfill trường/username hoặc tự kích hoạt tài khoản cũ. School đã có ở 0008; `users.school_id` chưa có FK vì mapping legacy và contract provision School trước Identity còn cần owner duyệt. TASK-014 có CLI report/plan/apply theo manifest, không tự suy mapping; xem [runbook](../../../../services/core/migrations/README.md).
- Identity lookup lấy school_id từ DB hiện hành, không từ JWT/body. Admin tạo tài khoản qua public helper kế thừa school_id của actor. Các Admin helpers yêu cầu school scope; mutation status che tài khoản ngoài trường hoặc thiếu scope bằng 404, kể cả hai phía đều null. Trước khi sử dụng Admin helpers phải có mapping trường được duyệt cho tài khoản cũ; migration không tự gán trường.
- Migration 0007 bổ sung purpose STUDENT_ACTIVATION/STUDENT_PASSWORD_RESET, giữ token lịch sử. Student onboarding/recovery đã triển khai theo quyết định kỹ thuật được người dùng duyệt 2026-10-14; bulk Student import CSV/XLSX đã triển khai ở TASK-013. Tài khoản Student cũ giữ ID/password/dữ liệu nhưng cần Admin gán username qua public interface/import trước khi đăng nhập lại; không fallback email cho Student.

## Student provisioning / activation / recovery — IMPLEMENTED
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /admin/students | Admin cùng school scope; {username,display_name?} → 201 {student:UserSummaryDTO,purpose:ACTIVATION,code,expires_at} |
| POST | /admin/students/{user_id}/activation-codes | Admin cùng trường; {} cho pending → mã ACTIVATION mới; {identity_verified:true} cho ACTIVE → mã PASSWORD_RESET sau xác minh thủ công |
| POST | /auth/activate | Public; {username,activation_code,new_password} → 204 ACTIVE, thu hồi phiên; sai tên/purpose/hạn/replay/LOCKED trả 400 |

- Mã kích hoạt mặc định 24 giờ (`STUDENT_ACTIVATION_EXPIRE_HOURS`); mã reset dùng `PASSWORD_RESET_EXPIRE_MINUTES` (60 phút). Lưu SHA-256; cấp lại vô hiệu hóa mã trước. Không SMTP/mật khẩu mặc định dùng chung. Mã reset sử dụng `/auth/password/reset`, không tự mở tài khoản LOCKED.
- Admin nhận code trực tiếp một lần, chịu trách nhiệm phân phối an toàn; không có API đọc lại code và không cache code response. Request mất phản hồi: dùng route issue-code để cấp mã mới; tạo lại cùng username trả 409. Ba thao tác create/issue-code/activate từ chối `Idempotency-Key` bằng 400.
- Admin phải xác minh danh tính trước khi gửi `identity_verified:true` cho recovery; Backend kiểm tra role/trạng thái/trường, ghi audit cấp mã và reset; flag là xác nhận thao tác của Admin, không phải xác minh tự động. Cấp mã reset thu hồi các phiên đang mở; hoàn tất reset tiếp tục thu hồi phiên.
- `identity.public.admin_assign_student_username` chuyển Student legacy trong cùng trường: username chưa có mới được gán; giữ UUID/email/hash/status. ACTIVE/LOCKED legacy phải đã verify email, ghi activated_at; LOCKED không tự mở. Pending vẫn phải nhận mã và activate. Thu hồi phiên/token cũ, audit cùng transaction. HTTP import hỗ trợ cột user_id để gọi helper này; không tự chuyển dữ liệu khi migration schema.
