"""Benchmark the unified Adaptive Hybrid IDP pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import pymupdf  # noqa: F401 - warm native PDF extension before per-file timing
from idp.config import NATIVE_TRUSTED_PARSERS
from idp.ingest import ingest_file
from idp.validation.quality_gate import check_ingestion_artifacts
from retrieval.canonical_harness import LocalRagIndex

DEFAULT_FIXTURES = (
    "native.pdf",
    "scan.pdf",
    "mixed.pdf",
    "columns.pdf",
    "table.pdf",
    "formula.pdf",
    "figure.pdf",
    "vietnamese.pdf",
    "encoding.pdf",
    "rotated_cropbox.pdf",
    "multipage.pdf",
    "plain.txt",
    "plain.md",
)


def _canonical_stats(out_dir: Path) -> dict:
    canonical_file = out_dir / "canonical.json"
    if not canonical_file.is_file():
        return {
            "chars_extracted": 0,
            "blocks_extracted": 0,
            "formulas_extracted": 0,
            "tables_extracted": 0,
            "figures_extracted": 0,
            "rag_chunks_indexed": 0,
        }
    canonical = json.loads(canonical_file.read_text(encoding="utf-8"))
    blocks = [
        b
        for p in canonical.get("pages") or []
        for b in p.get("blocks") or []
        if not b.get("excluded")
    ]
    chars = sum(len((b.get("text") or "").strip()) for b in blocks)
    formulas = sum(len(b.get("latex") or []) for b in blocks)
    tables = sum(1 for b in blocks if b.get("type") == "Table")
    figures = sum(1 for b in blocks if b.get("type") in {"Picture", "Diagram", "Chart", "PictureGroup"})

    rag_db = out_dir / "rag_bench.sqlite"
    try:
        rag_chunks = LocalRagIndex(rag_db).index(
            canonical, trusted_parsers=NATIVE_TRUSTED_PARSERS
        )
    except Exception:
        rag_chunks = 0

    return {
        "chars_extracted": chars,
        "blocks_extracted": len(blocks),
        "formulas_extracted": formulas,
        "tables_extracted": tables,
        "figures_extracted": figures,
        "rag_chunks_indexed": rag_chunks,
    }


def _measure_run(fn) -> tuple[dict | None, float, float, str | None]:
    tracemalloc.start()
    t0 = time.perf_counter()
    error: str | None = None
    result: dict | None = None
    try:
        result = fn()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = max(1e-6, time.perf_counter() - t0)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, round(peak_bytes / (1024.0 * 1024.0), 3), error


def benchmark_one_adaptive(source: Path, *, language: str | None = None, vlm_mode: str = "selective") -> dict:
    with tempfile.TemporaryDirectory(prefix="bench-adaptive-") as tmp:
        out_dir = Path(tmp) / source.stem
        result, elapsed, peak_ram_mb, error = _measure_run(
            lambda: ingest_file(source, out_dir, language=language, vlm_mode=vlm_mode)
        )
        if error is not None or result is None:
            return {"file": source.name, "engine": "adaptive", "error": error, "elapsed_seconds": round(elapsed, 4)}
        chk = check_ingestion_artifacts(out_dir)
        stats = _canonical_stats(out_dir)
        pages = int(result.get("pages") or 1)
        telemetry = result.get("telemetry") or {}
        return {
            "file": source.name,
            "engine": "adaptive",
            "pages": pages,
            "elapsed_seconds": round(elapsed, 4),
            "latency_ms_per_page": round((elapsed * 1000.0) / max(1, pages), 2),
            "throughput_pages_per_min": round((pages * 60.0) / elapsed, 2),
            "peak_ram_mb": peak_ram_mb,
            "render_count": int(telemetry.get("render_count") or 0),
            "rerender_count": int(telemetry.get("rerender_count") or 0),
            "ocr_calls": int(telemetry.get("ocr_calls") or 0),
            "vlm_calls": int(telemetry.get("vlm_calls") or 0),
            "vlm_skipped_early_exit": int(telemetry.get("vlm_skipped_early_exit") or 0),
            "page_routes": telemetry.get("page_routes") or {},
            "region_actions": telemetry.get("region_actions") or {},
            "ingestion_pass": bool(result.get("ingestion_pass")),
            "ingestion_auto_publish_pass": bool(result.get("ingestion_auto_publish_pass")),
            "check_artifacts_pass": bool(chk.get("pass")),
            **stats,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Adaptive Hybrid IDP pipeline")
    parser.add_argument("--fixtures-dir", default="tests/fixtures/generated")
    parser.add_argument("--pdf", action="append", default=[], help="Extra PDF paths to benchmark")
    parser.add_argument("--language", default=None)
    parser.add_argument("--vlm-mode", default="selective", choices=("selective", "full", "off"))
    parser.add_argument("--skip-ocr", action="store_true", help="Skip scan.pdf and mixed.pdf")
    parser.add_argument("--out", default=None, help="Optional JSON report path")
    args = parser.parse_args(argv)

    fixtures_dir = Path(args.fixtures_dir)
    targets: list[Path] = []
    for name in DEFAULT_FIXTURES:
        if args.skip_ocr and name in {"scan.pdf", "mixed.pdf"}:
            continue
        candidate = fixtures_dir / name
        if candidate.is_file():
            targets.append(candidate)
    targets.extend(Path(p) for p in args.pdf)

    adaptive_rows: list[dict] = [
        benchmark_one_adaptive(path, language=args.language, vlm_mode=args.vlm_mode)
        for path in targets
    ]

    print("| File | Pages | ms/page | pages/min | RAM(MB) | Renders | OCR | Chars | Blocks | RAG Chunks | AutoPub | Routes |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for ad in adaptive_rows:
        if "error" in ad:
            print(f"| {ad['file']} | - | ERR | - | - | - | - | - | - | - | False | {ad['error']} |")
            continue
        print(
            f"| {ad['file']} | {ad['pages']} | {ad['latency_ms_per_page']} | "
            f"{ad['throughput_pages_per_min']} | {ad['peak_ram_mb']} | "
            f"{ad['render_count']} | {ad['ocr_calls']} | "
            f"{ad['chars_extracted']} | {ad['blocks_extracted']} | "
            f"{ad['rag_chunks_indexed']} | {ad['ingestion_auto_publish_pass']} | {ad['page_routes']} |"
        )

    summary = {"adaptive": _aggregate(adaptive_rows)}
    print("\nSummary:", json.dumps(summary, ensure_ascii=False))

    if args.out:
        Path(args.out).write_text(
            json.dumps({"adaptive": adaptive_rows, "summary": summary}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if summary["adaptive"]["files_err"] else 0


if __name__ == "__main__":
    sys.exit(main())
