# Core Service — Quyết định thiết kế

Ngày phê duyệt: 25/11/2026. CORE-D01–08 ACCEPTED theo xác nhận của người dùng.

| ID | Quyết định |
|---|---|
| CORE-D01 | Core sở hữu User, Classroom, Membership, RBAC, Feed, Comment; không truy vấn DB xuyên service. |
| CORE-D02 | Email/password, JWT access/refresh, rotation, hash refresh token, logout revoke session, rate limit; ưu tiên tái sử dụng auth an toàn hiện có. Argon2id, access 15 phút, refresh 7 ngày là đề xuất cấu hình. |
| CORE-D03 | RBAC hệ thống USER/ADMIN và lớp OWNER/TEACHER/STUDENT; kiểm tra quyền theo tài nguyên. Owner quản lý lớp/thành viên/chuyển quyền; Owner/Teacher chia sẻ tài liệu, tạo bài tập, chấm điểm; Student làm bài; thành viên được dùng AI/feed/comment theo policy. Ma trận cần đối chiếu business rules, nhất là đồng giáo viên. |
| CORE-D04 | Classroom ACTIVE/ARCHIVED/DELETED; archived chỉ đọc, có thể khôi phục; join bằng mã/lời mời; một membership hiện hành mỗi người/lớp; đúng một owner; chuyển quyền trước khi owner rời; revoke quyền mới ngay khi loại thành viên. Retention pending. |
| CORE-D05 | POST /internal/v1/authorization/check theo DOC-T04: user_id, resource_type, resource_id, action -> allowed. Core xác minh quyền hiện hành, service sở hữu tài nguyên kiểm tra quyền bổ sung; fail closed. |
| CORE-D06 | Feed/comment thuộc Core, hỗ trợ tạo/sửa/xóa/báo cáo vi phạm; Notification nhận sự kiện. |
| CORE-D07 | Transactional Outbox + async REST, durable retry, event_id dedup ở Notification; không broker Increment 1. |
| CORE-D08 | Account ACTIVE/SUSPENDED/DELETION_PENDING/DELETED; Core điều phối xóa dữ liệu, mỗi service xử lý dữ liệu mình sở hữu; không cascade xuyên DB. |

## Giới hạn
Thiết kế mục tiêu, chưa xác minh đầy đủ implementation hiện tại. Không thay đổi application code. Chi tiết schema, DTO, key management, retention, role policy và backlog còn chờ technical design/đối chiếu repository. Kế thừa DOC-T01/T04/T05/T06 khi phù hợp.
