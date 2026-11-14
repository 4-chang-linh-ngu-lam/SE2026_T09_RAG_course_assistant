"""Bounded recovery of text regions missed by whole-page OCR.

Preserve baseline text, append missing lines with pixel provenance, and retain
conflicting readings for review. Layout/recognition scores are not certificates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from pathlib import Path
import time
import threading
import copy
from collections import OrderedDict
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from idp.documents.text_quality import has_model_artifact_tokens, is_garbled_text

RECOVERY_VERSION = "idp-region-1"
TEXT_KINDS = {"text", "paragraph_title", "doc_title", "header", "footer", "panel"}


@dataclass(frozen=True)
class RecoveryOptions:
    coverage_min: float = .35
    confidence_min: float = 60.0  # Tesseract hOCR scale, not layout confidence.
    max_regions: int = 12
    page_budget_seconds: float = 15.0
    region_timeout_seconds: float = 5.0
    max_crop_pixels: int = 2_000_000
    padding: int = 4

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.coverage_min, self.confidence_min, self.page_budget_seconds, self.region_timeout_seconds)):
            raise ValueError("recovery settings must be finite")
        if not 0 <= self.coverage_min <= 1 or not 0 <= self.confidence_min <= 100:
            raise ValueError("invalid recovery thresholds")
        if self.max_regions < 1 or self.page_budget_seconds <= 0 or self.region_timeout_seconds <= 0:
            raise ValueError("recovery budgets must be positive")
        if self.max_crop_pixels < 1 or self.padding < 0:
            raise ValueError("invalid recovery crop limits")


def cli_recovery_options(parser, args):
    if getattr(args, "layout_policy", "default") != "default" and not args.layout_model_dir:
        parser.error("--layout-policy requires --layout-model-dir")
    if args.no_region_recovery and args.layout_model_dir and not getattr(args, "structured_regions", False):
        parser.error("--layout-model-dir requires region recovery")
    try:
        return RecoveryOptions(page_budget_seconds=args.region_budget)
    except ValueError as exc:
        parser.error(str(exc))


def _bbox(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        values = [float(x) for x in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in values):
        return None
    x1, y1, x2, y2 = values
    width, height = size
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def _inside(line, box):
    b = line["bbox"]
    return box[0] <= (b[0] + b[2]) / 2 <= box[2] and box[1] <= (b[1] + b[3]) / 2 <= box[3]


def vertical_coverage(lines: list[dict], box: list[float]) -> float:
    intervals = sorted(
        (max(box[1], line["bbox"][1]), min(box[3], line["bbox"][3]))
        for line in lines if _inside(line, box)
    )
    covered, end = 0.0, -math.inf
    for y1, y2 in intervals:
        covered += max(0, y2 - max(y1, end))
        end = max(end, y2)
    return min(1.0, covered / max(1, box[3] - box[1]))


def detect_panels(image_path: str | Path) -> list[dict]:
    """Cheap visual hints for coloured callouts, independent of subject words.

    A hint is not a text classification. OCR additions stay review-only.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("cannot read recovery image")
    height, width = image.shape[:2]
    # Bound detection cost independently of image resolution.
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
            rw >= max(60, int(.08 * w)) and rh >= 28
            and .004 * w * h <= area <= .45 * w * h
            and area / (rw * rh) >= .55
        ):
            regions.append({"bbox": [float(x / scale), float(y / scale), float((x + rw) / scale), float((y + rh) / scale)], "kind": "panel"})
    return regions


