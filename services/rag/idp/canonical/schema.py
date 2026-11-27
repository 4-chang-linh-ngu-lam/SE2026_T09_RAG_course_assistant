"""Canonical v1 schema mapping, gap materialization, and cross-read attachment."""

from __future__ import annotations

import math

from idp.canonical.contract import (
    SUPPORTED_CANONICAL_SCHEMAS,
    build_block_provenance,
)
from idp.evidence import cross_read
from idp.processing.figure import visual_evidence
from idp.processing.reading_order import horizontal_overlap, insert_in_reading_order
from idp.processing.table import parse_table_html
from idp.validation.calibration import build_confidence_meta
from idp.validation.quality_gate import (
    CANONICAL_VERSION,
    RECOVERY_GAP_CODES,
    STRUCTURED_GAP_CODES,
)

_HOST_TYPES = {"Text", "SectionHeader", "ListGroup", "Caption"}


def block_payload(block: dict, page: dict | None = None, *, calibrator=None) -> dict:
    btype = block.get("block_type") or block.get("type")
    table = {}
    if btype == "Table" and not block.get("table_cells"):
        try:
            table = parse_table_html(block.get("table_html") or block.get("html") or block.get("markdown") or "")
        except ValueError:
            pass
    confidence_meta = block.get("confidence_meta")
    if not isinstance(confidence_meta, dict):
        confidence_meta = build_confidence_meta(
            block.get("confidence"),
            source=block.get("source"),
            calibrator=calibrator,
        )
    payload = {
        "block_id": block.get("block_id"),
        "order": block.get("order"),
        "type": btype,
        "bbox": block.get("bbox"),
        "excluded": bool(block.get("excluded_from_content") or block.get("excluded")),
        "text": block.get("text") or "",
        "markdown": block.get("markdown") or "",
        "latex": list(block.get("latex") or []),
        "latex_validation": list(block.get("latex_validation") or []),
        "table_html": (
            block.get("table_html")
            if page and page.get("hybrid_source")
            else (block.get("table_html") or (block.get("markdown") if btype == "Table" else None))
        ),
        "table_confidence": block.get("table_confidence"),
        "chart_data": block.get("chart_data"),
        "description": block.get("description"),
        "figure_description_provenance": block.get("figure_description_provenance"),
        "visual_facts": block.get("visual_facts"),
        "label_detection": block.get("label_detection"),
        "caption": block.get("caption"),
        "section_path": list(block.get("section_path") or []),
        "source": block.get("source"),
        "source_evidence": block.get("source_evidence"),
        "source_window": block.get("source_window"),
        "confidence": block.get("confidence"),
        "confidence_meta": confidence_meta,
        "layout_score": block.get("layout_score"),
        "block_crop_path": block.get("block_crop_path"),
        "asset_paths": list(block.get("asset_paths") or []),
        "figure_kind": block.get("figure_kind"),
        "review_flags": list(block.get("review_flags") or []),
        "recovery_region_id": block.get("recovery_region_id"),
        "table_cells": block.get("table_cells") or table.get("cells") or [],
        "table_shape": block.get("table_shape") or ([table["rows"], table["columns"]] if table else None),
        "table_header_rows": block.get("table_header_rows") or table.get("header_rows") or [],
        "formula_kind": block.get("formula_kind"),
        "visual_labels": block.get("visual_labels") or [],
        "structured_status": block.get("structured_status"),
        "structured_provenance": block.get("structured_provenance"),
        "text_recognition": block.get("text_recognition"),
        "question_group_ids": list(block.get("question_group_ids") or []),
        "question_reading": block.get("question_reading"),
        "visual_context": visual_evidence(page or {}, block),
    }
    payload["provenance"] = build_block_provenance(
        {**block, **payload, "confidence_meta": confidence_meta},
        page,
        calibrator=calibrator,
    )
    return payload


def _scaled_box(box, sx: float, sy: float, size) -> list[float] | None:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    w, h = float(size[0]), float(size[1])
    scaled = [max(0.0, x1 * sx), max(0.0, y1 * sy), min(w, x2 * sx), min(h, y2 * sy)]
    if not all(math.isfinite(v) for v in scaled) or not (scaled[0] < scaled[2] and scaled[1] < scaled[3]):
        return None
    return scaled


