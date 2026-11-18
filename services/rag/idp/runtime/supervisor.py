"""Resource supervision for the opt-in worker; legacy methods remain delegated."""

import json
import os
import signal
import subprocess
import time
import uuid

from idp.orchestration.worker import sha256_file

from .cache import atomic_bytes
from .resources import cleanup_attempt_containers


class SupervisedExecution:
    def _terminate_current(self):
        if not self.use_service:
            return super()._terminate_current()
        process = self.current_proc
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            import psutil

            # taskkill may fail without killing Python's venv redirector tree.
            # Terminate only our captured descendants and bound the wait.
            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except psutil.Error:
                children = []
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(children, timeout=3)
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=40)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def _execute_batch(self, job, out_dir, log_path):
        if not self.use_service:
            return super()._execute_batch(job, out_dir, log_path)
        import psutil

        command = self._command(job, out_dir)
        path = self._job_dir(job.job_id) / "service-request.json"
        request = json.loads(path.read_text()) if path.exists() else {}
        token = request.get("attempt_token", uuid.uuid4().hex)
        env = {
            **os.environ,
            "PYTHONPATH": str(self.package_root)
            + os.pathsep
            + os.environ.get("PYTHONPATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "DEEPDOC_JOB_TOKEN": token,
            "DEEPDOC_PARENT_PID": str(os.getpid()),
            "DEEPDOC_PARENT_CREATED": str(psutil.Process().create_time()),
        }
        started = time.monotonic()
        reason = None
        peak = 0
        with log_path.open("a", encoding="utf-8") as log:
            self.current_proc = subprocess.Popen(
                command,
                cwd=self.package_root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                process = psutil.Process(self.current_proc.pid)
            except psutil.NoSuchProcess:
                process = None
            try:
                while self.current_proc.poll() is None:
                    try:
                        peak = max(
                            peak,
                            sum(
                                p.memory_info().rss
                                for p in (
                                    [process, *process.children(recursive=True)]
                                    if process
                                    else []
                                )
                            ),
                        )
                    except psutil.Error:
                        pass
                    if peak > self.max_worker_rss_mb * 1024**2:
                        reason = "RESOURCE_EXHAUSTED"
                    elif self.stop.is_set():
                        reason = "CANCELLED"
                    elif (
                        self.job_timeout
                        and time.monotonic() - started > self.job_timeout
                    ) or (
                        request.get("deadline_at")
                        and time.time() >= request["deadline_at"]
                    ):
                        reason = "DEADLINE_EXCEEDED"
                    if reason:
                        self._terminate_current()
                        break
                    time.sleep(0.1)
                code = self.current_proc.wait()
            finally:
                if self.current_proc.poll() is None:
                    self._terminate_current()
                self.current_proc = None
        if code or reason:
            cleanup_attempt_containers(token)
        if reason:
            out_dir.mkdir(parents=True, exist_ok=True)
            report = {
                "schema": "deepdoc-job-result:1",
                "status": "FAILED",
                "job_id": job.job_id,
                "source_sha256": sha256_file(job.pdf_path),
                "error_code": reason,
                "retryable": reason == "DEADLINE_EXCEEDED"
                and time.time() < request.get("deadline_at", 0),
                "attempt_token": request.get("attempt_token"),
                "stage": "supervisor",
                "sampled_peak_tree_rss_bytes": peak,
                "public_message": "Worker stopped within configured resource policy.",
            }
            atomic_bytes(out_dir / "runtime_result.json", json.dumps(report).encode())
            return (
                124
                if reason == "DEADLINE_EXCEEDED"
                else 130
                if reason == "CANCELLED"
                else 65
            )
        return code