class PaddleLayoutDetector:
    """Optional local CPU adapter. One model instance serves the entire run."""

    def __init__(self, model_dir: str | Path, cpu_threads: int = 2, *, layout_policy="default"):
        from idp.input.filetypes import InputError

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
        # PaddleX 3.7.2 PaddleOCR-VL-1.6.yaml: standalone detection defaults
        # suppress nested inline formulas. This explicit opt-in reproduces the
        # upstream pipeline's postprocessing, without book-dependent thresholds.
        postprocess = ({"threshold": .3, "layout_nms": True,
            "layout_unclip_ratio": [1.0, 1.0],
            "layout_merge_bboxes_mode": {i: "large" if i in {3, 5, 6, 15, 17} else "union" for i in range(25)}}
            if layout_policy == "v3_vl16" else {})
        self.predict_options = {"filter_overlap_boxes": False} if layout_policy == "v3_vl16" else {}
        try:
            from paddleocr import LayoutDetection
        except ImportError as exc:
            raise InputError("LAYOUT_ENGINE_UNAVAILABLE", "install the optional PaddleOCR runtime or omit --layout-model-dir") from exc
        try:
            self.model = LayoutDetection(
                model_name=model_name, model_dir=str(self.model_dir),
                device="cpu", cpu_threads=cpu_threads, enable_mkldnn=False, **postprocess,
            )
        except Exception as exc:
            raise InputError("LAYOUT_ENGINE_FAILED", "local CPU layout engine could not initialize") from exc
        def digest(path):
            sha = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(chunk)
            return sha.hexdigest()

        self.identity = {
            "name": model_name, "device": "cpu",
            "layout_policy": layout_policy, "postprocess": json.loads(json.dumps(postprocess)), "cpu_threads": cpu_threads,
            "predict_options": dict(self.predict_options),
            "files_sha256": {path.name: digest(path) for path in required},
        }
        self._cache, self._lock = OrderedDict(), threading.RLock()

    def __call__(self, image_path):
        sha = hashlib.sha256()
        with Path(image_path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        key = sha.hexdigest()
        with self._lock:
            if key not in self._cache:
                result = self.model.predict(str(image_path), **self.predict_options)[0].json
                self._cache[key] = [{"bbox": b.get("coordinate"), "kind": b.get("label"), "layout_score": b.get("score")} for b in result.get("res", result).get("boxes", [])]
                if len(self._cache) > 8:
                    self._cache.popitem(last=False)
            self._cache.move_to_end(key)
            return copy.deepcopy(self._cache[key])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.model.close()


def _overlapping_line(a, b):
    # A malformed tall word box can cross the next row. Median word bands
    # decide overlap; the full source bbox remains the citation boundary.
    aa, bb = a.get("text_bbox", a["bbox"]), b.get("text_bbox", b["bbox"])
    ix = max(0, min(aa[2], bb[2]) - max(aa[0], bb[0]))
    iy = max(0, min(aa[3], bb[3]) - max(aa[1], bb[1]))
    return ix / max(1, min(aa[2] - aa[0], bb[2] - bb[0])) >= .5 and iy / max(1, min(aa[3] - aa[1], bb[3] - bb[1])) >= .5


def _insert_line(lines, line):
    """Spatial insertion without reordering or rewriting baseline lines."""
    b = line["bbox"]
    for index, old in enumerate(lines):
        a = old["bbox"]
        overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        if a[1] > b[1] and overlap / max(1, min(a[2] - a[0], b[2] - b[0])) >= .5:
            lines.insert(index, line)
            return
    lines.append(line)


def recover_text_regions(
    image_path: str | Path, baseline: list[dict], work: str | Path,
    *, lang: str = "vie", profile: str = "general",
    detector: Callable | None = None, options: RecoveryOptions | None = None,
    read_crop: Callable | None = None,
) -> tuple[list[dict], dict]:
    from idp.ocr.fast import _run_tesseract, parse_hocr_lines

    options = options or RecoveryOptions()
    started = time.perf_counter()
    image_path, work = Path(image_path), Path(work)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    result = [dict(line) for line in baseline]
    report = {
        "version": RECOVERY_VERSION,
        "options": asdict(options),
        "detector": getattr(detector, "identity", {"name": "colour_panels"}),
        "regions": [], "flags": [], "lines_added": 0,
        "baseline_lines": len(baseline), "candidate_regions": 0,
    }

    def flag(code):
        if not any(f["code"] == code for f in report["flags"]):
            report["flags"].append({"code": code, "severity": "warning"})

    try:
        proposed = (detector or detect_panels)(image_path)
        if not isinstance(proposed, (list, tuple)) or any(not isinstance(region, dict) for region in proposed):
            raise ValueError("layout detector must return a list of region objects")
    except Exception as exc:
        flag("OCR_REGION_DETECTION_FAILED")
        report["error"] = str(exc)[:300]
        report["seconds"] = time.perf_counter() - started
        return result, report
    candidates, seen = [], set()
    # Garbage tokens do not demonstrate that a paragraph has been read.
    # This only routes a retry; originals remain available for review.
    reliable = [line for line in baseline if (
        isinstance(line.get("confidence"), (int, float))
        and options.confidence_min <= line["confidence"] <= 100
        and len(line.get("text", "")) >= 8
        and sum(c.isalpha() for c in line["text"]) / len(line["text"]) >= .35
    )]
    for region in proposed:
        if region.get("kind") not in TEXT_KINDS:
            continue
        box = _bbox(region.get("bbox"), image.size)
        if box is None:
            flag("OCR_REGION_INVALID_BBOX")
            continue
        key = tuple(round(x) for x in box)
        if key in seen:
            continue
        seen.add(key)
        coverage = vertical_coverage(reliable, box)
        if coverage < options.coverage_min:
            candidates.append((box, coverage, region.get("kind")))
    candidates.sort(key=lambda x: (x[0][1], x[0][0]))
    report["candidate_regions"] = len(candidates)
    for index, (box, coverage, kind) in enumerate(candidates):
        remaining = options.page_budget_seconds - (time.perf_counter() - started)
        if index >= options.max_regions or remaining <= 0:
            flag("OCR_REGION_BUDGET_EXHAUSTED")
            break
        x1, y1, x2, y2 = box
        pad = options.padding
        bounds = [max(0, int(x1) - pad), max(0, int(y1) - pad), min(image.width, math.ceil(x2) + pad), min(image.height, math.ceil(y2) + pad)]
        entry = {"region_id": f"r{index:03d}", "bbox": box, "crop_bbox": bounds, "kind": kind, "baseline_coverage": coverage, "status": "unresolved", "lines_added": 0, "alternatives": []}
        report["regions"].append(entry)
        if (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) > options.max_crop_pixels:
            entry["status"] = "pixel_limit"
            flag("OCR_REGION_UNRESOLVED")
            continue
        work.mkdir(parents=True, exist_ok=True)
        crop = work / f"{entry['region_id']}.png"
        image.crop(tuple(bounds)).save(crop)
        entry["crop_path"] = str(crop)
        begin = time.perf_counter()
        try:
            timeout = min(options.region_timeout_seconds, max(.001, options.page_budget_seconds - (begin - started)))
            local = read_crop(crop, timeout) if read_crop else parse_hocr_lines(_run_tesseract(crop, crop.with_suffix(""), lang, 6, timeout=timeout), profile)
            for line in local:
                b = _bbox(line.get("bbox"), (bounds[2] - bounds[0], bounds[3] - bounds[1]))
                text = (line.get("text") or "").strip()
                confidence = line.get("confidence", 0)
                if (
                    b is None or not isinstance(confidence, (int, float)) or not math.isfinite(confidence)
                    or not options.confidence_min <= confidence <= 100 or len(text) < 8
                    or sum(c.isalpha() for c in text) / max(1, len(text)) < .35
                    or is_garbled_text(text) or has_model_artifact_tokens(text)
                ):
                    continue
                reading = {**line, "text": text, "bbox": [b[0] + bounds[0], b[1] + bounds[1], b[2] + bounds[0], b[3] + bounds[1]], "recovery_region_id": entry["region_id"]}
                def translated(local_box):
                    return [local_box[0] + bounds[0], local_box[1] + bounds[1], local_box[2] + bounds[0], local_box[3] + bounds[1]]

                for field in ("text_bbox", "layout_bbox"):
                    if field in line:
                        reading[field] = translated(line[field])
                if "words" in line:
                    reading["words"] = [{**word, "bbox": translated(word["bbox"])} for word in line["words"]]
                # Text recovery must not silently treat a recognized formula
                # as ordinary prose or claim it has been validated.
                operators = sum(c in "=+−-×÷/^<>" for c in text)
                if operators >= 2 and operators / len(text) >= .15:
                    flag("OCR_REGION_COMPLEX_CONTENT")
                    continue
                overlaps = [old for old in result if _overlapping_line(old, reading)]
                if overlaps:
                    if not any(" ".join(old["text"].split()) == " ".join(text.split()) for old in overlaps):
                        entry["alternatives"].append(reading)
                        flag("OCR_REGION_DISAGREEMENT")
                    continue
                _insert_line(result, reading)
                entry["lines_added"] += 1
                report["lines_added"] += 1
            if entry["lines_added"]:
                entry["status"] = "recovered"
                flag("OCR_REGION_RECOVERED")
            elif entry["alternatives"]:
                entry["status"] = "disagreement"
            else:
                flag("OCR_REGION_UNRESOLVED")
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)[:300]
            flag("OCR_REGION_FAILED")
        entry["seconds"] = time.perf_counter() - begin
        entry["coverage_after"] = vertical_coverage(result, box)
    report["seconds"] = time.perf_counter() - started
    return result, report


