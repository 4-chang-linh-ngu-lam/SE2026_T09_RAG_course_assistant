"""Bounded region recovery for missed OCR regions and bad native PDF blocks."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from idp.backends.layout import detect_panels
from idp.backends.text_ocr import ocr_crop_with_orientation, parse_hocr_lines, run_tesseract
from idp.input.validation import (
    choose_ocr_language,
    encoding_issues,
    has_model_artifact_tokens,
    is_garbled_text,
    needs_ocr,
)
from idp.processing.formula import normalize_text

RECOVERY_VERSION = "idp-region-1"
TEXT_KINDS = {"text", "paragraph_title", "doc_title", "header", "footer", "panel", "Text", "SectionHeader"}


@dataclass(frozen=True)
class RecoveryOptions:
    coverage_min: float = 0.35
    confidence_min: float = 60.0
    max_regions: int = 12
    page_budget_seconds: float = 15.0
    region_timeout_seconds: float = 5.0
    max_crop_pixels: int = 2_000_000
    padding: int = 4

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(v)
            for v in (self.coverage_min, self.confidence_min, self.page_budget_seconds, self.region_timeout_seconds)
        ):
            raise ValueError("recovery settings must be finite")
        if not 0 <= self.coverage_min <= 1 or not 0 <= self.confidence_min <= 100:
            raise ValueError("invalid recovery thresholds")
        if self.max_regions < 1 or self.page_budget_seconds <= 0 or self.region_timeout_seconds <= 0:
            raise ValueError("recovery budgets must be positive")
        if self.max_crop_pixels < 1 or self.padding < 0:
            raise ValueError("invalid recovery crop limits")


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


def _inside(line: dict, box: list[float]) -> bool:
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


def _overlapping_line(a: dict, b: dict) -> bool:
    aa, bb = a.get("text_bbox", a["bbox"]), b.get("text_bbox", b["bbox"])
    ix = max(0, min(aa[2], bb[2]) - max(aa[0], bb[0]))
    iy = max(0, min(aa[3], bb[3]) - max(aa[1], bb[1]))
    return (
        ix / max(1, min(aa[2] - aa[0], bb[2] - bb[0])) >= 0.5
        and iy / max(1, min(aa[3] - aa[1], bb[3] - bb[1])) >= 0.5
    )


def _insert_line(lines: list[dict], line: dict) -> None:
    b = line["bbox"]
    for index, old in enumerate(lines):
        a = old["bbox"]
        overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        if a[1] > b[1] and overlap / max(1, min(a[2] - a[0], b[2] - b[0])) >= 0.5:
            lines.insert(index, line)
            return
    lines.append(line)


def recover_text_regions(
    image_path: str | Path,
    baseline: list[dict],
    work: str | Path,
    *,
    lang: str = "vie",
    profile: str = "general",
    detector: Callable | None = None,
    options: RecoveryOptions | None = None,
    read_crop: Callable | None = None,
    proposed_regions: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Recover missed text regions (e.g. colored textbook panels or missed columns)."""
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
        "regions": [],
        "flags": [],
        "lines_added": 0,
        "baseline_lines": len(baseline),
        "candidate_regions": 0,
        "image_size": [image.width, image.height],
    }

    def flag(code: str) -> None:
        if not any(f["code"] == code for f in report["flags"]):
            report["flags"].append({"code": code, "severity": "warning"})

    try:
        proposed = proposed_regions if proposed_regions is not None else (detector or detect_panels)(image_path)
        if not isinstance(proposed, (list, tuple)) or any(not isinstance(region, dict) for region in proposed):
            raise ValueError("layout detector must return a list of region objects")
    except Exception as exc:
        flag("OCR_REGION_DETECTION_FAILED")
        report["error"] = str(exc)[:300]
        report["seconds"] = time.perf_counter() - started
        return result, report

    candidates, seen = [], set()
    reliable = [
        line for line in baseline
        if (
            isinstance(line.get("confidence"), (int, float))
            and options.confidence_min <= line["confidence"] <= 100
            and len(line.get("text", "")) >= 8
            and sum(c.isalpha() for c in line["text"]) / len(line["text"]) >= 0.35
        )
    ]
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
        x1, y1, x2, y2 = box
        pad = options.padding
        bounds = [
            max(0, int(x1) - pad),
            max(0, int(y1) - pad),
            min(image.width, math.ceil(x2) + pad),
            min(image.height, math.ceil(y2) + pad),
        ]
        entry = {
            "region_id": f"r{index:03d}",
            "bbox": box,
            "crop_bbox": bounds,
            "kind": kind,
            "baseline_coverage": coverage,
            "status": "unresolved",
            "lines_added": 0,
            "alternatives": [],
        }
        report["regions"].append(entry)
        if index >= options.max_regions or remaining <= 0:
            entry["status"] = "budget_limit"
            flag("OCR_REGION_BUDGET_EXHAUSTED")
            continue
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
            timeout = min(options.region_timeout_seconds, max(0.001, options.page_budget_seconds - (begin - started)))
            local = (
                read_crop(crop, timeout)
                if read_crop
                else parse_hocr_lines(run_tesseract(crop, crop.with_suffix(""), lang, 6, timeout=timeout), profile)
            )
            for line in local:
                b = _bbox(line.get("bbox"), (bounds[2] - bounds[0], bounds[3] - bounds[1]))
                text = (line.get("text") or "").strip()
                confidence = line.get("confidence", 0)
                if (
                    b is None
                    or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence)
                    or not options.confidence_min <= confidence <= 100
                    or len(text) < 8
                    or sum(c.isalpha() for c in text) / max(1, len(text)) < 0.35
                    or is_garbled_text(text)
                    or has_model_artifact_tokens(text)
                ):
                    continue
                reading = {
                    **line,
                    "text": text,
                    "bbox": [b[0] + bounds[0], b[1] + bounds[1], b[2] + bounds[0], b[3] + bounds[1]],
                    "recovery_region_id": entry["region_id"],
                }

                def translated(local_box):
                    return [
                        local_box[0] + bounds[0],
                        local_box[1] + bounds[1],
                        local_box[2] + bounds[0],
                        local_box[3] + bounds[1],
                    ]

                for field in ("text_bbox", "layout_bbox"):
                    if field in line:
                        reading[field] = translated(line[field])
                if "words" in line:
                    reading["words"] = [{**word, "bbox": translated(word["bbox"])} for word in line["words"]]

                operators = sum(c in "=+−-×÷/^<>" for c in text)
                if operators >= 2 and operators / len(text) >= 0.15:
                    entry["complex_skipped"] = entry.get("complex_skipped", 0) + 1
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


