# Danh mục công việc — Lumi / RAG Course Assistant

**Trạng thái nguồn chuẩn (2026-10-29):** `main` hiện ở `84490d3`; PR #33 (Web/Core integration), PR #34 (staging Admin bootstrap) và PR #35 (sửa recipient trước lần gửi đầu) đã merge. Không cần chờ review thành viên theo chỉ đạo TV1; self-review cùng CI là quy trình hiện hành, còn policy/data/production gates vẫn giữ nguyên.

### Bằng chứng hiện hành
- PR #33: Core PostgreSQL 16 **360 passed/0 skipped**, Identity public interface **100%**, tổng coverage **88%**; Web 251 test, live build, Compose smoke và Vercel checks xanh.
- PR #34: Core PostgreSQL 16 **368 passed/0 skipped**, total coverage **89%**.
- PR #35: Core PostgreSQL 16 **380 passed/0 skipped**, total coverage **88%**; Web build, Compose smoke và Vercel checks xanh.
- Staging Core API revision `lumi-core-api-00011-xss`, health/DB ready; SMTP version 2 gửi invitation thành công. Admin staging đang `PENDING_VERIFICATION`, chờ người nhận redeem.
- Vercel Production page trả 200 nhưng API fail-closed 503 vì chưa có Core/DB Production riêng. Preview CORS được phép, Production origin bị từ chối. Browser E2E còn chờ người dùng đăng nhập Preview và hoàn tất luồng Admin → Lecturer → Student.

