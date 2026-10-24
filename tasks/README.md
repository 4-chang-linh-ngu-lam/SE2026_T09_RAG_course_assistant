# Danh mục công việc — Lumi / RAG Course Assistant

**Cập nhật nhánh `core_full` ngày 24/10/2026:** Web đã nối 63 public operation Core và 27 public operation Document; TASK-017 đã có backend, worker và UI live. Core head `0013`, Document head `document_0003`. Xem [hướng dẫn chạy/trải nghiệm](../docs/LOCAL_DEVELOPMENT.md), [bằng chứng Document](../apps/web/docs/DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md) và [báo cáo đồng bộ main](../docs/CORE_MAIN_MERGE_2026-10-24.md). Các số liệu bàn giao main/TV4 ngày 19/10 bên dưới là lịch sử; AI/RAG TASK-018, owner review và các gate production còn riêng.

**Trạng thái Core trên `main` commit `2f7d70a` (2026-10-19):** Backend TASK-001–016 đã có triển khai. Full suite trên PostgreSQL 16 đạt **342 passed, 0 skipped**; [CI PR #10](https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant/actions/runs/39157402992) đạt `core-tests`, `compose-smoke`, `web-build` trên head `bb7f88d` trước squash merge. [Bàn giao task 001–015](TV4_BACKEND_HANDOVER.md) ghi bằng chứng và giới hạn. Đây chưa phải nghiệm thu toàn Core G2 hoặc owner approval.

**Rà soát đồng bộ: 2026-10-16.** Cả TASK-001–020 có mục **Rà soát đồng bộ** ghi hiện trạng, việc cần sửa, phụ thuộc và nghiệm thu bổ sung. Đây là kế hoạch theo code trong workspace, không phải xác nhận phần còn thiếu đã triển khai.

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

Repo có Common, Identity, Classroom Admin/access API, Social, Notification inbox/worker, Administration backend, health, migration Core 0001–0013 và Compose/CI. Administration có import Student CSV/XLSX, staff/role/status/audit và data-request review; phần thiếu policy/executor giữ IN_REVIEW theo người dùng. Document đã có API/storage/worker/notes/bookmarks và Web live; AI, Learning, Learner Intelligence chưa triển khai trong bản này. UI demo riêng bị gitignore không thay Web nghiệp vụ. Bằng chứng Core–Document/Web có trong các báo cáo liên kết ở đầu tài liệu; owner review, dữ liệu School thực và các workflow service còn thiếu vẫn cần nghiệm thu riêng.

## 3. Ma trận 20 task và phần cần đồng bộ

| Task / giai đoạn | Hiện trạng và việc cần làm | Phụ thuộc / reviewer |
|---|---|---|
| [001 Common](TASK-001-core-common-foundation.md) · G0 | Có nền tảng; giữ DB-based auth/school scope, audit allowlist, không đưa nghiệp vụ lớp vào Common | TV1 + owner shared; mapping 005/014 |
| [002 Identity core](TASK-002-identity-auth-core.md) · G1 | Có Student activation/recovery, staff email; tích hợp mapping legacy, giữ flow đã kiểm thử | 004/005/013/014; TV1/TV2/TV4 |
| [003 Identity HTTP](TASK-003-identity-api-router.md) · G1 | Có auth/profile/Student API/OpenAPI; giữ register 403, no-store code, tránh trùng Admin routes | 002/004/013/016; TV1/TV4 |
| [004 Identity public/data requests](TASK-004-identity-public-interface.md) · G1 | DTO/helpers và public operations cho Admin/import đã triển khai; fulfillment/retention thật của 4 loại yêu cầu còn thiếu policy/executor | 002/013; TV1/TV4 |
| [005 Classroom schema](TASK-005-classroom-models-schema.md) · G1 | Có migration 0008 School/roster/SubjectClass/AUTO-MANUAL/TeachingAssignment; còn mapping trường cho user cũ | 004/014; TV2/TV1/TV4 |
| [006 Enrollment/transfer](TASK-006-classroom-membership-flow.md) · G1 | Có Admin sync, preview/version confirm, MANUAL và chuyển homeroom/MANUAL giữ lịch sử; Learning attempt policy còn pending | 005/008/012/019; TV2/TV4 |
| [007 Lifecycle/phân công](TASK-007-classroom-lifecycle-colecturer.md) · G1 | Có Admin PRIMARY/ASSISTING, thay giáo viên chính, archive/restore; consumer Learning approval còn pending | 005/006/008/019; TV2/TV1 |
| [008 Classroom public/internal](TASK-008-classroom-public-interface.md) · G1 | Có action access, lịch sử cá nhân, school scope và X-Service-Key; consumer grant/grade cần tích hợp | 001/004/005–007; TV2 + consumers |
| [009 Feed](TASK-009-social-feed.md) · G1 | Feed CRUD/soft-delete, author DTO, cursor/sort và membership/resource checks đã có | Owner review shared/action contracts còn cần ghi nhận; TV3/TV1/TV2 |
| [010 Comments](TASK-010-social-comments.md) · G1 | Body 1..10.000, class/post/comment checks, Feed public và moderation/outbox | 008/009/012; TV3/TV2/TV4 |
| [011 Calendar](TASK-011-social-calendar.md) · G1 | PRIMARY/ASSISTING, starts_at < ends_at; Core event và Learning projection riêng | 007/008/012; contract 019 khi tích hợp |
| [012 Notification/outbox](TASK-012-notification-module.md) · G1 | API/worker/snapshot/watermark đã triển khai; worker chỉ giao V2 có recipient snapshot, giữ V1 legacy không phát để tránh sai người nhận | Review event contracts và quyết định xử lý backlog V1 nếu DB thực có; TV4 |
| [013 Administration/audit](TASK-013-administration-audit.md) · G1 | Đã triển khai staff/status/roles, audit theo trường, CSV/XLSX preview/confirm atomic/retry và review data requests; 38 test Administration đạt PostgreSQL | Review TV1/TV2/shared; fulfillment chưa đủ điều kiện giữ IN_REVIEW theo người dùng |
| [014 Migrations/seed](TASK-014-core-migrations-db.md) · G2 | Head 0012 tại bàn giao TV4; TASK-017 nâng Core lên 0013 và thêm receipt downgrade guard; CLI mapping/seed dev/test giữ nguyên | Mapping dữ liệu thực/FK cần TV1/TV2 duyệt; chưa có production onboarding |
| [015 Security/integration](TASK-015-core-integration-security-tests.md) · G2 | Backend-only: 342 test PG16, 300 thao tác cạnh tranh, CI xanh; tải follow-up 56.229 request, backend p95 18,79 ms/client p95 1,17 giây | Web E2E ngoài scope; user-facing SLO/full TP-01, owner review và service còn pending |
| [016 Compose/health/CI](TASK-016-core-docker-compose-ci.md) · G2 | Core wheel/Compose/health/CI đã chạy trên PR #10: `core-tests`, `compose-smoke`, `web-build` xanh | Full G2 và Web nghiệp vụ chưa nghiệm thu; mỗi revision mới cần CI riêng |
| [017 Document](TASK-017-document-service-design-impl.md) · G3 | Đã triển khai backend/worker, 27 public API và UI live: grant/version/retry, notes/bookmarks, revoke và O2; bằng chứng ở báo cáo TASK-017 | Owner review; AI index/retrieval thuộc TASK-018 |
| [018 AI Tutor](TASK-018-ai-service-rag-tutor.md) · G3 | Thiết kế RAG/2 chế độ/chat privacy; hỏi mới–lịch sử, grant hiện hành, đo QAS-06 | Core G2, 008/017; D6 phối hợp 019 |
| [019 Learning](TASK-019-learning-service.md) · G4 | Thiết kế PRIMARY approval, immutable attempt, transfer cutoff, grade version/deadline events | G3 + 006/008/011/012/018 contracts |
| [020 Learner Intelligence/reporting](TASK-020-learner-intelligence-service.md) · G5 | Thiết kế evidence/version, suppression nhóm nhỏ, gợi ý hỗ trợ, báo cáo PDF/Excel | 013/017–019 + Core access |

Phụ thuộc gồm **hợp đồng cần chốt trước** và **triển khai cần tích hợp sau**, không buộc xong tuần tự mọi task. TV2 chốt policy 008 cùng ERD 005–007 để TV3/TV4 làm mock/contract song song; mock không thay bằng chứng nghiệm thu thật.

## 4. Thứ tự sửa và quyết định còn mở

1. TV1/TV2 duyệt ERD/manifest School trên dữ liệu thật, rồi mới apply mapping và thêm constraint `users.school_id`; giữ nguyên ID/hash/status và không tự gán scope.
2. TV1/TV2/TV4 chốt yêu cầu nhiều worker/restart trước khi thay limiter hoặc idempotency RAM; import confirm đã có kết quả bền vững riêng.
3. TV1/TV4 chốt quy trình SMTP credential delivery/reissue và policy xác minh, fulfillment/retention cho data requests trước khi xử lý dữ liệu học sinh thật. Giữ `IN_REVIEW` khi chưa có executor.
4. TV2 cùng owner Learning/Document/AI chốt transfer cutoff, timed attempt, source grant, grading và lịch sử cá nhân; kiểm thử consumer thật trong TASK-017–019. Không tự đặt thời hạn phúc khảo.
5. Đồng bộ checklist lịch sử trong từng task với code/test và CI PR #10; lấy owner review cho shared/API/schema, đo lại client latency trên môi trường riêng trước khi nghiệm thu G2/full TP-01.

## 5. Điều kiện đóng task

- [ ] Rule ID, module owner và contract nhất quán; chốt PENDING DESIGN trước triển khai phụ thuộc.
- [ ] Code/API/schema thật đáp ứng tiêu chí; không import private module hoặc SQL xuyên service.
- [ ] Backend kiểm tra role/status/school/resource hiện hành; lịch sử cá nhân và source grant có test riêng.
- [ ] Migration mới/test/Web cần thiết đi cùng feature; không sửa migration đã áp dụng hoặc lấy demo local thay Web chính thức.
- [ ] Ghi command, môi trường/revision và kết quả thực chạy; skip/mock/lịch sử không thay bằng chứng mới.
- [ ] Shared/API/permission changes có owner consumer review trong PR; không commit secret, mã một lần hoặc nội dung riêng tư.