def _report_scale(report: dict, page: dict) -> tuple[float, float] | None:
    image_size = report.get("image_size")
    page_size = page.get("page_size")
    if not (
        isinstance(image_size, (list, tuple)) and len(image_size) == 2
        and isinstance(page_size, (list, tuple)) and len(page_size) == 2
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
            for v in (*image_size, *page_size)
        )
    ):
        return None
    return page_size[0] / image_size[0], page_size[1] / image_size[1]


def _own_flag(block: dict, code: str, **extra) -> None:
    flags = block.setdefault("review_flags", [])
    if not any(f.get("code") == code for f in flags):
        flags.append({"block_id": block.get("block_id"), "code": code, "severity": "warning", **extra})


def _structured_gaps(page: dict, blocks: list[dict]) -> list[dict]:
    report = page.get("structured_enrichment") or {}
    scale = _report_scale(report, page)
    if scale is None:
        return []
    by_id = {b.get("block_id"): b for b in blocks}
    taken = set(by_id)
    reason = {"reason": "region_not_transcribed"}
    gaps = []
    for index, region in enumerate(report.get("regions") or []):
        code = STRUCTURED_GAP_CODES.get(region.get("status"))
        if code is None and region.get("recognition_skipped") == "budget_limit":
            code = "STRUCTURED_BUDGET_EXHAUSTED"
        if code is None:
            continue
        block_id = region.get("block_id")
        if block_id is not None:
            if block_id in by_id:
                _own_flag(by_id[block_id], code, **reason)
            continue
        kind = region.get("kind")
        if kind not in {"Equation", "Table"}:
            continue
        box = _scaled_box(region.get("pixel_bbox"), *scale, page["page_size"])
        if box is None:
            continue
        gap_id = f"p{int(page.get('page_id') or 0):04d}_gap_s{index:03d}"
        if gap_id in taken:
            continue
        taken.add(gap_id)
        gap = {
            "block_id": gap_id,
            "type": kind,
            "bbox": box,
            "excluded": False,
            "text": "",
            "markdown": "",
            "latex": [],
            "latex_validation": [],
            "table_html": None,
            "source": "structured_region",
            "confidence": None,
            "section_path": [],
            "asset_paths": [],
            "structured_status": region.get("status"),
            "review_flags": [],
        }
        _own_flag(gap, code, **reason)
        _own_flag(gap, "TABLE_EMPTY" if kind == "Table" else "EMPTY_BLOCK", **reason)
        gaps.append(gap)
    return gaps


def _recovery_gaps(page: dict, blocks: list[dict]) -> list[dict]:
    report = page.get("region_recovery") or {}
    scale = _report_scale(report, page)
    if scale is None:
        return []
    sx, sy = scale
    page_size = page["page_size"]
    taken = {b.get("block_id") for b in blocks}
    gaps = []
    for region in report.get("regions") or []:
        region_id = str(region.get("region_id") or f"r{len(gaps):03d}")
        codes = []
        if region.get("status") in RECOVERY_GAP_CODES:
            codes.append(RECOVERY_GAP_CODES[region["status"]])
        if region.get("complex_skipped"):
            codes.append("OCR_REGION_COMPLEX_CONTENT")
        for alternative in region.get("alternatives") or []:
            alt_box = _scaled_box(alternative.get("bbox"), sx, sy, page_size)
            matched = [
                block for block in blocks
                if alt_box is not None
                and (b := block.get("bbox"))
                and len(b) == 4
                and horizontal_overlap(b, alt_box) >= 0.5
                and min(b[3], alt_box[3]) - max(b[1], alt_box[1]) >= 0.5 * min(b[3] - b[1], alt_box[3] - alt_box[1])
            ]
            if not matched:
                codes.append("OCR_REGION_DISAGREEMENT")
            for block in matched:
                _own_flag(block, "OCR_REGION_DISAGREEMENT", recovery_region_id=region_id, alternative=alternative.get("text"))
        if not codes:
            continue
        box = _scaled_box(region.get("bbox"), sx, sy, page_size)
        if box is None:
            continue
        block_id = f"p{int(page.get('page_id') or 0):04d}_gap_{region_id}"
        if block_id in taken:
            continue
        taken.add(block_id)
        reason = {"reason": "region_not_transcribed", "recovery_region_id": region_id}
        gaps.append({
            "block_id": block_id,
            "type": "Text",
            "bbox": box,
            "excluded": False,
            "text": "",
            "markdown": "",
            "latex": [],
            "latex_validation": [],
            "source": "ocr_region_recovery",
            "confidence": None,
            "section_path": [],
            "asset_paths": [],
            "recovery_region_id": region_id,
            "review_flags": [
                *({"block_id": block_id, "code": code, "severity": "warning", **reason} for code in dict.fromkeys(codes)),
                {"block_id": block_id, "code": "EMPTY_BLOCK", "severity": "warning", **reason},
            ],
        })
    return gaps


