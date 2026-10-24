# TASK-017 — Document backend và Web live

Gói thiết kế/API được người dùng duyệt ngày 2026-10-23; chốt triển khai và bằng chứng ngày 2026-10-24. Backend độc lập tại `services/document`; sáu workspace Web dùng dữ liệu thật, không fallback fixture. [Hướng dẫn chạy và trải nghiệm](../../../services/document/README.md), [API](../../../docs/architect/microservices-v1/document/API_CONTRACT.md), [thiết kế/quyền](../../../docs/architect/microservices-v1/document/DESIGN.md), [events](../../../docs/architect/microservices-v1/document/EVENT_CONTRACT.md).

## Phạm vi đã triển khai

| Phần | Hành vi |
|---|---|
| Lưu trữ và phiên bản | Bytes multipart thật, SHA-256, tệp bất biến trên volume riêng, receipt chống trùng, processing worker lease/generation; v2 lỗi giữ v1 phục vụ |
| Phân quyền | Actor ACTIVE từ Core; current class access mỗi request; PRIMARY/ASSISTING thêm nguồn của mình/gỡ grant; chỉ owner đổi/xóa nguồn; Admin không tự đọc thư viện khác |
| Reader | Text trích xuất PDF/PPTX/DOCX/TXT/MD, nhãn Trang/Slide/Mục đúng format, chọn phiên bản/vị trí, tải bản gốc có xác thực |
| Ghi chú/bookmark | Owner-only; quote phải thuộc locator/version; mất quyền che quote tại backend và giữ chữ tự viết; snapshot tên nguồn/lớp giữ lịch sử, không lộ tên nguồn mới sau revoke |
| Thông báo | Transactional Document outbox → Core internal intake với key riêng → Core.Notification; UUID/hash dedupe, current audience check; payload chỉ IDs/revisions |
| Đồng bộ Web | Chung session/refresh với Core, namespace/allowlist Document riêng, runtime decoders, hủy stale actor/resource reads, foreground/focus/online refresh, unknown writes không tự replay |
| Deploy cục bộ | Core migration0013 và bảo vệ downgrade dữ liệu receipt; Document migrations0001–0003; bootstrap login/schema riêng; non-root API/worker; script giữ dữ liệu Core/SMTP và tạo cấu hình riêng không đưa Git |

## Sáu route

| Route | Trạng thái tích hợp |
|---|---|
| `/teacher/library` | Live library/filter/bytes upload/receipt/processing/retry |
| `/teacher/library/:documentId` | Live metadata, version history/upload/retry/download, batch grants/revoke, revision/count-confirmed deletion |
| `/teacher/classes/:classId/documents` | Live current class grants, source preview, revoke theo quyền hiện hành |
| `/student/classes/:classId/documents` | Live permitted sources, serving version và explicit bookmarks |
| `/student/classes/:classId/documents/:documentId` | Live extracted reader, quotes/notes/bookmarks/download, revoke clears displayed source |
| `/student/notes` | Live own notes/bookmarks, current source redaction và historical labels |

AGY `gemini-3.8-flash-high` tạo CSS và presentation components theo allowlist trong worktree riêng: library/reader/source preview/source management, controlled metadata form, quote composer và sửa responsive sổ tay 320px. Codex review rồi tích hợp, giữ toàn bộ backend/API/session/quyền/controllers/test. Không gửi `.env`, credential, dữ liệu thật hoặc quyền acceptance cho AGY. Skill: [lumi-frontend-orchestrator](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md).

## Bằng chứng đã chạy

