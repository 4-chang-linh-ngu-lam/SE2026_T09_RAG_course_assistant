# TASK-017 — gói duyệt trước khi nối Document live

Trạng thái **người dùng đã duyệt toàn bộ gói để triển khai ngày 2026-10-23**. Trước task chưa có `services/document`, live adapter trả unavailable và upload UI chỉ truyền metadata; implementation mới đang được nghiệm thu. Không coi UI preview là bằng chứng backend.

Đề xuất triển khai được mô tả cụ thể tại:

- [Thiết kế và quyền](../../../docs/architect/microservices-v1/document/DESIGN.md).
- [27 public API, 3 internal API và DTO](../../../docs/architect/microservices-v1/document/API_CONTRACT.md).
- [Events v1 và một Core internal intake](../../../docs/architect/microservices-v1/document/EVENT_CONTRACT.md).
- [Ownership / cấu trúc](../../../docs/architect/microservices-v1/document/FOLDER_STRUCTURE.md).

Các lựa chọn đã duyệt cùng gói: Python/FastAPI + PostgreSQL schema/credential riêng + private file volume + worker DB lease; mặc định 50 MiB/file và giới hạn xử lý đã ghi; năm định dạng trích xuất text thật, không OCR; wire READY; thêm nguồn của mình/gỡ grant theo PRIMARY/ASSISTING; source revoke che quote nhưng giữ chữ tự viết; idempotency/revision chống mutation trùng; namespace Web `/api/document/v1` giữ nguyên 63 API Core; event IDs-only và service keys theo scope riêng. Không thêm Business Rule, không đổi quyền Admin và không triển khai hộ AI/TASK-018.

Sáu màn đã nối live: thư viện, chi tiết nguồn/phiên bản/chia sẻ, tài liệu lớp giáo viên, tài liệu lớp học sinh, reader, ghi chú/bookmark. Bytes multipart/tải file phải đi qua proxy có kiểm tra session, origin và giới hạn, không metadata-only upload; mất kết nối không báo thành công.

AGY chỉ chỉnh UI/CSS trong allowlist riêng, không đọc `.env`/credential, không viết API/quyền/backend. Backend/live-integration đã được phép triển khai theo câu trả lời “Duyệt toàn bộ gói để triển khai”. Document đã chuyển sang contract v1; chỉ nghiệm thu live khi kiểm thử thực tế đạt. Owner review PR vẫn áp dụng.

Bằng chứng ban đầu: `npm run check` thực chạy, exit 0, **338/338 tests**, trước thay đổi TASK-017. Những test này không chứng nhận Document backend chưa tồn tại.

Theo gói đã duyệt, Codex triển khai backend/proxy/adapter/controller, migration/deployment cô lập, kiểm thử 5 format, fallback/crash/revoke/O2/cross-scope/unknown writes, và browser live giáo viên/học sinh; owner Document/TV2/TV4/AI vẫn cần review PR theo trách nhiệm. Không commit/push hoặc reset dữ liệu môi trường đang dùng trong phạm vi task hiện tại.

Tiến độ và bằng chứng chạy thật cập nhật trong [báo cáo triển khai](DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md). Bản baseline338 test ở trên chỉ là lịch sử trước thay đổi.
