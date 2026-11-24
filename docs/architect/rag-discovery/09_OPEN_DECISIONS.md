# 09 — Quyết định mở cho Technical Lead

Tất cả đề mục dưới đây đều có trạng thái **PENDING TECHNICAL LEAD REVIEW**. Khuyến nghị của agent là phân tích kỹ thuật, không phải Business Rule hoặc API đã được chấp thuận.

## RAG-OD-01 — Ranh giới AI Service và API public

- **Vấn đề/hiện trạng:** services/rag là Python library, không có HTTP app. Architecture giao hội thoại/Tutor cho AI nhưng services/ai chưa tồn tại.
- **Phương án:** A) AI Service owns public Tutor API, gọi RAG như library; B) thêm standalone RAG service thứ sáu; C) chỉ tiếp tục offline.
- **Ưu/nhược:** A khớp năm-service ADR, nhưng cần AI runtime/DB; B scale độc lập nhưng thêm boundary/auth/vận hành; C an toàn nhưng không có Tutor live.
- **Khuyến nghị của agent:** A; chỉ công bố API sau khi contract được duyệt. Không dùng index/generator làm endpoint riêng.
- **Ảnh hưởng:** Web/API Entry, AI, Core, Document, Learning.
- **Ưu tiên:** P0.
- **Bằng chứng:** ADR-001; ARCHITECTURE ownership; services/rag/README.md; services directory chỉ có core/rag.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-02 — Canonical version và IDP/index adapter

- **Vấn đề/hiện trạng:** idp.canonical phát idp-canonical-1. README/DeepDoc mô tả v2. canonical_harness dùng idp.publish cho v2 nhưng module không được track. Indexing chính nhận TextDocument text/Markdown.
- **Phương án:** A) khôi phục publisher v2 và adapter version-bound; B) chuẩn hóa v1; C) index raw extracted text bỏ qua canonical.
- **Ưu/nhược:** A giữ locators/provenance nếu publisher/test được ship; B giảm scope nhưng có thể thiếu metadata dự kiến; C dễ nhưng citation/source quality yếu.
- **Khuyến nghị của agent:** chọn rõ v1 hay v2; ưu tiên versioned adapter bảo toàn page/block spans. Không ghi v2 là supported cho tới khi publisher hiện diện và có parity test.
- **Ảnh hưởng:** Document ingestion, RAG chunking/index/citations, AI.
- **Ưu tiên:** P0 trước PDF RAG live.
- **Bằng chứng:** idp/canonical.py:21,489-562; retrieval/canonical_harness.py:85-92; indexing/rag_corpus.py:28,73; tools/benchmark_pdf_local.py:25-39.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-03 — Document grant, version, content và revoke

- **Vấn đề/hiện trạng:** services/document không tồn tại. TASK-017 routes là draft. RAG cần source text/version/locators nhưng main index không lưu DocumentVersion ID.
- **Phương án:** A) Document cung cấp active grants và permitted canonical/version content; B) AI đọc Document DB; C) browser gửi chunks/ACL.
- **Ưu/nhược:** A giữ ownership và revoke semantics; B vi phạm service boundary; C cho phép forged context và không thể xác minh.
- **Khuyến nghị của agent:** A; contract service-to-service phải trả version hiện hành, grant đã xác minh và citation locator. Không truy xuất nếu Document không trả quyết định hiện hành.
- **Ảnh hưởng:** Document, AI, Core, Web.
- **Ưu tiên:** P0.
- **Bằng chứng:** BUSINESS_RULES B6/B7; tasks/TASK-017; tasks/TASK-018; rag_corpus.py:28-121.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-04 — Tenant key và authorization provider

