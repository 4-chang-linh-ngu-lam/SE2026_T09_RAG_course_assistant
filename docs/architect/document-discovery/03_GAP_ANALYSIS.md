# DOC-00.3 — Gap analysis

Quy ước: EXISTS_COMPATIBLE = phù hợp mục tiêu đã duyệt; EXISTS_NEEDS_CHANGE = có thành phần nhưng thiếu/thay đổi trước tích hợp; MISSING = chưa có; CONFLICT = implementation hiện tại mâu thuẫn trực tiếp với thiết kế đã duyệt; NOT_VERIFIED = thiếu bằng chứng.

| Component | Hiện trạng và bằng chứng | Target / quyết định | Phân loại | Tác động / hành động đề xuất | AC |
|---|---|---|---|---|---|
| Service boundary | Chỉ có services/core và services/rag; Core compose register Core modules. | Document là service sở hữu thư viện, file, versions, grants, jobs. DOC-D01, ADR-001. | MISSING | Tạo service riêng sau review; không mở module tài liệu trong Core. | 01–48 |
| Document schema/database | Không có services/document hoặc migration; Core chỉ quản lý schema core. | DB/credential/migration riêng cho Document, 4 bảng DOC-T02. | MISSING | Tạo ownership cô lập; đối chiếu ID/reference trước migration; không FK xuyên service. | 01–07, 16–22 |
| Public Document API | Không có Core routes hoặc Web allowlist cho documents. | Contract route group /api/v1/documents và classes/{id}/documents. DOC-T03. | MISSING | Xây contract-first; chốt field/size/MIME/pagination trước build. | 01–07, 23–34 |
| Upload validation | Web helper kiểm extension/size; RAG parser có preflight nhưng không phải upload handler. | Server validation, durable file storage, checksum, zip safety. DOC-D07/T03. | EXISTS_NEEDS_CHANGE | Dùng backend validation; không tin frontend policy hoặc RAG defaults làm product policy. | 01–07 |
| Source storage / file download | Compose chỉ có volume pgdata; RAG lưu artifacts cục bộ, chưa có Document file API. | Docker Volume abstraction và authenticated streaming nội bộ, SHA-256. DOC-D07/T04. | MISSING | Tạo adapter storage và job-bound download; thiết kế path safety, cleanup, backup. | 01–07, 28 |
| Version lifecycle/activation | Không có DocumentVersion/active pointer backend. RAG bundles không là authoritative activation. | Tách latest file version và active RAG version; chỉ activate index ready chính xác. DOC-D04/05, T02. | MISSING | Transaction activation và stale-result guard. | 16–22, 45–46 |
| Grants/revocation | Core biết quyền lớp; Document grant không có. | Core membership + Document grant hiện hành; revoke chặn truy vấn ngay. DOC-D06. | EXISTS_NEEDS_CHANGE | Reuse Core access check cho class side; tạo grant source-of-truth tại Document và query-time check. | 23–34, 47 |
| Service JWT foundation | Code Core hiện còn X-Service-Key; shared verifier/issuer chưa được xác minh. | SYS-02/CORE-T04 Service JWT cấp hệ thống; Document là consumer, không tự triển khai auth. | EXISTS_NEEDS_CHANGE | Chờ foundation/key lifecycle và wire-compatible verifier; không fallback sang user JWT/key legacy. | 25–27, 34 |
| Core authorization adapter | check_class_action xử lý ACTIVE user, school, membership/assignment và action; code hiện GET class access/X-Service-Key. | CORE-T03 POST /internal/v1/authorization/check; Core quyết định membership/role, Document quyết định owner/grant/version. | EXISTS_NEEDS_CHANGE | Reuse phía Core qua REST adapter; không import internal modules. Mapping READ_DOCUMENT_SOURCE sang DOCUMENT_READ/SHARE/MANAGE cần review. | 23–34 |
| Document ingestion jobs | Không có Document job table/worker. RAG worker dùng file queue và local registry. | PostgreSQL durable jobs trong Document, REST submit/status, idempotency. DOC-D02/03, T02/T05. | MISSING | Persist state trước trả 201/202; khôi phục khi restart; polling từ backend. | 08–15, 35–42 |
| AI HTTP integration | RAG không có FastAPI/API routes; AI service chưa có. | AI nhận REST 202 durable job, status, deletion/readiness; RAG là library. DOC-D01/02, T04. | MISSING | AI team sở hữu API/worker/index; TL tạo client/mock adapter theo contract. | 08–22, 35–48 |
| Canonical/index adapter | Current emitter canonical-1; version-2 path nhắc idp.publish không có. | Document/AI cần version-bound file-to-index handoff; RAG-D02 vẫn deferred. | EXISTS_NEEDS_CHANGE | AI team xác nhận adapter và locator; không sửa thuật toán ở DOC-00. | 16–22, 43–48 |
| Readiness / index deletion | Không có production index-ready, active alias hoặc index delete API. | Readiness đúng version; async deletion; stale ingestion không resurrect. DOC-D05/T04, SYS-B06. | MISSING | AI owns index cleanup; Document revoke ngay và track local cleanup/completion. | 16–22, 48 |
| Distributed account deletion | Core-T06/T08 targets user.deletion_requested/per-target completion; Document receiver/job chưa có. | Service-owned cleanup, durable ACK distinct from completion. | MISSING | Ghi DOC-OD-09; không sửa DOC-T02 schema trong R1. | C-AC17, S-AC14 |
| Document notification events | Chưa có Document producer/recipient contract. | Notification durable inbox; ingestion success/failure to owner is draft only. | MISSING | Chốt event name, recipient lookup, dedup horizon cùng NTF owners. | NTF-T03/T04, SYS-B09 |
| Web live integration | Document integration pending-contract; live methods trả 503; operation allowlist là Core-only. | Gọi public Document API qua data port/proxy với contract được duyệt. | EXISTS_NEEDS_CHANGE | Adapter chỉ bật sau khi API schema/OpenAPI/role behavior có test. | 01–07, 23–34 |
| Error/correlation contract | Core hiện dùng correlation_id và X-Correlation-ID; DOC-T03 draft error dùng request_id. | Một correlation/error envelope thống nhất xuyên service. DOC-T03/T04. | EXISTS_NEEDS_CHANGE | Chốt tên/propagation ở API review; không làm mất tương thích Core. | all error AC |
| Resilience | Core có các worker/outbox khác; RAG worker cục bộ; chưa có Document↔AI retry/lease/circuit. | DOC-T05 durable retry, jitter, polling, lease/fencing, bounded concurrency. | MISSING | Tạo trong service sở hữu; không dùng Core notification worker làm queue Document. | 08–15, 35–42 |
| Audit/retention/deletion policy | Core Business Rules nêu audit và retention theo loại; Document lifecycle/delete retention chưa chốt. | Chặn quyền trước dọn dữ liệu; retention/deletion orchestration được phê duyệt. | NOT_VERIFIED | Không triển khai hard-delete policy cho tới khi quyết định; audit state transitions. | 21, 32, 48 |
| CI/test cho Document | Không có Document suite/job. RAG/Core/Web tests hiện tại không kiểm tra liên service. | DOC-T06 có 48 AC, mock AI và real integration gates. | MISSING | Thêm isolated Postgres/storage, contract/integration và E2E. | 01–48 |
| Deployment | Compose/CI chỉ chạy Core, DB, notification worker, Web; không có Document/AI image. | Service deploy riêng; DB/mount/credentials/health được vận hành theo ownership. | MISSING | Thêm deployment sau service health/security gates; DOC-00 không deploy. | 04–48 |

## Tóm tắt mâu thuẫn cần giữ nguyên để review

1. SYS-02/CORE-T04 Service JWT accepted nhưng implementation hiện tại còn X-Service-Key; đây là system foundation, không phải auth riêng Document.
2. CORE-T03 endpoint/action registry là target mới; API code cũ chưa tương thích.
3. Core correlation_id và DOC/SYS request ID cần contract mapping.
4. File formats/size/quarantine còn pending.
5. 15 RAG test files xác minh ở bốn Git refs; nguồn của số 21 chưa tìm thấy.

Không chỉnh code, schema, quyết định ACCEPTED hoặc tài liệu nguồn trong DOC-00.
