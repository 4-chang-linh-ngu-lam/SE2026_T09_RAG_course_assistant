# Danh mục công việc — Lumi / RAG Course Assistant

**Trạng thái nguồn chuẩn (2026-10-30):** `main` hiện ở `ec10fa9`; PR #33 (Web/Core integration), PR #34 (staging Admin bootstrap) và PR #35 (sửa recipient trước lần gửi đầu) đã merge. Không cần chờ review thành viên theo chỉ đạo TV1; self-review cùng CI là quy trình hiện hành, còn policy/data/production gates vẫn giữ nguyên.

### Bằng chứng hiện hành
- PR #33: Core PostgreSQL 16 **360 passed/0 skipped**, Identity public interface **100%**, tổng coverage **88%**; Web 251 test, live build, Compose smoke và Vercel checks xanh.
- PR #34: Core PostgreSQL 16 **368 passed/0 skipped**, total coverage **89%**.
- PR #35: Core PostgreSQL 16 **380 passed/0 skipped**, total coverage **88%**; Web build, Compose smoke và Vercel checks xanh.
- Issue #17 Core-06 subset (2026-10-30, CKEY VM KR with provider-shared host not isolated, main `ec10fa9`, PostgreSQL 16.15/migration 0013): **58.521/58.521 HTTP 200**, backend p95 **21,84 ms**, client loopback p95 **672,04 ms**, client max **4,65 giây**, scope mismatch **0**; Core class-list threshold đạt theo harness. Host-side CPU/RAM utilization không được đo. Đây không phải user-facing/Cloud Run p95 và không xác nhận full TP-01 (`full_tp01_verified=false`). Xem [report](../services/core/test-evidence/task015/core-load-ckey-2026-10-30.json).
- Working-tree Core verification (2026-10-30, CKEY PostgreSQL 16.15/Python 3.12.16): migration 0014 `upgrade head` + `alembic check`, synthetic mapping/FK validation regression, Ruff check/format and **381 passed, 0 failed**. Sau đó production-bootstrap regression riêng trên PostgreSQL 16 Neon staging đạt **8 passed**; fixture chỉ tạo/xóa DB `test_maintenance_*` riêng.
- Staging Core API revision `lumi-core-api-00011-xss`, health/DB ready; SMTP version 2 đã gửi invitation, người nhận redeem và Admin staging ở trạng thái ACTIVE/email verified. Issue #16 đóng sau khi có recovery-delivery và retry/reissue coverage.
- Production mock: Neon PostgreSQL 16 `lumi-production-mock/neondb` đã migrate tới head 0014; Cloud Run `lumi-core-api-production` revision `lumi-core-api-production-00001-qcm`, `/health/live`, `/health/ready`, `/docs`, và Vercel Production CORS preflight đều 200. Admin pending và Lumi Mock School đã bootstrap; worker batch thành công, chưa xác minh người nhận thấy email.
- Vercel Production `CORE_API_URL`/`WEB_ORIGIN` đã áp dụng, Preview vẫn giữ Core staging. Sau redeploy, trang trả 200 và `/api/v1/auth/refresh` qua proxy trả `401 UNAUTHENTICATED` khi không có session, không còn upstream 503.
- Production image được build từ working tree chưa commit/push (`production-mock-20261030`); GitHub `main` vẫn `ec10fa9`. Trước lần build/deploy tiếp theo cần đồng bộ source để runtime không lệch repo.
- Browser E2E Preview: Admin tạo lớp AUTO nối homeroom/giáo viên; Teacher thấy lớp và trạng thái archive; Student mở lớp trước archive và sau đó dashboard còn 0 lớp hoạt động. Thông báo test của Teacher/Student đã đọc; lớp test được archive. Activation/redeem invitation và full workflow acceptance chưa kiểm tra.