def recover_marker(marker_path, image_path, work, *, lang="vie", profile="general", detector=None, options=None):
    """Recover a Tesseract line-marker; keep the original artifact unchanged."""
    from idp.ocr.fallback import lines_to_marker
    from idp.documents.normalize import html_text

    marker_path, work = Path(marker_path), Path(work)
    original = json.loads(marker_path.read_text("utf-8"))
    lines = []
    for block in original["children"][0]["children"]:
        line = {
            "bbox": block["bbox"],
            "text": html_text(block.get("html") or "")[0],
            "confidence": block.get("_idp_confidence", 0),
        }
        if block.get("_idp_text_bbox"):
            line["text_bbox"] = block["_idp_text_bbox"]
        lines.append(line)
    lines, report = recover_text_regions(image_path, lines, work, lang=lang, profile=profile, detector=detector, options=options)
    with Image.open(image_path) as image:
        output = lines_to_marker(lines, image.width, image.height, original.get("metadata", {}).get("page", 1), "tesseract_fallback")
    output["metadata"].update(original.get("metadata") or {})
    output["metadata"]["region_recovery"] = report
    output["metadata"]["baseline_marker_sha256"] = hashlib.sha256(marker_path.read_bytes()).hexdigest()
    target = marker_path.with_name(marker_path.stem + ".recovered.json")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    return target, report
