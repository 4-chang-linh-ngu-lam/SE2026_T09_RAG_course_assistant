"""Bounded typed-region processing; generated content always needs review.

Owned by tools/idp. No service API, model download, or automatic RAG indexing.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time

from PIL import Image

from idp.input.filetypes import InputError
from idp.ocr.recovery import _bbox
from idp.ocr.recognition import EasyOCRRecognizer, RecognitionOptions, verify_page_text
from idp.structured.structure import GridTableReader, parse_table_html, table_html
from idp.documents.text_quality import has_model_artifact_tokens
from idp.validation.validate import validate_latex

ENRICHMENT_VERSION = "idp-structured-9"
MAX_LABEL_EVIDENCE_BYTES = 262_144
KINDS = {"table": "Table", "formula": "Equation", "display_formula": "Equation", "inline_formula": "Equation", "equation": "Equation", "image": "Picture", "figure": "Picture", "picture": "Picture", "diagram": "Diagram", "chart": "Chart"}
VISUAL_TYPES = {"Table", "Equation", "Picture", "Diagram", "Chart", "PictureGroup"}
FIGURE_TYPES = VISUAL_TYPES - {"Table", "Equation"}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enrichment_summary(pages):
    reports = [p["structured_enrichment"] for p in pages if p.get("structured_enrichment")]
    regions = [r for report in reports for r in report["regions"]]
    return {"pages": len(reports), "regions": len(regions), "kinds": dict(Counter(r["kind"] for r in regions)), "statuses": dict(Counter(r["status"] for r in regions)), "seconds": round(sum(r["seconds"] for r in reports), 3)}


@dataclass(frozen=True)
class EnrichmentOptions:
    page_budget_seconds: float = 30
    region_timeout_seconds: float = 8
    max_regions: int = 16
    max_crop_pixels: int = 2_000_000
    max_output_chars: int = 32768
    min_visual_pixels_for_model: int = 4096

    def __post_init__(self):
        if not all(math.isfinite(x) and x > 0 for x in (self.page_budget_seconds, self.region_timeout_seconds)):
            raise ValueError("structured time budgets must be positive and finite")
        if any(not isinstance(x, int) or x < 1 for x in (self.max_regions, self.max_crop_pixels, self.max_output_chars, self.min_visual_pixels_for_model)):
            raise ValueError("structured size limits must be positive integers")


class PaddleFormulaReader:
    def __init__(self, model_dir, *, device="cpu"):
        directory = Path(model_dir).resolve()
        required = [directory / name for name in ("inference.pdiparams", "inference.json", "inference.yml")]
        if not all(path.is_file() for path in required):
            raise InputError("FORMULA_MODEL_UNAVAILABLE", "provide a complete local Paddle formula model directory")
        try:
            from paddleocr import FormulaRecognition
            self.model = FormulaRecognition(model_name=directory.name, model_dir=str(directory), device=device, cpu_threads=2, enable_mkldnn=False)
        except ImportError as exc:
            raise InputError("FORMULA_ENGINE_UNAVAILABLE", "PaddleOCR formula runtime is not installed") from exc
        except Exception as exc:
            raise InputError("FORMULA_ENGINE_FAILED", f"local formula engine could not initialize on {device}") from exc
        self.identity = {"name": directory.name, "device": device, "files_sha256": {p.name: file_hash(p) for p in required}}

    def __call__(self, crop, timeout):
        # Native inference cannot be preempted; the caller checks elapsed budget
        # before starting another region. External commands have hard timeouts.
        result = self.model.predict(str(crop))[0].json
        return {"latex": result.get("res", result).get("rec_formula", "")}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        close = getattr(self.model, "close", None)
        if close is not None:
            close()


class CommandRegionReader:
    def __init__(self, command, revision=None):
        self.command = command
        self.cacheable = bool(revision)
        self.identity = {"name": "command_region", "command_sha256": hashlib.sha256(command.encode()).hexdigest(), "revision": revision}

    def __call__(self, crop, timeout, kind):
        target = Path(crop).with_suffix(".result.json")
        target.unlink(missing_ok=True)
        env = os.environ.copy()
        env.update(IDP_REGION_IMAGE=str(crop), IDP_REGION_OUTPUT=str(target), IDP_REGION_KIND=kind)
        argv = self.command if os.name == "nt" else shlex.split(self.command)
        try:
            completed = subprocess.run(argv, shell=False, env=env, capture_output=True, timeout=timeout, check=True)
        except subprocess.CalledProcessError as exc:
            # Surface only a fixed error code from the bundled adapter. Raw
            # stderr may contain source text, credentials or arbitrary output.
            from idp.ocr.local_region import ERROR_CODES
            try:
                detail = json.loads(exc.stderr) if len(exc.stderr or b"") <= 1024 else {}
            except (ValueError, TypeError):
                detail = {}
            if isinstance(detail, dict) and detail.get("code") == "LOCAL_REGION_REJECTED" and isinstance(detail.get("reason"), str) and detail["reason"] in ERROR_CODES:
                raise RuntimeError("local region rejected: " + detail["reason"]) from exc
            raise
        raw = target.read_bytes() if target.exists() else completed.stdout
        if len(raw) > 2_000_000:
            raise ValueError("region response exceeds size limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("region reader must return an object")
        return value


class RegionEnricher:
    def __init__(self, detector=None, formula_reader=None, table_reader=None, *, language="vie", options=None, hard_reader=None, text_recognizer=None, recognition_options=None, typed_regions=True, label_reader=None, table_detector=None):
        self.detector, self.formula_reader = detector, formula_reader
        self.table_detector = table_detector
        self.recognition_options = recognition_options or RecognitionOptions()
        self.text_recognizer, self.typed_regions = text_recognizer, typed_regions
        self.table_reader = table_reader or GridTableReader(language, text_recognizer=text_recognizer, recognition_options=self.recognition_options)
        self.language, self.options, self.hard_reader = language, options or EnrichmentOptions(), hard_reader
        self.lock = threading.RLock()
        self.label_reader = label_reader
        self.cacheable = all(reader is None or (bool(getattr(reader, "identity", None)) and getattr(reader, "cacheable", True)) for reader in (detector, formula_reader, self.table_reader, hard_reader, text_recognizer, label_reader, table_detector))
        self.identity = {
            "version": ENRICHMENT_VERSION, "options": asdict(self.options), "language": language,
            "typed_regions": typed_regions, "recognition_options": asdict(self.recognition_options),
            "hard_supported_kinds": sorted(hard_reader.supported_kinds) if getattr(hard_reader,"supported_kinds",None) is not None else None,
            **{name: getattr(reader, "identity", None) for name, reader in (("detector", detector), ("formula", formula_reader), ("table", self.table_reader), ("hard", hard_reader), ("text_recognizer", text_recognizer), ("labels", label_reader))},
        }
        if table_detector is not None:
            self.identity["table_detector"] = getattr(table_detector, "identity", None)

    def enrich_page(self, page, out_dir, image_path=None):
        with self.lock:
            started = time.perf_counter()
            if image_path:
                page["page_image"] = str(image_path)
            if self.text_recognizer:
                verify_page_text(page, out_dir, self.text_recognizer, self.options.page_budget_seconds,
                                 language=self.language, options=self.recognition_options,
                                 hard_reader=self.hard_reader if self._hard_supports("Text") else None, hard_timeout_seconds=self.options.region_timeout_seconds)
            if not self.typed_regions:
                return page.get("text_recognition")
            return self._enrich_page(page, Path(out_dir), image_path, started)

    def _hard_supports(self,kind):
        supported=getattr(self.hard_reader,"supported_kinds",None)
        return self.hard_reader is not None and (supported is None or kind in supported)

    def _enrich_page(self, page, out, image_path, started=None):
        from idp.ocr.fast import _run_tesseract, parse_hocr_lines

        start, options = started if started is not None else time.perf_counter(), self.options
        image_path = image_path or page.get("page_image")
        report = {"version": ENRICHMENT_VERSION, "config": self.identity, "regions": [], "flags": [], "seconds": 0, "candidate_regions": 0}
        page["structured_enrichment"] = report

        def warning(code):
            if not any(f.get("code") == code for f in report["flags"]):
                flag = {"code": code, "severity": "warning"}
                report["flags"].append(flag)
                page.setdefault("review", []).append({"page": page["page_id"], "block_id": None, "bbox": None, **flag})

        if not image_path or not Path(image_path).is_file():
            warning("STRUCTURED_IMAGE_UNAVAILABLE")
            return report
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        pw, ph = page.get("page_size") or image.size
        sx, sy = image.width / pw, image.height / ph
        page["page_image"] = str(image_path)
        page["source_image_sha256"] = file_hash(image_path)
        report["image_size"] = list(image.size)
        candidates = []
        for block in page["blocks"]:
            if block["block_type"] in VISUAL_TYPES and block.get("bbox") and not block.get("excluded_from_content"):
                b = block["bbox"]
                candidates.append(({"bbox": [b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy], "kind": block["block_type"]}, block))
        try:
            proposed = self.detector(image_path) if self.detector else []
            if not isinstance(proposed, (list, tuple)) or any(not isinstance(r, dict) for r in proposed):
                raise ValueError("invalid layout output")
        except Exception as exc:
            warning("STRUCTURED_LAYOUT_FAILED")
            report["error"] = str(exc)[:300]
            proposed = []
        if self.table_detector is not None:
            try:
                proposed = [*proposed, *self.table_detector(image_path)]
            except Exception:
                warning("CPU_TABLE_DETECTION_FAILED")
        try:
            for region in proposed:
                kind = KINDS.get(str(region.get("kind", "")).lower())
                box = _bbox(region.get("bbox"), image.size)
                if not kind:
                    continue
                if box is None:
                    warning("STRUCTURED_INVALID_BBOX")
                    continue
                if kind in FIGURE_TYPES:
                    nested = next((old for old, block in candidates if block is None and old["kind"] == kind
                                   and _nested_figure(old["bbox"], box)), None)
                    if nested is not None:
                        prior = nested["bbox"]
                        nested.setdefault("layout_boxes", [prior]).append(box)
                        nested["bbox"] = [min(prior[0], box[0]), min(prior[1], box[1]),
                                          max(prior[2], box[2]), max(prior[3], box[3])]
                        nested["layout_score"] = max(nested.get("layout_score") or 0, region.get("layout_score") or 0)
                        continue
                overlaps = [old for old in candidates if _intersection(box, old[0]["bbox"]) > .7]
                if overlaps:
                    if any(old[0]["kind"] != kind for old in overlaps):
                        warning("STRUCTURED_LAYOUT_DISAGREEMENT")
                    continue
                candidates.append(({**region, "bbox": box, "kind": kind, "kind_original": region.get("kind")}, None))
        except Exception as exc:
            warning("STRUCTURED_LAYOUT_FAILED")
            report["error"] = str(exc)[:300]
        report["candidate_regions"] = len(candidates)
        baseline_text = [block for block in page["blocks"]
                         if block["block_type"] == "Text" and block.get("bbox") and not block.get("excluded_from_content")]
        work = out / "assets" / f"p{page['page_id']:04d}" / "structured"
        budget_used = 0
        prioritized = sorted(enumerate(candidates), key=lambda item: item[1][0]["kind"] == "Equation")
        for index, (region, existing) in prioritized:
            remaining = options.page_budget_seconds - (time.perf_counter() - start)
            can_recognize = budget_used < options.max_regions and remaining > 0
            box = _bbox(region["bbox"], image.size)
            if box is None:
                warning("STRUCTURED_INVALID_BBOX")
                continue
            kind = region["kind"]
            pad = 8 if kind == "Table" else 0
            bounds = [max(0, math.floor(box[0]) - pad), max(0, math.floor(box[1]) - pad), min(image.width, math.ceil(box[2]) + pad), min(image.height, math.ceil(box[3]) + pad)]
            entry = {"kind": kind, "pixel_bbox": bounds, "status": "unresolved", "block_id": None}
            report["regions"].append(entry)
            if region.get("layout_boxes"):
                entry["layout_boxes"] = region["layout_boxes"]
            if not can_recognize:
                warning("STRUCTURED_BUDGET_EXHAUSTED")
                entry["recognition_skipped"] = "budget_limit"
                if kind not in FIGURE_TYPES:
                    entry["status"] = "budget_limit"
                    entry["block_id"] = _hold_skipped_region(page, existing, region, kind, box, (sx, sy), index, "STRUCTURED_BUDGET_EXHAUSTED")
                    continue
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            oversized = width * height > options.max_crop_pixels
            if oversized and kind not in FIGURE_TYPES:
                entry["status"] = "pixel_limit"
                warning("STRUCTURED_PIXEL_LIMIT")
                entry["block_id"] = _hold_skipped_region(page, existing, region, kind, box, (sx, sy), index, "STRUCTURED_PIXEL_LIMIT")
                continue
            bid = existing["block_id"] if existing else f"p{page['page_id']:04d}_s{index:03d}"
            # Stable new IDs must not collide with externally supplied IDs.
            while existing is None and any(b["block_id"] == bid for b in page["blocks"]):
                bid += "_s"
            work.mkdir(parents=True, exist_ok=True)
            crop = work / f"r{index:03d}.png"
            image.crop(tuple(bounds)).save(crop)
            block = existing if existing is not None else {
                "block_id": bid, "block_type": kind, "bbox": [box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy],
                "text": "", "markdown": "", "html": "", "latex": [], "latex_validation": [],
                "source": "structured_region", "confidence": None, "review_flags": [], "asset_paths": [],
                "section_path": [], "page": page["page_id"], "excluded_from_content": False,
            }
            entry.update(block_id=bid, crop_path=str(crop))
            block.update(pixel_bbox=bounds, block_crop_path=str(crop), crop_sha256=file_hash(crop))
            block.setdefault("asset_paths", [])
            if str(crop) not in block["asset_paths"]:
                block["asset_paths"].append(str(crop))
            block["layout_score"] = region.get("layout_score", block.get("layout_score"))
            block["related_block_ids"] = _related(page, block)
            if entry.get("recognition_skipped") == "budget_limit":
                # The image is kept but not read; the page code needs an owner.
                _add_flag(block, "STRUCTURED_BUDGET_EXHAUSTED")
            if kind == "Equation":
                label = str(region.get("label") or region.get("kind_original") or "")
                block.setdefault("formula_kind", "inline" if "inline" in label else "display" if "display" in label else "unknown")
                block["formula_crops"] = [str(crop)]
            elif kind in FIGURE_TYPES:
                block.setdefault("figure_kind", "content")
            inference_crop = crop
            inference_size = (width, height)
            if oversized and can_recognize:
                factor = math.sqrt(options.max_crop_pixels / (width * height))
                inference_width = max(1, min(int(width * factor), options.max_crop_pixels))
                inference_height = max(1, min(int(height * factor), options.max_crop_pixels // inference_width))
                inference_size = (inference_width, inference_height)
                inference_crop = crop.with_name(crop.stem + "_inference.png")
                with Image.open(crop) as original:
                    original.resize(inference_size, Image.Resampling.LANCZOS).save(inference_crop)
                entry["inference_crop_path"] = str(inference_crop)
                entry["inference_size"] = list(inference_size)
            before = time.perf_counter()
            timeout = min(options.region_timeout_seconds, max(.001, options.page_budget_seconds - (before - start)))
            producer = None
            try:
                if can_recognize:
                    budget_used += 1
                if not can_recognize:
                    value = {}
                elif kind == "Equation" and block.get("latex"):
                    value = {"latex": block["latex"]}
                    producer = {"name": "existing_parser"}
                elif kind == "Table" and "<table" in (block.get("table_html") or block.get("html") or "").lower():
                    value = {"table_html": block.get("table_html") or block["html"]}
                    producer = {"name": "existing_parser"}
                elif kind == "Equation":
                    if self.formula_reader is None:
                        raise ValueError("no local formula reader configured")
                    value = self.formula_reader(crop, timeout)
                    producer = getattr(self.formula_reader, "identity", {"name": "custom_formula"})
                elif kind == "Table":
                    value = self.table_reader(crop, timeout)
                    producer = getattr(self.table_reader, "identity", {"name": "custom_table"})
                else:
                    if self.label_reader:
                        value = self.label_reader(inference_crop, timeout)
                        producer = getattr(self.label_reader, "identity", {"name": "custom_label_reader"})
                    else:
                        labels = parse_hocr_lines(_run_tesseract(inference_crop, crop.with_name(crop.stem + "_labels"), self.language, 11, timeout=timeout))
                        value = {"labels": labels}
                        producer = {"name": "tesseract_labels"}
                if isinstance(value, dict) and len(json.dumps(value)) <= options.max_output_chars:
                    entry["reading"] = value
                _apply_value(block, value, kind, bounds, options, visual_size=inference_size)
                entry["status"] = "extracted" if kind in {"Table", "Equation"} else "image_preserved"
                if kind == "Table" and (value.get("cell_disagreements") or value.get("ocr_budget_exhausted") or value.get("ocr_confidence", 1) < .7):
                    entry["status"] = "needs_verification"
                    block.setdefault("review_flags", []).append({"code": "TABLE_OCR_REVIEW", "severity": "warning"})
                    warning("TABLE_OCR_REVIEW")
                    if self._hard_supports(kind):
                        raise ValueError("table OCR is incomplete, weak, or disagrees between readings")
                if can_recognize and kind in FIGURE_TYPES and self._hard_supports(kind) and not block.get("description") and width * height >= options.min_visual_pixels_for_model:
                    left = options.page_budget_seconds - (time.perf_counter() - start)
                    if left <= 0:
                        raise TimeoutError("no budget for visual understanding")
                    visual = self.hard_reader(inference_crop, min(left, options.region_timeout_seconds), kind)
                    _apply_value(block, visual, kind, bounds, options, visual_size=inference_size)
                    producer = getattr(self.hard_reader, "identity", {"name": "hard_reader"})
                    entry["status"] = "extracted_external"
            except Exception as exc:
                entry["error"] = str(exc)[:300]
                if kind in FIGURE_TYPES:
                    warning("VISUAL_RECOGNITION_REVIEW")
                    block.setdefault("review_flags", []).append({"code": "VISUAL_RECOGNITION_REVIEW", "severity": "warning"})
                left = options.page_budget_seconds - (time.perf_counter() - start)
                if self._hard_supports(kind) and left > 0 and entry["status"] in {"unresolved", "needs_verification"}:
                    try:
                        value = self.hard_reader(crop, min(left, options.region_timeout_seconds), kind)
                        if isinstance(value, dict) and len(json.dumps(value)) <= options.max_output_chars:
                            entry["external_reading"] = value
                        if kind == "Table" and block.get("table_cells"):
                            # A complete local ruled grid constrains topology;
                            # a VLM may change readings, not invent/delete cells.
                            external = parse_table_html(value.get("table_html") or "")
                            topology = lambda cells: {(c["row"], c["column"], c.get("rowspan", 1), c.get("colspan", 1)) for c in cells}
                            if topology(external["cells"]) != topology(block["table_cells"]):
                                raise ValueError("external table topology disagrees with local grid")
                        _apply_value(block, value, kind, bounds, options)
                        producer = getattr(self.hard_reader, "identity", {"name": "hard_reader"})
                        entry["status"] = "extracted_external"
                    except Exception as hard_error:
                        entry["external_error"] = str(hard_error)[:300]
                if entry["status"] == "unresolved":
                    if kind in FIGURE_TYPES:
                        entry["status"] = "image_preserved"
                    else:
                        warning("STRUCTURED_REGION_UNRESOLVED")
                        if kind == "Table":
                            _add_flag(block, "TABLE_EMPTY")
                        # The block owns the page code, so the gap has a position.
                        _add_flag(block, "STRUCTURED_REGION_UNRESOLVED")
            block["structured_status"] = entry["status"]
            if kind == "Equation" and not (block.get("text") or "").strip() and not block.get("latex"):
                if not any(f.get("code") == "EMPTY_BLOCK" for f in block.get("review_flags", [])):
                    block.setdefault("review_flags", []).append({"code": "EMPTY_BLOCK", "severity": "warning",
                        "reason": "detected_formula_has_no_verified_transcription"})
            if block.get("figure_kind") == "content" and not block.get("caption"):
                if not any(f.get("code") == "FIGURE_NO_CAPTION" for f in block.get("review_flags", [])):
                    block.setdefault("review_flags", []).append({"code": "FIGURE_NO_CAPTION", "severity": "warning"})
            block["structured_provenance"] = {"version": ENRICHMENT_VERSION, "producer": producer, "crop_sha256": block["crop_sha256"]}
            block.setdefault("review_flags", []).append({"code": "STRUCTURED_EXTRACTION_REVIEW", "severity": "warning"})
            warning("STRUCTURED_EXTRACTION_REVIEW")
            if existing is None:
                page["blocks"].append(block)
            if entry["status"] in {"extracted", "extracted_external", "image_preserved", "needs_verification"}:
                # Containment establishes a review relationship, not OCR accuracy.
                x1, y1, x2, y2 = block["bbox"]
                entry["overlapping_text_block_ids"] = [
                    item["block_id"] for item in baseline_text
                    if (a := item["bbox"])[0] >= x1 - 1 and a[1] >= y1 - 1
                    and a[2] <= x2 + 1 and a[3] <= y2 + 1
                ]
            entry["seconds"] = time.perf_counter() - before
        for order, block in enumerate(page["blocks"]):
            block["order"] = order
        counts = {
            "formula_count": sum(len(b.get("latex") or []) for b in page["blocks"]),
            "figure_count": sum(b["block_type"] in VISUAL_TYPES - {"Equation"} for b in page["blocks"]),
        }
        report["counts"] = counts
        if isinstance(page.get("classification"), dict):
            page["classification"].update(counts)
        report["seconds"] = time.perf_counter() - start
        return report


def _add_flag(block: dict, code: str, **extra) -> None:
    flags = block.setdefault("review_flags", [])
    if not any(f.get("code") == code for f in flags):
        flags.append({"code": code, "severity": "warning", **extra})


def _hold_skipped_region(page, existing, region, kind, box, scale, index, code):
    """Make a region skipped by budget/pixel limit visible as a held block.

    Without a block the region would vanish silently: retrieval would join
    the text around it as if nothing were missing. The placeholder carries
    no text, so it is never indexed, and its code holds it.
    """
    from idp.canonical import insert_in_reading_order

    reason = {"reason": "region_not_transcribed"}
    status = "budget_limit" if code == "STRUCTURED_BUDGET_EXHAUSTED" else "pixel_limit"
    if existing is not None:
        _add_flag(existing, code, **reason)
        existing["structured_status"] = status
        return existing.get("block_id")
    sx, sy = scale
    bid = f"p{page['page_id']:04d}_s{index:03d}"
    while any(b.get("block_id") == bid for b in page["blocks"]):
        bid += "_s"
    block = {
        "block_id": bid, "block_type": kind, "bbox": [box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy],
        "text": "", "markdown": "", "html": "", "latex": [], "latex_validation": [],
        "source": "structured_region", "confidence": None, "review_flags": [], "asset_paths": [],
        "section_path": [], "page": page["page_id"], "excluded_from_content": False,
        "layout_score": region.get("layout_score"),
        "structured_status": status,
    }
    _add_flag(block, code, **reason)
    _add_flag(block, "TABLE_EMPTY" if kind == "Table" else "EMPTY_BLOCK", **reason)
    insert_in_reading_order(page["blocks"], block)
    return bid


def _intersection(a, b):
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return inter / max(1, max((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def _nested_figure(a, b):
    smaller, larger = sorted([(a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])])
    ratio = smaller / larger
    return ratio >= .5 and _intersection(a, b) >= .97 * ratio


def _related(page, target):
    box = target["bbox"]
    candidates = []
    for block in page["blocks"]:
        if block["block_id"] == target["block_id"] or not block.get("bbox"):
            continue
        b = block["bbox"]
        if block["block_type"] in {"Text", "Caption", "SectionHeader"} and min(b[2], box[2]) > max(b[0], box[0]):
            distance = max(0, box[1] - b[3], b[1] - box[3])
            if distance <= max(30, .12 * (page.get("page_size") or [0, 500])[1]):
                candidates.append((distance, block["block_id"]))
    return [bid for _, bid in sorted(candidates)[:6]]


def _apply_value(block, value, kind, bounds, options, *, visual_size=None):
    if not isinstance(value, dict):
        raise ValueError("invalid or oversized structured response")
    content = value
    if kind in {"Picture", "Diagram", "Chart", "PictureGroup"} and "label_detection" in value:
        evidence = value["label_detection"]
        if (not isinstance(evidence, dict) or len(json.dumps(evidence, ensure_ascii=False).encode("utf-8"))
                > MAX_LABEL_EVIDENCE_BYTES):
            raise ValueError("invalid or oversized label evidence")
        # Geometry, hashes and attempt provenance have a separate byte budget.
        # They must not consume the recognized-content character budget, nor
        # grant extra room to labels/descriptions/other provider content.
        content = {key: item for key, item in value.items() if key != "label_detection"}
    if len(json.dumps(content, ensure_ascii=False)) > options.max_output_chars:
        raise ValueError("invalid or oversized structured response")
    if has_model_artifact_tokens(json.dumps(value, ensure_ascii=False)):
        raise ValueError("decoder tokens in structured output")
    if kind == "Equation":
        formulas = value.get("latex")
        formulas = [formulas] if isinstance(formulas, str) else formulas
        if not formulas or not all(isinstance(x, str) and x.strip() for x in formulas):
            raise ValueError("empty formula reading")
        validations = [validate_latex(x).as_dict() for x in formulas]
        if not all(x["valid"] for x in validations):
            raise ValueError("formula syntax validation failed")
        block.update(latex=formulas, latex_validation=validations, markdown="\n".join(f"$${x}$$" for x in formulas))
    elif kind == "Table":
        data = parse_table_html(value.get("table_html") or "")
        if not data["rectangular"]:
            raise ValueError("incomplete table structure")
        safe_html = table_html(data["cells"])
        # Grid geometry is crop-local pixels; retain it separately from HTML semantics.
        geometry = {(raw["row"], raw["column"]): raw for raw in value.get("cells") or []}
        for cell in data["cells"]:
            raw = geometry.get((cell["row"], cell["column"]), {})
            if raw.get("confidence") is not None:
                score = raw["confidence"]
                if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("invalid table-cell recognition confidence")
                cell["recognition_confidence"] = score
            if "cell_local_reading" in raw or "whole_table_reading" in raw:
                cell["alternative_text"] = raw.get("cell_local_reading", raw.get("whole_table_reading"))
            if "text_recognition" in raw:
                cell["text_recognition"] = raw["text_recognition"]
            if "bbox" in raw:
                b = _bbox(raw["bbox"], (bounds[2] - bounds[0], bounds[3] - bounds[1]))
                if b is None:
                    raise ValueError("invalid table-cell pixel geometry")
                cell["pixel_bbox"] = [b[0] + bounds[0], b[1] + bounds[1], b[2] + bounds[0], b[3] + bounds[1]]
        block.update(table_html=safe_html, markdown=safe_html, table_cells=data["cells"], table_shape=[data["rows"], data["columns"]], table_header_rows=data["header_rows"])
        if not data["header_rows"]:
            block.setdefault("review_flags", []).append({"code": "TABLE_HEADER_UNKNOWN", "severity": "warning"})
    else:
        labels = value.get("labels") or []
        if "labels" in value:
            normalized = []
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            image_width, image_height = visual_size or (width, height)
            sx, sy = width / image_width, height / image_height
            for line in labels:
                box = _bbox(line.get("bbox"), (image_width, image_height))
                if box and line.get("text"):
                    label = {"text": line["text"], "pixel_bbox": [box[0] * sx + bounds[0], box[1] * sy + bounds[1], box[2] * sx + bounds[0], box[3] * sy + bounds[1]]}
                    if line.get("recognition_confidence") is not None:
                        score = line["recognition_confidence"]
                        if type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1:
                            raise ValueError("invalid label recognition confidence")
                        label["recognition_confidence"] = score
                    normalized.append(label)
            block["visual_labels"] = normalized
            if value.get("label_detection"):
                block["label_detection"] = value["label_detection"]
                info = value["label_detection"]
                if info.get("budget_exhausted") or info.get("recognized_regions", 0) < info.get("detected_regions", 0):
                    block.setdefault("review_flags", []).append({"code": "VISUAL_LABELS_PARTIAL", "severity": "warning"})
        description = value.get("description")
        if description:
            if not isinstance(description, str):
                raise ValueError("figure description must be text")
            block["description"] = description
        if value.get("chart_data") is not None:
            if not isinstance(value["chart_data"], (dict, list)):
                raise ValueError("chart_data must be an object or array")
            block["chart_data"] = value["chart_data"]


def add_structured_arguments(parser):
    parser.add_argument("--structured-regions", action="store_true", help="typed region extraction; requires --layout-model-dir")
    parser.add_argument("--layout-device", choices=("cpu", "gpu:0"), default="cpu", help="device for the local Paddle layout model")
    formula = parser.add_mutually_exclusive_group()
    formula.add_argument("--formula-model-dir", type=Path, help="optional local Paddle formula model")
    formula.add_argument("--formula-gguf-url", help="loopback HTTP origin of a PaddleOCR-VL llama-server")
    parser.add_argument("--formula-gguf-revision", help="immutable llama-server/model revision required for registry caching")
    parser.add_argument("--formula-device", choices=("cpu", "gpu:0"), default="cpu", help="device for the local Paddle formula model")
    parser.add_argument("--hard-region-cmd", help="optional command for regions the local reader cannot extract")
    parser.add_argument("--hard-region-revision", help="immutable runner/model revision required for registry/resume with a command")
    parser.add_argument("--structured-budget", type=float, default=30)
    parser.add_argument("--text-recognizer-model-dir", type=Path, help="optional local EasyOCR latin_g2.pth directory; CPU review candidates, no layout model required")
    parser.add_argument("--text-recognizer-max-blocks", type=int, default=24)
    parser.add_argument("--ocr-retry-attempts", type=int, choices=(0, 1, 2), default=0, help="opt-in bounded geometric CPU rereads on uncertain OCR crops")
    parser.add_argument("--text-hard-max-calls", type=int, default=2)


@contextmanager
def structured_context(args, parser, detector, language="vie", *, table_detector=None):
    if args.layout_device != "cpu" and detector is None:
        parser.error("--layout-device gpu:0 requires --layout-model-dir")
    if args.formula_device != "cpu" and not args.formula_model_dir:
        parser.error("--formula-device gpu:0 requires --formula-model-dir")
    formula_requested = bool(args.formula_model_dir or args.formula_gguf_url)
    if args.formula_gguf_revision and not args.formula_gguf_url:
        parser.error("--formula-gguf-revision requires --formula-gguf-url")
    if args.ocr_retry_attempts and not args.text_recognizer_model_dir:
        parser.error("--ocr-retry-attempts requires --text-recognizer-model-dir")
    typed_regions = args.structured_regions or table_detector is not None
    if not typed_regions:
        if formula_requested:
            parser.error("formula options require --structured-regions")
        if not args.text_recognizer_model_dir:
            if args.hard_region_cmd or args.hard_region_revision or args.ocr_retry_attempts:
                parser.error("hard-reader options require --text-recognizer-model-dir or --structured-regions")
            yield None
            return
    if args.structured_regions and detector is None and table_detector is None:
        parser.error("--structured-regions requires --layout-model-dir")
    if formula_requested and detector is None:
        parser.error("formula options require --layout-model-dir")
    if args.hard_region_revision and not args.hard_region_cmd:
        parser.error("--hard-region-revision requires --hard-region-cmd")
    try:
        options = EnrichmentOptions(page_budget_seconds=args.structured_budget)
        recognition_options = RecognitionOptions(max_blocks=args.text_recognizer_max_blocks,
                                                  cpu_retry_attempts=args.ocr_retry_attempts, max_hard_calls=args.text_hard_max_calls)
    except ValueError as exc:
        parser.error(str(exc))
    with ExitStack() as stack:
        formula = stack.enter_context(PaddleFormulaReader(args.formula_model_dir, device=args.formula_device)) if args.formula_model_dir else None
        if args.formula_gguf_url:
            from idp.ocr.local_region import PaddleGGUFFormulaReader

            try:
                formula = PaddleGGUFFormulaReader(args.formula_gguf_url, revision=args.formula_gguf_revision)
            except ValueError as exc:
                parser.error(str(exc))
        hard = CommandRegionReader(args.hard_region_cmd, args.hard_region_revision) if args.hard_region_cmd else None
        recognizer = EasyOCRRecognizer(args.text_recognizer_model_dir) if args.text_recognizer_model_dir else None
        yield RegionEnricher(detector, formula, language=language, options=options, hard_reader=hard,
                             text_recognizer=recognizer, recognition_options=recognition_options,
                             typed_regions=typed_regions, table_detector=table_detector)