### G1/G2 gates còn mở
School legacy mapping/FK (#13), data-request fulfillment/retention policy (#15), SMTP recovery/retry test (#16), phép đo QAS-05 cô lập (#17), production onboarding (#18), và browser E2E (#21) còn chờ dữ liệu, policy hoặc thao tác operator. Vì vậy **Core G2/TP-01 chưa nghiệm thu đầy đủ**. Document/AI/Learning/Learner Intelligence (#22–#25) vẫn deferred theo quyết định đã chốt. Issue #36 theo dõi enhancement import Excel sau MVP. Các bằng chứng theo task có ngày bên dưới là lịch sử nếu chưa được cập nhật riêng.

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

Repo có Common, Identity, Classroom Admin/access API, Social, Notification inbox/worker, Administration backend, health, migration 0001–0013 và Compose/CI. Administration có import Student CSV/XLSX, staff/role/status/audit và data-request review; phần thiếu policy/executor giữ IN_REVIEW theo quyết định người dùng. Web MVP được khôi phục qua PR #30 và tích hợp live Core ở PR #33. UI demo riêng bị gitignore và không phải Web nghiệp vụ. School legacy mapping, data-request policy, SMTP recovery/retry, Production Core/DB và browser E2E vẫn còn giới hạn hoặc bằng chứng cần bổ sung.

## 3. Ma trận 20 task và phần cần đồng bộ

| Task / giai đoạn | Hiện trạng và việc cần làm | Phụ thuộc / follow-up |
|---|---|---|
| [001 Common](TASK-001-core-common-foundation.md) · G0 | Có nền tảng; giữ DB-based auth/school scope, audit allowlist, không đưa nghiệp vụ lớp vào Common | #13 legacy school scope |
| [002 Identity core](TASK-002-identity-auth-core.md) · G1 | Student activation/recovery và staff identity có trong Core; staff invitation gửi được trên staging; recovery/retry provider test còn mở | #13 mapping, #16 recovery/retry, #18 Production onboarding |
| [003 Identity HTTP](TASK-003-identity-api-router.md) · G1 | Có auth/profile/Student API/OpenAPI; giữ register 403, no-store code, tránh trùng Admin routes | #16 recovery/retry; #21 Preview E2E |
| [004 Identity public/data requests](TASK-004-identity-public-interface.md) · G1 | DTO/helpers và public operations cho Admin/import đã triển khai; fulfillment/retention thật của 4 loại yêu cầu còn thiếu policy/executor | #13 mapping; #15 data-request policy |
| [005 Classroom schema](TASK-005-classroom-models-schema.md) · G1 | Có migration 0008 School/roster/SubjectClass/AUTO-MANUAL/TeachingAssignment; legacy mapping/FK còn pending | #13 mapping/FK |
| [006 Enrollment/transfer](TASK-006-classroom-membership-flow.md) · G1 | Có Admin sync, preview/version confirm, MANUAL và chuyển homeroom/MANUAL giữ lịch sử; Learning attempt policy còn pending | #24 Learning attempt policy |
| [007 Lifecycle/phân công](TASK-007-classroom-lifecycle-colecturer.md) · G1 | Có Admin PRIMARY/ASSISTING, thay giáo viên chính, archive/restore; consumer Learning approval còn pending | #24 Learning approval contract |
| [008 Classroom public/internal](TASK-008-classroom-public-interface.md) · G1 | Có action access, lịch sử cá nhân, school scope và X-Service-Key; consumer grant/grade cần tích hợp | #22–#24 consumers |
| [009 Feed](TASK-009-social-feed.md) · G1 | Feed CRUD/soft-delete, author DTO, cursor/sort và membership/resource checks đã có; PR #10/#33 CI xanh | Issue #14 self-review xong; E2E Web thuộc #21 |
| [010 Comments](TASK-010-social-comments.md) · G1 | Body 1..10.000, class/post/comment checks, Feed public và moderation/outbox | 008/009/012; Learning consumer #24 |
| [011 Calendar](TASK-011-social-calendar.md) · G1 | PRIMARY/ASSISTING, starts_at < ends_at; Core event và Learning projection riêng | Learning API/event thật chưa triển khai (#24) |
| [012 Notification/outbox](TASK-012-notification-module.md) · G1 | Worker chỉ giao V2 có recipient snapshot; V1 legacy được giữ và không phát. Migration regression test xác nhận hành vi này. | Credential email queue có trong #16; không giao V1 từ audience hiện tại |
| [013 Administration/audit](TASK-013-administration-audit.md) · G1 | Staff/status/roles, audit, CSV/XLSX preview/confirm/reconciliation; staging invitation đã gửi. | Password recovery/retry (#16); data-request fulfillment giữ IN_REVIEW (#15) |
| [014 Migrations/seed](TASK-014-core-migrations-db.md) · G2 | Head 0013, downgrade guard, dev/test seed guard; staging bootstrap và recipient correction đã chạy có audit. | Mapping/FK legacy (#13); production onboarding riêng (#18) |
| [015 Security/integration](TASK-015-core-integration-security-tests.md) · G2 | PR #35 CI đạt 380 PostgreSQL 16 tests/0 skip, gồm security/integration matrix. | QAS-05 client latency cần môi trường đo cô lập (#17); browser E2E #21 |
| [016 Compose/health/CI](TASK-016-core-docker-compose-ci.md) · G2 | Compose smoke, health, migration/head và Web build đạt trong CI; staging Core đang ready. | Production Core/DB tách riêng; full Web E2E #21 |
| [017 Document](TASK-017-document-service-design-impl.md) · G3 | Thiết kế trước code; grant/version/retry, notes/bookmarks, revoke và O2 | Core G2, 008/012/018 contracts |
| [018 AI Tutor](TASK-018-ai-service-rag-tutor.md) · G3 | Thiết kế RAG/2 chế độ/chat privacy; hỏi mới–lịch sử, grant hiện hành, đo QAS-06 | Core G2, 008/017; D6 phối hợp 019 |
| [019 Learning](TASK-019-learning-service.md) · G4 | Thiết kế PRIMARY approval, immutable attempt, transfer cutoff, grade version/deadline events | G3 + 006/008/011/012/018 contracts |
| [020 Learner Intelligence/reporting](TASK-020-learner-intelligence-service.md) · G5 | Thiết kế evidence/version, suppression nhóm nhỏ, gợi ý hỗ trợ, báo cáo PDF/Excel | 013/017–019 + Core access |

Phụ thuộc gồm **hợp đồng cần chốt trước** và **triển khai cần tích hợp sau**, không buộc xong tuần tự mọi task. TV2 chốt policy 008 cùng ERD 005–007 để TV3/TV4 làm mock/contract song song; mock không thay bằng chứng nghiệm thu thật.

## 4. Thứ tự sửa và quyết định còn mở

1. School legacy mapping/FK: chờ nguồn dữ liệu trường có thẩm quyền (#13); giữ scope chưa map và không tự thêm FK.
2. Limiter/idempotency hiện giữ một worker theo quyết định MVP; chỉ mở rộng khi có scale target cụ thể.
3. SMTP invitation đã gửi trên staging; hoàn tất password recovery/retry test (#16). Data request giữ `IN_REVIEW` đến khi operator chốt policy/executor (#15).
4. Document/AI/Learning/Learner Intelligence vẫn deferred theo #22–#25; không tự đặt transfer cutoff, retention hay quyền lịch sử.
5. QAS-05 cần đo client latency trên môi trường cô lập (#17); browser E2E cần người dùng đăng nhập Preview và redeem invitation (#21). Self-review + CI thay cho việc chờ review thành viên.

## 5. Điều kiện đóng task

- [ ] Rule ID, module owner và contract nhất quán; chốt PENDING DESIGN trước triển khai phụ thuộc.
- [ ] Code/API/schema thật đáp ứng tiêu chí; không import private module hoặc SQL xuyên service.
- [ ] Backend kiểm tra role/status/school/resource hiện hành; lịch sử cá nhân và source grant có test riêng.
- [ ] Migration mới/test/Web cần thiết đi cùng feature; không sửa migration đã áp dụng hoặc lấy demo local thay Web chính thức.
- [ ] Ghi command, môi trường/revision và kết quả thực chạy; skip/mock/lịch sử không thay bằng chứng mới.
- [x] Shared/API/permission changes đã self-review theo contract, quyền hiện hành và CI; không chờ review thành viên theo chỉ đạo TV1. Không commit secret, mã một lần hoặc nội dung riêng tư.
