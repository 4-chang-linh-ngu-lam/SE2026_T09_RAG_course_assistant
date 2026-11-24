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

## DOC-T03 — Public API Contract (ACCEPTED)

**Phương án A — Upload đồng bộ, ingestion bất đồng bộ.** Product Owner đồng ý ngày 25/11/2026.

- Public API dự kiến /api/v1: POST/GET /documents; GET/PATCH/DELETE /documents/{id}; POST/GET /documents/{id}/versions; GET /documents/{id}/versions/{vid}; GET /documents/{id}/versions/{vid}/download; POST/GET /documents/{id}/grants; DELETE /documents/{id}/grants/{gid}; GET /classrooms/{cid}/documents; GET/POST /documents/{id}/versions/{vid}/jobs; GET /documents/{id}/versions/{vid}/jobs/{jid}. Tổng 16 endpoint; đối chiếu routing hiện tại trước implementation.
- Upload multipart file/title, trả 201 sau khi file lưu và DB transaction tạo version/job bền vững; không chờ AI. Detail trả latest_version, active_rag_version, ingestion status và rag_ready (eligibility, không phải live AI health). DELETE document trả 202, chặn truy cập mới ngay khi DELETING; cleanup bất đồng bộ. Retry trả 202; revoke grant 204.
- Owner/authorized manager quản lý; học sinh chỉ xem/tải tài nguyên được phép; xác minh quyền Core và Document. Không lộ storage key, lease, index nội bộ. 404 cho tài nguyên không được phép biết tồn tại; 403 cho thao tác bị cấm trên tài nguyên được phép thấy; 503 nếu không xác minh được quyền. HTTP 200/201/202/204/400/401/403/404/409/413/415/422/429/503 theo ngữ nghĩa chuẩn; error envelope error.code/message/request_id/details, không lộ nội bộ.
- Giới hạn 50 MB, PDF/DOCX/PPTX/TXT, pagination 20/100, frontend polling 3–5s vẫn đề xuất PENDING; xác nhận định dạng với AI team. Admin/co-teacher/ownership transfer/historical download, full DTO/OpenAPI và routing compatibility cần review trước implementation.

## DOC-T04 — Internal API Contract (ACCEPTED)

**Phương án B — Internal REST API + Service JWT.** Product Owner đồng ý ngày 25/11/2026.

- AI: POST /internal/v1/ingestion-jobs (job_id, document_id, version_id, file metadata/checksum, Idempotency-Key; 202 sau durable acceptance, ai_job_id); GET /internal/v1/ingestion-jobs/{ai_job_id} (job/version identity, status, index_ref, index_ready, error); DELETE /internal/v1/documents/{document_id}/indexes (202 deletion_job_id); GET /internal/v1/deletion-jobs/{id} khi xóa async. Ngăn ingestion tạo lại index sau deletion. index_ready nghĩa là index hoàn chỉnh và truy vấn được theo version/index_ref.
- Document: GET /internal/v1/versions/{version_id}/file (service auth, X-Ingestion-Job-ID, kiểm tra job/version/document, binary stream, Content-Length/Type, X-Content-SHA256); GET /internal/v1/classrooms/{classroom_id}/rag-scope (active grants/documents/versions và index_ref); POST /internal/v1/rag-scope/validate (classroom_id và toàn bộ phạm vi tài liệu đã sử dụng, valid/invalid_documents). AI phải bỏ kết quả không còn được phép hoặc thực hiện lại retrieval.
- Core: POST /internal/v1/authorization/check (user_id, resource_type, resource_id, action; allowed). Actions dự kiến AI_QUERY, DOCUMENT_READ, DOCUMENT_SHARE, DOCUMENT_MANAGE; đối chiếu RBAC hiện có. AI xác minh Core trước retrieval và trước trả lời, đồng thời validate Document scope; fail closed. Không tin user_id từ frontend nếu chưa xác thực.
- Service JWT riêng user JWT, xác minh chữ ký/issuer/audience/expiry/scope; internal network, không expose public gateway, TLS khi mạng không tin cậy. X-Request-ID để correlation. Token issuance, key management/rotation, exact DTO/OpenAPI, routing/ID compatibility, streaming race semantics và Learning D6 vẫn PENDING.
- Technical Lead sở hữu Core/Document endpoints, orchestration và integration; AI team sở hữu AI endpoints, durable worker, index readiness/deletion, scope enforcement và RAG internals. Technical Lead có thể bổ sung HTTP adapter nếu thiếu. AI team compatibility/confirmation chưa được xác minh.

## DOC-T05 — Retry, Timeout, Idempotency và Fault Isolation (ACCEPTED)

**Phương án B — Resilient REST Integration.** Product Owner đồng ý ngày 25/11/2026.

