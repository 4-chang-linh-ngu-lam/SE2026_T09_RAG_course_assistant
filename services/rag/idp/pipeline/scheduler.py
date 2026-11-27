"""Warm model pool, bounded CPU page workers, and GPU VLM request queue."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from idp.backends.layout import PaddleLayoutDetector, RemoteLayoutDetector
from idp.backends.vision_ocr import PaddleVisionBackend
from idp.config import ExecutionConfig
from idp.input.validation import InputError

T = TypeVar("T")
R = TypeVar("R")


class ModelPool:
    """Process-wide warm-loading cache for PP-DocLayoutV3 and PaddleOCR-VL clients."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._layout_detectors: dict[tuple[str, str, str], PaddleLayoutDetector] = {}
        self._remote_layout_detectors: dict[tuple[str, str, str | None], RemoteLayoutDetector] = {}
        self._vision_backends: dict[tuple[str, str, str | None, int], PaddleVisionBackend] = {}
        self.layout_loads = 0
        self.remote_layout_loads = 0
        self.vision_loads = 0

    def get_layout_detector(
        self,
        model_dir: str | Path,
        *,
        layout_policy: str = "v3_vl16",
        device: str = "cpu",
        cpu_threads: int = 2,
        serving_mode: str = "auto",
    ) -> PaddleLayoutDetector:
        if serving_mode == "remote":
            raise InputError(
                "MODEL_SERVING_REMOTE_ONLY",
                "in-process layout model loading is disabled when serving_mode='remote'",
            )
        key = (str(Path(model_dir).resolve()), layout_policy, device)
        with self._lock:
            detector = self._layout_detectors.get(key)
            if detector is None:
                detector = PaddleLayoutDetector(
                    model_dir, cpu_threads=cpu_threads, layout_policy=layout_policy, device=device
                )
                self._layout_detectors[key] = detector
                self.layout_loads += 1
            return detector

    def get_remote_layout_detector(
        self,
        base_url: str,
        *,
        layout_policy: str = "v3_vl16",
        revision: str | None = None,
        timeout: float = 30.0,
        allowed_hosts: tuple[str, ...] = (),
        service_key: str | None = None,
    ) -> RemoteLayoutDetector:
        key = (
            base_url.rstrip("/"),
            layout_policy,
            revision,
            tuple(sorted(allowed_hosts)),
            bool(service_key),
        )
        with self._lock:
            detector = self._remote_layout_detectors.get(key)
            if detector is None:
                detector = RemoteLayoutDetector(
                    base_url,
                    layout_policy=layout_policy,
                    revision=revision,
                    timeout=timeout,
                    allowed_hosts=allowed_hosts,
                    service_key=service_key,
                )
                self._remote_layout_detectors[key] = detector
                self.remote_layout_loads += 1
            return detector

    def get_vision_backend(
        self,
        base_url: str,
        *,
        model: str = "paddleocr-vl-1.6",
        revision: str | None = None,
        parallel: int = 4,
        timeout: float = 120.0,
        allowed_hosts: tuple[str, ...] = (),
        service_key: str | None = None,
    ) -> PaddleVisionBackend:
        key = (
            base_url.rstrip("/"),
            model,
            revision,
            parallel,
            tuple(sorted(allowed_hosts)),
            bool(service_key),
        )
        with self._lock:
            backend = self._vision_backends.get(key)
            if backend is None:
                backend = PaddleVisionBackend(
                    base_url,
                    model=model,
                    revision=revision,
                    parallel=parallel,
                    timeout=timeout,
                    allowed_hosts=allowed_hosts,
                    service_key=service_key,
                )
                self._vision_backends[key] = backend
                self.vision_loads += 1
            return backend

    def clear(self) -> None:
        with self._lock:
            for detector in self._layout_detectors.values():
                try:
                    detector.close()
                except Exception:
                    pass
            for rdet in self._remote_layout_detectors.values():
                try:
                    rdet.close()
                except Exception:
                    pass
            self._layout_detectors.clear()
            self._remote_layout_detectors.clear()
            self._vision_backends.clear()

    def stats(self) -> dict:
        with self._lock:
            return {
                "warm_layout_detectors": len(self._layout_detectors),
                "warm_remote_layout_detectors": len(self._remote_layout_detectors),
                "warm_vision_backends": len(self._vision_backends),
                "layout_loads": self.layout_loads,
                "remote_layout_loads": self.remote_layout_loads,
                "vision_loads": self.vision_loads,
                "remote_layout_circuits": [
                    d.serving_metrics() for d in self._remote_layout_detectors.values()
                ],
                "vision_circuits": [
                    b.serving_metrics() for b in self._vision_backends.values()
                ],
            }


GLOBAL_MODEL_POOL = ModelPool()


class GpuWorkQueue:
    """Bounded concurrency queue for VLM region calls with strict in-flight tracking."""

    def __init__(self, concurrency: int = 4):
        if type(concurrency) is not int or not 1 <= concurrency <= 16:
            raise ValueError("gpu concurrency must be an integer in 1..16")
        self.concurrency = concurrency
        self._sem = threading.Semaphore(concurrency)
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="idp-gpu")
        self.calls = 0
        self.failures = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self.total_seconds = 0.0

    def submit_call(self, fn: Callable[..., R], *args, **kwargs) -> R:
        with self._sem:
            with self._lock:
                self.calls += 1
                self.in_flight += 1
                if self.in_flight > self.peak_in_flight:
                    self.peak_in_flight = self.in_flight
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            except Exception:
                with self._lock:
                    self.failures += 1
                raise
            finally:
                elapsed = time.perf_counter() - started
                with self._lock:
                    self.in_flight -= 1
                    self.total_seconds += elapsed

    def map_calls(self, fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
        item_list = list(items)
        if not item_list:
            return []
        if len(item_list) == 1 or self.concurrency == 1:
            return [self.submit_call(fn, item) for item in item_list]
        futures = [self._pool.submit(self.submit_call, fn, item) for item in item_list]
        return [f.result() for f in futures]

    def metrics(self) -> dict:
        with self._lock:
            return {
                "concurrency": self.concurrency,
                "calls": self.calls,
                "failures": self.failures,
                "peak_in_flight": self.peak_in_flight,
                "total_seconds": round(self.total_seconds, 3),
            }

    def close(self) -> None:
        self._pool.shutdown(wait=True)

    def __enter__(self) -> "GpuWorkQueue":
        return self

    def __exit__(self, *args) -> None:
        self.close()


class AdaptiveScheduler:
    """Coordinate bounded CPU batch parallelism with a shared GPU queue."""

    def __init__(self, config: ExecutionConfig | None = None):
        self.config = config or ExecutionConfig()
        self.gpu_queue = GpuWorkQueue(self.config.gpu_concurrency)

    def run_cpu_batch(self, fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
        item_list = list(items)
        if not item_list:
            return []
        workers = min(self.config.cpu_workers, len(item_list))
        if workers <= 1:
            return [fn(item) for item in item_list]
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="idp-cpu") as pool:
            return list(pool.map(fn, item_list))

    def close(self) -> None:
        self.gpu_queue.close()

    def __enter__(self) -> "AdaptiveScheduler":
        return self

    def __exit__(self, *args) -> None:
        self.close()
