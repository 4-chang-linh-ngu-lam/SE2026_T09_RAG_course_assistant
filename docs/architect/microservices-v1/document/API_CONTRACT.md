# Document API v1 — TASK-017

**Người dùng đã duyệt toàn bộ gói ngày 2026-10-23; backend và Web live đã triển khai, kiểm thử thực tế ghi trong báo cáo TASK-017.** Đi cùng [DESIGN](DESIGN.md) và [EVENT_CONTRACT](EVENT_CONTRACT.md). Không thay contract của 63 API public Core; intake Document mới chỉ là internal.

Public upstream `/api/v1`, Web `/api/document/v1`. Bearer Core bắt buộc mọi operation bên dưới. Browser không được gọi `/internal/*`. UUID theo canonical string, timestamps UTC ISO-8601. Không user/role/school ID do client cấp làm căn cứ quyền.

## Quy ước

JSON envelope `{data: T, meta?: {next_cursor: string|null}}`, lỗi `{error:{code,message,details?},correlation_id}`; không stack trace, storage path, token hoặc raw nội dung file trong lỗi. `Cache-Control: no-store`. 401 session không hợp lệ; 403 quyền nguồn/lớp đã bị thu hồi; 404 không tồn tại/không thuộc thư viện owner; 409 revision/state/idempotency conflict; 413 vượt bytes; 422 input/file không hợp lệ; 503 Core/storage/DB chưa sẵn sàng. Response lỗi không chứng nhận mutation chưa commit; unknown phải đối soát.

Collection có `limit` mặc định 20, tối đa 100, cursor opaque; không coi trang đầu là toàn bộ. Sort ổn định timestamp + UUID. Optional filters được liệt kê riêng, filter lạ trả 422. Không gửi secret/query token; tên/từ khóa không ghi log.

`Idempotency-Key: UUID` bắt buộc khi upload tài liệu/phiên bản. Identity actor + operation + key + server payload hash tạo receipt bền vững trong transaction nghiệp vụ. Lặp cùng key/payload trả cùng document/version, không tạo job/phiên bản mới; khác payload 409. Key không cấp quyền, vẫn kiểm tra session/owner. Không tự hết hạn receipt ở G3 khi chưa có retention được duyệt.

## Public operations (27)

