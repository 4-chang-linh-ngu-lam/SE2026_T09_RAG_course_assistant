# Lumi RAG — Biên bản Technical Lead Review 01

**Trạng thái:** RAG-D01 ACCEPTED / CÁC CONTRACT CHI TIẾT PENDING  
**Source commit:** `2d975514c4d017fe135b38df13652714b33433eb` (`codex/rag-technical-discovery`)  
**Nguồn:** `docs/architect/rag-discovery/00..09`, `docs/architect/microservices-v1/ADR-001.md`, `docs/architect/microservices-v1/ARCHITECTURE.md`, `docs/architect/BUSINESS_RULES.md`, `services/rag/README.md`.

## Đã xác minh từ 10 tài liệu discovery

- `services/rag` là pipeline Python offline với các stage IDP, chunking, indexing, retrieval, packing, generation và citations; chưa có HTTP API hoặc AI Service triển khai.
- Canonical emitter hiện dùng `idp-canonical-1`; đường v2 được mô tả nhưng `idp.publish` không có trong repository được khảo sát. Chưa có adapter production version-bound Canonical → TextDocument → index.
- Index chính hiện là immutable filesystem bundles và vectors nạp RAM; không có active version pointer, source grant ownership hoặc multi-instance lifecycle.
- Retrieval yêu cầu caller-provided authorization callback; callback chưa nối với Core/Document; việc kiểm tra lại trước trả answer đã có trong engine nhưng không thay thế quyền thực tế.
- Các kiểm thử CI 144 passed, 2 skipped, 1 xfailed dựa vào fixtures; không chứng minh inference model thật hoặc RAG end-to-end Production.
- AI Tutor chưa có conversation storage và Learning D6/Document active-grant API.
- Rủi ro bảo mật: trace nội bộ có raw generation text, không được expose/log qua public HTTP adapter; locator/citation hiện chưa phải Document-facing DTO hoàn chỉnh.

## Kết luận review

Các báo cáo phù hợp để làm tài liệu khảo sát và lập danh sách rủi ro; chúng **không phải approved implementation/API contract**. Không tự đổi trạng thái của `09_OPEN_DECISIONS.md` thành ACCEPTED.

## ADR-001 và ranh giới đã duyệt (RAG-D01)

**Ranh giới được duyệt (RAG-OD-01):** Giữ 5 microservices như ADR-001. `services/rag` là Python library/engine được AI Service sử dụng cho index/query/generation, không mở thêm RAG microservice thứ sáu.

**Ranh giới sở hữu được duyệt (RAG-OD-01 và RAG-OD-03):** Document Service sở hữu upload/source files/DocumentVersion/class grants/revocation/processing jobs; có thể sử dụng `idp`/chunking như Python library trong worker của chính Document. AI Service sở hữu conversation/message, derived search index và Tutor orchestration, gọi Core current classroom access, Document current grants/versions, Learning official assessment D6. Mọi truy hồi phải fail closed khi chưa kiểm chứng quyền.

**Chưa chốt:** ranh giới thực thi embedding/indexing, chuẩn canonical adapter, API endpoints, storage, event contract, inference provider, model runtime và chính sách vận hành.

**Lưu ý:** RAG engine không cần và không nên tự tin tưởng `source_acl` trong Canonical; gateway/service layer phải cấp đúng authorized child IDs từ quyền Core + Document hiện hành.

## Câu hỏi để Product Owner phê duyệt — RAG-D01

Có đồng ý giữ RAG là thư viện nội bộ của **AI Service** (không thêm service thứ sáu) và để **Document Service sở hữu file/version/grant/ingestion**, còn **AI Service sở hữu retrieval/index dẫn xuất/generation/conversation**, theo ADR-001 hay không?

- A — Đồng ý khung ranh giới này (khuyến nghị Technical Lead; các contract chi tiết vẫn PENDING).
- B — Muốn RAG thành microservice HTTP riêng (cần giải trình thay đổi ADR-001 và chi phí vận hành).
- C — Chưa chốt; cần đánh giá thêm.

**Trạng thái quyết định:** ACCEPTED — Phương án A.

**Ngày phê duyệt:** 25/11/2026 (Product Owner).

