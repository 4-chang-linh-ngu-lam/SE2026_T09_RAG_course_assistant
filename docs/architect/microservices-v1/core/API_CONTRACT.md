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

## Course / Class / Membership — PROPOSED (chưa chốt payload)
**DECIDED:** Chỉ Admin tạo lớp môn học, roster, phân công giáo viên, ghi danh AUTO/MANUAL, archive/restore. Không có join code, join-request, giáo viên tự tạo lớp, teacher invitation/ownership transfer, Student tự leave trong MVP.

**PROPOSED routes:** `POST /admin/homeroom-classes`, `PUT /admin/homeroom-classes/{id}/roster`, `POST /admin/classes`, `PUT /admin/classes/{id}/teaching-assignments`, `POST /admin/classes/{id}/enrollment/preview`, `POST /admin/classes/{id}/enrollment/sync`, `PATCH /admin/classes/{id}/enrollment-mode`, `POST /admin/classes/{id}/members`, `DELETE /admin/classes/{id}/members/{student_id}`, `POST /admin/classes/{id}/archive`, `POST /admin/classes/{id}/restore`.

**PENDING DESIGN:** request/response schema, method/payload roster, idempotency bền vững, preview token, thời điểm chuyển lớp, API versioning, event contract. Không xem các route đề xuất là đã triển khai. Endpoint join-request/owner transfer cũ **SUPERSEDED/OUT OF MVP**; không xóa code hoặc migration lịch sử chỉ do thay đổi tài liệu.

## Feed / Comments / Calendar / Notifications — PROPOSED
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
| GET | /notifications | Authenticated; chỉ của mình, paginated |
| PATCH | /notifications/{id}/read | Recipient → 200 {read:true} |
| POST | /notifications/read-all | Authenticated → 204 |

Các route Social/Notification ở bảng này chưa triển khai; payload/error/permission chi tiết cần review cùng TASK-009–012. Parent class/post/comment phải cùng scope, dữ liệu đã soft delete không lộ qua list/detail; archived từ chối hoạt động ghi chung. Deadline LEARNING chỉ đồng bộ qua integration, không chỉnh tại Core.

## Admin / Internal — PROPOSED (Student implemented bên dưới)
| Method | Endpoint | Quyền / Body |
|---|---|---|
| POST | /admin/users | Admin {email,roles:ADMIN/LECTURER} → 201, gửi link đặt mật khẩu; Student dùng provisioning riêng |
| PATCH | /admin/users/{id}/status | Admin {status:ACTIVE/LOCKED} + audit |
| PUT | /admin/users/{id}/roles | Admin {roles:[...]} + audit; không xóa Admin cuối |
| GET | /admin/audit-events | Admin; paginated redacted audit |
| GET/PATCH | /admin/data-requests/{id} | Admin; PATCH {status:IN_REVIEW/COMPLETED/REJECTED,resolution_note} |
| GET | /admin/data-requests | Admin; paginated |
| GET | /internal/v1/classes/{class_id}/access?user_id=&action= | Authenticated service scope core:check_access → {allowed,class_id,user_id,action} |

Admin can thiệp lớp cần `X-Admin-Reason` và audit; không tự có quyền xem chat riêng tư. Common AuditMetadata hiện chỉ hỗ trợ allowlist/reason_code; cách lưu lý do tự do cần được thiết kế/redact ở TASK-013, không tự ghi nguyên header. Internal API không chấp nhận browser trực tiếp; fail closed.

Credential nội bộ hiện dùng header `X-Service-Key` so với `INTERNAL_SERVICE_SECRET`, cấp scope `core:check_access`. Không dùng Bearer JWT của người dùng thay service credential; `user_id` chỉ được tin sau khi xác thực service, và endpoint vẫn phải kiểm tra quyền hiện hành/action.

Python public interface Identity cho consumer Core được đặc tả tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004). Admin mutation bắt buộc actor/correlation ID, trả DTO thay ORM và ghi audit cùng transaction; consumer không import model/repository Identity hoặc ghi audit trùng.

