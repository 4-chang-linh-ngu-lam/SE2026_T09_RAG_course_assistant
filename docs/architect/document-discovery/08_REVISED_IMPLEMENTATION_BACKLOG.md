# DOC-00.8 — Backlog triển khai đề xuất sau khảo sát

Roadmap dưới đây đã đối chiếu DOC-T07 với Master Implementation Plan tại c7f56c7. Đây là đề xuất để Technical Lead review, chưa phải lệnh bắt đầu DOC-01 hoặc thay đổi roadmap đã ACCEPTED.

## MIP alignment và quan hệ chạy song song

| Phase | Document scope | Dependency / parallelism |
|---|---|---|
| 0 Discovery/contracts | DOC-00-R1 | CORE-00/LRN-00/NTF-00/SYS-00 và AI contract review chạy song song; chưa code. |
| 1 Foundation | Không làm Service JWT riêng trong Document | SYS-01 DB isolation, SYS-02 shared Service JWT, SYS-03 gateway và CORE-01–04/CORE-T03 trước khi expose internal API. |
| 2 Independent services | DOC-01–08 | DOC-01 DB, DOC-02 storage, DOC-04 DTO có thể chạy song song; DOC-03 chờ SYS-02/CORE-T04; DOC-05 chờ 01/02/04; DOC-06 chờ 01/03/04/CORE-T03; DOC-07 chờ 02/05/06/AI contract; DOC-08 chờ 03/04/AI contract. Learning LRN-01–08 và Notification NTF-01–05 có thể chạy song song sau foundation. |
| 3 AI integration | DOC-09–13 | DOC-09 sau 05/07/08; DOC-10 sau 09; DOC-11 sau 09/10 và deletion decision; AI owns RAG internals/readiness/delete. |
| 4 Frontend | Document UI qua SYS-04 | Chỉ nối live sau public API/gateway DTO/error contract ổn định; preparation có thể song song. |
| 5 Acceptance | DOC-12/13 cùng SYS-05–09 | E2E/security/fault, load, backup/restore và final acceptance; real AI không được thay bằng mock. |

Các dòng task bên dưới giữ objective, reuse, candidate scope, AC, verification và blockers. DOC-03 đổi nghĩa thành Document adoption của shared JWT foundation, không tạo auth/key service riêng.

## DOC-01 — Database và migrations

- **Objective:** tạo database/schema Document-owned với bốn bảng DOC-T02.
- **Owner / dependencies:** Technical Lead; sau DOC-00 approval.
- **Reuse:** quy ước UUID/timestamp, SQLAlchemy/Alembic patterns và test PostgreSQL của Core; không import Core models.
- **Expected changes / candidate scope:** service mới services/document, DB settings, models, migrations, isolated test DB. Database/credential/migrations riêng; unique/index/composite constraints và migration guard.
- **AC / verification:** AC-04, 06, 13, 16–22, 40; migration upgrade/check, constraints, concurrent version numbering và restart integration trên PostgreSQL 16 riêng.
- **Risks / blockers:** không có dữ liệu Document hiện tại được phát hiện, nhưng DB Production chưa kiểm tra; cần preflight/backup. Chốt schema constraints với DOC-T02 trước DDL.

## DOC-02 — Storage abstraction

- **Objective:** lưu/tải/xóa file gốc bền vững theo DOC-D07.
- **Dependencies:** sau DOC-00 approval; có thể phát triển interface song song DOC-01, hợp nhất trước CRUD.
- **Reuse:** Core Docker/Compose conventions, không dùng Core database volume làm file store.
- **Expected changes / candidate scope:** services/document storage adapter, persistent Document volume, temp/final object workflow, checksum, streamed read/write và orphan reconciliation.
- **AC / verification:** AC-01–07, 28, 35–36, 48; test path traversal, restart, checksum, partial write and cleanup bằng file giả trong volume tạm.
- **Risks / blockers:** quota, encryption, backup, malware/zip scan, max size và file name policy chưa được duyệt.

## DOC-03 — Document adoption của Service JWT foundation

