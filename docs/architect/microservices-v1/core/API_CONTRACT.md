# Core API Contract v1

**Trạng thái:** Identity auth/profile/data requests và Student provisioning/activation/recovery **IMPLEMENTED**; public register **BLOCKED — LEGACY**. Classroom/import và các API khác chưa triển khai được đánh dấu **PROPOSED**. Business Rules là nguồn quyết định nghiệp vụ.

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

Profile trả `{id,email,username,school_id,display_name,roles,status}`, không chứa hash; email/username/school_id có thể null cho tài khoản chưa chuyển đổi. PATCH không gửi `display_name` giữ nguyên, `null` xóa tên. Forgot-password trả `{message}` generic, không lộ token hoặc việc tài khoản tồn tại; thiếu cấu hình SMTP trả 503. Register bị chặn 403, không phụ thuộc SMTP.

Password/reset nhận PASSWORD_RESET/ADMIN_INVITATION cho staff hoặc STUDENT_PASSWORD_RESET do Admin đã xác minh cấp cho Student ACTIVE. Lời mời staff chỉ đặt mật khẩu/xác minh tài khoản PENDING, không mở LOCKED. Activation token chỉ dùng tại /auth/activate, reset token không thay activation; token email cũ không được dùng cho Student. Token một lần, đúng purpose/hạn; reset không trả token qua response.

Data requests POST dùng `type` chuẩn (alias `request_type` được chấp nhận), reason tùy chọn tối đa 10000 ký tự; trả `{id,user_id,type,reason,status:PENDING,resolution_note:null,created_at,updated_at}`. GET trả `{items,next_cursor}` theo limit/cursor và UUID tăng dần, chỉ của người dùng xác thực. Không nhận user_id/status/resolution_note do người dùng đặt. DELETE là loại yêu cầu xử lý thủ công, không tự xóa dữ liệu hoặc khóa tài khoản.

Rate limit mặc định: login 5 lần sai/60 giây theo IP và identifier chuẩn hóa (namespace username/email); forgot 3 request/3600 giây theo IP; activate/verify/reset 5/60 giây theo IP. 429 có `Retry-After`. Register bị chặn mọi lần gọi, không replay response 201 từ cache.

