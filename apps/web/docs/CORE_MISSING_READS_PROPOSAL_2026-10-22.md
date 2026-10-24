# Đề xuất read API để mở workspace quản trị Core

**Trạng thái: đã được người dùng cho phép triển khai khi yêu cầu “hoàn thiện all cho xong cái core” sau đề xuất tám API đọc này.** Phạm vi triển khai giữ đúng tám GET bên dưới và các mutation đã duyệt; kết quả kiểm chứng được ghi riêng khi chạy xong. Đây là bước kế tiếp sau [38 operation hiện có đã được duyệt](CORE_REMAINING_CONTRACT_REVIEW_2026-10-22.md). Không thay Business Rules, mutation contract, schema DB, migration hoặc quyền đọc Social/chat. Các DTO chỉ chiếu metadata đang có của module sở hữu.

## Phạm vi đề xuất: 8 GET

Prefix public `/api/v1`. Tất cả yêu cầu actor ACTIVE có role ADMIN và school scope hiện hành trong DB. Tài nguyên ngoài trường/không có trả 404; thiếu/thu hồi phiên trả 401, actor không phải Admin trả 403. Không nhận school_id tùy ý từ browser. Không yêu cầu X-Admin-Reason cho read; không phát sinh mutation ngầm.

| Method/path đề xuất | Response 200 | Module sở hữu / mục đích |
|---|---|---|
| GET /admin/courses | Page[CourseResponse] hiện có `{id,school_id,code,name}` | Classroom; chọn môn học thực khi tạo lớp |
| GET /admin/academic-years | Page[`{id,school_id,label}`] | Classroom; ánh xạ academic_year_id sang nhãn thực |
| GET /admin/academic-years/{year_id}/semesters | Page[`{id,academic_year_id,name}`] | Classroom; chọn đúng semester theo năm thuộc trường |
| GET /admin/homeroom-classes | Page[HomeroomResponse] hiện có | Classroom; chọn lớp hành chính và roster_version thực |
| GET /admin/homeroom-classes/{id}/roster | RosterResponse hiện có `{homeroom_class_id,student_ids,roster_version}` | Classroom; đọc roster hiện hành trước khi sửa |
| GET /admin/classes/{id}/teaching-assignments | TeachingAssignmentResponse[] hiện có, phân công đang hiệu lực | Classroom; biết PRIMARY/ASSISTING thay vì đoán từ quyền đọc lớp |
| GET /admin/users | Page[`{id,email,username,school_id,display_name,status,roles}`] | Identity public interface, Administration router; chọn học sinh/giáo viên và hiển thị tài khoản trong trường |
| GET /admin/users/{id} | DTO tài khoản ở hàng trên | Identity public interface, Administration router; xác nhận trạng thái/role trước và sau mutation riêng rẽ |

Page dùng `{items,next_cursor}`, limit 1..100 mặc định 20, UUID cursor opaque canonical 22 ký tự và ràng buộc cùng phạm vi trường/resource. Chưa đề xuất search/filter bổ sung; frontend có thể lọc trên kết quả đã tải đủ. Response và errors no-store, có correlation ID, không trả password/hash/token/invitation code/refresh family/session_version hoặc private chat. Giữ đúng nullable email/username/display_name; không dựng tên giả.

Administration chỉ gọi public interface Identity; không import model/repository của Identity. DTO Classroom chỉ xuất qua module sở hữu. Public interface mới, schema và permission tests cần review tương ứng; không truy cập bảng service khác.

## Frontend phải thích nghi, không ép backend khớp preview

- Dùng ClassResponse.version, HomeroomResponse.roster_version và preview class_version/roster_version thực. Bỏ giả định workspace/global/account/catalog revision; response UserSummaryDTO của mutation không tự chứa roles.
- Status và roles lưu bằng hai thao tác có trạng thái thành công/lỗi riêng; sau mỗi lần dùng read mới để đối soát. Không biến thành save atomic hoặc tự cấp lastAdmin từ số dòng đang thấy; backend bảo vệ Admin cuối cùng.
- Chỉ mutation đã có: tạo course/homeroom/class, roster, teaching assignments, enrollment, membership và lifecycle. Không tự cho sửa tên lớp/catalog, ngày năm học/học kỳ, OVERRIDE enrollment hoặc durable preview token khi chưa có API tương ứng.
- Grade 6–12 là lựa chọn từ Business Rules, không tạo entity/endpoint grade mới. Nhãn năm/học kỳ lấy từ metadata thực, không suy ngược từ UUID.
- Staff invitation list/resend/revoke, import job/history GET và legacy conversion đơn lẻ chưa có API. Các tính năng đó vẫn không khả dụng; không thêm chúng trong gói 8 GET này.
- Mời staff, import từ file gốc và review data-request đã nối live theo [báo cáo riêng](CORE_ADMIN_FORMS_INTEGRATION_2026-10-22.md). Chúng dùng API hiện có và không phụ thuộc gói 8 GET này; quyền AGY đã được người dùng duyệt và worker/UI đã được review.

## Kiểm chứng bắt buộc trước khi gọi ready

OpenAPI snapshot và decoder/proxy tests; PostgreSQL/HTTP thật qua Web production; pagination nhiều trang và cursor sai scope; 401/403/404/422; cross-school user/year/semester/homeroom/class; LOCKED/revoked actor; không lộ secrets; assignment/roster/status thay đổi trong lúc tải; actor đổi/cancel/timeout không trả partial success. Có browser thì kiểm chứng chọn dữ liệu và mutation riêng rẽ; không dùng test adapter làm bằng chứng backend.

Owner cần review khi có PR: Core.Classroom, Core.Identity/Administration, Common transport và Web. Chưa có quyết định triển khai gói này; báo cáo tích hợp hiện tại vẫn chỉ chứng nhận 55 operation đã duyệt.
