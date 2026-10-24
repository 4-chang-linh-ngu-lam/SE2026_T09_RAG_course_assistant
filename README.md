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

## Triển khai thử MVP (Neon + Render + Vercel)

`render.yaml` khai báo Core API trên nhánh `codex/mvp-deploy`, dùng Render Free và
kiểm tra `/health/ready`. Dockerfile đọc biến `PORT` của Render, vẫn giữ một Uvicorn
worker. Free Web Service có thể sleep sau 15 phút không có request; SMTP port 587 bị
chặn trên Render Free, nên staging này không bật gửi email. Pre-deploy migration tự
động được hoãn; muốn API ready trên Neon mới cần chạy one-off migration trước khi
deploy Core.

Notification worker được chạy bằng GitHub Actions mỗi 15 phút, với lệnh một lượt
`python -m app.modules.notification.worker --once --batch-size 100`. Workflow
`.github/workflows/neon-staging-notifications.yml` dùng runner chuẩn miễn phí của repo
công khai; lịch chỉ chạy sau khi workflow được merge vào `main` và có thể bị GitHub trì
hoãn lúc tải cao. Mỗi lần xử lý tối đa 100 event. Sau migration thành công, đặt repository
variable `NEON_STAGING_READY=true` để mở lịch; trước đó cron tự bỏ qua job.

Tạo Neon staging branch PostgreSQL 16 với dữ liệu tổng hợp. Đổi direct URI có SSL sang
scheme `postgresql+psycopg://`, rồi lưu trong GitHub Environment `neon-staging` dưới
secret `NEON_STAGING_DATABASE_URL`. Workflow
`.github/workflows/neon-staging-migrate.yml` cho phép chạy `alembic upgrade head` và
`alembic check` thủ công đúng một lần đầu trên DB staging rỗng: merge hai workflow vào
`main`, vào Actions, chạy `Neon staging migration` với `run_initial_migration=true`, xác
nhận thành công, rồi bật `NEON_STAGING_READY`. Tạo Render Core sau khi migration đạt
và nhập URI Neon vào `DATABASE_URL` ở Render. Không dùng database production hay dán
URI/secret vào Git, issue hoặc chat.

GitHub schedule dùng `main` mặc định; `workflow_dispatch` cho phép chạy notification
thủ công. Migration workflow chỉ chạy trên `main` sau khi người vận hành bật xác nhận
`run_initial_migration`. Render Free không có pre-deploy command tự động; không bật
Gmail trên gói này. Render sinh `SECRET_KEY` và `INTERNAL_SERVICE_SECRET`; nhập
`CORS_ORIGINS` là JSON array chứa đúng origin Vercel.

Trên Vercel, kết nối repository và chọn root directory `apps/web`; dùng nhánh
`codex/mvp-deploy` làm Preview branch và đặt `NEXT_PUBLIC_CORE_API_URL` theo URL Render.
Sau khi Vercel cấp URL, cập nhật `CORS_ORIGINS` ở Render cho đúng URL đó. Main hiện chỉ
có trang Web skeleton; bản deploy thử chưa phải MVP frontend hoàn chỉnh, và cần E2E
Web → Core → Neon sau khi PR frontend được tích hợp. Gửi lời mời/reset hiện vẫn gửi
SMTP đồng bộ trước commit; email sẽ không hoạt động ở staging này cho đến khi chọn gói
có SMTP egress và hoàn tất issue #16. Không dùng tài khoản/dữ liệu thật trong staging.

## Phạm vi sản phẩm Lumi
Lumi phục vụ **học sinh THCS và THPT (khối 6–12)** trong **lớp học chính khóa**. Tiểu học, đại học và lớp học thêm không thuộc phạm vi MVP. Giao diện hướng đến học sinh phổ thông, giữ phong cách sáng, gọn, không game hóa hoặc trang trí quá mức.

**Stakeholder/role không mở rộng:** Admin, Lecturer (hiển thị là **Giáo viên**) và Student (hiển thị là **Học sinh**); nhà trường nhận báo cáo thông qua Admin, không có tài khoản riêng. Các enum `LECTURER`/`STUDENT` hiện hành tiếp tục được giữ để tương thích với code và API. Không mặc định có vai trò Phụ huynh hay Admin theo trường.

**Nguồn quyết định:** 20 quyết định đã được hợp nhất vào `docs/architect/BUSINESS_RULES.md`; API/schema mới phải được phân biệt rõ với Identity legacy đã triển khai. Không suy ra tính năng đã hoàn thành chỉ từ tài liệu.


## Phạm vi nghiệp vụ Lumi (baseline 2026-10-14)
MVP dành cho lớp chính khóa THCS/THPT khối 6–12 tại một trường, chuẩn bị school_id cho mở rộng; giữ 5 service và ba role ADMIN/LECTURER/STUDENT. Admin tạo lớp môn học liên kết lớp hành chính, phân công giáo viên và quản lý ghi danh AUTO/MANUAL; không có join code hoặc tự đăng ký Student trong MVP. Student nhận username và mã kích hoạt một lần từ Admin. Dữ liệu học tập cá nhân và chat lịch sử được bảo vệ khi chuyển lớp; nguồn tài liệu vẫn kiểm tra quyền hiện hành. Quản trị MVP có nhập CSV/Excel, yêu cầu dữ liệu xử lý có kiểm soát. **Đây là baseline mục tiêu, không phải tuyên bố mọi chức năng đã triển khai.** Xem `docs/architect/BUSINESS_RULES.md`.
