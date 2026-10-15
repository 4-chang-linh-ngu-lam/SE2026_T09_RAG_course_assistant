# TASK-013: Administration Workflows & Core Audit Logging

- **Mã Task:** `TASK-013`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV4` (Phối hợp với `TV1`, `TV2`)
- **Module:** `services/core/app/modules/administration/`
- **Business Rules liên quan:** `F1`, `F2`, `F4`, `F7`, `K1`, `K5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Administration mới có skeleton. Identity đã phục vụ hai API Admin Student và public helpers có authorization/audit; không coi toàn bộ Admin HTTP/role/import/data resolution đã hoàn thành.

**Cần sửa/bổ sung:**
- Student dùng helper provision/issue-code/legacy username đã có; staff dùng email invitation ADMIN/LECTURER. Không cho `/admin/users` tạo Student bằng email hoặc đăng ký lại route Student hiện có.
- Bổ sung workflow CSV/Excel preview → lỗi/trùng → confirm → kết quả/retry an toàn theo F1/F2 và phạm vi MVP. Chốt định danh đối soát/re-import, stale preview, atomicity từng batch, rollback và cấp lại mã; không giữ response chứa code trong cache idempotency.
- Classroom sở hữu School/homeroom/roster/enrollment/teaching assignment; Admin workflow gọi public interface TASK-008, không tự ghi bảng. Bỏ duyệt join/đổi chủ khỏi quy trình can thiệp.
- Mở rộng Identity public cho role management và resolution khi được review; giữ current actor/status/school checks, revocation, chống gỡ Admin cuối bằng kiểm soát cạnh tranh. Không dùng status mutation để bỏ qua activation hoặc xác minh recovery.
- Dùng AuditEvent/record_audit đã có ở Common, không tạo bảng trùng. AuditMetadata hiện chỉ nhận trường allowlist/reason_code, chưa nhận lý do tự do; chốt cách lưu lý do can thiệp/resolution có giới hạn và redaction trước khi nhận X-Admin-Reason, không nhét nguyên header vào metadata.
- Xử lý đủ ACCESS/EXPORT/CORRECTION/DELETE có xác minh, kết quả/lý do/audit. Không tự thực thi xóa toàn bộ, retention hay truy cập private chat; policy chưa duyệt phải giữ pending cho phần liên quan.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] TASK-004/005–008/012/014 chốt public contracts, mapping trường và schema; TV1/TV2/TV4 review trước code workflow tương ứng.
- [ ] Test cross-school, thiếu scope, Admin cuối cạnh tranh, revoke phiên, legacy giữ ID và import trùng/lỗi/retry/stale preview.
- [ ] Test audit cùng transaction/không trùng/không chứa mã hoặc chat; data resolution chỉ xử lý sau xác minh, không đánh dấu COMPLETED trước khi hành động thực tế thành công.

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
  - `action: str` (Ví dụ: `ADMIN_LOCK_USER`, `ADMIN_ASSIGN_ROLE`, `ADMIN_INTERVENE_CLASS`, `DATA_REQUEST_PROCESSED`)
  - `target_type: str` (`USER`, `CLASS`, `DATA_REQUEST`)
  - `target_id: UUID`
  - `correlation_id: UUID`
  - `metadata_json: AuditMetadata` (allowlist hiện có; lý do tự do cần thiết kế lưu an toàn riêng)
  - `occurred_at: datetime` (UTC)
  - Index phục vụ lọc actor/action/thời gian là đề xuất cần review query/migration, không coi đã tồn tại.
  - **Quy tắc bảo mật bất biến:** Tuyệt đối không lưu token, mật khẩu, chat riêng tư vào `metadata_json` (Rule K5, F3).

### 2.2. `schemas.py`
- `AdminCreateUserRequest`: `email: str`, `roles: list[str]` (LECTURER, ADMIN; Student dùng provisioning riêng)
- `AdminUpdateUserStatusRequest`: `status: str` (ACTIVE, LOCKED), `reason: str`
- `AdminUpdateUserRolesRequest`: `roles: list[str]`, `reason: str`
- `AdminDataRequestResolve`: `status: str` (IN_REVIEW, COMPLETED, REJECTED), `resolution_note: str`
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

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Chỉ tài khoản có vai trò hệ thống `ADMIN` mới được gọi các endpoint `/admin/*`. Tài khoản `LECTURER` hay `STUDENT` bị chặn `403 FORBIDDEN`.
- [ ] Khi Admin khóa một tài khoản (`LOCKED`), người dùng đó lập tức không thể đăng nhập hoặc dùng access token cũ để gọi API.
- [ ] Không thể gỡ quyền `ADMIN` của Admin duy nhất còn lại trong hệ thống (báo lỗi `400 BAD_REQUEST`).
- [ ] Mọi hành động của Admin đều sinh ra bản ghi kiểm toán tương ứng trong `audit_events`.
- [ ] Dữ liệu trong `audit_events` không bao giờ chứa thông tin bí mật hay chat riêng tư.
