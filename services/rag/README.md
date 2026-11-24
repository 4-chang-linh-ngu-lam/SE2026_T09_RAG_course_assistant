# RAG subsystem

`services/rag/` is the bounded RAG codebase. The packages below it are stages of
one pipeline; they are not separate microservices.

```text
idp -> chunking -> embedding/indexing -> search -> retrieval/fusion
    -> rerank -> packing -> generation -> citations
```

`idp/` owns only file ingestion, OCR, layout/structure extraction, normalization,
quality checks and canonical source export. It must not import or own embedding,
BM25, vector search, reranking, context packing or generation.

All RAG phase packages now exist under this root. They are extracted from the
prototype without algorithm changes, and each phase has an explicit ownership
boundary. The current prototype in `tools/idp` is a reference/evaluation
implementation; it is not a runtime dependency. Parity tests remain in place
until each extracted phase is reviewed and promoted.

The top-level `pipeline.py` is an orchestration composition only. It does not
turn the phases into separate microservices or introduce a new endpoint.

The runtime boundaries are explicit:

- `indexing.load_index_bundle()` validates and returns immutable corpus artifacts.
- `retrieval.corpus.load_retriever()` composes those artifacts into query serving.
- `packing.fit_evidence()` owns final whole-record prompt-budget fitting through
  callbacks; it does not import generation schemas.
- `generation` validates model output, while `citations` owns source quote/span
  mapping and review.

## Optional Vietnamese MRC reader

The default answer policies remain local-generator based.  A non-commercial,
opt-in `answer_policy="vi_mrc"` is available through
`services.rag.generation.vi_mrc_reader.ViMrcReader`.  It loads a caller-provided
local `nguyenvulebinh/vi-mrc-large` checkpoint and optional adapted QA head,
using the pinned reader settings `top_passages=3`, `max_length=384`,
`stride=128`, `max_answer_tokens=64` and null-margin threshold `-2`.
Use `vi_mrc_config()` from `services.rag.pipeline` for the matching Vietnamese
retrieval profile.

The model directory and QA-head file are external artifacts: they are not
downloaded or committed here.  Callers must provide artifact provenance and
should provide a per-file SHA-256 manifest.  The reader returns exact evidence
offsets and the pipeline maps them into the normal citation contract.  When
enabled, an abstention may run bounded lexical/date recovery over still-
authorized source texts and re-read at most three recovered passages; a
recovered answer is accepted only with a positive reader margin or the checked
relative-year rule.  This is an experimental non-commercial path; it is not
the default policy or a production quality claim.

## Optional bounded multi-hop planner

`RagPipeline` accepts an opt-in `multihop_planner`. The planner may return a
validated `MultiHopDecision` in `services.rag.retrieval.multihop`: `direct`
keeps the raw request, `rewrite` replaces it with one standalone query, and
`decompose` keeps the raw request plus at most two bounded subqueries. Each
retrieval still runs through the caller's fresh authorization callback; only
authorized evidence is merged before normal packing and generation. The
planner never supplies evidence or answer text. `GeneratorMultiHopPlanner`
uses the injected generator and is gated by follow-up/composite/context cues;
callers needing deterministic routing can use `CallableMultiHopPlanner`.

The default remains planner-off for backward-compatible latency and budget
behavior. Evaluation harnesses enable it explicitly with `--multi-hop`, and
record the planner identity and decision under `trace.multi_hop`.

The older `indexing.load_corpus()` entry point remains a compatibility wrapper
for prototype callers. New pipeline composition uses the retrieval boundary.

The AI Service described by TASK-018 owns the deployable conversation/Tutor
boundary and consumes this subsystem. Core and Document remain the authorities
for class access and active source grants; retrieval must fail closed when either
dependency cannot verify access.

See [the proposed pipeline and ownership](../../docs/architect/ai/RAG_PIPELINE_PROPOSAL.md)
for offline indexing, online query flow, contracts, stage metrics and migration
order.
