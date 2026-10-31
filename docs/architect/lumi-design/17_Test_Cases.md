# TEST CASES & TEST SCENARIOS — CHI TIẾT THỰC THI

**Mã:** LUMI-TC-001 · **Phiên bản:** 1.0-DRAFT · **Tất cả trạng thái dưới đây đều là KẾ HOẠCH**, không phải kết quả test đã chạy.

## Hướng dẫn dùng

- Mỗi test có ID duy nhất, nguồn FR/NFR, tiền điều kiện, dữ liệu, bước và expected. `CORE` nghĩa backend Core được ghi nhận đã triển khai nhưng **case vẫn cần chạy trên revision mục tiêu**; `PROPOSED` nghĩa future service chưa có để chạy.
- Khi chạy, bổ sung: result PASSED/FAILED/BLOCKED/NOT RUN, source SHA, browser/OS, PostgreSQL migration, seed fixture, log artifact và issue nếu failed.
- Không lưu token/password thật trong screenshot/CI artifacts.
- Với `PENDING DECISION` không tự biến behavior chưa duyệt thành expected có thể nghiệm thu.


## Core MVP — hiện có backend, E2E vẫn cần chạy


### TC-001 — Student đăng nhập username

- **Truy vết:** `FR-ID-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student ACTIVE, password đã đặt; Web live + Core.
- **Các bước thực hiện:** Mở /login; nhập username/password hợp lệ; submit; mở /users/me.
- **Kết quả mong đợi:** 200 access token, refresh cookie HttpOnly, profile STUDENT; chuyển student UI; không lộ refresh token.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-002 — Đăng nhập sai và rate limit

- **Truy vết:** `FR-ID-03; NFR-SEC-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Có tài khoản staff/student trong DB test.
- **Các bước thực hiện:** Gửi password sai; gửi dồn nhiều lần theo cửa sổ limiter.
- **Kết quả mong đợi:** 401/429 theo policy; response không xác nhận username tồn tại; Retry-After khi bị giới hạn.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-003 — Refresh rotation và revoke

- **Truy vết:** `FR-ID-04; NFR-SEC-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student ACTIVE đã login, có refresh cookie.
- **Các bước thực hiện:** Làm mới access token; thử lại refresh cookie cũ; logout-all; thử token/phiên cũ.
- **Kết quả mong đợi:** Rotated cookie và access hợp lệ; refresh replay bị từ chối; phiên đã revoke không đọc được resource.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-004 — Kích hoạt một lần

- **Truy vết:** `FR-ID-02`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student PENDING, Admin đã nhận code còn hạn.
- **Các bước thực hiện:** Submit username/code/password; submit lại cùng code; thử code expired và LOCKED.
- **Kết quả mong đợi:** Lần đầu 204/ACTIVE; replay/hết hạn/LOCKED không kích hoạt; no raw code trong logs.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-005 — Admin tạo Student

- **Truy vết:** `FR-ID-01; FR-ID-08`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Admin ACTIVE có school scope; username mới.
- **Các bước thực hiện:** Gọi POST /admin/students; xem response; kiểm tra DB/audit; login Student trước activation.
- **Kết quả mong đợi:** 201 + code một lần/no-store; Student PENDING trong school Admin; password chưa kích hoạt không login.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-006 — Non-Admin cố tạo Student hoặc đổi role

- **Truy vết:** `FR-ID-01; FR-ID-05`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student/Lecturer ACTIVE; Admin khác school.
- **Các bước thực hiện:** Gọi POST /admin/students và PUT /admin/users/{id}/roles với token trái quyền.
- **Kết quả mong đợi:** Không thành công; không thêm account/role; không có dữ liệu nhạy cảm trong response.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-007 — Admin tìm danh sách tài khoản theo scope

- **Truy vết:** `FR-ID-05`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Hai school, Admin school A, nhiều Student/Staff.
- **Các bước thực hiện:** GET /admin/users?search=&role=&status=; paginate cursor; dùng user_id của trường B.
- **Kết quả mong đợi:** Chỉ thấy user school A, cursor/filter đúng; user trường B 404/ẩn; không trả hash/token.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-008 — Revision conflict và last Admin

- **Truy vết:** `FR-ID-05`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Hai session Admin, tài khoản đích và last ACTIVE Admin.
- **Các bước thực hiện:** Cùng gửi PATCH expected_revision; cố khóa/gỡ last Admin.
- **Kết quả mong đợi:** Một thay đổi thành công, stale 409; không bỏ trống Admin ACTIVE hợp lệ; audit/revoke đúng.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-009 — Import preview sai định dạng/cột

- **Truy vết:** `FR-ID-06`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Admin ACTIVE; CSV/XLSX synthetic malformed.
- **Các bước thực hiện:** Upload file có formula/duplicate header/username trùng; kiểm tra preview.
- **Kết quả mong đợi:** Parser trả lỗi có dòng, không tạo user; không xuất raw file/secret; error field chính xác.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-010 — Import confirm timeout/replay

- **Truy vết:** `FR-ID-06; NFR-DI-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Preview hợp lệ, DB test; hai request đồng thời.
- **Các bước thực hiện:** Confirm preview; giả lập response mất; GET batch; gửi confirm lại.
- **Kết quả mong đợi:** Chỉ tạo một kết quả theo preview, status COMPLETED/replayed; không nhân đôi roster/user.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-011 — Homeroom roster update expected version

