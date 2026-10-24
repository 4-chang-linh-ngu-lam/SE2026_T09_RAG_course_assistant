# Phạm vi duyệt kết nối Notifications — 22/10/2026

Trạng thái: **đã được người dùng duyệt ngày 22/10/2026** với lựa chọn “Duyệt Notifications theo đề xuất”. `apps/web/AGENTS.md` yêu cầu duyệt hợp đồng trước khi thêm operation ngoài Identity; quyết định này mở đúng ba operation bên dưới, thay trạng thái PROPOSED của riêng Notifications. Các module khác không được tự đổi trạng thái.

Owner: Core.Notification và Web transport/notification controller. Chỉ nối ba operation đã có, không thêm endpoint, quyền hoặc Business Rule:

| Operation | Request | Response thành công |
|---|---|---|
| GET `/api/v1/notifications` | Bearer; `cursor?`, `limit?` (1–100) | 200 `{items:[{id,type,payload_json,read,created_at}],unread_count,next_cursor}` |
| PATCH `/api/v1/notifications/{id}/read` | Bearer; UUID; không JSON body | 200 `{id,read:true}` |
| POST `/api/v1/notifications/read-all` | Bearer; không JSON body | 204 |

Backend lấy recipient từ actor DB hiện tại, không nhận `user_id` từ browser; tài khoản LOCKED/phiên đã thu hồi trả 401, ID không thuộc recipient trả 404. Header Cache-Control no-store; Origin/attestation/correlation giữ nguyên như proxy Identity. Không cấp quyền mở tài nguyên từ notification payload.

Web sẽ decode wire DTO riêng, map type thành nhãn/nội dung hệ thống, không render raw payload/HTML hoặc dùng URL từ payload. Type lạ dùng thông báo tổng quát và không tạo link suy đoán. Các link tới lớp chỉ dựng từ UUID hợp lệ và role hiện tại; quyền tài nguyên vẫn do backend kiểm tra. Vì các workspace lớp còn blocked-contract, ưu tiên không tạo link chưa hoạt động.

Trang notifications tải các trang cursor có chặn cursor/row lặp và hủy khi đổi actor. Mỗi lần tải có deadline chung 15 giây và tối đa 100 trang; nếu chưa đủ dữ liệu thì báo lỗi, không công bố một trang dở dang như toàn inbox. `unread_count` là số toàn inbox do Core trả ở trang mới nhất; chỉ snapshot mới cập nhật số này, không thay bằng số unread của trang đầu. Các GET phân trang không phải snapshot transaction duy nhất, nên thay đổi đồng thời từ thiết bị khác có thể cần refresh. Mark-one/all chỉ đổi trạng thái sau xác nhận; mutation unknown cần GET mới để đối soát, không tự replay hoặc tô thành công. Không thêm dữ liệu preview vào live.

Compose bổ sung tiến trình worker có sẵn `python -m app.modules.notification.worker`, dùng cùng Core image/database, đợi migration và không mở cổng/nhận JWT/service secret. Không sửa lịch retry, audience hoặc cơ chế dedup.

Chốt phạm vi này chỉ mở Notifications. Classroom/Social/Calendar/Administration và các service khác tiếp tục pending theo hợp đồng hiện tại; các khoảng trống khác trong [API matrix](CORE_API_MATRIX_2026-10-22.md) không được tự xem là đã duyệt. Không thay Business Rules, schema DB hoặc migration.

Acceptance: unit/contract tests cho decode, cursor/unread count, actor change, 401/404/422, malformed response, lost mutation response; live build/release scan; HTTP PostgreSQL/Core/Web fixture riêng cho inbox/ownership/mark/reconcile và worker delivery. UI/browser certification báo riêng theo công cụ thực tế có sẵn.
