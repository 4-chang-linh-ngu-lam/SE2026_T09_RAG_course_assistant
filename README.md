# RAG Course Assistant — SE2026-T09

Dự án trợ giảng học tập sử dụng **Microservices trong một GitHub Monorepo**, nhóm 4 thành viên.

**Năm service:** Core, Document, Learning, AI, Learner Intelligence. **Core-first:** hoàn thiện toàn bộ Core (auth, lớp/thành viên, feed, comments, calendar, notifications, quản trị/audit) rồi mới sang Document + AI, Learning và Learner Intelligence.

**Core stack đã chọn:** Next.js (Web), FastAPI (Core), PostgreSQL, Docker Compose. Các service khác chỉ chốt ranh giới và giao tiếp ở giai đoạn này; không suy diễn stack hay schema riêng.

## Đọc tài liệu

**Bàn giao backend TV4 (2026-10-19):** [task 001–015, phần đã làm, kiểm thử và toàn bộ vấn đề còn mở](tasks/TV4_BACKEND_HANDOVER.md).

1. [Business Rules](docs/architect/BUSINESS_RULES.md) — nguồn nghiệp vụ.
2. [ADR](docs/architect/microservices-v1/ADR-001.md), [Architecture](docs/architect/microservices-v1/ARCHITECTURE.md) — kiến trúc.
3. [Core Design](docs/architect/microservices-v1/core/DESIGN.md), [Core API](docs/architect/microservices-v1/core/API_CONTRACT.md), [Folder Structure](docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md) — triển khai Core.
4. [Danh mục task](tasks/README.md) — hiện trạng, việc cần sửa và phụ thuộc của TASK-001–020 (rà soát 2026-10-16).
5. [Roadmap](docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md), [Quality Attributes](docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md), [Contributing](docs/CONTRIBUTING.md).

**Trạng thái:** Core đã có Common, Identity, Classroom Admin/access API, Social, Notification inbox/outbox worker và Administration backend (staff/role/status/audit, import Student CSV/XLSX, data-request review). Yêu cầu dữ liệu thiếu policy/executor giữ IN_REVIEW. Xem [Core README](services/core/README.md) để cấu hình, migration và kiểm thử. Sau khi cấu hình môi trường theo `.env.example`, chạy `docker compose up --build -d`; Compose tự chạy migration trước Core và notification worker. Chưa nghiệm thu toàn Core/Web G2 hoặc chuyển G3.

TASK-014 có [runbook migration/seed](services/core/migrations/README.md), guard downgrade
và CLI report/plan/apply School theo manifest; seed atomic/idempotent chỉ cho database
dev/test riêng. Local đạt **313 test Core trên PostgreSQL 16**, không skip. Mapping
School dữ liệu thực và FK users.school_id vẫn cần TV1/TV2 review, không tự backfill.

TASK-015 đã có [bộ kiểm chứng backend](services/core/tests/README.md): **342 test
đạt PostgreSQL 16**, coverage tổng **91%**, 300 thao tác cạnh tranh, Rule/evidence
artifacts và backend Compose smoke. Bài đo class-list 10 phút tách backend/client
latency và ghi rõ giới hạn; Web E2E ngoài scope lần này, full TP-01/G2 chưa nghiệm thu.

## Triển khai thử MVP (Neon + Google Cloud + Vercel)

Neon giữ database staging riêng; Core API và Notification worker chạy trên Google Cloud
Run ở `asia-southeast1`; Vercel host Web tại `apps/web`. Cloud Run service dùng request-
based billing, `min=0`, `max=1`, 1 CPU/512 MiB để scale về 0 khi rảnh và giới hạn tải.
Cloud Run Job chạy `python -m app.modules.notification.worker --once --batch-size 100`
mỗi 15 phút qua Cloud Scheduler.

Tạo Neon branch riêng với PostgreSQL 16 và dữ liệu tổng hợp. Lưu direct connection URI
có SSL trong Secret Manager, scheme SQLAlchemy là `postgresql+psycopg://`. Không dùng
database production hay đưa URI/secret vào Git/chat. Trên database mới, chạy một lần
Cloud Run Job `python -m alembic upgrade head`, sau đó `alembic check`; đây là bước
bootstrap đã được người dùng duyệt. Core API chỉ nhận traffic sau khi migration đạt.

