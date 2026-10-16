# Danh mục công việc — Lumi / RAG Course Assistant

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

Repo có Common, Identity, health, migration 0001–0007 và Compose/CI. Classroom/Social/Notification/Administration mới có skeleton, trừ hai API Student do Identity đang phục vụ. Bốn service sau Core chưa có triển khai; apps/web hiện là skeleton. UI demo riêng bị gitignore không phải Web nghiệp vụ đã nghiệm thu.

## 3. Ma trận 20 task và phần cần đồng bộ

| Task / giai đoạn | Hiện trạng và việc cần làm | Phụ thuộc / reviewer |
|---|---|---|
| [001 Common](TASK-001-core-common-foundation.md) · G0 | Có nền tảng; giữ DB-based auth/school scope, audit allowlist, không đưa nghiệp vụ lớp vào Common | TV1 + owner shared; mapping 005/014 |
| [002 Identity core](TASK-002-identity-auth-core.md) · G1 | Có Student activation/recovery, staff email; tích hợp mapping legacy, giữ flow đã kiểm thử | 004/005/013/014; TV1/TV2/TV4 |
| [003 Identity HTTP](TASK-003-identity-api-router.md) · G1 | Có auth/profile/Student API/OpenAPI; giữ register 403, no-store code, tránh trùng Admin routes | 002/004/013/016; TV1/TV4 |
| [004 Identity public/data requests](TASK-004-identity-public-interface.md) · G1 | Có DTO/helpers và 4 loại yêu cầu; bổ sung public operations cho Admin resolution/role/hiển thị khi chốt contract | 002/013; TV1/TV4 |
| [005 Classroom schema](TASK-005-classroom-models-schema.md) · G1 | Thiết kế School/roster/SubjectClass/AUTO-MANUAL/TeachingAssignment, thay schema join/invitation | 004, Core Design; TV2/TV1/TV4 |
| [006 Enrollment/transfer](TASK-006-classroom-membership-flow.md) · G1 | Thay join approval/self-leave bằng Admin sync, preview/confirm, chuyển lớp giữ lịch sử | 005, contract 008/012/013; TV2/TV4 |
| [007 Lifecycle/phân công](TASK-007-classroom-lifecycle-colecturer.md) · G1 | Admin phân công PRIMARY/ASSISTING, thay giáo viên chính, archive/restore | 005/006, policy 008; TV2/TV1 |
| [008 Classroom public/internal](TASK-008-classroom-public-interface.md) · G1 | Action access, lịch sử cá nhân, school scope; dùng X-Service-Key đã có | 001/004 và thiết kế 005–007; TV2 + consumers |
| [009 Feed](TASK-009-social-feed.md) · G1 | Quyền hiện hành, author DTO không buộc email, chốt sort/cursor và parent scope | 004/005/007/008/012; TV3/TV1/TV2 |
| [010 Comments](TASK-010-social-comments.md) · G1 | Body 1..10.000, class/post/comment checks, Feed public và moderation/outbox | 008/009/012; TV3/TV2/TV4 |
| [011 Calendar](TASK-011-social-calendar.md) · G1 | PRIMARY/ASSISTING, starts_at < ends_at; Core event và Learning projection riêng | 007/008/012; contract 019 khi tích hợp |
| [012 Notification/outbox](TASK-012-notification-module.md) · G1 | Enqueue/event ownership, retry/crash/dedup, recipient-only, payload không chứa secret | Producer 006/007/009–011/013 + 014; TV4 |
| [013 Administration/audit](TASK-013-administration-audit.md) · G1 | Student/staff tách luồng, CSV/Excel preview/confirm/retry, role/lock/resolution có audit | 004/005–008/012/014; TV4/TV1/TV2 |
| [014 Migrations/seed](TASK-014-core-migrations-db.md) · G2 | Giữ 0001–0007, revision mới theo domain; mapping School, legacy upgrade, seed an toàn | Model/contract 002/004–013; TV4 + owner |
| [015 Security/integration](TASK-015-core-integration-security-tests.md) · G2 | Thay test legacy bằng Admin enrollment/assignment, current vs historical access, E2E Web | 001–014/016; cả nhóm |
| [016 Compose/health/CI](TASK-016-core-docker-compose-ci.md) · G2 | Có hạ tầng; chạy lại PostgreSQL 16 cho Identity mới, xác nhận CI đúng revision, thêm test module mới | 014/015 và toàn G1; TV4/TV1 |
| [017 Document](TASK-017-document-service-design-impl.md) · G3 | Thiết kế trước code; grant/version/retry, notes/bookmarks, revoke và O2 | Core G2, 008/012/018 contracts |
| [018 AI Tutor](TASK-018-ai-service-rag-tutor.md) · G3 | Thiết kế RAG/2 chế độ/chat privacy; hỏi mới–lịch sử, grant hiện hành, đo QAS-06 | Core G2, 008/017; D6 phối hợp 019 |
| [019 Learning](TASK-019-learning-service.md) · G4 | Thiết kế PRIMARY approval, immutable attempt, transfer cutoff, grade version/deadline events | G3 + 006/008/011/012/018 contracts |
| [020 Learner Intelligence/reporting](TASK-020-learner-intelligence-service.md) · G5 | Thiết kế evidence/version, suppression nhóm nhỏ, gợi ý hỗ trợ, báo cáo PDF/Excel | 013/017–019 + Core access |

Phụ thuộc gồm **hợp đồng cần chốt trước** và **triển khai cần tích hợp sau**, không buộc xong tuần tự mọi task. TV2 chốt policy 008 cùng ERD 005–007 để TV3/TV4 làm mock/contract song song; mock không thay bằng chứng nghiệm thu thật.

## 4. Thứ tự sửa và quyết định còn mở

1. Chốt G0 còn thiếu: ERD School/roster/lớp/phân công, action/error contract và mapping trường cho user cũ; roster API hiện mới PROPOSED.
2. Chốt preview/confirm, định danh re-import, partial failure/retry và idempotency bền vững của import/sync; cache RAM Identity không giải quyết yêu cầu này.
3. Chốt transfer cutoff và timed attempt với Learning; tách participation, lịch sử cá nhân, source grant và grading access. Không tự đặt thời hạn phúc khảo.
4. Triển khai Classroom 005–008, mở rộng public Identity theo consumer; tích hợp 009–013. Mỗi feature đi cùng migration/test, 014/015 tập hợp và kiểm chứng.
5. Chạy 016 trên PostgreSQL 16/Compose và Web chính thức; chỉ nghiệm thu G2 khi toàn checklist Core đạt, rồi mới G3–G5.
6. Trước dữ liệu học sinh thật, người vận hành cần duyệt policy xác minh/căn cứ xử lý/retention; không tự suy đoán thời hạn hoặc tự động xóa liên service.

## 5. Điều kiện đóng task

- [ ] Rule ID, module owner và contract nhất quán; chốt PENDING DESIGN trước triển khai phụ thuộc.
- [ ] Code/API/schema thật đáp ứng tiêu chí; không import private module hoặc SQL xuyên service.
- [ ] Backend kiểm tra role/status/school/resource hiện hành; lịch sử cá nhân và source grant có test riêng.
- [ ] Migration mới/test/Web cần thiết đi cùng feature; không sửa migration đã áp dụng hoặc lấy demo local thay Web chính thức.
- [ ] Ghi command, môi trường/revision và kết quả thực chạy; skip/mock/lịch sử không thay bằng chứng mới.
- [ ] Shared/API/permission changes có owner consumer review trong PR; không commit secret, mã một lần hoặc nội dung riêng tư.
