# TASK-014: Core Database Migrations & Seed Data

- **Mã Task:** `TASK-014`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `TV4` (Phối hợp với `TV1`, `TV2`, `TV3`)
- **Module:** `services/core/migrations/`
- **Business Rules liên quan:** `A1–A8`, `F1–F2`, `F7`, `H1–H2`, `K5`
- **Tài liệu căn cứ:** [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#4-quy-tắc-giảm-git-conflict-cho-4-người)

**Cập nhật sau PR #10 (2026-10-19):** Main hiện có head `0012`; full Core PostgreSQL 16 đạt 342 passed, 0 skipped và CI PR #10 xanh. Mapping School dữ liệu thực, FK `users.school_id` và owner approval vẫn pending.


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

- [x] PostgreSQL 16 sạch: upgrade head và alembic check đạt, metadata không drift, lịch sử migration một head hợp lệ.
- [x] Upgrade từ 0004 và head đang dùng giữ dữ liệu legacy; công cụ mapping report/plan/apply được kiểm thử bằng fixture; cross-school/FK/unique constraints được kiểm tra thật.
- [ ] Mapping School **dữ liệu thực** được TV1/TV2 review trước backfill/FK: chưa có manifest được duyệt, không tự tạo trường/gán scope hoặc bật users.school_id FK. Công cụ và runbook đã sẵn sàng.
- [x] Round trip downgrade/upgrade trên fixture tương thích; fixture không tương thích bị chặn có giải thích, không mất dữ liệu.
- [x] Test membership/assignment cạnh tranh và audit/outbox persistence theo schema đã duyệt; không áp dụng tổng số bảng cố định.
- [x] Seed lặp không tạo trùng, không ghi secret/log mã, chỉ tác động database test/dev được chỉ định; TASK-016 vẫn chạy migration trước startup. CI bổ sung heads/report artifact, full suite có test maintenance. Trạng thái remote tại thời điểm viết được cập nhật ở phần cuối.

## 4. Triển khai — 2026-10-19

- Giữ nguyên lịch sử 0001–0012; task này không đổi schema nên không thêm revision placeholder. Registry metadata dùng chung Alembic/maintenance, giới hạn schema Core; single-head và coverage của danh sách bảng được guard có test.
- Guard downgrade đặt ở env/tooling, lấy transaction lock và khóa writer trước kiểm tra; DDL/guard cùng transaction. Chặn mất bảng có dữ liệu, audit school scope, Student identifiers và outbox envelope/retry. Constraint cũ tiếp tục chặn email-free/purpose/CORRECTION không biểu diễn được; không xóa dữ liệu để ép thành công. SQL downgrade offline bị từ chối; SQL upgrade range được kiểm thử.
- CLI `python -m app.maintenance`: report legacy; plan/apply School từ manifest + hash review, recheck drift và lịch sử Classroom, chặn remap sang trường khác, giữ UUID/hash/status/request/token history; scope đổi revoke refresh sessions và audit. Không tự kích hoạt/mở LOCKED hoặc suy mapping audit lịch sử.
- Seed dev/test chính thức: database riêng có prefix và expected-name, initial empty preflight, mật khẩu Admin riêng qua môi trường, random credential riêng cho tài khoản tổng hợp còn lại. Owner fixture bootstrap School/Admin; invitation/activation và Classroom workflows giữ audit/outbox trong transaction chung. Tạo 7 homeroom khối 6–12, 14 lớp AUTO/MANUAL, PRIMARY/ASSISTING, roster khối 9; Student pending để thử cấp mã. Marker bền vững giúp repeat/concurrency không trùng/reset; lỗi rollback cả seed.
- API HTTP không đổi; Identity/Classroom public thêm maintenance helpers, Common audit allowlist thêm school_id. Shared/owner review cần TV1 (Identity), TV2 (School/Classroom), TV3 (metadata Social) và CI/TASK-016. Không commit/push/deploy trong task.
- Hướng dẫn lệnh, manifest, rollback và giới hạn: [Core migrations runbook](../services/core/migrations/README.md).

## 5. Bằng chứng local — 2026-10-19

- Python 3.12.14, PostgreSQL 16 container test riêng: `pytest -q -W error -p no:cacheprovider --tb=short` → **313 passed**, không skip (171.34 giây); gồm **23 test maintenance** cùng các test migration/Notification/Administration/Classroom/Identity hiện có.
- `pytest tests/identity/test_public.py -q -W error -p no:cacheprovider --cov=app.modules.identity.public --cov-branch --cov-fail-under=100` → **17 passed, 100% line/branch**.
- `ruff check app tests migrations` và `ruff format --check app tests migrations` đạt; **127 file** format đúng. `alembic heads` → **0012 (head)**; upgrade/check/roundtrip được chạy thật trong test, gồm schema khác service không bị tác động.
- Docker Core build thành công; smoke trong wheel/site-packages với UID 10001: upgrade head/check, seed lần đầu/lặp, report 6 user và check không drift đều đạt. Mật khẩu test sinh riêng trong môi trường, không xuất ra log; tài nguyên Docker test được dọn sau kiểm thử.
- CI workflow bổ sung `alembic heads --verbose`, read-only maintenance report và artifact; full PostgreSQL suite bao gồm maintenance/CLI. Tại thời điểm ghi chú này trước khi push, chưa có kết quả remote CI; PR #10 sau đó đã đạt CI, còn owner approval và nghiệm thu toàn Core G2 vẫn pending.
