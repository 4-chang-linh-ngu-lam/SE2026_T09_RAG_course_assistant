# Core FastAPI skeleton

Chạy tại thư mục repo: `docker compose up --build -d`.

- Liveness: http://localhost:8000/health/live
- Readiness (kiểm tra DB): http://localhost:8000/health/ready
- OpenAPI: http://localhost:8000/docs
- Migration: `docker compose exec core alembic upgrade head`
- Test cục bộ: `cd services/core && pip install -e '.[dev]' && pytest -q`

**Skeleton không triển khai Identity, Classroom, Social, Notification hay Admin.** Các thư mục module chỉ có `__init__.py` để tránh file placeholder không cần thiết. Migration 0001 chỉ khởi tạo Alembic version trong schema `core`, chưa có bảng nghiệp vụ. Không dùng mật khẩu DB mặc định trong production.
