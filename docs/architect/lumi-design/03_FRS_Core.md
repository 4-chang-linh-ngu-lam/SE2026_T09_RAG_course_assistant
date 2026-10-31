# FRS-CORE — ĐẶC TẢ CHỨC NĂNG CORE VÀ WEB

**Mã:** LUMI-FRS-CORE-001 · **Mốc:** commit 55324dc · **Trạng thái:** Core API đã triển khai; các yêu cầu UI phải kiểm tra lại bằng browser E2E.

## 1. Quy ước mô tả chức năng

Mỗi chức năng có: actor, tiền điều kiện, đầu vào, UI/action, xử lý backend, phản hồi, lỗi, hậu điều kiện và test. **Một route tồn tại hoặc một form hiển thị không đồng nghĩa chức năng đã chạy live.** Mọi kiểm tra quyền phải tại server bằng user hiện hành và school/class scope.

### 1.1 Mã lỗi nhất quán

| HTTP | Khi nào dùng | Hành vi UX |
|---|---|---|
| 400 | Request sai quy tắc/không áp dụng theo contract | Thông báo giá trị sai, không tự retry mutation |
| 401 | Chưa đăng nhập/phiên không còn hợp lệ | Thử refresh một lần theo contract; nếu thất bại yêu cầu login |
| 403 | Actor đã xác thực nhưng không được phép, nếu contract quy định | Hiển thị từ chối, không tiết lộ nội dung |
| 404 | Không tồn tại hoặc che giấu tài nguyên ngoài scope | Không phân biệt resource ngoài trường với không tồn tại |
| 409 | Version stale, trùng hoặc conflict nghiệp vụ | Refresh dữ liệu, yêu cầu user xem lại thay đổi trước confirm |
| 422 | Dữ liệu input không hợp lệ | Chỉ ra field lỗi, giữ input hợp lệ để sửa |
| 429 | Rate-limited | Hiển thị Retry-After, không spam retry |
| 503 | Backend/dependency unavailable | Trạng thái lỗi tạm thời, không giả thành công |

## 2. FRS-C01 — Đăng nhập (`/login`)

- **Actor:** Student dùng username; Lecturer/Admin dùng email.
- **Tiền điều kiện:** tài khoản được tạo, trạng thái và credential hợp lệ.
- **Form:** identifier theo loại tài khoản, password, hành động Đăng nhập; hiển thị lỗi không tiết lộ tài khoản tồn tại hay không.
- **Validation client:** các trường bắt buộc; không trim/lowercase mật khẩu; không gửi đồng thời cả `email` và `username` nếu API yêu cầu đúng một.
- **Server:** `POST /api/v1/auth/login`; kiểm tra password, role/status/school, phát access JWT và refresh HttpOnly cookie. Trả 401 khi sai credential/không đủ điều kiện.
- **Hậu điều kiện:** UI lấy `/users/me`, điều hướng đúng role; không lưu refresh token trong localStorage; xóa state session khi logout.
- **Ngoại lệ:** thiếu/khác Origin ở refresh; đổi status sau khi phát JWT; expired/replayed refresh; lỗi API; rate limiting 429.
- **AC:** TC-001, TC-002, TC-003.

## 3. FRS-C02 — Kích hoạt Student (`/activate`)

- **Actor:** Student chưa kích hoạt; Admin cấp code qua luồng khác.
- **Form:** username, activation code, password mới và xác nhận mật khẩu (xác nhận ở client; server validate chính sách password).
- **API:** `POST /auth/activate` → 204 nếu đúng; token phải đúng purpose, chưa hết hạn, chưa dùng.
- **Hành vi:** sau khi thành công, mời login; không hiển thị code qua query logs, không ghi vào analytics; đánh dấu no-store ở response cấp code.
- **Ngoại lệ:** code cũ/reissued/expired/replay, user LOCKED, username không tồn tại; không tự mở LOCKED.
- **AC:** TC-004.

## 4. FRS-C03 — Cấp tài khoản Student (`/admin/accounts/students/new`)

- **Actor:** Admin ACTIVE, school scope hợp lệ.
- **Form:** username, display_name tùy chọn; nút Tạo; vùng hiển thị code một lần sau thành công; không lưu code vĩnh viễn trong browser.
- **API:** `POST /admin/students` → `student`, `purpose`, `code`, `expires_at`.
- **Server:** kiểm tra username duy nhất; school kế thừa actor; trạng thái pending; lưu code hash + audit.
- **Hậu điều kiện:** Admin bàn giao code qua kênh an toàn; nút cấp lại code chỉ dùng endpoint chuyên biệt với đúng trạng thái.
- **Ngoại lệ:** username trùng, actor không Admin, thiếu school scope, double click; không dùng Idempotency-Key cho API trả credential nhạy cảm nếu contract cấm.
- **AC:** TC-005, TC-006.

