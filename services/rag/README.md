# Local text RAG

`build_corpus` creates a versioned bundle of source text, validated chunks and embeddings. `load_retriever` loads that bundle. `TextRetriever.retrieve` builds its candidate set from a required callback supplying current authorized child IDs, checks the set again before returning and packs source-bound context under a token budget. The caller owns permission checks for the actor and documents.

Run the test suite from `services/rag` on Windows.

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Use `rag.*` imports for the text RAG library with `services` on `PYTHONPATH`. When calling the Canonical v2 harness, also include `services/rag` for its existing `idp` dependency. Pytest sets both paths. Existing IDP scripts can continue to use `retrieval.canonical_harness` from the service root. Keep library callers within one import style to avoid mixing separate Python class identities.

### Retrieval and quote behavior

- A dotted label such as `1.2.` starts a unit in a recognized practice section. An explicit query such as `bài 1.2` or `câu 2` gives matching task metadata priority. With the default accent fallback, `bai 1.2` and `cau 2` are also recognized. Source text and citation offsets retain their accents. Set `RetrievalConfig(accent_fallback=False)` to disable folded matching.
- The text retriever keeps up to four BM25 indexes per loaded corpus, keyed by the exact authorized and scoped chunk set and accent mode. The Canonical SQLite harness keeps one BM25 index for the last exact authorized row snapshot and checks access again before returning. A new scope can still require an index build. Both are local reference implementations for small corpora.
- The Canonical harness also prioritizes explicit dotted numbers at the start of extracted lines for task-number queries. This cue still works when PDF extraction omits a printed practice heading. Rebuild the SQLite index to refresh chunk metadata.
- `source_quotes` offers valid source substrings. Short or unmappable items are omitted from the quote branches, and oversized unbroken tokens are skipped without altering surrounding text. The existing quote limits apply. With no quotable evidence, `TextRagPipeline` returns `insufficient_evidence` before calling the generator.
- `TextRagPipeline(retriever, GroundedTaskPipeline(generator))` composes retrieval, prompt budgeting, source quote validation and provenance. It can be passed to `VerifiedRagPipeline(base, ClaimVerifier(verifier_generator))` for optional claim review. The model's verdict and a resolved quote do not certify answer correctness.

### Dependencies and rebuild

Install `requirements-phase0.lock.txt` for the base environment and `requirements-rag-models.lock.txt` for `tokenizers` and its pinned dependencies. The [tokenizers 0.22.2 package](https://pypi.org/project/tokenizers/0.22.2/) has compatible wheels for Python 3.12. ONNX embedding/reranking requires separate local model exports, matching tokenizer files and declared artifact provenance. A tokenizer smoke test runs on a locally generated file. End-to-end regression uses scripted generation and fixture embeddings/reranker scores.

Rebuild bundles created before `idp-text-chunking-7` into a fresh corpus directory before switching consumers. This change does not deploy new indexes. Create a new retriever when you load a different corpus generation.
