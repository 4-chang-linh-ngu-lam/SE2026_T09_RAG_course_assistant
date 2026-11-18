"""Bounded Paddle sessions sharing existing queue/ledger, no second job queue."""

import os
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

from idp.ocr.backends.tesseract import BackendUnavailable

from .model_pool import JobMarkerTransport
from .resources import HeavyModelLease

# Dimensions are rounded up after clamping scale to max_pixels; 1% covers it.
PIXEL_ROUNDING_SLACK = 1.01
CPU_IMAGE = "lumi-rag-paddle:phase4"
GPU_IMAGE = "lumi-rag-paddle:gpu"


class PaddleSessionTransport(JobMarkerTransport):
    def __init__(
        self,
        backend,
        *,
        device="cpu",
        timeout_seconds=300,
        max_pixels=1_000_000,
        cpu_fallback=True,
        image=None,
        shared_lease=None,
        model=None,
    ):
        if backend not in {"paddle-layout", "paddle-formula"}:
            raise ValueError("persistent Paddle supports layout/formula only")
        image = image or (CPU_IMAGE if device == "cpu" else GPU_IMAGE)
        super().__init__(
            image=image,
            backend=backend,
            worker="paddle_session_worker.py",
            device=device,
            timeout_seconds=timeout_seconds,
            max_pixels=max_pixels,
            memory="4g",
            model=model,
        )
        self.identity.update(
            device=device, max_pixels=max_pixels, cpu_fallback=cpu_fallback
        )
        self.paddle_distribution = (
            "paddlepaddle" if image == "lumi-rag-paddle:phase4" else "paddlepaddle-gpu"
        )
        self.lease = None
        # A GPU admission lease already held by the same job (owned and
        # released by the caller). It lets one job keep two small models
        # resident without deadlocking on the per-GPU lock; other jobs are
        # still excluded by that same lock file.
        self.shared_lease = shared_lease
        self.cpu = None
        self.cpu_fallback = cpu_fallback
        self.ledger = None
        self.page = None
        self.fallback_count = 0

    @property
    def resource(self):
        return "GPU" if self.device != "cpu" and self.cpu is None else "CPU"

    @property
    def stats(self):
        return {
            "requested_device": self.device,
            "execution_device": "cpu"
            if self.cpu is not None
            else self.container_device,
            "model_loads": self.model_loads + (self.cpu.model_loads if self.cpu else 0),
            "cpu_fallbacks": self.fallback_count,
        }

    def execute(self, image_bytes, *, deadline):
        with Image.open(BytesIO(image_bytes)) as image:
            # The renderer clamps scale to max_pixels but rounds dimensions
            # up, so a clamped page is a few hundred pixels over (measured:
            # 1687x2371 = 4,000,177 vs 4,000,000 on a 787x1106 pt page).
            # Allow that rounding, not real oversize input.
            if image.width * image.height > self.max_pixels * PIXEL_ROUNDING_SLACK:
                raise ValueError("Paddle input exceeds configured pixel limit")
        if self.cpu is not None:
            return self.cpu.execute(image_bytes, deadline=deadline)
        if self.device != "cpu" and self.lease is None and self.shared_lease is None:
            # Keep admission while weights occupy VRAM, not only during predict.
            root = Path(
                os.environ.get(
                    "DEEPDOC_GPU_LOCK_DIR",
                    Path(tempfile.gettempdir()) / "deepdoc-gpu-locks",
                )
            )
            self.lease = HeavyModelLease(
                root / (self.device.replace(":", "-") + ".lock"), deadline
            )
            try:
                self.lease.__enter__()
            except BaseException:
                self.lease = None
                raise
        try:
            return super().execute(image_bytes, deadline=deadline)
        except BackendUnavailable as error:
            if (
                str(error) != "PADDLE_GPU_OOM"
                or self.device == "cpu"
                or not self.cpu_fallback
            ):
                raise
            if self.ledger is None:
                raise BackendUnavailable(
                    "GPU OOM; CPU retry needs an admitted ledger"
                ) from error
            key = "paddle-cpu-fallback-" + uuid.uuid4().hex
            self.ledger.reserve(key, resource="CPU", page=self.page)
            JobMarkerTransport.close(self)
            self._release()
            self.cpu = PaddleSessionTransport(
                self.backend,
                device="cpu",
                timeout_seconds=self.timeout_seconds,
                max_pixels=self.max_pixels,
                cpu_fallback=False,
                # The CUDA image cannot import Paddle without --gpus (no
                # libcuda); the CPU retry needs the CPU image.
                image=CPU_IMAGE if self.image == GPU_IMAGE else self.image,
                model=getattr(self, "model", None),
            )
            ok = False
            try:
                value = self.cpu.execute(image_bytes, deadline=deadline)
                ok = True
                self.fallback_count += 1
                return value
            finally:
                self.ledger.settle(key, ok)

    def _release(self):
        if self.lease is not None:
            self.lease.__exit__(None, None, None)
            self.lease = None

    def close(self):
        try:
            if self.cpu is not None:
                self.cpu.close()
            super().close()
        finally:
            self._release()
