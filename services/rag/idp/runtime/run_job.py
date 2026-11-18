"""Bounded service child process; existing queue owns leases and retry attempts."""

import argparse
import hashlib
import json
import os
import signal
import threading
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

from idp.canonical import audit_canonical
from idp.ingest import ingest_file
from idp.orchestration.cli import parse_pages
from idp.orchestration.registry import DocumentRegistry
from idp.orchestration.worker import sha256_file
from idp.pdf.service import (
    DeepDocService,
    legacy_language,
    trusted_native_parsers,
)
from idp.publish import to_v1

from .cache import StageCache, atomic_bytes
from .events import Events
from .lanes import configuration
from .resources import FileLease, HeavyModelLease, cleanup_attempt_containers


def classify(error):
    import sqlite3

    from idp.input.filetypes import InputError
    from idp.ocr.backends.tesseract import BackendUnavailable
    from idp.pdf.native.preflight import PdfAdmissionError
    from idp.pdf.resource import BudgetExceeded

    if isinstance(error, sqlite3.DatabaseError):
        transient = isinstance(error, sqlite3.OperationalError) and any(
            s in str(error).lower() for s in ("locked", "busy")
        )
        return (
            ("IO_FAILURE", True, 75) if transient else ("INVALID_CONTRACT", False, 65)
        )

    if isinstance(error, (ImportError, ModuleNotFoundError)) or isinstance(
        error.__cause__, (ImportError, ModuleNotFoundError)
    ):
        return "BACKEND_UNAVAILABLE", False, 65

    if isinstance(error, InterruptedError):
        return "CANCELLED", False, 130
    if isinstance(error, PermissionError):
        return "PERMISSION_DENIED", False, 65
    if isinstance(error, BudgetExceeded):
        return "RESOURCE_EXHAUSTED", False, 65
    if isinstance(error, PdfAdmissionError):
        return error.diagnostic.code, False, 65
    if isinstance(error, InputError):
        return error.code, error.retryable, 75 if error.retryable else 65
    if isinstance(error, TimeoutError):
        return "DEADLINE_EXCEEDED", True, 124
    if isinstance(error, BackendUnavailable):
        return "BACKEND_UNAVAILABLE", True, 75
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "INVALID_CONTRACT", False, 65
    if isinstance(error, OSError):
        return "IO_FAILURE", True, 75
    return "INTERNAL_FAILURE", False, 70


