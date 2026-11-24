# 01 — Kiến trúc RAG hiện trạng

## Phạm vi và nguồn

Khảo sát dựa trên mã nguồn tại HEAD dc0671c36bf750ef914ac34d22e6ff2cf685287a. Trong services/rag có 218 file được Git theo dõi, gồm 183 file Python. Toàn bộ file Python được AST-parse tĩnh; entrypoint và module sở hữu pipeline được truy vết thủ công.

services/ hiện chỉ có core/ và rag/. Không có services/ai/, services/document/ hoặc services/learning/. Ngoài services/rag, DeepDoc chỉ có tài liệu trong docs/deepdoc/README.md và relocation-manifest; không có parser runtime độc lập ngoài RAG. tools/idp/, services/rag/parser/, services/rag/colab/ và services/rag/idp/publish.py không tồn tại trong Git tree.

## Cây module và trách nhiệm

    services/rag/
      idp/
        input/           nhận dạng, giới hạn và preflight tệp
        documents/       parser native PDF/Office/TXT/MD/CSV/HTML/email
        ocr/             Tesseract, Marker/Paddle/llama.cpp và OCR fallback
        structured/      bảng, công thức, hình, vùng câu hỏi, tái kiểm chứng
        validation/      canonical/output audit và review flags
        orchestration/   pipeline, CLI, worker và SQLite registry cục bộ
        evidence/        provenance/evidence contracts dùng trong native parser
        pdf/native/      parser text/layout/table/math đã relocation từ prototype
        canonical.py     xuất/audit Canonical hiện tại
      chunking/          text source -> hierarchy/parents/children có source spans
      embedding/         ONNX BGE-M3/E5 local adapters và tokenizer
      indexing/          TextDocument -> chunks + immutable file bundle/vectors
      search/            lexical BM25, fusion, reranking, planning, probes/bridges
      retrieval/         TextRetriever, multi-hop, canonical evaluation harness
      packing/           evidence/context packing theo token budget
      generation/        task pipeline, local generator adapter, QA/quiz policies
      citations/         quote/source span mapping và verification
      contracts/         package reserved for promoted cross-stage contracts
      tests/             unit, golden, parser, OCR, retrieval/generation integration
      tools/             local PDF benchmark/native spike

## Pipeline boundaries

~~~mermaid
flowchart LR
  F[Local file path] --> P[IDP preflight and parser]
  P --> C[Canonical output and review report]
  C -. adapter gap .-> T[TextDocument or canonical harness]
  T --> CH[Chunking]
  CH --> E[ONNX embedding]
  E --> IDX[Local immutable files]
  IDX --> R[TextRetriever]
  A[Caller authorization callback] --> R
  R --> PK[Evidence packing]
  PK --> G[Injected generator or MRC reader]
  G --> CV[Schema and citation validation]
  CV --> O[Python result object]
  CORE[Core access API] -. no client wired .-> A
  DOC[Document grants/content API] -. no service .-> A
  LEARN[Learning D6 status] -. no service .-> G
~~~

RAG packages are stages of one Python subsystem, not separate network services. README says the top-level pipeline is composition only and introduces no endpoint. No FastAPI/APIRouter route was found under services/rag.

## Entry points

| Entry point | Kind | Input/output |
|---|---|---|
| idp.ingest.ingest_file / python -m idp.ingest | Python + CLI | Local file path and output directory; returns local report/canonical. |
| idp.orchestration.pipeline.run_ingestion | Python | PDF plus precomputed page images/Marker JSON; local output directory. |
| idp.orchestration.worker.IngestionWorker | Local filesystem worker | JSON job files in incoming/running/done/failed dirs; status/result JSON and batch logs. |
| idp.orchestration.batch / idp.orchestration.cli | CLI/subprocess | Page-batch OCR/Marker orchestration. |
| chunking.chunk_text | Python + CLI | Plain text/Markdown and tokenizer; returns chunk bundle. |
| indexing.build_corpus / load_index_bundle | Python | TextDocument list and new/empty directory; immutable local corpus files. |
| retrieval.TextRetriever.retrieve | Python callable | SearchRequest and required authorize callback; retrieval result. |
| pipeline.RagPipeline.answer / retrieval.TextRagPipeline.answer | Python callable | Query and required authorize callback; answer/citations/provenance. |
| tools/benchmark_pdf_local.py | Local evaluation CLI | External/local PDF and artifacts; not a runtime service. |

No RAG query HTTP endpoint, health/readiness route, upload endpoint, or API worker is implemented.

## Module dependency map

- IDP imports local parsers/OCR/structure/validation. It stops at Canonical JSON and review artifacts; it explicitly rejects non-ingestion mode and directs chunking downstream.
- chunking is text-focused and independent of OCR. It emits source-position spans, section paths and retrieval eligibility.
- indexing imports chunking and an encoder interface. It writes source text, chunk bundles, embedding vectors and checksum manifests.
- retrieval loads an immutable bundle and matching encoder identity. It builds lexical BM25 in memory and optionally calls a reranker.
- packing operates on retrieved evidence and a caller-supplied token counter. It retains whole-source spans while fitting the context budget.
- generation uses TaskSpec, a generator-shaped interface, schema validators and optional verifiers. It does not own source authorization.
- citations converts exact evidence quotes to source spans; it requires evidence records to already contain source IDs and source spans.

Tightly coupled components include TextRetriever and exact chunk/index/encoder identity; RagPipeline and retriever/generator token-counter identity; TextRagPipeline and retrieved-record/source-quote contract.

## Prototypes and external sources

- LocalRagIndex in retrieval/canonical_harness.py is explicitly a local evaluation harness using SQLite and BM25, not an AI Service or production permission provider.
- DeepDoc phase1 relocation manifest records upstream parser source hashes. Original parser/ directory is absent; current code is under services/rag/idp/pdf/native.
- README references a Canonical v2 publisher at idp.publish, but no idp/publish.py is tracked. Canonical v2 handling in the harness is conditional on that absent module.
- services/rag/README.md:97 links docs/architect/ai/RAG_PIPELINE_PROPOSAL.md, absent on main.
- services/rag/README.md:97 links docs/architect/ai/RAG_PIPELINE_PROPOSAL.md, which is absent on main.
- Dockerfile.phase0 copies a missing parser/ directory. Dockerfile.phase4-models references a missing backend worker file; Dockerfile.phase5 references a local phase4 image and missing colab/ directory, and copies tools twice. None of these Dockerfiles are built by Core CI.

Evidence: services/rag/README.md:19-42, 91-97; services/rag/pipeline.py:1-4; services/rag/idp/canonical.py:21, 489-562; retrieval/canonical_harness.py:1-5, 85-92; Dockerfile.phase0:8-9; Dockerfile.phase4-models:10; Dockerfile.phase5:2, 10-11.
