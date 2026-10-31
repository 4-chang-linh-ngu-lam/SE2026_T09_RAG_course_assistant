# UI/UX DESIGN SPECIFICATION — WEB LUMI

**Mã:** LUMI-UI-001 · **Trạng thái:** UI routes có trong repo, mức độ live cần đánh giá từng màn; Future feature UI chỉ unavailable khi backend chưa có.

## 1. Mục tiêu trải nghiệm

- Học sinh khối 6–12 dùng giao diện rõ ràng, tập trung học, không lạm dụng game hóa.
- Phân biệt quyền Admin/Lecturer/Student ngay trong navigation, nhưng backend tiếp tục là authority.
- Không “success giả”: chỉ hiển thị thành công sau khi server trả receipt/ACK đáng tin cậy.
- Tự phục hồi khỏi stale form khi roster/version thay; không che lỗi 401/403/404/409/422.
- Responsive desktop/mobile, keyboard navigable, form labels, focus states và screen-reader feedback cho lỗi quan trọng.

## 2. Navigation/route map

| Nhóm | Route đã nhìn thấy trong Web | Chức năng | Live status/gate |
|---|---|---|---|
| Public | `/login`, `/activate`, `/recover`, `/reset-password`, `/staff/invitation` | Auth/activation/invitation | Core backend có; browser E2E phải xác minh |
| Account | `/account`, `/account/data-requests` | Profile, self-request | Core backend có; policy xử lý đầy đủ chưa có |
| Admin | `/admin/accounts`, `/admin/accounts/students/new`, `/admin/accounts/[userId]` | List/create/update user | Core API có |
| Admin | `/admin/imports/new`, `/admin/imports/[importId]` | Preview/confirm/reconcile | Core API có |
| Admin | `/admin/catalog`, `/admin/homerooms`, `/admin/homerooms/[homeroomId]` | Course/year/homeroom/roster | Core API có |
| Admin | `/admin/classes`, `/admin/classes/new`, `/admin/classes/[classId]/settings` | Class create/manage | Core API có |
| Admin | `/admin/classes/[classId]/enrollment`, `/lifecycle` | Sync/transfer/archive/restore | Core API có |
| Admin | `/admin/audit`, `/admin/data-requests` | Audit/review | Backend có; một số UI adapter có thể pending |
| Admin | `/admin/reports`, `/admin/reports/exports` | Reporting | Backend export Intelligence chưa triển khai |
| Teacher | `/teacher/classes`, `/teacher/classes/[classId]/feed`, `/calendar`, `/overview` | Core teaching UI | Core API có |
| Student | `/student/classes`, `/student/classes/[classId]/feed`, `/calendar`, `/overview` | Core student UI | Core API có |
| Common | `/notifications`, `/calendar` | Notifications/schedule | Core API có |
| Future | `/teacher/library`, `/student/classes/[classId]/documents`, `/practice`, `/assessments`, `/assignments`, `/progress` | Document/Learning/Intelligence | **Không khả dụng live** cho tới khi backend được duyệt |

Các route thêm trong code mới hơn mốc 55324dc phải được đối chiếu tự động từ `apps/web/app/` và cập nhật map, không lấy danh sách này làm đầy đủ tuyệt đối.

## 3. Interaction template cho mỗi screen

| Trường thiết kế | Cần mô tả |
|---|---|
| Screen ID | Định danh độc lập với route |
| Role/action | Ai xem và làm được gì |
| Data sources | API thật, nguồn cập nhật và quyền |
| Controls | Label, button, form, required/optional/default |
| Validation | Client hints và server authoritative validation |
| States | loading/empty/error/forbidden/notfound/conflict/success |
| Feedback | Toast/inline, acknowledgement, retry rules |
| Security | Không tiết lộ secret/hidden data; disable control không thay auth |
| E2E evidence | Test/screenshot/commit, **live hay mock** |

## 4. Screen-level specs — Core ưu tiên

### UI-A01 — Admin tài khoản

- **Search:** theo tên/email/username, lọc role/status/account_type; server-side pagination cursor, reset cursor khi đổi filter.
- **Bảng:** tên, tài khoản, role, trạng thái, delivery, actions; không hiển thị token/password hash.
- **Tạo staff:** email, role, tên; sau submit hiển thị trạng thái email delivery, không chứa invitation token.
- **Edit:** gửi `expected_revision`; 409 hiển thị “Dữ liệu đã thay đổi, tải lại để kiểm tra”, không ghi đè.
- **Errors:** 403 khác trường/tài khoản không hợp quyền, 404 concealed, 422 email/roles.

### UI-A02 — Tạo Student + activation code

- **Controls:** username, display_name, Tạo, Sao chép mã (một lần), xác nhận đã bàn giao qua kênh an toàn.
- **Display:** purpose, expires_at; auto-clear khi điều hướng/đóng, no-store; không screenshot/log trong E2E public artifacts.
- **Retry:** nếu request timeout không “tạo lại” ngay; query danh sách user hoặc xử lý có chứng cứ.

### UI-A03 — Import Student

