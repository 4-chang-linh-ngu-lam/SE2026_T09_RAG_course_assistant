# DOC-00.9 — Blockers và quyết định còn mở

**Trạng thái tài liệu:** DOC-00-R1 — PENDING TECHNICAL LEAD APPROVAL. Recommendations dưới đây không phải quyết định được phê duyệt.

## 1. Các quyết định đã ACCEPTED

| Quyết định | Nội dung chấp thuận | Điều chưa được chấp thuận |
|---|---|---|
| RAG-D01 | Giữ 5 service; RAG là library của AI; Document sở hữu source/version/grant/job; AI sở hữu pipeline/index/conversation | API, schema, runtime và giao thức cụ thể |
| RAG-D02 | DEFERRED cho nhóm AI/RAG | Không lựa chọn Canonical v1/v2 hoặc thay engine |
| DOC-D01 | Document quản lý; AI xử lý nội dung | Giao thức/ownership adapter chi tiết |
| DOC-D02 | REST bất đồng bộ, 202 sau durable acceptance; không thêm broker trong Increment 1 | Endpoint/schema/retry/client |
| DOC-D03 | Backend polling, không phụ thuộc browser | Chu kỳ/scheduler cụ thể |
| DOC-D04 | Tách Document, DocumentVersion, IngestionJob lifecycle | Enum/schema hoàn chỉnh và retention |
| DOC-D05 | Giữ active version cũ khi mới processing/fail; activate khi đúng index sẵn sàng | Exact readiness/deletion/rollback contract |
| DOC-D06 | Core + Document xác minh quyền hiện hành; fail closed | JWT, DTO, race/stream semantics |
| DOC-D07 | Internal streaming API + storage abstraction; Volume riêng trong Increment 1 | Size, credential, endpoint, backup/encryption |
| DOC-T01/T02 | Database riêng từng service; bốn bảng Document và các constraints/transaction | DDL implementation và reconciliation details |
| DOC-T03/T04 | Public Document API route groups; internal REST + Service JWT | DTO/OpenAPI/claims/AI compatibility |
| DOC-T05/T06/T07 | Resilience policy, 48 AC và roadmap 14 task | Tuning, AC evidence, detailed CI/deployment |

Nguồn chuẩn sau pull: docs/architect/rag-design/00_DESIGN_STATUS.md và docs/architect/system-integration/00_DESIGN_STATUS.md tại HEAD c7f56c722f421bf1df17f5a82f26a78682eb82be.

## 2. Blockers cần nhóm AI/RAG xác nhận

| ID / priority | Blocker và bằng chứng | Lựa chọn cần chốt | Recommendation để review | Trạng thái |
|---|---|---|---|---|
| AI-01 / P0 | Không có services/ai hoặc HTTP API; RAG README chỉ mô tả offline library. | AI Service public/internal routes và deployment boundary. | AI sở hữu service/API, dùng RAG như library theo RAG-D01; không thêm service RAG thứ sáu. | PENDING TECHNICAL LEAD / AI TEAM |
| AI-02 / P0 | DOC-T04 AI job submit/status/delete/readiness chưa có implementation. | Durable acceptance, remote job IDs, status/result schema và idempotency retention. | REST 202 chỉ sau persist; cùng key replay; payload khác 409; confirm AI compatibility trước DOC-08/09. | PENDING |
| AI-03 / P0 | DOC-D07 file handoff chưa có endpoint, RAG không đọc Document service. | Job-bound stream, checksum, max bytes, file type metadata, temporary-file cleanup. | Chỉ tải version cụ thể qua authenticated Document internal API; không share path/Base64. | PENDING |
| AI-04 / P0 | RAG retrieval chỉ nhận callback; Document scope API thiếu. | Authorized source/version set, revalidation trước response, stale index behavior. | Core check + Document active grant/version; fail closed. Không tin index ACL metadata. | PENDING |
| AI-05 / P1 | Current canonical-1; idp.publish v2 adapter absent; RAG-D02 deferred. | Engine-side canonical/version adapter và locator fields. | AI team tự quyết định engine internals; Technical Lead chỉ thống nhất DTO tối thiểu liên service. | DEFERRED / CONTRACT PENDING |
| AI-06 / P1 | Không có production index deletion/readiness API. | Index readiness, exact index_ref/version binding, async deletion and retry. | index_ready phải chứng minh đúng version/index ref có thể query; delete stale work chống resurrection. | PENDING |
| AI-07 / P1 | Không có model/runtime/provider deployment hoặc real AI test evidence. | Runtime, model provenance, health/readiness and resource budget. | AI team cung cấp test contract trước; DOC-13 mới nghiệm thu runtime thật. | PENDING |

