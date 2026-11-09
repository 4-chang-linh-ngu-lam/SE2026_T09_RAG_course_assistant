"""Full CPU-layout + self-hosted recognition runner with completion evidence.

Explicit quality lane, not an automatic model download or source-trust grant.
The standalone batch module owns this runtime; no service API is introduced.
"""
from __future__ import annotations

from idp.validation.ingestion_checks import check_ingestion_artifacts

import argparse
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import time
import uuid

from idp.ocr.completion import AuditedLocalClient, digest, json_bytes, local_origin, _write
from idp.input.filetypes import InputLimits, detect_file_type, validate_input, choose_ocr_language
from idp.ocr.quality import ingest_quality

QUALITY_RUNTIME_VERSION = "idp-quality-runtime-3"
SUPPORTED = {"paddleocr": "3.7.0", "paddlex": "3.7.2"}


class PaddleQualityRuntime:
    def __init__(self, layout_model_dir, *, url, revision, request_timeout=20,
            page_budget=120, max_requests=64, max_tokens=4096, ocr_images=False, inline_formulas=False):
        local_origin(url)
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("supply immutable model/projector/server revision")
        if not math.isfinite(page_budget) or page_budget <= 0:
            raise ValueError("invalid quality page budget")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
            raise ValueError("invalid quality token budget")
        if type(ocr_images) is not bool:
            raise ValueError("invalid image OCR option")
        if type(inline_formulas) is not bool:
            raise ValueError("invalid inline formula option")
        from idp.structured import inline_formula
        limit = os.environ.get("OMP_THREAD_LIMIT")
        if limit and (not limit.isdecimal() or int(limit) < 2):
            raise ValueError("OMP_THREAD_LIMIT must allow two CPU layout threads")
        directory = Path(layout_model_dir).resolve()
        weights = [directory / n for n in ("inference.yml", "inference.json", "inference.pdiparams")]
        if not all(p.is_file() for p in weights) or "PP-DocLayoutV3" not in weights[0].read_text("utf-8"):
            raise ValueError("provide complete local PP-DocLayoutV3 weights")
        installed = {name: version(name) for name in SUPPORTED}
        if installed != SUPPORTED:
            raise ValueError("unsupported Paddle runtime; validate the adapter before upgrading")
        self.client = AuditedLocalClient(url, request_timeout=request_timeout, max_requests=max_requests)
        from idp.ocr import completion
        self.identity = {"runner": QUALITY_RUNTIME_VERSION, "revision": revision,
            "runtime": {**installed, "paddlepaddle": version("paddlepaddle")},
            "adapter_sha256": digest(Path(__file__).read_bytes()),
            "completion_adapter_sha256": digest(Path(completion.__file__).read_bytes()),
            "layout_weights_sha256": {p.name: digest(p.read_bytes()) for p in weights},
            "layout_device": "cpu", "cpu_threads": 2, "mkldnn": False,
            "doc_preprocessor": False, "queues": False,
            "recognition_concurrency": 1, "request_timeout": request_timeout,
            "ocr_images": ocr_images,
            "inline_formulas": inline_formulas,
            "inline_adapter_sha256": digest(Path(inline_formula.__file__).read_bytes()),
            "page_budget": page_budget, "max_requests": max_requests, "max_tokens": max_tokens}
        self.revision, self.page_budget, self.max_tokens = revision, page_budget, max_tokens
        self.inline_formulas = inline_formulas
        # Offline weights must already exist; no provider keys or SDK retries.
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["HF_HUB_OFFLINE"] = "1"
        from paddleocr import PaddleOCRVL
        self.pipeline = PaddleOCRVL(pipeline_version="v1.6", device="cpu", cpu_threads=2,
            enable_mkldnn=False, layout_detection_model_name="PP-DocLayoutV3",
            layout_detection_model_dir=str(directory), use_doc_orientation_classify=False,
            use_doc_unwarping=False, use_queues=False, vl_rec_backend="llama-cpp-server",
            use_ocr_for_image_block=ocr_images,
            vl_rec_server_url=self.client.url + "/v1", vl_rec_max_concurrency=1)
        try:
            # Version-scoped private seam, instance-local. Fail on upstream
            # changes; never patch the dependency's classes or global methods.
            model = self.pipeline.paddlex_pipeline.vl_rec_model
            if not hasattr(model, "_genai_client") or model.genai_client.backend != "llama-cpp-server":
                raise ValueError("Paddle recognition client seam changed")
            model._genai_client.close()
            model._genai_client = self.client
        except Exception:
            self.pipeline.close()
            raise

    def recognize_page(self, image, out, *, source_sha256, page, resume=False):
        image, out = Path(image).resolve(), Path(out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        identity = {"producer": self.identity, "source_sha256": source_sha256,
            "source_image_sha256": digest(image.read_bytes()), "page": page}
        record_path = out / "result.json"
        if resume and record_path.is_file():
            from idp.ocr.completion import verify_completion
            try:
                if record_path.stat().st_size > 2_000_000:
                    raise ValueError("quality resume pointer byte limit")
                record = json.loads(record_path.read_bytes())
                if record.get("identity") == identity:
                    raw_path, proof = (out / record["raw"]).resolve(), (out / record["completion"]).resolve()
                    if not raw_path.is_relative_to(out) or not proof.is_relative_to(out):
                        raise ValueError("quality resume file outside page workspace")
                    if raw_path.stat().st_size > 16_000_000:
                        raise ValueError("quality resume raw result byte limit")
                    raw = json.loads(raw_path.read_bytes())
                    verified = verify_completion(proof, raw_result=raw, image_path=image,
                        revision=self.revision, source_sha256=source_sha256, page=page)
                    if verified["producer"] != self.identity:
                        raise ValueError("quality resume producer mismatch")
                    return {"page": page, "image": str(image), "image_sha256": identity["source_image_sha256"],
                        "result": str(raw_path), "completion": str(proof), "reused": True}
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                # Corrupt/missing cache is not accepted and does not trap every
                # worker retry on the same artifact. Retain it, log the reason
                # class without source content, and infer a fresh bounded attempt.
                _write(out / ("cache_rejected_" + uuid.uuid4().hex + ".json"),
                    json_bytes({"reason": type(exc).__name__, "pointer": "result.json"}))
        attempt = out / ("attempt_" + uuid.uuid4().hex)
        self.client.begin_page(attempt, seconds=self.page_budget)
        tick = time.monotonic()
        try:
            outputs = self.pipeline.predict(str(image), temperature=0, max_new_tokens=self.max_tokens, use_queues=False)
            if len(outputs) != 1:
                raise ValueError("quality runtime expected one page result")
            raw = outputs[0].json
            if self.inline_formulas:
                from idp.structured.inline_formula import augment_inline_formulas
                raw = augment_inline_formulas(raw, image, self.client, attempt / "inline_formulas",
                    max_tokens=min(self.max_tokens, 1024))
            proof = self.client.finish_page(image_path=image, raw_result=raw, revision=self.revision,
                producer=self.identity, source_sha256=source_sha256, page=page)
            raw_path = attempt / "raw.json"
            _write(raw_path, json_bytes(raw))
            record = {"identity": identity, "raw": raw_path.relative_to(out).as_posix(),
                "completion": proof.relative_to(out).as_posix(), "seconds": time.monotonic() - tick}
            # Success pointer only changes after every recognition completed.
            _write(record_path, json_bytes(record))
            return {"page": page, "image": str(image), "image_sha256": identity["source_image_sha256"],
                "result": str(raw_path), "completion": str(proof), "reused": False}
        except Exception as exc:
            self.client.abort_page()
            _write(attempt / "failure.json", json_bytes({"error": type(exc).__name__,
                "identity": identity, "seconds": time.monotonic() - tick}))
            raise

    def close(self):
        self.pipeline.close()


def run_quality(input_path, out, *, layout_model_dir, url, revision, language="vie+eng",
        resume=False, dpi=180, max_pixels=1_600_000, requested_pages=None, **runtime_options):
    input_path, out = Path(input_path).resolve(), Path(out).resolve()
    if detect_file_type(input_path) != "pdf":
        raise ValueError("quality runtime expects the original PDF")
    info = validate_input(input_path, "pdf", InputLimits())
    if requested_pages is not None:
        from idp.orchestration.cli import parse_pages
        if parse_pages(requested_pages) != list(range(1, info["pages"] + 1)):
            raise ValueError("quality runtime job must cover every source PDF page")
    choose_ocr_language(language)
    if type(dpi) is not int or not 72 <= dpi <= 400 or type(max_pixels) is not int or not 4096 <= max_pixels <= 2_000_000:
        raise ValueError("invalid quality render limits")
    source_hash = digest(input_path.read_bytes())
    # New source bytes get an isolated work area. No successful published version
    # is activated here; existing Document version rules still govern activation.
    work = out / "work" / "runtime" / source_hash
    work.mkdir(parents=True, exist_ok=True)
    import fitz
    pages = []
    runtime = PaddleQualityRuntime(layout_model_dir, url=url, revision=revision, **runtime_options)
    try:
        with fitz.open(input_path) as pdf:
            for index in range(info["pages"]):
                page = pdf[index]
                area = page.rect.width * page.rect.height
                if not math.isfinite(area) or area <= 0:
                    raise ValueError("invalid source page geometry")
                scale = min(dpi / 72, math.sqrt(max_pixels / area) * .999)
                image = work / f"p{index+1:04d}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                if pixmap.width * pixmap.height > max_pixels:
                    raise ValueError("render exceeded quality pixel limit")
                # Stable PNG bytes bind resume to this rendering, not its name.
                pixmap.save(image)
                pages.append(runtime.recognize_page(image, work / f"p{index+1:04d}",
                    source_sha256=source_hash, page=index+1, resume=resume))
                _write(work / "pages.json", json_bytes({"pages": pages, "expected_pages": info["pages"]}))
        result = ingest_quality(input_path, out, pages, revision=revision, language=language)
        audit_result = check_ingestion_artifacts(out, expected_pages=list(range(1, info["pages"] + 1)))
        _write(out / "batch_summary.json", json_bytes({
            "engine": QUALITY_RUNTIME_VERSION,
            "pipeline_version": result["report"]["pipeline_version"],
            "audit_pass": audit_result["pass"], "audit_errors": audit_result["errors"],
            "ingestion_pass": result["ingestion"]["pass"],
            "failed": result["failed_pages"], "pages": info["pages"],
            "source_sha256": source_hash,
        }))
        return result
    finally:
        runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--layout-model-dir", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--pages", help="optional worker assertion; must cover every source PDF page")
    parser.add_argument("--language", default="vie+eng")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--max-pixels", type=int, default=1_600_000)
    parser.add_argument("--request-timeout", type=float, default=20)
    parser.add_argument("--page-budget", type=float, default=120)
    parser.add_argument("--max-requests", type=int, default=64)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--ocr-images", action="store_true", help="experimental upstream image-block transcription; not a figure-relation model")
    parser.add_argument("--inline-formulas", action="store_true", help="experimental detector-proposed math supplements; preserves original prose and requires review")
    args = parser.parse_args()
    result = run_quality(args.input, args.out, layout_model_dir=args.layout_model_dir, url=args.url,
        revision=args.revision, language=args.language, resume=args.resume, dpi=args.dpi, max_pixels=args.max_pixels,
        requested_pages=args.pages,
        request_timeout=args.request_timeout, page_budget=args.page_budget,
        max_requests=args.max_requests, max_tokens=args.max_tokens, ocr_images=args.ocr_images, inline_formulas=args.inline_formulas)
    print(json.dumps({"pages": len(result["pages"]),
        "ingestion_pass": result["ingestion"]["pass"],
        "canonical_version": result["canonical"]["schema_version"]}))
    summary = json.loads((args.out / "batch_summary.json").read_bytes())
    return 1 if result["failed_pages"] or result["report"]["output_validation_errors"] or not summary["audit_pass"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