**Phạm vi:** Chấp thuận ranh giới sở hữu và mô hình 5 microservices; không thêm RAG service thứ sáu. Các contract chi tiết và quyết định mở trong discovery vẫn cần review riêng; không phải phê duyệt triển khai hoặc deploy.

## Các quyết định tiếp theo

1. Canonical v1/v2 và adapter giữ page/block locator.
2. Lifecycle index/version activation/reindex/delete; Document→AI event contract.
3. Core/Document/Learning current-access checks và query-time authorization.
4. AI HTTP API: Tutor turns, retrieve-only internal operations, history/streaming.
5. Model provider/runtime, test evidence, privacy, retention 14 ngày chat/tạm/log theo quyết định Product Owner trước đó (chưa đồng bộ vào GitHub ADR).

## Giới hạn review

Đã đọc đầy đủ 10 Markdown discovery và đối chiếu tài liệu nguồn chuẩn. Chưa chạy mã hay test mới, chưa xác minh remote Production runtime. Đây là biên bản kiến trúc, không phải nghiệm thu thực thi.

## Điều chỉnh phạm vi thiết kế — 25/11/2026 (ACCEPTED)

- Product Owner phụ trách Core, Document, Learning, Notification và tích hợp toàn hệ thống.
- Nhóm AI/RAG phụ trách AI Service và RAG Engine; Product Owner hỗ trợ endpoint/adapter tích hợp khi cần.
- RAG-D01 giữ ACCEPTED. RAG-D02 (Canonical v1/v2) DEFERRED, giao nhóm AI/RAG quyết định nội bộ; hợp đồng dữ liệu liên service vẫn cần hai bên thống nhất.
- Thứ tự review tiếp theo: Document–AI integration contract; authorization Core/Document/AI; Learning–AI; lifecycle tài liệu/index; public API/frontend; lỗi/retry/timeout; integration tests/deployment.
- Không phê duyệt trước các contract hoặc thuật toán chưa được thảo luận.

## DOC-D01 — Ranh giới xử lý tài liệu (ACCEPTED)

**Phương án A — Document quản lý, AI xử lý nội dung.** Product Owner phê duyệt ngày 25/11/2026.

- Document Service sở hữu file gốc, metadata, DocumentVersion, grants/revocation, kiểm tra upload, điều phối ingestion jobs và theo dõi trạng thái xử lý; yêu cầu AI xử lý hoặc xóa index khi cần.
- AI Service sở hữu thực thi trích xuất/OCR/Canonical/chunking/embedding/indexing và dữ liệu index dẫn xuất; báo cáo kết quả xử lý cho Document.
- Quyết định này cụ thể hóa RAG-D01: Document sở hữu nghiệp vụ ingestion, AI thực thi pipeline nội dung. Đề xuất trước đây về thực thi IDP/chunking trong Document worker không được chọn cho phạm vi này.
- Canonical v1/v2 và thuật toán nội bộ vẫn thuộc nhóm AI/RAG (RAG-D02 DEFERRED). Giao thức REST/queue, schema, retry, idempotency, activation và authorization contract vẫn PENDING.

## DOC-D02 — Cơ chế giao tiếp Document–AI (ACCEPTED)

**Phương án B — REST API bất đồng bộ cho Increment 1.** Product Owner phê duyệt ngày 25/11/2026.

- Document gửi yêu cầu xử lý; AI trả HTTP 202 Accepted cùng job ID sau khi tiếp nhận bền vững, xử lý pipeline bất đồng bộ.
- Job phải bền vững qua restart, hỗ trợ idempotency và retry; Document vẫn hoạt động khi AI offline, không đánh dấu READY khi chưa xác minh index đúng phiên bản và đủ điều kiện kích hoạt.
- Không bổ sung message broker cho tích hợp này trong Increment 1; giữ khả năng chuyển đổi sau này. Không coi FastAPI BackgroundTasks đơn thuần là cơ chế job bền vững.
- Polling/callback, worker runtime, endpoint/schema cụ thể, retry policy, authorization và activation contract vẫn PENDING; nhóm AI/RAG sở hữu thực thi nội bộ.

