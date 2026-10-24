# Document Service — TASK-017 / G3

**Trạng thái: người dùng đã duyệt toàn bộ gói thiết kế/API để triển khai ngày 2026-10-23; backend/Web live đã triển khai; bằng chứng chức năng được ghi trong báo cáo TASK-017.** Owner review trong PR vẫn bắt buộc, chưa giả danh review của TV2/TV4/AI.

Nguồn chuẩn: [Business Rules](../../BUSINESS_RULES.md) B1–B7, G5, H3, H6, L6, O1, O2; [ADR-001](../ADR-001.md); [TASK-017](../../../../tasks/TASK-017-document-service-design-impl.md). Tài liệu này cụ thể hóa bản nháp theo gói người dùng đã duyệt; không đổi Business Rules. Không coi Core G2, owner review, chỉ tiêu tải hoặc AI indexing là đã nghiệm thu chỉ vì tài liệu tồn tại.

## 1. Ownership và triển khai

- Document sở hữu thư viện cá nhân, file gốc, phiên bản, nội dung đã trích xuất, grant lớp, ghi chú và bookmark. AI sở hữu index dẫn xuất, retrieval và tutor ở TASK-018; Document không giả lập kết quả AI.
- Một process API FastAPI và một process worker Python 3.12, SQLAlchemy/Alembic; image riêng. Tái sử dụng cùng hệ PostgreSQL với Core nhưng schema `document`, tài khoản DB riêng, bảng migration riêng. Không SQL, FK hoặc import Python vào Core/service khác. Runtime role không superuser/createdb/createrole/bypassrls, không quyền vào schema Core.
- File trên volume riêng, đường dẫn do server sinh UUID; file không public, không nhận URL từ client. Mọi lần tải/xem qua API có kiểm tra quyền. Giữ file gốc bất biến và SHA-256 do server tính. Không đưa file, nội dung, email hay credential vào event/log.
- Job bền vững trong PostgreSQL, worker claim bằng `FOR UPDATE SKIP LOCKED`, lease theo đồng hồ DB và generation token. Worker chết thì job được claim lại; không cần thêm broker. API, worker và migration có lifecycle riêng.
- Cấu hình mẫu chỉ có placeholder. Credential thật nhập ở môi trường cục bộ, không Git, không trình duyệt, không gửi AGY. Thêm Compose profile riêng, không reset DB Core hoặc thay tài khoản người dùng hiện có.

## 2. Upload và xử lý

Mặc định **50 MiB/file**, cấu hình từ server và trả về `/capabilities`; 10 MB của TP-01 vẫn chỉ là tải mẫu. Chấp nhận PDF/PPTX/DOCX/TXT/MD; kiểm tra đuôi, chữ ký/nội dung thực và cấu trúc, không tin MIME từ browser. File rỗng, tên sai, quá hạn mức trả lỗi trước khi enqueue.

Upload là multipart có **bytes gốc**, không phải JSON chứa tên/kích thước. API stream vào file staging có giới hạn, hash, fsync rồi atomic rename; transaction chỉ tham chiếu file hoàn chỉnh. Crash có thể để file staging/orphan nhưng không công bố nguồn dở; không tự thêm chính sách xóa theo thời hạn pháp lý. Không ghi đè bản gốc khi retry.

Trích xuất thực: `pypdf` cho PDF; ZIP + XML parser chặn DTD/entity cho DOCX/PPTX; UTF-8 có/không BOM cho TXT/MD. MD trả text, không render HTML từ file. Không OCR ở G3 này; PDF mã hóa/không có text trích được trả FAILED kèm thông báo rõ. Định dạng không hợp lệ không được gắn READY.

Giới hạn kỹ thuật: ZIP giải nén tối đa 128 MiB, 2.000 entries; tổng text tối đa 8 MiB, 5.000 locator; mỗi lần xử lý tối đa 90 giây, bộ nhớ worker con tối đa 512 MiB. Không giải nén đường dẫn do ZIP cung cấp ra filesystem, không truy cập external relationship/network. Vượt giới hạn trả lỗi xử lý, giữ file gốc và bản phục vụ trước. Không tuyên bố xử lý được mọi PDF 50 MiB trong giới hạn này.

Locator là **trang PDF, slide PPTX, mục văn bản DOCX/TXT/MD**, không bịa số trang vật lý Word/Markdown. Reader hiển thị text thật đã trích xuất và nhãn locator đúng loại; tải bản gốc qua nút riêng.