- **Truy vết:** `FR-CL-01; FR-CL-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Admin school A, homeroom version V và students ACTIVE.
- **Các bước thực hiện:** GET roster; PUT student_ids expected V; GET lại.
- **Kết quả mong đợi:** Một revision tăng, students đúng; episodes lịch sử còn; audit có actor/scope.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-012 — Roster stale conflict

- **Truy vết:** `FR-CL-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Hai Admin cùng homeroom version V.
- **Các bước thực hiện:** Admin A lưu V thành V+1; Admin B lưu expected V.
- **Kết quả mong đợi:** B nhận 409, không overwrite; UI yêu cầu reload/preview, không báo success.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-013 — Tạo lớp AUTO từ catalog

- **Truy vết:** `FR-CL-01; FR-CL-02`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** School có course, year, semester, homeroom và PRIMARY ACTIVE.
- **Các bước thực hiện:** Gọi POST /admin/classes với mode AUTO, các linked IDs hợp lệ.
- **Kết quả mong đợi:** Class + teaching assignments được tạo atomically; membership theo roster khi sync; class trong list đúng scope.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-014 — Teacher và cross-school không tạo được lớp

- **Truy vết:** `FR-CL-01; FR-CL-07`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Lecturer school A và Admin A; course/teacher thuộc B.
- **Các bước thực hiện:** Lecturer POST /admin/classes; Admin A gửi linked IDs trường B.
- **Kết quả mong đợi:** Request bị từ chối, không có class/assignment rác, không leak trường B.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-015 — MANUAL→AUTO preview/sync stale

- **Truy vết:** `FR-CL-02; FR-CL-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Class MANUAL, homeroom roster đã chốt, hai Admin.
- **Các bước thực hiện:** Preview; thay roster trước confirm; gửi sync với version cũ; preview lại.
- **Kết quả mong đợi:** Stale 409/rollback; sync mới tính add/end đúng; history giữ; MANUAL không tự overwrite ngoài flow.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-016 — Transfer membership & access revoke

- **Truy vết:** `FR-CL-04; FR-CL-07`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student ACTIVE lớp nguồn; class destination hợp lệ; vài post lịch sử.
- **Các bước thực hiện:** Admin transfer; Student refresh classes; cố POST/read new content lớp nguồn.
- **Kết quả mong đợi:** Membership source ended, destination active; hoạt động mới nguồn bị deny, lịch sử membership bảo tồn.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-017 — Archive class Admin-only

- **Truy vết:** `FR-CL-06; FR-SO-04`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Class ACTIVE, teacher+student đang hoạt động.
- **Các bước thực hiện:** Admin archive expected version; teacher POST post/calendar; Student truy cập read-only.
- **Kết quả mong đợi:** Archive success+audit; new mutations bị block; lịch sử đọc theo policy.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-018 — Restore và quyền hiện hành

- **Truy vết:** `FR-CL-05; FR-CL-06`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Class ARCHIVED, Lecturer đã bị bỏ assignment.
- **Các bước thực hiện:** Admin restore, Lecturer cũ thử POST post, current assigned Lecturer thử.
- **Kết quả mong đợi:** Lớp ACTIVE, người mất assignment vẫn bị deny, assigned Lecturer theo rule được phép.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-019 — Cross-class class-detail IDOR

- **Truy vết:** `FR-CL-07; NFR-SEC-02`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student chỉ thuộc class A; có class B ngoài scope.
- **Các bước thực hiện:** GET /classes/B, /classes/B/members và /classes? filter cố suy đoán.
- **Kết quả mong đợi:** Không lộ B, API trả concealed 404/deny theo contract; list đúng scope.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-020 — Feed create/edit/soft-delete

- **Truy vết:** `FR-SO-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Teacher assigned, Student enrolled, post author hiện hành.
- **Các bước thực hiện:** Tạo post; sửa own; delete; GET feed; kiểm tra audit nếu moderation.
- **Kết quả mong đợi:** Content đúng trước xóa, không hiện raw body sau soft-delete; rights theo author/current scope.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-021 — Comment permissions và moderation

