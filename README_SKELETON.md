# Hướng dẫn chạy skeleton Monorepo

## Khởi động
1. Sao chép `.env.example` thành `.env`; đổi `POSTGRES_PASSWORD` và cập nhật mật khẩu trong `DATABASE_URL` cho khớp.
2. Chạy `docker compose up --build -d`.
3. Chạy `docker compose exec core alembic upgrade head`.
4. Mở http://localhost:3000, http://localhost:8000/health/live, http://localhost:8000/health/ready và http://localhost:8000/docs.
5. Dừng bằng `docker compose down`. `docker compose down -v` sẽ xóa cả dữ liệu DB.

## Phạm vi
Đây là **skeleton chạy được theo thiết kế**, chưa có nghiệp vụ Identity/Classroom/Social/Notification/Admin. Các thư mục service còn lại **chưa được tạo** vì chỉ triển khai Core ở giai đoạn này. `0001` chỉ khởi tạo migration baseline, chưa tạo bảng nghiệp vụ.

## Kiểm thử
`cd services/core && pip install -e '.[dev]' && ruff check app tests migrations && pytest -q`.
`cd apps/web && npm install && npm run build`.
CI chạy hai công việc trên. Chưa có test tích hợp PostgreSQL hoặc security tests cho tính năng chưa viết.

## Lưu ý
Mật khẩu và CORS mặc định chỉ phục vụ local. Không triển khai production với cấu hình này. Khi thêm module, tạo router riêng và đăng ký tại `app/bootstrap.py` qua PR được review.