## 3. Blockers nội bộ Core/Document/Web

### DOC-OD-01 — Document adoption Service JWT dùng chung

- **Evidence:** SYS-02/CORE-T04 chốt foundation Service JWT cấp hệ thống; implementation Core hiện vẫn X-Service-Key.
- **Options:** A) Document dùng shared verifier/identity; B) Document tự cấp token/key riêng.
- **Trade-off:** A giữ một trust model; B tạo cơ chế/key lifecycle trùng lặp.
- **Recommendation:** A; không tạo issuer/key/auth service trong Document.
- **Priority/status:** P0, SYS-02 implementation pending.

### DOC-OD-02 — Upload type/size/quarantine

- **Evidence:** FRS liệt kê PDF/PPTX/DOCX/TXT/Markdown; DOC-T03 nêu 50 MB/5 formats là đề xuất chưa chốt; RAG parser nhận thêm nhiều format và giới hạn 512 MiB.
- **Options:** A) giữ 5 formats và duyệt size mới; B) mở rộng định dạng theo năng lực AI; C) API nhận policy capability từ config.
- **Trade-off:** A ít bề mặt tấn công; B tăng parser/support burden; C linh hoạt nhưng phải version contract.
- **Recommendation:** bắt đầu từ allowlist 5 formats, chọn size/quarantine sau review threat/resource limits; server sniff nội dung và không tin extension.
- **Priority/status:** P0, PENDING TECHNICAL LEAD + AI.

### DOC-OD-03 — Error/correlation convention

- **Evidence:** Core error contract dùng correlation_id/X-Correlation-ID; DOC-T03 ghi request_id.
- **Options:** A) thống nhất correlation_id để reuse Core; B) đổi toàn hệ sang request_id; C) hỗ trợ alias có thời gian migration.
- **Trade-off:** A tương thích Core; B thống nhất tên mới nhưng cần thay Web/proxy; C tăng complexity.
- **Recommendation:** dùng một canonical response field/header và mapping tại boundary; chọn tên tại API review trước OpenAPI.
- **Priority/status:** P1, PENDING.

### DOC-OD-04 — Storage durability và cleanup

- **Evidence:** DOC-D07 chọn Docker Volume cho Increment 1; compose hiện không có Document volume/file store.
- **Options:** A) volume local/Compose; B) object storage ngay; C) abstraction với volume adapter trước.
- **Trade-off:** A đơn giản nhưng giới hạn replica/backup; B vận hành phù hợp scale nhưng cần cost/security; C đáp ứng decision và giảm coupling nhưng vẫn cần volume ops.
- **Recommendation:** C/A theo DOC-D07; yêu cầu backup, restore, disk quota, encryption, temp file and orphan cleanup runbook trước deployment.
- **Priority/status:** P1, PENDING.

### DOC-OD-05 — Retention, old versions và deletion

- **Evidence:** lumi-design/19_Decisions_Gaps.md OD-02 retention pending; DOC-T03 delete 202 nhưng thời gian cleanup/retention chưa chốt.
- **Options:** A) soft-delete/tombstone đến khi policy duyệt; B) hard-delete theo retention được phê duyệt; C) giữ mọi version indefinitely.
- **Trade-off:** A bảo vệ khỏi xóa quá sớm nhưng cần storage; B đáp ứng policy nhưng destructive; C giữ lịch sử nhưng tăng privacy/cost risk.
- **Recommendation:** triển khai chặn truy cập + trạng thái DELETING trước; không permanent delete/backup purge cho tới khi có policy và proof.
- **Priority/status:** P0 trước DOC-11 destructive cleanup, PENDING.

### DOC-OD-06 — Roles, owner transfer và class assignment