- **Vấn đề/hiện trạng:** TextRetriever chỉ nhận callback trả tập allowed child IDs; index không có school_id/class_id/owner_id. Core có use_ai_tutor/read_own_history action nhưng RAG không gọi Core.
- **Phương án:** A) Core access-check + Document grant adapter tạo allowed IDs; B) per-class/per-tenant separate indexes; C) metadata filter làm authorization.
- **Ưu/nhược:** A tránh trùng quyền nhưng cần kiểm tra trước/sau và revoke; B cô lập rõ nhưng tốn bundle/resource; C đơn giản nhưng không đủ quyền.
- **Khuyến nghị của agent:** A là nguồn quyết định; có thể dùng B như lớp cô lập bổ sung. Không coi school/class metadata là quyền.
- **Ảnh hưởng:** Core, Document, AI, RAG indexing/retrieval.
- **Ưu tiên:** P0.
- **Bằng chứng:** Core API_CONTRACT.md internal access; retrieval.py:135-160,480-551; TextRagPipeline.answer:75-120; manifests grants_authorization=false.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-05 — Index storage, activation, update và delete

- **Vấn đề/hiện trạng:** corpus/embeddings là immutable local directories; TextRetriever nạp vectors vào RAM. LocalRagIndex SQLite là evaluation harness. Chưa có active alias, cross-instance store, version activation, revoke invalidation hay production delete.
- **Phương án:** A) immutable artifact bundle per DocumentVersion + AI-owned active-generation pointer; B) managed vector database; C) SQLite/file-only.
- **Ưu/nhược:** A gần code hiện có nhưng cần object store/atomic activation; B có thể scale nhưng thêm công nghệ/cost/migration; C hợp local/dev, không đủ multi-instance.
- **Khuyến nghị của agent:** chốt scale trước; ưu tiên immutable versioned artifacts, active pointer và live-grant checks. Không chọn vector DB khi chưa có yêu cầu.
- **Ảnh hưởng:** Document, AI, storage/operations.
- **Ưu tiên:** P1 trước production corpus.
- **Bằng chứng:** rag_corpus.py:73-145; embedding_store.py:61-115; canonical_harness.py:482-550.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-06 — Model/provider và inference runtime

- **Vấn đề/hiện trạng:** LlamaGenerator chỉ gọi llama.cpp loopback và cần model/server artifact pinned; ONNX/ViMRC cũng nhận local paths. Không có Production provider/artifact/latency/cost.
- **Phương án:** A) self-host local model; B) managed inference API; C) giữ generation disabled.
- **Ưu/nhược:** A kiểm soát data hơn nhưng cần artifact/CPU-GPU/memory; B dễ vận hành hơn nhưng có data egress, key và cost; C an toàn cho tới khi được quyết định nhưng không sinh answer.
- **Khuyến nghị của agent:** giữ adapter provider-neutral, chọn một runtime/artifact có provenance và cost/latency target trước deploy; không gọi external model chưa được duyệt.
- **Ảnh hưởng:** AI, RAG, Cloud Run, Secret Manager.
- **Ưu tiên:** P0 trước Production answer.
- **Bằng chứng:** generation/rag_generation.py:90-190; generation/vi_mrc_reader.py:155-240; requirements-rag-models.lock.txt.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-07 — Conversation persistence và retention

- **Vấn đề/hiện trạng:** AI owns Conversation/Message theo architecture nhưng không có store/schema. H4 cần giữ history hợp lệ sau transfer/archive; OD-02 retention/deletion/backup policy còn pending.
- **Phương án:** A) durable private history với retention/delete policy được duyệt; B) transient session-only messages; C) lưu trong Core DB.
- **Ưu/nhược:** A phù hợp H4 nhưng cần retention/deletion/backup/access review; B không đáp ứng durable history; C vi phạm ownership và tăng PII risk trong Core.
- **Khuyến nghị của agent:** A sau khi Product/Operator chốt thời hạn và deletion trigger; chưa tạo Production chat store trước đó.
- **Ảnh hưởng:** AI, Core identity/access, backup/operations, data requests.
- **Ưu tiên:** P0 trước persistence.
- **Bằng chứng:** BUSINESS_RULES H4/E5/F3; docs/architect/lumi-design/19_Decisions_Gaps.md OD-02; TASK-018.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-08 — D6, Tutor policy và teacher config