def recover_bad_native_blocks(
    page: dict,
    image_path: str | Path,
    *,
    profile: str,
    language: str | None,
    work: Path,
    bad_blocks: list[dict] | None = None,
) -> int:
    """OCR only empty/garbled/encoding-corrupt native blocks, keeping healthy native text."""
    if bad_blocks is None:
        bad_blocks = [
            block for block in page["blocks"]
            if block.get("block_type") in {"Text", "ListGroup", "SectionHeader"}
            and block.get("bbox")
            and (
                not (block.get("text") or "").strip()
                or is_garbled_text(block.get("text") or "")
                or bool(encoding_issues(block.get("text") or ""))
            )
        ]
    if not bad_blocks:
        return 0
    chosen, _ = choose_ocr_language(language)
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        pw, ph = page.get("page_size") or (width, height)
        sx, sy = width / max(1.0, float(pw)), height / max(1.0, float(ph))
        work.mkdir(parents=True, exist_ok=True)
        recovered_count = 0
        for block in bad_blocks:
            bx0, by0, bx1, by1 = [float(v) for v in block["bbox"]]
            pad = 6
            x1 = max(0, int(round(bx0 * sx)) - pad)
            y1 = max(0, int(round(by0 * sy)) - pad)
            x2 = min(width, int(round(bx1 * sx)) + pad)
            y2 = min(height, int(round(by1 * sy)) + pad)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image.crop((x1, y1, x2, y2))
            try:
                recovered, confidence, angle = ocr_crop_with_orientation(
                    crop, work, block["block_id"], lang=chosen, psm=6, profile=profile,
                )
            except Exception as exc:
                block.setdefault("review_flags", []).append({
                    "code": "TEXT_OCR_RECOVERY_FAILED",
                    "severity": "warning",
                    "reason": str(exc)[:200],
                })
                continue
            recovered, _ = normalize_text(recovered, profile)
            recovered = recovered.strip()
            if recovered and not needs_ocr(recovered)[0]:
                block["text"] = recovered
                block["markdown"] = recovered
                block["source"] = "tesseract"
                block["confidence"] = confidence
                block["ocr_rotation"] = angle
                block["review_flags"] = [
                    f for f in block.get("review_flags") or []
                    if f.get("code") != "TEXT_ENCODING_REVIEW"
                ]
                block["review_flags"].append({
                    "code": "TEXT_OCR_RECOVERED",
                    "severity": "info",
                    "confidence": confidence,
                    "rotation": angle,
                })
                if confidence < 0.60:
                    block["review_flags"].append({
                        "code": "TEXT_OCR_RECOVERY_LOW_CONFIDENCE",
                        "severity": "warning",
                        "confidence": confidence,
                        "rotation": angle,
                    })
                recovered_count += 1
            elif recovered:
                block.setdefault("review_flags", []).append({
                    "code": "TEXT_OCR_RECOVERY_LOW_QUALITY",
                    "severity": "warning",
                    "text": recovered[:200],
                    "confidence": confidence,
                    "rotation": angle,
                })
            else:
                block.setdefault("review_flags", []).append({
                    "code": "EMPTY_BLOCK",
                    "severity": "warning",
                })

    existing = {(item.get("block_id"), item.get("code")) for item in page.get("review") or []}
    for block in page["blocks"]:
        for flag in block.get("review_flags") or []:
            if flag.get("severity") in {"warning", "error"}:
                key = (block["block_id"], flag.get("code"))
                if key not in existing:
                    existing.add(key)
                    page.setdefault("review", []).append({
                        "page": page["page_id"],
                        "block_id": block["block_id"],
                        "block_type": block["block_type"],
                        "bbox": block["bbox"],
                        **flag,
                    })
    return recovered_count
