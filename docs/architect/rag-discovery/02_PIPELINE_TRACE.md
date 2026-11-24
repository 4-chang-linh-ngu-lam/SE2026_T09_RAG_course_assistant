# 02 — Pipeline trace từ ingestion đến answer

## Pipeline A — Document ingestion

| Bước | Code thực hiện | Input/output và điều kiện |
|---|---|---|
| 1. Preflight | idp.input.filetypes.detect_file_type / validate_input | Local path; nhận dạng PDF, DOCX, PPTX, XLSX, text, Markdown, HTML, CSV, email, image. Mặc định giới hạn 512 MiB, 5.000 trang, 10M ký tự và pixel budget; chặn tệp rỗng/corrupt và PDF encrypted. Không phải upload API. |
| 2. Chọn lane | idp.ingest.ingest_file | Tệp text-native/Office gọi digital.process. Image gọi _ingest_image/Tesseract. PDF có marker JSON và page image gọi run_ingestion; PDF không có marker gọi parser digital. Nếu PDF không có text layer và OCR fallback không sinh text, trả NEEDS_OCR_ENGINE. |
| 3. Parse/OCR | idp.documents.digital.process, idp.ocr.* | PDF native dùng PyMuPDF/table helpers; OCR/fallback có Tesseract, Marker/Paddle/llama.cpp local workers tùy profile. Nhiều model/server path phải do caller cấu hình. Lỗi có thể tạo page review flags/layout_failed; không tự đảm bảo publish. |
| 4. Chuẩn hóa/structure | idp.documents.normalize, idp.structured.*, idp.canonical.build_canonical | Tạo pages/blocks, bbox, text/Markdown/LaTeX/table, provenance, review flags, question groups. Source ACL/metadata đi vào như caller values, không được xác minh với Document/Core. |
| 5. Quality gate | idp.canonical.audit_canonical | Tính ingestion_pass, quality_pass, review_assisted_pass, production_pass, auto_publish_pass; block/page có thể bị giữ lại nếu thiếu nguồn tin cậy/verification. Đây là parser-quality gate, không phải quyền cấp tài liệu cho lớp. |
| 6. Output | digital.process / run_pipeline | Ghi local page JSON/Markdown, canonical.json, manifest/report/ingestion_report, assets và review_queue.jsonl. Không ghi DocumentVersion vào service DB. |
| 7. Idempotency | DocumentRegistry | SQLite cục bộ: source hash + parser/pipeline/scope fingerprint, canonical path/hash/status. Không phải shared registry hoặc Document-owned version store. |
| 8. Job worker | IngestionWorker | JSON file queue và status files trên filesystem; os.replace để claim; subprocesses, heartbeat, retry/stale recovery, logs. Không HTTP, broker hoặc durable cross-instance queue. |

Digital parser hiện chấp nhận định dạng rộng hơn rule Document MVP; hỗ trợ trong thư viện không chứng minh Document Service/API đã hỗ trợ.

~~~mermaid
flowchart TD
  A[Local file] --> B[File type and limits]
  B --> C{File kind}
  C -->|PDF native| D[PyMuPDF and optional table/OCR fallback]
  C -->|Image| E[Tesseract OCR route]
  C -->|PDF scanned with marker inputs| F[Marker/page-image pipeline]
  C -->|Office/text/Markdown/etc| G[Digital parser]
  D --> H[Canonical v1 and audit]
  E --> H
  F --> H
  G --> H
  H --> I[Local page/canonical/report files]
  I -. no production adapter .-> J[TextDocument/chunk index]
~~~

## Pipeline B — Query & answer

1. Request validation and plan: SearchRequest carries query, up to three facets, context_hint, optional hard scope_source_ids and focus_source_ids. make_plan NFC-normalizes text and derives deterministic anchors/facets; simple comparisons can become several queries. It does not semantically rewrite ordinary queries.
2. Optional query planner: GeneratorMultiHopPlanner is injected and off by default. When enabled, cheap cues gate it; output is constrained to direct/rewrite/decompose and at most two subqueries. It never supplies evidence or answer text; on planner failure RagPipeline falls back to direct retrieval.
3. Authorization snapshot: TextRetriever.retrieve requires a caller-provided callback returning a set of known child IDs. It intersects that set with retrieval-eligible chunks and optional source_ids. Invalid/missing callback denies. RAG does not call Core or Document itself.
4. Candidate retrieval: default arms are dense + lexical + structure + section; dense computes normalized vector dot products in memory, lexical is fielded BM25 over body/title/path, structure detects exercise anchors, section groups source sections. Optional accent fallback, lexical probes, lexical bridge and facet comparison are bounded by RetrievalConfig.
5. Fusion/rerank: RRF by default; relative-score option. Optional ONNX cross-encoder/passage rank reorders a bounded head. Reranker failures can fall back to fusion and are marked in trace; scores are ordering signals, not probabilities.
6. Packing: context expansion uses authorized child/parent dependencies, token budget and whole-record fitting. Output includes selected evidence records and source spans. It never grants access.
7. Generation: GroundedTaskPipeline packs messages, applies output schema, calls the injected generator, parses/validates, runs configured verifiers, retries bounded attempts with derived seed, records hash-based provenance. StepSession and quiz drafts are in-memory Python objects here; persistence is not implemented.
8. Citation validation: source_quotes selects exact source snippets, restricts model citations to evidence IDs/quote enums and maps quotes back to source spans. This validates citation shape/location, not necessarily semantic entailment.
9. Final authorization: TextRagPipeline and RagPipeline re-run the callback and discard results if the allowed child-ID snapshot changed during query/generation.

~~~mermaid
flowchart LR
  Q[SearchRequest] --> P[Deterministic plan]
  P --> H{Optional multi-hop planner}
  H --> D[Dense + BM25 + structure/section]
  D --> F[Fusion]
  F --> R{Optional reranker}
  R --> C[Authorized context packing]
  C --> G[Injected generator or MRC reader]
  G --> V[Schema/claim/citation checks]
  V --> Z[Python result object]
  A[Caller authorization callback] --> D
  A --> Z
~~~

## Step-level conditions and limitations

- Embedding query vectors are cached only within one retrieval call; lexical snapshots are in-process LRU (max four authorized row sets).
- Retrieval soft_deadline_ms is a soft budget; trace explicitly states it is not a hard timeout. Reranking may skip after deadline, but retrieval itself can continue.
- Dense, BM25, structure and section arms are deterministic code. Model decisions occur only in the optional injected multi-hop planner, reranker/MRC/answer generator.
- Streaming is not implemented by LlamaGenerator: it sends stream=false and reads the full response. Stop/cancellation exists only in the separate IDP worker and is not a Tutor query API.
- Retrieval can run without generation through TextRetriever; TextRagPipeline couples it to grounded generation. IDP can run without chunking/indexing. No public service composes the full path.
- Call bounds: retrieval recovery runs at most two passes by default; multi-hop planner is optional, gates on follow-up/composite/context cues and permits at most two extra queries; TaskSpec max_attempts defaults to 1 and is bounded to 1–5; the source-quotes task uses one attempt by default. Optional verifier/MRC recovery can add calls. These are local pipeline bounds, not a service-wide request/concurrency budget.