Identity idempotency hiện dùng RAM một process, TTL 24 giờ; không bền vững qua restart/nhiều worker. Scope anonymous dùng identifier chuẩn hóa/token hash, refresh/Bearer dùng user. Token cookie được tính vào payload; cookie đã đổi với cùng key có thể trả 409. Cache credential responses phải kiểm tra quyền/phiên hiện hành, trả 401 khi stale; dùng key mới cho lần xác thực mới. Chi tiết cấu hình và giới hạn tại [Core README](../../../../services/core/README.md#identity-http-api-task-003).

## Course / Class / Membership — IMPLEMENTED trong Core (PR #6 sau chỉnh sửa)
Chỉ Admin cùng trường tạo môn/lớp hành chính/lớp môn học, phân công giáo viên, ghi danh AUTO/MANUAL, chuyển lớp và archive/restore. Trường của lớp lấy từ actor hiện hành trong Identity DB; thiếu trường hoặc khác trường bị che bằng 404. Không có join code, join request, Lecturer-created class, teacher invitation/ownership transfer hay Student self-leave.

| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /admin/courses | Admin; {code,name} → 201 course trong trường hiện hành |
| POST | /admin/homeroom-classes | Admin; {name,academic_year,grade_level:6..12} → 201 |
| PUT | /admin/homeroom-classes/{id}/roster | Admin; {student_ids:UUID[]} thay roster, đồng bộ lớp AUTO, giữ lịch sử → 200 |
| POST | /admin/homeroom-classes/{id}/students/{student_id}/transfer | Admin; {destination_homeroom_id} → 200; cùng năm/khối, đổi hai roster và sync AUTO trong một transaction |
| POST | /admin/classes | Admin; {course_id,name,academic_year,semester,grade_level,homeroom_class_id?,enrollment_mode:AUTO/MANUAL,primary_lecturer_id} → 201 |
| GET | /classes; /classes/{id}; /classes/{id}/members | Chỉ lớp cùng trường và còn quyền hiện hành; Admin xem trong phạm vi trường |
| PUT | /admin/classes/{id}/teaching-assignments | Admin; {primary_lecturer_id,assisting_lecturer_ids:[]} → 200; giữ lịch sử PRIMARY/ASSISTING |
| POST | /admin/classes/{id}/enrollment/preview | Admin; xem add/end và class_version/roster_version trước MANUAL→AUTO |
| PATCH | /admin/classes/{id}/enrollment-mode | Admin; {mode,expected_class_version?,expected_roster_version?}; MANUAL→AUTO buộc version từ preview, stale trả 409 |
| POST | /admin/classes/{id}/enrollment/sync | Admin; AUTO đồng bộ lại roster, không ghi đè lớp MANUAL |
| POST/DELETE | /admin/classes/{id}/members[/{student_id}] | Admin; chỉ MANUAL, thêm/kết thúc membership, không xóa lịch sử |
| POST | /admin/classes/{id}/members/{student_id}/transfer | Admin; {destination_class_id}; chuyển MANUAL cùng môn/năm/học kỳ trong một transaction |
| POST | /admin/classes/{id}/archive; /admin/classes/{id}/restore | Chỉ Admin; archived chặn hoạt động chung mới, restore kiểm tra lại quyền hiện hành |
| GET | /internal/v1/classes/{id}/access?user_id=&action= | Service credential scope core:check_access → quyết định quyền theo action/trường/lớp/trạng thái hiện hành |

Các mutation quản trị quan trọng yêu cầu `X-Admin-Reason` là một trong `ADMIN_INTERVENTION`, `POLICY_VIOLATION`, `USER_REQUEST`; audit chỉ lưu reason_code hợp lệ, không lưu nguyên văn tự do. Roster và membership dùng constraint, version và transaction để chống trùng/mất lịch sử; HTTP Idempotency-Key vẫn dùng RAM một process theo phần Auth, không bảo đảm replay response qua restart. Chuyển lớp hiện có mốc hiệu lực khi transaction ghi dữ liệu; Learning xử lý attempt/bài nộp dở theo hợp đồng riêng chưa triển khai. School row được tạo từ school_id đã gán cho Admin; hệ thống không tự mapping trường cho user legacy.

Access action hiện gồm `read_class_content`, `participate_current_class`, `moderate_class_content`, `manage_class_calendar`, `read_own_history`, `read_document_source`, `use_ai_tutor`, `grade_submitted_work`. Đọc lịch sử cá nhân không cấp quyền xem nội dung lớp mới hoặc mở nguồn bị thu hồi; consumer vẫn phải xác minh chủ tài nguyên/Document grant/Learning assignment. Action sai trả validation error; DB/service không xác minh được trả lỗi hạ tầng và consumer fail closed. Khi từ chối, access-check trả thêm `class_status` nếu lớp tồn tại và cùng trường với user (consumer phân biệt lớp archived → 409 với lớp không thấy/khác trường → 404-che); trường hợp không tìm thấy hoặc khác trường vẫn bỏ `class_status`. Consumer ghi dữ liệu có thể yêu cầu khóa chia sẻ hàng lớp (`FOR SHARE`) trong transaction ghi của mình qua tùy chọn lock của check, để mutation Classroom đang giữ `FOR UPDATE` kịp commit trước khi quyết định quyền — không tự sửa bảng Classroom.

**Còn chờ tích hợp:** import CSV/Excel, xử lý pending attempt theo Learning, Notification worker/recipient, policy retention, mapping School cho tài khoản cũ và bảo đảm idempotency bền vững nhiều worker. Những phần này chưa được tính là Core G2 hoàn tất.

## Feed / Comments / Calendar — IMPLEMENTED; Notifications — PROPOSED
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
| GET | /notifications | Authenticated; chỉ của mình, paginated |
| PATCH | /notifications/{id}/read | Recipient → 200 {read:true} |
| POST | /notifications/read-all | Authenticated → 204 |

Social kiểm tra quyền đọc trước khi tra tài nguyên: ngoài quyền/trường/lớp, parent sai scope hoặc đã soft-delete trả 404; thiếu action ghi trả 403; lớp ARCHIVED vẫn đọc nhưng mọi ghi trả 409. Mọi thao tác ghi Social khóa chia sẻ hàng lớp qua access-check trong cùng transaction với mutation. Cursor không hợp lệ hoặc thuộc parent khác trả 400. Body post/comment 1..10.000 và không toàn khoảng trắng; title 1..200; datetime phải có timezone và `starts_at < ends_at`; validation trả 422. LEARNING-origin PATCH/DELETE trả 400. Mọi response Social có `Cache-Control: no-store`; author chỉ gồm `id,display_name`, không lộ email/username. Admin không được đọc Social; Admin cùng trường chỉ đi nhánh moderation DELETE và ghi audit, khác trường trả 404.

Tạo post/comment ghi outbox trong cùng transaction; lỗi ghi outbox làm rollback mutation. Payload không chứa body. Projection deadline Learning chỉ có helper nội bộ chờ contract TASK-019, dedup bằng `external_ref` và bỏ qua version trùng/cũ; không có HTTP sync endpoint. Calendar CORE dùng hard-delete vì DESIGN chưa yêu cầu giữ lịch sử xóa. Notifications ở ba dòng cuối bảng vẫn PROPOSED.

## Admin còn lại — PROPOSED (Student và Classroom đã triển khai ở mục riêng)
| Method | Endpoint | Quyền / Body |
|---|---|---|
| POST | /admin/users | Admin {email,roles:ADMIN/LECTURER} → 201, gửi link đặt mật khẩu; Student dùng provisioning riêng |
| PATCH | /admin/users/{id}/status | Admin {status:ACTIVE/LOCKED} + audit |
| PUT | /admin/users/{id}/roles | Admin {roles:[...]} + audit; không xóa Admin cuối |
| GET | /admin/audit-events | Admin; paginated redacted audit |
| GET/PATCH | /admin/data-requests/{id} | Admin; PATCH {status:IN_REVIEW/COMPLETED/REJECTED,resolution_note} |
| GET | /admin/data-requests | Admin; paginated |

Admin can thiệp lớp có reason_code allowlist và audit theo mục Classroom; không tự có quyền xem chat riêng tư. Lý do tự do cho các workflow Administration khác vẫn cần thiết kế/redact ở TASK-013, không tự ghi nguyên header. Internal API không chấp nhận browser trực tiếp; fail closed.

Credential nội bộ hiện dùng header `X-Service-Key` so với `INTERNAL_SERVICE_SECRET`, cấp scope `core:check_access`. Không dùng Bearer JWT của người dùng thay service credential; `user_id` chỉ được tin sau khi xác thực service, và endpoint vẫn phải kiểm tra quyền hiện hành/action.

Python public interface Identity cho consumer Core được đặc tả tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004). Admin mutation bắt buộc actor/correlation ID, trả DTO thay ORM và ghi audit cùng transaction; consumer không import model/repository Identity hoặc ghi audit trùng.