- **Evidence:** FRS có PRIMARY/ASSISTING và owner; DOC-T03 ghi admin/co-teacher/transfer còn review; Core API có class roles nhưng chưa có Document grants.
- **Options:** A) chỉ source owner và assigned teacher; B) mở rộng school admin/co-teacher theo O1; C) thêm owner transfer workflow.
- **Trade-off:** A nhỏ hơn nhưng có thể thiếu nghiệp vụ; B cần kiểm soát cross-school/mutation; C cần audit và orphan policy.
- **Recommendation:** giữ đúng BUSINESS_RULES + DOC-D06, phê duyệt ma trận role/action trước endpoint implementation.
- **Priority/status:** P0, PENDING.

### DOC-OD-07 — Polling/retry/lease tuning

- **Evidence:** DOC-T05 đưa giá trị khởi đầu nhưng nói rõ chưa benchmark; chưa có worker.
- **Options:** A) dùng starter defaults có config; B) chạy workload benchmark trước khi khóa; C) callback/hybrid sau Increment 1.
- **Trade-off:** A giúp bắt đầu; B chính xác hơn nhưng cần runtime; C giảm polling nhưng tăng event complexity.
- **Recommendation:** bắt đầu A chỉ cho dev/CI, đo trước staging acceptance; giữ polling server-to-server theo DOC-D03.
- **Priority/status:** P1, PENDING.

### DOC-OD-08 — Web API enablement và error behavior

- **Evidence:** Web Document live methods trả 503, operations allowlist Core-only; routes/mocks không phải API integration.
- **Options:** A) bật data adapter sau contract + API tests; B) giữ hidden/disabled trong live; C) trỏ UI vào mock trong production.
- **Trade-off:** A cho phép tích hợp có kiểm soát; B hạn chế nhưng trung thực; C tạo fake persistence/false success và trái frontend AGENTS.
- **Recommendation:** A sau DOC-12 prerequisites; giữ live fail-closed/disabled cho tới khi có service.
- **Priority/status:** P0 trước demo/production, PENDING.

## 4. Phê duyệt cần trước DOC-01

1. Technical Lead chấp thuận kết quả DOC-00 và xác nhận roadmap DOC-01–13.
2. Xác nhận boundary ownership Core/Document/AI và không thay đổi RAG-D02.
3. Chốt SYS-02/CORE-T04 foundation, CORE-T03 action mapping và AI-01..06 cross-team contracts.
4. Chốt upload format/size/quarantine và Document storage operational prerequisites.
5. Chốt API error/correlation naming và role-action matrix.
6. Xác định retention/deletion gate; destructive cleanup phải chờ policy.

**Không có quyết định nào ở mục 3 được xem là ACCEPTED chỉ vì đã có recommendation.** Dừng tại DOC-00 cho tới khi Technical Lead review.

### DOC-OD-09 — Durable deletion, retries và physical cleanup

- **Evidence:** DOC-T02 bốn bảng chưa định nghĩa deletion job; CORE-T06/T08 có per-target deletion event/completion; SYS-B06/B07 nêu durable cleanup, index identity, stale fencing và retention; Notification ACK không đồng nghĩa completion.
- **Options:** A) Document state + durable inbox/reconciliation; B) Document-local deletion job/outbox record; C) workflow store dùng chung. B làm rõ retries/per-target work nhưng thay đổi schema được duyệt; C tăng ownership/dependency.
- **Recommendation:** revoke/DELETING ngay và track bền vững việc Document-owned source/grants; phối hợp AI cho derived index; ACK khác completion. Chưa chọn persistence schema hay API trong R1.
- **Cần chốt:** retry/idempotency/lease/dead-letter; AI deletion job/status and version/index identity; Core per-target completion; Notification/event recipient; physical source/temp/index cleanup; backup erasure; retention 14 ngày áp dụng cho dữ liệu nào.
- **Status:** OPEN, P0 trước DOC-11/account-deletion acceptance; không tạo migration hoặc hard-purge trước approval.

## 5. MIP và design baseline mới

CORE-D/T, LRN-D/T, NTF-D/T và SYS-D/T mới nhất được ghi ACCEPTED ở mức thiết kế. SYS-02 là shared Service JWT; CORE-T03 là authorization API; LRN-D07/T05 phụ thuộc source IDs; NTF durable event ACK khác delivery/completion; SYS Master Plan xác định DOC-01–08 Phase 2, DOC-09–13 Phase 3 và system acceptance ở Phase 5. Implementation vẫn chưa xác minh.
