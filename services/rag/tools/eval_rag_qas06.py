"""Offline/live QAS-06 evaluation CLI for GroundedTaskPipeline + answer_quick."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rag.chunking.chunking import chunk_text
from rag.generation.contracts.evidence import evidence_items
from rag.generation.eval.metrics import qa_report
from rag.generation.openai_compatible import OpenAICompatibleGenerator
from rag.generation.pipeline import GroundedTaskPipeline
from rag.generation.policy.config import TutorConfig
from rag.generation.rag_generation import LlamaGenerator
from rag.generation.tasks.qa.quick import answer_quick
from rag.indexing.canonical_text import canonical_to_markdown
from rag.retrieval.canonical_harness import LexicalTokenBudget
from rag.retrieval.corpus import load_retriever
from rag.search.retrieval_lexical import FieldedBM25
from rag.search.retrieval_plan import SearchRequest


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def build_canonical_retriever(canonical_path: Path, *, top_k: int = 5) -> Callable[[str], list[dict]]:
    artifact = json.loads(canonical_path.read_text(encoding="utf-8"))
    text, _ = canonical_to_markdown(artifact)
    if not text.strip():
        return lambda _q: []
    bundle = chunk_text(
        text,
        source_id=canonical_path.stem,
        counter=LexicalTokenBudget(),
        format="markdown",
        max_tokens=384,
    )
    children = [c for c in bundle["children"] if c.get("retrieval_eligible")]
    by_id = {c["id"]: c for c in children}
    bm25 = FieldedBM25(children, fold_accents=True)

    def retrieve(question: str) -> list[dict]:
        ranked = bm25.rank(question)[:top_k]
        return [by_id[cid] for cid, _ in ranked if cid in by_id]

    return retrieve


def build_corpus_retriever(
    corpus_dir: Path,
    *,
    model_path: Path,
    tokenizer_path: Path,
    repo: str,
    revision: str,
    variant: str,
) -> Callable[[str], list[dict]]:
    from rag.embedding.bge_embedding import OnnxBgeM3

    encoder = OnnxBgeM3(
        model_path,
        tokenizer_path,
        provenance={"repo": repo, "revision": revision, "variant": variant},
    )
    retriever, _, _ = load_retriever(corpus_dir, encoder=encoder)
    allowed = set(retriever.children)

    def retrieve(question: str) -> list[dict]:
        res = retriever.retrieve(SearchRequest(question), authorize=lambda: allowed)
        return list(res["context"]["items"])

    return retrieve


def _evaluate_case_heuristic(
    case: dict[str, Any],
    answer: dict[str, Any],
) -> tuple[list[dict[str, bool]], list[dict[str, Any]]]:
    expected_substrings = [
        str(s).casefold()
        for s in (case.get("expected_substrings") or [])
        if isinstance(s, str) and s.strip()
    ]
    source_claims = [c for c in answer.get("claims", []) if c.get("basis") == "source"]
    citations_eval: list[dict[str, bool]] = []
    claims_eval: list[dict[str, Any]] = []
    for claim in source_claims:
        combined = " ".join(
            [
                claim.get("text", ""),
                *(c.get("quote", "") for c in claim.get("evidence", [])),
            ]
        ).casefold()
        supports = (
            any(sub in combined for sub in expected_substrings)
            if expected_substrings
            else bool(claim.get("evidence"))
        )
        for _ in claim.get("evidence", []):
            citations_eval.append({"supports": supports, "class_ok": True})
        claims_eval.append({"basis": "source", "grounded": supports})
    return citations_eval, claims_eval


def run_evaluation(
    cases: list[dict[str, Any]],
    retrieve_fn: Callable[[str], list[dict]],
    pipeline: GroundedTaskPipeline,
    *,
    judge: bool = False,
    config: TutorConfig | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tutor_config = config or TutorConfig()
    latencies_ms: list[float] = []
    eval_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for index, case in enumerate(cases):
        question = str(case["question"])
        answerable = bool(case.get("answerable", True))
        started = time.perf_counter()
        records = retrieve_fn(question)
        ev = evidence_items(records) if records else []
        answer = answer_quick(
            pipeline,
            question=question,
            evidence=ev,
            config=tutor_config,
            judge=judge,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        latencies_ms.append(elapsed_ms)

        citations_eval, claims_eval = _evaluate_case_heuristic(case, answer)
        eval_rows.append(
            {
                "answerable": answerable,
                "status": answer.get("status"),
                "citations": citations_eval,
                "claims": claims_eval,
            }
        )
        results.append(
            {
                "index": index,
                "question": question,
                "answerable": answerable,
                "status": answer.get("status"),
                "refusal_reason": answer.get("refusal_reason"),
                "claim_count": len(answer.get("claims", [])),
                "flags": answer.get("flags", []),
                "latency_ms": elapsed_ms,
            }
        )

    return {
        "metadata": metadata or {},
        "cases_count": len(cases),
        "judge_enabled": judge,
        "p50_latency_ms": round(statistics.median(latencies_ms), 2) if latencies_ms else None,
        "p95_latency_ms": _percentile(latencies_ms, 0.95),
        "qa_report": qa_report(eval_rows),
        "results": results,
        "manual_audit_required": True,
        "certifies_qas06": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAG quick-QA against QAS-06 cases.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--canonical", type=Path, help="Path to Canonical JSON file.")
    source.add_argument("--corpus", type=Path, help="Path to built corpus directory.")
    parser.add_argument("--cases", type=Path, required=True, help="Path to evaluation JSONL file.")
    parser.add_argument("--api-base", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key-env", default="LLM_API_KEY", help="Env var holding API key.")
    parser.add_argument("--model", default="deepseek-chat", help="OpenAI-compatible model name.")
    parser.add_argument("--llama-url", help="Loopback llama.cpp HTTP origin.")
    parser.add_argument("--llama-model-path", type=Path)
    parser.add_argument("--llama-server-path", type=Path)
    parser.add_argument("--llama-model-repo")
    parser.add_argument("--llama-model-revision")
    parser.add_argument("--llama-model-variant")
    parser.add_argument("--embedding-model", type=Path)
    parser.add_argument("--embedding-tokenizer", type=Path)
    parser.add_argument("--embedding-repo")
    parser.add_argument("--embedding-revision")
    parser.add_argument("--embedding-variant")
    parser.add_argument("--context-tokens", type=int, default=8192)
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--out", type=Path, help="Optional JSON output path.")
    args = parser.parse_args(argv)

    cases = [
        json.loads(line)
        for line in args.cases.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.canonical is not None:
        retrieve_fn = build_canonical_retriever(args.canonical)
    else:
        if not all(
            (
                args.embedding_model,
                args.embedding_tokenizer,
                args.embedding_repo,
                args.embedding_revision,
                args.embedding_variant,
            )
        ):
            parser.error("--corpus requires all --embedding-* arguments")
        retrieve_fn = build_corpus_retriever(
            args.corpus,
            model_path=args.embedding_model,
            tokenizer_path=args.embedding_tokenizer,
            repo=args.embedding_repo,
            revision=args.embedding_revision,
            variant=args.embedding_variant,
        )

    if args.api_base:
        api_key = os.environ.get(args.api_key_env, "")
        if not api_key.strip():
            parser.error(f"Environment variable {args.api_key_env} is empty")
        generator = OpenAICompatibleGenerator(
            args.api_base,
            api_key,
            model=args.model,
            context_tokens=args.context_tokens,
            max_new_tokens=args.max_new_tokens,
            output_ceiling=max(768, args.max_new_tokens),
        )
        mode = "openai_compatible"
    elif args.llama_url:
        generator = LlamaGenerator(
            args.llama_url,
            model_path=args.llama_model_path,
            server_path=args.llama_server_path,
            provenance={
                "repo": args.llama_model_repo or "local",
                "revision": args.llama_model_revision or "local",
                "variant": args.llama_model_variant or "local",
            },
            context_tokens=args.context_tokens,
            max_new_tokens=args.max_new_tokens,
            output_ceiling=max(768, args.max_new_tokens),
        )
        mode = "local_llama"
    else:
        parser.error("Specify either --api-base or --llama-url")

    pipeline = GroundedTaskPipeline(generator)
    report = run_evaluation(
        cases,
        retrieve_fn,
        pipeline,
        judge=args.judge,
        metadata={"mode": mode, "model": getattr(generator, "model", None)},
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