def execute(request, out, cache_root, *, registry_path=None):
    source = Path(request["pdf_path"])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    sha = sha256_file(source)
    events = Events(out / "events.jsonl", request["job_id"], sha)
    start = time.perf_counter()
    cpu = time.process_time()
    events(stage="job", status="started")
    try:
        if request.get("source_sha256") and request["source_sha256"] != sha:
            raise ValueError("source mismatch")
        opts = request.get("options", {})
        cfg = configuration(**opts)
        logical_config_sha256 = cfg.fingerprint
        if request.get("deadline_at"):
            remaining = request["deadline_at"] - time.time()
            if remaining <= 0:
                raise TimeoutError("job deadline exhausted")
            cfg = replace(cfg, timeout_seconds=min(cfg.timeout_seconds, remaining))
        pages_in_scope = (
            len(parse_pages(request["pages"]))
            if request.get("pages") and source.suffix.lower() == ".pdf"
            else 0
        )
        cache = StageCache(
            cache_root,
            event=events,
            job_id=request["job_id"],
            # The persistent (cross-retry) call budget scales like the job
            # ledger, or long documents exhaust it (audit IDP-002).
            max_backend_calls=cfg.effective_limits(pages_in_scope)["max_calls"],
        )
        if source.suffix.lower() == ".pdf":
            if request.get("pages"):
                cfg = replace(cfg, pages=tuple(parse_pages(request["pages"])))
            lease = (
                HeavyModelLease(
                    Path(cache_root) / "heavy-model.lock",
                    time.monotonic() + cfg.timeout_seconds,
                )
                if cfg.ocr_backend == "marker"
                else nullcontext()
            )
            with lease:
                pools = []
                registry = None
                if cfg.ocr_backend == "marker":
                    from idp.evidence.contracts import DeepDocCapability as C
                    from idp.ocr.backends.advanced import AdvancedBackend
                    from idp.pdf.verify_runtime import (
                        AcquisitionBackendSpec,
                        BackendRegistry,
                    )

                    from .model_pool import JobMarkerTransport

                    def factory(directory):
                        if not pools:
                            pools.append(
                                JobMarkerTransport(
                                    timeout_seconds=cfg.ocr_timeout_seconds
                                )
                            )
                        return AdvancedBackend(directory, pools[0])

                    registry = BackendRegistry(
                        acquisitions=(
                            AcquisitionBackendSpec(
                                "marker",
                                factory,
                                (C.TEXT, C.TABLE, C.MATH, C.FIGURE),
                                2,
                            ),
                        )
                    )
                try:
                    canonical = DeepDocService(
                        cfg, stage_cache=cache, backend_registry=registry
                    ).process_pdf(source, out)
                finally:
                    for pool in pools:
                        pool.close()
            compatibility = (
                to_v1(canonical)
                if canonical.get("schema_version") == "idp-canonical-2"
                else canonical
            )
            audit = audit_canonical(
                compatibility, trusted_parsers=trusted_native_parsers(compatibility)
            )
            review = any(p.get("status") == "review" for p in compatibility["pages"])
        else:
            # Existing readers remain authoritative v1 until verified migration.
            ingest_file(source, out, language=legacy_language(cfg.language))
            canonical = json.loads((out / "canonical.json").read_text(encoding="utf-8"))
            audit = audit_canonical(canonical)
            review = not audit.get("quality_pass", False)
        if canonical.get("source_sha256") != sha:
            raise ValueError("source changed between identity check and extraction")
        if not audit["pass"]:
            raise ValueError("output structural audit failed")
        write = lambda path, value: atomic_bytes(
            path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        )
        # Unified PDF runs measure failed pages and withheld content; the
        # job is only SUCCESS when that measurement says so (audit IDP-008).
        run_report = {}
        report_path = out / "run_report.json"
        if source.suffix.lower() == ".pdf" and report_path.is_file():
            run_report = json.loads(report_path.read_text(encoding="utf-8"))
        status_reasons = list(run_report.get("status_reasons") or ())
        if review and "REVIEW_PAGES" not in status_reasons:
            status_reasons.append("REVIEW_PAGES")
        review = review or bool(status_reasons)
        write(out / "audit_report.json", audit)
        write(
            out / "batch_summary.json",
            {
                "audit_pass": audit["pass"],
                "quality_pass": audit.get("quality_pass"),
                "production_pass": audit.get("production_pass"),
                "runtime": "deepdoc-runtime:1",
                "review": review,
                "review_reasons": status_reasons,
            },
        )
        result = {
            "schema": "deepdoc-job-result:1",
            "job_id": request["job_id"],
            "source_sha256": sha,
            "status": "REVIEW" if review else "SUCCESS",
            "review_reasons": status_reasons,
            "failed_pages": run_report.get("failed_pages", []),
            "publication": run_report.get("publication"),
            "retryable": False,
            "profile": opts.get("profile", "HYBRID"),
            "engine": cfg.engine,
            "canonical_version": canonical.get("schema_version"),
            "attempt_token": request.get("attempt_token"),
            "cache_stats": cache.stats,
            "duration": time.perf_counter() - start,
            "cpu_seconds": time.process_time() - cpu,
        }
        if source.suffix.lower() == ".pdf":
            result["model_loads"] = sum(p.model_loads for p in pools)
            result["model_load_seconds"] = sum(p.model_load_seconds for p in pools)
        try:
            import resource
            import sys

            result["peak_self_rss_bytes"] = resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        except ImportError:
            import psutil

            result["peak_self_rss_bytes"] = getattr(
                psutil.Process().memory_info(), "peak_wset", None
            )
        # A commit manifest binds the canonical and audit envelope after all
        # writes. Canonical v2 references its L1 by hash, so bind it as well.
        hashes = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                out / "canonical.json",
                out / "audit_report.json",
                out / "batch_summary.json",
                out / "extraction.json",
            )
            if p.name != "extraction.json" or p.is_file()
        }
        write(
            out / "commit.json",
            {"schema": "deepdoc-commit:1", "source_sha256": sha, "files": hashes},
        )
        if registry_path:
            # The legacy registry's first-use schema upgrade is check-then-alter.
            # Coordinate its initialization and commit without changing that API
            # or holding a database/lease lock during extraction.
            with FileLease(
                Path(str(registry_path) + ".runtime.lock"), time.monotonic() + 30
            ):
                registry = DocumentRegistry(registry_path)
                registry.record(
                    doc_id=sha,
                    source_path=str(source),
                    source_sha256=sha,
                    parser_name="deepdoc-" + cfg.engine
                    if source.suffix.lower() == ".pdf"
                    else "legacy-reader",
                    parser_version="runtime:1",
                    pipeline_version=logical_config_sha256,
                    scope=request.get("pages", "all"),
                    status="succeeded",
                    canonical_path=str(out / "canonical.json"),
                    pages=len(canonical["pages"]),
                )
        write(out / "runtime_result.json", result)
        events(
            stage="job",
            status=result["status"],
            duration=result["duration"],
            cpu_seconds=result["cpu_seconds"],
            cache_stats=cache.stats,
            rss_bytes=result["peak_self_rss_bytes"],
        )
        for stage, duration in run_report.get("stage_seconds", {}).items():
            events(stage=stage, status="complete", duration=duration)
        return 0
    except Exception as error:  # noqa: BLE001 - safe taxonomy; no document content in errors.
        code, retryable, exit_code = classify(error)
        if request.get("deadline_at") and time.time() >= request["deadline_at"]:
            retryable = False
        result = {
            "schema": "deepdoc-job-result:1",
            "job_id": request["job_id"],
            "source_sha256": sha,
            "status": "FAILED",
            "error_code": code,
            "retryable": retryable,
            "stage": "job",
            "public_message": "Document processing could not complete.",
            "attempt_token": request.get("attempt_token"),
        }
        atomic_bytes(out / "runtime_result.json", json.dumps(result).encode())
        events(
            stage="job",
            status="FAILED",
            error_code=code,
            retryable=retryable,
            duration=time.perf_counter() - start,
        )
        print(json.dumps(result), flush=True)
        return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--registry")
    args = parser.parse_args()

    def cancel(*_):
        raise InterruptedError("cancelled")

    signal.signal(signal.SIGTERM, cancel)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    done = threading.Event()

    def watch_parent():
        import psutil

        pid = int(os.environ["DEEPDOC_PARENT_PID"])
        created = float(os.environ["DEEPDOC_PARENT_CREATED"])
        while not done.wait(0.5):
            try:
                alive = psutil.Process(pid).create_time() == created
            except psutil.Error:
                alive = False
            if not alive:
                if os.name == "nt":
                    # os.kill(SIGTERM) on Windows bypasses Python's handler.
                    # Clean owned descendants/containers and persist a failed
                    # result before terminating, even during blocking native code.
                    for child in psutil.Process().children(recursive=True):
                        try:
                            child.kill()
                            child.wait(timeout=3)
                        except psutil.Error:
                            pass
                    cleanup_attempt_containers(request.get("attempt_token"))
                    result = {
                        "schema": "deepdoc-job-result:1",
                        "job_id": request["job_id"],
                        "status": "FAILED",
                        "error_code": "CANCELLED",
                        "retryable": False,
                        "stage": "parent-watchdog",
                        "attempt_token": request.get("attempt_token"),
                        "public_message": "Worker parent process exited.",
                    }
                    atomic_bytes(
                        Path(args.out) / "runtime_result.json",
                        json.dumps(result).encode(),
                    )
                    os._exit(130)
                os.kill(os.getpid(), signal.SIGTERM)
                return

    watcher = None
    if os.environ.get("DEEPDOC_PARENT_PID") and os.environ.get(
        "DEEPDOC_PARENT_CREATED"
    ):
        watcher = threading.Thread(target=watch_parent, daemon=True)
        watcher.start()
    try:
        return execute(request, args.out, args.cache, registry_path=args.registry)
    finally:
        done.set()
        if watcher:
            watcher.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