- **Truy vết:** `FR-SO-02; NFR-SEC-02`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Hai Students khác lớp, teacher assigned, post tồn tại.
- **Các bước thực hiện:** Bình luận bằng member hợp lệ; nonmember/author khác sửa; teacher moderate.
- **Kết quả mong đợi:** Only authorized operations succeed, deleted comment hidden; moderator action audited.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-022 — Calendar validation và read-only projection

- **Truy vết:** `FR-SO-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Class ACTIVE, teacher assigned, Student member.
- **Các bước thực hiện:** POST starts>=ends; POST valid CORE; Student PATCH; PATCH projection LEARNING nếu có fixture.
- **Kết quả mong đợi:** Invalid 422, valid 201; Student PATCH denied, LEARNING projection không chỉnh bằng Core.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-023 — Notification recipient snapshot replay

- **Truy vết:** `FR-NO-02; NFR-DI-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Producer mutation, outbox V2, worker and same-school recipients.
- **Các bước thực hiện:** Publish event; thay membership sau commit; chạy worker; replay same event.
- **Kết quả mong đợi:** Chỉ original snapshot recipients nhận; dedup không nhân đôi; không dùng current audience để gửi lịch sử.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-024 — Notification own/read-all watermark

- **Truy vết:** `FR-NO-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Hai Users; notifications trước/sau read-all.
- **Các bước thực hiện:** User A GET/mark read; cố đọc notification B; read-all; phát event mới.
- **Kết quả mong đợi:** A chỉ thấy own; B không lộ; event sau watermark vẫn unread; mark-read idempotent.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-025 — Self data request và scope

- **Truy vết:** `FR-ID-07; NFR-SEC-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Student ACTIVE và Admin school A/B.
- **Các bước thực hiện:** Student POST type DELETE; Admin B GET request ID; Admin A GET list.
- **Kết quả mong đợi:** Request PENDING owner-only; Admin B không đọc; Admin A cùng trường thấy trạng thái đúng.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-026 — DELETE chưa có executor không COMPLETED

- **Truy vết:** `FR-ID-07`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Request DELETE IN_REVIEW; policy DELETE chưa duyệt.
- **Các bước thực hiện:** Admin có identity_verified gửi PATCH COMPLETED; đọc trạng thái/audit.
- **Kết quả mong đợi:** Giữ IN_REVIEW/POLICY_PENDING theo policy; audit deferred; không xóa data nhầm.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-027 — Live build không có mock fixture

- **Truy vết:** `NFR-DEP-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Next.js build server với NEXT_PUBLIC_DATA_MODE=live.
- **Các bước thực hiện:** Chạy npm run check/build, scan fixture; gọi API upstream 503.
- **Kết quả mong đợi:** Build không chứa mock payload; upstream lỗi hiển thị lỗi thật, không dữ liệu giả.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-028 — Browser login/logout/refresh end-to-end

- **Truy vết:** `FR-ID-03; NFR-UX-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Web live, PostgreSQL real synthetic, Core healthy.
- **Các bước thực hiện:** Chrome login Student; refresh tab; expire access; logout; back navigation.
- **Kết quả mong đợi:** Cập nhật đúng session, không lộ protected content sau logout; route guard + server deny.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-029 — Origin/CSRF proxy hardening

