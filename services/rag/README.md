# Local text RAG & Adaptive Hybrid IDP

`build_corpus` creates a versioned bundle of source text, validated chunks and embeddings. `load_retriever` loads that bundle. `TextRetriever.retrieve` builds its candidate set from a required callback supplying current authorized child IDs, checks the set again before returning and packs source-bound context under a token budget. The caller owns permission checks for the actor and documents.

Run the test suite from `services/rag` on Windows:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Use `rag.*` imports for the text RAG library with `services` on `PYTHONPATH`. Existing IDP scripts and downstream services use Canonical v1 (`idp-canonical-1`) via `idp.ingest.ingest_file` and `retrieval.canonical_harness` from `services/rag`.

## Unified Adaptive Hybrid IDP

`idp` runs a single unified **Native-first, CPU-first, GPU-on-demand** parsing pipeline coordinated by `AdaptiveHybridOrchestrator` behind the public entry point `idp.ingest.ingest_file()`:

| Level | Stage | Technology | Device |
|---|---|---|---|
| L0 | Profiling & Native Parsing | PyMuPDF (`PDF`), Pandoc (`DOCX`/OMML), Python/openpyxl/python-pptx (`Office`/`TXT`) | CPU |
| L1 | Fast Text OCR | Tesseract + OpenCV preprocessing (`deskew`/`CLAHE`) | CPU |
| L2 | Layout & Grid Structure | `PP-DocLayoutV3` (`paddleocr.LayoutDetection`), OpenCV ruled-table/panel detection | CPU/GPU |
| L3 | Selective VLM Recognition | `PaddleOCR-VL 1.6 GGUF` via loopback `llama.cpp` server | GPU (on-demand) |
| L4 | Verification & Publish Gate | Cross-read agreement (`cross_read.py`), Canonical v1 builder, fail-closed `audit_canonical` | CPU |

### Routing & Optimization

- **Page-level router (`idp/pipeline/page_router.py`)**: Profiles PDF pages before rendering (`idp/input/profiler.py`) into `SKIP_BLANK`, `NATIVE_PURE`, `NATIVE_ADAPTIVE`, `SCAN_FAST_OCR`, or `SCAN_LAYOUT_HYBRID`.
- **Region-level router (`idp/pipeline/region_router.py`)**: Exits early on CPU for clean native/high-confidence blocks (`>= 0.85`), tries OpenCV+Tesseract (`GridTableReader`) on ruled tables first, and escalates only formulas, irregular tables, garbled spans, and low-confidence text regions to the bounded GPU queue (`idp/pipeline/scheduler.py`).
- **Render-once & streaming**: `PageRenderCache` renders PDF pages lazily on demand, shares crops across steps, and evicts per-batch PIL images between streaming batches. Warm models (`ModelPool`) and SQLite fingerprint caching (`DocumentRegistry`) avoid repeated loads.

### Directory Layout

```
idp/
├── ingest.py              # Single public entry point (ingest_file & CLI)
├── config.py              # PIPELINE_VERSION, profiles (general/math_vi/auto), budgets
├── input/                 # validation.py, profiler.py, filetypes.py (shim)
├── pipeline/              # orchestrator.py, page_router.py, region_router.py, scheduler.py, cache.py
├── backends/              # native/{pdf,docx,office}.py, text_ocr.py, layout.py, vision_ocr.py
├── processing/            # render.py, preprocess.py, reading_order.py, formula.py, table.py, figure.py
├── evidence/              # cross_read.py, recovery.py, fusion.py
├── canonical/             # schema.py, builder.py, questions.py
└── validation/            # quality_gate.py, review.py
```

### CLI & Benchmark

Ingest a document:

```powershell
.venv\Scripts\python.exe -m idp.ingest source.pdf -o out_dir --profile auto --vlm-mode selective
```

With local or SSH-tunneled `PP-DocLayoutV3` (`127.0.0.1:8112`) and loopback `llama-server` (`paddleocr-vl-1.6` on `127.0.0.1:8111`):

```powershell
.venv\Scripts\python.exe -m idp.ingest source.pdf -o out_dir --layout-url http://127.0.0.1:8112 --layout-revision pp-doclayoutv3-1 --vl-ocr-url http://127.0.0.1:8111 --vl-ocr-revision r1
```

Verify remote GPU tunnel health, token `logprobs`, layout boxes, and `paddleocr_vl_gguf` Canonical output:

```powershell
.venv\Scripts\python.exe -m idp.verify_remote
```

Run the local benchmark across `tests/fixtures/generated/`:

```powershell
.venv\Scripts\python.exe -m tools.benchmark_idp
```

## Retrieval, Orthography, Quotes & Performance

- `LocalRagIndex.index(canonical, trusted_parsers=NATIVE_TRUSTED_PARSERS)` indexes approved non-held Canonical v1 blocks while preserving source provenance and access checks (`retrieve(..., actor=..., access_check=...)`).
- Publish decisions are stamped into `canonical.json` (`publish_decision`, per-block `held` and `hold_reasons`) so retrieval holds unverified regions while preserving them for human review in `review_queue.jsonl`.
- **Vietnamese orthography & lexical search**:
  - `FieldedBM25` (`search/retrieval_lexical.py`) indexes body bigrams alongside title/path fields and applies collision-free **Layer A** normalization (`normalize_vi_orthography`: NFD syllable tone canonicalization + `_IY_MAP`, `@lru_cache(8192)`) to lexical and section terms without altering `retrieval_plan.terms()` or `accent_fold()`.
  - **Layer B** (`RetrievalConfig(lexical_folded_boost=...)`) is opt-in and defaults to `0.0` (validated in `[0, 1]`). `RetrievalConfig(accent_fallback=True)` continues to support accent-folded queries while preserving accented quotes and offsets.
  - A dotted label such as `1.2.` starts a unit in a recognized practice section; reranker `max_tokens` scales up to `8192`.
- **Chunking (`idp-text-chunking-10`)**: keeps display formulas and code inside their logical parent (one atom per formula), makes `Định nghĩa`/`Định lý`/`Chú ý`/`Bảng N.`… units (numbered ones are query anchors), isolates unclosed formulas and unclosed code fences, avoids tiny paragraph-snap fragmentation, and packs oversized formulas/tables beside their seed (`context_eligible`). Older corpora must be rebuilt; see [chunking](chunking/README.md).
- **Quote extraction & generation**:
  - `citations/source_quotes.py` preserves semicolons inside parentheses (`skip_paren_semicolon=True`) so math coordinates such as `(x; y)` are not split mid-sentence, validates record spans once per item (`_validate_record_spans`), and resolves snippet spans in O(1) via `_span_covers_range`.
  - `generation/openai_compatible.py` provides `OpenAICompatibleGenerator` with persistent `httpx.Client` keep-alive connection pooling (`follow_redirects=False`, `close()`) and safe multiline quote snapping (`len(q_norm) >= 16` with `>= 75%` snippet coverage).
  - `TextRagPipeline(retriever, GroundedTaskPipeline(generator))` composes retrieval, prompt budgeting, source quote validation, and provenance.
- **Performance & Update Comparison**: `TextRetriever` caches per-child `_search_text_tokens` at load time so `packing/neighbor_context.py` uses exact-safe additive token bounds for `local_huggingface_tokenizer`, eliminating redundant 2048-token BPE passes without changing `items` or `budget_count`. See [docs/deepdoc/rag-update-comparison.md](../../docs/deepdoc/rag-update-comparison.md) for measured before/after benchmarks.
