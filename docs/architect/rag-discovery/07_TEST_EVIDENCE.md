# 07 — Test evidence and verification limits

## Current revision evidence

- Surveyed branch codex/rag-technical-discovery at dc0671c36bf750ef914ac34d22e6ff2cf685287a; origin/main matches.
- GitHub Actions rag-tests on PR #49 head 680beaf2f4122e2e2fc10f959a6004c1713eafb4 passed: 144 passed, 2 skipped, 1 xfailed, 2 warnings in 3.63 seconds. Runner used Ubuntu 26.04 / CPython 3.12.16, installed requirements-test.txt, then ran pytest services/rag/tests. PR #49 did not change services/rag; this is recent CI evidence for the same RAG source, not a fresh Production run.
- The tracked RAG tree contains 21 test_*.py files. CI does not install real model artifacts, call an AI HTTP service, access Document or Learning services, or use a production database.
- tests/test_text_rag_integration.py builds a real text bundle/retriever from two tiny Markdown strings, but encoder and generator are deterministic fixtures. Multihop tests use fake retriever/generator. This proves composition and authorized-source filtering in that harness only.
- Historical docs/deepdoc/README.md records 489 pass, 2 skip, 2 XFAIL on Windows dated 2026-11-18; it is a different suite/environment and is not the latest CI count.
- PR #46 records a 48-question retrieval experiment and a 12-question Gemini check (4/10 correct where an answer existed); these are not QAS-06 acceptance or a real integrated-service result.
- QAS-06 requires at least 100 labeled questions, citation/grounding/refusal targets and cross-scope tests; no accepted 100-question Production-model evaluation is evidenced.
- Static AST parsing of all 183 Python files under services/rag found zero parse errors. This is a syntax scan, not behavioral verification.

## Local test attempt

NOT RUN locally. At inspection time the machine had about 0.50 GB RAM free; system Python was 3.11.9, pytest was not installed, and no local RAG virtual environment exists. The documented RAG test environment uses Python 3.12. Installing dependencies and running OCR/model-heavy tests was not safe with this memory state; no dependencies or model artifacts were installed/downloaded.

## Test groups and what they prove

- tests/test_phase0.py, test_idp_restored_parsing.py, test_ocr_quality.py, test_sgk_cross_read.py and related tests exercise parser/chunking/validation code using fixtures and configured local tools.
- tests/test_rag_core.py and retrieval-focused tests cover deterministic indexing/search/context behavior.
- tests/test_text_rag_integration.py covers a small text index-to-answer path with fixture encoder/generator.
- tests/test_multihop_pipeline.py covers optional planner/retrieval/generation orchestration with fake model/retriever objects.
- tests/generation/ covers adapters and QA/quiz contracts with fixture generators; it does not load the Production model.

## Verification not evidenced

- Real PDF ingestion through a Production parser/OCR model into a Document-owned source/version.
- Real ONNX embedding/reranking artifacts on a deployed runtime.
- Real llama.cpp/ViMRC inference under Cloud Run resource limits.
- HTTP/contract/E2E tests across AI + Core + Document + Learning.
- Cross-school/class grant revocation through actual service endpoints.
- QAS-05 mixed-service client latency and QAS-06 quality benchmark.
