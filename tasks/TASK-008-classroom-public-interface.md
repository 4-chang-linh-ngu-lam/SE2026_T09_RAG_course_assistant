# TASK-008: Classroom Public Interface & Internal Access Check API

- **Mã Task:** `TASK-008`
- **Giai đoạn:** `G1 — Core chức năng đầy đủ`
- **Owner chính:** `TV2`
- **Module:** `services/core/app/modules/classroom/`
- **Business Rules liên quan:** `H4–H5`, `L2`, `M1`, `O4`, `F3`; QAS-04
- **Tài liệu căn cứ:** [API_CONTRACT.md](../docs/architect/microservices-v1/core/API_CONTRACT.md), [FOLDER_STRUCTURE.md](../docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md#5-luồng-phụ-thuộc-và-quy-tắc-import)


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng cập nhật:** Classroom public/internal access API đã dùng action theo user/status/school/class/membership/teaching assignment hiện hành; internal API yêu cầu X-Service-Key. Đọc lịch sử cá nhân tách participation, nhưng consumer vẫn phải kiểm tra owner/Document grant/Learning assignment. Những hàm membership-only trong bản task cũ chỉ là draft, không phải public contract đã phát hành.

**Cần sửa:** access theo action, quyền lịch sử và school scope; bỏ quy tắc kết thúc membership là mất mọi quyền. Header phải khớp code `X-Service-Key`, không phải `X-Internal-Service-Key` hoặc user JWT.

**Phụ thuộc:** TASK-005–007 chốt dữ liệu/quyền, TV1 review auth/public, TV3/TV4 và owner Document/AI/Learning review DTO/action contract trước dùng.

---

## 1. Mục tiêu

Cung cấp một chính sách quyền Classroom dùng chung cho Python consumer trong Core và REST consumer liên service. Fail closed khi không xác minh được, đồng thời giữ ngoại lệ lịch sử hợp lệ theo H4/H5, L2, M1 và O4.

## 2. Chi tiết cần triển khai

### 2.1. Public interface trong Core

- Export DTO an toàn và thao tác kiểm tra quyền theo action; chữ ký cụ thể phải được chốt trong Core Design/API Contract trước triển khai.
- Phân biệt các nhóm action đang được Design đề xuất: `participate_current_class`, `read_own_history`, `read_document_source`, `use_ai_tutor`, `grade_submitted_work`. Không coi tên này là enum đã được phát hành.
- Global role, trạng thái tài khoản, school scope, trạng thái lớp, membership/assignment hiện hành hoặc bằng chứng lịch sử đều phải được xét theo action.
- ACTIVE membership không đủ để quyết định mọi quyền; học sinh kết thúc enrollment vẫn có thể đọc dữ liệu của mình được cho phép. Consumer sở hữu tài nguyên phải xác minh owner và phạm vi dữ liệu lịch sử.
- Core chỉ xác minh quyền lớp; Document kiểm tra grant nguồn hiện hành, Learning kiểm tra attempt/assessment/grading assignment, AI kiểm tra owner/chia sẻ chat. Không trả allowed=true như quyền đọc mọi tài nguyên.

### 2.2. Internal access API

- Route đã đề xuất: `GET /internal/v1/classes/{class_id}/access?user_id=&action=`; còn chờ chốt request/response/action/error contract.
- Bắt buộc `X-Service-Key` với `INTERNAL_SERVICE_SECRET` và scope `core:check_access` theo Common. Không đưa service credential vào Web/demo; Bearer user không thay được xác thực service.
- Sau xác thực service vẫn phải kiểm tra user/quyền hiện hành; ID từ query không tự cấp quyền. Action lạ/thiếu hoặc school không xác minh được đều không cho phép.
- Không nuốt mọi exception để trả HTTP 200: lỗi validation/auth/hạ tầng dùng error contract tương ứng; consumer phải coi timeout/5xx/response không hợp lệ là từ chối thao tác nhạy cảm.
- Chốt cache/invalidation trước khi cache quyết định quyền; transfer/archive/revoke phải có hiệu lực theo hợp đồng, không dựa vào event trễ để tiếp tục cấp quyền.

### 2.3. Ranh giới import

- Social/Administration gọi `classroom.public`; không query membership/assignment repository.
- Service khác gọi REST có authentication và timeout; không đọc SQL Core.
- Public/internal checks dùng cùng policy để tránh hai kết quả khác nhau cho cùng actor/resource/action.

## 3. Tiêu chí nghiệm thu

- [ ] Thiếu/sai service credential/scope hoặc chỉ có user JWT bị chặn; action lạ, cross-school và DB timeout không cấp quyền.
- [ ] Kết thúc enrollment chặn participation/AI mới nhưng cho phép owner đọc kết quả lịch sử giới hạn; không cấp lịch sử của người khác.
- [ ] ARCHIVED chặn AI/hoạt động chung; source revoke vẫn bị Document chặn dù Core cho đọc lịch sử.
- [ ] Teacher assignment hiện hành và giới hạn PRIMARY/ASSISTING được consumer kiểm tra; Admin không mặc định được đọc chat.
- [ ] Contract tests so khớp Python và HTTP policy; snapshot/error schemas, timeout/fail-closed và import boundaries có kiểm chứng.