`UserSummaryDTO` nội bộ có `display_name` nullable, được batch lookup cùng các trường an toàn khác. Khi dùng cho feed/bình luận, Social chỉ chiếu `id` và `display_name` sang author response; email/username đăng nhập không tự động công khai. Admin Student create/issue-code trả cùng DTO này trong response của Admin.

## Validation / Contract tests
- **IMPLEMENTED Identity:** email lowercase; username trim/lowercase, 1..200 ký tự, không whitespace hoặc @, unique toàn hệ thống; mật khẩu mới 12..128 ký tự. Student không cần email. Không expose hash; chỉ Admin nhận mã một lần trong response Student create/issue-code có `Cache-Control: no-store`. Post/comment 1..10000, title/name 1..200, starts_at < ends_at là contract các module tương ứng.
- Test: unauthorized/cross-school/cross-class, LOCKED/ENDED/ARCHIVED, Admin-only mutations, AUTO/MANUAL concurrency, activation replay, JWT replay/revoke, CSRF, post/comment delete, notification dedup, calendar LEARNING read-only, Admin audit, internal auth.
- FastAPI sinh OpenAPI cho Identity, Classroom và Social đã triển khai; Identity có snapshot, Classroom/Social có contract test kiểm tra đúng tập route. Notification/Admin còn lại vẫn là PROPOSED; CI chạy test liên quan cùng pytest.

## Ghi chú tương thích — phạm vi Lumi THCS/THPT chính khóa
Đối tượng: học sinh khối 6–12 trong lớp chính khóa. Giữ các enum/API role kỹ thuật `ADMIN`, `LECTURER`, `STUDENT` để tương thích code; UI hiển thị Quản trị viên/Giáo viên/Học sinh. Những route hiện được mô tả ở trên là **contract hiện hành hoặc dự kiến**, không phải toàn bộ đã triển khai.

- `POST /auth/register` **BLOCKED — LEGACY**: giữ route deprecated nhưng trả 403 cho request hợp lệ; không tạo Student. Logic đăng ký nội bộ cũ được giữ để tương thích/kiểm thử tài khoản lịch sử, không export qua Identity public interface.
- Lecturer `POST /classes` là **SUPERSEDED DRAFT**, không được triển khai theo quyền Lecturer; chỉ Admin tạo lớp môn học.
- `/classes/join-requests*` là **SUPERSEDED DRAFT/OUT OF MVP**; không dùng mã lớp hoặc teacher approval.
- `DELETE /classes/{class_id}/members/me` là **SUPERSEDED DRAFT/OUT OF MVP**; Student không tự rời lớp.
- Các API quản trị, dữ liệu cá nhân, điểm, quyền và audit tiếp tục phải tuân thủ Business Rules; không tự thêm role Phụ huynh/Admin theo trường.