## DOC-D03 — Đồng bộ trạng thái xử lý (ACCEPTED)

**Phương án A — Polling cho Increment 1.** Product Owner đồng ý ngày 25/11/2026.

- Document Service chủ động polling trạng thái job qua internal REST API của AI; không phụ thuộc trình duyệt, lưu trạng thái bền vững và phục hồi sau restart.
- Hỗ trợ backoff khi lỗi hoặc job kéo dài; xác minh job/version và điều kiện activation trước READY. Không coi lỗi kết nối là kết quả xử lý thất bại.
- Không yêu cầu callback trong Increment 1; có thể nâng cấp Hybrid sau này. Chu kỳ polling, scheduler, endpoint/schema và retry policy cụ thể vẫn PENDING.

## DOC-D04 — Vòng đời và trạng thái tài liệu (ACCEPTED)

**Phương án B — Tách trạng thái theo trách nhiệm.** Product Owner đồng ý ngày 25/11/2026.

- Tách vòng đời Document, trạng thái lưu file DocumentVersion và trạng thái thực thi IngestionJob; không gộp thành một status chung.
- Trạng thái dự kiến: Document ACTIVE/DELETING/DELETED; DocumentVersion UPLOADING/STORED/FAILED; IngestionJob PENDING/PROCESSING/SUCCEEDED/FAILED. Tên enum và schema cụ thể vẫn PENDING.
- AI lỗi không làm mất khả năng quản lý/tải file đã lưu nếu quyền hiện hành cho phép. Retry bảo toàn lịch sử thực thi; SUCCEEDED không đồng nghĩa index đã activation.
- Query chỉ được phép với phiên bản/index hợp lệ đã kích hoạt và quyền hiện hành; chính sách version activation, reindex, deletion và authorization chi tiết vẫn PENDING.

## DOC-D05 — Quản lý phiên bản tài liệu và kích hoạt index (ACCEPTED)

**Phương án B — Chuyển đổi tự động khi phiên bản mới sẵn sàng.** Product Owner phê duyệt ngày 25/11/2026.

- Mỗi DocumentVersion có ID riêng, không ghi đè file gốc. Phân biệt latest_version_id (file mới nhất đã lưu) và active_rag_version_id (phiên bản được phép dùng cho RAG); tên trường/schema cụ thể vẫn là đề xuất.
- Giữ phiên bản RAG cũ hợp lệ trong khi phiên bản mới đang xử lý hoặc thất bại; chỉ chuyển con trỏ bằng transaction trong Document khi index mới đúng version, đã xác minh và đủ điều kiện activation.
- Kết quả job cũ đến muộn không được kích hoạt nhầm phiên bản. Thu hồi quyền/xóa phải chặn truy vấn mà không chờ xóa index. Citation tham chiếu đúng phiên bản đã dùng.
- Document quyết định version được phép truy vấn; AI bảo đảm index tương ứng tồn tại và truy vấn được. Retention phiên bản cũ, rollback, giao thức xác nhận index và authorization chi tiết vẫn PENDING.

## DOC-D06 — Quyền truy cập tài liệu và thu hồi quyền (ACCEPTED)

**Phương án B — Core + Document xác minh quyền hiện hành.** Product Owner đồng ý ngày 25/11/2026.

- Core sở hữu membership và quyền sử dụng AI trong lớp; Document sở hữu grant/revocation và phạm vi DocumentVersion đang hoạt động. AI/RAG thực thi retrieval chỉ trong phạm vi đã xác minh.
- Không tin quyền/danh sách tài liệu từ frontend hoặc metadata index như nguồn authorization. Kiểm tra trước retrieval và trước khi trả nội dung; fail closed nếu không xác minh được quyền hiện hành.
- Thu hồi quyền/xóa chặn truy vấn mới mà không chờ xóa index. Streaming revocation cần contract riêng; nội dung đã gửi không thể thu hồi.
- Service-to-service authentication, endpoint/schema, consistency/race handling, streaming và Learning D6 contract vẫn PENDING. Không áp đặt cách bố trí vector index nội bộ.

## DOC-D07 — Lưu trữ và bàn giao file (ACCEPTED)