def _add_region_gaps(page: dict, blocks: list[dict]) -> int:
    gaps = _structured_gaps(page, blocks) + _recovery_gaps(page, blocks)
    for gap in gaps:
        insert_in_reading_order(blocks, gap)
    if gaps:
        for order, block in enumerate(blocks):
            block["order"] = order
    return len(gaps)


def _intersection_area(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _host_line(block: dict, blocks: list[dict]) -> dict | None:
    box = block.get("bbox")
    if not box or len(box) != 4:
        return None
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    best, best_share = None, 0.5
    for other in blocks:
        b = other.get("bbox")
        if (
            other is block
            or other.get("type") not in _HOST_TYPES
            or other.get("excluded")
            or not (other.get("text") or "").strip()
            or not b
            or len(b) != 4
        ):
            continue
        share = _intersection_area(box, b) / area
        if share >= best_share:
            best, best_share = other, share
    return best


def _add_cross_reads(page: dict, blocks: list[dict]) -> int:
    added = 0
    readings = {
        region.get("block_id"): region.get("reading")
        for region in (page.get("structured_enrichment") or {}).get("regions") or []
        if region.get("block_id") and isinstance(region.get("reading"), dict)
    }
    placed: dict[int, int] = {}
    for block in list(blocks):
        all_codes = {f.get("code") for f in block.get("review_flags") or []}
        if (block.get("text") or "").strip() or all_codes & cross_read.CROSS_READ_CODES:
            continue
        if block.get("type") == "Equation":
            latex = [x for x in block.get("latex") or [] if isinstance(x, str) and x.strip()]
            validation = block.get("latex_validation") or []
            if len(latex) != 1 or not validation or not all(v.get("valid") for v in validation):
                continue
            host = _host_line(block, blocks)
            result = cross_read.formula_agreement(latex[0], host["text"]) if host else None
            if result is None:
                continue
            block["text"] = latex[0]
            block.setdefault("review_flags", []).append({
                "block_id": block.get("block_id"),
                "severity": "info",
                "version": cross_read.CROSS_READ_VERSION,
                "host_block_id": host.get("block_id"),
                **result,
            })
            blocks.remove(block)
            anchor = blocks.index(host) + 1 + placed.get(id(host), 0)
            blocks.insert(anchor, block)
            placed[id(host)] = placed.get(id(host), 0) + 1
            if (
                result["code"] == cross_read.FORMULA_AGREED
                and result["ocr_coverage"] >= cross_read.SUPERSEDE_MIN_COVERAGE
            ):
                _own_flag(host, cross_read.LINE_SUPERSEDED, superseded_by=block.get("block_id"))
            added += 1
        elif block.get("type") == "Table":
            reading = readings.get(block.get("block_id")) or {}
            result = cross_read.table_agreement(reading.get("cells") or [])
            if result is None:
                continue
            block["text"] = result.pop("text")
            block.setdefault("review_flags", []).append({
                "block_id": block.get("block_id"),
                "severity": "info",
                "version": cross_read.CROSS_READ_VERSION,
                **result,
            })
            added += 1
    if added:
        for order, block in enumerate(blocks):
            block["order"] = order
    return added


def canonical_blocks(page: dict, *, calibrator_registry=None, profile: str | None = None) -> list[dict]:
    blocks = []
    for block in page.get("blocks") or []:
        calibrator = (
            calibrator_registry.get(source=block.get("source"), profile=profile)
            if calibrator_registry is not None
            else None
        )
        blocks.append(block_payload(block, page, calibrator=calibrator))
    _add_region_gaps(page, blocks)
    _add_cross_reads(page, blocks)
    return blocks


def cross_check_structured(document: dict) -> int:
    if document.get("schema_version") not in SUPPORTED_CANONICAL_SCHEMAS:
        raise ValueError("cross-reads apply to canonical v1/v2 documents")
    return sum(_add_cross_reads(page, page.setdefault("blocks", [])) for page in document.get("pages") or [])


def materialize_region_gaps(document: dict) -> int:
    if document.get("schema_version") not in SUPPORTED_CANONICAL_SCHEMAS:
        raise ValueError("region gaps apply to canonical v1/v2 documents")
    return sum(_add_region_gaps(page, page.setdefault("blocks", [])) for page in document.get("pages") or [])
