# TASK-015: Core Comprehensive Security & Integration Test Suite

- **Mã Task:** `TASK-015`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `Cả nhóm (TV1, TV2, TV3, TV4)`
- **Module:** `services/core/tests/`
- **Business Rules:** `A1–A8`, `F1–F5`, `H1–H5`, `K2–K5`, `L1–L3`, `M1–M2`, `M5`, `O2`, `O4`
- **Quality Attributes:** `QAS-04`, `QAS-05`, `Core-01` đến `Core-06`
- **Tài liệu căn cứ:** [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#6-kiểm-thử-core-g1g2), [IMPLEMENTATION_ROADMAP.md](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md#checklist-nghiệm-thu-core)


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** repo có test Common/Identity/health/migration; chưa có bộ Classroom/Social/Notification/Administration vì nghiệp vụ chưa triển khai. Số test/coverage đã ghi là bằng chứng cho phạm vi đó, không phải Core-01–06 đầy đủ.

**Cần sửa:** thay concurrent join approval/ownership transfer và E2E xin mã vào lớp bằng Admin provisioning, roster AUTO/MANUAL, teaching assignment và transfer; tách lịch sử cá nhân khỏi quyền tham gia lớp hiện tại.

**Phụ thuộc:** mỗi owner bổ sung test cùng TASK-001–014; TASK-016 chạy suite trên PostgreSQL 16 và môi trường Compose sạch. Thiết kế chưa chốt phải có contract/fixture được duyệt trước nghiệm thu.

---

## 1. Mục tiêu

Kiểm chứng Core theo QAS-04/QAS-05 và Core-01–06 bằng PostgreSQL thực, test HTTP/public interface và E2E Web → Core → DB. Demo cá nhân bị gitignore chỉ hỗ trợ kiểm thử cục bộ; luồng UI chính thức còn phải được tích hợp trong apps/web.

## 2. Kịch bản bắt buộc

### 2.1. Quyền và dữ liệu — Core-01/QAS-04

- Cross-school/class/user/resource, scope null, ID giả và quyền đổi sau khi phát hành JWT; LOCKED/PENDING không vượt qua auth.
- Chỉ Admin tạo lớp, roster, phân công, ghi danh, chuyển lớp và archive/restore; Student không self-register/join/leave; Lecturer không dùng global role để tự cấp quyền.
- Membership kết thúc chặn nội dung mới/participation/AI mới; owner đọc bài đã nộp/điểm/chat/notes/appeal theo action giới hạn. Document source vẫn cần grant hiện hành, Admin không mặc định đọc private chat.
- ARCHIVED chặn hoạt động chung; ngoại lệ notes/bookmarks cá nhân theo O2 được kiểm thử ở Document khi có service, không coi mock là E2E đã chạy.

### 2.2. Cạnh tranh và toàn vẹn — Core-02

- 100 thao tác sync/transfer/import cạnh tranh có kiểm soát: một membership hiện hành/cặp, giữ lịch sử, không ghi đè MANUAL.
- MANUAL→AUTO preview/confirm, preview stale, duplicate confirm, retry sau mất phản hồi/restart; kiểm chứng bảo đảm idempotency theo thiết kế đã duyệt.
- Thay giáo viên chính cạnh tranh giữ H2; assignment cũ hết hiệu lực, consumer không tiếp tục cấp quyền cũ.
- Import CSV/Excel lỗi/trùng/re-import và rollback theo batch contract; không cache/phát lại activation code như response thường.

### 2.3. Xác thực — Core-03

- Student không email: provision/reissue/activate/login/refresh/Admin recovery; expiry/purpose/replay/username duplicate, không tự mở LOCKED; staff email auth vẫn hoạt động.
- Legacy migration giữ ID/hash/dữ liệu, chỉ chuyển bằng Admin cùng trường; email token cũ không bypass Student activation.
- Refresh rotation/family replay, logout-all/password/status/role revocation, cookie attributes/clear, CSRF Origin/Referer, limiter và stale idempotency response.
- Register request hợp lệ luôn 403; activation/login/reset đúng giới hạn, không dùng test register 201 như luồng phát hành.

### 2.4. Tích hợp — Core-04

- Admin provision → Student activate → Admin roster/AUTO hoặc MANUAL → thông báo → Student feed/comment/calendar → moderation có audit → transfer/archive.
- Kiểm tra relation class–post–comment, soft delete list/detail, recipient-only notification, worker retry/crash/dedup và producer rollback.
- Admin role/lock/data request ACCESS/EXPORT/CORRECTION/DELETE có xác minh, audit/redaction, không tự xóa liên service.
- Calendar LEARNING read-only; duplicate/out-of-order deadline và notification đúng contract. Learning chưa triển khai thì chỉ ghi kết quả contract/projection test.
- Bộ test hợp đồng bảo vệ module boundaries; không có import repository/model chéo hoặc SQL xuyên service.

### 2.5. Hạ tầng và hiệu năng — Core-05/06

- TASK-014/016: upgrade/drift/legacy data preservation, clean Compose startup, installed wheel/non-root, readiness DB/schema, outage/recovery, lint/format/OpenAPI và coverage gates.
- Đo p95 danh sách lớp ≤500 ms và thành công ≥99% theo TP-01 sau khi có API danh sách lớp được duyệt; không tự coi GET /classes là route đã triển khai.
- Ghi máy/cấu hình/tải/script và kết quả thật. Không suy ra KPI tải/RAG hoặc toàn bộ G2 chỉ vì unit tests/CI green.

## 3. Tiêu chí nghiệm thu

- [ ] Tất cả module G1 có test chạy thật trên PostgreSQL 16; test DB bị skip không được ghi là đã kiểm chứng.
- [ ] Core-01–06 có ma trận Rule ID → scenario → kết quả và bằng chứng CI/artifact; phần chưa có service được ghi pending.
- [ ] Chạy luồng Web chính thức đầy đủ, contract/public permission nhất quán; không chỉ dựa vào demo-ui local.
- [ ] Không phát hiện rò rỉ trong bộ test; báo rõ phạm vi hữu hạn và lỗi còn lại, không khẳng định bảo đảm tuyệt đối.
