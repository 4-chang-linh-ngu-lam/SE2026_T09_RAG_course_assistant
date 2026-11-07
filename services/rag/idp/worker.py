from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .cli import parse_pages

JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
KNOWN_JOB_FIELDS = {
    "schema_version", "job_id", "pdf_path", "pages", "dpi",
    "image_dir", "marker_dir", "gold_path", "source_sha256", "metadata",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return data[-limit:]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class JobRequest:
    job_id: str
    pdf_path: Path
    pages: str
    dpi: int = 300
    image_dir: Path | None = None
    marker_dir: Path | None = None
    gold_path: Path | None = None
    source_sha256: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict, input_roots: list[Path]) -> "JobRequest":
        if not isinstance(data, dict):
            raise ValueError("job must be a JSON object")
        unknown = set(data) - KNOWN_JOB_FIELDS
        if unknown:
            raise ValueError(f"unknown job fields: {sorted(unknown)}")
        if data.get("schema_version", 1) != 1:
            raise ValueError("unsupported schema_version")
        job_id = str(data.get("job_id") or "")
        if not JOB_ID_RE.fullmatch(job_id):
            raise ValueError("invalid job_id")
        pdf_raw = data.get("pdf_path")
        if not pdf_raw:
            raise ValueError("pdf_path is required")
        pdf = _resolve_input(Path(pdf_raw), input_roots, "pdf_path")
        if not pdf.is_file():
            raise ValueError("pdf_path does not exist or is not a file")
        pages_value = data.get("pages")
        if isinstance(pages_value, list):
            pages_value = ",".join(str(x) for x in pages_value)
        if not isinstance(pages_value, str):
            raise ValueError("pages must be a string or list")
        try:
            pages = parse_pages(pages_value)
        except Exception as exc:
            raise ValueError(f"invalid pages: {exc}") from exc
        if not pages or any(page <= 0 for page in pages):
            raise ValueError("pages must contain positive page numbers")
        dpi = data.get("dpi", 300)
        if not isinstance(dpi, int) or not 72 <= dpi <= 600:
            raise ValueError("dpi must be an integer in [72, 600]")
        image_dir = _optional_input(data.get("image_dir"), input_roots, "image_dir")
        marker_dir = _optional_input(data.get("marker_dir"), input_roots, "marker_dir")
        gold_path = _optional_input(data.get("gold_path"), input_roots, "gold_path")
        if image_dir is not None and not image_dir.is_dir():
            raise ValueError("image_dir does not exist or is not a directory")
        if marker_dir is not None and not marker_dir.is_dir():
            raise ValueError("marker_dir does not exist or is not a directory")
        if gold_path is not None and not gold_path.is_file():
            raise ValueError("gold_path does not exist or is not a file")
        source_sha256 = data.get("source_sha256")
        if source_sha256 is not None:
            source_sha256 = str(source_sha256).lower()
            if not SHA256_RE.fullmatch(source_sha256):
                raise ValueError("source_sha256 must be 64 hex characters")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 64 * 1024:
            raise ValueError("metadata is too large")
        return cls(
            job_id=job_id, pdf_path=pdf, pages=",".join(str(x) for x in pages),
            dpi=dpi, image_dir=image_dir, marker_dir=marker_dir,
            gold_path=gold_path, source_sha256=source_sha256, metadata=metadata,
        )


