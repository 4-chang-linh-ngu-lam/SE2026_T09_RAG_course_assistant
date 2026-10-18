# RAG Course Assistant — SE2026-T09

Dự án trợ giảng học tập sử dụng **Microservices trong một GitHub Monorepo**, nhóm 4 thành viên.

**Năm service:** Core, Document, Learning, AI, Learner Intelligence. **Core-first:** hoàn thiện toàn bộ Core (auth, lớp/thành viên, feed, comments, calendar, notifications, quản trị/audit) rồi mới sang Document + AI, Learning và Learner Intelligence.

**Core stack đã chọn:** Next.js (Web), FastAPI (Core), PostgreSQL, Docker Compose. Các service khác chỉ chốt ranh giới và giao tiếp ở giai đoạn này; không suy diễn stack hay schema riêng.

## Đọc tài liệu
1. [Business Rules](docs/architect/BUSINESS_RULES.md) — nguồn nghiệp vụ.
2. [ADR](docs/architect/microservices-v1/ADR-001.md), [Architecture](docs/architect/microservices-v1/ARCHITECTURE.md) — kiến trúc.
3. [Core Design](docs/architect/microservices-v1/core/DESIGN.md), [Core API](docs/architect/microservices-v1/core/API_CONTRACT.md), [Folder Structure](docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md) — triển khai Core.
4. [Danh mục task](tasks/README.md) — hiện trạng, việc cần sửa và phụ thuộc của TASK-001–020 (rà soát 2026-10-16).
5. [Roadmap](docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md), [Quality Attributes](docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md), [Contributing](docs/CONTRIBUTING.md).

**Trạng thái:** Core đã có Common, Identity, Classroom Admin/access API và hạ tầng Compose/CI; Social, Notification worker và Administration còn thiếu. Xem [Core README](services/core/README.md) để cấu hình, migration và kiểm thử. Sau khi cấu hình môi trường theo `.env.example`, chạy `docker compose up --build -d`; Compose tự chạy migration trước Core. Chưa nghiệm thu toàn Core/G2 hoặc chuyển G3.

## Phạm vi sản phẩm Lumi
Lumi phục vụ **học sinh THCS và THPT (khối 6–12)** trong **lớp học chính khóa**. Tiểu học, đại học và lớp học thêm không thuộc phạm vi MVP. Giao diện hướng đến học sinh phổ thông, giữ phong cách sáng, gọn, không game hóa hoặc trang trí quá mức.

**Stakeholder/role không mở rộng:** Admin, Lecturer (hiển thị là **Giáo viên**) và Student (hiển thị là **Học sinh**); nhà trường nhận báo cáo thông qua Admin, không có tài khoản riêng. Các enum `LECTURER`/`STUDENT` hiện hành tiếp tục được giữ để tương thích với code và API. Không mặc định có vai trò Phụ huynh hay Admin theo trường.

**Nguồn quyết định:** 20 quyết định đã được hợp nhất vào `docs/architect/BUSINESS_RULES.md`; API/schema mới phải được phân biệt rõ với Identity legacy đã triển khai. Không suy ra tính năng đã hoàn thành chỉ từ tài liệu.


## Phạm vi nghiệp vụ Lumi (baseline 2026-10-14)
MVP dành cho lớp chính khóa THCS/THPT khối 6–12 tại một trường, chuẩn bị school_id cho mở rộng; giữ 5 service và ba role ADMIN/LECTURER/STUDENT. Admin tạo lớp môn học liên kết lớp hành chính, phân công giáo viên và quản lý ghi danh AUTO/MANUAL; không có join code hoặc tự đăng ký Student trong MVP. Student nhận username và mã kích hoạt một lần từ Admin. Dữ liệu học tập cá nhân và chat lịch sử được bảo vệ khi chuyển lớp; nguồn tài liệu vẫn kiểm tra quyền hiện hành. Quản trị MVP có nhập CSV/Excel, yêu cầu dữ liệu xử lý có kiểm soát. **Đây là baseline mục tiêu, không phải tuyên bố mọi chức năng đã triển khai.** Xem `docs/architect/BUSINESS_RULES.md`.
