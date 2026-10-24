# Document events v1 — TASK-017

**Người dùng duyệt toàn bộ gói ngày 2026-10-23; producer Document và consumer Core.Notification đã qua kiểm thử tích hợp.** Owner review Document / Core.Notification / AI vẫn cần trong PR. Xem [DESIGN](DESIGN.md), [API_CONTRACT](API_CONTRACT.md). Không chọn broker mới và không sửa event hiện hành của Core.

## Envelope và publication

`{event_id:UUID,event_type,schema_version:1,occurred_at:UTC,school_id:UUID,aggregate_id:UUID,aggregate_revision:int,payload:{...}}`.

Không raw text/quote/filename/title/email/URL/token trong payload. Publication cùng transaction thay đổi trạng thái nghiệp vụ; at-least-once, event ID ổn định khi retry, consumer dedupe theo event ID + hash. Không dùng file version làm idempotency key của mọi thay đổi grant: share -> revoke -> share là ba revision khác nhau.

| Type | Aggregate | Payload |
|---|---|---|
| `document.version.ready.v1` | document UUID / document revision | `{document_id,owner_user_id,document_version,artifact_revision}` |
| `document.grant.changed.v1` | grant UUID / grant revision | `{document_id,owner_user_id,actor_user_id,class_id,grant_id,grant_revision,is_active,document_version:number|null}` |
| `document.source.deleted.v1` | document UUID / document revision | `{document_id,owner_user_id,actor_user_id}` |

READY phát sau artifact hoàn chỉnh; FAILED không phát READY. Revoke/xóa tăng revision và ghi event ngay trong transaction; access API từ chối ngay dù delivery đang retry. Một stale job hoặc stale event không thể phục hồi grant đã thu hồi. Worker commit trước rồi crash thì phát lại cùng ID, không tạo hai thay đổi nghiệp vụ.

## Core.Notification intake

Thêm **một** endpoint `POST /internal/v1/document-events`, không thuộc public proxy. Dùng `X-Service-Key` bằng cấu hình Core riêng `DOCUMENT_EVENTS_SERVICE_SECRET`, scope cố định `core:document_events`; không chấp nhận JWT làm service credential, không nhận arbitrary notification type hoặc recipient từ caller.

Request là envelope trên. Core kiểm tra schema/type/UUID/range, school/class/actor hợp lệ qua public interface Core; ghi receipt `{event_id,payload_hash}` cùng outbox Notification. Cùng event/hash trả receipt cũ, cùng ID khác payload trả 409. DB/validation lỗi không ack thành công. Delivery worker Document retry có backoff và trạng thái lỗi để vận hành, không nuốt exception.

Core chọn audience theo quyền lớp hiện hành. Khi version READY/source deleted tác động nhiều lớp, Document tạo từng event grant.changed có revision tăng phù hợp ở mỗi grant trong transaction, để Core không phải đọc SQL Document. Thông báo chứa IDs đủ điều hướng và nhãn tổng quát, không nội dung file; source reader vẫn kiểm tra lại Document grant. Delivery đến muộn/reorder không thể cho phép mở nguồn đã revoke. Không phát thông báo lặp cho cùng event.

Migration intake receipts và notification schema phải là revision mới của Core, có test public-interface boundary, duplicate/reorder/cross-school và DB outage. Owner TV4/TV2 review trước merge; tài liệu không thay thế review.

## TASK-018 boundary

Document có journal IDs/revisions để AI consumer sau này đọc bằng key scope `document:read_events` riêng; cursor ổn định, không retention/purge tự đặt. Không triển khai một AI receiver/vector store/provider chưa đặc tả. Consumer AI phải tự dedupe, xử lý tombstone/revision, lấy nội dung qua internal source API có actor+grant hiện hành và kiểm tra lại trước prompt/citation. Mất Core/Document thì fail closed. AI index không là nguồn sự thật và Document READY không có nghĩa đã index AI.

Trước khi triển khai TASK-018 cần chốt bootstrap index theo service identity, checkpoint, invalidation ACK và retry của AI; **không dùng internal source key để tự cấp impersonation một actor**. G3 Document có thể nghiệm thu lưu/trích xuất/đọc nguồn và event journal độc lập, chưa chứng nhận end-to-end RAG.