**Phương án B — Internal Download API + Storage Abstraction.** Product Owner đồng ý ngày 25/11/2026.

- Document sở hữu file gốc; Increment 1 dùng Docker Volume riêng bền vững qua restart, thông qua Storage Interface để có thể thay adapter Object Storage sau này.
- AI tải đúng DocumentVersion qua Internal Download API có xác thực service và giới hạn phạm vi job; streaming file, không Base64 trong JSON, không chia sẻ đường dẫn vật lý. SHA-256 kiểm tra toàn vẹn; AI quản lý và dọn file tạm.
- Giới hạn dung lượng, định dạng, credential, endpoint/schema và interface cụ thể vẫn PENDING.

## Mốc hoàn thành lựa chọn kiến trúc nền tảng Document Service

DOC-D01 đến DOC-D07 ACCEPTED. Chuyển sang technical design: database/ERD, public API, internal API, retry/timeout/idempotency, integration tests/acceptance criteria và implementation tasks. Các thiết kế chi tiết chưa được phê duyệt; RAG-D02 vẫn DEFERRED cho nhóm AI/RAG.

## DOC-T01 — Database Ownership (ACCEPTED)

**Phương án B — Một PostgreSQL instance, database riêng cho mỗi service có nhu cầu dữ liệu quan hệ.** Product Owner phê duyệt ngày 25/11/2026.

- Database, credential và migration riêng theo service; không truy vấn trực tiếp, SQL JOIN hoặc foreign key xuyên service. Tham chiếu owner_id/classroom_id tới Core là tham chiếu logic, xác minh qua API.
- Chấp nhận PostgreSQL instance là điểm lỗi chung trong Increment 1; không áp đặt PostgreSQL cho vector index hoặc persistence nội bộ của AI/RAG.
- Chỉ phê duyệt database ownership; schema bốn bảng, kiểu dữ liệu, constraints, indexes và transaction chi tiết vẫn PENDING.

## DOC-T02 — Database Schema, ERD và Constraints (ACCEPTED)

**Phương án B — Bốn bảng, mỗi lần thực thi ingestion là một job riêng.** Product Owner đồng ý ngày 25/11/2026.

- documents: id, owner_id, title, status, latest_version_id, active_rag_version_id, created_at, updated_at, deleted_at.
- document_versions: id, document_id, version_number, storage_key, original_filename, mime_type, size_bytes, sha256, file_status, created_at, stored_at.
- document_grants: id, document_id, classroom_id, granted_by, granted_at, revoked_by, revoked_at.
- ingestion_jobs: id, version_id, ai_job_id, idempotency_key, status, attempt_number, index_ref, next_action_at, error_code, created_at, updated_at, completed_at, lease_until, lease_token.
- UUID nội bộ, ID ngoài theo contract, TIMESTAMPTZ, BIGINT dung lượng, INTEGER version/attempt, CHAR(64) SHA-256, VARCHAR + CHECK cho trạng thái. Hai con trỏ version nullable, composite FK bảo đảm cùng document. Unique document/version_number, document/id, storage_key, idempotency_key; version_number dương, size không âm, STORED yêu cầu metadata đầy đủ. Không unique SHA-256 toàn cục.
- Partial unique active grant theo document/classroom với revoked_at IS NULL; bảo toàn lịch sử. Index phục vụ owner/status, version history, active classroom grants, job version/attempt, status/next_action_at. Worker lease có token và thời hạn.
- Retry execution đã xác nhận FAILED tạo job và key mới; resend/polling lỗi giữ nguyên job/key. Không tạo nhiều job đang hoạt động cho cùng version; bảo toàn lịch sử.
- Transaction T1 hoàn tất upload: STORED, latest pointer, PENDING job; T2 khóa document, xác minh index/version/job và chống stale activation; T3 revoke grant; T4 retry kiểm tra eligibility và tạo job mới. File storage không nằm trong DB transaction: yêu cầu reconciliation và cleanup file mồ côi.
- Trước migration phải đối chiếu schema/migrations/ID hiện tại; báo xung đột để review, không tự thay đổi quyết định. Chi tiết contract AI, lease/retry policy, cleanup và migration implementation chưa được xác minh.
