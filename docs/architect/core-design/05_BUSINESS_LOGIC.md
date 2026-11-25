# Nghiệp vụ — CORE-T05/T08 sau CORE-CR01/02

Giữ transaction IDs để traceability; actor/action theo Business Rules:

- T1: Admin/Identity provisioning và audit qua public interface; public /auth/register tiếp tục BLOCKED — LEGACY.
- T2: Admin tạo SubjectClass cùng PRIMARY/ASSISTING assignment trong một transaction.
- T3: Admin preview/confirm AUTO hoặc mutation MANUAL, version guard, giữ membership history; không join code/invitation self-join.
- T4: Admin thay teaching assignment theo H1/H2; PRIMARY không bỏ trống, thay người dạy trước khi assignment cũ kết thúc; không class owner transfer.
- T5: membership removal + outbox atomic; Core current authorization chặn hoạt động lớp mới.
- T6: Social mutation + event/outbox trong cùng transaction; không HTTP trong transaction.
- T7: Identity refresh rotation/reuse detection giữ implementation hiện tại.
- T8: account deletion phân tán chỉ hoàn tất sau per-target service cleanup; retention/owner/completion policy vẫn pending.

Class status hiện hành ACTIVE/ARCHIVED; archived read-only, Admin restore. Không thêm hard-delete class state hoặc retention behavior khi Business Rules chưa duyệt. C-AC01 register-valid conflict với API Contract riêng biệt; CORE-CR01/02 không tự sửa nó.