## 5. FRS-C04 — Tài khoản nhân sự / quản lý user (`/admin/accounts`)

- **Actor:** Admin trong cùng trường.
- **Danh sách:** phân trang bằng cursor, lọc account_type/role/status/search; thông tin trả về không có password/token/hash; lựa chọn row mở chi tiết.
- **API:** `GET /admin/users`, `POST /admin/users`, `PATCH /admin/users/{id}`, hoặc status/role endpoint tương thích.
- **Form tạo staff:** email, display_name, roles trong ADMIN/LECTURER; không tạo Student qua staff flow. Invitation qua SMTP, frontend hiển thị delivery status, không yêu cầu token từ API.
- **Edit:** gửi `expected_revision` trên PATCH atomically; stale 409 → fetch lại và thông báo khác biệt; khóa/gỡ role thu hồi session; không khóa/gỡ Admin ACTIVE cuối nếu ràng buộc không cho phép.
- **Ngoại lệ:** cross-school 404; staff thiếu email; roles rỗng/trùng, locked user; email provider lỗi không đồng nghĩa DB rollback sau khi đã commit.
- **AC:** TC-007, TC-008.

## 6. FRS-C05 — Student import (`/admin/imports/new`)

- **Actor:** Admin.
- **Bước 1:** chọn CSV UTF-8 hoặc XLSX; chỉ cho các định dạng hỗ trợ; chọn mapping cột username/display_name/user_id khi cần. Không phỏng đoán user_id legacy.
- **Bước 2 (Preview):** `POST /admin/students/imports/preview` với `format`, `content_base64`, cột mapping và tùy chọn homeroom. Hiển thị từng dòng valid/error, số lượng hợp lệ, thời điểm hết hạn preview.
- **Bước 3 (Confirm):** chỉ khi preview hợp lệ/không hết hạn, gọi `POST /admin/students/imports/confirm` bằng `preview_id`.
- **Bước 4 (Reconcile):** nếu timeout/unknown response, gọi `GET /admin/students/imports/{preview_id}` thay vì blind confirm lại; hiển thị `COMPLETED/replayed` và line outcomes.
- **Validation:** không chấp nhận formula nguy hiểm, duplicate header, file vượt ngưỡng theo API; tránh log base64 dữ liệu học sinh.
- **Ngoại lệ:** file lỗi/duplicate/row conflict/stale preview, resume sau timeout, DB rollback; không tự tạo school hoặc tự activate legacy student.
- **AC:** TC-009, TC-010.

## 7. FRS-C06 — Quản lý catalog và lớp hành chính (`/admin/catalog`, `/admin/homerooms`)

- **Actor:** Admin.
- **Đọc:** `GET /admin/catalog` → courses, academic years, semesters, homerooms, grades; roster counts không phải danh sách cá nhân.
- **Tạo môn:** `POST /admin/courses` với code, name.
- **Tạo homeroom:** `POST /admin/homeroom-classes` với name, academic_year, grade_level 6–12.
- **Roster detail:** `GET /admin/homeroom-classes/{id}/roster`; cập nhật bằng `PUT` với `student_ids` và `expected_roster_version`; transfer có expected source/destination versions.
- **Validation:** khối chỉ 6–12; không gán học sinh không thuộc trường; thông tin năm học phù hợp theo schema; không sửa dữ liệu ngoài trường.
- **Ngoại lệ:** roster conflict 409, chuyển cùng năm/khối không hợp lệ, cập nhật đụng độ; UI không được overwrite câm lặng.
- **AC:** TC-011, TC-012.

## 8. FRS-C07 — Tạo và cấu hình lớp môn học (`/admin/classes/new`)

- **Actor:** Admin.
- **Form:** course, class name, academic year, semester, grade, homeroom tùy chọn, AUTO/MANUAL, PRIMARY Lecturer và ASSISTING lecturers tùy chọn.
- **API:** `POST /admin/classes`; tạo class cùng assignments trong một transaction; `GET /admin/classes/{id}/management` cho thông tin quản trị sau khi tạo.
- **Validation:** giáo viên cùng trường và ACTIVE, PRIMARY bắt buộc theo contract; AUTO cần liên hệ homeroom hợp lệ; ghi danh không thay đổi bằng trực tiếp từ Student.
- **Ngoại lệ:** course/homeroom không hợp scope, lecturer sai/không ACTIVE, mode không phù hợp; 404/409/422 theo contract.
- **AC:** TC-013, TC-014.