| # | Method / path | Request | Response data / quyền |
|---|---|---|---|
| 1 | GET `/capabilities` | — | `Capabilities`, actor ACTIVE |
| 2 | GET `/documents` | cursor, limit, search tối đa 200 ký tự, format, status | `DocumentSummary[]`, thư viện owner LECTURER |
| 3 | POST `/documents` | multipart `file`, `title` 1–200, `description` tối đa 4.000; Idempotency-Key | 201 `UploadReceipt`, owner LECTURER; bytes thật |
| 4 | GET `/documents/{document_id}` | — | `OwnedDocument`, owner |
| 5 | PATCH `/documents/{document_id}` | `{title,description,expected_revision}` | `OwnedDocument`, owner |
| 6 | DELETE `/documents/{document_id}` | JSON `{expected_revision,confirmed_shared_class_count}` | `MutationReceipt`, owner; xác nhận đúng snapshot grant hiện hành |
| 7 | GET `/documents/{document_id}/versions` | cursor, limit | `DocumentVersion[]`, owner |
| 8 | POST `/documents/{document_id}/versions` | multipart `file`, Idempotency-Key | 201 `UploadReceipt`, owner; giữ cùng format nguồn |
| 9 | POST `/documents/{document_id}/versions/{version}/retry` | `{expected_generation}` | 202 `DocumentVersion`, owner; không tạo version mới |
| 10 | GET `/documents/{document_id}/versions/{version}/content` | cursor, limit locators | `ContentPage`, owner, READY |
| 11 | GET `/documents/{document_id}/versions/{version}/file` | — | bytes gốc, owner, READY; attachment + no-store |
| 12 | GET `/documents/{document_id}/grants` | cursor, limit | `Grant[]`, owner; không suy quyền từ metadata lớp |
| 13 | POST `/documents/{document_id}/grants` | `{class_ids:UUID[1..50],expected_revision}` | `Grant[]`, atomic toàn batch, owner + PRIMARY/ASSISTING hiện hành từng lớp ACTIVE |
| 14 | GET `/classes/{class_id}/documents` | cursor, limit, search, format | `ClassDocument[]`, current source read |
| 15 | GET `/classes/{class_id}/documents/{document_id}` | — | `ClassDocument`, current source read + grant active |
| 16 | PUT `/classes/{class_id}/documents/{document_id}/grant` | `{expected_revision}` | `Grant`, thêm nguồn của mình, PRIMARY/ASSISTING lớp ACTIVE |
| 17 | DELETE `/classes/{class_id}/documents/{document_id}/grant` | `{expected_revision}` | `Grant` active=false, PRIMARY/ASSISTING lớp ACTIVE, không cần owner file |
| 18 | GET `/classes/{class_id}/documents/{document_id}/versions/{version}/content` | cursor, limit locators | `ContentPage`, current source read + active grant + version READY |
| 19 | GET `/classes/{class_id}/documents/{document_id}/versions/{version}/file` | — | bytes gốc, kiểm tra quyền như #18, attachment + no-store |
| 20 | GET `/notes` | cursor, limit, class_id?, document_id? | `Note[]`, chính owner; che quote/open-source theo quyền hiện tại |
| 21 | POST `/classes/{class_id}/documents/{document_id}/notes` | `{version,locator_id,note_text:1..10000,source_quote?:0..2000,client_request_id:UUID}` | 201 `Note`, chính owner + còn quyền nguồn; client_request_id chống tạo trùng khi đối soát |
| 22 | PATCH `/notes/{note_id}` | `{note_text,expected_revision}` | `Note`, owner + nguồn còn quyền, kể cả ARCHIVED |
| 23 | DELETE `/notes/{note_id}` | `{expected_revision}` | `MutationReceipt`, owner, kể cả đã mất quyền nguồn |
| 24 | GET `/bookmarks` | cursor, limit, class_id?, document_id? | `Bookmark[]`, chính owner; source access theo quyền hiện tại |
| 25 | PUT `/classes/{class_id}/documents/{document_id}/bookmarks/{version}/{locator_id}` | `{bookmarked:boolean}` | `{bookmarked,bookmark:Bookmark|null}`, đặt trạng thái; thêm cần quyền nguồn, gỡ chỉ owner |
| 26 | DELETE `/bookmarks/{bookmark_id}` | — | `MutationReceipt`, chỉ owner, idempotent trong phạm vi owner |
| 27 | GET `/uploads/{request_id}` | — | `UploadReceipt`, chỉ actor đã upload; 404 **không chứng minh** request đang bay đã thất bại |

`version` là integer >0, `locator_id` ID do server tạo từ artifact; không chấp nhận file path hay tùy ý offset từ client. PUT/DELETE grant lặp đúng trạng thái trả snapshot hiện tại, không tạo event trùng; revision stale thay đổi trạng thái trả 409. Khi xử lý file chưa READY, content/file trả 409 với status, không tự trả nội dung trống.

## DTO

Các object cấm field lạ ở request; response được decode có kiểm tra runtime ở Web. Không trả storage key, payload hash hay thông tin worker cho người dùng lớp.

