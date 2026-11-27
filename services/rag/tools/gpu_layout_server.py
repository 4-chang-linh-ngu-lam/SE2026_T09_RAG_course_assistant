"""HTTP server hosting PP-DocLayoutV3/V2 on a GPU server or Google Colab instance.

Listens on 127.0.0.1:8112 by default so Lumi's `ocr-tunnel` forwards loopback
requests securely over SSH without exposing an unauthenticated port publicly.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import io
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

MAX_REQUEST_BYTES = 20_000_000
MAX_IMAGE_PIXELS = 12_000_000


class _ManagedPaddleLayoutBackend:
    """Wrap either a pinned local model_dir or PaddleOCR's named PP-DocLayoutV3 model."""

    def __init__(
        self,
        *,
        model_dir: str | Path | None = None,
        model_name: str = "PP-DocLayoutV3",
        layout_policy: str = "v3_vl16",
        device: str = "gpu:0",
        cpu_threads: int = 2,
        revision: str | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.revision = revision
        if model_dir is not None:
            from idp.backends.layout import PaddleLayoutDetector

            self._detector = PaddleLayoutDetector(
                model_dir,
                cpu_threads=cpu_threads,
                layout_policy=layout_policy,
                device=device,
            )
            self.identity = {**self._detector.identity, "revision": revision}
            self._use_callable = True
            return

        if layout_policy not in {"default", "v3_vl16"} or (
            layout_policy == "v3_vl16" and model_name != "PP-DocLayoutV3"
        ):
            raise ValueError("v3_vl16 requires PP-DocLayoutV3")
        from paddleocr import LayoutDetection

        postprocess = (
            {
                "threshold": 0.3,
                "layout_nms": True,
                "layout_unclip_ratio": [1.0, 1.0],
                "layout_merge_bboxes_mode": {
                    i: "large" if i in {3, 5, 6, 15, 17} else "union" for i in range(25)
                },
            }
            if layout_policy == "v3_vl16"
            else {}
        )
        self.predict_options = {"filter_overlap_boxes": False} if layout_policy == "v3_vl16" else {}
        self._model = LayoutDetection(
            model_name=model_name,
            device=device,
            cpu_threads=cpu_threads,
            enable_mkldnn=False,
            **postprocess,
        )
        self.identity = {
            "name": model_name,
            "device": device,
            "layout_policy": layout_policy,
            "revision": revision,
        }
        self._use_callable = False

    def predict_image_bytes(self, raw_bytes: bytes) -> list[dict]:
        with Image.open(io.BytesIO(raw_bytes)) as opened:
            w, h = opened.size
            if w <= 0 or h <= 0 or w * h > MAX_IMAGE_PIXELS:
                raise ValueError(f"invalid or oversized image ({w}x{h})")
            rgb = opened.convert("RGB")
        with tempfile.TemporaryDirectory(prefix="lumi-layout-") as tmp_dir:
            img_path = Path(tmp_dir) / "page.png"
            rgb.save(img_path, format="PNG")
            with self._lock:
                if self._use_callable:
                    return self._detector(img_path)
                result = self._model.predict(str(img_path), **self.predict_options)[0].json
                return [
                    {
                        "bbox": b.get("coordinate"),
                        "kind": b.get("label"),
                        "layout_score": b.get("score"),
                    }
                    for b in result.get("res", result).get("boxes", [])
                ]


def create_server(
    host: str,
    port: int,
    backend,
    *,
    service_key: str | None = None,
) -> ThreadingHTTPServer:
    metrics_lock = threading.Lock()
    metrics = {"requests": 0, "errors": 0, "unauthorized": 0, "total_seconds": 0.0}

    class LayoutRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "LumiLayoutServer/1.0"

        def _send_json(self, code: int, body: dict) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write(f"[lumi-layout] {self.address_string()} - {fmt % args}\n")

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.rstrip("/")
            if path in {"", "/health"}:
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "identity": getattr(backend, "identity", None),
                        "revision": getattr(backend, "revision", None),
                    },
                )
                return
            if path == "/metrics":
                with metrics_lock:
                    snap = dict(metrics)
                self._send_json(200, snap)
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/v1/layout":
                self._send_json(404, {"error": "not_found"})
                return
            if service_key:
                provided = self.headers.get("X-Model-Service-Key") or ""
                if not hmac.compare_digest(provided, service_key):
                    with metrics_lock:
                        metrics["unauthorized"] += 1
                    self._send_json(401, {"error": "unauthorized"})
                    return
            started = time.perf_counter()
            try:
                content_len = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                with metrics_lock:
                    metrics["errors"] += 1
                self._send_json(400, {"error": "invalid_content_length"})
                return
            if content_len <= 0 or content_len > MAX_REQUEST_BYTES:
                with metrics_lock:
                    metrics["errors"] += 1
                self._send_json(413, {"error": "payload_too_large"})
                return
            raw_body = self.rfile.read(content_len)
            try:
                data = json.loads(raw_body)
                b64 = data["image_base64"]
                raw_img = base64.b64decode(b64, validate=True)
                boxes = backend.predict_image_bytes(raw_img)
            except Exception as exc:
                with metrics_lock:
                    metrics["errors"] += 1
                self._send_json(400, {"error": "bad_request", "detail": type(exc).__name__})
                return
            with metrics_lock:
                metrics["requests"] += 1
                metrics["total_seconds"] += time.perf_counter() - started
            self._send_json(
                200,
                {
                    "boxes": boxes,
                    "model": (getattr(backend, "identity", None) or {}).get("name"),
                    "revision": getattr(backend, "revision", None),
                },
            )

    return ThreadingHTTPServer((host, port), LayoutRequestHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve PP-DocLayoutV3 over loopback HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8112)
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="Allow binding 0.0.0.0 inside an isolated Docker container mapped to 127.0.0.1 on host",
    )
    parser.add_argument("--model-dir", default=None, help="Local PP-DocLayoutV3 directory")
    parser.add_argument("--model-name", default="PP-DocLayoutV3", choices=("PP-DocLayoutV3", "PP-DocLayoutV2"))
    parser.add_argument("--layout-policy", default="v3_vl16", choices=("default", "v3_vl16"))
    parser.add_argument("--device", default="gpu:0", help="Paddle device, e.g. gpu:0 or cpu")
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--revision", default=None, help="Weights revision tag")
    parser.add_argument(
        "--service-key",
        default=os.environ.get("IDP_MODEL_SERVICE_KEY") or None,
        help="Optional X-Model-Service-Key shared secret",
    )
    args = parser.parse_args(argv)

    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_non_loopback:
        parser.error("Refusing to bind non-loopback host without --allow-non-loopback")

    backend = _ManagedPaddleLayoutBackend(
        model_dir=args.model_dir,
        model_name=args.model_name,
        layout_policy=args.layout_policy,
        device=args.device,
        cpu_threads=args.cpu_threads,
        revision=args.revision,
    )
    server = create_server(args.host, args.port, backend, service_key=args.service_key)
    print(
        json.dumps({
            "event": "lumi_layout_server_listening",
            "host": args.host,
            "port": args.port,
            "identity": backend.identity,
        }),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
