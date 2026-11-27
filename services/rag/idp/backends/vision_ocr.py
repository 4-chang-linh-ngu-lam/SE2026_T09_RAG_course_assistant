"""Level 3 PaddleOCR-VL 1.6 GGUF vision backend via loopback llama.cpp server."""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from idp.processing.table import otsl_to_html, parse_table_html
from idp.serving.client import (
    CircuitOpenError,
    LocalRegionError,
    ModelOriginPolicy,
    NoRedirectHandler,
    ServingCircuitBreaker,
    build_serving_headers,
    post_json_keepalive,
    require_serving_origin,
)

_ORIG_BUILD_OPENER = urllib.request.build_opener

LOCAL_REGION_VERSION = "idp-local-region-3"
VL_PRIMARY_VERSION = "idp-vl-primary-1"
SOURCE = "paddleocr_vl_gguf"
MAX_HARD_INPUT_PIXELS = 32_000_000
ERROR_CODES = {
    "ORIGIN", "LIMITS", "KIND", "PROFILE", "TABLE_FORMAT", "VISUAL_FORMAT",
    "IMAGE_BYTES", "IMAGE_PIXELS", "IMAGE_FORMAT", "RESPONSE_BYTES", "INCOMPLETE", "UNREADABLE",
}

TEXT_PROMPT = (
    "Transcribe only the exact visible text in the image. Preserve Vietnamese accents, letter case, digits, "
    "punctuation, mathematical symbols, units and superscripts as Unicode text. Preserve line breaks. "
    "Do not explain, solve, infer missing values, or add formatting. If unreadable, output <unreadable>."
)
PROMPTS = {
    "Text": TEXT_PROMPT,
    "Table": (
        "Transcribe the visible table as a single HTML <table> only. Preserve every row, column, merged cell, "
        "Vietnamese accent, digit, punctuation, mathematical symbol, unit and superscript as Unicode. "
        "Use <td> for cells unless a header is explicit in the image. Preserve all punctuation and empty cells. "
        "Do not solve, complete missing values, explain or add code fences. Use <unreadable> for unreadable text."
    ),
    "Equation": (
        "Transcribe the visible mathematical expression as LaTeX only, without dollar delimiters, "
        "explanation or code fences. Preserve all signs, indices, exponents and units. Do not solve "
        "or complete the expression. If unreadable, output <unreadable>."
    ),
}
PADDLE_PROMPTS = {
    "Text": "OCR:",
    "Table": "Table Recognition:",
    "Equation": "Formula Recognition:",
}
VISUAL_PROMPT = (
    "Describe the visible figure faithfully for text retrieval. Include visible labels, relationships "
    "and arrow directions. For charts include axes, units, series and readable values. Preserve "
    "Vietnamese names, digits and symbols. Distinguish explicit labels from estimates; state when "
    "a value or relation is unreadable. Do not solve exercises or infer missing facts. Return description only."
)


_NoRedirect = NoRedirectHandler


def _require_loopback(base_url: str, *, allowed_hosts: Iterable[str] = ()) -> None:
    require_serving_origin(base_url, allowed_hosts=allowed_hosts)