## 9. FRS-C08 — AUTO/MANUAL và transfer (`/admin/classes/:classId/enrollment`)

- **AUTO:** Admin gọi preview, xem danh sách add/end và `class_version`/`roster_version`, sau đó confirm sync với version; stale 409 phải preview lại.
- **MANUAL:** thêm, xóa (kết thúc episode), thay cả roster bằng API Admin; không xóa hard lịch sử để “đơn giản hóa”.
- **Đổi mode:** `PATCH /admin/classes/{id}/enrollment-mode`; từ MANUAL→AUTO phải có version theo preview.
- **Transfer:** homeroom transfer đồng bộ AUTO trong transaction; class MANUAL transfer phải kiểm tra cùng môn/năm/học kỳ theo Core contract.
- **Hậu điều kiện:** nhận membership mới, lịch sử cũ tồn tại; access tới hoạt động mới của lớp cũ phải bị revoke; lịch sử kết quả cá nhân do Learning xử lý về sau.
- **AC:** TC-015, TC-016.

## 10. FRS-C09 — Teaching assignments và vòng đời lớp

- **Actor:** Admin.
- **API:** `PUT /admin/classes/{id}/teaching-assignments`, `POST /admin/classes/{id}/archive`, `/restore` với expected class version.
- **Quy tắc:** PRIMARY không bị bỏ trống khi thay; ASSISTING có quyền hoạt động giảng dạy nhưng không sửa roster/giáo viên; archive chặn tạo hoạt động mới, restore kiểm tra quyền hiện hành.
- **UI:** trang lifecycle hiển thị ACTIVE/ARCHIVED, cảnh báo tác động trước confirm, hiển thị lý do lỗi version stale.
- **AC:** TC-017, TC-018.

## 11. FRS-C10 — Danh sách và chi tiết lớp

- **Actors:** Admin, Lecturer, Student.
- **API:** `GET /classes`, `/classes/{id}`, `/classes/{id}/members`.
- **Rule:** Student chỉ lớp membership hiện hành; Lecturer chỉ assignment hiện hành; Admin trường mình. `teaching_role` của student/admin null; không dùng thông tin ở browser để thay quyền.
- **Hậu điều kiện:** lớp archived có trạng thái chỉ đọc theo policy; quyền đọc lịch sử cá nhân được xử lý tách khỏi quyền lớp mới.
- **AC:** TC-019.

## 12. FRS-C11 — Feed và Comments

- **Giao diện lập trình (API):** Các đường dẫn dưới đây đều có tiền tố `/api/v1` và bắt buộc xác định đúng lớp, bài đăng liên quan:
  - `GET /classes/{class_id}/posts`: lấy danh sách bài đăng trong lớp.
  - `POST /classes/{class_id}/posts`: tạo bài đăng mới.
  - `PATCH /classes/{class_id}/posts/{post_id}`: chỉnh sửa bài đăng.
  - `DELETE /classes/{class_id}/posts/{post_id}`: xóa mềm bài đăng theo quyền hiện hành.
  - `GET /classes/{class_id}/posts/{post_id}/comments`: lấy danh sách bình luận của bài đăng.
  - `POST /classes/{class_id}/posts/{post_id}/comments`: tạo bình luận.
  - `PATCH /classes/{class_id}/posts/{post_id}/comments/{comment_id}`: chỉnh sửa bình luận.
  - `DELETE /classes/{class_id}/posts/{post_id}/comments/{comment_id}`: xóa mềm bình luận theo quyền hiện hành.
  - Quyền truy cập, dữ liệu yêu cầu/phản hồi và mã lỗi tuân theo [Hợp đồng API Core](../microservices-v1/core/API_CONTRACT.md), không có đường dẫn rút gọn ngoài phạm vi lớp.
- **Vai trò:** thành viên hiện hành đọc/bình luận; tác giả còn quyền sửa; moderator có quyền ẩn/xóa theo rule; Student không thể quản trị nội dung người khác.
- **Validation:** body bắt buộc, length theo backend schema; không tự đặt max length trong FRS nếu chưa xác nhận Pydantic; sanitize nội dung hiển thị để chống XSS.
- **Trạng thái:** optimistic update chỉ khi rollback được; soft-delete không trả body mới; archived/read-only chặn POST/PATCH/DELETE theo action.
- **AC:** TC-020, TC-021.

