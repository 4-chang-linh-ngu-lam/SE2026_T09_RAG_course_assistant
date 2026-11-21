"""Reproducible CPU benchmark/stress driver; no unmeasured production claims."""

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


def generate(path, pages, scan=False):
    import fitz

    with fitz.open() as template:
        p = template.new_page(width=400, height=600)
        p.insert_text(
            (30, 70),
            "Independent textbook source evidence for performance evaluation.",
            fontsize=10,
        )
        p.insert_text((30, 100), "The cobalt crystal reflects blue light.", fontsize=12)
        image = p.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png") if scan else None
        with fitz.open() as pdf:
            for _ in range(pages):
                if scan and (scan != "mixed" or _ % 2 == 1):
                    pdf.new_page(width=400, height=600).insert_image(
                        p.rect, stream=image
                    )
                else:
                    pdf.insert_pdf(template)
            pdf.save(path)


def child(args):
    import psutil
    from idp.pdf.service import DeepDocConfig, DeepDocService
    from idp.publish import to_v1
    from idp.runtime.cache import StageCache

    process = psutil.Process()
    fds = process.num_fds() if hasattr(process, "num_fds") else None
    source = Path(args.source)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    cache = (
        StageCache(args.cache, job_id=output.name, max_backend_calls=10000)
        if args.cache
        else None
    )
    settings = dict(  # noqa: C408 - keys below mirror keyword constructor arguments.
        engine="unified",
        canonical_version=2,
        dpi=144,
        max_pixels=1_000_000,
        timeout_seconds=3600,
        max_calls=10000,
        max_total_pixels=250_000_000,
    )
    started = time.perf_counter()
    service = DeepDocService(DeepDocConfig(**settings), stage_cache=cache)
    doc = service.process_pdf(source, output)
    duration = time.perf_counter() - started
    text = "\n".join(b["text"] for p in to_v1(doc)["pages"] for b in p["blocks"])
    expected = "\n".join(
        [
            "Independent textbook source evidence for performance evaluation.",
            "The cobalt crystal reflects blue light.",
        ]
        * len(doc["pages"])
    )
    actual_tokens = Counter(text.split())
    expected_tokens = Counter(expected.split())
    covered = sum((actual_tokens & expected_tokens).values())
    import hashlib

    report = json.loads((output / "run_report.json").read_text())
    result = {
        "source": source.name,
        "pages": len(doc["pages"]),
        "seconds": duration,
        "pages_per_second": len(doc["pages"]) / duration,
        "ocr_calls": report["ocr_invocations"],
        "ocr_backends": report["ocr_backends"],
        "status": report["status"],
        "stage_seconds": report["stage_seconds"],
        "cache_stats": cache.stats if cache else None,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "independent_ground_truth": "PDF draw commands in generate()",
        "published_text_exact": text == expected,
        "published_token_precision": covered / max(1, sum(actual_tokens.values())),
        "published_token_recall": covered / max(1, sum(expected_tokens.values())),
        "fds_before": fds,
        "fds_after": process.num_fds() if fds is not None else None,
        "service_sha256": hashlib.sha256(
            Path(sys.modules[DeepDocService.__module__].__file__).read_bytes()
        ).hexdigest(),
        "serde_sha256": hashlib.sha256(
            Path(__import__("idp.evidence.serde", fromlist=["x"]).__file__).read_bytes()
        ).hexdigest(),
    }
    (output / "measurement.json").write_text(json.dumps(result, indent=2))


def measured(command, log):
    import psutil

    peak = 0
    cpu = 0
    start = time.perf_counter()
    with Path(log).open("w") as handle:
        proc = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)
        monitor = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                tree = [monitor, *monitor.children(recursive=True)]
                peak = max(
                    peak, sum(p.memory_info().rss for p in tree if p.is_running())
                )
                cpu = max(
                    cpu,
                    sum(
                        p.cpu_times().user + p.cpu_times().system
                        for p in tree
                        if p.is_running()
                    ),
                )
            except psutil.Error:
                pass
            if time.perf_counter() - start > 3600:
                proc.kill()
                proc.wait()
                raise TimeoutError("benchmark hard timeout")
            time.sleep(0.05)
        code = proc.wait()
    return {
        "returncode": code,
        "sampled_peak_tree_rss_bytes": peak,
        "sampled_cpu_seconds": cpu,
        "subprocess_wall_seconds": time.perf_counter() - start,
    }


def benchmark(args):
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for name, n, scan in [
        ("native", 1, False),
        ("scan", 1, True),
        ("scan4", 4, True),
        ("mixed", 2, "mixed"),
    ]:
        source = root / (name + ".pdf")
        generate(source, n, scan)
        for repeat in range(args.repeats):
            for variant in ("cold", "warm"):
                output = root / f"{name}-{repeat}-{variant}"
                cache = root / f"cache-{name}-{repeat}"
                command = [
                    sys.executable,
                    __file__,
                    "--child",
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                ]
                command.extend(["--cache", str(cache)])
                metric = measured(command, root / (output.name + ".log"))
                if metric["returncode"] == 0:
                    metric.update(json.loads((output / "measurement.json").read_text()))
                records.append(
                    {"case": name, "repeat": repeat, "variant": variant, **metric}
                )
                (root / "benchmark-results.json").write_text(
                    json.dumps(records, indent=2)
                )
    for kind, pages in [
        *(("native", n) for n in args.stress),
        *(("scan", n) for n in args.scan_stress),
    ]:
        source = root / f"{kind}-{pages}.pdf"
        generate(source, pages, scan=kind == "scan")
        output = root / f"stress-{kind}-{pages}"
        metric = measured(
            [
                sys.executable,
                __file__,
                "--child",
                "--source",
                str(source),
                "--output",
                str(output),
            ],
            root / (output.name + ".log"),
        )
        if metric["returncode"] == 0:
            metric.update(json.loads((output / "measurement.json").read_text()))
        records.append(
            {
                "case": "stress-" + kind,
                "pages_requested": pages,
                "variant": "clean",
                **metric,
            }
        )
        (root / "benchmark-results.json").write_text(json.dumps(records, indent=2))
    print(
        json.dumps(
            {
                "runs": len(records),
                "failures": sum(r["returncode"] != 0 for r in records),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source")
    parser.add_argument("--cache")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--stress", nargs="*", type=int, default=[100, 500, 1000])
    parser.add_argument("--scan-stress", nargs="*", type=int, default=[100])
    args = parser.parse_args()
    child(args) if args.child else benchmark(args)
