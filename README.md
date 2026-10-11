# RAG Course Assistant — SE2026-T09

Dự án trợ giảng học tập sử dụng **Microservices trong một GitHub Monorepo**, nhóm 4 thành viên.

**Năm service:** Core, Document, Learning, AI, Learner Intelligence. **Core-first:** hoàn thiện toàn bộ Core (auth, lớp/thành viên, feed, comments, calendar, notifications, quản trị/audit) rồi mới sang Document + AI, Learning và Learner Intelligence.

**Core stack đã chọn:** Next.js (Web), FastAPI (Core), PostgreSQL, Docker Compose. Các service khác chỉ chốt ranh giới và giao tiếp ở giai đoạn này; không suy diễn stack hay schema riêng.

## Đọc tài liệu
1. [Business Rules](docs/architect/BUSINESS_RULES.md) — nguồn nghiệp vụ.
2. [ADR](docs/architect/microservices-v1/ADR-001.md), [Architecture](docs/architect/microservices-v1/ARCHITECTURE.md) — kiến trúc.
3. [Core Design](docs/architect/microservices-v1/core/DESIGN.md), [Core API](docs/architect/microservices-v1/core/API_CONTRACT.md), [Folder Structure](docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md) — triển khai Core.
4. [Roadmap](docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md), [Quality Attributes](docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md), [Contributing](docs/CONTRIBUTING.md).

**Trạng thái:** Core đã có Common, Identity và hạ tầng Compose/CI; các module Core khác vẫn chưa hoàn thành. Xem [Core README](services/core/README.md) để cấu hình, migration và kiểm thử. Sau khi cấu hình môi trường theo `.env.example`, chạy `docker compose up --build -d`; Compose tự chạy migration trước Core. Chưa nghiệm thu toàn Core/G2 hoặc chuyển G3.