- Durable PostgreSQL jobs, exponential backoff + equal jitter, adaptive polling, circuit breaker, bounded concurrency, per-operation timeouts. Không bổ sung Redis/RabbitMQ/Kafka chỉ cho ingestion Increment 1. AI outage không chặn nghiệp vụ độc lập khi dependency cần thiết còn hoạt động.
- Retry transport timeout/refused, 502/503/504, 429 theo Retry-After, 500 có giới hạn; 400/422/403 dừng retry và review; 401 refresh một lần nếu phù hợp; 409 reconcile; checksum mismatch tải lại có giới hạn. Không đánh FAILED chỉ vì mất liên lạc hoặc job lâu; timeout không hủy remote job. Sau khi hết retry budget cần đối soát/alert, không tạo execution mới khi trạng thái remote chưa rõ.
- Resend cùng job/key; AI lưu mapping bền vững, trả job cũ cho payload giống nhau, 409 nếu cùng key khác payload. Retry execution đã xác nhận FAILED tạo job/key mới. Không cam kết exactly-once execution; index publication phải an toàn khi chạy lại.
- Worker claim transaction ngắn (FOR UPDATE SKIP LOCKED hoặc tương đương), lease token/expiry, fencing khi ghi kết quả; HTTP ngoài DB transaction. Restart/lease expiry phục hồi cùng job/key. Frontend chỉ poll Document.
- Cấu hình khởi điểm chưa benchmark: backoff base 5s cap 300s, equal jitter [d/2,d]; polling theo tuổi job 3s (0–30s), 5s (30s–2m), 15s (2–10m), 30s (>10m); dependency errors backoff. Circuit mở sau 5 lỗi dependency liên tiếp, 30s cooldown, một probe half-open; không tính lỗi nghiệp vụ/validation. Connect 3s, authorization/scope/status 5s, submit 10s, file download 120s tổng, AI query 60s tổng, cảnh báo ingestion 30m. Retry budgets, concurrency/lease limits, benchmark và AI compatibility vẫn PENDING.

## DOC-T06 — Integration Test và Acceptance Criteria (ACCEPTED)

**Phương án B — Contract-First Testing + Mock AI + Real Integration Test.** Product Owner đồng ý ngày 25/11/2026.

- Unit, contract, integration, E2E và performance tests; mock AI để phát triển song song, real AI bắt buộc trước nghiệm thu tích hợp. Test DB/storage riêng, không dùng production data.
- AC-01–07: upload hợp lệ, giới hạn kích thước, file invalid, persistence restart, orphan cleanup, concurrent version numbering, checksum mismatch.
- AC-08–15: durable acceptance, lost response dedup, conflicting payload 409, worker recovery, stale lease fencing, retry history, polling timeout không FAILED, AI restart sau 202.
- AC-16–22: activate V1, giữ V1 khi V2 processing/failed, activate V2 khi ready, stale result không overwrite, delete during ingestion không resurrect, SUCCEEDED chưa ready không activate.
- AC-23–34: outsider denied, spoof owner denied, user JWT denied internal, expired service JWT denied, wrong audience/scope denied, file outside job denied, Core unavailable fail closed, scope unavailable fail closed, revoke before retrieval, revoke before response, spoof document denied, internal gateway blocked.
- AC-35–42: upload/download khi AI offline, recovery pending jobs, circuit breaker 503, 429 retry policy, bounded concurrency, Document restart recovery, long job alert không duplicate.
- AC-43–48: real PDF indexing, scoped QA, exact-version citation, version replacement, grant revocation, deletion cleanup.
- Gates: static, unit, contract/integration, applicable AC, Technical Lead review. DoD: scope/accepted decisions, no unauthorized contract change, tests pass, no secrets/data exposure, config/test instructions, mock vs real evidence, no unexplained skip, review. IMPLEMENTED != VERIFIED != INTEGRATION_ACCEPTED.
- CI proposal: static/unit/contract on push/PR; relevant integration on service PR; cross-service before integration merge; E2E/real AI smoke before demo; AC/performance before increment acceptance. 358 concurrent users requires explicit workload, not 358 simultaneous inference requests. Exact tooling/layout, quantitative performance, streaming revocation, Learning D6 remain pending. No tests executed by this approval.

## DOC-T07 — Implementation Roadmap (ACCEPTED)

**Phương án B — Incremental Implementation with Technical Lead Review.** Product Owner đồng ý ngày 25/11/2026.

- Roadmap sơ bộ 14 task: DOC-00 discovery; DOC-01 database/migrations; DOC-02 storage; DOC-03 service JWT; DOC-04 DTO/OpenAPI/errors; DOC-05 document/version CRUD; DOC-06 Core authorization/grants; DOC-07 internal file/scope; DOC-08 mock AI/client; DOC-09 durable worker; DOC-10 resilience; DOC-11 activation/deletion; DOC-12 integration/security/fault isolation; DOC-13 real AI acceptance.
- Dependencies: 01–04 sau 00; 05 sau 01/02/04; 06 sau 01/03/04; 07 sau 05/06; 08 sau 03/04; 09 sau 05/07/08; 10 sau 09; 11 sau 09/10; 12 sau 01–11; 13 sau 12 và AI thật. Backlog cuối cùng phải review sau discovery; security prerequisites bắt buộc trước expose API.
- DOC-00 read-only application code: khảo sát Document/Core/AI boundaries, DB/migrations, auth, storage, compose, frontend, tests/CI, business rules. Phân loại EXISTS_COMPATIBLE / EXISTS_NEEDS_CHANGE / MISSING / CONFLICT, evidence file/line, đề xuất reuse và backlog/AC mapping. Không review lại thuật toán RAG. Không tự giải quyết conflict kiến trúc.
- Mỗi task: preflight Git, scope file, implementation, verification, evidence, Engineering Review, Technical Lead approval; không tự commit/push/merge/deploy. Mock không thay thế real integration acceptance. Mapping AC theo DOC-T06, hoàn thiện sau DOC-00.
- Milestone: DOC-D01–07 và DOC-T01–07 ACCEPTED về thiết kế; implementation/verification chưa bắt đầu theo roadmap mới. RAG-D02 deferred; AI compatibility, exact contracts/configuration và các pending decisions vẫn mở. Tiếp theo DOC-00 discovery.
