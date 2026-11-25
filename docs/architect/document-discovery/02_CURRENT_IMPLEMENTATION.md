# DOC-00.2 — Hiện trạng implementation

## 1. Document Service

Không có implementation backend Document trong services/. Không tìm thấy endpoint document, class DocumentVersion/DocumentGrant, repository/service nghiệp vụ, migration, file API, scheduler, worker, audit ownership hoặc database Document. FRS Document vẫn đánh dấu PROPOSED / DESIGN REVIEW REQUIRED và ghi rõ backend chưa khả dụng: docs/architect/lumi-design/04_FRS_Document.md:3, 7–13.

### Giao diện Web

- Có route và feature library/reader cho teacher/student cùng domain types, document upload/version/sharing helper và unit tests.
- apps/web/src/lib/data/integrations.ts đánh dấu Document pending-contract.
- apps/web/src/lib/data/live.ts:29–57 implement live Document methods bằng lỗi UNAVAILABLE/503 cho preview, upload, version, retry, share/revoke, delete, notes/bookmark.
- apps/web/src/lib/api/operations.ts mô tả allowlist chỉ gồm Core operations; không có Document route.
- Vì vậy UI/mocks là giao diện và state logic, không phải luồng Document live có persistence.

## 2. Core authorization có thể tái sử dụng một phần

Core có GET /internal/v1/classes/{class_id}/access. Router yêu cầu scope core:check_access; access action enum đã có read_document_source và use_ai_tutor. API kiểm tra trạng thái/membership/quyền lớp ở Core, nhưng không sở hữu hay xác minh Document ownership/grant/version. Tham chiếu: services/core/app/modules/classroom/router.py:60–63, 482–493; classroom/schemas.py:19–27; app/common/auth_dependencies.py:86–96.

Code hiện dùng GET /internal/v1/classes/{class_id}/access với X-Service-Key và action legacy; đây chưa phải CORE-T03. Target là shared Service JWT theo SYS-02/CORE-T04 và POST /internal/v1/authorization/check. Document chỉ tiêu thụ foundation dùng chung.

## 3. RAG Engine cần thiết cho tích hợp

RAG hiện là pipeline/library offline:

1. Ingestion: idp/ingest.py:151; orchestration/pipeline.py:291, 839. Digital parser chủ yếu sinh canonical artifacts; ingestion_only=False bị từ chối ở pipeline.
2. Worker/registry: orchestration/worker.py:73, 158, 337–371, 540; registry.py lưu trạng thái local SQLite. Đây không phải API nhận job durable của AI Service hoặc Document DB.
3. Canonical: idp/canonical.py:21 hiện emitter là idp-canonical-1. Đường xử lý v2 trong harness import idp.publish, nhưng file này không có trên HEAD.
4. Index: indexing/rag_corpus.py:28, 73 nhận TextDocument (source_id/text/format) và ghi bundle/artifacts filesystem; không có DocumentVersion/grant/active-version service contract.
5. Retrieval: retrieval/retrieval.py:4, 480 yêu cầu authorize callback được caller cung cấp; kết quả ghi rõ không tự cấp authorization. Callback chưa nối với Core/Document.
6. Generation: services/rag/pipeline.py trace có raw_generation_text/primary_raw_generation_text và cờ không chứng nhận tính đúng đắn. Đây là output nội bộ, không được expose như public API.

Ranh giới quan trọng: DOC-D01 giao Document sở hữu file/version/grant/job; AI sở hữu việc chạy extraction/OCR/Canonical/chunking/embedding/indexing. RAG-D02 Canonical v1/v2 vẫn DEFERRED; DOC-00 không thay đổi pipeline hoặc quyết định đó.

## 4. Input formats và giới hạn

- FRS Document liệt kê PDF, PPTX, DOCX, TXT, Markdown; size/MIME sniffing/quarantine còn cần thiết kế.
- RAG filetype detector hỗ trợ thêm XLSX, CSV, HTML, email, ảnh và nhiều dạng text. InputLimits mặc định 512 MiB, 5.000 trang, 10 triệu ký tự; đây là giới hạn pipeline, không phải policy upload của Document.
- Không dùng giới hạn của RAG để suy ra giới hạn public API; DOC-T03 ghi 50 MB/format là đề xuất cần xác nhận với nhóm AI.

Evidence: docs/architect/lumi-design/04_FRS_Document.md:15–23; services/rag/idp/input/filetypes.py:24–70, 92–120.

## 5. Thành phần hiện có và khả năng reuse

| Thành phần | Reuse được | Điều kiện |
|---|---|---|
| Core class access check | Có, cho membership/action/class status | Bổ sung/đồng bộ Service JWT và scope; Document vẫn kiểm tra grant riêng. |
| SQLAlchemy/Alembic patterns của Core | Có thể tham khảo | Tạo ownership/schema/migration độc lập cho Document; không import model/repository Core. |
| Core CI/PostgreSQL Compose smoke patterns | Có thể tham khảo | Thêm test DB/service scope riêng; không dùng production DB. |
| RAG parsers, canonical, chunking, embedding, retrieval, generation | AI Service có thể dùng làm library theo DOC-D01 | Không sao chép thuật toán sang Document; cần adapter HTTP và contract liên service. |
| RAG local worker/SQLite/filesystem | Chỉ dùng làm đối chiếu hoặc local fixture | Không coi là durable job store, production index store hay Document source of truth. |
| Web Document UI/data types | Có thể nối qua public data port khi contract được phê duyệt | Không mở rộng API allowlist trước khi có endpoint/DTO/error agreement. |

## 6. Ảnh hưởng thiết kế cross-service

- Core owns current user/membership/role decision; Document checks owner, grant, version and local resource. Reuse class decision logic only behind CORE-T03 REST adapter; do not import Core internals.
- Current Core check_class_action validates ACTIVE user, school scope, current membership/teacher assignment and class state. It exposes legacy READ_DOCUMENT_SOURCE; this is not automatically equivalent to CORE-T03 DOCUMENT_READ, DOCUMENT_SHARE or DOCUMENT_MANAGE.
- Learning LRN-D07/T05 validates source/version and AI result before save; LRN-D10 allows a permission-valid snapshot when Document is offline and no source content is needed.
- Notification can notify the document owner for ingestion success/failure, but event names, recipient lookup and mandatory delivery are pending. Durable event ACK is not delivery or account-deletion completion.
- CORE-T06/T08 sends user.deletion_requested per target; Document handles its owned source/grants and coordinates index deletion with AI. Completion contract is open.
