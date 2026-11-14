from idp.validation.ingestion_checks import check_ingestion_artifacts
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from idp.orchestration.cli import _find_marker, _find_page_image, parse_pages
from idp.input.filetypes import InputError, validate_input
from idp.orchestration.pipeline import PIPELINE_VERSION, sha256_file
from idp.input.preflight import preflight
from idp.orchestration.registry import DocumentRegistry


def _copy_existing_markers(source_dir: Path | None, target_dir: Path, pages: list[int]) -> None:
    if not source_dir:
        return
    if source_dir.resolve() == target_dir.resolve():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        candidates = [
            (
                source_dir / f"p{page}_300" / f"p{page}_300.json",
                target_dir / f"p{page}_300" / f"p{page}_300.json",
            ),
            (
                source_dir / f"p{page:04d}" / f"p{page:04d}.json",
                target_dir / f"p{page:04d}" / f"p{page:04d}.json",
            ),
        ]
        for src, dst in candidates:
            if src.exists() and (not dst.exists() or sha256_file(src) != sha256_file(dst)):
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            sidecar = src.with_name(src.name + ".fast")
            if sidecar.exists():
                dst_sidecar = dst.with_name(dst.name + ".fast")
                dst_sidecar.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(sidecar, dst_sidecar)
            elif src.exists():
                dst.with_name(dst.name + ".fast").unlink(missing_ok=True)
            fallback = src.with_name(src.name + ".fallback")
            if fallback.exists():
                dst_fallback = dst.with_name(dst.name + ".fallback")
                dst_fallback.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(fallback, dst_fallback)
            elif src.exists():
                dst.with_name(dst.name + ".fallback").unlink(missing_ok=True)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _cli_command(args, pages: str, resume: bool) -> list[str]:
    cmd = [
        sys.executable, "-m", "idp.orchestration.cli",
        "--pdf", str(args.pdf),
        "--pages", pages,
        "--out", str(args.out),
        "--dpi", str(args.dpi),
        "--marker-dir", str(args.out / "markers"),
        "--marker-bin", args.marker_bin,
        "--marker-timeout", str(args.marker_timeout),
        "--llama-bin", args.llama_bin or "",
    ]
    if args.image_dir:
        cmd.extend(["--image-dir", str(args.image_dir)])
    if args.run_marker:
        cmd.append("--run-marker")
    if args.fast_fallback:
        cmd.append("--fast-fallback")
    cmd.extend([
        "--fallback-engine", args.fallback_engine,
        "--fallback-timeout", str(args.fallback_timeout),
        "--fallback-lang", args.fallback_lang,
        "--profile", args.profile,
    ])
    if args.language:
        cmd.extend(["--language", args.language])
    if args.chart_cmd:
        cmd.extend([
            "--chart-cmd", args.chart_cmd,
            "--chart-timeout", str(args.chart_timeout),
        ])
    if args.figure_cmd:
        cmd.extend([
            "--figure-cmd", args.figure_cmd,
            "--figure-timeout", str(args.figure_timeout),
        ])
    if args.workers != 1:
        cmd.extend(["--workers", str(args.workers)])
    if args.fallback_cmd:
        cmd.extend(["--fallback-cmd", args.fallback_cmd])
    if args.repair_math:
        cmd.append("--repair-math")
    if args.verify_cmd:
        cmd.extend([
            "--verify-cmd", args.verify_cmd,
            "--verify-timeout", str(args.verify_timeout),
            "--verify-max-pages", str(args.verify_max_pages),
        ])
    for parser_name in args.trusted_parser or []:
        cmd.extend(["--trusted-parser", parser_name])
    if args.preprocess:
        cmd.append("--preprocess")
    if args.allow_layout_failure:
        cmd.append("--allow-layout-failure")
    if resume:
        cmd.append("--resume")
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Checkpointed full-book IDP batch")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--image-dir")
    parser.add_argument("--marker-dir")
    parser.add_argument("--run-marker", action="store_true")
    parser.add_argument("--fast-fallback", action="store_true")
    parser.add_argument("--repair-math", action="store_true")
    parser.add_argument("--preprocess", action="store_true")
    parser.add_argument("--marker-bin", default="marker_single")
    parser.add_argument("--marker-timeout", type=int, default=600)
    parser.add_argument("--fallback-engine", choices=["auto", "none", "tesseract", "command"], default="auto")
    parser.add_argument("--fallback-cmd", default=os.environ.get("IDP_FALLBACK_CMD"))
    parser.add_argument("--fallback-timeout", type=int, default=300)
    parser.add_argument("--fallback-lang", default="vie")
    parser.add_argument("--profile", default="general")
    parser.add_argument("--language", default=None)
    parser.add_argument("--chart-cmd", default=os.environ.get("IDP_CHART_CMD"))
    parser.add_argument("--chart-timeout", type=int, default=120)
    parser.add_argument("--figure-cmd", default=os.environ.get("IDP_FIGURE_CMD"))
    parser.add_argument("--figure-timeout", type=int, default=120)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--llama-bin", default=os.environ.get("LLAMA_CPP_BINARY"))
    parser.add_argument("--allow-layout-failure", action="store_true")
    parser.add_argument("--registry", help="SQLite document registry for idempotent reruns")
    parser.add_argument("--scope", help="registry scope override (default: pages@dpi)")
    parser.add_argument("--verify-cmd", default=os.environ.get("IDP_VERIFY_CMD"))
    parser.add_argument("--verify-timeout", type=int, default=600)
    parser.add_argument("--verify-max-pages", type=int, default=0)
    parser.add_argument("--trusted-parser", action="append", default=None)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--allow-digital", action="store_true")
    parser.add_argument("--gold")
    args = parser.parse_args()
    if args.gold:
        parser.error("--gold evaluation was moved out of ingestion")

    args.pdf = Path(args.pdf)
    args.out = Path(args.out)
    args.image_dir = Path(args.image_dir) if args.image_dir else None
    source_markers = Path(args.marker_dir) if args.marker_dir else None
    args.out.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(args.pages)
    source_sha256 = sha256_file(args.pdf)
    config = {
        key: value for key, value in vars(args).items()
        if key not in {"pdf", "out", "registry", "scope"}
    }
    config["trusted_parser"] = sorted(args.trusted_parser or [])
    if args.registry:
        external = {}
        for page in pages:
            for label, path in (
                ("marker", _find_marker(source_markers, page, args.dpi) if source_markers else None),
                ("image", _find_page_image(args.image_dir, page, args.dpi) if args.image_dir else None),
            ):
                if path is not None:
                    external[f"{label}:{page}"] = sha256_file(path) if path.exists() else None
                    if label == "marker":
                        for suffix in (".fast", ".fallback"):
                            sidecar = path.with_name(path.name + suffix)
                            external[f"{label}:{page}{suffix}"] = sha256_file(sidecar) if sidecar.exists() else None
        config["external_inputs"] = external
    config_sha = hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    scope = f"{args.scope or args.pages + '@' + str(args.dpi)}:{config_sha}"
    registry = DocumentRegistry(args.registry) if args.registry else None
    if registry and registry.should_skip(
        source_sha256, "marker", "unknown", PIPELINE_VERSION, scope
    ):
        row = registry.lookup(
            source_sha256, "marker", "unknown", PIPELINE_VERSION, scope
        ) or {}
        print(json.dumps({
            "status": "skipped",
            "reason": "canonical document already exists",
            "canonical_path": row.get("canonical_path"),
            "source_sha256": source_sha256,
            "scope": scope,
        }, ensure_ascii=False, indent=1))
        return 0
    try:
        validate_input(args.pdf)
    except InputError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    profile = preflight(args.pdf, pages)
    (args.out / "preflight.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if profile["recommended_lane"] == "digital" and not args.allow_digital:
        print(json.dumps({
            "status": "wrong_lane",
            "recommended_lane": "digital",
            "message": "PDF has a text layer; use `python -m idp.documents.digital`. "
                       "Pass --allow-digital to force marker anyway.",
        }, ensure_ascii=False, indent=1))
        return 2
    _copy_existing_markers(source_markers, args.out / "markers", pages)

    status_path = args.out / "batch_status.jsonl"
    ok, failed = [], []
    for index, page in enumerate(pages, 1):
        t0 = time.perf_counter()
        cmd = _cli_command(args, str(page), resume=True)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=_child_env(),
        )
        elapsed = round(time.perf_counter() - t0, 2)
        record = {
            "page": page,
            "index": index,
            "total": len(pages),
            "status": "ok" if proc.returncode == 0 else "failed",
            "seconds": elapsed,
            "returncode": proc.returncode,
        }
        if proc.returncode != 0:
            record["error"] = (proc.stderr or proc.stdout)[-2000:]
            failed.append(page)
        else:
            ok.append(page)
        with status_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}/{len(pages)}] page {page} {record['status']} {elapsed}s", flush=True)

    final_cmd = _cli_command(args, ",".join(str(p) for p in pages), resume=True)
    final = subprocess.run(
        final_cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=_child_env(),
    )
    audit_result = None
    summary = {
        "pages": len(pages),
        "ok": len(ok),
        "failed": failed,
        "profile": args.profile,
        "language": args.language,
        "preflight_lane": profile["recommended_lane"],
        "preflight_review_required": profile["review_required"],
        "preflight_math_page_count": len(profile.get("math_pages", [])),
        "final_returncode": final.returncode,
        "audit_pass": None,
        "status_file": str(status_path),
    }
    summary_path = args.out / "batch_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if args.audit and final.returncode == 0:
        audit_result = check_ingestion_artifacts(args.out, expected_pages=pages)
        summary["audit_pass"] = audit_result["pass"]
        summary["audit_errors"] = audit_result["errors"]
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if final.stdout:
        print(final.stdout[-4000:])
    if final.stderr:
        print(final.stderr[-2000:], file=sys.stderr)
    audit_ok = audit_result is None or audit_result["pass"]
    report_path = args.out / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    summary["ingestion_pass"] = report.get("ingestion_pass")
    summary["ingestion_quality_pass"] = report.get("ingestion_quality_pass")
    summary["ingestion_review_assisted_pass"] = report.get("ingestion_review_assisted_pass")
    summary["ingestion_production_pass"] = report.get("ingestion_production_pass")
    summary["ingestion_auto_publish_pass"] = report.get("ingestion_auto_publish_pass")
    summary["ingestion_quality_certified"] = report.get("ingestion_quality_certified")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    ingestion_review = report.get("ingestion_review_assisted_pass")
    ok_final = final.returncode == 0 and not failed and audit_ok and ingestion_review is not False
    if registry:
        canonical = args.out / "canonical.json"
        registry.record(
            doc_id=source_sha256,
            source_path=str(args.pdf),
            source_sha256=source_sha256,
            parser_name="marker",
            parser_version="unknown",
            pipeline_version=PIPELINE_VERSION,
            scope=scope,
            status="succeeded" if ok_final else "failed",
            canonical_path=str(canonical) if canonical.exists() else None,
            pages=len(pages),
        )
    return 0 if ok_final else 1


if __name__ == "__main__":
    sys.exit(main())