`UserSummaryDTO` nội bộ có `display_name` nullable, được batch lookup cùng các trường an toàn khác. Khi dùng cho feed/bình luận, Social chỉ chiếu `id` và `display_name` sang author response; email/username đăng nhập không tự động công khai. Admin Student create/issue-code trả cùng DTO này trong response của Admin.

## Validation / Contract tests
- **IMPLEMENTED Identity:** email lowercase; username trim/lowercase, 1..200 ký tự, không whitespace hoặc @, unique toàn hệ thống; mật khẩu mới 12..128 ký tự. Student không cần email. Không expose hash; chỉ Admin nhận mã một lần trong response Student create/issue-code có `Cache-Control: no-store`. Post/comment 1..10000, title/name 1..200, starts_at < ends_at là contract các module tương ứng.
- Test: unauthorized/cross-school/cross-class, LOCKED/ENDED/ARCHIVED, Admin-only mutations, AUTO/MANUAL concurrency, activation replay, JWT replay/revoke, CSRF, post/comment delete, notification dedup, calendar LEARNING read-only, Admin audit, internal auth.
- FastAPI sinh OpenAPI cho Identity auth/profile/data requests, với request/response/error schemas và snapshot trong test. Các bảng endpoint ngoài Identity vẫn là hợp đồng hành vi, chưa phải bằng chứng triển khai; CI chạy contract test cùng pytest.

## Ghi chú tương thích — phạm vi Lumi THCS/THPT chính khóa
Đối tượng: học sinh khối 6–12 trong lớp chính khóa. Giữ các enum/API role kỹ thuật `ADMIN`, `LECTURER`, `STUDENT` để tương thích code; UI hiển thị Quản trị viên/Giáo viên/Học sinh. Những route hiện được mô tả ở trên là **contract hiện hành hoặc dự kiến**, không phải toàn bộ đã triển khai.

- `POST /auth/register` **BLOCKED — LEGACY**: giữ route deprecated nhưng trả 403 cho request hợp lệ; không tạo Student. Logic đăng ký nội bộ cũ được giữ để tương thích/kiểm thử tài khoản lịch sử, không export qua Identity public interface.
- Lecturer `POST /classes` là **SUPERSEDED DRAFT**, không được triển khai theo quyền Lecturer; chỉ Admin tạo lớp môn học.
- `/classes/join-requests*` là **SUPERSEDED DRAFT/OUT OF MVP**; không dùng mã lớp hoặc teacher approval.
- `DELETE /classes/{class_id}/members/me` là **SUPERSEDED DRAFT/OUT OF MVP**; Student không tự rời lớp.
- Các API quản trị, dữ liệu cá nhân, điểm, quyền và audit tiếp tục phải tuân thủ Business Rules; không tự thêm role Phụ huynh/Admin theo trường.


## API mục tiêu (PROPOSED, chưa triển khai)
- `POST /admin/students/imports/preview` và `POST /admin/students/imports/confirm`: CSV/Excel, phát hiện trùng/lỗi, idempotency và audit; không trả mã kích hoạt trong log.
- Nhóm homeroom/roster/classes/teaching-assignments theo mục Course / Class / Membership bên trên; chỉ Admin, ràng buộc school scope. Method/payload roster vẫn là đề xuất cần chốt, không có hai contract POST/PUT cùng được duyệt.
- `POST /admin/classes/{id}/enrollment/preview`, `POST /admin/classes/{id}/enrollment/sync`, `PATCH /admin/classes/{id}/enrollment-mode`, `POST /admin/classes/{id}/members`, `DELETE /admin/classes/{id}/members/{student_id}`: chỉ Admin, đồng bộ AUTO/MANUAL, audit, giữ lịch sử; MANUAL→AUTO phải preview/confirm.
- `POST /admin/classes/{id}/archive`, `POST /admin/classes/{id}/restore`: chỉ Admin.
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