- **Truy vết:** `NFR-SEC-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Web same-origin proxy, Core config đúng.
- **Các bước thực hiện:** Gửi unsafe mutation không có/khác Origin; refresh cookie từ origin khác.
- **Kết quả mong đợi:** 403 không forward; correct origin hoạt động; không nới CORS để test qua.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-030 — Full Admin→Lecturer→Student journey

- **Truy vết:** `FR-CL-01; FR-SO-01; FR-NO-01; NFR-DEP-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Synthetic seed + worker + live Next.js + PostgreSQL.
- **Các bước thực hiện:** Tạo Student/homeroom/class/assignment; activate; teacher post/event; student comment/read notification; archive.
- **Kết quả mong đợi:** Tất cả bước có response thật, audit/inbox đúng, không mock, logs/screenshots redacted; source revision ghi rõ.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


## Document Service — future proposal


### DOC-T01 — Document owner library

- **Truy vết:** `FR-DOC-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Document backend đã triển khai theo approved contract; Lecturer ACTIVE.
- **Các bước thực hiện:** Owner tạo source và GET library; user khác GET owner list.
- **Kết quả mong đợi:** Source thuộc owner; khác owner không xem thư viện riêng.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T02 — Delete source shared multi-class

- **Truy vết:** `FR-DOC-01; FR-DOC-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Một source đã grant tới ≥2 classes.
- **Các bước thực hiện:** Owner bấm delete; kiểm tra warning; confirm/delete theo policy.
- **Kết quả mong đợi:** Hiện tác động đầy đủ; không xóa âm thầm hoặc mở grant lỗi.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T03 — Năm định dạng file

- **Truy vết:** `FR-DOC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Five valid test files và storage worker.
- **Các bước thực hiện:** Upload PDF, PPTX, DOCX, TXT, Markdown; kiểm tra processing state.
- **Kết quả mong đợi:** Cả 5 format supported, trạng thái xử lý phản ánh thực tế.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T04 — Malformed/oversize file

- **Truy vết:** `FR-DOC-02; NFR-SEC-03`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Có file hỏng, nén bomb, MIME mismatch.
- **Các bước thực hiện:** Upload lần lượt; theo dõi parser/storage/log.
- **Kết quả mong đợi:** Validation safe, không chạy extraction nguy hiểm, không lộ stacktrace.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T05 — Failed latest version fallback

- **Truy vết:** `FR-DOC-03; FR-DOC-07; NFR-REC-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Document v1 SUCCESS, v2 malformed.
- **Các bước thực hiện:** Upload v2; đợi FAILED; user được phép GET nội dung.
- **Kết quả mong đợi:** Vẫn đọc v1 SUCCESS, lỗi v2 hiện với owner; không publish v2.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T06 — ASSISTING share authorized source

- **Truy vết:** `FR-DOC-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Assigned ASSISTING, document owner cùng hoặc được quyền share.
- **Các bước thực hiện:** POST grant vào ACTIVE class; student GET.
- **Kết quả mong đợi:** Grant hiệu lực, không cho sửa source của người khác.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T07 — Lecturer mất assignment rồi grant

- **Truy vết:** `FR-DOC-04; NFR-SEC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Teacher revoked assignment.
- **Các bước thực hiện:** Gửi lại POST grant/revoke with old token.
- **Kết quả mong đợi:** Server deny dựa current assignment, không chỉ frontend flag.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T08 — Revoke immediate

- **Truy vết:** `FR-DOC-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Student đang đọc tài liệu có grant, teacher revoke.
- **Các bước thực hiện:** Revoke; mở lại URL/page/API, kể cả cached state.
- **Kết quả mong đợi:** New access bị deny, không leak source, notes riêng được giữ.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T09 — Cross-school document access

- **Truy vết:** `FR-DOC-05; NFR-SEC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Document grant school A; student school B.
- **Các bước thực hiện:** Gọi API download/read bằng doc_id đoán được.
- **Kết quả mong đợi:** Deny; không trả metadata hoặc signed URL trái phép.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T10 — Core unavailable permission check

