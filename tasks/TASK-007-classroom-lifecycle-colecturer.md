# TASK-007: Classroom Lifecycle & Admin Teaching Assignments

- **Mã Task:** `TASK-007`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `A3`, `A7–A8`, `F5`, `H1–H2`, `H5`, `M2`, `M5`, `O2`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** lifecycle/phân công chưa triển khai. Teacher invitation, ownership transfer và Owner archive/restore trong task cũ không còn được phép trong MVP.

**Cần sửa:** thay bằng phân công PRIMARY/ASSISTING và archive/restore do Admin; tách quyền dạy học với quản lý roster và quyền phê duyệt đánh giá nhạy cảm.

**Phụ thuộc:** TASK-005 chốt dữ liệu, TASK-006 giữ enrollment history, TASK-008 cung cấp action checks; phối hợp TASK-012/013/019 cho thông báo, audit và approval. Mốc hiệu lực thay giáo viên cần chốt cùng chính sách chuyển lớp.

---

## 1. Mục tiêu

Quản lý vòng đời lớp môn học và phân công giáo viên theo A3/A7/A8, F5, H1/H2, M2/M5. Giáo viên chỉ thực hiện hoạt động giảng dạy trong lớp được Admin phân công.

## 2. Chi tiết cần triển khai

### 2.1. Phân công giáo viên

- Admin cùng trường thêm/thay/kết thúc phân công PRIMARY/ASSISTING; xác minh tài khoản giáo viên và quyền hiện hành qua Identity public.
- Khi giáo viên chính rời lớp, Admin phân công người thay thế trước khi thay đổi có hiệu lực; transaction/locking giữ bất biến khi có yêu cầu cạnh tranh.
- Giữ lịch sử phân công, lý do/audit và event versioned để consumer không giữ quyền cũ.
- Không tạo global role CO_LECTURER hoặc API lời mời/chấp nhận/chuyển chủ giữa giáo viên.
- Giáo viên phối hợp quản lý tài liệu/nháp hoạt động, chấm bài được phân công; không sửa roster, phân công giáo viên hoặc tự công bố Assessment/sửa điểm nhạy cảm. Learning sở hữu approval nghiệp vụ tương ứng.

### 2.2. Archive/restore

- Chỉ Admin archive/restore qua nhóm route Admin đã đề xuất trong Core API Contract; không dùng Owner archive route legacy.
- ARCHIVED chặn ghi hoạt động chung, participation và câu hỏi AI mới; quyền xem lịch sử không tự biến thành quyền ghi.
- O2 vẫn cho học sinh sửa notes/bookmarks cá nhân với nguồn còn quyền; Document thực thi, không chặn tất cả mutation của mọi service bằng một cờ archived.
- Restore áp dụng trạng thái user, assignment, membership và grant hiện hành; không khôi phục quyền cũ đã hết hiệu lực.
- Mỗi năm học tạo lớp môn học mới, archive lớp cũ theo Admin; không tái sử dụng lớp cũ bằng cách đổi năm làm mất ngữ cảnh lịch sử.

### 2.3. Permissions và tích hợp

- Quyền theo actor hiện hành + trường/lớp + action; global LECTURER hoặc lịch sử từng là giáo viên không đủ quyền.
- Gọi Common/Identity public, ghi audit/outbox cùng transaction; chốt payload/mã lỗi trong contract trước triển khai.
- TASK-008 công bố quyền cho Social/Document/AI/Learning; consumer không đọc trực tiếp bảng TeachingAssignment.

## 3. Tiêu chí nghiệm thu

- [ ] Student/Lecturer không thể tự phân công, mời giáo viên, chuyển chủ, archive hoặc restore.
- [ ] Thay giáo viên chính cạnh tranh không tạo hai phân công chính có hiệu lực hoặc để thiếu người thay theo H2; audit/lịch sử được giữ.
- [ ] ARCHIVED chặn hoạt động chung/AI mới; vẫn đọc lịch sử cá nhân hợp lệ và sửa notes/bookmarks theo O2.
- [ ] Restore không cấp lại assignment/membership/grant đã thu hồi; cross-school và tài khoản LOCKED bị chặn.
- [ ] Test giới hạn ASSISTING và PRIMARY approval ở consumer Learning; chưa có Learning thì dùng contract test, không tuyên bố đã kiểm chứng toàn luồng.
