# 04 — Models, dependencies and storage

## Model/runtime inventory

| Stage | Implementation in source | Artifact/provider | Evidence/status |
|---|---|---|---|
| Native PDF/layout | PyMuPDF, pdfplumber/table helpers, python-docx/openpyxl/python-pptx | Local libraries and optional subprocess | IMPLEMENTED offline; not a Document Service. |
| OCR | Tesseract fallback; Marker/PaddleOCR/PaddleX paths; optional PaddleOCR-VL/llama.cpp local workers | System binaries, language data, model directories and loopback servers | PARTIAL/profile-dependent; caller supplies model paths/runtime. |
| Dense embedding | OnnxBgeM3, BAAI/bge-m3 ONNX, 1024-dimensional CLS/L2 | Local ONNX and tokenizer paths with repo/revision/variant and SHA provenance | IMPLEMENTED adapter; no downloader or production artifact. |
| Alternate embedding | OnnxE5, 384-dimensional masked-mean/L2 | Local ONNX/tokenizer paths | Evaluation adapter, CPUExecutionProvider. |
| Reranking | OnnxCrossEncoder, optional BGE multi-vector MaxSim | Local ONNX/tokenizer/projection files; cross-encoder requires artifact provenance | Optional; not default in every configuration; raw logits are not calibrated probabilities. |
| LLM generation | LlamaGenerator calls llama.cpp-compatible /props, /tokenize, /apply-template and /v1/chat/completions on an explicit loopback origin | Local model file and server executable with SHA/provenance | No hosted provider; no model/server artifact deployed or measured. Request sets stream=false. |
| Extractive reader | ViMrcReader, Transformers QA model and optional adapted head | Local-only model directory and optional head; local_files_only=True | Opt-in experimental/non-commercial path; no model artifact in repo. |
| Query planner | GeneratorMultiHopPlanner over an injected generator; default disabled | Same generator supplied by caller | IMPLEMENTED optional helper, not an independent provider. |

The code records model/config identities to prevent silent artifact/index drift. It does not select, download, promote or deploy production models. requirements-rag-models.lock.txt provides tokenizer/Hugging Face support dependencies; it does not contain the actual ONNX/GGUF/Transformers artifacts.

## Dependency sets

- requirements-test.txt pins pytest, jsonschema, numpy, opencv-python-headless, Pillow and PyMuPDF for CI tests.
- requirements-phase0.lock.txt pins OCR/PDF/native processing, ONNX Runtime, image, Office and parser dependencies for local phase 0.
- requirements-rag-models.lock.txt pins tokenizers/Hugging Face support libraries; model files remain externally supplied.
- Optional model Dockerfiles install large Marker/Paddle/Torch stacks. They are experimental stages, not an AI Service image.
- RAG requirements do not define FastAPI, an API runtime, SQLAlchemy, a production DB client, or a vector database.

## Storage observed in code

| Data | Current location | Behavior |
|---|---|---|
| IDP pages/canonical/assets/reports | Caller-selected local output directory | JSON/Markdown/images/review queue; not uploaded to Document storage. |
| Ingestion idempotency | DocumentRegistry SQLite WAL | Source hash + parser/pipeline/scope fingerprint, canonical path/hash/status; local file. |
| Main text corpus | Filesystem directory | sources.json, bundles.json, immutable embedding generation. Build requires new/empty directory; no active alias, transaction over generations, remote object store, or version activation. |
| Dense index | vectors.npy + rows.jsonl + profile/manifest | Loaded wholly into process memory by TextRetriever; checksum/profile checked. |
| Sparse BM25 | Constructed in process from authorized child subset | LRU cache of at most four child-ID sets; not persisted as a service index. |
| Canonical evaluation harness | Local SQLite chunks table | LocalRagIndex in retrieval/canonical_harness.py; not the primary retrieval backend or Production storage. |
| Chat/conversation state | None | No AI database, schema, migration, retention or deletion executor. |
| Queue/status | Local JSON files and directories | IngestionWorker queue; not a distributed/cloud queue. |

Both embedding and corpus manifests explicitly state grants_authorization=false. A valid index artifact is not proof that a caller can read its sources.

## Resource and packaging limits

- ONNX adapters force CPUExecutionProvider and expose thread/batch settings; ViMrcReader can accept CUDA but needs a separate artifact and working CUDA runtime.
- Retrieval defaults include a 10-second soft deadline, explicitly not a hard timeout. LlamaGenerator default request timeout is 180 seconds and caps at 600 seconds.
- No Production latency, memory, concurrency, cost, GPU offload or autoscaling measurement is available.
- Dockerfile.phase0 copies a missing parser directory; Dockerfile.phase4-models references a missing OCR backend worker file; Dockerfile.phase5 references a local phase4 image and missing colab directory, and copies tools twice. These Dockerfiles are not built by current Core CI.