- **Truy vết:** `FR-DOC-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Document đang xử lý read; Core access check unavailable.
- **Các bước thực hiện:** Ngắt Core access endpoint; user yêu cầu mở tài liệu.
- **Kết quả mong đợi:** Fail closed; không cấp link/content.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T11 — SourceBoundNote owner only

- **Truy vết:** `FR-DOC-06`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Student A có note, Student B có chung lớp.
- **Các bước thực hiện:** B GET/PATCH note của A; A edit note.
- **Kết quả mong đợi:** B denied, A được edit theo policy.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T12 — Revoke hides quote but preserves own text

- **Truy vết:** `FR-DOC-06`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Note có self_text + quote_ref từ source.
- **Các bước thực hiện:** Teacher revoke; A mở note.
- **Kết quả mong đợi:** A xem được self_text, quote/source bị che và không mở source.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### DOC-T13 — Archived class personal bookmark

- **Truy vết:** `FR-DOC-06`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Class archived, student owner bookmark, source grant còn.
- **Các bước thực hiện:** Student sửa bookmark và thử POST shared activity.
- **Kết quả mong đợi:** Bookmark cá nhân theo O2 được sửa; shared activity denied.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


## Learning Service — future proposal


### LE-T01 — Tạo draft assessment

- **Truy vết:** `FR-LE-01; FR-LE-02; FR-LE-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Assigned Lecturer, class ACTIVE.
- **Các bước thực hiện:** Tạo draft với 4 loại câu hỏi.
- **Kết quả mong đợi:** Draft tồn tại đúng lớp, không công bố khi chưa duyệt.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T02 — PRIMARY publish approval

- **Truy vết:** `FR-LE-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** PRIMARY/ASSISTING trong class.
- **Các bước thực hiện:** ASSISTING đề xuất; PRIMARY approve.
- **Kết quả mong đợi:** Không publish trước approval; publish đúng version immutable.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T03 — ASSISTING cannot approve

- **Truy vết:** `FR-LE-04; NFR-SEC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** ASSISTING current, draft awaiting approval.
- **Các bước thực hiện:** Gọi approval endpoint bằng ASSISTING.
- **Kết quả mong đợi:** Denied, không mutate state hay score.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T04 — Published immutable new version

- **Truy vết:** `FR-LE-03`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** V1 published, attempts đã bắt đầu.
- **Các bước thực hiện:** Giáo viên sửa nội dung V1 / tạo V2.
- **Kết quả mong đợi:** V1 không mutate; V2 riêng cho lượt sau.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T05 — Attempt pins version

- **Truy vết:** `FR-LE-03; FR-LE-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** V1 published; Student starts attempt.
- **Các bước thực hiện:** Tạo attempt; publish V2; GET attempt.
- **Kết quả mong đợi:** Attempt vẫn gắn V1 và câu hỏi V1.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T06 — Save answer ACK server

- **Truy vết:** `FR-LE-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Attempt IN_PROGRESS, valid question.
- **Các bước thực hiện:** PATCH answer; nhận ACK revision; reload.
- **Kết quả mong đợi:** Answer đã ACK tồn tại, revision monotonic.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T07 — Offline before ACK

- **Truy vết:** `FR-LE-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Browser offline trước response save.
- **Các bước thực hiện:** Edit answer; ngắt network; reload after recovery.
- **Kết quả mong đợi:** Không báo Đã lưu khi chưa ACK; chỉ committed answer recovered.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T08 — Auto-submit server clock

- **Truy vết:** `FR-LE-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Attempt có deadline gần, saved answers.
- **Các bước thực hiện:** Chờ đến deadline; ngắt browser; query receipt.
- **Kết quả mong đợi:** AUTO_SUBMITTED với saved answers, không phụ thuộc tab mở.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T09 — Double submit race

- **Truy vết:** `FR-LE-06; NFR-DI-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Một attempt, hai client tabs đồng thời.
- **Các bước thực hiện:** POST submit cùng lúc và retry after timeout.
- **Kết quả mong đợi:** Một final submission/grade, stable receipt; no duplicate evidence.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T10 — Auto grade objective

- **Truy vết:** `FR-LE-09`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Official attempt đã submitted, key approved.
- **Các bước thực hiện:** Run grader cho single/multi/truefalse.
- **Kết quả mong đợi:** Kết quả khách quan theo key/policy, không kết luận chủ quan.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T11 — Teacher grades subjective

- **Truy vết:** `FR-LE-09; FR-LE-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Submission có short answer/Assignment.
- **Các bước thực hiện:** ASSISTING được phân công chấm và đề xuất.
- **Kết quả mong đợi:** Chấm theo assignment; chưa tự công bố nhạy cảm.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T12 — PRIMARY grade correction approval

