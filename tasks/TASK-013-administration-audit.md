# TASK-013: Administration Workflows & Core Audit Logging

- **Mã Task:** `TASK-013`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV4` (Phối hợp với `TV1`, `TV2`)
- **Module:** `services/core/app/modules/administration/`
- **Business Rules liên quan:** `F1`, `F2`, `F4`, `F7`, `K1`, `K5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)

## Triển khai và kiểm chứng — 2026-10-18

**Hiện trạng:** Đã triển khai Administration backend: staff invitation, status/role mutations, school-scoped audit API, data-request list/detail/review/reject/defer và import Student CSV/XLSX preview/confirm. Tái sử dụng hai route Student Identity; không tạo route trùng hoặc bảng User/Audit/Roster thứ hai. Migration mới 0012 theo sau 0011, không sửa migration đã áp dụng.

**Quyết định người dùng:** Giữ IN_REVIEW khi chưa đủ chính sách hoặc hành động xử lý thực tế (trả lời ngày 2026-10-18). ACCESS/EXPORT/CORRECTION/DELETE đều có quy trình Admin xác minh/phân loại/reject; request COMPLETED chưa có policy/executor trả trạng thái thực IN_REVIEW, note POLICY_PENDING và audit DEFERRED. Không dùng cờ xác nhận làm bằng chứng đã xóa/xuất/sửa dữ liệu; không tự đặt retention hoặc đọc chat.

**Bằng chứng backend local:** Windows, Python 3.12.14, PostgreSQL 16 container test riêng. `pytest -q -W error -p no:cacheprovider --tb=short`: **290 passed**, không skip; **38 test Administration** gồm parser/contracts và PostgreSQL thật. `pytest tests/identity/test_public.py -q -W error -p no:cacheprovider --cov=app.modules.identity.public --cov-branch --cov-report=term-missing --cov-fail-under=100`: **17 passed**, 100% coverage/branches. `ruff check app tests migrations`, `ruff format --check app tests migrations`, `alembic upgrade head` và `alembic check` đạt; một head `0012`. Tắt cacheprovider vì ACL cache Windows, không tắt test. Chưa dùng kết quả backend local để tuyên bố Web E2E/CI hoặc toàn Core G2 hoàn tất.

**Container smoke:** Docker build Core thành công với wheel và dependencies thực; runtime UID 10001, package nằm trong site-packages, defusedxml bật, OpenAPI có Administration routes. Image chạy `alembic upgrade head`, `alembic check` và Notification worker `--once` thành công trên PostgreSQL 16 test. Đây là smoke Core/package, không phải full-stack Web E2E.

**Owner review còn cần xác nhận sau merge:** TV1 review Identity admin helpers/revocation/last-admin lock; TV2 review public roster append/session ownership và scope audit Classroom; TV3 review scope audit Social; TV4/common owner review audit metadata/index, migration 0012, bootstrap và dependencies openpyxl/defusedxml. CI PR #10 xanh, nhưng CI không thay owner approval. Contract đầy đủ tại [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md#administration--implemented-task-013).

