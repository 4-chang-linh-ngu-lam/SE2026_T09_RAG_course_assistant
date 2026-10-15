# TASK-016: Core Docker Compose, Health Check & CI Pipeline

- **Mã Task:** `TASK-016`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `TV4`
- **Business Rules liên quan:** `F1`, `F7`, `K5`; Core-05/QAS-04
- **Tài liệu căn cứ:** [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#6-kiểm-thử-core-g1g2), [CONTRIBUTING.md](../docs/CONTRIBUTING.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Docker/Compose/health/CI đã triển khai; bằng chứng 2026-10-12 là 124 test PostgreSQL 16. Bản Identity Lumi mới có bằng chứng 153 test PostgreSQL 18; chưa được coi là lần chạy PostgreSQL 16/Docker mới nhất.

**Cần sửa/bổ sung:**
- Giữ một Uvicorn worker khi limiter/idempotency còn RAM; tăng worker/replica cần thiết kế backend dùng chung, không tự thêm gunicorn/multi-worker.
- Dependencies chính thức nằm ở pyproject.toml, build wheel theo Dockerfile hiện có; không tạo requirements riêng lệch nguồn chuẩn. Health ready kiểm tra cả DB và quyền USAGE schema Core, không chỉ SELECT 1.
- CI thực tế gồm core-tests, web-build, compose-smoke, push main/feature/fix/codex và PR. Giữ migration trước startup, không format/sửa revision đã áp dụng, không coi Web skeleton build thành công là Web nghiệp vụ đã xong.
- Bổ sung module/test mới khi TASK-005–015 có triển khai; tách stack/volume/port test, không prune/xóa DB người dùng. Demo-ui giữ gitignore, không trở thành dependency build/CI.
- Xác nhận run GitHub cho đúng commit/PR khi có quyền và ghi link bằng chứng; ảnh CI xanh trước đó không xác nhận mọi thay đổi workspace hiện tại. Không tự push/commit để tạo run.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] Chạy lại migration 0005–0007, lint/format/OpenAPI/tests/coverage và Compose smoke trên PostgreSQL 16 cho revision mới nhất.
- [ ] TASK-015 và toàn checklist G1/G2 có bằng chứng trước G3; Docker/CI sẵn sàng không thay thế nghiệm thu chức năng.

---

## 1. Mục tiêu
Hoàn thiện hạ tầng đóng gói Docker cho Core Service, chuẩn hóa file cấu hình `compose.yaml`, thiết lập các endpoint kiểm tra sức khỏe hệ thống (`health check: live & ready`), và xây dựng pipeline GitHub Actions CI tự động hóa việc lint, kiểm thử và xác thực hợp đồng OpenAPI.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. Dockerfile & `compose.yaml`
- Tối ưu hóa `services/core/Dockerfile`:
  - Multi-stage build với Python 3.12-slim.
  - Chạy bằng user không có quyền root (`non-root user`) để tăng cường bảo mật.
  - Cài đặt đầy đủ dependencies, giữ một Uvicorn worker phù hợp giới hạn limiter/idempotency hiện tại.
- Chuẩn hóa `compose.yaml` ở root repo:
  - Service `db` (PostgreSQL 16), volume persistence, healthcheck kiểm tra `pg_isready`.
  - Service `core`: depends_on `db` với điều kiện `service_healthy`.
  - Môi trường biến cấu hình độc lập qua `.env`.

### 2.2. Health Check Endpoints (`/health/live` & `/health/ready`)
- `GET /health/live`: Trả về `200 OK` `{status: "live"}` nếu tiến trình FastAPI đang chạy bình thường (liveness probe).
- `GET /health/ready`: Kiểm tra kết nối DB và quyền USAGE schema `core` theo health router hiện tại. Trả về `200 OK` `{status: "ready", "db": "connected"}` nếu kết nối tốt, trả về `503 SERVICE_UNAVAILABLE` nếu mất kết nối DB (readiness probe).

### 2.3. Pipeline GitHub Actions CI (`.github/workflows/core-ci.yml`)
- Tự động kích hoạt khi có Pull Request hoặc Push vào các nhánh `feature/*`, `fix/*`, `codex/*`, `main`.
- Các bước thực thi:
  1. **Linting & Code Quality:** Chạy `ruff check services/core` và `ruff format --check services/core`.
  2. **Static Analysis & Typing:** Chạy `mypy services/core` (nếu có cấu hình).
  3. **OpenAPI Schema Contract Check:** Xuất OpenAPI schema từ FastAPI và so sánh với snapshot để cảnh báo breaking changes.
  4. **Database Migrations:** Khởi chạy dịch vụ PostgreSQL trong CI container, chạy `alembic upgrade head`.
  5. **Automated Testing:** Thực thi `pytest services/core/tests/` và xuất báo cáo độ bao phủ mã (coverage report).

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Lệnh `docker compose up --build -d` khởi động thành công từ môi trường sạch không báo lỗi (project test riêng, thêm `--wait` để xác minh health).
- [x] Endpoint `/health/live` trả về 200; endpoint `/health/ready` phản ánh chính xác trạng thái kết nối PostgreSQL và quyền dùng schema Core.
- [ ] GitHub Actions CI chạy thành công (green build) trên mọi PR mới.
- [ ] Toàn bộ checklist nghiệm thu Core tại [IMPLEMENTATION_ROADMAP.md](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md#checklist-nghiệm-thu-core) được tích hợp kiểm tra tự động.

**Đã triển khai:** Core wheel image multi-stage/non-root/read-only/single worker, migration job trước startup, health typed schemas/timeouts, Compose env/port config, CI PostgreSQL 16 + migration/contract/tests/coverage/public gate/Web/Compose smoke. CI trigger PR và push main/feature/fix/codex; mypy chưa có cấu hình nên không thêm. Không sửa migration đã áp dụng; formatter exclusion chỉ dành cho baseline 0001 cũ, lint vẫn chạy.

**Bằng chứng local (2026-10-12):** Docker 29.8.2, Compose 5.5.1, Linux engine; build và startup project test với volume/cổng/image riêng đạt, Core UID 10001/wheel installed, schema drift không có, Web/health đạt. Toàn bộ 124 test chạy PostgreSQL 16, không warning; app coverage 96%, public interface 100%; lint/format đạt. Khi dừng DB: ready 503 và live 200; sau khởi động lại: ready 200, schema/migration giữ nguyên. Stack test được dọn riêng, không tác động stack/volume khác.

**Chưa nghiệm thu đầy đủ:** GitHub green build cần chạy sau khi người dùng mở/push PR; chưa có xác nhận remote. Checklist toàn Core bị phụ thuộc TASK-005–015 chưa hoàn thành (Classroom, Social, Notification, Admin và các test tích hợp tương ứng). Pipeline hiện kiểm tra toàn bộ code/tests đã có, không chứng minh tính năng chưa triển khai. Giữ trạng thái hai tiêu chí này pending; chưa chuyển G3. Hướng dẫn chính: [Core README](../services/core/README.md#docker-migration-và-ci-task-016). Shared CI/Compose/contracts cần TV1/TV4 review trong PR.
