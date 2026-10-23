# Rà soát kết nối Web–Core — 22/10/2026

> Cập nhật sau sửa lỗi: F1–F4 và sai khác quyền sửa bài đã được xử lý; xem [bằng chứng bảo mật](CORE_SECURITY_FIXES_2026-10-22.md). Người dùng đã duyệt ba API Notifications: inbox đã nối live và worker Compose đã bổ sung; lỗi thời gian/class context của lịch và metadata lỗi HTTP đã sửa, xem [follow-up](CORE_INTEGRATION_FOLLOWUP_2026-10-22.md). Phần phát hiện bên dưới giữ lại snapshot trước sửa. Các API ngoài Identity/Notifications vẫn cần chốt hợp đồng.

Phạm vi: toàn bộ transport/proxy/decoder/session Identity đang kết nối; các port, live adapter và mô hình UI liên quan Core; router/schema backend cho Identity, Classroom, Social, Calendar, Notifications, Administration; OpenAPI của Core đang chạy. Người rà soát: Codex. Nhánh `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8`, cộng các thay đổi backend chưa commit có sẵn.

Kết quả: request/response Identity đang nối không có lệch tên trường hoặc status thành công trong các kiểm tra bên dưới. Có hai lỗi xử lý phiên tái hiện được, vấn đề rate limit qua proxy, và nhiều khoảng trống/mâu thuẫn cần giải quyết trước khi nối các module Core còn lại. Đợt này chỉ thêm tài liệu kiểm tra; không sửa logic, schema, permission, Business Rules hoặc dữ liệu DB.

## 1. Đường đi và mức độ kết nối

Browser gọi cùng origin `http://localhost:3000/api/v1/...` → Next route handler → `createCoreProxy` → `http://localhost:8000/api/v1/...` → router Core. `CORE_API_URL` ở server; access token ở bộ nhớ; refresh token ở cookie HttpOnly, path `/api/v1/auth`. Local dùng `COOKIE_SECURE=false`, `WEB_ORIGIN=http://localhost:3000` và cùng giá trị trong `CORS_ORIGINS`.

OpenAPI hiện có **59 operation HTTP / 79 schema**:

| Nhóm | Operation backend | Trạng thái frontend |
|---|---:|---|
| Health | 2 | Gọi trực tiếp Core, không qua proxy sản phẩm |
| Identity | 15 | 14 operation trong allowlist; 13 được gọi trong live Identity adapter; verify-email chưa có method trên port; register cố ý chặn |
| Classroom | 17 | `blocked-contract`: live port trả unavailable |
| Internal access check | 1 | Chỉ service-to-service; không mở cho browser |
| Social Feed / Comments / Calendar | 12 | `blocked-contract`: live port/workspace trả unavailable |
| Notifications | 3 | `blocked-contract`: live port/workspace trả unavailable |
| Administration | 9 | `blocked-contract`: live Accounts port trả unavailable |

41 operation public ngoài Identity đã có trong backend nhưng chưa nối live. Đây là khoảng trống tích hợp có chủ đích trong code hiện tại, không phải 41 request frontend đang gửi sai. [integrations.ts](../src/lib/data/integrations.ts), [live.ts](../src/lib/data/live.ts), [operations.ts](../src/lib/api/operations.ts).

Document, AI, Learning và Learner Intelligence là các service riêng, không phải module Core. Frontend hiện cũng để các capability này unavailable; ma trận này không tạo hoặc phê duyệt endpoint cho chúng.

## 2. Phát hiện có tác động hiện tại

### F1 — P2: Đăng xuất mọi thiết bị thất bại khi access token hết hạn

Trigger: đăng nhập, để access token hết hạn (mặc định 15 phút), rồi chọn “Đăng xuất mọi thiết bị” mà chưa có thao tác bảo vệ nào refresh token.