**Quyết định triển khai:**
- Student dùng helper provision/issue-code/legacy username đã có; staff dùng email invitation ADMIN/LECTURER. Không cho `/admin/users` tạo Student bằng email hoặc đăng ký lại route Student hiện có.
- CSV UTF-8/XLSX một worksheet, tối đa 100 dòng/2 MB: preview → lỗi/trùng → confirm nguyên batch → kết quả/retry bền vững. Username là định danh đối soát, user_id hỗ trợ Student legacy; fingerprint và roster_version chống stale. Code chỉ trả lần đầu cho tài khoản mới, không persist/cache; retry/restart cùng preview không cấp lại mã, re-import không tạo trùng hoặc reset credential.
- Classroom sở hữu School/homeroom/roster/enrollment/teaching assignment; Admin workflow gọi public interface TASK-008, không tự ghi bảng. Bỏ duyệt join/đổi chủ khỏi quy trình can thiệp.
- Identity public đã mở rộng role management/import checks/data requests; current actor/status/school checks, revocation và advisory lock chống gỡ/khóa Admin ACTIVE cuối có scope/verify được kiểm thử cạnh tranh. Không dùng status/role mutation để bỏ qua activation hoặc chuyển credential khi thiếu điều kiện.
- Dùng AuditEvent/record_audit Common, thêm school_id/index bằng 0012. X-Admin-Reason và resolution_note chỉ nhận enum code allowlist, không nhận text tự do. Metadata thêm changed_fields=data_request_status và identity_verified dạng cấu trúc; API metadata legacy không hợp lệ trả rỗng, legacy scope null bị ẩn thay vì suy đoán backfill.
- ACCESS/EXPORT/CORRECTION/DELETE có xác minh, phân loại, lý do code/audit; phần thiếu policy/executor giữ IN_REVIEW theo lựa chọn người dùng, không tự báo COMPLETED.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TASK-004/005–008/012/014 chốt public contracts, mapping trường và schema; TV1/TV2/TV4 review trước code workflow tương ứng.
- [x] Test cross-school, thiếu scope, Admin cuối cạnh tranh, revoke phiên, legacy giữ ID và import trùng/lỗi/retry/stale preview.
- [x] Test audit cùng transaction/không trùng/không chứa mã hoặc chat trong các kịch bản đã chạy; không đánh dấu COMPLETED khi chưa có hành động thực tế thành công.
- [x] Test XLSX qua HTTP; import → append roster → AUTO enrollment → outbox → Notification. Inject lỗi outbox rollback user/roster/membership/audit/batch, retry thành công.
- [x] Test confirm đồng thời chỉ một response có code; replay/re-import trả đúng ID và code null; mất code cấp lại qua Identity, mã cũ bị vô hiệu.

---

## 1. Mục tiêu
Xây dựng các chức năng quản trị hệ thống (`Administration`), bao gồm tạo tài khoản bởi Admin (Student username/mã kích hoạt, staff lời mời email), khóa/mở khóa tài khoản, phân bổ vai trò người dùng, xử lý các yêu cầu dữ liệu cá nhân (Data Requests), và hệ thống ghi nhận sự kiện kiểm toán (`Audit Logging`) với yêu cầu ghi nhận lý do can thiệp (`X-Admin-Reason`).

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. Tái sử dụng `common/audit.py`
AuditEvent đã có từ TASK-001/migration 0002 trong schema `core`, không tạo lại model/bảng:
- `AuditEvent`:
  - `id: UUID` (PK)
  - `actor_id: Optional[UUID]` (người thực hiện hoặc NULL nếu hệ thống; model hiện chưa có FK, thay đổi cần migration mới)
  - `school_id: Optional[UUID]` (scope tại thời điểm event từ backend; legacy null không tự backfill, Admin API ẩn)
  - `action: str` (Ví dụ: `ADMIN_LOCK_USER`, `ADMIN_ASSIGN_ROLE`, `ADMIN_INTERVENE_CLASS`, `DATA_REQUEST_PROCESSED`)
  - `target_type: str` (`USER`, `CLASS`, `DATA_REQUEST`)
  - `target_id: UUID`
  - `correlation_id: UUID`
  - `metadata_json: AuditMetadata` (allowlist hiện có; lý do tự do cần thiết kế lưu an toàn riêng)
  - `occurred_at: datetime` (UTC)
  - Index school/time/id, actor/time, action/time đã có trong migration 0012; review query/index cùng feature.
  - **Quy tắc bảo mật bất biến:** Tuyệt đối không lưu token, mật khẩu, chat riêng tư vào `metadata_json` (Rule K5, F3).

### 2.2. `schemas.py`
- `AdminCreateUserRequest`: `email: str`, `roles: list[str]` (LECTURER, ADMIN; Student dùng provisioning riêng)
- `AdminUserStatusRequest`: `status: ACTIVE|LOCKED`; lý do qua header code X-Admin-Reason
- `AdminUserRolesRequest`: danh sách không rỗng/trùng ADMIN/LECTURER/STUDENT; lý do qua header code
- `AdminDataRequestResolve`: `status: IN_REVIEW|COMPLETED|REJECTED`, `resolution_note` enum, `identity_verified` strict bool
- Import request/preview/result DTO theo contract; code field repr=False, không đưa vào durable results
- `AuditEventResponse`: `id: UUID`, `actor_id: Optional[UUID]`, `action: str`, `target_type: str`, `target_id: str`, `metadata_json: dict`, `occurred_at: datetime`

