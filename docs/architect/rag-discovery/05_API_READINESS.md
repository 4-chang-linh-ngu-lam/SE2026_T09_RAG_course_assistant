# 05 — API readiness and endpoint blockers

## Implemented Python callable vs HTTP

| Capability | Python/interface evidence | HTTP endpoint | Assessment |
|---|---|---|---|
| Parse/preflight file | idp.ingest.ingest_file; idp.input.validate_input | None | IMPLEMENTED as local callable/CLI |
| PDF/OCR page pipeline | run_ingestion, run_pipeline, Digital.process | None | IMPLEMENTED/PARTIAL; caller must supply page markers/images for OCR lane |
| Enqueue/status/retry | IngestionWorker.enqueue/run_once/recover_stale; local status.json/result.json | None | PARTIAL local filesystem worker; no cloud job contract |
| Chunk text | chunk_text/validate_chunking | None | IMPLEMENTED Python callable |
| Build/load corpus | build_corpus/load_index_bundle/load_retriever | None | IMPLEMENTED local file bundles only |
| Search/retrieve | TextRetriever.retrieve(SearchRequest, authorize) | None | IMPLEMENTED callable; caller must provide fresh authorization |
| Multi-hop | RagPipeline with injected optional planner | None | IMPLEMENTED opt-in helper; default off |
| Grounded answer | RagPipeline.answer/TextRagPipeline.answer | None | IMPLEMENTED callable; injected generator; not service runtime |
| Rerank/citation | OnnxCrossEncoder/MaxSim and source-quote/span functions | None | IMPLEMENTED optional callable components |
| Stream/cancel answer | Generator request currently uses stream=false | None | NOT IMPLEMENTED for Tutor HTTP/SSE |
| Health/readiness | No FastAPI app/ASGI health in services/rag | None | NOT IMPLEMENTED |
| Conversation CRUD/history | No conversation service/store | None | NOT IMPLEMENTED |

Search under services/rag found no FastAPI, APIRouter or HTTP application routes. HTTP calls present in the source are loopback calls to local llama.cpp/OCR runtimes, not user-facing service APIs. CLI entry points are not API endpoints.

## Production observations (read-only, 2026-11-24)

- Cloud Run services present: lumi-core-api, lumi-core-api-production and unrelated voice-vending-backend; no AI, Document or Learning service.
- Core Production OpenAPI has no route path containing /rag, /ai or /tutor.
- Web integrations mark tutor and document as pending-contract; live route availability hides s.tutor/t.documents.
- services/rag/README.md states that tests do not exercise an AI Service endpoint or real model artifacts.
- Core internal access check exists at GET /internal/v1/classes/{class_id}/access with scope core:check_access and action use_ai_tutor. This is one dependency, not an AI endpoint.

## What must exist before exposing an endpoint

1. AI Service ASGI app, OpenAPI schemas, service identity, DB, health/readiness and deployment image.
2. Web API gateway destination/allowlist and server-only AI_API_URL; frontend live decoders must target only approved operations.
3. Core user identity resolution plus scoped internal access checks, separated for use_ai_tutor and read_own_history.
4. Document grant/current-version/content contract, including revocation consistency and citation locators.
5. Learning-owned D6 assessment-state contract; unknown state must deny Tutor.
6. Conversation persistence, idempotency, cancellation, retention and deletion policy.
7. Chosen model/runtime/artifact and real-model QAS-06 evaluation.
