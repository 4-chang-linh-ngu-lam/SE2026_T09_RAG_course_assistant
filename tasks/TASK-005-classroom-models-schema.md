# TASK-005: Classroom Models & Schema

- **Mã Task:** `TASK-005`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `A1–A8`, `F2`, `H1–H2`, `L2`, `M5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md)


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** Classroom mới có skeleton, chưa có ORM/router nghiệp vụ. Đặc tả JoinRequest/CoLecturerInvitation/owner_user_id trước đây đã bị baseline thay thế; không dùng làm kế hoạch tạo bảng mới.

**Cần sửa:** thiết kế School, năm học/học kỳ, lớp hành chính/roster, lớp môn học, phân công PRIMARY/ASSISTING và enrollment AUTO/MANUAL theo [Core Design](../docs/architect/microservices-v1/core/DESIGN.md). Đây là entity logic; tên bảng, enum kỹ thuật, FK và payload phải được TV2/TV1/TV4 review trước triển khai.

**Phụ thuộc:** TASK-004 cung cấp Identity DTO; task này chốt schema cho TASK-006–008 và TASK-014. Mapping trường cho user legacy và thời điểm hiệu lực chuyển lớp còn PENDING DESIGN; không tự backfill.

---

## 1. Mục tiêu

Thiết kế và triển khai dữ liệu Classroom cho một trường THCS/THPT, khối 6–12. Chỉ Admin tạo lớp, roster và phân công; mỗi năm tạo lớp môn học mới, lớp cũ archive. Không có join code/join request, giáo viên tự tạo lớp hoặc lời mời/chuyển chủ giữa giáo viên.

## 2. Chi tiết cần triển khai

### 2.1. Models và schema

- Classroom sở hữu School, AcademicYear, Semester, HomeroomClass, HomeroomRoster, Course/SubjectClass, TeachingAssignment và ClassMembership theo Core Design.
- Lớp môn học có phạm vi trường, môn, khối 6–12, năm học/học kỳ, liên kết lớp hành chính tương ứng và mode AUTO/MANUAL; lớp ghép/tự chọn dùng MANUAL theo A7. Chốt cardinality/liên kết cụ thể trong ERD, không suy đoán từ schema legacy.
- TeachingAssignment biểu diễn PRIMARY/ASSISTING, thời gian hiệu lực và lịch sử. Đây là quan hệ theo lớp, không thêm global role hoặc coi OWNER legacy là quyền Admin.
- Membership lưu nguồn ghi danh, khoảng hiệu lực, trạng thái và từng đợt tham gia; ràng buộc chỉ một membership hiện hành cho cặp học sinh–lớp, bảo toàn lịch sử khi chuyển/tái ghi danh.
- School scope phải nhất quán giữa user, roster, lớp và phân công; user/status/role kiểm tra qua Identity public. FK nội Core được review trong ERD/migration, không import model/repository Identity để xử lý nghiệp vụ.
- Bổ sung index/constraint phục vụ danh sách, đồng bộ và cạnh tranh dựa trên query thực tế. Không cascade xóa lịch sử học tập chỉ vì kết thúc membership.

### 2.2. DTO và repository

- DTO tạo/cập nhật lớp, roster, phân công, membership và preview phải phản ánh metadata mới, không nhận school/actor do browser tự cấp.
- Loại join_code/join_enabled/JoinRequest/CoLecturerInvitation khỏi hợp đồng mục tiêu. Nếu sau này phát hiện dữ liệu lịch sử có các trường này, chuyển đổi bằng migration mới, không sửa revision đã áp dụng.
- Query theo school/class, membership có hiệu lực và lịch sử; batch lookup user qua TASK-004. Không dùng email làm định danh bắt buộc cho học sinh.
- Chốt transaction/locking và khóa chống lặp với TASK-006/007 trước migration; không chỉ dựa vào kiểm tra tồn tại trong Python.

## 3. Tiêu chí nghiệm thu

- [ ] ERD, state machine và DTO thống nhất với Core Design/API Contract; payload chưa chốt được đánh dấu PENDING DESIGN, không phát hành như API đã duyệt.
- [ ] PostgreSQL thực kiểm tra constraint khối 6–12, quan hệ cùng trường và một membership hiện hành; tái ghi danh không mất đợt cũ.
- [ ] Phân công giáo viên giữ bất biến giáo viên chính theo H2; không tạo quan hệ chéo trường hoặc cho Student thành giáo viên bằng dữ liệu request.
- [ ] TASK-014 có revision mới và phương án mapping School được duyệt, giữ nguyên user ID/dữ liệu cũ; không dùng SQLite thay bằng chứng constraint PostgreSQL.
- [ ] Schema không phát sinh join code, self-join, teacher invitation hoặc ownership transfer trong MVP.