### 2.3. `service.py` & Quy trình nghiệp vụ
- **Admin tạo người dùng (`admin_create_user`):**
  - Kiểm tra quyền: Chỉ tài khoản có vai trò `ADMIN`.
  - Gọi `identity.public.admin_create_user(...)`. Sinh link đặt mật khẩu một lần (OneTimeToken).
  - Dùng audit trong public helper, không ghi trùng.

  **Hợp đồng Identity đã triển khai ở TASK-004:** `public.admin_create_user` và `public.admin_set_user_status` yêu cầu `actor_id` từ authentication, `correlation_id` và hỗ trợ `session=` do workflow sở hữu. Trả DTO/token SecretStr, không trả ORM User; hai hàm đã kiểm tra Admin hiện hành và ghi audit tối thiểu trong cùng transaction. Consumer không import model/repository hoặc tạo audit trùng; tham khảo [Core README](../services/core/README.md#identity-public-interface-và-data-requests-task-004) khi bổ sung lý do can thiệp/role workflows.
- **Khóa / Mở khóa tài khoản (`set_user_status`):**
  - Gọi public helper cập nhật LOCKED/ACTIVE với điều kiện credential/activation hợp lệ; không mở khóa thành đường bỏ qua Student activation.
  - Khi khóa: ngay lập tức vô hiệu hóa các phiên đăng nhập hiện tại bằng cách gọi hàm thu hồi token của Identity.
  - Ghi audit log kèm lý do.
- **Quản lý vai trò (`update_user_roles`):**
  - Quy tắc an toàn: Không được phép gỡ bỏ quyền `ADMIN` của tài khoản Admin cuối cùng trong hệ thống.
  - Ghi audit log.
- **Can thiệp lớp học của Admin:**
  - Khi Admin thực hiện các thao tác quản trị trên lớp (như ghi danh/chuyển lớp, thay phân công giáo viên, archive/restore), yêu cầu header HTTP `X-Admin-Reason`.
  - Thiết kế ghi lý do đã kiểm tra/redact; Common hiện không nhận text tự do, không tự chép nguyên header vào metadata.
- **Xử lý yêu cầu dữ liệu cá nhân (`resolve_data_request`):**
  - Phân loại yêu cầu: `ACCESS`, `EXPORT`, `CORRECTION`, `DELETE`.
  - Ghi chú giải thích lý do xử lý, cập nhật trạng thái `COMPLETED` hoặc `REJECTED` (Rule K1, F4).

### 2.4. `router.py`
Các route dưới prefix `/api/v1/admin`:
- `POST /admin/users`
- `PATCH /admin/users/{id}/status`
- `PUT /admin/users/{id}/roles`
- `GET /admin/audit-events` (Phân trang, lọc theo actor/action/thời gian)
- `GET /admin/data-requests`
- `GET/PATCH /admin/data-requests/{id}`
- `POST /admin/students/imports/preview`
- `POST /admin/students/imports/confirm`

Student import thuộc Administration; `POST /admin/students` và `/admin/students/{id}/activation-codes` tiếp tục do Identity sở hữu. Optional homeroom import chỉ append roster qua public interface, không tự thay teaching assignment/metadata lớp. Classroom administrative APIs hiện có vẫn xử lý các can thiệp đó.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Các endpoint mới Admin-only; Lecturer/Student bị chặn 403, role/status hiện hành ưu tiên JWT, null/cross-school bị che.
- [x] Khóa LOCKED/đổi role thu hồi phiên; access token cũ bị chặn. Mở ACTIVE không bypass activation.
- [x] Không gỡ/khóa Admin ACTIVE cuối cùng có verify/scope trong hệ thống; request đồng thời vẫn giữ một Admin, lỗi 400.
- [x] Mutation và đọc audit/data-request nhạy cảm có audit tối thiểu cùng transaction; không ghi trùng audit của Identity/Classroom.
- [x] Allowlist metadata/reason codes và test redaction chặn secret/chat/code trong phạm vi đã kiểm thử.