- **Steps:** chọn file → mapping cột → Preview → xác nhận → kết quả.
- **Preview table:** row no, username/display_name, valid/errors; không gửi confirm nếu preview không hợp lệ/hết hạn.
- **Reconcile:** trên lỗi network sau confirm, query batch status; giữ preview_id an toàn trong phiên UI.
- **Conflict:** phiên bản roster đổi → yêu cầu làm lại preview, không ghi đè.

### UI-A04 — Homeroom roster

- **List:** năm học, khối, lớp, roster count. **Detail:** student list, version.
- **Controls:** chọn học sinh, thêm/bớt, transfer; confirm nêu tác động lớp AUTO.
- **Conflict:** khi expected_roster_version stale, giữ selection tạm nhưng phải fetch lại trước confirm.

### UI-A05 — Class create & management

- **Form:** course, class name, grade 6–12, year/semester, homeroom, AUTO/MANUAL, PRIMARY, ASSISTING.
- **Actions:** Create, Edit assignment, Preview Enrollment, Sync, Transfer, Archive/Restore.
- **Warnings:** AUTO roster sync ảnh hưởng học sinh; ARCHIVE làm read-only; đổi PRIMARY phải có người thay.
- **Errors:** version conflict/permissions; không gọi API qua mock khi live.

### UI-T01/S01 — Class feed

- **List:** author display name, timestamp, content, comments count, deleted state; cursor pagination.
- **Controls:** create, comment, edit own, moderation nếu authorized; disabled/read-only khi archive.
- **Visual:** deleted post không show raw body; user mất membership chuyển 404/forbidden appropriate.

### UI-T02/S02 — Calendar

- **Controls:** date range, teacher create event, edit/delete CORE-origin; LEARNING-origin future view-only.
- **Validation:** ends_at phải sau starts_at; timezone hiển thị nhất quán, server lưu UTC.
- **Empty:** “Chưa có sự kiện trong khoảng thời gian này”, không hiển thị deadline giả từ mock.

### UI-C01 — Notifications

- **List:** inbox owner-only, unread count, mark-read/read-all; link content bị đổi quyền sẽ mở trang no access.
- **Read-all:** client không tự mark sự kiện mới phát sau request là read; dựa response/refresh watermark server.

### UI-A06 — Data request/audit

- **Self:** user chọn ACCESS/EXPORT/CORRECTION/DELETE, gửi lý do; không cho tự đặt state.
- **Admin:** cùng trường, identity verification attest, reason code, status; DELETE thiếu executor phải hiển thị IN_REVIEW/POLICY_PENDING.
- **Audit:** filter/sort/cursor, không ghi show token/raw chat.

## 5. Form validation

| Form | Client-side | Server-side bắt buộc |
|---|---|---|
| Student create | nonblank username, display_name optional | uniqueness, school, role/status, code purpose |
| Activate | username/code/password/confirm | token hash, purpose, consumed/expiry/locked |
| Class create | required fields, grade 6–12 | all linked IDs current school, teachers ACTIVE, mode constraints |
| Calendar | title/times | starts_at < ends_at, assignment, class ACTIVE |
| Import | extension and selected header | MIME/size/zip-bomb/formula/duplicate/legacy scope |
| Assessment (future) | question type/timer/responses | immutable version, official approval, current permissions |

Không tự gán min/max ký tự hay hạn file ngoài Pydantic/API contract hiện hành.

## 6. Component patterns

- **Page shell:** role-specific nav, breadcrumb, heading, action states và compact responsive layout.
- **Table:** sorting/filtering có phân trang server-side hoặc data source có quyền; không tải toàn bộ học sinh để filter browser nếu backend có list API.
- **Dialog:** destructive/archive/transfer phải có confirmation nội dung tác động; Enter/Escape, focus trap và return focus.
- **Toast:** chỉ khi mutation success; unknown outcome phải hiện “Cần kiểm tra kết quả” cùng reconciliation path.
- **Unauthorized/empty:** hiển thị trạng thái có ý nghĩa; không tiết lộ tên tài nguyên ngoài quyền.
- **Error boundary:** lỗi route, API 503, session expired/refresh failed; không fallback fixture.
- **Skeleton/loading:** tránh layout shift; hiển thị sau server data arrival.

## 7. Accessibility test checklist

- Mọi input có label, error liên kết `aria-describedby`, và thông báo form failure được focus/announced.
- Keyboard tab order hợp lý, dialog trap/return focus, dropdown có thể dùng bàn phím.
- Tương phản và target size đủ dùng; viewport 320/390/768/1440 được kiểm tra theo kế hoạch, **không tự nhận WCAG certification**.
- Có visible focus; không chỉ phân biệt trạng thái bằng màu; disabled controls phải giải thích lý do nếu quyền hạn.

## 8. Đối chiếu prototype

Repo có bộ UI lớn và `FRONTEND_COMPLETION.md` mô tả mock route/visual QA. Mock screenshot được dùng tham khảo layout, nhưng **không** chứng nhận backend. Những page Future phải hiển thị chưa khả dụng trong live mode; không tự bật dựa vào việc route đã tồn tại.