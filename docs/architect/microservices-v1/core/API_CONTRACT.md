# Hợp đồng API Core v0 — Bản thảo

**Trạng thái:** [ĐỀ XUẤT], chưa được duyệt, chưa có OpenAPI chạy thực tế. **Ngày:** 11/10/2026.

Tài liệu giúp Frontend/Backend thống nhất giao tiếp trước khi code; **không phải danh sách endpoint đã tồn tại**. Đối chiếu [thiết kế Core](DESIGN.md), [Business Rules](../../BUSINESS_RULES.md) và [lộ trình](../IMPLEMENTATION_ROADMAP.md).

## 1. Quy ước — [ĐỀ XUẤT]
- Base path: `/api/v1`; HTTP/JSON; tài nguyên dùng ID không đoán được.
- Xác thực: chưa chọn cookie-session hay bearer token; ví dụ không áp đặt một cơ chế.
- Mã lỗi tham khảo: `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`.
- Không tiết lộ thông tin lớp/tài khoản không có quyền; có thể trả `404` thay `403` tùy chính sách.
- `correlation_id` trong log và phản hồi lỗi; không đưa mật khẩu/token vào log.
- Phân trang cho danh sách; mọi kiểm tra quyền thực hiện tại Backend.
- Các tên field và mã trạng thái dưới đây chỉ là **bản phác thảo hợp đồng**.

## 2. Endpoint dự kiến
| Method | Đường dẫn | Người được phép | Mục đích / Rule |
|---|---|---|---|
| POST | `/auth/login` | Chưa đăng nhập | Xác thực (F1, K2) |
| POST | `/auth/logout` | Đã đăng nhập | Kết thúc phiên |
| GET | `/users/me` | Đã đăng nhập | Xem hồ sơ và vai trò |
| POST | `/classes` | Lecturer | Tạo lớp, không cần Admin duyệt |
| GET | `/classes` | Đã đăng nhập | Danh sách lớp được phép xem |
| GET | `/classes/{class_id}` | Thành viên được phép / Admin | Xem lớp; kiểm tra quyền hiện tại |
| PATCH | `/classes/{class_id}` | Giảng viên có quyền / Admin | Cập nhật cấu hình, nhận yêu cầu (A6) |
| POST | `/classes/join-requests` | Student | Xin vào bằng mã lớp (A1) |
| GET | `/classes/{class_id}/join-requests` | Giảng viên có quyền | Danh sách chờ duyệt |
| POST | `/classes/{class_id}/join-requests/{request_id}/approve` | Giảng viên có quyền | Duyệt thành viên (A1) |
| POST | `/classes/{class_id}/join-requests/{request_id}/reject` | Giảng viên có quyền | Từ chối |
| GET | `/classes/{class_id}/members` | Thành viên được phép | Danh sách thành viên theo chính sách |
| DELETE | `/classes/{class_id}/members/me` | Student / Lecturer theo điều kiện | Rời lớp (A5, H2) |
| DELETE | `/classes/{class_id}/members/{user_id}` | Giảng viên có quyền / Admin | Loại thành viên (A4, M2) |
| POST | `/classes/{class_id}/co-lecturers/invitations` | Giảng viên chính | Mời đồng giảng viên (A3) |
| POST | `/classes/{class_id}/ownership-transfer` | Giảng viên chính / Admin | Chuyển chủ (H1–H2) |
| POST | `/classes/{class_id}/archive` | Giảng viên chính / Admin | Lưu trữ (F5) |
| POST | `/classes/{class_id}/restore` | Giảng viên chính / Admin | Khôi phục (M5) |
| PATCH | `/admin/users/{user_id}/status` | Admin | Khóa/mở tài khoản (F1, K2) |
| GET | `/internal/v1/classes/{class_id}/access` | Service tin cậy, xác thực nội bộ | Kiểm tra quyền hiện tại cho service khác |

**Chưa đặc tả trong bảng này:** quản lý tài khoản/role đầy đủ, feed, comments, lịch, thông báo, ghi chú, yêu cầu dữ liệu cá nhân, báo cáo. Những phần này **vẫn thuộc MVP** và phải được thêm hợp đồng khi bắt đầu increment tương ứng.

## 3. Ví dụ request/response — [ĐỀ XUẤT]
### Xin tham gia lớp
```http
POST /api/v1/classes/join-requests
Content-Type: application/json

{"join_code":"EXAMPLE123"}
```
```json
{"request_id":"req_example","class_id":"class_example","status":"PENDING"}
```
Sinh viên **chưa có quyền xem nội dung** cho đến khi được duyệt (A1).

### Duyệt tham gia
```http
POST /api/v1/classes/class_example/join-requests/req_example/approve
```
```json
{"request_id":"req_example","class_id":"class_example","student_id":"user_example","membership_status":"ACTIVE"}
```
Duyệt lặp phải có kết quả xác định, không tạo membership trùng; lựa chọn trả `200` hay `409` khi duyệt lại vẫn [CHƯA CHỐT].

### Kiểm tra quyền nội bộ
```http
GET /internal/v1/classes/class_example/access?user_id=user_example&action=read
```
```json
{"allowed":true,"class_id":"class_example","user_id":"user_example","action":"read"}
```
**Bắt buộc:** chỉ service đã xác thực và được cấp quyền mới gọi được; không tin `user_id` từ client công khai. Khi Core không khả dụng, service gọi phải từ chối thao tác nhạy cảm (fail closed). Kết quả không thay thế kiểm tra quyền tài liệu hiện hành tại Document.

### Lỗi thống nhất
```json
{"error":{"code":"FORBIDDEN","message":"Không có quyền thực hiện thao tác","correlation_id":"trace_example"}}
```

## 4. Ma trận quyền tối thiểu
| Hành động | Admin | Lecturer chính | Đồng giảng viên | Student |
|---|---|---|---|---|
| Tạo lớp | Theo quyền quản trị [CHƯA CHỐT] | Có | Có khi tạo lớp của chính mình | Không |
| Duyệt thành viên | Can thiệp | Có | Có | Không |
| Loại thành viên | Can thiệp | Có | Có trong phạm vi quyền | Không |
| Chuyển chủ lớp | Can thiệp | Có | Không | Không |
| Lưu trữ/khôi phục | Can thiệp | Có | Không mặc định | Không |
| Xem nội dung lớp | Theo quyền quản trị [CHƯA CHỐT] | Có | Có | Chỉ khi ACTIVE |

Ma trận diễn giải các Business Rules để triển khai; các ô [CHƯA CHỐT] không được coi là quyền đã duyệt.

## 5. Checklist trước khi đóng băng API
- [ ] Thống nhất xác thực, thu hồi phiên, CSRF/rate limit.
- [ ] Thống nhất trạng thái lớp, membership, join request và xử lý lặp/cạnh tranh.
- [ ] Bổ sung JSON Schema/OpenAPI cho từng endpoint, lỗi và phân trang.
- [ ] Review ma trận quyền với Business Rules; test unauthorized và cross-class.
- [ ] Thống nhất service-to-service authentication và contract test.
- [ ] Có mock server/fixtures để Frontend phát triển song song.

Không tuyên bố API đã hoạt động khi chưa có code và test.