- `Capabilities`: `{max_file_size_bytes:52428800,allowed_formats:[PDF,PPTX,DOCX,TXT,MD],allowed_extensions:[.pdf,.pptx,.docx,.txt,.md],allowed_mime_types:string[],reader_mode:'extracted_text',supports_ocr:false,assigned_classes:[{id,name,status:ACTIVE|ARCHIVED,teaching_role:PRIMARY|ASSISTING}]}`. Hạn mức phản ánh config server thật, không hard-code policy trong UI.
- `DocumentSummary`: `{id,title,description,format,owner_id,owner_name,latest_version:number,latest_status:PENDING|PROCESSING|READY|FAILED,serving_version:number|null,shared_class_count,revision,created_at,updated_at,can_manage_source:boolean}`. Danh sách owner mới có processing error của latest version.
- `OwnedDocument`: summary + `{versions:DocumentVersion[],grant_revision:number}`. Versions trong detail tối đa 20 và cờ/next cursor nếu còn; UI lấy tiếp qua #7, không kết luận version vắng khi chưa lấy đủ.
- `DocumentVersion`: `{version_number,filename,file_size_bytes,uploaded_at,status,error_code:string|null,error_message:string|null,is_serving,locator_count:number|null,locator_kind:PAGE|SLIDE|SECTION|null,generation:number}`. Error message đã biên tập, không exception/parser trace.
- `ClassDocument`: `{id,class_id,title,description,format,owner_id,owner_name,serving_version:number|null,latest_status,created_at,updated_at,grant_id,grant_revision,class_status:ACTIVE|ARCHIVED,can_manage_source,can_revoke_grant,locator_count:number|null,locator_kind:PAGE|SLIDE|SECTION|null}`. Không leak file phiên bản lỗi hay grant lớp khác cho học sinh.
- `Grant`: `{id,document_id,class_id,school_id,is_active,revision,granted_by,granted_at,updated_at}`. Web lấy tên/mã lớp từ Core theo quyền sẵn có; không cần Document truy vấn bảng Core.
- `ContentPage`: `{document_id,version,format,locator_kind,total_locators,locators:Locator[],next_cursor:string|null}`; `Locator`: `{id,number,title,text}`. Text thuần, không HTML. `ContentPage` lớp không được dùng lại nếu chuyển actor/class hoặc grant đã bị revoke.
- `Note`: `{id,document_id,document_title,document_format,version,class_id,class_name,locator_id,locator_label,note_text,source_quote:string|null,source_access:ALLOWED|REVOKED|UNAVAILABLE,client_request_id,revision,updated_at}`. Quyền kiểm tra khi response; không gửi quote gốc kèm cờ để frontend tự che. Khi tạo note/bookmark, lưu snapshot tên tài liệu và tên lớp từ Core public API có Bearer. Mất quyền dùng tên tài liệu lịch sử, không lộ tên mới sau revoke; không có Core FK/SQL. Migration `document_0003` backfill tên nguồn hiện có và class UUID cho dữ liệu trước snapshot vì không thể dựng lại nhãn lịch sử.
- `Bookmark`: `{id,document_id,document_title,document_format,version,class_id,class_name,locator_id,locator_label,source_access,created_at}`.
- `UploadReceipt`: `{request_id,document_id,version_number,status,created_at}`. Upload thành công nghĩa đã lưu file/job, không đồng nghĩa READY. Receipt riêng của actor vẫn đọc được sau soft-delete, không khôi phục quyền nguồn.
- `MutationReceipt`: `{id,revision:number|null,deleted:boolean}`. 204 không body được dùng cho bookmark không tồn tại thuộc scope actor; không phân biệt bookmark ID thuộc người khác với ID không tồn tại.

## Internal operations và credential

Các operation này không xuất hiện trong allowlist Web. Key riêng `DOCUMENT_INTERNAL_SERVICE_SECRET`, scope cố định `document:read_sources`, constant-time compare, **khác Core JWT secret/check_access/event key**. Key chỉ nhận diện service, vẫn phải có Bearer actor Core và đầy đủ current permission cho dữ liệu nguồn.

| Method/path | Request/response | Quyền |
|---|---|---|
| GET `/internal/v1/classes/{class_id}/documents/active-grants` | paginated `{document_id,serving_version,grant_id,grant_revision}` | service key + Bearer; Core source read và use_ai_tutor khi purpose=tutor; chỉ grant active, không thông tin thư viện riêng |
| GET `/internal/v1/classes/{class_id}/documents/{document_id}/versions/{version}/content` | `ContentPage`, expected_grant_revision bắt buộc | service key + Bearer + kiểm tra nguồn hiện hành/revision và version đúng serving_version hiện tại; bản READY lịch sử chỉ cho phép human citation qua public API. AI phải kiểm tra lại trước prompt/citation |
| GET `/internal/v1/events` | cursor + limit, event metadata IDs/revisions, không nội dung | key riêng scope `document:read_events`, không được dùng key đọc nguồn thay; consumer TASK-018 chưa được triển khai |

Hai key internal tách riêng cho read_sources/read_events. Không tạo dynamic scope do caller tự khai. `/health/live`, `/health/ready` không proxy qua browser; ready kiểm tra DB/storage/Core dependency nhưng không trả credential.

Không coi các internal API này là thiết kế của AI service. AI phải review cách dùng, không được coi event hoặc index cũ là bằng chứng quyền nguồn còn hiệu lực.

Admission xác minh session trước khi parse/spool multipart; request upload tối đa hạn mức file +64 KiB, JSON tối đa64 KiB. Request multipart chỉ có field đã chốt, không trùng field. UI không tự retry mutation; người dùng có thể chủ động phát lại đúng payload/key/revision/desired state đã giữ, vẫn đối soát riêng.
