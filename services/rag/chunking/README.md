# Chunking stage

This package is the first extracted stage after IDP. It converts canonical
UTF-8 Markdown/plain text into a deterministic parent/child chunk bundle while
preserving source spans, hierarchy, protected blocks, and retrieval flags.

Run the focused tests from `services/rag`.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_chunking_v8.py tests/test_chunking_review_v8.py tests/test_chunking_v10.py tests/test_rag_core.py -q -p no:cacheprovider
```

## Input from Canonical

`indexing/canonical_text.canonical_to_markdown` is the only producer of
chunker input in the product (AI index builder). An `Equation` block projects
its `markdown` when it is a delimited display formula (`$$\n…\n$$`, `\[…\]`, or
`\begin{align}…\end{align}`), and a `Table` block projects its GFM `markdown`,
or its plain HTML table converted to GFM (no rowspan/colspan/nesting). Heading
blocks honor explicit `heading_level`/`level` (and `Title` at level 1, defaulting
to `##`), and `page_ranges` also tracks per-block `block_id`/`bbox` when
present (`locate_spans_in_canonical(..., include_block=True)`). Otherwise `text`
is used as before. Before this, formulas arrived as undelimited LaTeX and tables
as one flattened line, so no math or table policy below ever applied to real
documents. The Document service keeps an identical copy for citation location
(`document/app/modules/versions/service.py`, parity test
`document/tests/test_canonical_projection_parity.py`). On the two real local100
canonicals the two copies resolve ~8,800 probe spans identically. The default
location carries page, offsets and section title only (`include_block=True` adds
`block_id`/`bbox` when available).

## Pipeline (`idp-text-chunking-10`)

