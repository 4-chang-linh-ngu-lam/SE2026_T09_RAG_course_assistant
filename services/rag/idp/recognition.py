"""Independent, local CPU text readings. Candidates never overwrite source text.

Owned by tools/idp. Recognition confidence is engine-specific, not a vote or a
calibrated probability of correctness. Agreement cannot certify semantic OCR.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import math
from pathlib import Path
import time
import unicodedata

from PIL import Image

from .filetypes import InputError
from .recovery import _bbox
from .text_quality import has_model_artifact_tokens

RECOGNITION_VERSION = "idp-recognition-2"
VIETNAMESE = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text or "").split())


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class RecognitionOptions:
    max_blocks: int = 24
    max_lines: int = 16
    max_crop_pixels: int = 2_000_000
    max_output_chars: int = 8192
    max_line_aspect_ratio: int = 80
    cpu_retry_attempts: int = 0
    cpu_retry_budget_seconds: float = 3
    max_hard_calls: int = 2

    def __post_init__(self):
        integers = (self.max_blocks, self.max_lines, self.max_crop_pixels, self.max_output_chars, self.max_line_aspect_ratio)
        if any(type(v) is not int or v < 1 for v in integers):
            raise ValueError("recognition limits must be positive integers")
        if type(self.cpu_retry_attempts) is not int or self.cpu_retry_attempts not in (0, 1, 2):
            raise ValueError("CPU retry attempts must be 0, 1 or 2")
        if type(self.max_hard_calls) is not int or self.max_hard_calls < 0:
            raise ValueError("text hard-reader call limit must be a nonnegative integer")
        if not math.isfinite(self.cpu_retry_budget_seconds) or self.cpu_retry_budget_seconds <= 0:
            raise ValueError("CPU retry budget must be positive and finite")


class EasyOCRRecognizer:
    """Use cached latin_g2 weights, with detection and downloads disabled."""

    def __init__(self, model_dir):
        directory = Path(model_dir).resolve()
        weights = directory / "latin_g2.pth"
        if not weights.is_file():
            raise InputError("TEXT_MODEL_UNAVAILABLE", "provide a local directory containing latin_g2.pth")
        try:
            import easyocr
            import torch
            torch.set_num_threads(2)
            self.reader = easyocr.Reader(["vi"], gpu=False, detector=False,
                                         model_storage_directory=str(directory),
                                         download_enabled=False, verbose=False)
        except ImportError as exc:
            raise InputError("TEXT_ENGINE_UNAVAILABLE", "install EasyOCR in a compatible optional runtime") from exc
        except Exception as exc:
            raise InputError("TEXT_ENGINE_FAILED", "local EasyOCR CPU recognizer could not initialize") from exc
        self.charset = frozenset(unicodedata.normalize("NFC", self.reader.character))
        missing = set(VIETNAMESE + VIETNAMESE.upper()) - self.charset
        if missing:
            raise InputError("TEXT_MODEL_CHARSET", "local recognizer lacks required Vietnamese characters")
        self.identity = {"name": "easyocr_latin_g2", "version": RECOGNITION_VERSION,
                         "weights_sha256": _sha(weights), "language": "vi", "device": "cpu",
                         "cpu_threads": 2, "decoder": "greedy", "quantize": True,
                         "charset_sha256": hashlib.sha256("".join(sorted(self.charset)).encode()).hexdigest(),
                         "unsupported_stem_symbols": sorted(set("²³°µΩ−αβ") - self.charset),
                         "runtime": {name: importlib.metadata.version(name) for name in ("easyocr", "torch")}}

    def __call__(self, image):
        import numpy as np
        width, height = image.size
        results = self.reader.recognize(np.asarray(image.convert("RGB")),
                                       horizontal_list=[[0, width, 0, height]], free_list=[],
                                       decoder="greedy", detail=1, paragraph=False)
        return {"text": " ".join(str(r[1]) for r in results),
                "confidence": sum(float(r[2]) for r in results) / len(results) if results else None}


def read_candidate(reader, image, crop_path, baseline, timeout, *, language="vie", options=None):
    """Tesseract supplies line geometry only; the second engine reads original RGB.

    All subprocesses share the timeout. Native inference is non-preemptible; no
    new line starts after deadline. Budget/line-limit results remain incomplete.
    """
    from .fast import _run_tesseract, parse_hocr_lines

    options = options or RecognitionOptions()
    start = time.monotonic()
    record = {"baseline": baseline, "candidate": None, "status": "unresolved",
              "budget_seconds": timeout,
              "producer": getattr(reader, "identity", None), "lines": [],
              "unsupported_baseline_characters": sorted({c for c in normalized(baseline)
                  if not c.isspace() and c not in getattr(reader, "charset", set())}),
              "auto_applied": False}
    try:
        if not math.isfinite(timeout) or timeout <= 0:
            raise TimeoutError("no recognition budget")
        if image.width * image.height > options.max_crop_pixels:
            raise ValueError("recognition pixel limit")
        crop_path = Path(crop_path)
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(crop_path)
        record.update(crop_path=str(crop_path), crop_sha256=_sha(crop_path))
        lines = parse_hocr_lines(_run_tesseract(crop_path, crop_path.with_suffix(""), language, 6, timeout=timeout))
        if not lines:
            from .ocr_retry import ink_geometry
            geometry = ink_geometry(image)
            # A second recognizer must not require the baseline to detect an
            # isolated symbol/line first. Never send an unsegmented paragraph
            # into the line recognizer when geometric segmentation is ambiguous.
            if geometry and geometry["line_bands"] == 1:
                lines = [{"bbox": geometry["ink_bbox"]}]
                record["geometry_source"] = "foreground_projection"
        for line in lines[:options.max_lines]:
            if time.monotonic() - start >= timeout:
                record["status"] = "budget_exhausted"
                break
            b = _bbox(line["bbox"], image.size)
            if b is None:
                continue
            bounds = [max(0, math.floor(b[0]) - 2), max(0, math.floor(b[1]) - 2),
                      min(image.width, math.ceil(b[2]) + 2), min(image.height, math.ceil(b[3]) + 2)]
            if (bounds[2] - bounds[0]) / max(1, bounds[3] - bounds[1]) > options.max_line_aspect_ratio:
                raise ValueError("recognition line aspect limit")
            value = reader(image.crop(bounds))
            text, score = value.get("text"), value.get("confidence")
            if not isinstance(text, str) or len(text) > options.max_output_chars or has_model_artifact_tokens(text):
                raise ValueError("invalid recognition response")
            if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("invalid recognizer confidence")
            record["lines"].append({"text": text, "confidence": score, "crop_local_bbox": bounds})
        candidate = normalized(" ".join(line["text"] for line in record["lines"]))
        if len(candidate) > options.max_output_chars:
            raise ValueError("recognition output limit")
        record["candidate"] = candidate
        if record["status"] != "budget_exhausted":
            record["status"] = ("line_limit" if len(lines) > options.max_lines else
                                "empty" if not candidate else
                                "agreement" if candidate == normalized(baseline) else "disagreement")
        # Even a successful last native call may overrun the soft deadline.
        record["deadline_exceeded"] = time.monotonic() - start > timeout
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
    record["seconds"] = time.monotonic() - start
    if options.cpu_retry_attempts and (record["status"] != "agreement" or record["unsupported_baseline_characters"]):
        from .ocr_retry import retry_ocr
        remaining = timeout - (time.monotonic() - start)
        if remaining > .05 and record.get("crop_path"):
            record["cpu_retry"] = retry_ocr(image, Path(crop_path).with_name(Path(crop_path).stem + "_retry"), baseline,
                                            min(remaining, options.cpu_retry_budget_seconds), language=language,
                                            max_attempts=options.cpu_retry_attempts, max_pixels=options.max_crop_pixels,
                                            max_output_chars=options.max_output_chars)
        else:
            record["cpu_retry"] = {"status": "budget_exhausted", "attempts": [], "auto_applied": False}
        record["seconds"] = time.monotonic() - start
        record["deadline_exceeded"] = record["seconds"] > timeout
    return record


def verify_page_text(page, out, reader, timeout, *, language="vie", options=None, hard_reader=None, hard_timeout_seconds=8):
    options = options or RecognitionOptions()
    started = time.monotonic()
    report = {"version": RECOGNITION_VERSION, "policy": "review_candidates_only",
              "page_budget_seconds": timeout,
              "producer": getattr(reader, "identity", None), "options": asdict(options),
              "blocks": [], "flags": [], "seconds": 0}
    report["hard_calls"] = 0
    page["text_recognition"] = report

    def flag(code, block=None):
        value = {"code": code, "severity": "warning"}
        if block is not None:
            block.setdefault("review_flags", []).append(value)
        else:
            report["flags"].append(value)
            page.setdefault("review", []).append({"page": page["page_id"], "block_id": None, "bbox": None, **value})

    path = page.get("page_image")
    if not path or not Path(path).is_file():
        flag("TEXT_RECOGNIZER_IMAGE_UNAVAILABLE")
        return report
    with Image.open(path) as source:
        image = source.convert("RGB")
    pw, ph = page.get("page_size") or image.size
    if not pw or not ph:
        flag("TEXT_RECOGNIZER_IMAGE_UNAVAILABLE")
        return report
    sx, sy = image.width / pw, image.height / ph
    blocks = [b for b in page["blocks"] if b.get("block_type") in {"Text", "Caption", "SectionHeader"}
              and str(b.get("source", "")).startswith("tesseract") and b.get("text") and not b.get("excluded_from_content")]
    # Spend limited CPU on weak readings first. Scores only rank this baseline
    # engine, never compare them to the independent recognizer's confidence.
    blocks.sort(key=lambda b: b.get("confidence") if isinstance(b.get("confidence"), (int, float)) else 0)
    for index, block in enumerate(blocks):
        remaining = timeout - (time.monotonic() - started)
        if index >= options.max_blocks or remaining <= .05:
            flag("TEXT_RECOGNIZER_BUDGET_EXHAUSTED")
            break
        raw = block.get("bbox")
        box = _bbox([raw[0] * sx, raw[1] * sy, raw[2] * sx, raw[3] * sy], image.size) if raw and len(raw) == 4 else None
        if box is None:
            flag("TEXT_RECOGNIZER_FAILED", block)
            continue
        bounds = [max(0, math.floor(box[0]) - 2), max(0, math.floor(box[1]) - 2),
                  min(image.width, math.ceil(box[2]) + 2), min(image.height, math.ceil(box[3]) + 2)]
        crop = Path(out) / "assets" / f"p{page['page_id']:04d}" / "recognition" / f"b{index:04d}.png"
        reading = read_candidate(reader, image.crop(bounds), crop, block["text"], remaining, language=language, options=options)
        reading["pixel_bbox"] = bounds
        block["text_recognition"] = reading
        risk = reading["status"] != "agreement" or bool(reading["unsupported_baseline_characters"])
        if risk and hard_reader and options.max_hard_calls:
            left = timeout - (time.monotonic() - started)
            if report["hard_calls"] >= options.max_hard_calls or left <= .05 or not reading.get("crop_path"):
                reading["external_reading"] = {"status": "not_attempted", "reason": "budget_or_crop_unavailable", "auto_applied": False}
                flag("TEXT_RECOGNIZER_BUDGET_EXHAUSTED", block)
            else:
                report["hard_calls"] += 1
                external = {"producer": getattr(hard_reader, "identity", None), "auto_applied": False}
                reading["external_reading"] = external
                flag("TEXT_EXTERNAL_REVIEW", block)
                try:
                    from .ocr_retry import complete_ink_bounds
                    hard_box, context_status = complete_ink_bounds(image, bounds)
                    hard_crop = crop.with_name(crop.stem + "_hard.png")
                    image.crop(hard_box).save(hard_crop)
                    external.update(crop_path=str(hard_crop), crop_sha256=_sha(hard_crop), pixel_bbox=hard_box, context_status=context_status)
                    left = timeout - (time.monotonic() - started)
                    if left <= 0:
                        raise TimeoutError("no budget after hard crop preparation")
                    value = hard_reader(hard_crop, min(left, hard_timeout_seconds), "Text")
                    text = value.get("text") if isinstance(value, dict) else None
                    if not isinstance(text, str) or not text.strip() or len(text) > options.max_output_chars or has_model_artifact_tokens(text):
                        raise ValueError("invalid external text reading")
                    external.update(status="candidate", text=text)
                except Exception as exc:
                    external.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
                    flag("TEXT_RECOGNIZER_FAILED", block)
        report["blocks"].append({"block_id": block["block_id"], "status": reading["status"]})
        if reading["status"] != "agreement":
            flag("TEXT_RECOGNIZER_DISAGREEMENT" if reading["status"] == "disagreement" else "TEXT_RECOGNIZER_FAILED", block)
        if reading["unsupported_baseline_characters"]:
            flag("TEXT_RECOGNIZER_UNSUPPORTED_CHARACTERS", block)
        if reading.get("deadline_exceeded"):
            flag("TEXT_RECOGNIZER_BUDGET_EXHAUSTED")
    report["seconds"] = time.monotonic() - started
    return report