- **Objective:** Document xác minh/gửi Service JWT theo foundation SYS-02/CORE-T04; không tự tạo issuer, key store, signer hoặc auth protocol riêng.
- **Dependencies:** DOC-00 approval và SYS-02/CORE-T04 implementation; CORE-T03 cho authorization call.
- **Reuse:** shared verifier/config/credential issuance của system; không dùng user JWT cho internal calls.
- **Expected changes / candidate scope:** Document middleware/client config và audience/scope allowlist sau khi shared contract có.
- **AC / verification:** AC-25–27, 34 qua shared test fixtures: expired/wrong issuer/audience/scope/source bị từ chối; không public gateway.
- **Risks / blockers:** SYS-02 key issuance/distribution/rotation chưa được xác minh trong implementation.

## DOC-04 — DTO, OpenAPI và error contract

- **Objective:** contract-first DTO, validation, OpenAPI, status/error/correlation semantics.
- **Dependencies:** sau DOC-00; chạy song song DOC-01–03.
- **Reuse:** Core public contract, UUID/time/pagination/error styles; preserve compatibility where agreed.
- **Expected changes / candidate scope:** Document schemas/router contract, generated OpenAPI snapshot, Web decoders; compare request_id target with Core correlation_id.
- **AC / verification:** contract tests cho 16 public + internal operation groups, schema validation and 4xx/5xx envelope.
- **Risks / blockers:** upload 50 MB/formats, cursor DTO, IDs, Retry-After, 404/403 concealment, exact DTO remain incomplete.

## DOC-05 — Document CRUD và version management

- **Objective:** owner-scoped library, durable upload, version listing, latest pointer and delete request state.
- **Dependencies:** DOC-01, DOC-02, DOC-04.
- **Reuse:** document Web domain types only after mapping review.
- **Expected changes / candidate scope:** Document application services/repositories/API, file storage integration and transaction boundaries T1.
- **AC / verification:** AC-01–07, 16–18; isolated API+PostgreSQL+storage tests and concurrent version creation.
- **Risks / blockers:** owner transfer/admin/co-teacher permissions, upload type/size and duplicate semantics unresolved.

## DOC-06 — Core authorization và grants

- **Objective:** class access from Core plus source grant/revoke in Document; enforce current permissions.
- **Dependencies:** DOC-01, DOC-03, DOC-04 và CORE-T03 implementation.
- **Reuse:** CORE-T03 POST authorization/check qua REST; current Core decision logic chỉ reuse phía Core sau adapter, không import internal modules.
- **Expected changes / candidate scope:** Document grant service/routes, CORE-T03 client adapter, action mapping review, audit and lock/race behavior.
- **AC / verification:** AC-23–27, 29–33, 47; outsider, cross-school, revoked, archived, lost assignment, Core timeout and concurrent revoke.
- **Risks / blockers:** Service JWT mismatch, co-teacher/ownership rules, query-versus-response race/stream semantics.

## DOC-07 — Internal file API và RAG scope

- **Objective:** AI can stream a version only for a valid job; expose active document/version/index scope and revocation validation.
- **Dependencies:** DOC-05, DOC-06; AI team confirms DTO.
- **Reuse:** storage adapter, Core permission interface and DOC-D07 streaming rule.
- **Expected changes / candidate scope:** Document internal download/rag-scope/validate endpoints and AI-facing contract.
- **AC / verification:** AC-28–34, 43–47; spoofed job/file/version denied; revoke before retrieval/response denied; checksum preserved.
- **Risks / blockers:** exact safe file claim, actor identity and scope representation are cross-team contracts.

## DOC-08 — Mock AI và AI HTTP client

- **Objective:** let Document exercise accepted async contract without a real model; create bounded client with status mapping.
- **Owner / dependencies:** Technical Lead + AI team; after DOC-03/DOC-04.
- **Reuse:** RAG Python package remains behind AI boundary; do not call internal Python packages from Document.
- **Expected changes / candidate scope:** Document AI adapter/client + deterministic mock service/fixture; AI confirms route and response contract.
- **AC / verification:** AC-08–10, 14–15, 37–38; lost response, duplicate key, conflicting payload, 429, timeout and malformed result.
- **Risks / blockers:** AI endpoint implementation and durable acceptance not present; mocks must be clearly isolated from live.

## DOC-09 — Durable ingestion worker

