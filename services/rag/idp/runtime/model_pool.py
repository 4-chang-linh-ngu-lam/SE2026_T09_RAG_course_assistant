"""One lazy Marker container per job; same typed AdvancedBackend boundary."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from idp.ocr.backends.advanced import DockerModelTransport
from idp.ocr.backends.tesseract import BackendUnavailable, OCRTimeout


class JobMarkerTransport(DockerModelTransport):
    def __init__(
        self,
        *,
        timeout_seconds=300,
        image="lumi-rag-marker:phase4",
        backend="marker",
        worker="persistent_worker.py",
        memory="5g",
        device="cpu",
        max_pixels=1_000_000,
        model=None,
    ):
        super().__init__(
            image,
            backend,
            timeout_seconds=timeout_seconds,
            memory=memory,
            device=device,
            model=model,
        )
        root = Path(__file__).parents[1] / "ocr/backends"
        self.worker = root / worker
        self.max_pixels = max_pixels
        self.helper = root / "model_worker.py"
        self.identity.update(
            session_worker_sha256=hashlib.sha256(self.worker.read_bytes()).hexdigest(),
            source_worker_sha256=hashlib.sha256(self.helper.read_bytes()).hexdigest(),
        )
        self.directory = None
        self.process = None
        self.log = None
        self.name = None
        self.model_loads = 0
        self.model_load_seconds = 0
        self._identity_checked = False
        self._model_identity = None

    def model_identity(self):
        if not self._identity_checked:
            self._model_identity = super().model_identity()
            self._identity_checked = True
        return self._model_identity

    def execute(self, image_bytes, *, deadline):
        deadline = min(deadline, time.monotonic() + self.timeout_seconds)
        if self.directory is None:
            self.directory = TemporaryDirectory(prefix="deepdoc-model-session-")
            root = Path(self.directory.name)
            shutil.copy2(self.worker, root / "session.py")
            shutil.copy2(self.helper, root / "source_model_worker.py")
            self.name = "deepdoc-session-" + uuid.uuid4().hex
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                self.name,
                "--memory",
                self.memory,
                "--cpus",
                str(self.cpus),
                "--mount",
                f"type=bind,source={root},target=/request",
                "--mount",
                f"type=volume,source=deepdoc-{self.cache_family}-{'models' if self.cache_family == 'marker' else 'cache'},target=/root/.cache",
                "--mount",
                f"type=volume,source=deepdoc-{self.cache_family}-{'paddlex' if self.cache_family == 'marker' else 'models'},target=/root/.paddlex",
                "--entrypoint",
                "python",
            ]
            if self.device != "cpu":
                command.extend(["--gpus", "device=" + self.device.split(":")[1]])
            command.extend(
                [
                    "--env",
                    "DEEPDOC_BACKEND=" + self.backend,
                    "--env",
                    "DEEPDOC_DEVICE=" + self.container_device,
                    "--env",
                    "DEEPDOC_MAX_PIXELS=" + str(int(self.max_pixels * 1.01)),  # renderer rounds up
                    *self.model_env(),
                ]
            )
            token = os.environ.get("DEEPDOC_JOB_TOKEN")
            if token and re.fullmatch("[0-9a-f]{32}", token):
                command.extend(["--label", "deepdoc.job=" + token])
            command.extend([self.identity["image_id"], "/request/session.py"])
            self.log = (root / "session.log").open("wb")
            self.process = subprocess.Popen(
                command, stdout=self.log, stderr=subprocess.STDOUT
            )
        root = Path(self.directory.name)
        key = uuid.uuid4().hex
        source = root / (key + ".png")
        target = root / (key + ".json")
        source.write_bytes(image_bytes)
        request = root / ("request-" + key + ".json")
        tmp = request.with_suffix(".tmp")
        tmp.write_text(json.dumps({"input": source.name, "output": target.name}))
        tmp.replace(request)
        while not target.is_file():
            if self.process.poll() is not None:
                raise BackendUnavailable(
                    f"{self.backend} session unavailable (exit {self.process.returncode}); no result accepted"
                )
            if time.monotonic() >= deadline:
                self.close()
                raise OCRTimeout("Marker session exceeded deadline")
            time.sleep(0.1)
        if target.stat().st_size > 32_000_000:
            raise ValueError("model output too large")
        value = json.loads(target.read_text(encoding="utf-8"))
        if "error" in value:
            raise BackendUnavailable(value["error"])
        self.model_loads += int(value.get("model_loaded", False))
        self.model_load_seconds += value.get("model_load_seconds", 0)
        self._model_identity = {
            "packages": value["packages"],
            "weights": value["weights_sha256"],
            "transport": self.identity,
        }
        self._identity_checked = True
        source.unlink()
        target.unlink()
        request.with_name("handled-" + request.name).unlink(missing_ok=True)
        return value

    def close(self):
        if self.directory is None:
            return
        try:
            (Path(self.directory.name) / "stop").touch()
            if self.process is not None:
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            subprocess.run(
                ["docker", "rm", "-f", self.name],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
        finally:
            if self.log is not None:
                self.log.close()
            self.directory.cleanup()
            self.directory = None
            self.process = None
