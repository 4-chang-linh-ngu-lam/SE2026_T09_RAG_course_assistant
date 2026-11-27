"""Structured region enrichment (layout proposals + CPU/VLM reading + gap tracking)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import subprocess
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from idp.backends.text_ocr import ocr_labels
from idp.evidence.recovery import _bbox
from idp.input.validation import has_model_artifact_tokens
from idp.processing.figure import intersection_ratio, nested_figure, related_blocks
from idp.processing.formula import validate_latex
from idp.processing.render import sha256_file
from idp.processing.table import GridTableReader, parse_table_html, table_html

ENRICHMENT_VERSION = "idp-structured-9"
MAX_LABEL_EVIDENCE_BYTES = 262_144
KINDS = {
    "table": "Table",
    "formula": "Equation",
    "display_formula": "Equation",
    "inline_formula": "Equation",
    "equation": "Equation",
    "image": "Picture",
    "figure": "Picture",
    "picture": "Picture",
    "diagram": "Diagram",
    "chart": "Chart",
}
VISUAL_TYPES = {"Table", "Equation", "Picture", "Diagram", "Chart", "PictureGroup"}
FIGURE_TYPES = VISUAL_TYPES - {"Table", "Equation"}


def enrichment_summary(pages: list[dict]) -> dict:
    reports = [p["structured_enrichment"] for p in pages if p.get("structured_enrichment")]
    all_regions = [r for report in reports for r in report["regions"]]
    return {
        "pages": len(reports),
        "regions": len(all_regions),
        "kinds": dict(Counter(r["kind"] for r in all_regions)),
        "statuses": dict(Counter(r["status"] for r in all_regions)),
        "seconds": round(sum(r["seconds"] for r in reports), 3),
    }


@dataclass(frozen=True)
class EnrichmentOptions:
    page_budget_seconds: float = 30
    region_timeout_seconds: float = 8
    max_regions: int = 16
    max_crop_pixels: int = 2_000_000
    max_output_chars: int = 32768
    min_visual_pixels_for_model: int = 4096

    def __post_init__(self) -> None:
        if not all(math.isfinite(x) and x > 0 for x in (self.page_budget_seconds, self.region_timeout_seconds)):
            raise ValueError("structured time budgets must be positive and finite")
        if any(
            not isinstance(x, int) or x < 1
            for x in (self.max_regions, self.max_crop_pixels, self.max_output_chars, self.min_visual_pixels_for_model)
        ):
            raise ValueError("structured size limits must be positive integers")


class CommandRegionReader:
    def __init__(self, command: str, revision: str | None = None):
        self.command = command
        self.cacheable = bool(revision)
        self.identity = {
            "name": "command_region",
            "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
            "revision": revision,
        }

    def __call__(self, crop, timeout: float, kind: str) -> dict:
        target = Path(crop).with_suffix(".result.json")
        target.unlink(missing_ok=True)
        env = os.environ.copy()
        env.update(IDP_REGION_IMAGE=str(crop), IDP_REGION_OUTPUT=str(target), IDP_REGION_KIND=kind)
        argv = self.command if os.name == "nt" else shlex.split(self.command)
        try:
            completed = subprocess.run(argv, shell=False, env=env, capture_output=True, timeout=timeout, check=True)
        except subprocess.CalledProcessError as exc:
            from idp.backends.vision_ocr import ERROR_CODES
            try:
                detail = json.loads(exc.stderr) if len(exc.stderr or b"") <= 1024 else {}
            except (ValueError, TypeError):
                detail = {}
            if (
                isinstance(detail, dict)
                and detail.get("code") == "LOCAL_REGION_REJECTED"
                and isinstance(detail.get("reason"), str)
                and detail["reason"] in ERROR_CODES
            ):
                raise RuntimeError("local region rejected: " + detail["reason"]) from exc
            raise
        raw = target.read_bytes() if target.exists() else completed.stdout
        if len(raw) > 2_000_000:
            raise ValueError("region response exceeds size limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("region reader must return an object")
        return value


def _add_flag(block: dict, code: str, **extra) -> None:
    flags = block.setdefault("review_flags", [])
    if not any(f.get("code") == code for f in flags):
        flags.append({"code": code, "severity": "warning", **extra})


def _hold_skipped_region(page, existing, region, kind, box, scale, index, code):
    from idp.processing.reading_order import insert_in_reading_order

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
        "block_id": bid,
        "block_type": kind,
        "bbox": [box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy],
        "text": "",
        "markdown": "",
        "html": "",
        "latex": [],
        "latex_validation": [],
        "source": "structured_region",
        "confidence": None,
        "review_flags": [],
        "asset_paths": [],
        "section_path": [],
        "page": page["page_id"],
        "excluded_from_content": False,
        "layout_score": region.get("layout_score"),
        "structured_status": status,
    }
    _add_flag(block, code, **reason)
    _add_flag(block, "TABLE_EMPTY" if kind == "Table" else "EMPTY_BLOCK", **reason)
    insert_in_reading_order(page["blocks"], block)
    return bid


def _apply_value(block, value, kind, bounds, options, *, visual_size=None):
    if not isinstance(value, dict):
        raise ValueError("invalid or oversized structured response")
    content = value
    if kind in FIGURE_TYPES and "label_detection" in value:
        evidence = value["label_detection"]
        if (
            not isinstance(evidence, dict)
            or len(json.dumps(evidence, ensure_ascii=False).encode("utf-8")) > MAX_LABEL_EVIDENCE_BYTES
        ):
            raise ValueError("invalid or oversized label evidence")
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
        block.update(
            latex=formulas,
            latex_validation=validations,
            markdown="\n".join(f"$${x}$$" for x in formulas),
        )
    elif kind == "Table":
        data = parse_table_html(value.get("table_html") or "")
        if not data["rectangular"]:
            raise ValueError("incomplete table structure")
        safe_html = table_html(data["cells"])
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
        block.update(
            table_html=safe_html,
            markdown=safe_html,
            table_cells=data["cells"],
            table_shape=[data["rows"], data["columns"]],
            table_header_rows=data["header_rows"],
        )
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
                    label = {
                        "text": line["text"],
                        "pixel_bbox": [
                            box[0] * sx + bounds[0],
                            box[1] * sy + bounds[1],
                            box[2] * sx + bounds[0],
                            box[3] * sy + bounds[1],
                        ],
                    }
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


class RegionEnricher:
    """Bounded typed-region processing: layout -> CPU table/labels -> selective VLM."""

    def __init__(
        self,
        detector=None,
        formula_reader=None,
        table_reader=None,
        *,
        language: str = "vie",
        options: EnrichmentOptions | None = None,
        hard_reader=None,
        label_reader=None,
        table_detector=None,
    ):
        self.detector = detector
        self.formula_reader = formula_reader
        self.table_detector = table_detector
        self.table_reader = table_reader or GridTableReader(language)
        self.language = language
        self.options = options or EnrichmentOptions()
        self.hard_reader = hard_reader
        self.label_reader = label_reader
        self.lock = threading.RLock()
        self.cacheable = all(
            reader is None or (bool(getattr(reader, "identity", None)) and getattr(reader, "cacheable", True))
            for reader in (detector, formula_reader, self.table_reader, hard_reader, label_reader, table_detector)
        )
        self.identity = {
            "version": ENRICHMENT_VERSION,
            "options": asdict(self.options),
            "language": language,
            **{
                name: getattr(reader, "identity", None)
                for name, reader in (
                    ("detector", detector),
                    ("formula", formula_reader),
                    ("table", self.table_reader),
                    ("hard", hard_reader),
                    ("labels", label_reader),
                )
            },
        }
        if table_detector is not None:
            self.identity["table_detector"] = getattr(table_detector, "identity", None)

    def _hard_supports(self, kind: str) -> bool:
        supported = getattr(self.hard_reader, "supported_kinds", None)
        return self.hard_reader is not None and (supported is None or kind in supported)

    def enrich_page(self, page: dict, out_dir: str | Path, image_path: str | Path | None = None, *, precomputed_layout: list[dict] | None = None) -> dict:
        with self.lock:
            return self._enrich_page(page, Path(out_dir), image_path, precomputed_layout=precomputed_layout)

    def _enrich_page(self, page: dict, out: Path, image_path, *, precomputed_layout=None) -> dict:
        start, options = time.perf_counter(), self.options
        image_path = image_path or page.get("page_image")
        report = {
            "version": ENRICHMENT_VERSION,
            "config": self.identity,
            "regions": [],
            "flags": [],
            "seconds": 0,
            "candidate_regions": 0,
        }
        page["structured_enrichment"] = report

        def warning(code: str) -> None:
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
        page["source_image_sha256"] = sha256_file(image_path)
        report["image_size"] = list(image.size)

        candidates = []
        for block in page["blocks"]:
            if block["block_type"] in VISUAL_TYPES and block.get("bbox") and not block.get("excluded_from_content"):
                b = block["bbox"]
                candidates.append(({"bbox": [b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy], "kind": block["block_type"]}, block))

        try:
            if precomputed_layout is not None:
                proposed = list(precomputed_layout)
            else:
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
                    nested = next(
                        (
                            old for old, block in candidates
                            if block is None and old["kind"] == kind and nested_figure(old["bbox"], box)
                        ),
                        None,
                    )
                    if nested is not None:
                        prior = nested["bbox"]
                        nested.setdefault("layout_boxes", [prior]).append(box)
                        nested["bbox"] = [
                            min(prior[0], box[0]), min(prior[1], box[1]),
                            max(prior[2], box[2]), max(prior[3], box[3]),
                        ]
                        nested["layout_score"] = max(nested.get("layout_score") or 0, region.get("layout_score") or 0)
                        continue
                overlaps = [old for old in candidates if intersection_ratio(box, old[0]["bbox"]) > 0.7]
                if overlaps:
                    if any(old[0]["kind"] != kind for old in overlaps):
                        warning("STRUCTURED_LAYOUT_DISAGREEMENT")
                    continue
                candidates.append(({**region, "bbox": box, "kind": kind, "kind_original": region.get("kind")}, None))
        except Exception as exc:
            warning("STRUCTURED_LAYOUT_FAILED")
            report["error"] = str(exc)[:300]

        report["candidate_regions"] = len(candidates)
        baseline_text = [
            block for block in page["blocks"]
            if block["block_type"] == "Text" and block.get("bbox") and not block.get("excluded_from_content")
        ]
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
            bounds = [
                max(0, math.floor(box[0]) - pad),
                max(0, math.floor(box[1]) - pad),
                min(image.width, math.ceil(box[2]) + pad),
                min(image.height, math.ceil(box[3]) + pad),
            ]
            entry = {"kind": kind, "pixel_bbox": bounds, "status": "unresolved", "block_id": None}
            report["regions"].append(entry)
            if region.get("layout_boxes"):
                entry["layout_boxes"] = region["layout_boxes"]
            if not can_recognize:
                warning("STRUCTURED_BUDGET_EXHAUSTED")
                entry["recognition_skipped"] = "budget_limit"
                if kind not in FIGURE_TYPES:
                    entry["status"] = "budget_limit"
                    entry["block_id"] = _hold_skipped_region(
                        page, existing, region, kind, box, (sx, sy), index, "STRUCTURED_BUDGET_EXHAUSTED"
                    )
                    continue
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            oversized = width * height > options.max_crop_pixels
            if oversized and kind not in FIGURE_TYPES:
                entry["status"] = "pixel_limit"
                warning("STRUCTURED_PIXEL_LIMIT")
                entry["block_id"] = _hold_skipped_region(
                    page, existing, region, kind, box, (sx, sy), index, "STRUCTURED_PIXEL_LIMIT"
                )
                continue
            bid = existing["block_id"] if existing else f"p{page['page_id']:04d}_s{index:03d}"
            while existing is None and any(b["block_id"] == bid for b in page["blocks"]):
                bid += "_s"
            work.mkdir(parents=True, exist_ok=True)
            crop = work / f"r{index:03d}.png"
            image.crop(tuple(bounds)).save(crop)
            block = existing if existing is not None else {
                "block_id": bid,
                "block_type": kind,
                "bbox": [box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy],
                "text": "",
                "markdown": "",
                "html": "",
                "latex": [],
                "latex_validation": [],
                "source": "structured_region",
                "confidence": None,
                "review_flags": [],
                "asset_paths": [],
                "section_path": [],
                "page": page["page_id"],
                "excluded_from_content": False,
            }
            entry.update(block_id=bid, crop_path=str(crop))
            block.update(pixel_bbox=bounds, block_crop_path=str(crop), crop_sha256=sha256_file(crop))
            block.setdefault("asset_paths", [])
            if str(crop) not in block["asset_paths"]:
                block["asset_paths"].append(str(crop))
            block["layout_score"] = region.get("layout_score", block.get("layout_score"))
            block["related_block_ids"] = related_blocks(page, block)
            if entry.get("recognition_skipped") == "budget_limit":
                _add_flag(block, "STRUCTURED_BUDGET_EXHAUSTED")
            if kind == "Equation":
                label = str(region.get("label") or region.get("kind_original") or "")
                block.setdefault(
                    "formula_kind",
                    "inline" if "inline" in label else "display" if "display" in label else "unknown",
                )
                block["formula_crops"] = [str(crop)]
            elif kind in FIGURE_TYPES:
                block.setdefault("figure_kind", "content")

            inference_crop = crop
            inference_size = (width, height)
            if oversized and can_recognize:
                factor = math.sqrt(options.max_crop_pixels / (width * height))
                iw = max(1, min(int(width * factor), options.max_crop_pixels))
                ih = max(1, min(int(height * factor), options.max_crop_pixels // iw))
                inference_size = (iw, ih)
                inference_crop = crop.with_name(crop.stem + "_inference.png")
                with Image.open(crop) as original:
                    original.resize(inference_size, Image.Resampling.LANCZOS).save(inference_crop)
                entry["inference_crop_path"] = str(inference_crop)
                entry["inference_size"] = list(inference_size)

            before = time.perf_counter()
            timeout = min(options.region_timeout_seconds, max(0.001, options.page_budget_seconds - (before - start)))
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
                        labels = ocr_labels(inference_crop, crop.parent, lang=self.language, timeout=timeout)
                        value = {"labels": labels}
                        producer = {"name": "tesseract_labels"}
                if isinstance(value, dict) and len(json.dumps(value)) <= options.max_output_chars:
                    entry["reading"] = value
                _apply_value(block, value, kind, bounds, options, visual_size=inference_size)
                entry["status"] = "extracted" if kind in {"Table", "Equation"} else "image_preserved"
                if kind == "Table" and (
                    value.get("cell_disagreements")
                    or value.get("ocr_budget_exhausted")
                    or (value.get("ocr_confidence") is not None and value.get("ocr_confidence", 1) < 0.7)
                ):
                    entry["status"] = "needs_verification"
                    block.setdefault("review_flags", []).append({"code": "TABLE_OCR_REVIEW", "severity": "warning"})
                    warning("TABLE_OCR_REVIEW")
                    if self._hard_supports(kind):
                        raise ValueError("table OCR is incomplete, weak, or disagrees between readings")
                if (
                    can_recognize
                    and kind in FIGURE_TYPES
                    and self._hard_supports(kind)
                    and not block.get("description")
                    and width * height >= options.min_visual_pixels_for_model
                ):
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
                        _add_flag(block, "STRUCTURED_REGION_UNRESOLVED")

            block["structured_status"] = entry["status"]
            if kind == "Equation" and not (block.get("text") or "").strip() and not block.get("latex"):
                if not any(f.get("code") == "EMPTY_BLOCK" for f in block.get("review_flags", [])):
                    block.setdefault("review_flags", []).append({
                        "code": "EMPTY_BLOCK",
                        "severity": "warning",
                        "reason": "detected_formula_has_no_verified_transcription",
                    })
            if block.get("figure_kind") == "content" and not block.get("caption"):
                if not any(f.get("code") == "FIGURE_NO_CAPTION" for f in block.get("review_flags", [])):
                    block.setdefault("review_flags", []).append({"code": "FIGURE_NO_CAPTION", "severity": "warning"})
            block["structured_provenance"] = {
                "version": ENRICHMENT_VERSION,
                "producer": producer,
                "crop_sha256": block["crop_sha256"],
            }
            block.setdefault("review_flags", []).append({"code": "STRUCTURED_EXTRACTION_REVIEW", "severity": "warning"})
            warning("STRUCTURED_EXTRACTION_REVIEW")
            if existing is None:
                page["blocks"].append(block)
            if entry["status"] in {"extracted", "extracted_external", "image_preserved", "needs_verification"}:
                x1, y1, x2, y2 = block["bbox"]
                entry["overlapping_text_block_ids"] = [
                    item["block_id"]
                    for item in baseline_text
                    if (a := item["bbox"])[0] >= x1 - 1 and a[1] >= y1 - 1 and a[2] <= x2 + 1 and a[3] <= y2 + 1
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