- **Vấn đề/hiện trạng:** Learning/D6 API absent. TutorConfig has GD-02 allow_general_knowledge=false and GD-06 hint_reveal_after=3 marked pending; teacher config API and permission action not implemented.
- **Phương án:** A) Learning supplies authoritative active-assessment check; B) Core gains an approved projection/action; C) trust a browser flag/class status.
- **Ưu/nhược:** A respects service ownership; B requires a Core contract change; C stale/forgeable and violates D6.
- **Khuyến nghị của agent:** A; fail closed on missing/unknown assessment state. Keep GD-01..07 defaults unapproved. Teacher config requires current assignment and explicit policy limits.
- **Ảnh hưởng:** Learning, AI, Core, Web.
- **Ưu tiên:** P0 before Tutor enablement.
- **Bằng chứng:** BUSINESS_RULES C4/C6/D6; TASK-018; TASK-019; generation/policy/config.py.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-09 — Streaming, cancellation và idempotency

- **Vấn đề/hiện trạng:** Web TutorPort expects onChunk, AbortSignal, retry and stopStreaming. LlamaGenerator sends stream=false and TextRagPipeline is synchronous. AI durable message idempotency is absent.
- **Phương án:** A) server-side stream and cancellation with turn ID; B) one-shot JSON response and redesign UI; C) fake client-side streaming.
- **Ưu/nhược:** A matches current UI but needs model cancellation and persisted turn state; B is simpler but changes UX; C fabricates progress.
- **Khuyến nghị của agent:** A only if the chosen model can cancel; otherwise change UX/contract before integration. Use a per-turn operation key and do not blindly replay paid generation.
- **Ảnh hưởng:** Web, AI, model runtime, persistence.
- **Ưu tiên:** P1.
- **Bằng chứng:** apps/web/src/lib/data/port.ts:86-99; rag_generation.py:165-190; retrieval/text_pipeline.py:75-120.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-10 — QAS-06 dataset and acceptance

- **Vấn đề/hiện trạng:** QAS-06 requires at least 100 labeled questions including answerable, insufficient, multi-source and unauthorized-source cases. CI uses deterministic fixtures; no accepted Production-model dataset exists.
- **Phương án:** A) label synthetic/rights-cleared sources; B) use approved course materials with answer key and reviewers; C) infer quality from unit tests.
- **Ưu/nhược:** A is reproducible but may not represent school content; B is representative but needs rights/provenance/independent labels; C supplies no quality evidence.
- **Khuyến nghị của agent:** use a rights-cleared, versioned source set with independent labels and report citation, groundedness and refusal separately. Do not claim QAS-06 from CI fixtures.
- **Ảnh hưởng:** Document, AI, RAG, QA.
- **Ưu tiên:** P1 before quality claims/Production use.
- **Bằng chứng:** QUALITY_ATTRIBUTES.md QAS-06; TASK-018; PR #46 benchmark note; CI rag-tests.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.

## RAG-OD-11 — Web gateway and deployment

- **Vấn đề/hiện trạng:** Web API operations target Core only; no AI_API_URL or AI Cloud Run service. RAG has no health/readiness endpoint.
- **Phương án:** A) AI Service behind same-origin Next proxy and private Cloud Run; B) expose AI directly to browsers; C) route AI through Core.
- **Ưu/nhược:** A preserves allowlist and service ownership; B exposes service boundary/credentials; C couples Core to generation and private chat data.
- **Khuyến nghị của agent:** A after decisions 01–10; keep server credentials server-only, add health/readiness, and leave Tutor route unavailable until dependencies verify.
- **Ảnh hưởng:** Web, AI, Cloud Run, Core/Document/Learning.
- **Ưu tiên:** P1 after contract approval.
- **Bằng chứng:** apps/web/src/lib/api/operations.ts; apps/web/src/lib/data/live.ts; Cloud Run service list; Core OpenAPI.
- **Trạng thái:** PENDING TECHNICAL LEAD REVIEW.
