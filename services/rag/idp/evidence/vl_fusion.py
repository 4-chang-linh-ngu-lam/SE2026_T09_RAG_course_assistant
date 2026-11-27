"""Selective VLM token-logprob fusion, diacritic repair, and LaTeX validation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path

from PIL import Image

from idp.backends.vision_ocr import SOURCE, VL_PRIMARY_VERSION, _unwrap_latex
from idp.evidence.cross_read import LOW, line_confidence, repair_line, split_lines, word_probs
from idp.processing.figure import is_structural_section_header, section_level
from idp.processing.formula import normalize_latex, validate_latex
from idp.validation.calibration import build_confidence_meta

REPLACED_TYPES = {"Text", "Equation", "ListGroup", "SectionHeader"}
MAX_CROP_PIXELS = 1_500_000
PAD = 10
GROUP_LINES = 7


def _intersect(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(box) -> float:
    return max(1.0, (box[2] - box[0]) * (box[3] - box[1]))


def _vertical_iou(a, b) -> float:
    inter = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = max(1e-6, max(a[3], b[3]) - min(a[1], b[1]))
    return inter / union


def _region_tess(page: dict, box) -> str:
    return "\n".join(
        b.get("text") or ""
        for b in page.get("blocks") or []
        if b.get("block_type") in {"Text", "Equation", "SectionHeader", "ListGroup"}
        and b.get("bbox")
        and (
            _intersect(b["bbox"], box) / _area(b["bbox"]) > 0.5
            or _intersect(b["bbox"], box) / _area(box) > 0.5
        )
    )


def regions(page: dict) -> list[tuple[str, tuple, list]]:
    """Group Tesseract text lines (up to GROUP_LINES) plus structured formula regions."""
    size = page.get("page_size") or [0, 0]
    enrichment = page.get("structured_enrichment") or {}
    image_size = enrichment.get("image_size") or size
    sx = size[0] / image_size[0] if image_size and image_size[0] else 1.0
    sy = size[1] / image_size[1] if image_size and image_size[1] else 1.0
    structure = []
    for region in enrichment.get("regions") or []:
        box = region.get("pixel_bbox")
        if region.get("kind") in ("Equation", "Table") and box:
            structure.append((region["kind"], (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy), []))
    grouped = []
    for block in page.get("blocks") or []:
        if block.get("block_type") != "Text" or block.get("excluded_from_content") or not block.get("bbox"):
            continue
        box = tuple(block["bbox"])
        if any(_intersect(box, other) / _area(box) > 0.55 for _, other, _ in structure):
            continue
        if grouped:
            current, lines = grouped[-1]
            overlap = max(0, min(current[2], box[2]) - max(current[0], box[0]))
            if (
                len(lines) < GROUP_LINES
                and -15 <= box[1] - current[3] <= 65
                and abs(current[0] - box[0]) < 170
                and overlap >= 0.65 * min(current[2] - current[0], box[2] - box[0])
            ):
                grouped[-1] = (
                    (min(current[0], box[0]), min(current[1], box[1]), max(current[2], box[2]), max(current[3], box[3])),
                    lines + [box],
                )
                continue
        grouped.append((box, [box]))
    texts = [("Text", box, lines) for box, lines in grouped]
    formulas = [r for r in structure if r[0] == "Equation"]
    return sorted(texts + formulas, key=lambda r: (r[1][1], r[1][0]))


def fuse_vl_regions(
    page: dict,
    page_regions: list[tuple[str, tuple, list]],
    reads: list[tuple[list | dict | None, Exception | None]],
    *,
    replace_all_text: bool = False,
    reader_identity: dict | None = None,
) -> dict:
    """Fuse VLM region readings into ``page`` in place, keeping unescalated & failed blocks."""
    summary = {
        "version": VL_PRIMARY_VERSION,
        "reader": reader_identity,
        "regions": 0,
        "lines": 0,
        "low_confidence": 0,
        "repairs": 0,
        "failed": 0,
    }
    size = page.get("page_size") or [0, 0]
    if not size[0] or not size[1]:
        return summary
    tables = [b for b in page.get("blocks") or [] if b.get("block_type") == "Table"]
    new_blocks: list[dict] = []
    failed_regions: list[dict] = []
    succeeded_boxes: list[tuple] = []

    for index, ((kind, box, lines), (tokens, error)) in enumerate(zip(page_regions, reads)):
        summary["regions"] += 1
        if error is not None or not tokens:
            summary["failed"] += 1
            failed_regions.append({
                "bbox": list(box),
                "kind": kind,
                "reason": type(error).__name__ if error is not None else "empty_vlm_output",
            })
            continue
        tess_text = _region_tess(page, box)
        tess_words = {w for w, _ in word_probs([(tess_text, 1.0)])}
        out_lines = split_lines(tokens)
        boxes = lines if len(lines) == len(out_lines) else [box] * len(out_lines)
        region_blocks: list[dict] = []
        for j, (line_tokens, line_box) in enumerate(zip(out_lines, boxes)):
            conf_kind = "Text" if kind == "SectionHeader" else kind
            line_tokens, repairs = repair_line(line_tokens, tess_words)
            confidence = line_confidence(line_tokens, conf_kind, tess_text, tess_words)
            if confidence is None:
                continue
            text = "".join(t[0] for t in line_tokens).strip()
            block_id = f"p{page['page_id']:04d}_vl{index:03d}_{j:02d}"
            flags = [{
                "block_id": block_id,
                "code": "OCR_VL_PRIMARY",
                "severity": "info",
                "version": VL_PRIMARY_VERSION,
            }]
            if repairs:
                flags.append({
                    "block_id": block_id,
                    "code": "OCR_VL_MARKS_REPAIRED",
                    "severity": "info",
                    "repairs": repairs,
                })
                summary["repairs"] += len(repairs)
            if confidence < LOW:
                flags.append({"block_id": block_id, "code": "LOW_CONFIDENCE", "severity": "warning"})
                summary["low_confidence"] += 1
            bx0, by0, bx1, by1 = line_box
            latex_list: list[str] = []
            latex_vals: list[dict] = []
            block_type = (
                "Equation"
                if kind == "Equation"
                else ("SectionHeader" if kind == "SectionHeader" and is_structural_section_header(text) else "Text")
            )
            markdown = text
            if kind == "Equation":
                tex = normalize_latex(_unwrap_latex(text))
                if not tex:
                    continue
                val = validate_latex(tex).as_dict()
                latex_list = [tex]
                latex_vals = [val]
                text = tex
                markdown = f"$$\n{tex}\n$$"
                if not val["valid"]:
                    flags.append({"block_id": block_id, "code": "LATEX_INVALID", "severity": "warning"})
            elif block_type == "SectionHeader" and len(text) <= 240:
                markdown = f"{'#' * min(6, section_level(text))} {text}"
            conf_meta = build_confidence_meta(
                confidence,
                source=SOURCE,
                score_kind="vlm_min_token_prob",
            )
            block_entry = {
                "block_id": block_id,
                "block_type": block_type,
                "bbox": [max(0, bx0), max(0, by0), min(size[0], bx1), min(size[1], by1)],
                "text": text,
                "markdown": markdown,
                "latex": latex_list,
                "latex_validation": latex_vals,
                "source": SOURCE,
                "confidence": confidence,
                "confidence_meta": conf_meta,
                "review_flags": flags,
                "excluded_from_content": False,
                "asset_paths": [],
                "section_path": [],
                "page": page.get("page_id"),
            }
            region_blocks.append(block_entry)
        if region_blocks:
            new_blocks.extend(region_blocks)
            succeeded_boxes.append(box)
        else:
            summary["failed"] += 1
            failed_regions.append({"bbox": list(box), "kind": kind, "reason": "no_confirmed_tokens"})

    if not new_blocks:
        summary["failed_regions"] = failed_regions
        page["vl_primary"] = summary
        return summary

    failed_boxes = [r["bbox"] for r in failed_regions]
    keep = []
    for block in page.get("blocks") or []:
        box = block.get("bbox")
        in_table = box and any(_intersect(box, t["bbox"]) / _area(box) > 0.55 for t in tables)
        in_failed = box and any(_intersect(box, f) / _area(box) > 0.5 for f in failed_boxes)
        btype = block.get("block_type")
        if replace_all_text:
            if btype not in REPLACED_TYPES or in_table or in_failed:
                keep.append(block)
        else:
            covered_by_succeeded = bool(
                box
                and any(
                    _intersect(box, sb) / _area(box) > 0.55
                    or (_intersect(box, sb) / _area(sb) > 0.75 and _vertical_iou(box, sb) > 0.65)
                    for sb in succeeded_boxes
                )
            )
            if btype not in REPLACED_TYPES or in_table or in_failed or not covered_by_succeeded:
                keep.append(block)

    page["blocks"] = sorted(keep + new_blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    for order, block in enumerate(page["blocks"]):
        block["order"] = order
    enrichment = page.get("structured_enrichment")
    if enrichment:
        enrichment["regions"] = [r for r in enrichment.get("regions") or [] if r.get("kind") != "Equation"]
    page["review"] = [
        f for f in page.get("review") or []
        if f.get("block_id") is None and f.get("code") not in {"STRUCTURED_REGION_UNRESOLVED", "STRUCTURED_BUDGET_EXHAUSTED"}
    ]
    summary["lines"] = len(new_blocks)
    summary["failed_regions"] = failed_regions
    page["vl_primary"] = summary
    return summary


def vl_reread_page(
    page: dict,
    image_path: str | Path,
    reader,
    *,
    page_regions: list[tuple[str, tuple, list]] | None = None,
    replace_all_text: bool = True,
    gpu_queue=None,
) -> dict:
    """Read specified (or all) text/formula regions on a page with PaddleOCR-VL."""
    size = page.get("page_size") or [0, 0]
    if not size[0] or not size[1]:
        return {
            "version": VL_PRIMARY_VERSION,
            "reader": getattr(reader, "identity", None),
            "regions": 0, "lines": 0, "low_confidence": 0, "repairs": 0, "failed": 0,
        }
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    ix, iy = image.width / size[0], image.height / size[1]
    selected_regions = regions(page) if page_regions is None else page_regions
    crops: list[tuple[Image.Image, str]] = []
    for kind, box, _ in selected_regions:
        x0, y0, x1, y1 = box
        raw_w = max(1.0, (x1 - x0) * ix)
        raw_h = max(1.0, (y1 - y0) * iy)
        pad = max(PAD, min(18, int(round(0.15 * min(raw_w, raw_h))))) if min(raw_w, raw_h) < 40 else PAD
        crop = image.crop((
            max(0, x0 * ix - pad),
            max(0, y0 * iy - pad),
            min(image.width, x1 * ix + pad),
            min(image.height, y1 * iy + pad),
        ))
        min_dim = min(crop.width, crop.height)
        if 0 < min_dim < 36:
            up_scale = min(3.0, 48.0 / min_dim)
            if crop.width * crop.height * up_scale * up_scale > MAX_CROP_PIXELS:
                up_scale = math.sqrt(MAX_CROP_PIXELS / max(1, crop.width * crop.height))
            if up_scale > 1.01:
                crop = crop.resize(
                    (max(1, int(round(crop.width * up_scale))), max(1, int(round(crop.height * up_scale)))),
                    Image.Resampling.LANCZOS,
                )
        if crop.width * crop.height > MAX_CROP_PIXELS:
            scale = (MAX_CROP_PIXELS / (crop.width * crop.height)) ** 0.5
            crop = crop.resize(
                (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                Image.Resampling.LANCZOS,
            )
        reader_kind = "Text" if kind == "SectionHeader" else kind
        crops.append((crop, reader_kind))

    def read(item):
        try:
            return reader(*item), None
        except Exception as exc:
            return None, exc

    if gpu_queue is not None:
        reads = gpu_queue.map_calls(read, crops)
    else:
        workers = max(1, min(int(getattr(reader, "parallel", 1) or 1), len(crops)))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                reads = list(pool.map(read, crops))
        else:
            reads = [read(item) for item in crops]

    return fuse_vl_regions(
        page,
        selected_regions,
        reads,
        replace_all_text=replace_all_text,
        reader_identity=getattr(reader, "identity", None),
    )
