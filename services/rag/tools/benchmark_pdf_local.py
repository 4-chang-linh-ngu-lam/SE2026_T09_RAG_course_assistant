"""Benchmark native PDF extraction on CPU, with OCR disabled."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from importlib.util import find_spec
from pathlib import Path

import psutil


def child(args):
    from retrieval.canonical_harness import (
        LocalRagIndex,
        iter_retrievable_blocks,
        resolve_citation,
    )

    start = time.perf_counter()
    trusted_parsers = ()
    canonical_path = args.out / "canonical.json"
    if find_spec("idp.publish") is None:
        from idp.documents.digital import process

        process(args.pdf, args.out, ocr_fallback=False, region_recovery=False)
        service_seconds = time.perf_counter() - start
        doc = json.loads(canonical_path.read_text(encoding="utf-8"))
        report_path = args.out / "ingestion_report.json"
        trusted_parsers = ("pymupdf",)
    else:
        from dataclasses import replace

        from idp.pdf.native.preflight import PdfAdmissionPolicy
        from idp.pdf.service import DeepDocConfig, DeepDocService
        from idp.pdf.verify_runtime import BackendRegistry
        from idp.publish import load_canonical

        DeepDocService(
            DeepDocConfig(
                engine="unified",
                canonical_version=2,
                timeout_seconds=900,
                max_calls=2500,
                max_calls_per_page=100,
                max_regions=5000,
                max_total_pixels=2000000000,
                admission=replace(PdfAdmissionPolicy(), max_total_render_pixels=2000000000),
            ),
            backend_registry=BackendRegistry(),
        ).process_pdf(args.pdf, args.out)
        service_seconds = time.perf_counter() - start
        doc = load_canonical(canonical_path)
        report_path = args.out / "run_report.json"
    blocks = list(iter_retrievable_blocks(doc, trusted_parsers=trusted_parsers))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    extraction_path = args.out / "extraction.json"
    result = {
        "service_seconds": service_seconds,
        "report": report,
        "eligible_blocks": len(blocks),
        "eligible_characters": sum(len(b["text"]) for b in blocks),
        "canonical_bytes": canonical_path.stat().st_size,
        "extraction_bytes": extraction_path.stat().st_size if extraction_path.is_file() else None,
        "quality": "NOT MEASURED: native extraction only, no OCR or ground truth",
        "docker_used": False,
        "gpu_used": False,
    }
    if blocks:
        index = LocalRagIndex(args.out / "smoke-index.sqlite3")
        index.index(doc, trusted_parsers=trusted_parsers)
        query = " ".join(blocks[0]["text"].split()[:8])
        hits = index.retrieve(
            query, actor="benchmark-local", access_check=lambda *a: True
        )
        result["retrieval_smoke"] = {
            "hits": len(hits),
            "citations_valid": bool(hits) and all(
                resolve_citation(h, doc, trusted_parsers=trusted_parsers) for h in hits
            ),
            "note": "query from extracted text; pipeline smoke only, not retrieval accuracy",
        }
    (args.out / "measurement.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.child:
        child(args)
        return
    rows = []
    for n in range(args.runs):
        out = args.out / f"run-{n + 1}"
        out.mkdir(exist_ok=True)
        start = time.monotonic()
        peak = 0
        with (out / "worker.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "tools.benchmark_pdf_local",
                    "--child",
                    "--pdf",
                    str(args.pdf.resolve()),
                    "--out",
                    str(out.resolve()),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=Path(__file__).resolve().parents[1],
            )
            root = psutil.Process(proc.pid)
            try:
                while proc.poll() is None:
                    try:
                        peak = max(
                            peak,
                            sum(
                                p.memory_info().rss
                                for p in [root, *root.children(recursive=True)]
                            ),
                        )
                    except psutil.Error:
                        pass
                    if time.monotonic() - start > 960 or peak > 2 * 1024**3:
                        for p in root.children(recursive=True):
                            try:
                                p.kill()
                            except psutil.Error:
                                pass
                        proc.kill()
                        break
                    time.sleep(0.1)
                code = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        row = {
            "run": n + 1,
            "returncode": code,
            "wall_seconds": time.monotonic() - start,
            "sampled_peak_tree_rss_mib": peak / 1048576,
        }
        if (out / "measurement.json").exists():
            row.update(
                json.loads((out / "measurement.json").read_text(encoding="utf-8"))
            )
        rows.append(row)
        with args.pdf.open("rb") as f:
            sha = hashlib.file_digest(f, "sha256").hexdigest()
        (args.out / "benchmark.json").write_text(
            json.dumps(
                {
                    "input": str(args.pdf),
                    "source_sha256": sha,
                    "runs": rows,
                    "cache": "OS warm on repeat; no StageCache configured",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    k: row[k]
                    for k in [
                        "run",
                        "returncode",
                        "wall_seconds",
                        "sampled_peak_tree_rss_mib",
                    ]
                }
            ),
            flush=True,
        )
        if code:
            raise SystemExit(code)


if __name__ == "__main__":
    main()