`PENDING -> PROCESSING -> READY | FAILED`. `READY` là tên wire thống nhất (bản task cũ viết `SUCCESS`). Chỉ đổi `serving_version` trong transaction sau khi artifact hoàn chỉnh đã lưu bền vững. Chọn phiên bản READY có số lớn nhất, kể cả job hoàn thành không theo thứ tự. v2 FAILED/đang xử lý không thay v1 READY. Retry chỉ owner, chỉ FAILED hoặc lease đã hết, generation cũ không được publish. Xóa nguồn hoặc revoke grant luôn thắng mọi fallback.

## 3. Xác thực và quyền hiện hành

Mỗi request người dùng xác minh bearer bằng Core `GET /api/v1/users/me`, không chia sẻ JWT signing secret. Actor lấy từ Core, không lấy user ID/role/school ở request body. Core không trả identity hợp lệ hoặc không truy cập được thì fail closed; outage là 503, không biến thành quyền được cấp hoặc mock success.

Quyền lớp dùng Core `GET /internal/v1/classes/{class_id}/access`, key hiện có với scope cố định `core:check_access`. Document kiểm tra đầy đủ user/class/action/school trong response; không cache allow xuyên request. Đây là HTTP service-to-service, không phải proxy browser và không SQL Core.

| Thao tác | Điều kiện tại backend Document |
|---|---|
| Thư viện riêng, upload, sửa metadata, phiên bản, retry, xóa nguồn | Actor ACTIVE có LECTURER, cùng trường và sở hữu nguồn |
| Thêm nguồn vào lớp | Nguồn của chính actor, lớp ACTIVE, `participate_current_class` allowed và teaching role PRIMARY/ASSISTING, cùng trường |
| Gỡ grant khỏi lớp | PRIMARY/ASSISTING đang phụ trách lớp ACTIVE; không cần sở hữu file gốc |
| Xem/tải nguồn trong lớp | `read_document_source` allowed, cùng trường, grant Document còn active, nguồn chưa xóa và phiên bản READY |
| Ghi chú/bookmark mới hoặc sửa | Chính owner ghi chú/bookmark, quyền đọc nguồn còn hiệu lực; ARCHIVED vẫn được theo O2 |
| Đọc lịch sử ghi chú/bookmark | Chính owner; chữ tự viết giữ lại, quote/open-source chỉ hiện sau kiểm tra quyền hiện hành |
| Xóa ghi chú/bookmark của mình | Chính owner; không cần cấp lại quyền nguồn đã mất |

Admin không tự được quyền đọc thư viện người khác. Metadata môn/khối không cấp quyền. Grant của một lớp không tự cho phép tái chia sẻ file người khác sang lớp khác; PRIMARY/ASSISTING có thể upload nguồn của mình và gỡ nguồn đang dùng trong lớp theo B2/O1. Cách hiểu này nằm trong gói đã được người dùng duyệt; owner review vẫn cần trong PR.

Archive không cho upload/share/revoke trong lớp, vẫn cho đọc nguồn và sửa ghi chú/bookmark còn quyền. Chuyển lớp/kết thúc assignment/khóa actor làm mất quyền nguồn ở request kế tiếp. Không thể thu hồi bytes đã được người dùng tải trước đó; không tạo URL tải công khai sống lâu sau revoke.

Backend không trả raw quote trong DTO nếu grant/current access đã mất. Khi Core kiểm tra nguồn tạm lỗi, có thể đọc chữ tự viết thuộc owner nhưng quote bị che, `source_access=UNAVAILABLE`; không diễn giải outage thành nguồn đã bị thu hồi vĩnh viễn. Không cho tạo/sửa source-bound nội dung trong trạng thái đó.

## 4. Dữ liệu và đồng thời

- `documents`: UUID, school ID/owner ID opaque, title/description, revision, serving version, soft-deleted flag, timestamps. Không FK Core.
- `document_versions`: document FK nội bộ, version number unique/document, filename đã chuẩn hóa, format, byte size/hash, storage key riêng, status/error code, generation/lease, immutable extracted artifact metadata.
- `class_document_grants`: UUID, document FK, class ID/school ID opaque, active, revision, granted-by ID; unique document/class. Check lớp trước commit và trước mọi lần dùng nguồn. Quyền Core và transaction Document không phải distributed transaction; không giữ quyền allow đã cache để dùng cho request sau.
- `source_notes`: owner ID, document/version FK nội bộ, class ID, locator ID, chữ tự viết, quote đã kiểm tra nằm trong nội dung locator. ID nguồn không cho người khác dò ghi chú. Note/bookmark lưu snapshot tên nguồn và tên lớp tại thời điểm tạo; khi mất quyền không đọc tên nguồn mới vào lịch sử cá nhân. Class name lấy qua Core public API, không truy cập bảng Core.
- `bookmarks`: owner/document/version/class/locator, unique trên phạm vi đó; đặt trạng thái tường minh, không toggle mù khi retry.
- `upload_receipts`: idempotency UUID + actor + operation + payload hash + kết quả document/version; cùng key khác payload trả 409. Không lưu token. Upload mới/phiên bản được đối soát bằng receipt, không tự gửi lặp sau timeout.
- `outbox`: event ID/aggregate/revision/type/payload IDs/status/attempt/lease. Event chỉ được ghi cùng transaction đổi trạng thái nghiệp vụ.

