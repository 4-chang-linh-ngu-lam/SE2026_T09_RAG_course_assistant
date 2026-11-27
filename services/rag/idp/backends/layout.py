"""Level 2 layout detection backend (PP-DocLayoutV3 + OpenCV panel hints)."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import re
import threading
import urllib.request
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from idp.backends.vision_ocr import LocalRegionError, _NoRedirect, _require_loopback
from idp.input.validation import InputError
from idp.serving.client import (
    CircuitOpenError,
    ModelOriginPolicy,
    ServingCircuitBreaker,
    build_serving_headers,
    post_json_keepalive,
)

_ORIG_BUILD_OPENER = urllib.request.build_opener

REMOTE_LAYOUT_VERSION = "idp-remote-layout-1"

LAYOUT_KINDS = {
    "text": "Text",
    "content": "Text",
    "abstract": "Text",
    "reference": "Text",
    "reference_content": "Text",
    "footnote": "Text",
    "vision_footnote": "Text",
    "aside_text": "Text",
    "formula_number": "Text",
    "number": "PageNumber",
    "doc_title": "SectionHeader",
    "paragraph_title": "SectionHeader",
    "header": "PageHeader",
    "footer": "PageFooter",
    "figure_title": "Caption",
    "caption": "Caption",
    "table": "Table",
    "formula": "Equation",
    "display_formula": "Equation",
    "inline_formula": "Equation",
    "equation": "Equation",
    "image": "Picture",
    "figure": "Picture",
    "picture": "Picture",
    "header_image": "Picture",
    "footer_image": "Picture",
    "seal": "Picture",
    "diagram": "Diagram",
    "chart": "Chart",
    "algorithm": "Code",
}


def normalize_layout_kind(raw_kind: str) -> str | None:
    return LAYOUT_KINDS.get(str(raw_kind or "").strip().lower())


@dataclass(frozen=True)
class LayoutRegion:
    bbox: list[float]
    kind: str
    kind_original: str
    layout_score: float | None = None


def detect_panels(image_path: str | Path) -> list[dict]:
    """Cheap OpenCV visual hints for coloured textbook callout panels."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("cannot read recovery image")
    height, width = image.shape[:2]
    scale = min(1.0, 1400 / max(width, height))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale)
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 30, 155), (179, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    regions = []
    for x, y, rw, rh, area in stats[1:]:
        if (
            rw >= max(60, int(0.08 * w))
            and rh >= 28
            and 0.004 * w * h <= area <= 0.45 * w * h
            and area / (rw * rh) >= 0.55
        ):
            regions.append({
                "bbox": [float(x / scale), float(y / scale), float((x + rw) / scale), float((y + rh) / scale)],
                "kind": "panel",
            })
    return regions


def detect_missed_ink_regions(
    image_path: str | Path,
    existing_lines: list[dict],
    *,
    excluded_boxes: list[list[float]] | tuple[list[float], ...] = (),
    max_regions: int = 12,
) -> list[dict]:
    """Find ink-dense image regions missed by full-page OCR when no ML layout model is active."""
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None or float(np.std(image)) < 2.0:
        return []
    h, w = image.shape
    binary = cv2.adaptiveThreshold(
        image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    for item in existing_lines:
        box = item.get("bbox")
        if box and len(box) == 4:
            x0 = max(0, int(math.floor(float(box[0]))) - 4)
            y0 = max(0, int(math.floor(float(box[1]))) - 4)
            x1 = min(w, int(math.ceil(float(box[2]))) + 4)
            y1 = min(h, int(math.ceil(float(box[3]))) + 4)
            if x1 > x0 and y1 > y0:
                binary[y0:y1, x0:x1] = 0
    for box in excluded_boxes:
        if box and len(box) == 4:
            x0 = max(0, int(math.floor(float(box[0]))))
            y0 = max(0, int(math.floor(float(box[1]))))
            x1 = min(w, int(math.ceil(float(box[2]))))
            y1 = min(h, int(math.ceil(float(box[3]))))
            if x1 > x0 and y1 > y0:
                binary[y0:y1, x0:x1] = 0

    if not np.any(binary):
        return []
    kernel_w = max(15, min(64, w // 45))
    merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, kernel_w), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(merged)
    candidates: list[dict] = []
    min_w = max(24, int(0.03 * w))
    for x, y, bw, bh, _area in stats[1:]:
        if bw < min_w or bh < 10:
            continue
        box_area = bw * bh
        if box_area > 0.45 * w * h:
            continue
        ink_density = float(np.count_nonzero(binary[y : y + bh, x : x + bw])) / max(1, box_area)
        if ink_density < 0.015:
            continue
        candidates.append({
            "bbox": [float(x), float(y), float(x + bw), float(y + bh)],
            "kind": "text",
            "hint": "uncovered_ink",
        })
    candidates.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
    return candidates[:max_regions]


class PaddleLayoutDetector:
    """Warm-loaded local PP-DocLayoutV3/V2 detector with thread-safe LRU caching."""

    def __init__(
        self,
        model_dir: str | Path,
        cpu_threads: int = 2,
        *,
        layout_policy: str = "default",
        device: str = "cpu",
    ):
        self.model_dir = Path(model_dir).resolve()
        required = [self.model_dir / name for name in ("inference.pdiparams", "inference.json", "inference.yml")]
        if not all(path.is_file() for path in required):
            raise InputError("LAYOUT_MODEL_UNAVAILABLE", "provide a complete local PP-DocLayoutV2/V3 model directory")
        match = re.search(r"model_name:\s*[\"']?(PP-DocLayoutV[23])", required[2].read_text("utf-8"))
        if match is None:
            raise InputError("LAYOUT_MODEL_UNAVAILABLE", "local model config must identify PP-DocLayoutV2 or V3")
        model_name = match.group(1)
        if layout_policy not in {"default", "v3_vl16"} or (layout_policy == "v3_vl16" and model_name != "PP-DocLayoutV3"):
            raise InputError("LAYOUT_POLICY_UNSUPPORTED", "v3_vl16 requires PP-DocLayoutV3; otherwise use default")
        postprocess = (
            {
                "threshold": 0.3,
                "layout_nms": True,
                "layout_unclip_ratio": [1.0, 1.0],
                "layout_merge_bboxes_mode": {i: "large" if i in {3, 5, 6, 15, 17} else "union" for i in range(25)},
            }
            if layout_policy == "v3_vl16"
            else {}
        )
        self.predict_options = {"filter_overlap_boxes": False} if layout_policy == "v3_vl16" else {}
        try:
            from paddleocr import LayoutDetection
        except ImportError as exc:
            raise InputError("LAYOUT_ENGINE_UNAVAILABLE", "install the optional PaddleOCR runtime or omit --layout-model-dir") from exc
        try:
            self.model = LayoutDetection(
                model_name=model_name,
                model_dir=str(self.model_dir),
                device=device,
                cpu_threads=cpu_threads,
                enable_mkldnn=False,
                **postprocess,
            )
        except Exception as exc:
            raise InputError("LAYOUT_ENGINE_FAILED", f"local layout engine could not initialize on {device}") from exc

        def _digest(path: Path) -> str:
            sha = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(chunk)
            return sha.hexdigest()

        self.identity = {
            "name": model_name,
            "device": device,
            "layout_policy": layout_policy,
            "postprocess": json.loads(json.dumps(postprocess)),
            "cpu_threads": cpu_threads,
            "predict_options": dict(self.predict_options),
            "files_sha256": {path.name: _digest(path) for path in required},
        }
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._lock = threading.RLock()

    def __call__(self, image_path: str | Path) -> list[dict]:
        sha = hashlib.sha256()
        with Path(image_path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        key = sha.hexdigest()
        with self._lock:
            if key not in self._cache:
                result = self.model.predict(str(image_path), **self.predict_options)[0].json
                self._cache[key] = [
                    {
                        "bbox": b.get("coordinate"),
                        "kind": b.get("label"),
                        "layout_score": b.get("score"),
                    }
                    for b in result.get("res", result).get("boxes", [])
                ]
                if len(self._cache) > 16:
                    self._cache.popitem(last=False)
            self._cache.move_to_end(key)
            return copy.deepcopy(self._cache[key])

    def close(self) -> None:
        close_fn = getattr(self.model, "close", None)
        if close_fn is not None:
            close_fn()

    def __enter__(self) -> "PaddleLayoutDetector":
        return self

    def __exit__(self, *args) -> None:
        self.close()


class RemoteLayoutDetector:
    """Isolated HTTP client for PP-DocLayoutV3/V2 running on a dedicated model serving process."""

    def __init__(
        self,
        base_url: str,
        *,
        layout_policy: str = "v3_vl16",
        revision: str | None = None,
        timeout: float = 60.0,
        max_pixels: int = 2_500_000,
        allowed_hosts: Iterable[str] = (),
        service_key: str | None = None,
        circuit_breaker: ServingCircuitBreaker | None = None,
    ) -> None:
        self.allowed_hosts = tuple(allowed_hosts)
        self.service_key = service_key
        ModelOriginPolicy(self.allowed_hosts).validate(base_url)
        if layout_policy not in {"default", "v3_vl16"}:
            raise InputError("LAYOUT_POLICY_UNSUPPORTED", "layout_policy must be 'default' or 'v3_vl16'")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if type(max_pixels) is not int or not 65_536 <= max_pixels <= 16_000_000:
            raise ValueError("max_pixels must be an integer in [65536, 16000000]")
        self.base_url = base_url.rstrip("/")
        self.layout_policy = layout_policy
        self.revision = revision
        self.timeout = timeout
        self.max_pixels = max_pixels
        self._circuit_breaker = circuit_breaker or ServingCircuitBreaker()
        self.cacheable = bool(revision)
        self.identity = {
            "name": "pp_doclayout_remote",
            "layout_policy": layout_policy,
            "revision": revision,
            "version": REMOTE_LAYOUT_VERSION,
            "max_pixels": max_pixels,
        }
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._lock = threading.RLock()

    def serving_metrics(self) -> dict:
        return self._circuit_breaker.state()

    def _opener(self):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def health(self, timeout: float = 5.0) -> dict:
        ModelOriginPolicy(self.allowed_hosts).validate(self.base_url)
        req = urllib.request.Request(
            f"{self.base_url}/health",
            headers=build_serving_headers(self.service_key, content_type=None),
            method="GET",
        )
        with self._opener().open(req, timeout=timeout) as resp:
            raw = resp.read(262_145)
        if len(raw) > 262_144:
            raise LocalRegionError("RESPONSE_BYTES", "remote layout health response oversized")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("invalid layout health payload")
        return data

    def _encode_image(self, image_path: Path) -> tuple[str, float, float, str]:
        if image_path.stat().st_size > 15_000_000:
            raise LocalRegionError("IMAGE_BYTES", "layout page image exceeds 15 MB limit")
        with Image.open(image_path) as opened:
            orig_w, orig_h = opened.size
            if orig_w <= 0 or orig_h <= 0:
                raise ValueError("empty page image")
            area = orig_w * orig_h
            sx = 1.0
            sy = 1.0
            target = opened
            if area > self.max_pixels:
                scale = math.sqrt(self.max_pixels / area)
                send_w = max(1, int(orig_w * scale))
                send_h = max(1, int(orig_h * scale))
                target = opened.convert("RGB").resize((send_w, send_h), Image.Resampling.LANCZOS)
                sx = orig_w / send_w
                sy = orig_h / send_h
            elif Image.MIME.get(opened.format) == "image/jpeg":
                return base64.b64encode(image_path.read_bytes()).decode("ascii"), 1.0, 1.0, "image/jpeg"
            else:
                target = opened.convert("RGB")
            buf = io.BytesIO()
            target.save(buf, format="JPEG", quality=85, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("ascii"), sx, sy, "image/jpeg"

    def __call__(self, image_path: str | Path) -> list[dict]:
        path = Path(image_path)
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        key = sha.hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return copy.deepcopy(self._cache[key])

        if not self._circuit_breaker.allow_request():
            raise CircuitOpenError("remote layout serving circuit breaker is open")
        img_b64, sx, sy, mime_type = self._encode_image(path)
        payload = {
            "image_base64": img_b64,
            "mime_type": mime_type,
            "layout_policy": self.layout_policy,
        }
        url = f"{self.base_url}/v1/layout"
        body_bytes = json.dumps(payload).encode("utf-8")
        headers = build_serving_headers(self.service_key)
        try:
            if urllib.request.build_opener is _ORIG_BUILD_OPENER:
                raw = post_json_keepalive(
                    url,
                    body_bytes,
                    headers,
                    timeout=self.timeout,
                    max_bytes=2_000_000,
                )
            else:
                req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
                with self._opener().open(req, timeout=self.timeout) as resp:
                    raw = resp.read(2_000_001)
        except Exception as exc:
            if not isinstance(exc, LocalRegionError):
                self._circuit_breaker.record_failure(type(exc).__name__)
            raise
        if len(raw) > 2_000_000:
            raise LocalRegionError("RESPONSE_BYTES", "remote layout response exceeds 2 MB limit")
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("boxes"), list):
            self._circuit_breaker.record_failure("invalid_response")
            raise ValueError("remote layout response missing 'boxes' list")
        self._circuit_breaker.record_success()

        boxes: list[dict] = []
        for item in body["boxes"]:
            if not isinstance(item, dict):
                continue
            coord = item.get("bbox", item.get("coordinate"))
            kind = item.get("kind", item.get("label"))
            if (
                not isinstance(coord, (list, tuple))
                or len(coord) != 4
                or not isinstance(kind, str)
                or not kind.strip()
            ):
                continue
            x1, y1, x2, y2 = [float(v) for v in coord]
            if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or x2 <= x1 or y2 <= y1:
                continue
            score = item.get("layout_score", item.get("score"))
            if score is not None:
                score = float(score)
                if not math.isfinite(score):
                    score = None
            boxes.append({
                "bbox": [x1 * sx, y1 * sy, x2 * sx, y2 * sy],
                "kind": kind.strip(),
                "layout_score": score,
            })

        with self._lock:
            self._cache[key] = boxes
            if len(self._cache) > 16:
                self._cache.popitem(last=False)
            return copy.deepcopy(boxes)

    def close(self) -> None:
        with self._lock:
            self._cache.clear()

    def __enter__(self) -> "RemoteLayoutDetector":
        return self

    def __exit__(self, *args) -> None:
        self.close()


HttpLayoutDetector = RemoteLayoutDetector
