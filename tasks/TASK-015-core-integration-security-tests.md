# TASK-015: Core Comprehensive Security & Integration Test Suite

- **Mã Task:** `TASK-015`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `Cả nhóm (TV1, TV2, TV3, TV4)`
- **Module:** `services/core/tests/`
- **Business Rules & Attributes:** `QAS-04`, `QAS-05`, `Core-01` đến `Core-06`
- **Tài liệu căn cứ:** [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#6-kiểm-thử-core-g1g2), [IMPLEMENTATION_ROADMAP.md](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md#checklist-nghiệm-thu-core)

---

## 1. Mục tiêu
Xây dựng và thực thi bộ kiểm thử tích hợp (Integration Tests) và kiểm thử bảo mật (Security Tests) toàn diện cho Core Service, sử dụng kết nối cơ sở dữ liệu PostgreSQL thực tế trong môi trường Docker test container, đáp ứng các tiêu chuẩn nghiệm thu từ `Core-01` đến `Core-06`.

---

## 2. Chi tiết các kịch bản kiểm thử bắt buộc

### 2.1. Kiểm thử Phân quyền & Cô lập dữ liệu (Core-01 & QAS-04)
- **Cross-class isolation:** Sinh viên thuộc Lớp A không thể xem/đăng bài/bình luận/xem lịch của Lớp B (trả về `404` hoặc `403`).
- **Trạng thái tài khoản:**
  - Tài khoản `LOCKED` bị chặn ở mọi API.
  - Tài khoản `PENDING_VERIFICATION` không thể đăng nhập.
- **Trạng thái thành viên:**
  - Thành viên `PENDING` (chờ duyệt) không thể xem nội dung hay thành viên trong lớp.
  - Thành viên `LEFT` (tự rời) hoặc `REMOVED` (bị loại) lập tức bị chặn mọi quyền truy cập vào tài nguyên lớp.
- **Trạng thái lớp:** Lớp `ARCHIVED` chặn mọi thao tác ghi (đăng bài mới, bình luận mới, thêm thành viên mới).

### 2.2. Kiểm thử Cạnh tranh & Toàn vẹn dữ liệu (Core-02)
- **Concurrent Join Approval:** Giả lập 50–100 request duyệt đồng thời trên cùng một `JoinRequest` $\to$ Đảm bảo chỉ có duy nhất 1 bản ghi `ClassMembership` `ACTIVE` được tạo.
- **Concurrent Ownership Transfer:** Giả lập thao tác chuyển quyền đồng thời $\to$ Đảm bảo một lớp không bao giờ có 2 `OWNER` cùng lúc.

### 2.3. Kiểm thử Bảo mật Xác thực (Core-03)
- **Refresh Token Rotation & Replay Detection:** Khi một refresh token cũ đã được rotate bị dùng lại $\to$ Toàn bộ `family_id` bị thu hồi ngay lập tức, vô hiệu hóa phiên kẻ tấn công.
- **Logout-all:** Kiểm tra sau khi gọi `logout-all`, tất cả token phát hành trước đó đều bị từ chối truy cập.
- **Origin/CSRF Protection:** Gọi API dùng cookie mutation mà không có header Origin/Referer tin cậy bị từ chối `403`.
- **Rate Limiting:** Gửi quá số lần thử đăng nhập/đăng ký quy định trả về mã lỗi `429 RATE_LIMITED`.

### 2.4. Kiểm thử Tích hợp Xuyên Module (Core-04)
- Quy trình end-to-end: Sinh viên gửi mã $\to$ Giảng viên nhận thông báo $\to$ Giảng viên duyệt $\to$ Sinh viên nhận thông báo $\to$ Sinh viên đăng bài $\to$ Giảng viên bình luận $\to$ Giảng viên xóa bình luận $\to$ Kiểm tra log trong `audit_events`.
- Kiểm tra tính chất read-only của lịch đối với sự kiện có `origin = LEARNING`.

### 2.5. Đo kiểm Hiệu năng (Core-06 & QAS-05)
- Đo độ trễ p95 theo cấu hình TP-01:
  - `GET /classes`: p95 $\le$ **500 ms**.
  - Kiểm tra tỷ lệ thành công $\ge$ **99%**.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Chạy lệnh `pytest tests/ -v` trên môi trường PostgreSQL sạch, 100% test cases pass.
- [ ] Lưu lại báo cáo kết quả kiểm thử thực tế (Test Report kèm log thực tế) chứng minh đạt các tiêu chí Core-01 đến Core-06.
- [ ] Không có bất kỳ rò rỉ dữ liệu hoặc quyền ngoài mong muốn nào được phát hiện trong quá trình chạy test.
