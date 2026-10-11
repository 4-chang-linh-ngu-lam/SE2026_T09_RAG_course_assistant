# TASK-016: Core Docker Compose, Health Check & CI Pipeline

- **Mã Task:** `TASK-016`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `TV4`
- **Tài liệu căn cứ:** [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#6-kiểm-thử-core-g1g2), [CONTRIBUTING.md](../docs/CONTRIBUTING.md)

---

## 1. Mục tiêu
Hoàn thiện hạ tầng đóng gói Docker cho Core Service, chuẩn hóa file cấu hình `compose.yaml`, thiết lập các endpoint kiểm tra sức khỏe hệ thống (`health check: live & ready`), và xây dựng pipeline GitHub Actions CI tự động hóa việc lint, kiểm thử và xác thực hợp đồng OpenAPI.

---

## 2. Chi tiết kỹ thuật & File cần tạo/cập nhật

### 2.1. Dockerfile & `compose.yaml`
- Tối ưu hóa `services/core/Dockerfile`:
  - Multi-stage build với Python 3.12-slim.
  - Chạy bằng user không có quyền root (`non-root user`) để tăng cường bảo mật.
  - Cài đặt đầy đủ dependencies, cấu hình gunicorn/uvicorn workers phù hợp.
- Chuẩn hóa `compose.yaml` ở root repo:
  - Service `db` (PostgreSQL 16), volume persistence, healthcheck kiểm tra `pg_isready`.
  - Service `core`: depends_on `db` với điều kiện `service_healthy`.
  - Môi trường biến cấu hình độc lập qua `.env`.

### 2.2. Health Check Endpoints (`/health/live` & `/health/ready`)
- `GET /health/live`: Trả về `200 OK` `{status: "live"}` nếu tiến trình FastAPI đang chạy bình thường (liveness probe).
- `GET /health/ready`: Thực hiện truy vấn `SELECT 1` kiểm tra kết nối DB schema `core`. Trả về `200 OK` `{status: "ready", "db": "connected"}` nếu kết nối tốt, trả về `503 SERVICE_UNAVAILABLE` nếu mất kết nối DB (readiness probe).

### 2.3. Pipeline GitHub Actions CI (`.github/workflows/core-ci.yml`)
- Tự động kích hoạt khi có Pull Request hoặc Push vào các nhánh `feature/*`, `fix/*`, `main`.
- Các bước thực thi:
  1. **Linting & Code Quality:** Chạy `ruff check services/core` và `ruff format --check services/core`.
  2. **Static Analysis & Typing:** Chạy `mypy services/core` (nếu có cấu hình).
  3. **OpenAPI Schema Contract Check:** Xuất OpenAPI schema từ FastAPI và so sánh với snapshot để cảnh báo breaking changes.
  4. **Database Migrations:** Khởi chạy dịch vụ PostgreSQL trong CI container, chạy `alembic upgrade head`.
  5. **Automated Testing:** Thực thi `pytest services/core/tests/` và xuất báo cáo độ bao phủ mã (coverage report).

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Lệnh `docker compose up --build -d` khởi động thành công từ môi trường sạch không báo lỗi.
- [ ] Endpoint `/health/live` trả về 200; endpoint `/health/ready` phản ánh chính xác trạng thái kết nối PostgreSQL.
- [ ] GitHub Actions CI chạy thành công (green build) trên mọi PR mới.
- [ ] Toàn bộ checklist nghiệm thu Core tại [IMPLEMENTATION_ROADMAP.md](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md#checklist-nghiệm-thu-core) được tích hợp kiểm tra tự động.
