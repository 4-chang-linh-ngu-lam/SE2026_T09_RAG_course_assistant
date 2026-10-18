# TASK-014: Core Database Migrations & Seed Data

- **Mã Task:** `TASK-014`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `TV4` (Phối hợp với `TV1`, `TV2`, `TV3`)
- **Module:** `services/core/migrations/`
- **Business Rules liên quan:** `A1–A8`, `F1–F2`, `F7`, `H1–H2`, `K5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#4-quy-tắc-giảm-git-conflict-cho-4-người)


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** đã có migration 0001 baseline, 0002 audit, 0003 auth, 0004 data requests, 0005 CORRECTION, 0006 Student fields và 0007 Student token purposes. Không tạo lại revision 0002 hoặc yêu cầu cố định “12 bảng” như task cũ.

**Cần sửa:** thêm migration theo schema thực sự được duyệt của từng module; thiết kế mapping School và chuyển dữ liệu cũ, không sửa migration đã áp dụng.

**Phụ thuộc:** TV1–TV4 cung cấp model/contract theo TASK-002/004–013; TV2 sở hữu School, TV1 sở hữu users.school_id. Rà soát dữ liệu cần giữ trước khi chốt FK/backfill.

---

## 1. Mục tiêu

Quản lý lịch sử Alembic và dữ liệu mẫu của Core, bảo đảm từ database sạch hoặc phiên bản đang dùng đều nâng cấp được mà không mất dữ liệu hợp lệ. Không suy ra schema đã tồn tại chỉ từ bảng thiết kế.

## 2. Chi tiết cần triển khai

### 2.1. Metadata và revision

- Giữ `target_metadata`, schema `core` và version table hiện có; đăng ký model khi module được triển khai, không tạo placeholder cho mọi entity.
- Chốt ERD mới ở TASK-005: School/năm học/học kỳ/lớp hành chính/roster/lớp môn học, PRIMARY/ASSISTING, membership theo đợt và AUTO/MANUAL; không thêm JoinRequest/CoLecturerInvitation/join code theo thiết kế cũ.
- Tạo revision mới dựa trên head thực tế; nếu nhiều head thì review phụ thuộc và merge revision. Không ấn định trước số/tên revision kế tiếp trong task.
- Social, Notification/outbox và các thay đổi audit cần migration riêng theo feature; constraint/index phải khớp contract được duyệt, gồm thời gian Calendar `starts_at < ends_at`.
- FK chỉ trong Core; không nối FK đến bảng Document/AI/Learning/Learner Intelligence. Không cascade xóa lịch sử học tập khi user bị khóa hoặc membership kết thúc.

### 2.2. Dữ liệu legacy và School

- Hiện users.school_id nullable chưa có FK; không coi nó là bằng chứng School entity đã có. Tạo School và mapping tài khoản cũ theo phương án được duyệt trước backfill/constraint.
- Báo rõ user thiếu scope, username trùng/không hợp lệ và tài khoản chưa chuyển; không tự tạo trường giả hoặc tự kích hoạt/mở LOCKED.
- Identity public helper xử lý gán username/chuyển credential có audit/revocation; migration schema không thay thế workflow này.
- Upgrade phải giữ UUID/hash/trạng thái/yêu cầu dữ liệu/token lịch sử theo hợp đồng. Downgrade gặp dữ liệu không biểu diễn được ở phiên bản cũ phải từ chối rõ ràng, không xóa dữ liệu để ép thành công.

### 2.3. Seed dev/test

- Chỉ dùng database test/dev riêng và dữ liệu tổng hợp; seed có khả năng chạy lại, không có mật khẩu mặc định dùng chung/hardcode credential.
- Seed School và Admin trước, staff email, Student username/activation; tạo roster/lớp môn học khối 6–12, AUTO/MANUAL và PRIMARY/ASSISTING khi các module tương ứng tồn tại.
- Dùng public workflow khi kiểm thử hành vi; fixture DB trực tiếp chỉ để chuẩn bị test trong module sở hữu, không trở thành đường onboarding bỏ qua bảo mật.
- Không biến bootstrap trong demo-ui bị gitignore thành seed chính thức của project; chốt command/config dùng lại tại thư mục phù hợp trước khi thêm.

## 3. Tiêu chí nghiệm thu

- [ ] PostgreSQL 16 sạch: upgrade head và alembic check đạt, metadata không drift, lịch sử migration một head hợp lệ.
- [ ] Upgrade từ 0004 và head đang dùng giữ dữ liệu legacy; mapping School/backfill được review, cross-school/FK/unique constraints được kiểm tra thật.
- [ ] Round trip downgrade/upgrade trên fixture tương thích; fixture không tương thích bị chặn có giải thích, không mất dữ liệu.
- [ ] Test membership/assignment cạnh tranh và audit/outbox persistence theo schema đã duyệt; không áp dụng tổng số bảng cố định.
- [ ] Seed lặp không tạo trùng, không ghi secret/log mã, chỉ tác động database test/dev được chỉ định; TASK-016 chạy migration trước startup và CI có bằng chứng.