- **Truy vết:** `FR-LE-09`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Grade published, teacher đề xuất sửa.
- **Các bước thực hiện:** Submit proposal; PRIMARY review approve; GET grade history.
- **Kết quả mong đợi:** Version effective tăng, reason/audit lưu, history không mất.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T13 — Unauthorized grade correction

- **Truy vết:** `FR-LE-04; NFR-SEC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Unassigned Lecturer/Student, grade published.
- **Các bước thực hiện:** Gọi correction/approve endpoints.
- **Kết quả mong đợi:** Denied, grade effective không thay.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T14 — Admin exceptional grade action audit

- **Truy vết:** `FR-LE-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Policy Admin exceptional approval đã duyệt.
- **Các bước thực hiện:** Admin can thiệp đúng API và reason.
- **Kết quả mong đợi:** Audit đầy đủ, không coi Admin mặc nhiên PRIMARY.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T15 — Assignment deadline and late policy

- **Truy vết:** `FR-LE-07`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Assignment có late policy approved.
- **Các bước thực hiện:** Submit before/after due; compare rule.
- **Kết quả mong đợi:** Late status/acceptance đúng cấu hình, không phạt tùy ý.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T16 — Assignment resubmission limit

- **Truy vết:** `FR-LE-07`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Assignment có max_attempts và selected graded version.
- **Các bước thực hiện:** Nộp lại nhiều lần tới/vượt limit.
- **Kết quả mong đợi:** Số lần và bản được chấm đúng policy, out-of-limit denied.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T17 — Deadline extension effects

- **Truy vết:** `FR-LE-07; FR-LE-10`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Student đã submitted; lecturer đổi deadline.
- **Các bước thực hiện:** Extend deadline; inspect submitted grades/attempts.
- **Kết quả mong đợi:** Không đổi bài đã nộp/number-of-attempts, notification new deadline.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T18 — Grade policy best/latest/average

- **Truy vết:** `FR-LE-07`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Activity có nhiều attempts và policy set.
- **Các bước thực hiện:** Tính official result theo từng policy đã duyệt.
- **Kết quả mong đợi:** Kết quả khớp configured policy và audit revision.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T19 — Transfer after submission

- **Truy vết:** `FR-LE-08`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Student submitted before transfer; teacher current assignment.
- **Các bước thực hiện:** Admin transfer; teacher grade source submitted work; student GET own grade.
- **Kết quả mong đợi:** Grade allowed theo historical action, không trả feed mới source.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T20 — Transfer pending attempt cutoff

- **Truy vết:** `FR-LE-08`. **Phạm vi:** `PENDING DECISION`.
- **Tiền điều kiện / dữ liệu:** Student IN_PROGRESS khi Admin transfer.
- **Các bước thực hiện:** Thực hiện transfer tại cutoff policy đã duyệt.
- **Kết quả mong đợi:** Attempt behavior đúng quyết định operator, không xử lý mặc định.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T21 — Appeal after membership ended

- **Truy vết:** `FR-LE-08`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Student ended enrollment, within approved appeal window.
- **Các bước thực hiện:** Student file appeal for past submitted grade.
- **Kết quả mong đợi:** Limited appeal allowed, unrelated current class data denied.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T22 — Teacher assignment revoked before grading

- **Truy vết:** `FR-LE-08`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Lecturer không còn được phân công.
- **Các bước thực hiện:** Try grade submitted work without historical authorization.
- **Kết quả mong đợi:** Deny trừ khi action-specific approved exception còn hợp lệ.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T23 — Deadline projection event

- **Truy vết:** `FR-LE-10`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Learning activity due published.
- **Các bước thực hiện:** Emit versioned event, process in Core Calendar.
- **Kết quả mong đợi:** Core projection matches authoritative due/version.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T24 — Out-of-order deadline events

