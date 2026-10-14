# Core API Contract v1

**Trạng thái:** Identity HTTP API hiện có là **IMPLEMENTED — LEGACY** nếu trái baseline; API Classroom trước đây là **SUPERSEDED DRAFT**; API mục tiêu phía dưới là **PROPOSED**, chưa triển khai. Business Rules là nguồn quyết định nghiệp vụ.

## Quy ước
Health không dùng prefix `/api/v1`: `GET /health/live` → 200 `{status:"live"}`; `GET /health/ready` → 200 `{status:"ready",db:"connected"}` khi DB/schema Core dùng được, hoặc 503 `SERVICE_UNAVAILABLE`. Giá trị live thay `ok` của skeleton theo TASK-016. Health schemas được sinh trong OpenAPI.

- Public `/api/v1`, HTTP/JSON, Bearer access JWT; refresh/logout qua HttpOnly Secure cookie + CSRF/Origin protection.
- UUID cho ID; ISO-8601 UTC cho thời gian. List: `?limit=20&cursor=<opaque>`, limit 1..100; `{"items":[],"next_cursor":null}`.
- `200` đọc/cập nhật, `201` tạo, `204` xóa; lỗi `400 BAD_REQUEST`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`.
- Error: `{"error":{"code":"FORBIDDEN","message":"Không có quyền","correlation_id":"uuid"}}`. Che tài nguyên ngoài quyền bằng 404.
- Mọi response có `X-Correlation-ID`; giữ UUID hợp lệ từ request hoặc sinh UUID mới. Lỗi không dự kiến trả `500 INTERNAL_ERROR`, dependency xác thực/DB không khả dụng có thể trả `503 SERVICE_UNAVAILABLE`; không phản chiếu nội dung nhạy cảm trong lỗi.
- Mutations hỗ trợ `Idempotency-Key` UUID (scope user+endpoint, giữ 24h); cùng key khác payload trả 409. Hoạt động mới trong lớp cần membership hiện hành; đọc lịch sử cá nhân kiểm tra quyền riêng theo action và quyền nguồn hiện hành.

## Auth / User — IMPLEMENTED (legacy nơi mâu thuẫn)

> **Không dùng** public `/auth/register` cho Student trong MVP. Bảng dưới ghi nhận contract Identity đang triển khai, **không phải danh sách API được phép phát hành cho Student**. Luồng Student mục tiêu xem mục `API mục tiêu`.
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /auth/register | Public; {email,password} → 201 {user_id,email,status:PENDING_VERIFICATION} |
| POST | /auth/verify-email | Public; {token} → 200 {verified:true} |
| POST | /auth/login | Public; {email,password} → 200 {access_token,token_type:bearer,expires_in:900} + refresh cookie |
| POST | /auth/refresh | Refresh cookie + CSRF → 200 access + rotated cookie |
| POST | /auth/logout | Refresh cookie + CSRF → 204, revoke/clear |
| POST | /auth/logout-all | Bearer → 204 |
| POST | /auth/password/forgot | Public; {email} → 200 generic |
| POST | /auth/password/reset | Public; {token,new_password} → 204 |
| GET/PATCH | /users/me | Bearer; GET profile, PATCH {display_name?} |
| GET/POST | /users/me/data-requests | Bearer; GET list, POST {type:ACCESS/EXPORT/DELETE,reason?} → 201 PENDING |

Refresh cookie tên `refresh_token`, path `/api/v1/auth`, HttpOnly/Secure/SameSite=Lax. Refresh/logout kiểm tra Origin hoặc fallback Referer khi Origin vắng mặt, đối chiếu `CORS_ORIGINS`; sai/thiếu origin trả 403. Login cũng chặn Origin sai nếu được gửi. Responses auth/profile dùng `Cache-Control: no-store`; logout/logout-all/reset xóa cookie cùng path.

Profile trả `{id,email,display_name,roles,status}`, không chứa hash. PATCH không gửi `display_name` giữ nguyên, `null` xóa tên. Forgot-password trả `{message}` generic, không lộ token hoặc việc tài khoản tồn tại. Register/forgot cần cấu hình SMTP; thiếu cấu hình trả 503.

Password/reset nhận cả token PASSWORD_RESET và ADMIN_INVITATION hợp lệ; lời mời chỉ đặt mật khẩu/xác minh tài khoản PENDING, không mở LOCKED. Token một lần, đúng purpose/hạn, không trả qua response.

Data requests POST dùng `type` chuẩn (alias `request_type` được chấp nhận), reason tùy chọn tối đa 10000 ký tự; trả `{id,user_id,type,reason,status:PENDING,resolution_note:null,created_at,updated_at}`. GET trả `{items,next_cursor}` theo limit/cursor và UUID tăng dần, chỉ của người dùng xác thực. Không nhận user_id/status/resolution_note do người dùng đặt. DELETE là loại yêu cầu xử lý thủ công, không tự xóa dữ liệu hoặc khóa tài khoản.

Rate limit mặc định: login 5 lần sai/60 giây theo IP và email; register/forgot 3 request/3600 giây theo IP; verify/reset 5/60 giây theo IP. 429 có `Retry-After`.

Identity idempotency hiện dùng RAM một process, TTL 24 giờ; không bền vững qua restart/nhiều worker. Scope anonymous dùng email chuẩn hóa/token hash, refresh/Bearer dùng user. Token cookie được tính vào payload; cookie đã đổi với cùng key có thể trả 409. Cache credential responses phải kiểm tra quyền/phiên hiện hành, trả 401 khi stale; dùng key mới cho lần xác thực mới. Chi tiết cấu hình và giới hạn tại [Core README](../../../../services/core/README.md#identity-http-api-task-003).

## Course / Class / Membership — PROPOSED (chưa chốt payload)
**DECIDED:** Chỉ Admin tạo lớp môn học, roster, phân công giáo viên, ghi danh AUTO/MANUAL, archive/restore. Không có join code, join-request, giáo viên tự tạo lớp, teacher invitation/ownership transfer, Student tự leave trong MVP.

**PROPOSED routes:** `POST /admin/homeroom-classes`, `PUT /admin/homeroom-classes/{id}/roster`, `POST /admin/classes`, `PUT /admin/classes/{id}/teaching-assignments`, `POST /admin/classes/{id}/enrollment/preview`, `POST /admin/classes/{id}/enrollment/sync`, `PATCH /admin/classes/{id}/enrollment-mode`, `POST /admin/classes/{id}/members`, `DELETE /admin/classes/{id}/members/{student_id}`, `POST /admin/classes/{id}/archive`, `POST /admin/classes/{id}/restore`.

**PENDING DESIGN:** request/response schema, idempotency bền vững, preview token, thời điểm chuyển lớp, API versioning, event contract. Không xem các route đề xuất là đã triển khai. Endpoint join-request/owner transfer cũ **SUPERSEDED/OUT OF MVP**; không xóa code hoặc migration lịch sử chỉ do thay đổi tài liệu.

## Feed / Comments / Calendar / Notifications
| Method | Endpoint | Quyền / Body |
|---|---|---|
| GET/POST | /classes/{class_id}/posts | ACTIVE member; POST {body} |
| PATCH/DELETE | /classes/{class_id}/posts/{post_id} | Author hoặc lecturer moderation |
| GET/POST | /classes/{class_id}/posts/{post_id}/comments | ACTIVE member; POST {body} |
| PATCH/DELETE | /classes/{class_id}/posts/{post_id}/comments/{id} | Author hoặc lecturer moderation |
| GET | /classes/{class_id}/calendar | ACTIVE member; ?from=ISO&to=ISO |
| POST | /classes/{class_id}/calendar | Owner/Co-lecturer; {title,starts_at,ends_at} |
| PATCH/DELETE | /classes/{class_id}/calendar/{id} | Owner/Co-lecturer; chỉ CORE-origin event |
| GET | /notifications | Authenticated; chỉ của mình, paginated |
| PATCH | /notifications/{id}/read | Recipient → 200 {read:true} |
| POST | /notifications/read-all | Authenticated → 204 |

Soft delete bài đăng/bình luận ẩn khỏi danh sách; archived từ chối hoạt động ghi chung. Deadline LEARNING chỉ đồng bộ qua integration, không chỉnh tại Core.

## Admin / Internal — Identity implemented, Classroom target proposed
| Method | Endpoint | Quyền / Body |
|---|---|---|
| POST | /admin/users | Admin {email,roles} → 201, gửi link đặt mật khẩu |
| PATCH | /admin/users/{id}/status | Admin {status:ACTIVE/LOCKED} + audit |
| PUT | /admin/users/{id}/roles | Admin {roles:[...]} + audit; không xóa Admin cuối |
| GET | /admin/audit-events | Admin; paginated redacted audit |
| GET/PATCH | /admin/data-requests/{id} | Admin; PATCH {status:IN_REVIEW/COMPLETED/REJECTED,resolution_note} |
| GET | /admin/data-requests | Admin; paginated |
| GET | /internal/v1/classes/{class_id}/access?user_id=&action= | Authenticated service scope core:check_access → {allowed,class_id,user_id,action} |

Admin can thiệp lớp cần `X-Admin-Reason` và audit; không tự có quyền xem chat riêng tư. Internal API không chấp nhận browser trực tiếp; fail closed.

Credential nội bộ hiện dùng header `X-Service-Key` so với `INTERNAL_SERVICE_SECRET`, cấp scope `core:check_access`. Không dùng Bearer JWT của người dùng thay service credential; `user_id` chỉ được tin sau khi xác thực service, và endpoint vẫn phải kiểm tra quyền hiện hành/action.

Python public interface Identity cho consumer Core được đặc tả tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004). Admin mutation bắt buộc actor/correlation ID, trả DTO thay ORM và ghi audit cùng transaction; consumer không import model/repository Identity hoặc ghi audit trùng.

## Validation / Contract tests
- **IMPLEMENTED Identity:** email được chuẩn hóa lowercase; mật khẩu 12..128 ký tự. **TARGET Student:** username duy nhất, email không bắt buộc. Post/comment 1..10000, title/name 1..200, starts_at < ends_at. Không expose hash/token.
- Test: unauthorized/cross-school/cross-class, LOCKED/ENDED/ARCHIVED, Admin-only mutations, AUTO/MANUAL concurrency, activation replay, JWT replay/revoke, CSRF, post/comment delete, notification dedup, calendar LEARNING read-only, Admin audit, internal auth.
- FastAPI sinh OpenAPI cho Identity auth/profile/data requests, với request/response/error schemas và snapshot trong test. Các bảng endpoint ngoài Identity vẫn là hợp đồng hành vi, chưa phải bằng chứng triển khai; CI chạy contract test cùng pytest.

## Ghi chú tương thích — phạm vi Lumi THCS/THPT chính khóa
Đối tượng: học sinh khối 6–12 trong lớp chính khóa. Giữ các enum/API role kỹ thuật `ADMIN`, `LECTURER`, `STUDENT` để tương thích code; UI hiển thị Quản trị viên/Giáo viên/Học sinh. Những route hiện được mô tả ở trên là **contract hiện hành hoặc dự kiến**, không phải toàn bộ đã triển khai.

- `POST /auth/register` **IMPLEMENTED — LEGACY**: đang tự đăng ký Student bằng email, **không thuộc MVP** và cần chặn/đổi luồng khi triển khai.
- Lecturer `POST /classes` là **SUPERSEDED DRAFT**, không được triển khai theo quyền Lecturer; chỉ Admin tạo lớp môn học.
- `/classes/join-requests*` là **SUPERSEDED DRAFT/OUT OF MVP**; không dùng mã lớp hoặc teacher approval.
- `DELETE /classes/{class_id}/members/me` là **SUPERSEDED DRAFT/OUT OF MVP**; Student không tự rời lớp.
- Các API quản trị, dữ liệu cá nhân, điểm, quyền và audit tiếp tục phải tuân thủ Business Rules; không tự thêm role Phụ huynh/Admin theo trường.


## API mục tiêu (PROPOSED, chưa triển khai)
- `POST /admin/students/imports/preview` và `POST /admin/students/imports/confirm`: CSV/Excel, phát hiện trùng/lỗi, idempotency và audit; không trả mã kích hoạt trong log.
- `POST /admin/students`, `POST /admin/students/{id}/activation-codes`: Admin cấp username, mã một lần có hạn; phân phối an toàn. `POST /auth/activate`: username + activation_code + new_password; `POST /auth/login`: username/password cho Student, tương thích email cho Lecturer/Admin (chi tiết phiên bản API cần chốt).
- `POST /admin/homeroom-classes`, `POST /admin/homeroom-classes/{id}/roster`, `POST /admin/classes`, `PUT /admin/classes/{id}/teaching-assignments`: chỉ Admin; ràng buộc school scope.
- `POST /admin/classes/{id}/enrollment/preview`, `POST /admin/classes/{id}/enrollment/sync`, `PATCH /admin/classes/{id}/enrollment-mode`, `POST /admin/classes/{id}/members`, `DELETE /admin/classes/{id}/members/{student_id}`: chỉ Admin, đồng bộ AUTO/MANUAL, audit, giữ lịch sử; MANUAL→AUTO phải preview/confirm.
- `POST /admin/classes/{id}/archive`, `POST /admin/classes/{id}/restore`: chỉ Admin.
- Các route `/classes/join-requests*`, `/classes/{id}/co-lecturers/invitations*`, `/classes/{id}/ownership-transfer`, Lecturer `POST /classes`, Lecturer membership mutation, Owner archive/restore, public Student `/auth/register` là **legacy/ngoài phạm vi MVP**; không coi chúng là API được phép phát hành. Không xóa source/migration chỉ vì đổi contract.
- Learning phải có quyền nháp → duyệt/công bố assessment, chấm được phân công → đề xuất/phê duyệt sửa điểm, attempt transfer cutoff; các service dùng access check theo hành động, không dựa độc nhất membership ACTIVE.
- Kiểm thử: cross-school/cross-class, role Admin-only, Student no self-register/join, AUTO/MANUAL, idempotent bulk import, activation token expiry/replay, historical read vs source revoke, transfer attempt, grade approval/audit.
