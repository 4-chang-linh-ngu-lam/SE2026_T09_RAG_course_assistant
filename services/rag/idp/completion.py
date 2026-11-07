"""Bounded loopback recognition with replayable request-completion evidence.

Completion proves that issued requests finished, never that recognition is
accurate or that layout detection found every source region. Owned by tools/idp.
"""
from __future__ import annotations

import base64
from concurrent.futures import Future
import hashlib
import io
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace
import urllib.parse
import urllib.request

from PIL import Image

COMPLETION_VERSION = "idp-completion-1"
MAX_REQUEST_BYTES = 16_000_000
MAX_RESPONSE_BYTES = 2_000_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def local_origin(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("recognition requires a loopback HTTP origin")
    # Validate malformed ports now, before writing evidence or loading a model.
    _ = parsed.port
    return url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("recognition does not follow redirects")


def validate_response(raw):
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("recognition response byte limit")
    value = json.loads(raw)
    choices = value.get("choices") if isinstance(value, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("recognition requires exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise ValueError("recognition incomplete or finish reason unavailable")
    message = choice.get("message")
    text = message.get("content") if isinstance(message, dict) else None
    if (not isinstance(text, str) or not text.strip() or len(text) > 32768
            or any(t in text.lower() for t in ("<unreadable>", "[unreadable]"))):
        raise ValueError("recognition empty, unreadable or oversized")
    return text, value


def request_images(payload):
    """Reject external image references, and hash exact bytes sent to inference."""
    if not isinstance(payload, dict) or payload.get("stream") is not False:
        raise ValueError("recognition requires a nonstreaming request")
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 1 or messages[0].get("role") != "user":
        raise ValueError("unexpected recognition messages")
    content = messages[0].get("content")
    if not isinstance(content, list) or len(content) != 2:
        raise ValueError("recognition requires one image and one task")
    images, prompts = [], []
    for part in content:
        if not isinstance(part, dict):
            raise ValueError("invalid recognition content")
        if part.get("type") == "text":
            prompts.append(part.get("text"))
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            prefix, separator, encoded = url.partition(",")
            if not separator or prefix not in {"data:image/png;base64", "data:image/jpeg;base64"}:
                raise ValueError("recognition image must use inline local bytes")
            data = base64.b64decode(encoded, validate=True)
            if len(data) > 10_000_000:
                raise ValueError("recognition image byte limit")
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 2_000_000 or max(image.size) > 10000:
                    raise ValueError("recognition image pixel limit")
                image.verify()
            images.append(digest(data))
        else:
            raise ValueError("unsupported recognition content")
    if len(images) != 1 or len(prompts) != 1 or not isinstance(prompts[0], str) or not prompts[0].strip():
        raise ValueError("recognition image/task mismatch")
    return images


def _write(path, value):
    path = Path(path)
    target = path.with_suffix(path.suffix + ".tmp")
    target.write_bytes(value)
    target.replace(path)


class AuditedLocalClient:
    """Sequential Paddle GenAI protocol adapter, without hidden SDK retries.

    A completed Future preserves Paddle's collection protocol. Inference is
    intentionally serialized so no uncancelled background requests survive a
    failed page. Socket timeout and page budget are accounting limits; the
    enclosing worker process remains the hard wall-clock cancellation boundary.
    """
    backend = "llama-cpp-server"

    def __init__(self, url, *, request_timeout=20, max_requests=64):
        self.url = local_origin(url)
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("invalid recognition timeout")
        if type(max_requests) is not int or not 1 <= max_requests <= 512:
            raise ValueError("invalid recognition request limit")
        self.request_timeout, self.max_requests = request_timeout, max_requests
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.active = False

    def begin_page(self, directory, *, seconds):
        if self.active or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("invalid or overlapping recognition page")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.deadline, self.receipts, self.failed = time.monotonic() + seconds, [], False
        self.active = True

    def create_chat_completion(self, messages, *, return_future=False, timeout=600, **kwargs):
        future = Future()
        try:
            result = self._request(messages, timeout, kwargs)
        except Exception as exc:
            self.failed = True
            future.set_exception(exc)
        else:
            future.set_result(result)
        return future if return_future else future.result()

    def _request(self, messages, timeout, kwargs):
        if not self.active:
            raise ValueError("recognition page not started")
        if len(self.receipts) >= self.max_requests:
            raise ValueError("recognition page request limit")
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("recognition page budget exhausted")
        receipt = {"index": len(self.receipts), "status": "started"}
        self.receipts.append(receipt)
        tick = time.monotonic()
        try:
            extras = kwargs.pop("extra_body", {}) or {}
            allowed = {"temperature", "max_tokens", "top_p", "repetition_penalty", "skip_special_tokens"}
            if set(extras) - allowed or set(kwargs) - allowed or set(extras) & set(kwargs):
                raise ValueError("unsupported recognition parameters")
            payload = {"messages": messages, "stream": False, **kwargs, **extras}
            if "repetition_penalty" in payload:
                penalty = payload.pop("repetition_penalty")
                if type(penalty) not in {int, float} or not math.isfinite(penalty) or penalty <= 0:
                    raise ValueError("invalid recognition repetition penalty")
                # Paddle's GenAI option differs from llama.cpp's wire name.
                # Sending the SDK name unchanged is silently ignored by b12001.
                payload["repeat_penalty"] = penalty
            cap = payload.get("max_tokens")
            if type(cap) is not int or not 1 <= cap <= 8192:
                raise ValueError("invalid recognition token limit")
            images = request_images(payload)
            body = json_bytes(payload)
            if len(body) > MAX_REQUEST_BYTES:
                raise ValueError("recognition request byte limit")
            prefix = f"r{receipt['index']:04d}"
            request_name, response_name = prefix + ".request.json", prefix + ".response.json"
            _write(self.directory / request_name, body)
            receipt.update(request_file=request_name, request_sha256=digest(body), image_sha256=images)
            request = urllib.request.Request(self.url + "/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json"})
            with self.opener.open(request, timeout=min(timeout, self.request_timeout, left)) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            _write(self.directory / response_name, raw)
            receipt.update(response_file=response_name, response_sha256=digest(raw))
            text, value = validate_response(raw)
            if time.monotonic() > self.deadline:
                raise TimeoutError("recognition page budget exceeded")
            receipt.update(status="complete", finish_reason="stop", content_sha256=digest(text.encode("utf-8")),
                response_model=value.get("model"), usage=value.get("usage"))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")])
        except Exception as exc:
            receipt.update(status="failed", error=type(exc).__name__)
            raise
        finally:
            receipt["seconds"] = time.monotonic() - tick
            _write(self.directory / "receipts.json", json_bytes(self.receipts))

    def finish_page(self, *, image_path, raw_result, revision, producer, source_sha256, page):
        if not self.active:
            raise ValueError("recognition page not started")
        self.active = False
        if self.failed or not self.receipts or any(r["status"] != "complete" for r in self.receipts):
            raise ValueError("page has no verified recognition or has failed requests")
        evidence = {"schema_version": COMPLETION_VERSION, "revision": revision, "producer": producer,
            "source_image_sha256": digest(Path(image_path).read_bytes()), "source_sha256": source_sha256,
            "page": page, "raw_result_sha256": digest(json_bytes(raw_result)), "requests": self.receipts,
            "request_count": len(self.receipts), "scope": "all_issued_requests_completed_not_ocr_accuracy"}
        target = self.directory / "completion.json"
        _write(target, json_bytes(evidence))
        return target

    def abort_page(self):
        self.active = False

    def close(self):
        self.abort_page()


def verify_completion(path, *, raw_result, image_path, revision, source_sha256=None, page=None):
    """Replay bounded local evidence; do not accept an unattested boolean flag."""
    path = Path(path).resolve()
    if path.stat().st_size > 2_000_000:
        raise ValueError("completion evidence byte limit")
    evidence = json.loads(path.read_bytes())
    if (evidence.get("schema_version") != COMPLETION_VERSION or evidence.get("revision") != revision
            or evidence.get("scope") != "all_issued_requests_completed_not_ocr_accuracy"
            or evidence.get("source_image_sha256") != digest(Path(image_path).read_bytes())
            or evidence.get("raw_result_sha256") != digest(json_bytes(raw_result))
            or (source_sha256 is not None and evidence.get("source_sha256") != source_sha256)
            or (page is not None and evidence.get("page") != page)):
        raise ValueError("completion evidence does not match source/result/revision")
    receipts = evidence.get("requests")
    if (not isinstance(receipts, list) or not 1 <= len(receipts) <= 512
            or evidence.get("request_count") != len(receipts)):
        raise ValueError("completion evidence request count mismatch")
    for index, receipt in enumerate(receipts):
        if receipt.get("index") != index or receipt.get("status") != "complete" or receipt.get("finish_reason") != "stop":
            raise ValueError("completion evidence has incomplete recognition")
        files = []
        for kind, limit in (("request", MAX_REQUEST_BYTES), ("response", MAX_RESPONSE_BYTES)):
            name = receipt.get(kind + "_file")
            expected = f"r{index:04d}.{kind}.json"
            if name != expected:
                raise ValueError("completion evidence file identity mismatch")
            target = (path.parent / name).resolve()
            if target.parent != path.parent or target.stat().st_size > limit:
                raise ValueError("completion evidence file bounds")
            data = target.read_bytes()
            if digest(data) != receipt.get(kind + "_sha256"):
                raise ValueError("completion evidence file hash mismatch")
            files.append(data)
        if request_images(json.loads(files[0])) != receipt.get("image_sha256"):
            raise ValueError("completion evidence image mismatch")
        text, _ = validate_response(files[1])
        if digest(text.encode("utf-8")) != receipt.get("content_sha256"):
            raise ValueError("completion evidence content mismatch")
    return {"status": "verified", "evidence_sha256": digest(path.read_bytes()),
        "request_count": len(receipts), "producer": evidence.get("producer"), "scope": evidence.get("scope")}