Share nhiều lớp là một mutation atomic: kiểm tra tất cả lớp rồi ghi cả batch hoặc không lớp nào, không báo thành công một phần. Sửa metadata/xóa/revoke dùng `expected_revision`; stale snapshot trả 409. Xóa nguồn đang chia sẻ trả số lớp/revision để UI cảnh báo, chỉ thực thi với xác nhận rõ; nếu grant thay đổi phải xác nhận lại snapshot mới.

Khi mất phản hồi mutation: UI giữ trạng thái chưa xác định, giữ idempotency key và chọn lại file nếu browser đã mất File object; không mở lại nút tạo bản mới chỉ vì GET chưa thấy dữ liệu. Reader thay actor/lớp/phiên bản thì hủy request và không đưa dữ liệu cũ vào scope mới.

## 5. Sự kiện và ranh giới TASK-012/018

Xem [EVENT_CONTRACT](EVENT_CONTRACT.md). Document ghi event bền vững, cấp quyền nguồn hiện hành ở internal API cho AI sau này. **Chưa có AI service/index nên READY chỉ chứng nhận trích xuất Document, không chứng nhận RAG đã index.** Không tạo endpoint hay implementation cho AI thay owner TASK-018.

Đề xuất một Core internal intake riêng để nhận thông báo chia sẻ/thu hồi/có phiên bản mới. Đây là thay đổi Core.Notification cần duyệt cùng hợp đồng: key `DOCUMENT_EVENTS_SERVICE_SECRET` riêng, scope `core:document_events`, receipt chống trùng và kiểm tra class/school/actor qua public interface trong Core. Không đưa service key lên Web và không cho key này dùng route `check_access` thay key hiện hành.

## 6. Web và phạm vi nghiệm thu

Giữ 63 API Core hiện có; thêm proxy allowlist Document riêng `/api/document/v1` -> Document `/api/v1`, không mở wildcard. Proxy chuyển bytes multipart có giới hạn, không dùng `request.text()`; Bearer vẫn thuộc session hiện có, refresh cookie HttpOnly vẫn chỉ do Core quản lý. Kiểm tra same-origin, listener attestation và actor/session race như Core, không forward cookie hay service key sang Document.

Nối sáu màn: thư viện giáo viên, chi tiết nguồn/phiên bản/grant, tài liệu lớp giáo viên, tài liệu lớp học sinh, reader, ghi chú/bookmark cá nhân. `integrations.document` hiện contracted và sáu workspace dùng live Document adapter. AI/tutor vẫn pending-contract riêng; không có fallback fixture khi Document lỗi.

Nghiệm thu bằng DB/storage/container cô lập, không gửi Gmail thật hay ghi dữ liệu test vào lớp/tài khoản đang sử dụng: 5 định dạng thật; bytes/hash/tải; malformed/ZIP bomb/path traversal; fallback v2 lỗi; worker crash/reclaim/stale generation; cross-school/class/owner; PRIMARY/ASSISTING; revoke khi đang đọc; archive O2; che quote và giữ chữ tự viết; unknown upload/idempotency; outbox replay; Core outage fail closed; browser giáo viên/học sinh và 1440/390 px. Chạy build live và kiểm thử thực tế, không nhận kết quả AGY là bằng chứng nghiệm thu.

## 7. Các quyết định người dùng đã duyệt trong gói này

1. Stack/schema/storage/job queue và các hạn mức ở mục 1–2.
2. Ma trận quyền, cách thêm nguồn của mình/gỡ grant và giới hạn archive ở mục 3.
3. API v1, idempotency/revision, wire READY và namespace Web riêng.
4. Event v1, intake Core.Notification cùng credential/scope mới; TASK-018 vẫn sở hữu index/AI.

Owner review cần có khi làm PR: Document, Core.Classroom (TV2), Core.Notification/shared deployment (TV4) và AI/TASK-018. Tài liệu này không giả danh chữ ký duyệt của các owner.

Tham khảo kỹ thuật: [FastAPI UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/), [pypdf text extraction và giới hạn](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [PostgreSQL roles](https://www.postgresql.org/docs/16/sql-createrole.html).
