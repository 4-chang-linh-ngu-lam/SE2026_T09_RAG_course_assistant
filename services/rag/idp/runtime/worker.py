"""Opt-in extension of the existing filesystem queue, leases and worker states.

Legacy source is byte-preserved. No parallel queue or schema migration is added.
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from idp.orchestration.worker import JOB_ID_RE, IngestionWorker, utc_now
from idp.orchestration.worker import JobRequest as LegacyJobRequest

from .cache import atomic_bytes
from .events import Events
from .job_contracts import OPTIONS, JobRequest, serialize
from .lanes import configuration
from .resources import FileLease
from .supervisor import SupervisedExecution


# Languages every OCR lane can be asked for ("auto" probes and picks one).
REQUIRED_OCR_LANGUAGES = ("vie", "eng")


def check_ocr_backend(languages=REQUIRED_OCR_LANGUAGES):
    """Fail at worker start when Tesseract or its traineddata is missing.

    Without it every scan page goes to REVIEW one document at a time instead
    of failing the deployment once (audit IDP-006). Returns the version line.
    """
    from idp.ocr.backends.tesseract import TesseractBackend, TesseractConfig

    backend = TesseractBackend(None, TesseractConfig("+".join(languages)))
    return backend.producer.version


class RuntimeWorker(SupervisedExecution, IngestionWorker):
    def __init__(
        self,
        *args,
        use_service=False,
        cache_root=None,
        max_worker_rss_mb=1024,
        **kwargs,
    ):
        if type(max_worker_rss_mb) is not int or max_worker_rss_mb < 1:
            raise ValueError("positive worker RSS budget required")
        self.max_worker_rss_mb = max_worker_rss_mb
        self.use_service = use_service
        super().__init__(*args, **kwargs)
        # The module package root is rag, not rag/idp, for child -m imports.
        if use_service:
            self.package_root = Path(__file__).resolve().parents[2]
        self.cache_root = Path(cache_root or self.work_root / "stage-cache")
        if self.use_service and not JOB_ID_RE.fullmatch(self.worker_id):
            raise ValueError("invalid worker_id")

    def _write_worker_status(self, **fields):
        if not self.use_service:
            return super()._write_worker_status(**fields)
        value = {
            "worker_id": self.worker_id,
            "pid": os.getpid(),
            "updated_at": utc_now(),
            **fields,
        }
        payload = json.dumps(value).encode()
        atomic_bytes(self.work_root / "workers" / (self.worker_id + ".json"), payload)
        atomic_bytes(self.work_root / "worker_status.json", payload)

    def _update_status(self, job_id, **fields):
        if not self.use_service:
            return super()._update_status(job_id, **fields)
        with FileLease(self._job_dir(job_id) / "status.lock", time.monotonic() + 30):
            current = self._status(job_id)
            if (
                fields.get("state") == "running"
                and "attempt" not in fields
                and current.get("state") in {"succeeded", "failed", "retry"}
            ):
                return current
            current.update(fields)
            current.update(job_id=job_id, updated_at=utc_now())
            atomic_bytes(self._status_path(job_id), json.dumps(current).encode())
            return current

    def enqueue(self, data):
        if not self.use_service:
            return super().enqueue(data)
        job = JobRequest.from_dict(data, self.input_roots)
        with FileLease(self.queue / "enqueue.lock", time.monotonic() + 30):
            return super().enqueue(serialize(job))

    def recover_stale(self):
        if not self.use_service:
            return super().recover_stale()
        with FileLease(self.queue / "recovery.lock", time.monotonic() + 30):
            return super().recover_stale()

    def claim_next(self):
        self._current_job = None
        if not self.use_service:
            return super().claim_next()
        with FileLease(self.queue / "claim.lock", time.monotonic() + 30):
            return self._claim_service_job()

    def _claim_service_job(self):
        for source in sorted(self.dirs["incoming"].glob("*.json")):
            if self._status(source.stem).get("next_retry_at", 0) > time.time():
                continue
            target = self.dirs["running"] / source.name
            if target.exists():
                continue
            try:
                os.replace(source, target)
            except OSError:
                continue
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                data.setdefault("job_id", source.stem)
                if data["job_id"] != source.stem:
                    raise ValueError("queue identity mismatch")
                if OPTIONS in data.get("metadata", {}):
                    configuration(**data["metadata"][OPTIONS])
                    job = LegacyJobRequest.from_dict(data, self.input_roots)
                else:
                    job = JobRequest.from_dict(data, self.input_roots)
            except (ValueError, TypeError, OSError, KeyError):
                os.replace(target, self.dirs["failed"] / target.name)
                self._update_status(
                    source.stem, state="failed", error="INVALID_JOB", attempt=0
                )
                continue
            self._current_job = job.job_id
            return target, job
        return None

    def _command(self, job, out_dir):
        if not self.use_service:
            return super()._command(job, out_dir)
        request = {
            "job_id": job.job_id,
            "pdf_path": str(job.pdf_path),
            "pages": job.pages,
            "source_sha256": job.source_sha256,
            "options": job.metadata.get(OPTIONS, {}),
            "attempt_token": uuid.uuid4().hex,
        }
        deadline_file = self._job_dir(job.job_id) / "deadline.json"
        if not deadline_file.exists():
            atomic_bytes(
                deadline_file,
                json.dumps(
                    {
                        "deadline_at": time.time()
                        + configuration(**request["options"]).timeout_seconds
                    }
                ).encode(),
            )
        request.update(json.loads(deadline_file.read_text()))
        path = self._job_dir(job.job_id) / "service-request.json"
        atomic_bytes(path, json.dumps(request).encode())
        return [
            sys.executable,
            "-m",
            "idp.runtime.run_job",
            "--request",
            str(path),
            "--out",
            str(out_dir),
            "--cache",
            str(self.cache_root),
            "--registry",
            str(self.work_root / "documents.sqlite3"),
        ]

    def run_once(self):
        self._transition_lease = None
        try:
            outcome = super().run_once()
            return self._finish_attempt(outcome)
        finally:
            if self._transition_lease is not None:
                self._transition_lease.__exit__(None, None, None)
                self._transition_lease = None

    def _execute_batch(self, *args):
        if not self.use_service:
            return super()._execute_batch(*args)
        try:
            return super()._execute_batch(*args)
        finally:
            # The legacy loop requeues before runtime error/backoff classification.
            # Exclude claims only during that short transition, never inference.
            lease = FileLease(self.queue / "claim.lock", time.monotonic() + 30)
            lease.__enter__()
            self._transition_lease = lease

    def _finish_attempt(self, outcome):
        if not self.use_service or not self._current_job:
            return outcome
        job = self._current_job
        directory = self._job_dir(job)
        result_path = directory / "result.json"
        if not result_path.exists():
            return outcome
        result = json.loads(result_path.read_text())
        request_path = directory / "service-request.json"
        child = directory / "out/runtime_result.json"
        report = json.loads(child.read_text()) if child.exists() else {}
        request = json.loads(request_path.read_text()) if request_path.exists() else {}
        if report.get("attempt_token") != request.get("attempt_token"):
            report = {}
        if report:
            result.update(
                runtime=report,
                engine=report.get("engine", "unified"),
                mode=report.get("profile"),
                error=report.get("error_code"),
            )
        elif outcome != "succeeded":
            result["error"] = "WORKER_PROCESS_FAILURE"
        queued = self.dirs["incoming"] / (job + ".json")
        if outcome == "retry" and report and not report.get("retryable", False):
            os.replace(queued, self.dirs["failed"] / queued.name)
            result["error"] = report.get("error_code", "OUTPUT_VALIDATION_FAILED")
            self._update_status(job, state="failed", error=result["error"])
            outcome = "failed"
        elif outcome == "retry":
            attempt = self._status(job).get("attempt", 1)
            self._update_status(
                job,
                next_retry_at=time.time() + min(60, 2**attempt),
                error=result["error"],
            )
        atomic_bytes(result_path, json.dumps(result).encode())
        Events(directory / "worker-events.jsonl", job, result["source_sha256"])(
            stage="worker",
            status=outcome,
            error_code=result.get("error"),
            retryable=report.get("retryable", outcome == "retry"),
        )
        return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--allowed-input-root", action="append", required=True)
    parser.add_argument(
        "--use-service",
        action="store_true",
        help="default false; legacy execution remains default",
    )
    parser.add_argument("--enqueue")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cache-root")
    parser.add_argument("--job-timeout", type=int, default=1800)
    parser.add_argument("--max-worker-rss-mb", type=int, default=1024)
    parser.add_argument(
        "--allow-missing-ocr",
        action="store_true",
        help="start without Tesseract (scan pages then stay in REVIEW)",
    )
    args = parser.parse_args()
    if args.use_service and not args.enqueue and not args.allow_missing_ocr:
        from idp.ocr.backends.tesseract import BackendUnavailable

        try:
            check_ocr_backend()
        except BackendUnavailable as error:
            sys.stderr.write(
                f"OCR backend unavailable: {error}. Install Tesseract with "
                f"{'+'.join(REQUIRED_OCR_LANGUAGES)} traineddata or pass "
                "--allow-missing-ocr.\n"
            )
            return 78
    worker = RuntimeWorker(
        args.queue_dir,
        args.work_root,
        args.allowed_input_root,
        "marker_single",
        use_service=args.use_service,
        cache_root=args.cache_root,
        job_timeout=args.job_timeout,
        max_worker_rss_mb=args.max_worker_rss_mb,
    )
    if args.enqueue:
        worker.enqueue(json.loads(Path(args.enqueue).read_text(encoding="utf-8")))
        return 0
    if args.once:
        worker.recover_stale()
        return 0 if worker.run_once() in (None, "succeeded") else 1
    return worker.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