### G1/G2 gates còn mở
School mapping (#13) được TV1 xác nhận hoàn tất và issue đã đóng theo chỉ đạo; chi tiết manifest không lưu trong repo/issue. Production mock chưa có legacy user rows để backfill; nhập tài khoản tương lai vẫn cần report/plan/apply với manifest có thẩm quyền. Policy thủ công cho ACCESS/EXPORT/CORRECTION của #15 đã được duyệt và kiểm thử; DELETE/retention liên service tiếp tục deferred. Core Production/bootstrap #18 đã triển khai với `Lumi Mock School`; Vercel proxy đã nối Core, còn browser acceptance đầy đủ (#21) cần redeem Admin và chạy luồng người dùng. SMTP invitation/recovery/retry (#16) đã được kiểm thử staging và đóng. Issue #17 đóng sau benchmark Core class-list subset; **full Core G2/TP-01 vẫn chưa nghiệm thu đầy đủ**. Document/AI/Learning/Learner Intelligence (#22–#25) vẫn deferred theo quyết định đã chốt. Issue #36 theo dõi enhancement import Excel sau MVP. Các bằng chứng theo task có ngày bên dưới là lịch sử nếu chưa được cập nhật riêng.

## 1. Nguồn chuẩn và phạm vi

1. [Business Rules](../docs/architect/BUSINESS_RULES.md) quyết định nghiệp vụ; không sửa rule để khớp code.
2. [ADR-001](../docs/architect/microservices-v1/ADR-001.md), [Architecture](../docs/architect/microservices-v1/ARCHITECTURE.md) quyết định ranh giới năm service.
3. [Core Design](../docs/architect/microservices-v1/core/DESIGN.md), [API Contract](../docs/architect/microservices-v1/core/API_CONTRACT.md), [Folder Structure](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md) hướng dẫn triển khai Core; phân biệt IMPLEMENTED/PROPOSED/LEGACY.
4. [Roadmap](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md), [Quality Attributes](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md), [Contributing](../docs/CONTRIBUTING.md) quy định gate, bằng chứng và review.
5. [Core README](../services/core/README.md) mô tả command, public signatures và giới hạn thực tế. Checklist/bằng chứng có ngày trong task là lịch sử của phạm vi được ghi, không tự áp dụng cho revision mới.

Lumi phục vụ một trường THCS/THPT, khối 6–12. Giữ ba role ADMIN/LECTURER/STUDENT; co-teacher là assignment theo lớp. Admin cấp Student username/mã kích hoạt, quản lý roster, phân công, enrollment AUTO/MANUAL và archive/restore. Không triển khai join code, teacher-created class, Student self-join/leave hay teacher ownership transfer trong MVP.

## 2. Ownership và hiện trạng

| Owner | Sở hữu chính | Phối hợp |
|---|---|---|
| TV1 | Identity, user/token/data request, auth/security Common | TV2 về school scope, TV4 về Admin/import/migration/CI |
| TV2 | Classroom: School/năm học/lớp hành chính/roster/lớp môn học, phân công, enrollment và access policy | TV1/TV3/TV4 và consumer liên service |
| TV3 | Social: feed/comments/calendar | Classroom public, Identity DTO, Notification |
| TV4 | Notification, Administration, tích hợp/audit, migration/Compose/CI | Các owner domain; không sở hữu thay user/roster |
| Chưa phân công cụ thể | Document, AI, Learning, Learner Intelligence | Chốt owner trước triển khai từng giai đoạn |

Repo main có Common, Identity, Classroom Admin/access API, Social, Notification inbox/worker, Administration backend, health, migration 0001–0013 và Compose/CI; working tree hiện có thêm migration 0014. Administration có import Student CSV/XLSX, staff/role/status/audit và data-request review; ACCESS/EXPORT/CORRECTION có quy trình Admin thủ công, DELETE/retention vẫn giữ IN_REVIEW. Web MVP được khôi phục qua PR #30 và tích hợp live Core ở PR #33. UI demo riêng bị gitignore và không phải Web nghiệp vụ. Production mock API/bootstrap đã triển khai; #13 đóng theo xác nhận TV1, còn browser E2E đầy đủ cần hoàn tất. Image Production hiện chưa đồng bộ với source trên GitHub main.

## 3. Ma trận 20 task và phần cần đồng bộ

| Task / giai đoạn | Hiện trạng và việc cần làm | Phụ thuộc / follow-up |
|---|---|---|
| [001 Common](TASK-001-core-common-foundation.md) · G0 | Có nền tảng; giữ DB-based auth/school scope, audit allowlist, không đưa nghiệp vụ lớp vào Common | #13 legacy school scope |
| [002 Identity core](TASK-002-identity-auth-core.md) · G1 | Student activation/recovery và staff identity có trong Core; Gmail staging delivery/retry/reissue đã xác nhận qua issue #16 | #13 mapping thật; #18 Production Admin mock bootstrap |
| [003 Identity HTTP](TASK-003-identity-api-router.md) · G1 | Có auth/profile/Student API/OpenAPI; giữ register 403, no-store code, tránh trùng Admin routes | #21 Preview E2E |
| [004 Identity public/data requests](TASK-004-identity-public-interface.md) · G1 | DTO/helpers và manual attestation ACCESS/EXPORT/CORRECTION đã được kiểm thử PostgreSQL; DELETE/retention còn deferred | #13 mapping thật; #15 Web Admin integration |
| [005 Classroom schema](TASK-005-classroom-models-schema.md) · G1 | Migration 0014 nullable FK và synthetic mapping/validation regression đạt PostgreSQL 16.15; mapping thật chưa có | #13 authoritative mapping |
| [006 Enrollment/transfer](TASK-006-classroom-membership-flow.md) · G1 | Có Admin sync, preview/version confirm, MANUAL và chuyển homeroom/MANUAL giữ lịch sử; Learning attempt policy còn pending | #24 Learning attempt policy |
| [007 Lifecycle/phân công](TASK-007-classroom-lifecycle-colecturer.md) · G1 | Có Admin PRIMARY/ASSISTING, thay giáo viên chính, archive/restore; consumer Learning approval còn pending | #24 Learning approval contract |
| [008 Classroom public/internal](TASK-008-classroom-public-interface.md) · G1 | Có action access, lịch sử cá nhân, school scope và X-Service-Key; consumer grant/grade cần tích hợp | #22–#24 consumers |
| [009 Feed](TASK-009-social-feed.md) · G1 | Feed CRUD/soft-delete, author DTO, cursor/sort và membership/resource checks đã có; PR #10/#33 CI xanh | Issue #14 self-review xong; E2E Web thuộc #21 |
| [010 Comments](TASK-010-social-comments.md) · G1 | Body 1..10.000, class/post/comment checks, Feed public và moderation/outbox | 008/009/012; Learning consumer #24 |
| [011 Calendar](TASK-011-social-calendar.md) · G1 | PRIMARY/ASSISTING, starts_at < ends_at; Core event và Learning projection riêng | Learning API/event thật chưa triển khai (#24) |
| [012 Notification/outbox](TASK-012-notification-module.md) · G1 | Worker chỉ giao V2 có recipient snapshot; V1 legacy được giữ và không phát. Migration regression test xác nhận hành vi này. | Credential email queue có trong #16; không giao V1 từ audience hiện tại |
| [013 Administration/audit](TASK-013-administration-audit.md) · G1 | Staff/status/roles, audit, CSV/XLSX preview/confirm/reconciliation; staging invitation/recovery delivery verified; manual resolution attestation đang được đồng bộ. | DELETE/retention và Web Admin integration (#15) |
| [014 Migrations/seed](TASK-014-core-migrations-db.md) · G2 | Working tree có FK nullable 0014, Core 381 passed; Production mock migrate/bootstrap và schema check đạt; #13 đóng theo xác nhận TV1 | Publish image source đồng bộ trước deploy tiếp; manifest riêng chỉ cần cho future backfill |
| [015 Security/integration](TASK-015-core-integration-security-tests.md) · G2 | PR #35 CI đạt 380 PostgreSQL 16 tests/0 skip, gồm security/integration matrix. | QAS-05 client latency cần môi trường đo cô lập (#17); browser E2E #21 |
| [016 Compose/health/CI](TASK-016-core-docker-compose-ci.md) · G2 | Compose smoke, health, migration/head, Web build CI đạt; Staging và Core Production mock ready. | Vercel reauth/redeploy; full Web E2E #21 |
| [017 Document](TASK-017-document-service-design-impl.md) · G3 | Thiết kế trước code; grant/version/retry, notes/bookmarks, revoke và O2 | Core G2, 008/012/018 contracts |
| [018 AI Tutor](TASK-018-ai-service-rag-tutor.md) · G3 | Thiết kế RAG/2 chế độ/chat privacy; hỏi mới–lịch sử, grant hiện hành, đo QAS-06 | Core G2, 008/017; D6 phối hợp 019 |
| [019 Learning](TASK-019-learning-service.md) · G4 | Thiết kế PRIMARY approval, immutable attempt, transfer cutoff, grade version/deadline events | G3 + 006/008/011/012/018 contracts |
| [020 Learner Intelligence/reporting](TASK-020-learner-intelligence-service.md) · G5 | Thiết kế evidence/version, suppression nhóm nhỏ, gợi ý hỗ trợ, báo cáo PDF/Excel | 013/017–019 + Core access |

Phụ thuộc gồm **hợp đồng cần chốt trước** và **triển khai cần tích hợp sau**, không buộc xong tuần tự mọi task. TV2 chốt policy 008 cùng ERD 005–007 để TV3/TV4 làm mock/contract song song; mock không thay bằng chứng nghiệm thu thật.

## 4. Thứ tự sửa và quyết định còn mở

1. School mapping #13: TV1 xác nhận mapping với trường thật hoàn tất và issue đóng. Không lưu manifest hoặc dữ liệu cá nhân trong repo; FK nullable 0014 đã migrate vào Production mock, hiện chưa có legacy user rows. Backfill khi có tài khoản thực vẫn cần manifest được kiểm soát và report/plan/apply.
2. Limiter/idempotency hiện giữ một worker theo quyết định MVP; chỉ mở rộng khi có scale target cụ thể.
3. SMTP invitation/recovery/retry đã được xác nhận trên staging (#16 đóng). ACCESS/EXPORT/CORRECTION dùng quy trình Admin thủ công đã duyệt; DELETE giữ `IN_REVIEW` đến khi chốt retention và dọn dữ liệu xuyên service (#15).
4. Document/AI/Learning/Learner Intelligence vẫn deferred theo #22–#25; không tự đặt transfer cutoff, retention hay quyền lịch sử.
5. Issue #17 đã có benchmark Core subset trên máy CKEY cô lập; full TP-01/user-facing SLO vẫn chưa được xác nhận. #21 còn cần hoàn tất browser workflow acceptance trên Preview; Admin đã redeem invitation và role E2E đã chạy một phần. Self-review + CI thay cho việc chờ review thành viên.

## 5. Điều kiện đóng task

- [ ] Rule ID, module owner và contract nhất quán; chốt PENDING DESIGN trước triển khai phụ thuộc.
- [ ] Code/API/schema thật đáp ứng tiêu chí; không import private module hoặc SQL xuyên service.
- [ ] Backend kiểm tra role/status/school/resource hiện hành; lịch sử cá nhân và source grant có test riêng.
- [ ] Migration mới/test/Web cần thiết đi cùng feature; không sửa migration đã áp dụng hoặc lấy demo local thay Web chính thức.
- [ ] Ghi command, môi trường/revision và kết quả thực chạy; skip/mock/lịch sử không thay bằng chứng mới.
- [x] Shared/API/permission changes đã self-review theo contract, quyền hiện hành và CI; không chờ review thành viên theo chỉ đạo TV1. Không commit secret, mã một lần hoặc nội dung riêng tư.