- **Truy vết:** `FR-LE-10; NFR-DI-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Events V3 then V2 for same activity.
- **Các bước thực hiện:** Deliver events reverse and replay.
- **Kết quả mong đợi:** Core projection remains V3, no duplicate notification.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LE-T25 — Deadline change notification

- **Truy vết:** `FR-LE-10`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Assigned teacher updates due.
- **Các bước thực hiện:** Deliver event, worker process recipients.
- **Kết quả mong đợi:** Eligible recipients get correct deadline change once, old submissions remain.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


## Learner Intelligence — future proposal


### LI-T01 — Evidence ingestion permitted source

- **Truy vết:** `FR-LI-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Learning event signed/contracted.
- **Các bước thực hiện:** Send valid approved grade result.
- **Kết quả mong đợi:** Accepted with provenance and source revision.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T02 — Duplicate event replay

- **Truy vết:** `FR-LI-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** One accepted evidence event.
- **Các bước thực hiện:** Replay event ID multiple times.
- **Kết quả mong đợi:** No duplicate evidence or mastery distortion.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T03 — Out-of-order correction

- **Truy vết:** `FR-LI-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Source V2 approved, V1 event delayed.
- **Các bước thực hiện:** Deliver V2 then V1.
- **Kết quả mong đợi:** Effective evidence remains V2, previous revision audit retained.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T04 — Practice vs official distinction

- **Truy vết:** `FR-LI-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Student has practice + official scores.
- **Các bước thực hiện:** Ingest both and query report.
- **Kết quả mong đợi:** Separated evidence type and policy; no unapproved weight mixing.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T05 — Insufficient independent evidence

- **Truy vết:** `FR-LI-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Only one repeated question/attempt.
- **Các bước thực hiện:** Compute mastery.
- **Kết quả mong đợi:** Return Chưa đủ dữ liệu, no numeric high-confidence label.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T06 — Topic coverage insufficiency

- **Truy vết:** `FR-LI-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Many observations on narrow subtopic.
- **Các bước thực hiện:** Compute topic mastery.
- **Kết quả mong đợi:** Remain insufficient if approved topic coverage unmet.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T07 — Adequate evidence with explanation

- **Truy vết:** `FR-LI-02; NFR-MOD-01`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Approved evaluation corpus and coverage threshold.
- **Các bước thực hiện:** Compute mastery with calibration.
- **Kết quả mong đợi:** Result includes evidence refs/model_version, quality evaluated; not assumed correct.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T08 — Supportive recommendation

- **Truy vết:** `FR-LI-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Weak topic evidence meets approved rule.
- **Các bước thực hiện:** GET recommendations.
- **Kết quả mong đợi:** Student sees rationale and voluntary practice suggestion.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T09 — No punitive automation

- **Truy vết:** `FR-LI-04`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Insufficient evidence and attempts with low scores.
- **Các bước thực hiện:** GET recommendations/admin outcomes.
- **Kết quả mong đợi:** No automatic grade change or punitive label.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T10 — Recommendation source permission

- **Truy vết:** `FR-LI-04; NFR-SEC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Document reference permission revoked.
- **Các bước thực hiện:** GET recommendation/resource link.
- **Kết quả mong đợi:** Unauthorized source hidden/non-openable; explanation remains safe.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T11 — Student owner-only progress

- **Truy vết:** `FR-LI-03`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Two Student accounts, teacher class A.
- **Các bước thực hiện:** Student B GET Student A progress.
- **Kết quả mong đợi:** Deny; no evidence/grades leaked.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T12 — Lecturer class scope

- **Truy vết:** `FR-LI-03`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Lecturer assigned A not B.
- **Các bước thực hiện:** GET analytics for B, drilldown B student.
- **Kết quả mong đợi:** Deny/404; aggregation filtered by current assignment.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T13 — Small-group suppression contract

- **Truy vết:** `FR-LI-06`. **Phạm vi:** `PENDING SOURCE`.
- **Tiền điều kiện / dữ liệu:** Synthetic sensitive group with 4 then 5 distinct participants.
- **Các bước thực hiện:** Query aggregate with varying filters.
- **Kết quả mong đợi:** <5 suppressed; >=5 still subject to complementary suppression/reaidentification check.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T14 — Admin PDF export

- **Truy vết:** `FR-LI-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Admin school A, approved aggregate dataset.
- **Các bước thực hiện:** Request PDF; download after ready; inspect content.
- **Kết quả mong đợi:** Valid PDF, scoped counts match authoritative data, no private text.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T15 — Admin XLSX export

