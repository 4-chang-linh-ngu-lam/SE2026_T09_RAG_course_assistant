# Local text RAG

`build_corpus` creates a versioned bundle of source text, validated chunks and embeddings. `load_retriever` loads that bundle. `TextRetriever.retrieve` builds its candidate set from a required callback supplying current authorized child IDs, checks the set again before returning and packs source-bound context under a token budget. The caller owns permission checks for the actor and documents.

Run the test suite from `services/rag` on Windows.

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Use `rag.*` imports for the text RAG library with `services` on `PYTHONPATH`. When calling the Canonical v2 harness, also include `services/rag` for its existing `idp` dependency. Pytest sets both paths. Existing IDP scripts can continue to use `retrieval.canonical_harness` from the service root. Keep library callers within one import style to avoid mixing separate Python class identities.

### Restored IDP and Canonical v1

The local SQLite harness also accepts Canonical v1 from `idp.ingest`. It
recomputes the legacy IDP audit and indexes only pages marked for automatic
publication. For an operator-selected native PDF reader, pass the same explicit
`trusted_parsers=("pymupdf",)` to `LocalRagIndex.index` and `resolve_citation`.
Retrieval still requires the caller's current-access callback. Legacy citations
resolve to the original block text, page and bounding box. Unified L1 evidence
identities are unavailable for these artifacts.

From `services/rag`, run the native local smoke benchmark with
`python -m tools.benchmark_pdf_local --pdf path/to/source.pdf --out path/to/results --runs 1`.
With the legacy-only IDP, the supported downstream suite is
`python -m pytest -q tests/test_canonical_legacy.py tests/test_rag_core.py tests/test_retrieval_benchmark_fixes.py tests/generation`.

For offline GPU-assisted PDF parsing, use a CUDA-enabled Paddle runtime and
complete local model directories. From `services/rag` in that environment:

```sh
python -m idp.ocr.fast --pdf source.pdf --pages 43,87 --out results --lang vie+eng \
  --structured-regions --structured-budget 90 --layout-model-dir /models/PP-DocLayoutV3 \
  --layout-policy v3_vl16 --layout-device gpu:0 \
  --formula-model-dir /models/PP-FormulaNet_plus-M --formula-device gpu:0
```

These device options also work with `python -m idp.ingest` for an entire
document. They default to CPU and can be chosen independently. Tesseract text
OCR and ruled-table reconstruction run on CPU. The canonical audit still
requires review for fast OCR and model-generated formula/table candidates.

For ruled tables without model weights, run
`python -m idp.ocr.fast --pdf source.pdf --pages 43,87 --out results --lang vie+eng --cpu-tables`.
The OpenCV detector proposes table crops for the existing ruled-grid reader.
When a cell-level reread disagrees with the whole-table reading, the latter stays
in the preview and the alternate reading is retained for review.
Page enrichment reports list contained source text in
`overlapping_text_block_ids` so reviewers can compare the structured crop
with the baseline extraction.

Structured figure crops keep source resolution. When a figure exceeds the
recognition pixel limit, the reader gets a resized copy and any detected label
coordinates are projected back onto the source page. Figures and tables enter
the recognition budget before formulas. Figures can still be saved when that
budget runs out. Tight nested detections of the same figure type are merged
with both original detector boxes recorded in `structured_enrichment`.
PDF page Markdown links to local figure assets relative to the page file.

When auditing Canonical v1 moved from a Docker volume, pass the explicit export
prefix and local directory to `audit_canonical`, for example
`asset_path_mapping=("/results/output", local_output_dir)`. The mapping is
local to that audit. Keep the output folder structure when moving page Markdown
and image assets together.

To read detected formula crops with PaddleOCR-VL GGUF, start a local
`llama-server` with the model and vision projector under the alias
`paddleocr-vl-1.6`. In the structured-region command above, replace
`--formula-model-dir` and `--formula-device` with
`--formula-gguf-url http://127.0.0.1:8111`. Run IDP and the server on the same
loopback network. The GGUF server handles GPU placement. If using the IDP
registry, pass `--formula-gguf-revision` with the server and weights revision.
Formula crops, syntax validation, and review use the existing IDP workflow.
The historical DeepDoc Phase 1–5 and GPU suites require the Unified modules.

### Retrieval and quote behavior

- A dotted label such as `1.2.` starts a unit in a recognized practice section. An explicit query such as `bài 1.2` or `câu 2` gives matching task metadata priority. With the default accent fallback, `bai 1.2` and `cau 2` are also recognized. Source text and citation offsets retain their accents. Set `RetrievalConfig(accent_fallback=False)` to disable folded matching.
- The text retriever keeps up to four BM25 indexes per loaded corpus, keyed by the exact authorized and scoped chunk set and accent mode. The Canonical SQLite harness keeps one BM25 index for the last exact authorized row snapshot and checks access again before returning. A new scope can still require an index build. Both are local reference implementations for small corpora.
- The Canonical harness also prioritizes explicit dotted numbers at the start of extracted lines for task-number queries. This cue still works when PDF extraction omits a printed practice heading. Rebuild the SQLite index to refresh chunk metadata.
- `source_quotes` offers valid source substrings. Short or unmappable items are omitted from the quote branches, and oversized unbroken tokens are skipped without altering surrounding text. The existing quote limits apply. With no quotable evidence, `TextRagPipeline` returns `insufficient_evidence` before calling the generator.
- `TextRagPipeline(retriever, GroundedTaskPipeline(generator))` composes retrieval, prompt budgeting, source quote validation and provenance. It can be passed to `VerifiedRagPipeline(base, ClaimVerifier(verifier_generator))` for optional claim review. The model's verdict and a resolved quote do not certify answer correctness.

### Dependencies and rebuild

Install `requirements-phase0.lock.txt` for the base environment and `requirements-rag-models.lock.txt` for `tokenizers` and its pinned dependencies. The [tokenizers 0.22.2 package](https://pypi.org/project/tokenizers/0.22.2/) has compatible wheels for Python 3.12. ONNX embedding/reranking requires separate local model exports, matching tokenizer files and declared artifact provenance. A tokenizer smoke test runs on a locally generated file. End-to-end regression uses scripted generation and fixture embeddings/reranker scores.

Rebuild bundles created before `idp-text-chunking-7` into a fresh corpus directory before switching consumers. This change does not deploy new indexes. Create a new retriever when you load a different corpus generation.