`logout(true)` chụp token hiện tại, xóa trạng thái bộ nhớ và gọi thẳng `http(captured)('logoutAll')`; nó không đi qua nhánh kiểm tra hạn/refresh của `authenticated`. Backend yêu cầu Bearer còn hiệu lực và trả 401 trước khi `logout_all` thu hồi các phiên. SessionProvider vẫn chuyển local sang signed-out trong `finally`; các thiết bị khác chưa được thu hồi bởi request thất bại đó.

Bằng chứng: mô phỏng đồng hồ với access hạn 1 giây cho kết quả `401`, **0 refresh request**, trace `login → me → logout-all`. Đây là kiểm tra state machine bằng transport giả, không phải đăng nhập tài khoản DB thật.

Nguồn: [live-identity.ts](../src/lib/data/live-identity.ts#L52), [session-provider.tsx](../src/components/session-provider.tsx), [router.py](../../../services/core/app/modules/identity/router.py#L268), [auth_dependencies.py](../../../services/core/app/common/auth_dependencies.py).

Hướng xử lý: bảo đảm token hợp lệ trước lệnh logout-all, vẫn serialize credential operations và giữ ranh giới generation; phân biệt local sign-out với xác nhận đã revoke mọi phiên. Cần test expired-token và response đến sau login mới.

### F2 — P2: “Kiểm tra phiên đăng nhập” không đối soát sau login unknown

Trigger: login có thể đã đặt cookie nhưng response bị mất/sai schema. `decodeMutation` đánh dấu `unknown`; catch của `login` đặt `suspended=true`. Nút “Kiểm tra phiên đăng nhập” gọi `session.reload()` → `identity.restore()`, nhưng `restore` gặp suspended và trả null ngay, không thử refresh/me.

Bằng chứng: response login sai schema tạo `CONTRACT_MISMATCH / unknown`; gọi restore tiếp theo trả null với **0 request refresh**. Transport giả đã chuẩn bị response refresh/profile hợp lệ nhưng không được gọi.

Nguồn: [live-identity.ts](../src/lib/data/live-identity.ts#L61), [auth-view.tsx](../src/features/identity/auth-view.tsx#L333).

Hướng xử lý: có thao tác đối soát credential rõ ràng sau unknown, không đồng nhất trạng thái đó với explicit logout/revocation; giữ kiểm tra generation để không khôi phục actor cũ.

### F3 — P2: Rate limit theo IP bị gom vào địa chỉ của Next proxy

Core lấy `request.client.host`; Next không truyền một danh tính client đã được xác minh, và Uvicorn chạy với `--no-proxy-headers`. Với topology hiện tại, Core thấy peer của Next thay vì IP riêng từng browser. Limiter có bucket `login_ip` độc lập với bucket identifier: 5 lần sai từ những tài khoản khác nhau chung peer có thể chặn tài khoản tiếp theo bằng 429 trong cùng cửa sổ 60 giây. Forgot/activate/reset cũng có limit theo peer.

Bằng chứng: đối tượng RateLimiter riêng trong bộ nhớ, 5 account giả thất bại chung peer → account giả khác bị 429 trước authentication. Việc gom peer là suy luận từ đường proxy/TCP và cấu hình Uvicorn; chưa chạy thử nhiều browser/IP thực.

Nguồn: [proxy.ts](../src/lib/api/proxy.ts#L35), [http_security.py](../../../services/core/app/modules/identity/http_security.py#L49), [rate_limit.py](../../../services/core/app/modules/identity/rate_limit.py#L58), [Dockerfile](../../../services/core/Dockerfile).

Hướng xử lý cần thiết kế trusted proxy/client identity; không đơn giản tin `X-Forwarded-For` do browser gửi và không tắt rate limit.

### F4 — P3: Error do Next tạo thiếu correlation ID

Core trả `{error:{code,message,correlation_id}}` và `X-Correlation-ID`. `failure()` của proxy chỉ tạo `{error:{code,message}}`, không có header correlation. Lỗi cấu hình, Origin, path không allowlist hoặc upstream unavailable vì vậy thiếu mã đối soát mà một số màn hỗ trợ hiển thị. Frontend vẫn xử lý lỗi được; hạn chế nằm ở truy vết.

Nguồn: [proxy.ts](../src/lib/api/proxy.ts#L3), [errors.py](../../../services/core/app/common/errors.py), [data-requests.tsx](../src/features/identity/data-requests.tsx).

## 3. Xung đột tài liệu và điều kiện mở tích hợp

`docs/architect/microservices-v1/core/API_CONTRACT.md` vẫn ghi Classroom/Social/Notifications/Admin là PROPOSED; `BUSINESS_RULES.md` phần điều kiện triển khai vẫn ghi Classroom chưa triển khai. Trong khi đó bootstrap, router/schema, migrations 0008–0012 và Core README mô tả implementation mới. Frontend registry/allowlist vẫn theo hợp đồng cũ.

Đây là mâu thuẫn trạng thái giữa tài liệu và implementation, chưa đủ căn cứ coi router mới là contract đã được duyệt. Không tự đổi Business Rules hoặc bật tất cả route. Cần owner Core cập nhật/chốt public contract và frontend đồng bộ phần tương ứng. [API_CONTRACT.md](../../../docs/architect/microservices-v1/core/API_CONTRACT.md), [BUSINESS_RULES.md](../../../docs/architect/BUSINESS_RULES.md), [bootstrap.py](../../../services/core/app/bootstrap.py).

Proxy hiện chỉ export GET/POST/PATCH; allowlist chỉ Identity; header forward không có `X-Admin-Reason` hoặc `Idempotency-Key`; query chỉ chuyển `cursor/limit` cho self data requests. Các API mới dùng PUT/DELETE, reason code, lọc calendar/audit sẽ chưa đi qua được. Đây là ranh giới hiện có; mở một endpoint phải bổ sung method/headers/query cụ thể cùng decoder/test, không mở wildcard. [route.ts](../app/api/v1/%5B...path%5D/route.ts), [proxy.ts](../src/lib/api/proxy.ts).

Ngoài ra, Classroom kiểm tra `X-Admin-Reason` thủ công bằng `request.headers`, nên OpenAPI chưa liệt kê header bắt buộc cho các mutation đó. Body schema/OpenAPI đơn thuần chưa mô tả đủ contract. Administration đã khai báo header này qua dependency.

## 4. Identity: frontend gửi gì, backend trả gì

Các path trong bảng có prefix `/api/v1`. `?` là field tùy chọn; refresh cookie không phải JSON body. Tất cả 14 operation khớp method/path/status của OpenAPI đang chạy; success có xác thực đầy đủ vẫn cần DB journey riêng.

| Method / path | Frontend gửi | Backend trả |
|---|---|---|
| POST `/auth/login` | `{username,password}` Student **hoặc** `{email,password}` staff; không gửi cả hai | 200 `TokenResponse` + Set-Cookie refresh |
| POST `/auth/refresh` | Cookie refresh + Origin; không JSON body | 200 `TokenResponse` + cookie xoay vòng |
| POST `/auth/logout` | Cookie refresh + Origin; không JSON body | 204, xóa cookie |
| POST `/auth/logout-all` | Bearer; không JSON body | 204, revoke mọi phiên + xóa cookie |
| POST `/auth/activate` | `{username,activation_code,new_password}` | 204, xóa cookie; chưa tự login |
| POST `/auth/verify-email` | Contract nhận `{token}`; operation có trong allowlist nhưng chưa có method/UI gọi | 200 `{verified:true}` |
| POST `/auth/password/forgot` | `{email}` staff | 200 `{message}` generic; thiếu SMTP trả 503; UI bỏ body và hiển thị thông báo generic |
| POST `/auth/password/reset` | `{token,new_password}`; reset và nhận lời mời cùng dùng endpoint này | 204, xóa cookie và thu hồi phiên liên quan |
| GET `/users/me` | Bearer | 200 `UserProfile` |
| PATCH `/users/me` | Bearer + `{display_name:string|null}` | 200 `UserProfile`; null xóa tên |
| GET `/users/me/data-requests` | Bearer; client hiện gửi cursor, backend nhận thêm limit | 200 `{items:DataRequest[],next_cursor:string|null}` |
| POST `/users/me/data-requests` | Bearer + `{type,reason?}` | 201 `DataRequest` với trạng thái PENDING |
| POST `/admin/students` | Bearer Admin + `{username,display_name?}` | 201 `StudentCodeResponse`; mã chỉ trả một lần |
| POST `/admin/students/{user_id}/activation-codes` | Bearer Admin + `{}` hoặc `{identity_verified:true}` | 200 `StudentCodeResponse`; pending → ACTIVATION, ACTIVE đã xác minh → PASSWORD_RESET |

Các DTO frontend đang decode:

```text
TokenResponse = {access_token:string, token_type:"bearer", expires_in:number}
UserProfile = {id,email:string|null,username:string|null,school_id:string|null,
               display_name:string|null,roles:(STUDENT|LECTURER|ADMIN)[],status}
DataRequest = {id,user_id,type:ACCESS|EXPORT|CORRECTION|DELETE,reason:string|null,
               status:PENDING|IN_REVIEW|COMPLETED|REJECTED,
               resolution_note:string|null,created_at,updated_at}
StudentCodeResponse = {student:{id,email,username,school_id,display_name?,status},
                       purpose:ACTIVATION|PASSWORD_RESET,code,expires_at}
```

Backend Student summary thực tế luôn serialize display_name; decoder frontend bỏ field đó vì IssuedCode không cần. Không phải lỗi schema. Backend profile serialize cả field nullable/default nên decoder yêu cầu field hiện diện vẫn tương thích.

Quy tắc: mật khẩu mới 12–128 ký tự; username 1–200, trim/lowercase, không whitespace/@; reason tối đa 10000; display_name null hoặc 1–200. Student create/issue-code/activate không được gửi `Idempotency-Key`. Access token không chứa refresh token; login sau token còn gọi `/users/me` lấy actor thực.

## 5. Những mô hình chưa thể nối thẳng vào API backend

Các port dưới đây hiện là **view model/preview contract**, chưa phải wire DTO. Lệch shape chưa gây request sai ở live vì các capability đang unavailable.

| Luồng | Frontend mong đợi | Backend thực tế / phần thiếu |
|---|---|---|
| Tạo lớp | `courseId,yearId,semesterId,grade,homeroomId,mode,primaryTeacherId,...` | `course_id,academic_year:string,semester:string,grade_level,homeroom_class_id,enrollment_mode,primary_lecturer_id,name`; cần ánh xạ cả ID ↔ nhãn năm/học kỳ |
| Đọc lớp | `ManagedClass` có summary/code/metadata, teachers, members, revision, manualIncludes/Excludes | `ClassResponse` chỉ có ID tham chiếu, name, grade_level, enrollment_mode, status, version; members nằm API khác; chưa có GET teaching-assignments/course/year/semester catalog để hydrate toàn bộ UI hiện tại |
| Sửa lớp | Một save gồm name + primary/assisting teachers | Backend có PUT teaching-assignments; chưa có HTTP sửa tên lớp |
| Roster/lớp hành chính | Load toàn workspace, previewId → confirm, expected revision | Backend có create homeroom, PUT roster `{student_ids}`, transfer; chưa có HTTP list/detail homeroom/roster hoặc durable previewId cho roster |
| AUTO enrollment | `{previewId,reason}` → preview APPLIED; reconcile bằng previewId | Backend preview trả `{class_id,target_mode,class_version,roster_version,add_student_ids,end_student_ids}`; PATCH nhận `{mode,expected_class_version?,expected_roster_version?}`. Không có previewId/server receipt để cast trực tiếp |
| Membership | UI còn `source:OVERRIDE`, manualIncludes/manualExcludes | Backend source chỉ AUTO/MANUAL; không có cùng semantics override trong contract hiện tại |
| Tài khoản Admin | `ManagedAccount` gồm roles, revision, legacy, lastAdmin; update roles/status trong một operation | Backend PATCH status trả 204; PUT roles trả UserSummaryDTO không có roles/revision; hai request/transaction riêng. Chưa có HTTP list/detail user, expected revision hoặc một mutation atomic gộp cả hai |
| Mời staff | `{email,displayName,roles}` → `{invitation,code}`, có resend/revoke/list | Backend POST `/admin/users` nhận `{email,roles}` + reason header, gửi SMTP và trả UserSummaryDTO; **không trả raw invitation code**. Chưa có API list/resend/revoke invitation. Không sửa backend để lộ code chỉ nhằm khớp UI preview |
| Import preview | `{file:{filename,headers,rows},mapping}` → `ImportJob` | Backend nhận `{format:CSV|XLSX,content_base64,homeroom_class_id?}` → `{valid,preview_id,expires_at,items,errors}`. Tối đa 100 dòng, file 2 MB; cần giữ/chuyển đổi bytes theo contract và hiển thị row errors |
| Import confirm | `{importId,revision,reason}` → `ImportJob`; reconcile importId | Backend `{preview_id}` + reason header → `{preview_id,status:COMPLETED,replayed,items}`. Codes chỉ có lần disclosure đầu, replay code null; không có GET ImportJob. Không dùng retry như một lần cấp mã mới |
| Feed/comments | `content,authorId,authorName,authorRole,createdAt,comments[]` | Request `{body}`; response `{id,class_id/post_id,author:{id,display_name},body,created_at,updated_at}`. Comments tải API riêng/phân trang. Backend cố ý không trả email/role tác giả; cần quyết định cách hiển thị badge, không tự gán vai trò |
| Quyền sửa post | UI dùng `isTeacher || isAuthor` cho cả nút sửa và xóa | Backend PATCH chỉ tác giả được sửa; giáo viên có quyền moderation DELETE không đồng nghĩa được sửa bài người khác. Nối live nguyên UI sẽ hiện nút sửa dẫn tới 403 |
| Calendar | `{classId,date,start,timeRange,category,location,...}`; update/delete chỉ nhận eventId | Backend path cần class_id + event_id; body `{title,description?,starts_at,ends_at}` có timezone và start < end. Response có `origin:CORE|LEARNING,external_ref`. UI hiện hardcode start `07:00Z`, không lấy giờ đã nhập làm start/end, không có end bắt buộc; update không mang classId. Cần port/context + datetime mapping, không bỏ trường hoặc tự đặt end |
| Notifications | `title,content,isRead,category,targetHref,...` | `{items:[{id,type,payload_json,read,created_at}],unread_count,next_cursor}`; PATCH read → `{id,read:true}`, read-all → 204. Cần map type/payload sang nội dung/route an toàn, không xem payload là quyền mở tài nguyên |
| Xử lý yêu cầu dữ liệu Admin | Preview UI có thể thể hiện copy/file và kết quả COMPLETED | Backend chỉ nhận enum reason note và identity_verified; yêu cầu COMPLETED hiện trả IN_REVIEW/POLICY_PENDING khi chưa có policy/executor. Không báo hoàn tất dựa riêng trên 200 hoặc trạng thái đã gửi |

Nguồn mô hình frontend: [classroom-admin.ts](../src/lib/classroom-admin.ts), [accounts.ts](../src/lib/accounts.ts), [domain.ts](../src/lib/domain.ts), [port.ts](../src/lib/data/port.ts), [feed.tsx](../src/features/social/feed.tsx#L206), [calendar.tsx](../src/features/social/calendar.tsx#L188).

Nguồn backend: [Classroom schemas](../../../services/core/app/modules/classroom/schemas.py), [Administration schemas](../../../services/core/app/modules/administration/schemas.py), [Social schemas](../../../services/core/app/modules/social), [Notification schemas](../../../services/core/app/modules/notification/schemas.py), [data resolution](../../../services/core/app/modules/identity/admin_public.py#L230).

## 6. Cấu hình/runtime còn thiếu

Compose hiện chỉ khai báo `db,migrate,core,web`; chưa có `notification-worker`, dù Core README ghi worker tự chạy trong Compose. Nếu nối inbox lúc này mà không chạy worker riêng, outbox sẽ không được worker này chuyển thành thông báo. Đây là khoảng trống vận hành, tách biệt việc map DTO. [compose.yaml](../../../compose.yaml), [README](../../../services/core/README.md).

SMTP chưa được cấu hình trong setup local của phiên làm việc này; staff forgot/invitation chưa sẵn sàng gửi email. Database local mới chưa seed tài khoản; chưa có bằng chứng đăng nhập thành công, cookie rotation hoặc mutation DB xuyên frontend–Core bằng tài khoản thật. Health 200 không thay thế các bằng chứng đó.

## 7. Bằng chứng đã chạy trong đợt rà soát

| Kiểm tra | Kết quả / giới hạn |
|---|---|
| `node --import tsx --test --test-reporter=dot tests/integration-boundary.test.ts tests/live-session.test.ts` trong apps/web | Exit 0; 23 test có sẵn. Đây là test transport/state machine, không chứng nhận DB journey |
| So operation allowlist với OpenAPI live | 14/14 khớp method/path/success status |
| Decoder frontend đọc JSON từ Pydantic backend chạy trong Core container | 5/5: UserProfile, TokenResponse, StudentCodeResponse, DataRequestResponse, Page; chỉ dùng giá trị synthetic |
| Validate request mẫu bằng schema backend | 10 payload mẫu hợp lệ: Student/staff login, activation, create Student, issue code false/true, reset, forgot, data request, nullable profile |
| GET không xác thực vào Core và Next đang chạy | users/me cùng trả 401 và giữ correlation; classes/notifications/admin audit trả 401 ở Core, 404 ở Next, lỗi Next thiếu correlation. Không đọc dữ liệu tài khoản |
| Mô phỏng token hết hạn → logout-all | Tái hiện 401, 0 refresh |
| Mô phỏng login unknown → restore | Tái hiện null, 0 refresh |
| RateLimiter riêng trong bộ nhớ | Tái hiện shared-peer bucket chặn account khác sau 5 lần sai |
| `docker compose config --services` | db, migrate, core, web; không có worker |

Không chạy lại build sản phẩm trong đợt chỉ đọc code/thêm docs này. Build live và toàn bộ 226 test đã đạt ở bước setup trước; các kết quả đó không chứng minh hai edge case mới phát hiện. Không có browser được kết nối để kiểm thử tương tác UI trong đợt audit. Không tạo/sửa/xóa tài khoản hoặc dữ liệu nghiệp vụ để tạo bằng chứng.

## 8. Thứ tự xử lý đề xuất

1. Sửa F1/F2 cùng test hồi quy; thống nhất trusted client identity cho F3; bổ sung correlation cho lỗi proxy.
2. Chốt/cập nhật tài liệu hợp đồng Core theo implementation hiện tại trước khi mở module mới. Nêu rõ API/field thiếu thay vì tự bổ sung semantics từ fixture.
3. Nối từng slice với wire decoder và mapping view model: class list/detail → account/catalog data cần thiết → roster/teachers/enrollment → feed/comments → calendar → notifications → administration/import. Capability chưa đủ API tiếp tục unavailable.
4. Thiết lập Admin dev theo runbook, SMTP test và notification worker; chạy browser + PostgreSQL journey thật cho từng slice, gồm 401/403/404/409/422/429 và mutation unknown. Không dùng green mock test hoặc HTTP 200 làm xác nhận tác vụ nghiệp vụ.

Danh sách đầy đủ **59 operation**, request body, success response, parameters, auth và **79 schema/field/ràng buộc** nằm trong [CORE_API_MATRIX_2026-10-22.md](CORE_API_MATRIX_2026-10-22.md). Ma trận là kiểm kê implementation, không thay thế API_CONTRACT được owner duyệt.