| Lệnh / môi trường | Kết quả |
|---|---|
| `python services/document/scripts/test-service.py --full-core` | 25 Document + 428 Core tests đạt trên PostgreSQL16 cô lập; migration upgrade/check không drift, role không có quyền schema Core |
| `npm run check` tại `apps/web` | Boundaries, TypeScript và 346 tests đạt |
| `npm run build` với live `.env.local` | Production build và release scan đạt; không có fixture marker |
| `CORE_DOCUMENT_TEST=1 npm run test:core` | 6 nhóm HTTP Document đạt; Core 46 operations/7 nhóm, Notifications 7 nhóm, Identity/security 8 nhóm và DB outage/recovery đã đạt trong lượt integration |
| Chrome production | Core 7 + Document 6 nhóm đã đạt trên production fixture, không có uncaught JS exception. Đã kiểm tra thêm đối soát ngay trong dialog khi mất phản hồi sửa ghi chú, link lịch sử đúng version và sổ tay 320px không tràn |

Document tests gồm 5 định dạng thật, tải bytes gốc, malformed/ZIP traversal/DTD, hạn mức, idempotency/hash mismatch, cross-school/class/owner/Admin, ASSISTING, archiveO2, quote/locator validation, revoke/private history, xóa nguồn khi processing, worker child chết sau claim, reclaim/stale generation/out-of-order publication, internal scope/current serving version và outbox receipt. Lượt regression đầu có 100 tests Identity/Notification; lượt mở rộng cuối chạy toàn bộ 428 Core tests với warnings-as-errors. Lượt mở rộng phát hiện danh mục bảo vệ downgrade chưa có receipt mới: đã đăng ký revision 0013, bổ sung test chặn downgrade khi có receipt và chạy lại toàn bộ thành công. Không sửa migration đã áp dụng.

HTTP/browser fixtures có tài khoản, tệp, schema, PostgreSQL volume, SMTP TLS sink và Chrome profile tổng hợp riêng. Không gửi Gmail thật, không dùng account/DB đang hoạt động. Runner dọn đúng containers/volume/credential/TLS/profile của nó; private screenshots/logs ở TEMP không đưa Git. Xem [aggregate bằng chứng](evidence/document-service-2026-10-23.json): chỉ số liệu/trạng thái, không credential/ID người dùng/tệp thực.

Các trạng thái Git/runtime dưới đây và trong aggregate là ảnh chụp tại thời điểm nghiệm thu trước khi đóng gói commit. Việc xuất bản nhánh sau đó không thay đổi kết quả kiểm thử đã ghi.

## Giới hạn nghiệm thu

AI index/retrieval/tutor thuộc TASK-018; READY chỉ chứng nhận Document trích xuất. Chưa OCR; PDF scan/mã hóa/không có text báo FAILED rõ. Chưa chứng nhận KPI tải, QAS-04/QAS-10 toàn hệ thống, HA, mọi tệp 50 MiB hoặc owner sign-off. Không tự đặt retention/purge pháp lý. Owner Document, Core.Classroom/TV2, Core.Notification/shared deployment/TV4 và AI cần review khi tạo PR. Không commit/push trong task này.

Kiểm tra lint/format: Ruff đạt trên 172 file Python của Core +Document. Hai fixture cố ý tạo datetime không timezone vẫn giữ input naive qua `replace(tzinfo=None)` để kiểm tra rejection, đồng thời đáp ứng lint. `git diff --check` không có lỗi whitespace.

## Trạng thái cục bộ sau nghiệm thu

Web `http://localhost:3000/login`, Core 8000 và Document 8200 đã chạy lại; cả ba health/page checks trả200. Runtime Document thực có 27 public + 3 internal operations, UID 10002. Core ở 0013, Document ở document_0003; Alembic check không drift. Environment riêng vẫn bị Git bỏ qua. Không seed tài khoản/tệp vào DB đang dùng, không thay mật khẩu hoặc SMTP, không commit/push. Worktree AGY và các fixture containers/volume/profile đã dọn đúng phạm vi.

Tổng kết chức năng: 28 nhóm HTTP và 13 nhóm thao tác Chrome đạt. Đã xem ảnh Reader desktop/mobile, source v2 lỗi còn v1, sổ tay đã revoke tại 320px và dialog đối soát sửa ghi chú. Đây là các màn/luồng được chọn, không phải chứng nhận mọi canvas hay tải production. Owner review và giới hạn ở trên vẫn giữ nguyên.