## 13. FRS-C12 — Calendar

- **API:** `GET /classes/{id}/calendar?from=&to=&limit=&cursor=`, `POST /classes/{id}/calendar`, `PATCH/DELETE /classes/{id}/calendar/{event_id}`.
- **Form:** title, description?, starts_at, ends_at; server bắt buộc starts_at trước ends_at.
- **Quyền:** PRIMARY/ASSISTING hiện hành chỉ thay CORE-origin event; Student đọc; LEARNING-origin deadline chỉ là bản chiếu và không sửa qua Core calendar API.
- **AC:** TC-022.

## 14. FRS-C13 — Notifications

- **API:** `GET /notifications`, `PATCH /notifications/{id}/read`, `POST /notifications/read-all`.
- **UI:** chỉ hiện thông báo mình; unread_count; click notification luôn kiểm tra lại quyền tài nguyên đích; mark read có thể gọi lặp an toàn.
- **Backend:** sự kiện có snapshot recipient tại thời điểm mutation; outbox V2, worker dedup/retry, V1 legacy không fallback sang audience hiện tại.
- **AC:** TC-023, TC-024.

## 15. FRS-C14 — Audit & Data Requests

- **Actor:** Admin cùng trường hoặc owner request của chính họ.
- **Self-request:** `GET/POST /users/me/data-requests`, type ACCESS/EXPORT/CORRECTION/DELETE; lý do tùy chọn; không được đặt status/resolution_note của mình.
- **Admin list/review:** `GET /admin/data-requests`, `GET/PATCH /admin/data-requests/{id}`; audit `GET /admin/audit-events` theo scope.
- **Quy tắc:** identity_verified chỉ là xác nhận kiểm tra thủ công; status COMPLETED cần executor và evidence đúng loại; DELETE/retention xuyên service vẫn deferred. Không hiển thị hoàn tất giả.
- **UI:** phân biệt trạng thái PENDING/IN_REVIEW/REJECTED/COMPLETED thực; trường resolution_note dùng mã theo contract, không copy raw lý do nhạy cảm vào audit.
- **AC:** TC-025, TC-026.

## 16. FRS-C15 — Browser session, proxy và khả dụng

- **Frontend:** Next.js API proxy same-origin, Web live adapter, production không cho mock.
- **Access:** Bearer/refresh cookie theo contract; proxy chỉ cho phép route/method đã khai báo, forward query/header allowlist; Origin check cho mutation.
- **UI states:** loading, empty, forbidden, deleted, not found, conflict stale, backend 503, offline, retry unknown mutation, success receipt.
- **Giới hạn:** Browser build PASS chưa đủ; cần E2E trên PostgreSQL có dữ liệu tổng hợp và worker thật, bao gồm Admin→Lecturer→Student.
- **AC:** TC-027–TC-030.

## 17. Ma trận quyền chức năng cốt lõi

| Action | Admin | Lecturer PRIMARY | Lecturer ASSISTING | Student |
|---|---|---|---|---|
| Cấp user, import, status/roles | Có trong trường | Không | Không | Không |
| Tạo subject class, roster, transfer | Có | Không | Không | Không |
| Archive/restore | Có | Không | Không | Không |
| Tạo/sửa Core calendar | Theo quyền trường và contract | Có khi đang assigned | Có khi đang assigned | Không |
| Sửa post của mình | Nếu là tác giả & còn quyền | Nếu là tác giả & còn quyền | Nếu là tác giả & còn quyền | Nếu là tác giả & còn quyền |
| Moderation comment người khác | Theo quyền và audit | Trong lớp được giao | Trong lớp được giao theo policy | Không |
| Xem notification | Chỉ notification của mình | Chỉ của mình | Chỉ của mình | Chỉ của mình |
| Phê duyệt Assessment chính thức | Không mặc định (chỉ can thiệp ngoại lệ được duyệt) | Có, tương lai | Không | Không |

> Ma trận là tóm lược. Khi code, action-based Core policy và Business Rules có quyền ưu tiên hơn bảng này.

## 18. Tiêu chí không được tự coi là hoàn thành

- Tài liệu `FRONTEND_COMPLETION` ghi pass mock không chứng minh API live.
- Kết quả frontend route smoke không chứng minh dữ liệu post/notification/role isolation.
- Chưa có API Document/Learning/Intelligence → các page tương ứng chỉ hiển thị trạng thái chưa khả dụng.
- Không tự lập API AI khi thiếu contract; không dùng feature flag frontend thay quyền ở server.