- **Objective:** store Document job state in PostgreSQL, submit to AI asynchronously and recover after restart.
- **Dependencies:** DOC-05, DOC-07, DOC-08.
- **Reuse:** Core worker operational patterns may inform lifecycle; do not share Core notification/outbox tables.
- **Expected changes / candidate scope:** Document worker/claim/retry scheduler, ingestion_jobs repository, metrics/status updates.
- **AC / verification:** AC-08–15, 35–36, 40–42; restart, lease expiry, 202 lost response, dedup and AI offline.
- **Risks / blockers:** AI job ID/idempotency retention and terminal status semantics.

## DOC-10 — Resilience and fault isolation

- **Objective:** implement approved retry, backoff, adaptive polling, circuit breaker, timeouts, bounded concurrency and fencing.
- **Dependencies:** DOC-09; confirm tuning with actual workload.
- **Reuse:** configuration/metrics conventions from Core but maintain independent Document state.
- **Expected changes / candidate scope:** HTTP client policies, durable scheduling fields and worker lease guard.
- **AC / verification:** AC-09–15, 29–30, 35–42; deterministic failure injection, restart and bounded parallel worker tests.
- **Risks / blockers:** numeric starter values are unbenchmarked; remote operation cannot be assumed cancelled on client timeout.

## DOC-11 — Version activation và deletion

- **Objective:** atomically activate only verified matching version/index; prevent resurrection and handle delete cleanup.
- **Dependencies:** DOC-09, DOC-10 and AI readiness/delete contract.
- **Reuse:** transaction T2/T3; retain old active version while new version is processing/failing.
- **Expected changes / candidate scope:** Document activation/reconcile/deletion orchestration and AI delete client.
- **AC / verification:** AC-16–22, 48; stale result, v2 failure, delete during ingest and cleanup repeatability.
- **Risks / blockers:** DOC-OD-09, CORE-T08 completion, AI deletion contract, retention, hard-delete timing and backup erasure chưa được chốt; giữ irreversible cleanup gated.

## DOC-12 — Cross-service integration, security and fault isolation

- **Objective:** prove Document + Core + mock/AI contract with end-to-end authorization and resilience.
- **Dependencies:** DOC-01–11.
- **Reuse:** Core CI PostgreSQL service and Web proxy tests as patterns; isolated database/storage.
- **Expected changes / candidate scope:** API contract snapshots, integration fixtures, service startup/health wiring and Web live adapter.
- **AC / verification:** all applicable AC-01–42; CI must report skipped cases explicitly; no production DB/data.
- **Risks / blockers:** service auth, route gateway rules, mock/live separation and environment configuration.

## DOC-13 — AI thật và acceptance

- **Objective:** real PDF ingestion, scoped Tutor query, exact-version citation, revoke and deletion evidence.
- **Owner / dependencies:** Technical Lead + AI team; after DOC-12 and deployed compatible services.
- **Reuse:** existing RAG evaluation only as engine-level evidence; add DOC-T06 integrated case fixtures.
- **Expected changes / candidate scope:** release config, approved non-sensitive sample corpus, real AI integration suite and evidence.
- **AC / verification:** AC-43–48, QAS-05/QAS-06 relevant quality gates; pinned model/provider, data provenance, authorization and failure reports.
- **Risks / blockers:** AI runtime/artifacts, cost/resource limits, >=100 labeled QAS-06 dataset and acceptance thresholds are not verified here.

**Quy tắc tiến hành:** Technical Lead review DOC-00 trước DOC-01. Thay đổi owner, thứ tự, AC hoặc candidate scope phải được duyệt; discovery này không tự bắt đầu task.

## Cross-service gates

- CORE-T03 action registry phải thống nhất DOCUMENT_READ/SHARE/MANAGE; Document vẫn là nguồn grant/resource policy.
- LRN-D07/T05 source IDs và LRN-D10 offline snapshot phải tương thích với active version/grant từ Document.
- NTF-T03/T04 event ingestion và account-deletion recipient/completion semantics cần freeze.
- SYS-B06/B07 deletion/index cleanup/retention là dependency của DOC-11; không biến DOC-OD-09 recommendation thành accepted design.
