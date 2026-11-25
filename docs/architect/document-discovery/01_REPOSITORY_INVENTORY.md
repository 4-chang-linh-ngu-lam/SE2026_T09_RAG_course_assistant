# DOC-00.1 — Kiểm kê repository

**Snapshot sau pull:** local branch và origin/codex/rag-technical-discovery ở c7f56c722f421bf1df17f5a82f26a78682eb82be; origin/main ở dc0671c36bf750ef914ac34d22e6ff2cf685287a.

## 1. Cấu trúc service thực tế

| Thành phần | Có trong repository | Entry point / cấu trúc | Vai trò và mức hoàn thiện |
|---|---|---|---|
| Core | Có: services/core | app/main.py, app/bootstrap.py; modules identity, classroom, social, notification, administration, health; migrations/ | FastAPI backend và PostgreSQL/Alembic. Notification là module/worker thuộc Core, không phải microservice độc lập. |
| RAG Engine | Có: services/rag | Python packages idp, chunking, indexing, retrieval, generation, search; CLI và test fixtures | Library/pipeline offline; README xác nhận các stage không phải HTTP microservice. |
| Document | Không có services/document | Không tìm thấy app, router, model, repository, migration hay worker Document | MISSING. |
| AI Service | Không có services/ai | README generation nói service phải tự làm các ranh giới API/persistence | MISSING. RAG Engine không thay thế service này. |
| Learning | Không có services/learning | Chỉ xuất hiện trong architecture/business docs và adapter contracts | MISSING. |
| Web | Có: apps/web | Next.js App Router, features, src/lib/data adapters, same-origin /api/v1 proxy | Có giao diện Document; live adapter chưa nối Document API. |

Kiến trúc định hướng vẫn là monorepo với năm microservices; hiện trạng thư mục chỉ có Core và RAG. Tham chiếu: docs/architect/microservices-v1/ADR-001.md:9–19, ARCHITECTURE.md:6, 27–40; services/core/app/bootstrap.py:14–23.

## 2. Framework, package và persistence

| Khu vực | Quan sát |
|---|---|
| Core | FastAPI; SQLAlchemy; Alembic; PostgreSQL. Cấu hình package trong services/core/pyproject.toml; DB engine/schema trong app/common/db.py. |
| RAG | Python packages và requirements theo phase; không có web framework/HTTP app khai báo cho RAG API. |
| Web | Next.js; package.json; API proxy only forwards allowlisted operations under apps/web/src/lib/api/operations.ts. |
| Core migrations | services/core/migrations/versions/0001–0014; current migration README ghi head 0014. |
| Document persistence | Không có ORM model/migration/schema sở hữu Document. |
| RAG local state | Filesystem artifact, JSON manifests và local SQLite registry/harness; không phải Document source of truth. |

## 3. Tests hiện diện

Đếm file theo tracked code snapshot, không phải số test case:

| Vùng | File test hiện thấy | Phạm vi |
|---|---:|---|
| services/rag | 15 file test_*.py | Unit/fixture/local composition cho parsing, retrieval, generation. |
| services/core | 33 file test_*.py | Core module/API/security/database với PostgreSQL CI. |
| apps/web | 40 file *.test.ts/*.test.tsx | UI state/controller/contract helpers; không thay thế API E2E. |
| Document service | 0 | Không có backend nên chưa có test Document. |

Đếm Git tree tại 680beaf (PR #49 merge), 2d97551, dc0671c và c7f56c7 đều cho 15 file test_*.py. Không có RAG test tree changes giữa baseline và HEAD sau pull. Báo cáo cũ ghi 21 nhưng không có ref/scope trong các commit đã khảo sát giải thích chênh lệch; không suy đoán.

## 4. Configuration, Compose, Docker và CI

- Root compose.yaml chạy db, migrate, core, notification-worker và web. Không có service Document, AI hoặc RAG; volume duy nhất là pgdata cho PostgreSQL.
- Core Dockerfile/pyproject và app. RAG có Dockerfile.phase0, Dockerfile.phase4-models, Dockerfile.phase5 theo các phase thử nghiệm; không có một image/API Document hoặc RAG service được Compose dùng.
- Kiểm tra tĩnh đường dẫn Docker cho RAG cho thấy các COPY targets parser, idp/ocr/backends/model_worker.py và colab không tồn tại trên HEAD hiện tại. Dockerfiles đó chưa được build trong discovery; không khẳng định mọi target stage đều thất bại.
- .github/workflows/core-ci.yml có rag-tests, core-tests với PostgreSQL 16, web-build, compose-smoke; core-load chỉ chạy khi workflow_dispatch bật input.
- No Document CI job, service image, migration check, contract test hoặc deployment target tồn tại trong repository hiện tại.

## 5. Hướng dẫn và tài liệu đã đối chiếu

- AGENTS.md và apps/web/AGENTS.md: quyền backend fail closed, module ownership, hợp đồng API/schema phải có test, live/mock isolation.
- docs/architect/BUSINESS_RULES.md: B1–B7, E5, F3/F4/F7, H3/H6, L2/L6, O1/O2/O6.
- docs/architect/microservices-v1/ADR-001.md, ARCHITECTURE.md, QUALITY_ATTRIBUTES.md.
- docs/architect/microservices-v1/core/DESIGN.md, API_CONTRACT.md, FOLDER_STRUCTURE.md.
- docs/architect/lumi-design/04_FRS_Document.md, 06_FRS_Intelligence.md, 11_ERD_DFD.md, 12_API_Contracts.md, 14_Security_Privacy.md, 16_Test_Plan.md, 17_Test_Cases.md, 19_Decisions_Gaps.md, 22_ENVIRONMENTS_DEPLOYMENT.md.
- docs/architect/rag-discovery/00–09; các cập nhật chấp thuận mới nhất được đọc trực tiếp từ origin/codex/rag-technical-discovery:docs/architect/rag-design/00_DESIGN_STATUS.md.

Không kết nối tới Production, không đọc/copy dữ liệu người dùng, không chạy Docker hoặc thay đổi biến môi trường.

## 6. Thiết kế cross-service mới

- Core: CORE-T03 là POST /internal/v1/authorization/check; CORE-T04 là service authentication; CORE-T06/T08 bao phủ per-target events và distributed account deletion.
- Learning: LRN-D07/T05 cần source/version IDs và validation; LRN-D10 chỉ dùng snapshot Document offline khi quyền hợp lệ.
- Notification: NTF-T03/T04 yêu cầu durable event inbox; tên Document ingestion events/recipients và completion còn pending.
- System: SYS-02 là Service JWT foundation; SYS-08 Master Implementation Plan xác định dependency và phase. Tài liệu là target, chưa xác minh implementation.