def _unwrap_latex(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("$$") != stripped.endswith("$$"):
        return text
    for left, right in ((r"\[", r"\]"), (r"\(", r"\)"), ("$$", "$$"), ("$", "$")):
        if len(stripped) >= len(left) + len(right) and stripped.startswith(left) and stripped.endswith(right):
            inner = stripped[len(left):-len(right)]
            if left in inner or right in inner:
                return text
            return inner.strip()
    return text


def _prompt(kind: str, profile: str) -> str:
    if profile in {"generic", "qwen"}:
        return PROMPTS.get(kind, VISUAL_PROMPT)
    if profile != "paddleocr":
        raise LocalRegionError("PROFILE", "unsupported local region prompt profile")
    if kind not in PADDLE_PROMPTS:
        raise LocalRegionError("KIND", "PaddleOCR profile does not provide figure descriptions")
    return PADDLE_PROMPTS[kind]


def _encode_pil_data_url(img: Image.Image, *, max_pixels: int = 2_000_000) -> str:
    if img.width * img.height > MAX_HARD_INPUT_PIXELS:
        raise LocalRegionError("IMAGE_PIXELS", "local region image pixel limit")
    rgb = img.convert("RGB")
    area = rgb.width * rgb.height
    if area > max_pixels:
        scale = math.sqrt(max_pixels / max(1, area))
        rgb = rgb.resize(
            (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    # Keep tiny crops (e.g. narrow formulas) lossless PNG; use 4:4:4 JPEG on larger crops to shrink WAN uploads.
    if rgb.width * rgb.height < 40_000:
        rgb.save(buf, format="PNG", compress_level=6)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    rgb.save(buf, format="JPEG", quality=92, subsampling=0, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _encode_image_data_url(image_or_path: Image.Image | str | Path, *, max_pixels: int = 2_000_000) -> str:
    if isinstance(image_or_path, Image.Image):
        return _encode_pil_data_url(image_or_path, max_pixels=max_pixels)
    path = Path(image_or_path)
    if path.stat().st_size > 10_000_000:
        raise LocalRegionError("IMAGE_BYTES", "local region image byte limit")
    with Image.open(path) as img:
        mime = Image.MIME.get(img.format)
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise LocalRegionError("IMAGE_FORMAT", "unsupported local region image format")
        area = img.width * img.height
        if area > MAX_HARD_INPUT_PIXELS:
            raise LocalRegionError("IMAGE_PIXELS", "local region image pixel limit")
        if area > max_pixels:
            return _encode_pil_data_url(img, max_pixels=max_pixels)
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _post_chat_completion(
    base_url: str,
    payload: dict,
    *,
    timeout: float,
    allowed_hosts: Iterable[str] = (),
    service_key: str | None = None,
    circuit_breaker: ServingCircuitBreaker | None = None,
) -> dict:
    ModelOriginPolicy(allowed_hosts).validate(base_url)
    if circuit_breaker is not None and not circuit_breaker.allow_request():
        raise CircuitOpenError("vision serving circuit breaker is open")
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = build_serving_headers(service_key)
    try:
        if urllib.request.build_opener is _ORIG_BUILD_OPENER:
            raw = post_json_keepalive(
                url,
                body_bytes,
                headers,
                timeout=timeout,
                max_bytes=4_000_000,
            )
        else:
            request = urllib.request.Request(url, data=body_bytes, headers=headers)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(4_000_001)
    except Exception as exc:
        if circuit_breaker is not None and not isinstance(exc, LocalRegionError):
            circuit_breaker.record_failure(type(exc).__name__)
        raise
    if len(raw) > 4_000_000:
        raise LocalRegionError("RESPONSE_BYTES", "local region response byte limit")
    if circuit_breaker is not None:
        circuit_breaker.record_success()
    return json.loads(raw)


def read_region(
    image_path: str | Path | Image.Image,
    kind: str,
    *,
    base_url: str = "http://127.0.0.1:8081",
    timeout: float = 8,
    max_tokens: int = 1024,
    model: str | None = None,
    prompt_profile: str = "generic",
    allowed_hosts: Iterable[str] = (),
    service_key: str | None = None,
    circuit_breaker: ServingCircuitBreaker | None = None,
) -> dict:
    ModelOriginPolicy(allowed_hosts).validate(base_url)
    if not math.isfinite(timeout) or timeout <= 0 or type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
        raise LocalRegionError("LIMITS", "invalid local region limits")
    if kind not in {"Text", "Table", "Equation", "Picture", "Diagram", "Chart", "PictureGroup"}:
        raise LocalRegionError("KIND", "unsupported local region kind")
    prompt = _prompt(kind, prompt_profile)
    image_url = _encode_image_data_url(image_path)
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    if prompt_profile in {"paddleocr", "qwen"}:
        content.reverse()
    payload: dict = {
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if model:
        payload["model"] = model
    result = _post_chat_completion(
        base_url,
        payload,
        timeout=timeout,
        allowed_hosts=allowed_hosts,
        service_key=service_key,
        circuit_breaker=circuit_breaker,
    )
    choice = result["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise LocalRegionError("INCOMPLETE", "local region output incomplete or finish reason unavailable")
    text = choice["message"]["content"]
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 32768
        or any(marker in text.lower() for marker in ("<unreadable>", "[unreadable]"))
    ):
        raise LocalRegionError("UNREADABLE", "local region reading empty, unreadable or oversized")
    if kind == "Equation" and prompt_profile == "paddleocr":
        text = _unwrap_latex(text)
        if not text.strip():
            raise LocalRegionError("UNREADABLE", "local region formula empty after outer delimiters")
    if kind == "Table" and prompt_profile == "paddleocr":
        try:
            if text.lstrip().startswith(("<fcel>", "<ecel>")):
                text = otsl_to_html(text)
            table = parse_table_html(text)
            if not table["rectangular"]:
                raise ValueError("incomplete table topology")
        except ValueError as exc:
            raise LocalRegionError("TABLE_FORMAT", "local region table format is incomplete or unsupported") from exc
    key = {"Text": "text", "Table": "table_html", "Equation": "latex"}.get(kind, "description")
    return {key: text}


class PaddleVisionBackend:
    """PaddleOCR-VL 1.6 GGUF via isolated HTTP llama.cpp serving (logprobs + structured reads)."""

    def __init__(
        self,
        base_url: str,
        *,
        model: str = "paddleocr-vl-1.6",
        revision: str | None = None,
        timeout: float = 120,
        max_tokens: int = 1024,
        alternatives: int = 5,
        parallel: int = 1,
        allowed_hosts: Iterable[str] = (),
        service_key: str | None = None,
        circuit_breaker: ServingCircuitBreaker | None = None,
    ):
        self.allowed_hosts = tuple(allowed_hosts)
        self.service_key = service_key
        ModelOriginPolicy(self.allowed_hosts).validate(base_url)
        if type(parallel) is not int or not 1 <= parallel <= 16:
            raise ValueError("parallel must be an integer in 1..16")
        self.parallel = parallel
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.alternatives = alternatives
        self._circuit_breaker = circuit_breaker or ServingCircuitBreaker()
        self.cacheable = bool(revision)
        self.identity = {
            "name": "paddleocr_vl_primary",
            "model": model,
            "revision": revision,
            "adapter_version": LOCAL_REGION_VERSION,
            "version": VL_PRIMARY_VERSION,
            "max_tokens": max_tokens,
            "alternatives": alternatives,
        }

    def serving_metrics(self) -> dict:
        return self._circuit_breaker.state()

    def __call__(self, image: Image.Image, kind: str) -> list[tuple]:
        """Return token tuples [(text, prob, [(alt, alt_prob), ...])] for one region."""
        return self.read_with_logprobs(image, kind)

    def read_with_logprobs(self, image: Image.Image, kind: str) -> list[tuple]:
        data = _encode_image_data_url(image, max_pixels=2_000_000)
        prompt = PADDLE_PROMPTS.get(kind, "OCR:")
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "logprobs": True,
            "top_logprobs": max(1, self.alternatives),
        }
        result = _post_chat_completion(
            self.base_url,
            payload,
            timeout=self.timeout,
            allowed_hosts=self.allowed_hosts,
            service_key=self.service_key,
            circuit_breaker=self._circuit_breaker,
        )
        content = ((result["choices"][0].get("logprobs") or {}).get("content")) or []
        return [
            (
                t["token"],
                math.exp(t["logprob"]),
                [
                    (a["token"], math.exp(a["logprob"]))
                    for a in t.get("top_logprobs") or []
                    if a["token"] != t["token"]
                ],
            )
            for t in content
        ]

    def read_region_structured(
        self,
        image: Image.Image | str | Path,
        kind: str,
        *,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        if max_tokens is not None:
            effective_max_tokens = max_tokens
        elif kind == "Table":
            effective_max_tokens = min(4096, max(self.max_tokens, 2048))
        else:
            effective_max_tokens = self.max_tokens
        return read_region(
            image,
            kind,
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            max_tokens=effective_max_tokens,
            model=self.model,
            prompt_profile="paddleocr",
            allowed_hosts=self.allowed_hosts,
            service_key=self.service_key,
            circuit_breaker=self._circuit_breaker,
        )


# Compatibility alias for existing callers (e.g. services/document idp_runner)
PaddleVLPrimaryReader = PaddleVisionBackend


class PaddleGGUFFormulaReader:
    """Read a formula crop using an existing isolated llama-server."""

    def __init__(
        self,
        base_url: str,
        *,
        model: str = "paddleocr-vl-1.6",
        revision: str | None = None,
        allowed_hosts: Iterable[str] = (),
        service_key: str | None = None,
        circuit_breaker: ServingCircuitBreaker | None = None,
    ):
        self.allowed_hosts = tuple(allowed_hosts)
        self.service_key = service_key
        ModelOriginPolicy(self.allowed_hosts).validate(base_url)
        self.base_url = base_url
        self.model = model
        self._custom_breaker = circuit_breaker is not None
        self._circuit_breaker = circuit_breaker or ServingCircuitBreaker()
        self.cacheable = bool(revision)
        self.identity = {
            "name": "paddleocr_vl_gguf",
            "model": model,
            "revision": revision,
            "adapter_version": LOCAL_REGION_VERSION,
            "max_tokens": 512,
        }

    def __call__(self, crop, timeout: float = 20) -> dict:
        if not self._circuit_breaker.allow_request():
            raise CircuitOpenError("remote model serving circuit breaker is open")
        extra_kwargs: dict = {}
        if self.allowed_hosts:
            extra_kwargs["allowed_hosts"] = self.allowed_hosts
        if self.service_key:
            extra_kwargs["service_key"] = self.service_key
        if self._custom_breaker:
            extra_kwargs["circuit_breaker"] = self._circuit_breaker
        try:
            result = read_region(
                crop,
                "Equation",
                base_url=self.base_url,
                timeout=timeout,
                max_tokens=self.identity["max_tokens"],
                model=self.model,
                prompt_profile="paddleocr",
                **extra_kwargs,
            )
        except Exception as exc:
            if not self._custom_breaker and not isinstance(exc, LocalRegionError):
                self._circuit_breaker.record_failure(type(exc).__name__)
            raise
        if not self._custom_breaker:
            self._circuit_breaker.record_success()
        return result


class PaddleGGUFTextReader:
    """Read a text-line crop with PaddleOCR-VL ('OCR:') on an isolated llama-server."""

    def __init__(
        self,
        base_url: str,
        *,
        model: str = "paddleocr-vl-1.6",
        revision: str | None = None,
        timeout: float = 60,
        allowed_hosts: Iterable[str] = (),
        service_key: str | None = None,
        circuit_breaker: ServingCircuitBreaker | None = None,
    ):
        self.allowed_hosts = tuple(allowed_hosts)
        self.service_key = service_key
        ModelOriginPolicy(self.allowed_hosts).validate(base_url)
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._custom_breaker = circuit_breaker is not None
        self._circuit_breaker = circuit_breaker or ServingCircuitBreaker()
        self.cacheable = bool(revision)
        self.identity = {
            "name": "paddleocr_vl_gguf_text",
            "model": model,
            "revision": revision,
            "adapter_version": LOCAL_REGION_VERSION,
            "max_tokens": 256,
        }

    def __call__(self, crop) -> str:
        if not self._circuit_breaker.allow_request():
            raise CircuitOpenError("remote model serving circuit breaker is open")
        extra_kwargs: dict = {}
        if self.allowed_hosts:
            extra_kwargs["allowed_hosts"] = self.allowed_hosts
        if self.service_key:
            extra_kwargs["service_key"] = self.service_key
        if self._custom_breaker:
            extra_kwargs["circuit_breaker"] = self._circuit_breaker
        try:
            value = read_region(
                crop,
                "Text",
                base_url=self.base_url,
                timeout=self.timeout,
                max_tokens=self.identity["max_tokens"],
                model=self.model,
                prompt_profile="paddleocr",
                **extra_kwargs,
            )
        except Exception as exc:
            if not self._custom_breaker and not isinstance(exc, LocalRegionError):
                self._circuit_breaker.record_failure(type(exc).__name__)
            raise
        if not self._custom_breaker:
            self._circuit_breaker.record_success()
        return value.get("text", "") if isinstance(value, dict) else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--model")
    parser.add_argument("--prompt-profile", choices=("generic", "paddleocr", "qwen"), default="generic")
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    try:
        value = read_region(
            os.environ["IDP_REGION_IMAGE"],
            os.environ["IDP_REGION_KIND"],
            base_url=args.url,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            model=args.model,
            prompt_profile=args.prompt_profile,
        )
    except LocalRegionError as exc:
        print(json.dumps({"code": "LOCAL_REGION_REJECTED", "reason": exc.code}), file=sys.stderr)
        return 2
    output = os.environ.get("IDP_REGION_OUTPUT")
    if output:
        Path(output).write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    else:
        print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
