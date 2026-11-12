# FRS-DOCUMENT — THƯ VIỆN TÀI LIỆU, VERSION, GRANT, NOTES

**Mã:** LUMI-FRS-DOC-001 · **Trạng thái:** **PROPOSED / DESIGN REVIEW REQUIRED**, chưa có backend Document theo TASK-017.

## 1. Mục tiêu và nguồn quy tắc

Service Document sở hữu tệp nguồn, phiên bản, chia sẻ theo lớp và ghi chú/bookmark gắn nguồn. Source of truth: B1–B7, G5, H3, H6, L6, O1, O2. Không đọc SQL Core; cần xác minh current action/class scope qua interface dịch vụ được phê duyệt. Không mô tả hay thiết kế pipeline AI.

## 2. FRS-D01 — Thư viện cá nhân

- **Actor:** Lecturer có tài khoản ACTIVE.
- **Điểm vào:** `/teacher/library` (UI đã có route, nhưng backend Document chưa khả dụng).
- **List:** tài liệu do bản thân sở hữu, tên, loại, version thành công hiện hành, trạng thái xử lý, lớp được chia sẻ; chỉ metadata được phép.
- **Create:** metadata tối thiểu, lựa chọn tệp. Server xác minh owner từ credential, không nhận owner_user_id từ form để phân quyền.
- **Edit/Delete:** chỉ owner nguồn; trước xóa nếu có nhiều class grants đang dùng phải hiển thị danh sách ảnh hưởng và xác nhận riêng.
- **Errors:** 401/403/404, duplicate nếu contract định nghĩa, validation upload, storage unavailable; không xóa từ UI trước khi backend xác nhận.
- **AC:** DOC-T01, DOC-T02.

## 3. FRS-D02 — Upload và xử lý phiên bản

- **Format được chốt:** PDF, PPTX, DOCX, TXT, Markdown.
- **Điều kiện trước upload:** owner source; loại file hợp lệ; size limit, MIME-sniffing và chống file zip-bomb **cần thiết kế/duyệt**, không dùng 10 MB TP-01 làm upload cap.
- **Luồng:** nhận blob → lưu bền vững → ghi version PENDING → worker xử lý → SUCCESS hoặc FAILED → chỉ SUCCESS đủ điều kiện hiển thị sử dụng.
- **Retry:** worker crash, timeout hoặc upload v2 fail không làm mất v1 thành công; báo lỗi có thể khắc phục, không lộ stack trace.
- **Visibility:** lớp dùng newest SUCCESS version trong phạm vi grant hiện hành; version FAILED không tự trở thành active.
- **AC:** DOC-T03–DOC-T05, QAS-10.

## 4. FRS-D03 — Chia sẻ tài liệu vào lớp

- **Actor:** PRIMARY/ASSISTING hiện hành của lớp, với tài liệu nguồn thuộc quyền hợp lệ.
- **Điều kiện:** lớp ACTIVE; actor vẫn có teaching assignment; document ownership hoặc quyền chia sẻ theo policy; không thể sửa/xóa nguồn người khác.
- **Tạo grant:** idempotent/unique theo class/document; audit ai chia sẻ và thời điểm. Có thể share một nguồn nhiều lớp.
- **Revoke:** tác động ngay tại lần kiểm tra quyền sau; không dùng permission snapshot hoặc cache stale để mở tài liệu.
- **Lỗi:** class archived; actor mất assignment; cross-school; grant đã thu hồi; storage failure.
- **AC:** DOC-T06–DOC-T08.

## 5. FRS-D04 — Xem/tải tài liệu

- **Student:** chỉ xem/tải khi membership/action hợp lệ **và** Document grant hiện hành.
- **Teacher:** không mặc định mở source của giáo viên khác vì cùng lớp; điều kiện share phải được xác minh đúng action.
- **Lần kiểm tra:** trước cung cấp URL/tệp/preview, xác minh cả class access lẫn grant; URL tải có thời hạn và chính sách thu hồi cần được quyết định trước production.
- **Không lấy metadata môn/khối làm bằng chứng quyền.**
- **AC:** DOC-T09, DOC-T10.

## 6. FRS-D05 — Notes và bookmarks cá nhân

- **Actor:** owner ghi chú/bookmark.
- **Chức năng:** thêm, xem, sửa, xóa ghi chú tự viết; bookmark vị trí trang/slide/mục nếu xác định được; tìm trong tài liệu cá nhân theo quyền.
- **Khi mất quyền nguồn:** giữ chữ tự viết; che nguyên văn quote và chặn mở nguồn/bản preview; không tái cấp grant qua bookmark.
- **Lớp archived:** owner vẫn có thể sửa notes/bookmark cá nhân nếu nguồn còn quyền (O2), không tạo hoạt động chung mới.
- **AC:** DOC-T11–DOC-T13.

## 7. Ma trận dữ liệu và quyền

| Tài nguyên | Đọc | Ghi/sửa | Xóa/thu hồi |
|---|---|---|---|
| Source document | Owner, authorized reader theo grant | Source owner | Source owner với confirm multi-class |
| DocumentVersion | Reader được phép với successful version | Source owner upload; worker process | Policy lifecycle cần chốt |
| ClassGrant | Thành viên/teacher được phép xem trạng thái | Assigned Lecturer theo rule | Assigned Lecturer theo rule |
| SourceBoundNote | Chủ sở hữu note | Chủ sở hữu note | Chủ sở hữu note |
| Bookmark | Chủ sở hữu bookmark | Chủ sở hữu bookmark | Chủ sở hữu bookmark |

## 8. Các quyết định cần phê duyệt trước code

- File/object storage, encryption at rest, malware scanning, quota và upload size.
- Metadata page/slide extraction, parser versions và tính chính xác vị trí bookmark.
- API upload multipart hay presigned URL, TTL download, revoke propagation.
- Worker queue, lock, retry/backoff, dead letter và retention file/version.
- Trạng thái tài liệu xóa khi vẫn đang share, model permission owner/granter sau chuyển lớp.

Các route trong TASK-017 chỉ là **endpoint tham khảo**, không phải approved contract. Xem LLD Future.