- **Truy vết:** `FR-LI-05`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Admin school A, malicious spreadsheet-like text.
- **Các bước thực hiện:** Request Excel, open file, inspect cells.
- **Kết quả mong đợi:** Valid XLSX, no formula injection, scope/suppression respected.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### LI-T16 — Download after Admin role revoked

- **Truy vết:** `FR-LI-05; NFR-SEC-02`. **Phạm vi:** `PROPOSED`.
- **Tiền điều kiện / dữ liệu:** Admin requested report; later role revoked.
- **Các bước thực hiện:** Attempt download existing export URL.
- **Kết quả mong đợi:** Permission rechecked and denied; audit request/download attempts.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


## Cross-cutting NFR — kế hoạch kiểm chứng bổ sung


### TC-031 — Notification payload không chứa secret

- **Truy vết:** `FR-NO-03; NFR-SEC-03`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Core V2 event và DB test có synthetic token/chat/document text.
- **Các bước thực hiện:** Ghi event thử và đọc outbox/inbox JSON + logs với secret canary.
- **Kết quả mong đợi:** Payload chỉ ID/metadata allowlist, không chứa token/credential/raw chat/full document.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-032 — TP-01 Core class-list p95

- **Truy vết:** `NFR-PERF-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Load harness 100 users/10 classes/50 Student mỗi lớp trên DB PG16.
- **Các bước thực hiện:** Warmup; đo 10 phút độc lập; ghi resource contention, success, backend/client p95.
- **Kết quả mong đợi:** Báo p95 backend và target <=500ms, 0 scope mismatch; chưa suy ra full TP-01 hay 358 CCU.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-033 — Sự cố SMTP không làm sập Core

- **Truy vết:** `NFR-AV-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Core DB và auth healthy, SMTP test provider unavailable.
- **Các bước thực hiện:** Ngắt SMTP; thử class-list/login/notification inbox, quan sát credential delivery queue.
- **Kết quả mong đợi:** Các flow không phụ thuộc SMTP vẫn hoạt động; delivery pending/retry, không giả đã gửi.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-034 — Giới hạn single-worker và kế hoạch scale

- **Truy vết:** `NFR-SCAL-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** Một worker Core đang chạy; mục tiêu đa replica chưa chốt.
- **Các bước thực hiện:** Chạy workload theo current single-worker và ghi process count/config; nếu tăng worker tạo review gate.
- **Kết quả mong đợi:** Không tuyên bố durable rate-limit/idempotency across replicas khi chưa implement; kết quả tải có phạm vi rõ.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


### TC-035 — Correlation ID và log redaction

- **Truy vết:** `NFR-OBS-01`. **Phạm vi:** `CORE`.
- **Tiền điều kiện / dữ liệu:** API Core chạy với user, request IDs, secret canary.
- **Các bước thực hiện:** Gọi successful/denied/errors; kiểm tra response X-Correlation-ID, audit và logs.
- **Kết quả mong đợi:** Correlation ID hợp lệ/truy được request; không lộ password/token/chat/raw credentials.
- **Bằng chứng cần lưu:** request/response code redacted, DB invariant/diff nếu có, source revision, log/correlation ID và browser trace cho UI.
- **Kết quả thực thi:** `NOT RUN — chưa thực hiện trong quá trình biên soạn tài liệu`.


## Tổng hợp

| Nhóm | Số test thiết kế | Trạng thái thực thi |
|---|---:|---|
| Core MVP — hiện có backend, E2E vẫn cần chạy | 30 | NOT RUN |
| Document Service — future proposal | 13 | NOT RUN |
| Learning Service — future proposal | 25 | NOT RUN |
| Learner Intelligence — future proposal | 16 | NOT RUN |
| Cross-cutting NFR — kế hoạch kiểm chứng bổ sung | 5 | NOT RUN |
| **Tổng** | **89** | **NOT RUN** |


## Mẫu ghi nhận test run

```yaml
test_case_id: TC-030
source_commit: <sha>
environment: <staging-or-local>
postgres_migration: <head>
web_mode: live
worker_enabled: true
result: NOT_RUN  # PASSED | FAILED | BLOCKED | NOT_RUN
evidence: []
issues: []
reviewed_by: <reviewer>
```

Không coi chính sách `NOT RUN` là lỗi hệ thống; nó chỉ mô tả phạm vi tài liệu mới tạo.