def _resolve_input(path: Path, roots: list[Path], label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not any(_inside(resolved, root.resolve()) for root in roots):
        raise ValueError(f"{label} is outside allowed input roots")
    return resolved


def _optional_input(value: Any, roots: list[Path], label: str) -> Path | None:
    if value in (None, ""):
        return None
    path = _resolve_input(Path(str(value)), roots, label)
    return path


class IngestionWorker:
    def __init__(
        self,
        queue_dir: str | Path,
        work_root: str | Path,
        input_roots: list[str | Path],
        marker_bin: str,
        llama_bin: str | None = None,
        worker_id: str | None = None,
        marker_timeout: int = 360,
        run_marker: bool = True,
        fast_fallback: bool = True,
        repair_math: bool = True,
        preprocess: bool = False,
        allow_layout_failure: bool = True,
        audit: bool = True,
        fast_preview: bool = False,
        max_attempts: int = 2,
        stale_seconds: int = 7200,
        job_timeout: int = 0,
        poll_seconds: float = 10.0,
        heartbeat_seconds: float = 30.0,
        fallback_engine: str = "auto",
        fallback_cmd: str | None = None,
        fallback_timeout: int = 300,
        fallback_lang: str = "vie",
        profile: str = "general",
        language: str | None = None,
        chart_cmd: str | None = None,
        chart_timeout: int = 120,
        figure_cmd: str | None = None,
        figure_timeout: int = 120,
        workers: int = 1,
        verify_cmd: str | None = None,
        verify_timeout: int = 600,
        verify_max_pages: int = 0,
        trusted_parsers: list[str] | None = None,
        quality_layout_model_dir: str | Path | None = None,
        quality_url: str = "http://127.0.0.1:8081",
        quality_revision: str | None = None,
        hybrid_layout_model_dir: str | Path | None = None,
        hybrid_tessdata_dir: str | Path | None = None,
        hybrid_url: str = "http://127.0.0.1:8081",
        hybrid_revision: str | None = None,
        hybrid_max_pixels: int = 1_600_000,
        hybrid_repetition_penalty: float | None = None,
        hybrid_label_detector_model_dir: str | Path | None = None,
        hybrid_rectify_labels: bool = False,
        hybrid_question_context_max: int = 0,
        hybrid_question_context_mode: str = 'linked',
        hybrid_orientation_model_dir: str | Path | None = None,
        hybrid_source_window_max: int = 0,
        execute: Callable[[JobRequest, Path, Path], int] | None = None,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if type(hybrid_question_context_max) is not int or not 0<=hybrid_question_context_max<=16:
            raise ValueError('invalid hybrid whole-question budget')
        if type(hybrid_source_window_max) is not int or not 0<=hybrid_source_window_max<=16:raise ValueError('invalid hybrid source window budget')
        if not isinstance(hybrid_question_context_mode,str) or hybrid_question_context_mode not in {'single','linked'}:
            raise ValueError('invalid hybrid question mode')
        if type(hybrid_rectify_labels) is not bool or (hybrid_rectify_labels and not hybrid_label_detector_model_dir):
            raise ValueError('hybrid label rectification requires a local text detector')
        if type(hybrid_max_pixels) is not int or not 4096<=hybrid_max_pixels<=16_000_000:
            raise ValueError("invalid hybrid CPU pixel limit")
        if hybrid_repetition_penalty is not None and (type(hybrid_repetition_penalty) not in {int,float}
                or not math.isfinite(hybrid_repetition_penalty) or hybrid_repetition_penalty<=0):
            raise ValueError("invalid hybrid repetition penalty")
        if hybrid_layout_model_dir:
            from .completion import local_origin
            local_origin(hybrid_url)
            if (quality_layout_model_dir or fast_preview or not audit or job_timeout <= 0
                    or trusted_parsers or not hybrid_tessdata_dir
                    or not isinstance(hybrid_revision, str) or not hybrid_revision.strip()):
                raise ValueError("hybrid runtime requires exclusive mode, pinned tessdata/revision, audit, hard timeout and no parser trust")
        elif (hybrid_tessdata_dir or hybrid_revision or hybrid_repetition_penalty is not None
                or hybrid_max_pixels!=1_600_000 or hybrid_label_detector_model_dir or hybrid_question_context_max
                or hybrid_question_context_mode!='linked' or hybrid_orientation_model_dir or hybrid_source_window_max):
            raise ValueError("hybrid configuration requires a local layout model")
        self.hybrid_layout_model_dir = Path(hybrid_layout_model_dir).resolve() if hybrid_layout_model_dir else None
        self.hybrid_tessdata_dir = Path(hybrid_tessdata_dir).resolve() if hybrid_tessdata_dir else None
        self.hybrid_url, self.hybrid_revision = hybrid_url, hybrid_revision
        self.hybrid_max_pixels,self.hybrid_repetition_penalty=hybrid_max_pixels,hybrid_repetition_penalty
        self.hybrid_label_detector_model_dir=Path(hybrid_label_detector_model_dir).resolve() if hybrid_label_detector_model_dir else None
        self.hybrid_rectify_labels=hybrid_rectify_labels
        self.hybrid_question_context_max=hybrid_question_context_max
        self.hybrid_question_context_mode=hybrid_question_context_mode
        self.hybrid_orientation_model_dir=Path(hybrid_orientation_model_dir).resolve() if hybrid_orientation_model_dir else None
        self.hybrid_source_window_max=hybrid_source_window_max
        if quality_layout_model_dir:
            from .completion import local_origin
            local_origin(quality_url)
            if not quality_revision or not quality_revision.strip():
                raise ValueError("quality runtime requires an immutable model/server revision")
            if job_timeout <= 0 or fast_preview or not audit:
                raise ValueError("quality runtime requires a hard job timeout, audit, and quality mode")
            if trusted_parsers:
                raise ValueError("quality runtime does not grant parser trust; evaluate the runtime first")
        elif quality_revision:
            raise ValueError("quality revision requires a local layout model")
        self.quality_layout_model_dir = Path(quality_layout_model_dir).resolve() if quality_layout_model_dir else None
        self.quality_url, self.quality_revision = quality_url, quality_revision
        self.queue = Path(queue_dir).resolve()
        self.work_root = Path(work_root).resolve()
        self.input_roots = [Path(root).resolve() for root in input_roots]
        if not self.input_roots:
            raise ValueError("at least one input root is required")
        self.marker_bin = marker_bin
        self.llama_bin = llama_bin
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.marker_timeout = marker_timeout
        self.run_marker = run_marker
        self.fast_fallback = fast_fallback
        self.repair_math = repair_math
        self.preprocess = preprocess
        self.allow_layout_failure = allow_layout_failure
        self.audit = audit and not fast_preview
        self.fast_preview = fast_preview
        self.max_attempts = max_attempts
        self.stale_seconds = stale_seconds
        self.job_timeout = job_timeout
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.fallback_engine = fallback_engine
        self.fallback_cmd = fallback_cmd
        self.fallback_timeout = fallback_timeout
        self.fallback_lang = fallback_lang
        self.profile = profile
        self.language = language
        self.chart_cmd = chart_cmd
        self.chart_timeout = chart_timeout
        self.figure_cmd = figure_cmd
        self.figure_timeout = figure_timeout
        self.workers = workers
        self.verify_cmd = verify_cmd
        self.verify_timeout = verify_timeout
        self.verify_max_pages = verify_max_pages
        self.trusted_parsers = list(trusted_parsers or [])
        self._execute = execute or self._execute_batch
        self.stop = threading.Event()
        self.current_proc: subprocess.Popen | None = None
        self.dirs = {
            name: self.queue / name
            for name in ("incoming", "running", "done", "failed")
        }
        for directory in self.dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        (self.work_root / "jobs").mkdir(parents=True, exist_ok=True)
        self.package_root = Path(__file__).resolve().parent.parent

    def _status_path(self, job_id: str) -> Path:
        return self.work_root / "jobs" / job_id / "status.json"

    def _job_dir(self, job_id: str) -> Path:
        return self.work_root / "jobs" / job_id

    def _write_worker_status(self, **fields: Any) -> None:
        payload = {
            "worker_id": self.worker_id,
            "pid": os.getpid(),
            "updated_at": utc_now(),
            **fields,
        }
        _atomic_write_json(self.work_root / "worker_status.json", payload)

    def _status(self, job_id: str) -> dict:
        path = self._status_path(job_id)
        if not path.exists():
            return {}
        return _read_json(path)

    def _update_status(self, job_id: str, **fields: Any) -> dict:
        current = self._status(job_id)
        current.update(fields)
        current["job_id"] = job_id
        current["updated_at"] = utc_now()
        _atomic_write_json(self._status_path(job_id), current)
        return current

    def enqueue(self, data: dict) -> Path:
        job = JobRequest.from_dict(data, self.input_roots)
        target = self.dirs["incoming"] / f"{job.job_id}.json"
        if any((directory / target.name).exists() for directory in self.dirs.values()):
            raise FileExistsError(f"job already exists: {job.job_id}")
        _atomic_write_json(target, data)
        return target

    def claim_next(self) -> tuple[Path, JobRequest] | None:
        for source in sorted(self.dirs["incoming"].glob("*.json")):
            target = self.dirs["running"] / source.name
            try:
                os.replace(source, target)
            except FileNotFoundError:
                continue
            except OSError:
                continue
            try:
                data = _read_json(target)
                job = JobRequest.from_dict(data, self.input_roots)
            except Exception as exc:
                failed = self.dirs["failed"] / target.name
                os.replace(target, failed)
                _atomic_write_json(self._job_dir(source.stem) / "status.json", {
                    "job_id": source.stem,
                    "state": "failed",
                    "error": f"invalid job: {exc}",
                    "attempt": 0,
                    "updated_at": utc_now(),
                })
                continue
            return target, job
        return None

    def recover_stale(self) -> list[str]:
        recovered = []
        now = time.time()
        for running in sorted(self.dirs["running"].glob("*.json")):
            status = self._status(running.stem)
            state = status.get("state")
            if state == "succeeded":
                os.replace(running, self.dirs["done"] / running.name)
                recovered.append(running.stem)
                continue
            if state == "failed":
                os.replace(running, self.dirs["failed"] / running.name)
                recovered.append(running.stem)
                continue
            updated = status.get("updated_at")
            try:
                updated_ts = datetime.fromisoformat(str(updated)).timestamp()
            except Exception:
                updated_ts = running.stat().st_mtime
            if now - updated_ts <= self.stale_seconds:
                continue
            target = self.dirs["incoming"] / running.name
            if target.exists():
                continue
            os.replace(running, target)
            self._update_status(
                running.stem,
                state="retry",
                error="stale lease requeued",
            )
            recovered.append(running.stem)
        return recovered

    def _command(self, job: JobRequest, out_dir: Path) -> list[str]:
        if self.hybrid_layout_model_dir:
            command = [sys.executable, "-m", "idp.hybrid_runtime", "--input", str(job.pdf_path),
                "--pages", job.pages, "--out", str(out_dir), "--dpi", str(job.dpi),
                "--layout-model-dir", str(self.hybrid_layout_model_dir),
                "--tessdata-dir", str(self.hybrid_tessdata_dir), "--url", self.hybrid_url,
                "--revision", self.hybrid_revision, "--language", self.language or self.fallback_lang,
                "--max-pixels",str(self.hybrid_max_pixels)]
            if self.hybrid_repetition_penalty is not None:
                command.extend(["--context-repetition-penalty",str(self.hybrid_repetition_penalty)])
            if self.hybrid_label_detector_model_dir:
                command.extend(['--label-detector-model-dir',str(self.hybrid_label_detector_model_dir)])
            if self.hybrid_rectify_labels:command.append('--rectify-labels')
            if self.hybrid_question_context_max:
                command.extend(['--question-context-max',str(self.hybrid_question_context_max)])
                command.extend(['--question-context-mode',self.hybrid_question_context_mode])
            if self.hybrid_orientation_model_dir:
                command.extend(['--orientation-model-dir',str(self.hybrid_orientation_model_dir)])
            if self.hybrid_source_window_max:command.extend(['--source-window-max',str(self.hybrid_source_window_max)])
            return command
        if self.quality_layout_model_dir:
            return [sys.executable, "-m", "idp.quality_runtime", "--input", str(job.pdf_path),
                "--pages", job.pages, "--out", str(out_dir), "--dpi", str(job.dpi),
                "--layout-model-dir", str(self.quality_layout_model_dir), "--url", self.quality_url,
                "--revision", self.quality_revision, "--language", self.language or self.fallback_lang, "--resume"]
        if self.fast_preview:
            return [
                sys.executable, "-m", "idp.fast",
                "--pdf", str(job.pdf_path), "--pages", job.pages,
                "--out", str(out_dir), "--dpi", str(job.dpi),
                "--lang", self.fallback_lang, "--profile", self.profile,
            ]
        command = [
            sys.executable, "-m", "idp.batch",
            "--pdf", str(job.pdf_path), "--pages", job.pages,
            "--out", str(out_dir), "--dpi", str(job.dpi),
            "--marker-timeout", str(self.marker_timeout),
            "--marker-bin", self.marker_bin,
        ]
        if self.llama_bin:
            command.extend(["--llama-bin", self.llama_bin])
        if self.run_marker:
            command.append("--run-marker")
        if self.fast_fallback:
            command.append("--fast-fallback")
        command.extend([
            "--fallback-engine", self.fallback_engine,
            "--fallback-timeout", str(self.fallback_timeout),
            "--fallback-lang", self.fallback_lang,
            "--profile", self.profile,
        ])
        if self.language:
            command.extend(["--language", self.language])
        if self.chart_cmd:
            command.extend([
                "--chart-cmd", self.chart_cmd,
                "--chart-timeout", str(self.chart_timeout),
            ])
        if self.figure_cmd:
            command.extend([
                "--figure-cmd", self.figure_cmd,
                "--figure-timeout", str(self.figure_timeout),
            ])
        if self.workers != 1:
            command.extend(["--workers", str(self.workers)])
        if self.fallback_cmd:
            command.extend(["--fallback-cmd", self.fallback_cmd])
        if self.verify_cmd:
            command.extend([
                "--verify-cmd", self.verify_cmd,
                "--verify-timeout", str(self.verify_timeout),
                "--verify-max-pages", str(self.verify_max_pages),
            ])
        for parser_name in self.trusted_parsers:
            command.extend(["--trusted-parser", parser_name])
        if self.repair_math:
            command.append("--repair-math")
        if self.preprocess:
            command.append("--preprocess")
        if self.allow_layout_failure:
            command.append("--allow-layout-failure")
        if self.audit:
            command.append("--audit")
        if job.image_dir:
            command.extend(["--image-dir", str(job.image_dir)])
        if job.marker_dir:
            command.extend(["--marker-dir", str(job.marker_dir)])
        if job.gold_path:
            command.extend(["--gold", str(job.gold_path)])
        return command

    def _execute_batch(
        self, job: JobRequest, out_dir: Path, log_path: Path
    ) -> int:
        command = self._command(job, out_dir)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(self.package_root) + os.pathsep + env.get("PYTHONPATH", "")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"{utc_now()} COMMAND {json.dumps(command, ensure_ascii=False)}\n")
            log.flush()
            self.current_proc = subprocess.Popen(
                command, cwd=self.package_root, env=env,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                timeout = self.job_timeout or None
                return self.current_proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._terminate_current()
                log.write(f"{utc_now()} TIMEOUT after {self.job_timeout}s\n")
                return 124
            finally:
                self.current_proc = None

    def _terminate_current(self) -> None:
        proc = self.current_proc
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _heartbeat(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_seconds):
            self._update_status(job_id, state="running", updated_at=utc_now())
            self._write_worker_status(state="running", current_job=job_id)

    def run_once(self) -> str | None:
        claimed = self.claim_next()
        if claimed is None:
            return None
        running_path, job = claimed
        job_dir = self._job_dir(job.job_id)
        out_dir = job_dir / "out"
        log_path = job_dir / "batch.log"
        prior = self._status(job.job_id)
        attempt = int(prior.get("attempt", 0)) + 1
        job_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(job_dir / "request.json", {
            "job_id": job.job_id, "pdf_path": str(job.pdf_path),
            "pages": job.pages, "dpi": job.dpi,
            "image_dir": str(job.image_dir) if job.image_dir else None,
            "marker_dir": str(job.marker_dir) if job.marker_dir else None,
            "gold_path": str(job.gold_path) if job.gold_path else None,
            "source_sha256": job.source_sha256, "metadata": job.metadata,
        })
        started = utc_now()
        self._update_status(
            job.job_id, state="running", attempt=attempt,
            worker_id=self.worker_id, started_at=started,
            out_dir=str(out_dir), error=None,
        )
        self._write_worker_status(state="running", current_job=job.job_id)

        actual_sha = sha256_file(job.pdf_path)
        if job.source_sha256:
            if actual_sha != job.source_sha256:
                finished = utc_now()
                self._update_status(
                    job.job_id, state="failed",
                    error="source_sha256 mismatch",
                    actual_sha256=actual_sha, finished_at=finished,
                )
                _atomic_write_json(job_dir / "result.json", {
                    "job_id": job.job_id, "state": "failed",
                    "attempt": attempt, "exit_code": None,
                    "started_at": started, "finished_at": finished,
                    "out_dir": str(out_dir), "error": "source_sha256 mismatch",
                    "audit_pass": None, "pipeline_version": None,
                    "source_sha256": actual_sha, "metadata": job.metadata,
                })
                os.replace(running_path, self.dirs["failed"] / running_path.name)
                self._write_worker_status(state="idle", current_job=None)
                return "failed"

        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat, args=(job.job_id, heartbeat_stop), daemon=True
        )
        heartbeat.start()
        try:
            code = self._execute(job, out_dir, log_path)
        except Exception as exc:
            code = 1
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"{utc_now()} EXCEPTION {exc}\n")
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            self.current_proc = None

        summary_path = out_dir / "batch_summary.json"
        summary = _read_json(summary_path) if summary_path.exists() else {}
        report_path = out_dir / "report.json"
        report = _read_json(report_path) if report_path.exists() else {}
        audit_path = out_dir / "audit_report.json"
        succeeded = code == 0
        if self.fast_preview:
            succeeded = succeeded and not report.get("output_validation_errors")
        elif self.audit and not summary.get("audit_pass"):
            succeeded = False
        if not self.fast_preview and report.get("ingestion_pass") is False:
            succeeded = False
        if (
            not self.fast_preview
            and report.get("ingestion_review_assisted_pass") is False
        ):
            succeeded = False
        result = {
            "job_id": job.job_id,
            "state": "succeeded" if succeeded else "failed",
            "attempt": attempt,
            "exit_code": code,
            "started_at": started,
            "finished_at": utc_now(),
            "out_dir": str(out_dir),
            "batch_summary": str(summary_path) if summary_path.exists() else None,
            "audit_report": str(audit_path) if audit_path.exists() else None,
            "audit_pass": summary.get("audit_pass"),
            "ingestion_pass": report.get("ingestion_pass"),
            "ingestion_quality_pass": report.get("ingestion_quality_pass"),
            "ingestion_review_assisted_pass": report.get("ingestion_review_assisted_pass"),
            "ingestion_production_pass": report.get("ingestion_production_pass"),
            "ingestion_auto_publish_pass": report.get("ingestion_auto_publish_pass"),
            "ingestion_quality_certified": report.get("ingestion_quality_certified"),
            "pipeline_version": report.get("pipeline_version") or summary.get("pipeline_version"),
            "mode": "hybrid" if self.hybrid_layout_model_dir else ("fast_preview" if self.fast_preview else "quality"),
            "engine": "cpu_hybrid_runtime" if self.hybrid_layout_model_dir else ("paddleocr_vl_runtime" if self.quality_layout_model_dir else ("fast" if self.fast_preview else "marker")),
            "publishable_chunks": report.get("publishable_chunks"),
            "source_sha256": actual_sha,
            "metadata": job.metadata,
        }
        if succeeded:
            _atomic_write_json(job_dir / "result.json", result)
            self._update_status(
                job.job_id, state="succeeded", exit_code=code,
                finished_at=result["finished_at"], error=None,
            )
            os.replace(running_path, self.dirs["done"] / running_path.name)
            self._write_worker_status(state="idle", current_job=None)
            return "succeeded"

        result["error"] = _tail(log_path)
        _atomic_write_json(job_dir / "result.json", result)
        if attempt < self.max_attempts:
            self._update_status(
                job.job_id, state="retry", exit_code=code,
                error=result["error"], finished_at=result["finished_at"],
            )
            os.replace(running_path, self.dirs["incoming"] / running_path.name)
            self._write_worker_status(state="idle", current_job=None)
            return "retry"
        self._update_status(
            job.job_id, state="failed", exit_code=code,
            error=result["error"], finished_at=result["finished_at"],
        )
        os.replace(running_path, self.dirs["failed"] / running_path.name)
        self._write_worker_status(state="idle", current_job=None)
        return "failed"

    def _on_signal(self, signum, frame) -> None:
        self.stop.set()
        self._terminate_current()

    def run_forever(self) -> int:
        self.recover_stale()
        self._write_worker_status(state="idle", current_job=None)
        previous = None
        try:
            previous = signal.signal(signal.SIGTERM, self._on_signal)
        except (AttributeError, ValueError):
            pass
        try:
            while not self.stop.is_set():
                outcome = self.run_once()
                if outcome is None:
                    self.stop.wait(self.poll_seconds)
        except KeyboardInterrupt:
            self.stop.set()
            self._terminate_current()
        finally:
            if previous is not None:
                try:
                    signal.signal(signal.SIGTERM, previous)
                except (AttributeError, ValueError):
                    pass
            self._write_worker_status(state="stopped", current_job=None)
        return 0


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue-backed IDP ingestion worker")
    parser.add_argument("--queue-dir")
    parser.add_argument("--enqueue")
    parser.add_argument("--work-root")
    parser.add_argument("--allowed-input-root", action="append", default=[])
    parser.add_argument("--marker-bin", default="marker_single")
    parser.add_argument("--llama-bin", default=os.environ.get("LLAMA_CPP_BINARY"))
    parser.add_argument("--marker-timeout", type=int, default=360)
    parser.add_argument("--no-run-marker", action="store_true")
    parser.add_argument("--no-fast-fallback", action="store_true")
    parser.add_argument(
        "--fallback-engine", choices=["auto", "none", "tesseract", "command"],
        default="auto",
    )
    parser.add_argument("--fallback-cmd", default=os.environ.get("IDP_FALLBACK_CMD"))
    parser.add_argument("--fallback-timeout", type=int, default=300)
    parser.add_argument("--fallback-lang", default="vie")
    parser.add_argument("--verify-cmd", default=os.environ.get("IDP_VERIFY_CMD"))
    parser.add_argument("--verify-timeout", type=int, default=600)
    parser.add_argument("--verify-max-pages", type=int, default=0)
    parser.add_argument("--trusted-parser", action="append", default=None)
    parser.add_argument("--no-repair-math", action="store_true")
    parser.add_argument("--preprocess", action="store_true")
    parser.add_argument("--no-allow-layout-failure", action="store_true")
    parser.add_argument("--no-audit", action="store_true")
    parser.add_argument("--fast-preview", action="store_true")
    parser.add_argument("--quality-layout-model-dir", type=Path)
    parser.add_argument("--quality-url", default="http://127.0.0.1:8081")
    parser.add_argument("--quality-revision")
    parser.add_argument("--hybrid-layout-model-dir", type=Path)
    parser.add_argument("--hybrid-tessdata-dir", type=Path)
    parser.add_argument("--hybrid-url", default="http://127.0.0.1:8081")
    parser.add_argument("--hybrid-revision")
    parser.add_argument("--hybrid-max-pixels",type=int,default=1_600_000)
    parser.add_argument("--hybrid-repetition-penalty",type=float)
    parser.add_argument('--hybrid-label-detector-model-dir',type=Path)
    parser.add_argument('--hybrid-rectify-labels',action='store_true')
    parser.add_argument('--hybrid-question-context-max',type=int,default=0)
    parser.add_argument('--hybrid-question-context-mode',choices=('single','linked'),default='linked')
    parser.add_argument('--hybrid-orientation-model-dir',type=Path)
    parser.add_argument('--hybrid-source-window-max',type=int,default=0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--stale-seconds", type=int, default=7200)
    parser.add_argument("--job-timeout", type=int, default=0)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--worker-id", default=default_worker_id())
    args = parser.parse_args()

    if not args.allowed_input_root:
        parser.error("--allowed-input-root is required")
    if args.enqueue:
        if not args.queue_dir or not args.work_root:
            parser.error("--queue-dir and --work-root are required with --enqueue")
        worker = IngestionWorker(
            args.queue_dir, args.work_root, args.allowed_input_root,
            args.marker_bin, args.llama_bin, worker_id=args.worker_id,
        )
        data = _read_json(Path(args.enqueue))
        data.setdefault("job_id", Path(args.enqueue).stem)
        worker.enqueue(data)
        print(json.dumps({"queued": data["job_id"]}, ensure_ascii=False))
        return 0
    if not args.queue_dir or not args.work_root:
        parser.error("--queue-dir and --work-root are required")

    worker = IngestionWorker(
        queue_dir=args.queue_dir, work_root=args.work_root,
        input_roots=args.allowed_input_root, marker_bin=args.marker_bin,
        llama_bin=args.llama_bin, worker_id=args.worker_id,
        marker_timeout=args.marker_timeout, run_marker=not args.no_run_marker,
        fast_fallback=not args.no_fast_fallback, repair_math=not args.no_repair_math,
        fallback_engine=args.fallback_engine, fallback_cmd=args.fallback_cmd,
        fallback_timeout=args.fallback_timeout, fallback_lang=args.fallback_lang,
        verify_cmd=args.verify_cmd, verify_timeout=args.verify_timeout,
        verify_max_pages=args.verify_max_pages,
        trusted_parsers=args.trusted_parser,
        quality_layout_model_dir=args.quality_layout_model_dir,
        quality_url=args.quality_url, quality_revision=args.quality_revision,
        hybrid_layout_model_dir=args.hybrid_layout_model_dir,
        hybrid_tessdata_dir=args.hybrid_tessdata_dir,
        hybrid_url=args.hybrid_url, hybrid_revision=args.hybrid_revision,
        hybrid_max_pixels=args.hybrid_max_pixels, hybrid_repetition_penalty=args.hybrid_repetition_penalty,
        hybrid_label_detector_model_dir=args.hybrid_label_detector_model_dir,hybrid_rectify_labels=args.hybrid_rectify_labels,
        hybrid_question_context_max=args.hybrid_question_context_max,
        hybrid_question_context_mode=args.hybrid_question_context_mode,
        hybrid_orientation_model_dir=args.hybrid_orientation_model_dir,
        hybrid_source_window_max=args.hybrid_source_window_max,
        preprocess=args.preprocess,
        allow_layout_failure=not args.no_allow_layout_failure,
        audit=not args.no_audit, fast_preview=args.fast_preview,
        max_attempts=args.max_attempts,
        stale_seconds=args.stale_seconds, job_timeout=args.job_timeout,
        poll_seconds=args.poll_seconds,
    )
    if args.once:
        worker.recover_stale()
        outcome = worker.run_once()
        return 0 if outcome in (None, "succeeded") else 1
    return worker.run_forever()


if __name__ == "__main__":
    sys.exit(main())