## API mục tiêu còn lại (PROPOSED, chưa triển khai)
- `POST /admin/students/imports/preview` và `POST /admin/students/imports/confirm`: CSV/Excel, phát hiện trùng/lỗi, idempotency và audit; không trả mã kích hoạt trong log.
- Classroom routes và quyền đã triển khai theo mục Course / Class / Membership ở trên; các consumer Social/Document/AI/Learning phải dùng public/internal action check, không đọc repository Classroom.
- Các route `/classes/join-requests*`, `/classes/{id}/co-lecturers/invitations*`, `/classes/{id}/ownership-transfer`, Lecturer `POST /classes`, Lecturer membership mutation, Owner archive/restore, public Student `/auth/register` là **legacy/ngoài phạm vi MVP**; không coi chúng là API được phép phát hành. Không xóa source/migration chỉ vì đổi contract.
- Learning phải có quyền nháp → duyệt/công bố assessment, chấm được phân công → đề xuất/phê duyệt sửa điểm, attempt transfer cutoff; các service dùng access check theo hành động, không dựa độc nhất membership ACTIVE.
- Kiểm thử: cross-school/cross-class, role Admin-only, Student no self-register/join, AUTO/MANUAL, idempotent bulk import, activation token expiry/replay, historical read vs source revoke, transfer attempt, grade approval/audit.

## Phạm vi chuyển đổi Identity hiện tại
- Migration 0005 bổ sung `CORRECTION` cho yêu cầu xử lý thủ công; không tự sửa dữ liệu.
- Migration 0006 bổ sung `users.username` unique/lowercase, `school_id`, `activated_at`; email nullable. Không backfill trường/username hoặc tự kích hoạt tài khoản cũ. `school_id` chưa có FK vì entity School thuộc Classroom chưa được triển khai.
- Identity lookup lấy school_id từ DB hiện hành, không từ JWT/body. Admin tạo tài khoản qua public helper kế thừa school_id của actor. Các Admin helpers yêu cầu school scope; mutation status che tài khoản ngoài trường hoặc thiếu scope bằng 404, kể cả hai phía đều null. Trước khi sử dụng Admin helpers phải có mapping trường được duyệt cho tài khoản cũ; migration không tự gán trường.
- Migration 0007 bổ sung purpose STUDENT_ACTIVATION/STUDENT_PASSWORD_RESET, giữ token lịch sử. Student onboarding/recovery đã triển khai theo quyết định kỹ thuật được người dùng duyệt 2026-10-14; bulk import vẫn PROPOSED. Tài khoản Student cũ giữ ID/password/dữ liệu nhưng cần Admin gán username qua public interface trước khi đăng nhập lại; không fallback email cho Student.

## Student provisioning / activation / recovery — IMPLEMENTED
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /admin/students | Admin cùng school scope; {username,display_name?} → 201 {student:UserSummaryDTO,purpose:ACTIVATION,code,expires_at} |
| POST | /admin/students/{user_id}/activation-codes | Admin cùng trường; {} cho pending → mã ACTIVATION mới; {identity_verified:true} cho ACTIVE → mã PASSWORD_RESET sau xác minh thủ công |
| POST | /auth/activate | Public; {username,activation_code,new_password} → 204 ACTIVE, thu hồi phiên; sai tên/purpose/hạn/replay/LOCKED trả 400 |

- Mã kích hoạt mặc định 24 giờ (`STUDENT_ACTIVATION_EXPIRE_HOURS`); mã reset dùng `PASSWORD_RESET_EXPIRE_MINUTES` (60 phút). Lưu SHA-256; cấp lại vô hiệu hóa mã trước. Không SMTP/mật khẩu mặc định dùng chung. Mã reset sử dụng `/auth/password/reset`, không tự mở tài khoản LOCKED.
- Admin nhận code trực tiếp một lần, chịu trách nhiệm phân phối an toàn; không có API đọc lại code và không cache code response. Request mất phản hồi: dùng route issue-code để cấp mã mới; tạo lại cùng username trả 409. Ba thao tác create/issue-code/activate từ chối `Idempotency-Key` bằng 400.
- Admin phải xác minh danh tính trước khi gửi `identity_verified:true` cho recovery; Backend kiểm tra role/trạng thái/trường, ghi audit cấp mã và reset; flag là xác nhận thao tác của Admin, không phải xác minh tự động. Cấp mã reset thu hồi các phiên đang mở; hoàn tất reset tiếp tục thu hồi phiên.
- `identity.public.admin_assign_student_username` chuyển Student legacy trong cùng trường: username chưa có mới được gán; giữ UUID/email/hash/status. ACTIVE/LOCKED legacy phải đã verify email, ghi activated_at; LOCKED không tự mở. Pending vẫn phải nhận mã và activate. Thu hồi phiên/token cũ, audit cùng transaction. Chưa có HTTP quản lý chuyển đổi/bulk import; consumer Administration dùng public interface.
