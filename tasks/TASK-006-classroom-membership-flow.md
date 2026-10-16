# TASK-006: Classroom Enrollment AUTO/MANUAL & Transfer Workflow

- **Mã Task:** `TASK-006`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `A1–A6`, `F2`, `L2`, `M1`, `O4`
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md), [DESIGN.md](../docs/architect/microservices-v1/core/DESIGN.md)


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** chưa có service/router membership. Luồng xin vào bằng mã, giáo viên approve/reject/remove và Student self-leave cũ đã bị thay thế hoàn toàn trong phạm vi task này.

**Cần sửa:** triển khai ghi danh AUTO/MANUAL do Admin điều phối, sync roster, preview/confirm và chuyển lớp giữ lịch sử; không chỉ đổi tên JoinRequest.

**Phụ thuộc:** TASK-005 chốt ERD; TASK-004 xác minh user; TASK-008 chốt action access; TASK-012/014 bảo đảm outbox/migration. Hiệu lực chuyển lớp, preview snapshot và idempotency bền vững phải được thiết kế trước phần mutation tương ứng.

---

## 1. Mục tiêu

Admin quản lý thành viên chính thức theo A1–A6, F2 và L2. Student không tự join/leave; giáo viên không sửa roster/ghi danh. Thay đổi membership kết thúc quyền tham gia mới nhưng giữ lịch sử cá nhân hợp lệ.

## 2. Chi tiết cần triển khai

### 2.1. Ghi danh và đồng bộ

- AUTO lấy roster lớp hành chính theo liên kết đã duyệt; sync lặp không nhân đôi membership và không ghi đè lớp MANUAL.
- MANUAL nhận danh sách do Admin quản lý. Ngoại lệ của lớp AUTO phải chuyển MANUAL; đổi MANUAL→AUTO có preview tác động và confirm, không âm thầm thay roster.
- Thiết kế preview/confirm gắn đúng actor/trường, tập dữ liệu và phiên bản; xử lý roster thay đổi sau preview, hết hạn hoặc xác nhận lặp. Chi tiết token/lưu trữ/thời hạn là PENDING DESIGN.
- Mutation kiểm tra Admin hiện hành, scope trường/lớp, trạng thái user/lớp và transaction/constraint. Thiết kế khóa chống lặp bền vững cho sync/import; không dùng RAM cache auth như bảo đảm qua restart.
- Cùng transaction ghi membership, audit và outbox; publisher retry sau commit. Lỗi gửi notification sau commit không đảo ngược thay đổi đã lưu.

### 2.2. Chuyển lớp và kết thúc ghi danh

- Giữ từng đợt membership và mốc hiệu lực, không xóa user/bài nộp/điểm/chat/notes.
- Chấm dứt quyền tham gia lớp cũ và xem nội dung mới; TASK-008 cấp quyền đọc lịch sử cá nhân theo action riêng.
- Chốt transfer cutoff và hợp đồng sự kiện với Learning trước tích hợp: bài đã nộp tiếp tục được chấm, bài chưa nộp đóng theo thiết kế; timed attempt theo assessment policy, không tự coi đã hoàn thành.
- Không tự đặt thời hạn phúc khảo hoặc di chuyển toàn bộ dữ liệu học tập sang lớp mới. TASK-019 sở hữu kết quả/attempt/appeal.

### 2.3. API và tích hợp

- Dùng nhóm route Admin enrollment/roster/members đang **PROPOSED** tại Core API Contract; payload, method roster và mã lỗi phải chốt trước code.
- Không triển khai các route join-requests, Student members/me DELETE hoặc Lecturer membership mutation theo bản task cũ.
- Chuẩn hóa kết quả sync/preview, lỗi/trùng và retry với import TASK-013; chỉ enrollment owner ghi membership, không để importer query/ghi trực tiếp bảng Classroom.

## 3. Tiêu chí nghiệm thu

- [ ] Student/Lecturer bị chặn mọi mutation roster/enrollment/transfer; Admin khác trường hoặc thiếu school scope không truy cập được.
- [ ] 100 thao tác sync/transfer/import cạnh tranh có kiểm soát không sinh membership hiện hành trùng, không mất lịch sử; retry/out-of-order không áp dụng lại thay đổi cũ.
- [ ] MANUAL không bị AUTO ghi đè; MANUAL→AUTO cần preview/confirm; preview stale được xử lý theo contract đã duyệt.
- [ ] Sau chuyển lớp, không xem feed mới/hỏi AI mới ở lớp cũ; đọc điểm/bài đã nộp/appeal/chat/notes của chính mình theo quyền giới hạn và grant nguồn.
- [ ] Audit/outbox nhất quán với commit, rollback không phát notification; contract/public interface và integration tests được cập nhật.
