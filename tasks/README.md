# Danh mục công việc (Task Backlog) — RAG Course Assistant

> **Bản quyền kiến trúc:** Tuân thủ [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md), [ADR-001](../docs/architect/microservices-v1/ADR-001.md), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md), [IMPLEMENTATION_ROADMAP.md](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md).

---

## 1. Nguyên tắc thực hiện Task
1. **Traceability:** Mỗi task tham chiếu chính xác các `Business Rule ID` liên quan. Không tự ý thêm bớt hay sửa đổi Business Rule.
2. **Core hoàn chỉnh trước:** Tập trung hoàn thành G0 $\to$ G1 $\to$ G2 đạt toàn bộ tiêu chí nghiệm thu trước khi chuyển sang các service khác (G3 $\to$ G5).
3. **Ownership & Ranh giới Module:** Không import chéo repository/model nội bộ giữa các module trong Core; giao tiếp qua `public.py`. Không truy cập bảng của service khác.
4. **Bảo mật & Quyền:** Mọi thao tác kiểm tra quyền tại Backend theo vai trò + quyền hiện hành (fail-closed). Admin/Lecturer không mặc định đọc chat AI riêng tư.
5. **Kiểm thử thực tế:** Mọi task hoàn thành phải có unit/integration test chạy thật trên môi trường sạch; không báo hoàn thành nếu thiếu bằng chứng.

---

## 2. Phân công trách nhiệm (Core Phase G1–G2)
| Thành viên | Module chính | Trách nhiệm chính |
|---|---|---|
| **TV1** | `identity` | Xác thực, JWT, bảo mật chung, User, Role, Session |
| **TV2** | `classroom` | Quản lý môn, lớp, thành viên, duyệt đơn, mời co-lecturer, chuyển quyền |
| **TV3** | `social` | Bảng tin (feed), bình luận (comments), lịch lớp (calendar) |
| **TV4** | `notification`, `administration` | Thông báo (dedup/outbox), quản trị Admin, audit Core, Docker Compose, CI & test tích hợp |

---

## 3. Bản đồ Task (Task Matrix)

### Giai đoạn G0: Nền tảng hạ tầng Core
- [TASK-001: Core Common & Security Foundation](TASK-001-core-common-foundation.md) — *Owner: TV1 & Shared* — Hạ tầng `app/common/`: DB Base, config, security (Argon2id, JWT), auth dependencies, error handling, pagination, audit helpers.

### Giai đoạn G1: Xây dựng các Module Core (Phát triển song song theo Vertical Slice)
#### Module Identity (TV1)
- [TASK-002: Identity Models, Repository & Core Auth Service](TASK-002-identity-auth-core.md) — *Owner: TV1* — Rules: `F1, K2`. Xây dựng User, RoleAssignment, AuthSession, OneTimeToken, flow đăng ký, xác minh email, đăng nhập, refresh token rotation, logout-all, reset mật khẩu.
- [TASK-003: Identity API Router & Rate Limiting](TASK-003-identity-api-router.md) — *Owner: TV1* — Router `/auth/*`, `/users/me`, HttpOnly cookie, CSRF/Origin protection, rate-limit.
- [TASK-004: Identity Public Interface & Data Request Management](TASK-004-identity-public-interface.md) — *Owner: TV1* — Rules: `K1, K4, O8`. Export `public.py` cho module khác; luồng yêu cầu dữ liệu cá nhân (`/users/me/data-requests`).

#### Module Classroom (TV2)
- [TASK-005: Classroom Models & Schema](TASK-005-classroom-models-schema.md) — *Owner: TV2* — Rules: `A1-A6, H1-H2`. Models: Course, Class, ClassMembership, JoinRequest, CoLecturerInvitation.
- [TASK-006: Classroom Membership & Join Request Workflow](TASK-006-classroom-membership-flow.md) — *Owner: TV2* — Rules: `A1, A4, A5, L2`. Quy trình xin vào lớp qua mã, duyệt/từ chối đồng thời (concurrency), sinh viên rời lớp, giảng viên loại thành viên.
- [TASK-007: Classroom Lifecycle & Co-Lecturer Management](TASK-007-classroom-lifecycle-colecturer.md) — *Owner: TV2* — Rules: `A3, H1, H2, H5, M2, M5`. Mời đồng giảng viên, chuyển chủ lớp (ownership transfer trong 1 transaction), lưu trữ (`ARCHIVED`) và khôi phục lớp.
- [TASK-008: Classroom Public Interface & Internal Access Check API](TASK-008-classroom-public-interface.md) — *Owner: TV2* — Rules: `Fail-closed`. Export `classroom/public.py` và endpoint nội bộ `/internal/v1/classes/{class_id}/access` cho các service Document, AI, Learning.

