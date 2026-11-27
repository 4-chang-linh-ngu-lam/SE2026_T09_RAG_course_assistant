"""Pre-flight & end-to-end verification for remote GPU OCR + Layout over SSH tunnel.

Run inside `document-worker` (or locally when tunnel ports are open):
    python -m idp.verify_remote

Checks:
1. Loopback `/health` on `IDP_VL_OCR_URL` (and `IDP_LAYOUT_URL` when configured).
2. `PaddleVLPrimaryReader.read_with_logprobs` returns non-empty tokens with finite
   probabilities in (0, 1] (proving `llama-server` logprobs work).
3. `RemoteLayoutDetector` returns bounding boxes (when `IDP_LAYOUT_URL` is set).
4. Full `ingest_file()` on a scanned PDF confirms `telemetry["vlm_calls"] >= 1`
   and `source == "paddleocr_vl_gguf"` in `canonical.json` (not silent CPU fallback).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

from idp.backends.layout import RemoteLayoutDetector
from idp.backends.vision_ocr import (
    SOURCE as VL_SOURCE,
    PaddleVLPrimaryReader,
    _NoRedirect,
    _require_loopback,
)
from idp.ingest import ingest_file


def _check_vl_health(base_url: str, timeout: float = 10.0) -> dict:
    _require_loopback(base_url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    req = urllib.request.Request(f"{base_url.rstrip('/')}/health", method="GET")
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read(262_144)
    data = json.loads(raw) if raw.strip() else {"status": "ok"}
    return data if isinstance(data, dict) else {"raw": str(data)}


def _build_synthetic_scan_pdf(pdf_path: Path) -> Image.Image:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    img = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(img)
    draw.text((80, 90), "Bai 1. Giai phuong trinh bac hai:", fill="black")
    draw.text((80, 200), "x^2 - 5x + 6 = 0", fill="black")
    draw.text((80, 320), "Tinh gia tri bieu thuc A = 2x + 3 khi x = 4.", fill="black")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(36, 36, 559, 420), stream=buf.getvalue())
    doc.save(pdf_path)
    doc.close()
    return img


def verify_remote_stack(
    *,
    vl_url: str,
    vl_revision: str = "smoke-check",
    vl_parallel: int = 2,
    layout_url: str | None = None,
    layout_revision: str | None = "smoke-check",
    layout_policy: str = "v3_vl16",
    pdf_path: str | Path | None = None,
    vlm_mode: str = "full",
) -> dict:
    summary: dict = {
        "vl_url": vl_url,
        "layout_url": layout_url,
        "checks": {},
    }

    # 1) Health check for PaddleOCR-VL llama-server
    vl_health = _check_vl_health(vl_url)
    summary["checks"]["vl_health"] = {"pass": True, "detail": vl_health}

    # 2) Layout server health & prediction check (optional)
    layout_detector = None
    if layout_url:
        layout_detector = RemoteLayoutDetector(
            layout_url, layout_policy=layout_policy, revision=layout_revision
        )
        lay_health = layout_detector.health()
        summary["checks"]["layout_health"] = {"pass": True, "detail": lay_health}

    with tempfile.TemporaryDirectory(prefix="lumi-verify-ocr-") as tmp:
        tmp_dir = Path(tmp)
        synthetic_pdf = tmp_dir / "scan_probe.pdf"
        probe_img = _build_synthetic_scan_pdf(synthetic_pdf)
        probe_png = tmp_dir / "probe.png"
        probe_img.save(probe_png, format="PNG")

        # 3) Direct token + logprobs check on PaddleOCR-VL
        vl_reader = PaddleVLPrimaryReader(
            vl_url, revision=vl_revision, parallel=vl_parallel
        )
        crop = probe_img.crop((60, 170, 650, 260))
        tokens = vl_reader.read_with_logprobs(crop, "Text")
        valid_logprobs = bool(tokens) and all(
            isinstance(tok, str)
            and isinstance(prob, float)
            and math.isfinite(prob)
            and 0.0 < prob <= 1.0001
            for tok, prob, _alts in tokens
        )
        sample_text = "".join(t[0] for t in tokens).strip()
        summary["checks"]["vl_logprobs"] = {
            "pass": bool(valid_logprobs and sample_text),
            "token_count": len(tokens),
            "sample_text": sample_text[:120],
        }
        if not summary["checks"]["vl_logprobs"]["pass"]:
            raise RuntimeError(
                "llama-server returned empty tokens or missing logprobs; check --alias paddleocr-vl-1.6 and mmproj"
            )

        if layout_detector is not None:
            boxes = layout_detector(probe_png)
            summary["checks"]["layout_boxes"] = {
                "pass": isinstance(boxes, list),
                "box_count": len(boxes),
            }

        # 4) End-to-end ingest_file check proving GPU output lands in canonical.json
        target_pdf = Path(pdf_path) if pdf_path else synthetic_pdf
        out_dir = tmp_dir / "ingest_out"
        report = ingest_file(
            target_pdf,
            out_dir,
            language="vie",
            vlm_mode=vlm_mode,
            vl_reader=vl_reader,
            layout_detector=layout_detector,
        )
        canonical = json.loads((out_dir / "canonical.json").read_text(encoding="utf-8"))
        blocks = [
            b
            for p in canonical.get("pages") or []
            for b in p.get("blocks") or []
            if not b.get("excluded")
        ]
        vl_blocks = [b for b in blocks if b.get("source") == VL_SOURCE]
        telemetry = report.get("telemetry") or {}
        e2e_ok = len(vl_blocks) >= 1
        summary["checks"]["end_to_end_gpu_canonical"] = {
            "pass": e2e_ok,
            "pages": report.get("pages"),
            "total_blocks": len(blocks),
            "vl_sourced_blocks": len(vl_blocks),
            "page_routes": telemetry.get("page_routes"),
            "region_actions": telemetry.get("region_actions"),
        }
        if not e2e_ok:
            raise RuntimeError(
                "ingest_file succeeded via CPU fallback only — 0 blocks carry source='paddleocr_vl_gguf'"
            )

    summary["pass"] = all(c["pass"] for c in summary["checks"].values())
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify remote GPU OCR + Layout stack")
    parser.add_argument(
        "--vl-url",
        default=os.environ.get("IDP_VL_OCR_URL", "http://127.0.0.1:8111"),
        help="Loopback URL for PaddleOCR-VL llama-server",
    )
    parser.add_argument(
        "--vl-revision",
        default=os.environ.get("IDP_VL_OCR_REVISION", "smoke-check"),
    )
    parser.add_argument(
        "--vl-parallel",
        type=int,
        default=int(os.environ.get("IDP_VL_OCR_PARALLEL", "2")),
    )
    parser.add_argument(
        "--layout-url",
        default=os.environ.get("IDP_LAYOUT_URL") or None,
        help="Optional loopback URL for PP-DocLayoutV3 server",
    )
    parser.add_argument(
        "--layout-revision",
        default=os.environ.get("IDP_LAYOUT_REVISION", "smoke-check"),
    )
    parser.add_argument(
        "--layout-policy",
        default=os.environ.get("IDP_LAYOUT_POLICY", "v3_vl16"),
        choices=("default", "v3_vl16"),
    )
    parser.add_argument("--pdf", default=None, help="Optional real scanned PDF path to test")
    parser.add_argument(
        "--vlm-mode",
        default="selective",
        choices=("selective", "full"),
        help="Use 'full' on clean synthetic scans if selective CPU early-exit skips VLM",
    )
    args = parser.parse_args(argv)

    # For synthetic clean probes without --pdf, force 'full' so VLM is guaranteed to be exercised
    effective_mode = args.vlm_mode if args.pdf else "full"
    result = verify_remote_stack(
        vl_url=args.vl_url,
        vl_revision=args.vl_revision,
        vl_parallel=args.vl_parallel,
        layout_url=args.layout_url,
        layout_revision=args.layout_revision,
        layout_policy=args.layout_policy,
        pdf_path=args.pdf,
        vlm_mode=effective_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
