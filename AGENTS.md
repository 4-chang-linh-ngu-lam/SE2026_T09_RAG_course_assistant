# Hướng dẫn AI coding agent

## Nguồn chuẩn
- Nghiệp vụ: [BUSINESS_RULES.md](docs/architect/BUSINESS_RULES.md) — ưu tiên cao nhất, không tự sửa rule.
- Kiến trúc: [ADR-001](docs/architect/microservices-v1/ADR-001.md), [ARCHITECTURE](docs/architect/microservices-v1/ARCHITECTURE.md).
- Khi làm Core: đọc [DESIGN](docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT](docs/architect/microservices-v1/core/API_CONTRACT.md), [FOLDER_STRUCTURE](docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md). Khi làm Git/test/roadmap đọc tài liệu tương ứng. Không buộc đọc tất cả nếu không liên quan.
- **Một monorepo, năm microservices; Core là một service với nhiều module nội bộ.**

## Quy tắc bắt buộc
1. Xác định module sở hữu trước khi tạo file. Không import repository/model nội bộ của module khác; dùng public interface. Không truy cập bảng service khác.
2. Kiểm tra quyền tại Backend theo vai trò + quyền hiện hành theo lớp/tài nguyên. Fail closed nếu không xác minh được; không tự cấp quyền Admin đọc chat riêng tư.
3. Thay đổi public API, schema, permission, shared files phải cập nhật hợp đồng và test, thông báo owner liên quan trong PR.
4. Không tự tạo Business Rule, retention pháp lý, endpoint hoặc công nghệ chi tiết cho service chưa đặc tả. Nếu tài liệu xung đột, dừng phần bị ảnh hưởng và nêu rõ xung đột.
5. Không commit secret, token, mật khẩu, dữ liệu chat riêng tư. Không sửa migration đã áp dụng. Không để file tạm dùng một lần trong repo.
6. Test phải chạy thật; không tuyên bố đã đạt KPI hoặc tính năng hoàn thành nếu chưa có bằng chứng.
7. Không push thẳng main, merge PR, force push hoặc tạo commit giả khi chưa được cho phép. Commit theo nhóm thay đổi có ý nghĩa.