#### Module Social (TV3)
- [TASK-009: Social Feed Module](TASK-009-social-feed.md) — *Owner: TV3* — Rules: `G1, L1, L5`. Đăng bài, sửa bài, xóa bài (soft delete), kiểm tra quyền thành viên qua `classroom.public`.
- [TASK-010: Social Comments Module](TASK-010-social-comments.md) — *Owner: TV3* — Rules: `G2, L1, L5`. Bình luận bài đăng, kiểm tra trạng thái bài đăng, soft delete, kiểm duyệt bình luận vi phạm.
- [TASK-011: Social Calendar Module](TASK-011-social-calendar.md) — *Owner: TV3* — Rules: `G3, L3`. Quản lý sự kiện lịch của lớp (`CORE` origin) và cơ chế phản chiếu deadline (`LEARNING` origin, read-only).

#### Module Notification & Administration (TV4)
- [TASK-012: Notification Module with Transactional Outbox & Dedup](TASK-012-notification-module.md) — *Owner: TV4* — Rules: `G4`. Quản lý thông báo trong ứng dụng, đánh dấu đã đọc, dedup key, xử lý outbox event an toàn không rollback nghiệp vụ chính.
- [TASK-013: Administration Workflows & Core Audit Logging](TASK-013-administration-audit.md) — *Owner: TV4 (phối hợp TV1, TV2)* — Rules: `F1, F2, F4, F7, K1, K5`. Quản trị tài khoản, khóa/mở tài khoản, phân quyền, xử lý yêu cầu xóa/xuất dữ liệu, ghi audit can thiệp (kèm `X-Admin-Reason`).

### Giai đoạn G2: Tích hợp, Kiểm thử toàn diện & Đóng gói Core
- [TASK-014: Core Database Migrations & Seed Data](TASK-014-core-migrations-db.md) — *Owner: TV4 & Shared* — Hoàn thiện Alembic migrations cho toàn bộ schema `core`, seed script chuẩn cho dev/test.
- [TASK-015: Core Comprehensive Security & Integration Test Suite](TASK-015-core-integration-security-tests.md) — *Owner: Cả nhóm* — Bộ kiểm thử tự động QAS-04, Core-01 đến Core-06: cross-class, locked account, concurrent approve/transfer, JWT replay, rate-limit.
- [TASK-016: Core Docker Compose, Health Check & CI Pipeline](TASK-016-core-docker-compose-ci.md) — *Owner: TV4* — Docker Compose chuẩn hóa, GitHub Actions CI chạy ruff lint, pytest, contract snapshot test, migration validation.

---

### Giai đoạn G3–G5: Các Microservices tiếp theo (Theo lộ trình)
- [TASK-017: Document Service Specification & Implementation (G3)](TASK-017-document-service-design-impl.md) — Rules: `B1-B7, H3, H6, L6`. Thư viện tài liệu 5 định dạng, versioning, chia sẻ lớp (`ClassDocumentGrant`), ghi chú/bookmark gắn nguồn.
- [TASK-018: AI Service & Grounded RAG Tutor (G3)](TASK-018-ai-service-rag-tutor.md) — Rules: `C1-C6, H4, H5, QAS-06`. Trợ giảng AI 2 chế độ, trích dẫn tài liệu cụ thể, kiểm tra quyền truy hồi kép (Core + Document), tắt AI khi thi.
- [TASK-019: Learning Service (G4)](TASK-019-learning-service.md) — Rules: `D0-D8, I1-I7, M1-M4`. Practice Quiz, Assessment (timer, resume, immutable attempt versions), Assignment (nộp muộn, nộp lại), chấm điểm & phúc khảo.
- [TASK-020: Learner Intelligence Service & MVP Reporting (G5)](TASK-020-learner-intelligence-service.md) — Rules: `E1-E6, J1-J5, O6, F6, QAS-11`. Bằng chứng học tập, đo lường mastery, khuyến nghị hỗ trợ, ẩn nhóm < 5 sinh viên, xuất báo cáo PDF/Excel cho nhà trường.