1. `text_source.parse_text` — source blocks. One block-start predicate is used
   at every line, so a table, `$$…$$`, `\[…\]`, `\begin{align}…` or fence that
   directly follows a prose line is its own block. A paragraph made only of
   one-line display formulas is `math`. A display line inside prose stays prose.
   A display formula never spans a blank line, heading or fence: an unclosed
   `$$`, `\[` or `\begin{…}` is isolated up to that boundary and flagged, and
   an unclosed code fence (`` ``` `` or `~~~`) is likewise isolated up to the
   next blank line or structural block start so the rest of the document is
   parsed normally (nothing is added to the source).
2. `hierarchy.build_hierarchy` — heading tree.
3. `text_units.plan_units` — logical parents. A closed formula or code block is
   atomic (never cut) but stays inside the step, example or definition it
   belongs to. Tables keep their own parent (row splitting with the header as a
   context reference) and share the unit ID. Unclosed blocks stay separate and
   flagged. Unit kinds: `exercise`, `example`, `activity`, `statement`
   (Định nghĩa, Định lý/lí, Tính chất, Hệ quả, Bổ đề, Quy tắc, …), `remark`
   (Chú ý, Lưu ý, Nhận xét, Kết luận, Cách giải, Phương pháp giải), `caption`
   (`Bảng 2.` / `Table 1:`), `callout`, `prose`. `unit_subtype` names the
   explicit label: definition, theorem, property, corollary, lemma, rule,
   summary, axiom, law, principle, proposition, note, remark, conclusion,
   procedure, table (empty for tasks and prose).
   - A statement label opens a new unit and closes an example or exercise. A
     remark opens one only outside an active task; inside a solution it stays,
     except an unnumbered method header (`Phương pháp giải:`) that starts a
     paragraph after the task's solution. `Cách giải 2:` stays in the task.
   - A table caption opens a unit outside an active task, so the caption, the
     table (also when the caption is right below it) and the following
     explanation share one `unit_id` (related-unit seeds; `bảng 2` anchors).
   - Labels are capitalized and punctuated (`Định lý 2.` / `Chú ý:`), or an
     unnumbered box title alone on its line (`Chú ý`). `Định lý 6` alone is an
     index entry; `mệnh đề.` in lowercase continues a sentence.
   - A solution is a label (`Lời giải:`, `Giải.`, a `Lời giải` heading). An
     instruction such as `Giải các phương trình sau:` is not a solution.
   - Inside a solution, a bare number opens the next exercise when it is the
     next task number (`2.` after exercise `1`) and not the next step of the
     solution's own numbered list. When it is both, the line stays in the
     solution and the parent gets `unit_boundary_ambiguous: true`, cleared if a
     later exercise with that number resolves it.
4. `chunking._parent_ranges` — budgeted children. Greedy is the default.
   `split_text` gallops from each cut (window doubling then bisection), so the
   remainder of a long parent is never re-tokenized for every cut, and guards
   against snapping back to a paragraph break that leaves less than a third of
   the fitting window when a sentence break fits. Boundaries are checked on the
   exact complete input. `cost` remains experimental.
5. `chunk_relations` / `chunk_views` — table header and shared-passage refs,
   `search_text` and `index_body` (via `index_parts`).
6. `validator` / `cli` — validation (`validate_chunking`) and offline CLI
   (`python -m chunking.cli` / `python -m chunking.chunking`) live in dedicated
   modules; `token_budget.MemoCounter` is shared with retrieval loading.

## Bundle fields added in v8–v10

| Field | Where | Meaning |
|---|---|---|
| `content_atoms` | parent | `[{start, end, kind}]` parent-text intervals of merged `math`/`code` blocks; one per formula when a block is several one-line formulas (`\begin{align}` and multi-line `$$` stay one). Splitting and continuation packing never cut inside them. |
| `unit_subtype` | parent, child | Subtype of an explicit label (see above). |
| `unit_boundary_ambiguous` | parent | A numbered line kept in a solution could also have been the next task. |
| `context_eligible` | child | Held only for size (`indivisible_text_exceeds_budget`, `atomic_block_exceeds_budget`, `table_row_exceeds_budget`, `table_header_exceeds_budget`), closed source, token budget. Never searchable or a seed; `expand_context` may pack it beside an eligible seed of the same authorized scope. |
| `report.statement_parent_count`, `caption_unit_parents`, `ambiguous_unit_boundaries`, `mixed_content_parents`, `atomic_parent_count`, `context_eligible_children` | report | Structure counters. |
| `report.build_counter`, `validation_counter`, `validation_level` | report | Real tokenizer calls, cache hits and tokenized characters. |

## Representations used downstream

| Consumer | Field |
|---|---|
| BGE-M3 passage embedding (`indexing/rag_corpus.py`) | `search_text` (breadcrumb + indexed refs + text) |
| BM25 (`search/retrieval_lexical.py`) | `index_body` (body weight 1 + body bigrams + Layer A Vietnamese orthography), section title (0.5), `context_path` (0.25) |
| Reranker (`retrieval/retrieval.py`) | `search_text` (with `max_tokens` up to `8192`) |
| Neighbor packing (`packing/neighbor_context.py`) | `TextRetriever._search_text_tokens` (exact-safe additive bounds for `local_huggingface_tokenizer`, avoiding redundant full-sequence BPE calls) |
| Structure arm anchors (`search/retrieval_plan.py`) | `context_path` + `unit_label`; numbered statement labels (`định lý 2`, `định nghĩa 1.2`) are anchors |
| Related-unit seeds | `unit_id` (indexed once per retriever) |

## Validation levels

`validate_chunking(bundle, source, counter, level=...)`. Both levels re-parse
the source and recheck the heading tree, logical units, every span and hash,
the parent partition, references, index inputs, real token counts, flags and
eligibility, plus the boundary invariants without re-splitting: no cut inside
a formula/code atom or inline math/code, no cut inside a combining sequence,
row boundaries only in a valid table, one child for a non-table atomic parent,
and a size hold only on an input that really exceeds the budget. `full` also
re-derives every child boundary with the splitter.
`chunk_text` runs `full` (it reuses the build's exact count memo, so it is
cheap); `load_retriever` runs `fast` by default because the corpus was fully
validated when built (`chunk_validation="full"` for audits).

## Compatibility

Bundles before `idp-text-chunking-10` fail validation and must be rebuilt with
`build_corpus`. The AI index builder rebuilds a READY corpus whose
manifest has no current `chunking_version`
(`rag.retrieval.corpus.chunking_is_current`, a manifest-only probe). Until a
document version is rebuilt, `active_corpora` skips its stale corpus and
`ensure_canonical_cache` loads its canonical records, so Tutor and Quiz serve
it through the canonical fallback instead of failing with 503.
See [local RAG usage and verification](../README.md).
