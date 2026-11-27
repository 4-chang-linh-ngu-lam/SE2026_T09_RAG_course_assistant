"""Offline CLI entrypoint for deterministic text chunking."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .atomic_io import atomic_write_text
from .boundary_cost import normalize_policy
from .chunking import _sha, chunk_text
from .token_budget import LocalTokenizer, PrefixCounter, Utf8Budget


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chunk a text textbook without OCR/ingestion outputs")
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 .md or .txt")
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    parser.add_argument("--source-id", help="Stable source/version identifier or source URL")
    parser.add_argument("--format", choices=["markdown", "text"])
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--split-strategy", choices=["greedy", "cost"], default="greedy")
    parser.add_argument("--min-tokens", type=int, help="Soft minimum for experimental cost splitting")
    parser.add_argument("--target-tokens", type=int, help="Soft target for experimental cost splitting")
    parser.add_argument("--input-prefix", default="", help="Model input prefix to include in the budget, e.g. 'passage: '")
    counter_group = parser.add_mutually_exclusive_group(required=True)
    counter_group.add_argument("--tokenizer-json", type=Path, help="Local embedding tokenizer.json; no downloads")
    counter_group.add_argument("--utf8-budget", action="store_true", help="Byte-budget diagnostic only; not token counts")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error("input must be a Markdown/text file, not an ingestion directory")
    if not args.format and args.input.suffix.lower() not in {".md", ".markdown", ".txt"}:
        parser.error("input must be .md/.markdown/.txt, or have an explicit text --format")
    if args.out.exists() and not args.out.is_dir():
        parser.error("output must be a directory")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("output directory must be new or empty")
    format = args.format or ("markdown" if args.input.suffix.lower() in {".md", ".markdown"} else "text")
    text = args.input.read_bytes().decode("utf-8-sig")
    counter = LocalTokenizer(args.tokenizer_json) if args.tokenizer_json else Utf8Budget()
    if args.input_prefix:
        counter = PrefixCounter(counter, args.input_prefix)
    if args.split_strategy != "cost" and (args.min_tokens is not None or args.target_tokens is not None):
        parser.error("--min-tokens/--target-tokens require --split-strategy cost")
    policy = {}
    if args.min_tokens is not None:
        policy["min_budget"] = args.min_tokens
    if args.target_tokens is not None:
        policy["target_budget"] = args.target_tokens
    try:
        if args.split_strategy == "cost":
            normalize_policy(policy, args.max_tokens)
    except ValueError as error:
        parser.error(str(error))
    result = chunk_text(text, counter=counter, source_id=args.source_id or str(args.input.resolve()),
                        format=format, max_tokens=args.max_tokens, split_strategy=args.split_strategy,
                        boundary_policy=policy if args.split_strategy == "cost" else None)
    args.out.mkdir(parents=True, exist_ok=True)
    document_json = json.dumps({k: v for k, v in result.items() if k not in {"children", "report"}}, ensure_ascii=False, indent=2)
    chunks_json = "\n".join(json.dumps(c, ensure_ascii=False) for c in result["children"])
    atomic_write_text(args.out / "document.json", document_json)
    atomic_write_text(args.out / "chunks.jsonl", chunks_json)
    # A report is a completion marker only after BOTH payloads were published.
    result["report"].update(completed=True, artifact_sha256={
        "document.json": _sha(document_json), "chunks.jsonl": _sha(chunks_json)})
    atomic_write_text(args.out / "chunking_report.json", json.dumps(result["report"], ensure_ascii=False, indent=2))
    print(json.dumps(result["report"], ensure_ascii=False))
    return 0 if result["report"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