Cloud Run free-tier quota được tính gộp theo billing account: 240.000 vCPU-giây và
450.000 GiB-giây/tháng cho Jobs theo giá us-central1. Một Job 1 vCPU/512 MiB chạy mỗi
15 phút, với mức tính tối thiểu một phút mỗi lần, ước tính 172.800 vCPU-giây/tháng.
Quota có thể đã được workload khác sử dụng; vùng Singapore có mức giá riêng và Build,
Artifact Registry, egress hoặc phần vượt quota có thể phát sinh phí. Không đảm bảo bill
$0. Project GCP staging hiện có Cloud Billing bật.

Đặt `DATABASE_URL`, `SECRET_KEY` và `INTERNAL_SERVICE_SECRET` trong Secret Manager;
đặt `CORS_ORIGINS` là JSON array với đúng origin Vercel và `COOKIE_SECURE=true` trên
Cloud Run. Trên Vercel, chọn root directory `apps/web`, dùng `codex/mvp-deploy` làm
Preview branch và đặt `NEXT_PUBLIC_CORE_API_URL` theo URL Cloud Run.

Triển khai GCP theo thứ tự: bật APIs `run`, `cloudbuild`, `artifactregistry`,
`secretmanager`, `cloudscheduler`; tạo image một lần; chạy migration Job trên Neon staging
rỗng; deploy API và Notification Job từ cùng image; sau đó tạo Scheduler trigger có OAuth
service account được cấp `roles/run.invoker` cho job. Dùng service account runtime
`lumi-mvp-runtime` chỉ đọc các secrets cần thiết và `lumi-notification-scheduler` chỉ gọi
Notification Job. Secret names mẫu: `lumi-neon-staging-database-url`,
`lumi-core-secret-key`, `lumi-internal-service-secret`. GCP project cần Billing bật để
dùng Free Tier; không đưa giá trị secret vào command history hoặc Git.

Gmail đang hoãn theo lựa chọn của người dùng. Identity hiện gửi email đồng bộ trước
commit và chưa có retry/reissue worker trong revision này; không dùng tài khoản hoặc dữ
liệu học sinh thật. Main vẫn chỉ có Web skeleton; cần E2E Web → Core → Neon sau khi PR
frontend được tích hợp.

## Phạm vi sản phẩm Lumi
Lumi phục vụ **học sinh THCS và THPT (khối 6–12)** trong **lớp học chính khóa**. Tiểu học, đại học và lớp học thêm không thuộc phạm vi MVP. Giao diện hướng đến học sinh phổ thông, giữ phong cách sáng, gọn, không game hóa hoặc trang trí quá mức.

**Stakeholder/role không mở rộng:** Admin, Lecturer (hiển thị là **Giáo viên**) và Student (hiển thị là **Học sinh**); nhà trường nhận báo cáo thông qua Admin, không có tài khoản riêng. Các enum `LECTURER`/`STUDENT` hiện hành tiếp tục được giữ để tương thích với code và API. Không mặc định có vai trò Phụ huynh hay Admin theo trường.

**Nguồn quyết định:** 20 quyết định đã được hợp nhất vào `docs/architect/BUSINESS_RULES.md`; API/schema mới phải được phân biệt rõ với Identity legacy đã triển khai. Không suy ra tính năng đã hoàn thành chỉ từ tài liệu.


## Phạm vi nghiệp vụ Lumi (baseline 2026-10-14)
MVP dành cho lớp chính khóa THCS/THPT khối 6–12 tại một trường, chuẩn bị school_id cho mở rộng; giữ 5 service và ba role ADMIN/LECTURER/STUDENT. Admin tạo lớp môn học liên kết lớp hành chính, phân công giáo viên và quản lý ghi danh AUTO/MANUAL; không có join code hoặc tự đăng ký Student trong MVP. Student nhận username và mã kích hoạt một lần từ Admin. Dữ liệu học tập cá nhân và chat lịch sử được bảo vệ khi chuyển lớp; nguồn tài liệu vẫn kiểm tra quyền hiện hành. Quản trị MVP có nhập CSV/Excel, yêu cầu dữ liệu xử lý có kiểm soát. **Đây là baseline mục tiêu, không phải tuyên bố mọi chức năng đã triển khai.** Xem `docs/architect/BUSINESS_RULES.md`.
