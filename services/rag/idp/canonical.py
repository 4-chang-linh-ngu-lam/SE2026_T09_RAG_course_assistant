"""Canonical parsed-document contract for the ingestion stage.

Ingestion stops here: pages, typed blocks, text/LaTeX/table payloads, bbox,
provenance and review flags. Chunking, embeddings, BM25 and retrieval are
downstream consumers and are not part of this module.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import math
import re

from idp.input.profiles import resolve_profile
from idp.structured.structure import visual_evidence, parse_table_html
from idp.structured.questions import analyze_questions
from idp.structured import cross_read

CANONICAL_VERSION = "idp-canonical-1"
LOW_CONFIDENCE = 0.60
MATH_REVIEW_CODES = {
    "FORMULA_SEMANTIC_REVIEW", "FORMULA_FRAGMENT", "FORMULA_PLACEHOLDER",
    "FORMULA_ALIGNMENT_REVIEW", "FORMULA_INCOMPLETE", "FORMULA_SIGN_REVIEW",
    "FORMULA_SIGN_CORRECTED", "LATEX_INVALID", "MATH_TEXT_INTEGRITY",
    "MISSING_NUMERIC_CONTEXT",
}
FIGURE_REVIEW_CODES = {
    "FIGURE_NO_CAPTION", "FIGURE_NO_IMAGE", "FIGURE_REFERENCE_REVIEW",
    "TABLE_EMPTY", "TABLE_STRUCTURE_REVIEW", "TABLE_MULTI_REVIEW",
    "TABLE_DETECTION_REVIEW",
}
LAYOUT_REVIEW_CODES = {"LOW_LAYOUT_CONFIDENCE"}
# Image-risk flags are review signals, not proof that OCR text is wrong. They
# block auto-publish but must not fail review-assisted ingestion by themselves.
PAGE_TEXT_RISK_CODES = {
    "WATERMARK_CANDIDATE_REVIEW", "PAGE_FAINT_CONTENT_REVIEW",
    "QUESTION_GROUP_REVIEW", "QUESTION_ORPHAN_OPTIONS",
    "PAGE_TEXT_LAYER_UNUSABLE",
    "PAGE_BLURRY", "PAGE_LOW_CONTRAST", "PAGE_NEEDS_DESKEW",
    "PAGE_LAYOUT_FAILED", "FAST_MODE_REVIEW", "FAST_OCR_REVIEW", "FALLBACK_ENGINE_REVIEW",
    "PAGE_ORIENTATION_REVIEW", "PAGE_ORIENTATION_UNRESOLVED",
    "REGION_WINDOWS_REVIEW", "REGION_WINDOWS_PARTIAL",
    "VERIFIER_FAILED",
}

# --- Retrieval publication policy -------------------------------------------
# "page": legacy gate. Any warning anywhere holds the whole page.
# "block" (default): a finding holds only the block it is about. A page is
# held only by a page-level code that is not listed as advisory below, so an
# unknown page code still fails closed.
PUBLISH_POLICIES = {"page", "block"}
DEFAULT_PUBLISH_POLICY = "block"
# Page-level codes that describe provenance, a heuristic or image statistics,
# not text that is known to be wrong. Per-block evidence decides instead.
PAGE_ADVISORY_CODES = {
    "FAST_OCR_REVIEW", "FAST_MODE_REVIEW", "FALLBACK_ENGINE_REVIEW",
    "OCR_FALLBACK_USED", "OCR_LOW_CONFIDENCE",
    "PAGE_BLURRY", "PAGE_LOW_CONTRAST", "PAGE_NEEDS_DESKEW",
    "QUESTION_ORPHAN_OPTIONS", "QUESTION_GROUP_REVIEW",
    "STRUCTURED_EXTRACTION_REVIEW", "STRUCTURED_BUDGET_EXHAUSTED",
    "STRUCTURED_REGION_UNRESOLVED", "STRUCTURED_PIXEL_LIMIT",
    "OCR_REGION_RECOVERED", "OCR_REGION_UNRESOLVED", "OCR_REGION_DISAGREEMENT",
    "OCR_REGION_BUDGET_EXHAUSTED", "OCR_REGION_COMPLEX_CONTENT",
    "TABLE_OCR_REVIEW",
    # Candidate tokens only; the blocks that are exactly such a token are held.
    "WATERMARK_CANDIDATE_REVIEW",
}
# Page codes that report source content left untranscribed (budget, pixel
# limit, unresolved, disagreeing or complex regions). They are advisory only
# while a block on the page owns the same code: the producer's held
# placeholder (or the disagreeing block) marks where the gap is. Without an
# owner the gap has no position, so the page stays held (fail closed).
REGION_LOSS_CODES = {
    "STRUCTURED_BUDGET_EXHAUSTED", "STRUCTURED_PIXEL_LIMIT",
    "STRUCTURED_REGION_UNRESOLVED",
    "OCR_REGION_UNRESOLVED", "OCR_REGION_BUDGET_EXHAUSTED",
    "OCR_REGION_DISAGREEMENT", "OCR_REGION_COMPLEX_CONTENT",
}
# Region-recovery status -> the code its held placeholder carries.
RECOVERY_GAP_CODES = {
    "budget_limit": "OCR_REGION_BUDGET_EXHAUSTED",
    "pixel_limit": "OCR_REGION_UNRESOLVED",
    "unresolved": "OCR_REGION_UNRESOLVED",
    "failed": "OCR_REGION_FAILED",
    "disagreement": "OCR_REGION_DISAGREEMENT",
}
# Structured-enrichment status -> the code that marks that region's gap.
STRUCTURED_GAP_CODES = {
    "budget_limit": "STRUCTURED_BUDGET_EXHAUSTED",
    "pixel_limit": "STRUCTURED_PIXEL_LIMIT",
    "unresolved": "STRUCTURED_REGION_UNRESOLVED",
}
# Block-level codes that do not make the block's own text doubtful.
BLOCK_ADVISORY_CODES = {
    "FAST_OCR_REVIEW", "FAST_MODE_REVIEW", "FALLBACK_ENGINE_REVIEW",
    "QUESTION_GROUP_REVIEW",  # grouping guess; the chunker keeps groups atomic
    "FIGURE_NO_CAPTION", "FIGURE_REFERENCE_REVIEW", "FIGURE_NO_IMAGE",
    "LOW_LAYOUT_CONFIDENCE",
}
# Dual-read disagreement or failure is NOT advisory: the two readers did not
# agree, so the block is held even when the primary score clears the threshold.
# (Kept out of BLOCK_ADVISORY_CODES so _block_hold_reasons() reports them.)
# Not indexed as text, so they neither gate a page nor need authorization.
NON_TEXT_TYPES = {
    "Picture", "PictureGroup", "Diagram", "Chart",
    "PageHeader", "PageFooter", "PageNumber",
}
# Evidence that a block's text was checked independently of its own score.
# FORMULA_TEXT_LAYER_RECONSTRUCTED is not here: the rebuild is lossless with
# respect to the block's own text layer, so it is exactly as trustworthy as
# that source and must not stand in for an untrusted parser.
# A formula model agreeing with the page OCR is two engines on one region.
VERIFIED_CODES = {"OCR_DUAL_READ_AGREED", "HUMAN_CORRECTED", cross_read.FORMULA_AGREED}
# Cross-read evidence that is partial or from one engine read twice: as
# strong as an OCR score of at least LOW_CONFIDENCE, no stronger.
CROSS_READ_SCORED_CODES = {
    cross_read.FORMULA_CONSISTENT, cross_read.TABLE_AGREED, cross_read.TABLE_PARTIAL,
}
# Structured-extraction review findings a cross-read answers.
CROSS_READ_RESOLVES = {"STRUCTURED_EXTRACTION_REVIEW", "TABLE_OCR_REVIEW", "TABLE_HEADER_UNKNOWN"}
# Held because a verified formula replaces its garbled line; not a gap.
SUPERSEDED_CODES = {cross_read.LINE_SUPERSEDED}
VERIFICATION_TIERS = ("none", "scored", "verified", "trusted")
# Findings that only restate the recognizer's own score.
SCORE_ONLY_CODES = {"LOW_CONFIDENCE"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _block_payload(block: dict, page: dict | None = None) -> dict:
    btype = block.get("block_type")
    table = {}
    if btype == "Table" and not block.get("table_cells"):
        try:
            table = parse_table_html(block.get("table_html") or block.get("html") or block.get("markdown") or "")
        except ValueError:
            pass
    return {
        "block_id": block.get("block_id"),
        "order": block.get("order"),
        "type": btype,
        "bbox": block.get("bbox"),
        "excluded": bool(block.get("excluded_from_content")),
        "text": block.get("text") or "",
        "markdown": block.get("markdown") or "",
        "latex": list(block.get("latex") or []),
        "latex_validation": list(block.get("latex_validation") or []),
        "table_html": (
            block.get("table_html") if page and page.get('hybrid_source') else
            (block.get("table_html") or (block.get("markdown") if btype == "Table" else None))
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


def _horizontal_overlap(a, b) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1e-9, min(a[2] - a[0], b[2] - b[0]))


def insert_in_reading_order(blocks: list[dict], block: dict) -> int:
    """Insert ``block`` before the first block below it in the same column.

    Retrieval walks blocks in list order, so a held placeholder appended at
    the end would mark no gap. Existing blocks are never reordered.
    """
    box = block["bbox"]
    for index, other in enumerate(blocks):
        a = other.get("bbox")
        if not a or len(a) != 4:
            continue
        if a[1] > box[1] and _horizontal_overlap(a, box) >= .5:
            blocks.insert(index, block)
            return index
    blocks.append(block)
    return len(blocks) - 1


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
    """Image-pixel -> page-unit scale, or None when it cannot be trusted."""
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
        flags.append({
            "block_id": block.get("block_id"), "code": code, "severity": "warning", **extra,
        })


def _structured_gaps(page: dict, blocks: list[dict]) -> list[dict]:
    """Owners for structured regions that were detected but not transcribed.

    Current enrichment flags (or creates) the block itself; artifacts written
    before that only recorded the region in the page report. The region's
    block is flagged, or a held placeholder is placed at the region, so the
    page-level code has an owner and the gap a position.
    """
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
            continue  # a missing block leaves the code unowned: page held
        kind = region.get("kind")
        if kind not in {"Equation", "Table"}:
            continue
        box = _scaled_box(region.get("pixel_bbox"), *scale, page["page_size"])
        if box is None:
            continue
        gap_id = f"p{int(page.get('page_id') or 0):04d}_gap_s{index:03d}"
        if gap_id in taken:
            continue  # already materialized
        taken.add(gap_id)
        gap = {
            "block_id": gap_id, "type": kind, "bbox": box, "excluded": False,
            "text": "", "markdown": "", "latex": [], "latex_validation": [],
            "table_html": None, "source": "structured_region", "confidence": None,
            "section_path": [], "asset_paths": [], "structured_status": region.get("status"),
            "review_flags": [],
        }
        _own_flag(gap, code, **reason)
        _own_flag(gap, "TABLE_EMPTY" if kind == "Table" else "EMPTY_BLOCK", **reason)
        gaps.append(gap)
    return gaps


def _recovery_gaps(page: dict, blocks: list[dict]) -> list[dict]:
    """Held placeholders for OCR region-recovery regions left untranscribed.

    Recovery works on OCR lines, and an empty line never reaches the page
    blocks, so the gap is materialized here from the page's recovery report.
    Blocks that a recovered reading disagreed with are flagged too. Without the
    report's ``image_size`` nothing is added and the audit holds the page.
    """
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
                if alt_box is not None and (b := block.get("bbox")) and len(b) == 4
                and _horizontal_overlap(b, alt_box) >= .5
                and min(b[3], alt_box[3]) - max(b[1], alt_box[1])
                >= .5 * min(b[3] - b[1], alt_box[3] - alt_box[1])
            ]
            if not matched:
                # The disagreeing line has no block to hold; mark the region.
                codes.append("OCR_REGION_DISAGREEMENT")
            for block in matched:
                _own_flag(block, "OCR_REGION_DISAGREEMENT", recovery_region_id=region_id,
                          alternative=alternative.get("text"))
        if not codes:
            continue
        box = _scaled_box(region.get("bbox"), sx, sy, page_size)
        if box is None:
            continue
        block_id = f"p{int(page.get('page_id') or 0):04d}_gap_{region_id}"
        if block_id in taken:
            continue  # already materialized
        taken.add(block_id)
        reason = {"reason": "region_not_transcribed", "recovery_region_id": region_id}
        gaps.append({
            "block_id": block_id, "type": "Text", "bbox": box, "excluded": False,
            "text": "", "markdown": "", "latex": [], "latex_validation": [],
            "source": "ocr_region_recovery", "confidence": None,
            "section_path": [], "asset_paths": [], "recovery_region_id": region_id,
            "review_flags": [
                *({"block_id": block_id, "code": code, "severity": "warning", **reason}
                  for code in dict.fromkeys(codes)),
                {"block_id": block_id, "code": "EMPTY_BLOCK", "severity": "warning", **reason},
            ],
        })
    return gaps


def _add_region_gaps(page: dict, blocks: list[dict]) -> int:
    """Flag/insert gap owners into canonical ``blocks`` (in place)."""
    gaps = _structured_gaps(page, blocks) + _recovery_gaps(page, blocks)
    for gap in gaps:
        insert_in_reading_order(blocks, gap)
    if gaps:
        for order, block in enumerate(blocks):
            block["order"] = order
    return len(gaps)


def _intersection_area(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


_HOST_TYPES = {"Text", "SectionHeader", "ListGroup", "Caption"}


def _host_line(block: dict, blocks: list[dict]) -> dict | None:
    """The OCR text block most of this region lies on (>= half its area)."""
    box = block.get("bbox")
    if not box or len(box) != 4:
        return None
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    best, best_share = None, 0.5
    for other in blocks:
        b = other.get("bbox")
        if (
            other is block or other.get("type") not in _HOST_TYPES or other.get("excluded")
            or not (other.get("text") or "").strip() or not b or len(b) != 4
        ):
            continue
        share = _intersection_area(box, b) / area
        if share >= best_share:
            best, best_share = other, share
    return best


def _add_cross_reads(page: dict, blocks: list[dict]) -> int:
    """Give structured blocks retrievable text where a cross-read supports it.

    Formula text is its LaTeX; table text is its rows with disagreeing cells
    as "?". Each changed block records the check as a flag; a verified
    formula is moved right after the line it sits on, and a line that is
    mostly that formula is held as superseded (it is the garbled reading).
    """
    added = 0
    readings = {
        region.get("block_id"): region.get("reading")
        for region in (page.get("structured_enrichment") or {}).get("regions") or []
        if region.get("block_id") and isinstance(region.get("reading"), dict)
    }
    placed: dict[int, int] = {}
    for block in list(blocks):
        if (block.get("text") or "").strip() or _all_flag_codes(block) & cross_read.CROSS_READ_CODES:
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
                "block_id": block.get("block_id"), "severity": "info",
                "version": cross_read.CROSS_READ_VERSION, "host_block_id": host.get("block_id"),
                **result,
            })
            # Reading order: right after its line (after earlier formulas on it).
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
                "block_id": block.get("block_id"), "severity": "info",
                "version": cross_read.CROSS_READ_VERSION, **result,
            })
            added += 1
    if added:
        for order, block in enumerate(blocks):
            block["order"] = order
    return added


def _canonical_blocks(page: dict) -> list[dict]:
    blocks = [_block_payload(block, page) for block in page.get("blocks") or []]
    _add_region_gaps(page, blocks)
    _add_cross_reads(page, blocks)
    return blocks


def cross_check_structured(document: dict) -> int:
    """Upgrade a canonical v1 document with formula/table cross-reads.

    Idempotent; returns the number of structured blocks given text.
    """
    if document.get("schema_version") != CANONICAL_VERSION:
        raise ValueError("cross-reads apply to canonical v1 documents")
    return sum(_add_cross_reads(page, page.setdefault("blocks", [])) for page in document.get("pages") or [])


def materialize_region_gaps(document: dict) -> int:
    """Upgrade a canonical v1 document built before region-gap placeholders.

    Uses the structured/recovery reports kept on each canonical page. It is
    idempotent and returns the number of placeholders added. Without it, an
    older document's region-loss codes have no owner and hold their pages.
    """
    if document.get("schema_version") != CANONICAL_VERSION:
        raise ValueError("region gaps apply to canonical v1 documents")
    return sum(_add_region_gaps(page, page.setdefault("blocks", [])) for page in document.get("pages") or [])


def build_canonical(
    pages: list[dict],
    source_path: str | Path,
    source_sha256: str,
    pipeline_version: str,
    parser: dict | None = None,
    page_manifest: list[dict] | None = None,
    failed_pages: list[dict] | None = None,
    expected_pages: list[int] | None = None,
    profile: str | None = None,
    source_acl: dict | None = None,
    source_metadata: dict | None = None,
) -> dict:
    questions = analyze_questions(pages)
    canonical_pages = []
    for page in pages:
        canonical_pages.append({
            "page_id": page.get("page_id"),
            "page_number": page.get("page_number"),
            "page_size": page.get("page_size"),
            "status": page.get("processing_status"),
            "classification": page.get("classification"),
            "profile": page.get("profile"),
            "parser": page.get("parser"),
            "ocr_language": page.get("ocr_language"),
            "source_image_sha256": page.get("source_image_sha256"),
            "render_provenance": page.get("render_provenance"),
            "preprocessing": page.get("preprocessing"),
            "region_recovery": page.get("region_recovery"),
            "structured_enrichment": page.get("structured_enrichment"),
            "math_context": page.get("math_context"),
            "question_context": page.get("question_context"),
            "region_windows": page.get("region_windows"),
            "hybrid_source": page.get("hybrid_source"),
            "text_recognition": page.get("text_recognition"),
            "question_groups": page.get("question_groups") or [],
            "watermark_candidates": page.get("watermark_candidates") or [],
            "text_layer_audit": page.get("text_layer_audit"),
            "quality_source": page.get("quality_source"),
            # Block warnings are read from current blocks, so human corrections
            # do not retain an obsolete duplicate from the page summary.
            "review": [f for f in page.get("review") or [] if f.get("block_id") is None],
            "blocks": _canonical_blocks(page),
        })
    sources = Counter(
        block.get("source") or "unknown"
        for page in pages for block in page.get("blocks") or []
    )
    confidence_values = [
        block.get("confidence")
        for page in pages for block in page.get("blocks") or []
        if block.get("confidence") is not None
    ]
    layout_values = [
        block.get("layout_score")
        for page in pages for block in page.get("blocks") or []
        if block.get("layout_score") is not None
    ]
    parser_info = dict(parser or {})
    parser_info.setdefault("sources", dict(sources))
    parser_info.setdefault("confidence_available", bool(confidence_values))
    parser_info.setdefault("layout_confidence_available", bool(layout_values))
    return {
        "schema_version": CANONICAL_VERSION,
        "created_at": _utc_now(),
        "doc_id": source_sha256,
        "source": str(source_path),
        "source_sha256": source_sha256,
        "pipeline_version": pipeline_version,
        "profile": profile or "general",
        "source_acl": source_acl or {
            "owner": None, "users": [], "groups": [], "is_public": False,
        },
        "source_metadata": dict(source_metadata or {}),
        "parser": parser_info,
        "expected_pages": list(expected_pages or []),
        "page_manifest": list(page_manifest or []),
        "failed_pages": list(failed_pages or []),
        "question_grouping_version": questions["version"],
        "question_groups": questions["groups"],
        "pages": canonical_pages,
    }


def _block_has_payload(block: dict) -> bool:
    return bool(
        (block.get("text") or "").strip()
        or block.get("latex")
        or block.get("table_html")
        or block.get("type") in {"Diagram", "Picture", "PictureGroup", "Chart"}
    )


def _flag_codes(block: dict) -> set[str]:
    return {
        flag.get("code") for flag in block.get("review_flags") or []
        if flag.get("severity") in {"warning", "error"}
    }


def _all_flag_codes(block: dict) -> set[str]:
    return {
        flag.get("code") for flag in block.get("review_flags") or []
    }


def _score_ok(confidence) -> bool:
    return (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(confidence)
        and LOW_CONFIDENCE <= confidence <= 1
    )


def block_verification(block: dict, trusted: set[str]) -> str:
    """Why a block's text may be published: trusted / verified / scored / none.

    ``trusted``: explicitly trusted parser (e.g. a clean native text layer).
    ``verified``: checked independently (dual-read agreement, lossless glyph
    rebuild, human correction). ``scored``: the recognizer's own score is at
    least LOW_CONFIDENCE. ``none``: no evidence; the block is held.
    """
    if not block.get("source"):
        return "none"
    if block.get("source") in trusted:
        return "trusted"
    codes = _all_flag_codes(block)
    if codes & VERIFIED_CODES:
        return "verified"
    if codes & CROSS_READ_SCORED_CODES or _score_ok(block.get("confidence")):
        return "scored"
    return "none"


def _indexable_text(block: dict) -> bool:
    """A block retrieval would index as text (mirrors the harness filter)."""
    text = block.get("text")
    return (
        not block.get("excluded")
        and block.get("retrieval_eligible") is not False
        and block.get("type") not in NON_TEXT_TYPES
        and isinstance(text, str) and bool(text.strip())
    )


def _block_hold_reasons(block: dict, trusted: set[str], watermark_tokens: set[str]) -> list[str]:
    """Reasons to keep one indexable block out of retrieval (block policy)."""
    codes = _flag_codes(block) - BLOCK_ADVISORY_CODES
    if _all_flag_codes(block) & cross_read.CROSS_READ_CODES:
        codes -= CROSS_READ_RESOLVES
    verification = block_verification(block, trusted)
    if verification in {"trusted", "verified"}:
        # A low single-reader score is superseded by independent evidence.
        codes -= SCORE_ONLY_CODES
    reasons = sorted(codes)
    if verification == "none":
        reasons.append("UNVERIFIED_SOURCE")
    if watermark_tokens and (block.get("text") or "").strip() in watermark_tokens:
        reasons.append("WATERMARK_CANDIDATE_TOKEN")
    return reasons


def _page_publish_authorized(page: dict, trusted: set[str]) -> bool:
    """Trust each contributing source, rather than a mixed-document summary."""
    blocks = [b for b in page.get("blocks") or [] if not b.get("excluded")]
    if not blocks:
        return page.get("status") == "blank"
    for block in blocks:
        source = block.get("source")
        if not source:
            return False
        if source in trusted:
            continue
        # Capability metadata alone is not a recognition measurement. Require
        # the contributing block's actual score, or explicit source trust.
        confidence = block.get("confidence")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(confidence)
            and LOW_CONFIDENCE <= confidence <= 1
        ):
            continue
        return False
    return True


def resolve_publish_policy(policy: str | None, block_scoped_codes=()) -> str:
    if policy is None:
        return "page" if block_scoped_codes else DEFAULT_PUBLISH_POLICY
    if policy not in PUBLISH_POLICIES:
        raise ValueError(f"unknown publish policy: {policy}")
    if policy == "block" and block_scoped_codes:
        raise ValueError("block_scoped_codes only apply to policy='page'")
    return policy


def audit_canonical(
    document: dict,
    trusted_parsers: set[str] | None = None,
    profile: str | None = None,
    *,
    asset_path_mapping: tuple[str, str | Path] | None = None,
    block_scoped_codes: frozenset[str] | set[str] = frozenset(),
    policy: str | None = None,
) -> dict:
    """Audit a document, optionally resolving its former export root locally.

    ``policy="block"`` (default) decides retrieval per block: a page is held
    only by a non-advisory page-level code; each indexable block is held by
    its own non-advisory warnings or missing verification, and is listed in
    ``page_quality[i]["held_blocks"]`` (with ``hold_reasons``).
    ``policy="page"`` is the legacy gate, where ``block_scoped_codes`` (empty
    by default) are the only block findings that do not hold the page.
    Certification (``production_pass``/``quality_certified``) always uses the
    strict page gate.

    ``policy=None`` resolves to ``"page"`` when ``block_scoped_codes`` are
    given (they only mean something there) and to the default otherwise.
    Passing both ``policy="block"`` and ``block_scoped_codes`` is rejected
    rather than silently ignoring the codes.
    """
    trusted_parsers = set(trusted_parsers or ())
    block_scoped_codes = frozenset(block_scoped_codes)
    policy = resolve_publish_policy(policy, block_scoped_codes)
    if asset_path_mapping is not None:
        original_root = PurePosixPath(asset_path_mapping[0].replace("\\", "/"))
        local_root = Path(asset_path_mapping[1]).resolve()
        if not original_root.is_absolute() or not local_root.is_dir():
            raise ValueError("asset mapping requires an absolute export prefix and a local directory")

    def asset_exists(value: str) -> bool:
        if asset_path_mapping is None:
            return Path(value).exists()
        try:
            relative = PurePosixPath(value.replace("\\", "/")).relative_to(original_root)
        except ValueError:
            return Path(value).exists()
        path = (local_root / Path(*relative.parts)).resolve()
        return path.is_relative_to(local_root) and path.is_file()

    resolved_profile = resolve_profile(profile or document.get("profile") or "general")
    pages = document.get("pages") or []
    expected = set(int(x) for x in document.get("expected_pages") or [])
    actual = {int(page.get("page_id")) for page in pages}
    missing_pages = sorted(expected - actual)
    failed_pages = document.get("failed_pages") or []
    layout_failed = [
        page["page_id"] for page in pages
        if page.get("status") == "layout_failed"
    ]
    duplicate_blocks = []
    seen_blocks = set()
    invalid_blocks = []
    missing_assets = []
    formula_issues = []
    table_issues = []
    empty_unflagged = []
    source_missing = []
    confidence_unflagged = []
    for page in pages:
        page_size = page.get("page_size") or [0, 0]
        for block in page.get("blocks") or []:
            block_id = block.get("block_id")
            if block_id in seen_blocks:
                duplicate_blocks.append(block_id)
            seen_blocks.add(block_id)
            bbox = block.get("bbox")
            if page_size and page_size[0] and page_size[1]:
                if not bbox or len(bbox) != 4:
                    invalid_blocks.append(block_id)
                else:
                    x1, y1, x2, y2 = [float(v) for v in bbox]
                    if not (0 <= x1 < x2 <= page_size[0] + 1 and 0 <= y1 < y2 <= page_size[1] + 1):
                        invalid_blocks.append(block_id)
            if not block.get("source"):
                source_missing.append(block_id)
            crop = block.get("block_crop_path")
            if crop and not asset_exists(crop):
                missing_assets.append(block_id)
            for asset in block.get("asset_paths") or []:
                if asset and not asset_exists(asset):
                    missing_assets.append(block_id)
            codes = _flag_codes(block)
            for validation in block.get("latex_validation") or []:
                if not validation.get("valid") and not codes:
                    formula_issues.append(block_id)
            if block.get("type") == "Table":
                html = block.get("table_html") or ""
                markdown = block.get("markdown") or ""
                markdown_table = bool(
                    re.search(r"^\s*\|.+\|\s*$", markdown, re.M)
                    and re.search(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+", markdown, re.M)
                )
                if (
                    "<tr" not in html.lower()
                    and not markdown_table
                    and "TABLE_EMPTY" not in codes
                    and "TABLE_STRUCTURE_REVIEW" not in codes
                ):
                    table_issues.append(block_id)
            if (
                block.get("type") in {"Text", "SectionHeader", "PageHeader", "Equation"}
                and not block.get("excluded")
                and not _block_has_payload(block)
                and not (_all_flag_codes(block) & {
                    "EMPTY_BLOCK", "EMPTY_BLOCK_RECOVERED",
                    "EMPTY_BLOCK_LOW_CONFIDENCE",
                })
            ):
                empty_unflagged.append(block_id)
            confidence = block.get("confidence")
            if (
                confidence is not None
                and float(confidence) < LOW_CONFIDENCE
                and not (codes & {"LOW_CONFIDENCE", "LOW_LAYOUT_CONFIDENCE"})
            ):
                confidence_unflagged.append(block_id)

    checks = {
        "pages_present": {"value": len(pages), "pass": bool(pages)},
        "all_pages_present": {
            "value": missing_pages, "pass": not missing_pages and not failed_pages,
        },
        "no_layout_failed_pages": {
            "value": layout_failed, "pass": not layout_failed,
        },
        "blocks_valid": {
            "value": invalid_blocks, "pass": not invalid_blocks,
        },
        "no_duplicate_blocks": {
            "value": duplicate_blocks, "pass": not duplicate_blocks,
        },
        "assets_present": {
            "value": missing_assets, "pass": not missing_assets,
        },
        "source_provenance": {
            "value": source_missing, "pass": not source_missing,
        },
        "formulas_valid_or_flagged": {
            "value": formula_issues, "pass": not formula_issues,
        },
        "tables_structured_or_flagged": {
            "value": table_issues, "pass": not table_issues,
        },
        "no_unflagged_empty_blocks": {
            "value": empty_unflagged, "pass": not empty_unflagged,
        },
        "low_confidence_flagged": {
            "value": confidence_unflagged, "pass": not confidence_unflagged,
        },
    }
    review_pages = {
        page.get("page_id") for page in pages
        if any(
            flag.get("severity") in {"warning", "error"}
            for flag in page.get("review") or []
        )
    }
    text_review_pages = set()
    layout_review_pages = set()
    page_text_risk_pages = set()
    text_review_blocks = []
    layout_review_blocks = []
    text_block_count = 0
    review_codes = Counter()
    excluded_review_codes = (
        MATH_REVIEW_CODES if resolved_profile.math_formula_checks else set()
    )
    for page in pages:
        codes = {
            flag.get("code")
            for flag in page.get("review") or []
            if flag.get("severity") in {"warning", "error"}
        }
        page_layout_codes = codes & LAYOUT_REVIEW_CODES
        for block in page.get("blocks") or []:
            block_codes = _flag_codes(block)
            codes.update(block_codes)
            if block_codes & LAYOUT_REVIEW_CODES:
                layout_review_blocks.append(block.get("block_id"))
                page_layout_codes |= LAYOUT_REVIEW_CODES & block_codes
            if block.get("type") in {"Text", "SectionHeader", "PageHeader", "Equation", "ListGroup"}:
                text_block_count += 1
                if (
                    block_codes - excluded_review_codes - FIGURE_REVIEW_CODES
                    - LAYOUT_REVIEW_CODES
                ):
                    text_review_blocks.append(block.get("block_id"))
        review_codes.update(codes)
        if codes & PAGE_TEXT_RISK_CODES:
            page_text_risk_pages.add(page.get("page_id"))
        if codes - excluded_review_codes - FIGURE_REVIEW_CODES - LAYOUT_REVIEW_CODES:
            text_review_pages.add(page.get("page_id"))
        if page_layout_codes:
            layout_review_pages.add(page.get("page_id"))
    parser_info = document.get("parser") or {}
    parser_name = parser_info.get("name") or "unknown"
    recognition_confidence = bool(parser_info.get("confidence_available"))
    trusted_parser = parser_name in trusted_parsers
    authorized_pages = {
        page.get("page_id"): _page_publish_authorized(page, trusted_parsers)
        for page in pages
    }
    publish_authorized = bool(pages) and all(authorized_pages.values())
    structural_pass = all(check["pass"] for check in checks.values())

    page_quality = []
    tier_totals: dict[str, dict[str, int]] = {}
    indexable_totals = [0, 0]  # blocks, chars
    for page in pages:
        page_codes = {
            flag.get("code")
            for flag in page.get("review") or []
            if flag.get("severity") in {"warning", "error"}
        }
        block_codes = set()
        legacy_held = []
        for block in page.get("blocks") or []:
            codes = _flag_codes(block)
            block_codes.update(codes)
            if codes & block_scoped_codes:
                legacy_held.append(block.get("block_id"))
        all_codes = page_codes | block_codes
        # Strict page gate: certification, and retrieval under policy="page".
        # A block-scoped code without a block owner still holds the page.
        strict_publish = (
            structural_pass and authorized_pages[page.get("page_id")]
            and page.get("status") == "ok"
            and not (page_codes | (block_codes - block_scoped_codes))
        )
        indexable = [b for b in page.get("blocks") or [] if _indexable_text(b)]
        if policy == "page":
            auto_publish, held_blocks, hold_reasons = strict_publish, legacy_held, {}
            page_gating = sorted(page_codes | (block_codes - block_scoped_codes))
        else:
            # A region-loss code needs an owning block that marks the gap.
            unowned_loss = (page_codes & REGION_LOSS_CODES) - block_codes
            page_gating = sorted((page_codes - PAGE_ADVISORY_CODES) | unowned_loss)
            auto_publish = (
                structural_pass and page.get("status") == "ok" and not page_gating
            )
            tokens = set(page.get("watermark_candidates") or [])
            held_blocks, hold_reasons = [], {}
            for block in page.get("blocks") or []:
                if block.get("excluded") or block.get("type") in NON_TEXT_TYPES:
                    continue
                reasons = _block_hold_reasons(block, trusted_parsers, tokens)
                if reasons:
                    held_blocks.append(block.get("block_id"))
                    hold_reasons[block.get("block_id")] = reasons
        held_set = set(held_blocks)
        published = [
            b for b in indexable if auto_publish and b.get("block_id") not in held_set
        ]
        if policy == "block" and indexable and not published:
            # Nothing on the page would reach retrieval; do not count it.
            auto_publish = False
        for block in published:
            tier = block_verification(block, trusted_parsers)
            bucket = tier_totals.setdefault(tier, {"blocks": 0, "chars": 0})
            bucket["blocks"] += 1
            bucket["chars"] += len(block["text"])
        indexable_totals[0] += len(indexable)
        indexable_totals[1] += sum(len(b["text"]) for b in indexable)
        page_quality.append({
            "page_id": page.get("page_id"),
            "status": page.get("status"),
            "auto_publish": auto_publish,
            "strict_publish": strict_publish,
            "publish_authorized": authorized_pages[page.get("page_id")],
            "review_codes": sorted(all_codes),
            "page_gating_codes": page_gating,
            "held_blocks": held_blocks,
            "published_blocks": len(published),
            "hold_reasons": hold_reasons,
        })
    block_counts = Counter(
        block.get("type") for page in pages for block in page.get("blocks") or []
    )
    text_chars = sum(
        len(block.get("text") or "")
        for page in pages for block in page.get("blocks") or []
    )
    formulas = [
        validation
        for page in pages for block in page.get("blocks") or []
        for validation in block.get("latex_validation") or []
    ]
    formula_valid_rate = (
        sum(1 for item in formulas if item.get("valid")) / len(formulas)
        if formulas else 1.0
    )
    formula_gate = (
        not resolved_profile.require_formula_quality
        or formula_valid_rate >= resolved_profile.formula_valid_min
    )
    block_count = sum(block_counts.values())
    quality_pass = (
        formula_gate
        and len(text_review_blocks) / max(1, text_block_count)
        <= resolved_profile.text_review_max
        and not layout_failed
        and not failed_pages
    )
    # Structural ingestion is safe to accept with review even when content
    # confidence is low; quality/production gates still control auto-publish.
    review_assisted_pass = structural_pass
    page_risk_gate = (
        len(page_text_risk_pages) / max(1, len(pages))
        <= resolved_profile.page_risk_max
    )
    production_pass = (
        review_assisted_pass and quality_pass and publish_authorized and page_risk_gate
        and all(
            # Certification stays strict whatever the retrieval policy is.
            item["strict_publish"] or item["status"] == "blank"
            for item in page_quality
        )
    )
    quality = {
        "page_count": len(pages),
        "block_count": sum(block_counts.values()),
        "block_types": dict(block_counts),
        "text_chars": text_chars,
        "text_blocks": text_block_count,
        "text_review_blocks": len(text_review_blocks),
        "text_review_block_rate": round(
            len(text_review_blocks) / max(1, text_block_count), 4
        ),
        "layout_review_blocks": len(layout_review_blocks),
        "layout_review_block_rate": round(
            len(layout_review_blocks) / max(1, block_count), 4
        ),
        "layout_review_pages": sorted(layout_review_pages),
        "layout_review_page_rate": round(
            len(layout_review_pages) / max(1, len(pages)), 4
        ),
        "formula_count": len(formulas),
        "formulas_valid": sum(1 for item in formulas if item.get("valid")),
        "formula_valid_rate": round(formula_valid_rate, 4),
        "table_blocks": block_counts.get("Table", 0),
        "figure_blocks": sum(
            block_counts.get(name, 0)
            for name in ("Diagram", "Picture", "PictureGroup", "Chart")
        ),
        "review_items": sum(len(page.get("review") or []) for page in pages),
        "review_pages": sorted(review_pages),
        "review_page_rate": round(len(review_pages) / max(1, len(pages)), 4),
        "text_review_pages": sorted(text_review_pages),
        "text_review_page_rate": round(
            len(text_review_pages) / max(1, len(pages)), 4
        ),
        "page_text_risk_pages": sorted(page_text_risk_pages),
        "page_text_risk_rate": round(
            len(page_text_risk_pages) / max(1, len(pages)), 4
        ),
        "review_codes": dict(review_codes),
        "auto_publish_pages": [
            item["page_id"] for item in page_quality if item["auto_publish"]
        ],
        "block_scoped_codes": sorted(block_scoped_codes),
        "publish_policy": policy,
        "held_blocks": [
            block_id for item in page_quality if item["auto_publish"]
            for block_id in item["held_blocks"]
        ],
        # Block coverage that actually reaches retrieval, split by why each
        # block was authorized. Not a quality certification.
        "retrievable_blocks": sum(t["blocks"] for t in tier_totals.values()),
        "retrievable_block_rate": round(
            sum(t["blocks"] for t in tier_totals.values()) / max(1, indexable_totals[0]), 4
        ),
        "retrievable_chars": sum(t["chars"] for t in tier_totals.values()),
        "retrievable_char_rate": round(
            sum(t["chars"] for t in tier_totals.values()) / max(1, indexable_totals[1]), 4
        ),
        "retrievable_by_verification": {k: dict(v) for k, v in sorted(tier_totals.items())},
        "auto_publish_page_rate": round(
            sum(1 for item in page_quality if item["auto_publish"])
            / max(1, len(page_quality)), 4
        ),
        "page_quality": page_quality,
        "profile": resolved_profile.name,
        "profile_language": resolved_profile.language,
        "confidence_available": recognition_confidence,
        "layout_confidence_available": bool(parser_info.get("layout_confidence_available")),
        "trusted_parser": trusted_parser,
        "parser_sources": dict(parser_info.get("sources") or {}),
        "quality_pass": quality_pass,
        "content_quality_pass": quality_pass,
        "quality_certified": structural_pass and quality_pass and publish_authorized,
        "review_assisted_pass": review_assisted_pass,
        "page_risk_gate": page_risk_gate,
        "auto_publish_authorized": publish_authorized,
    }
    return {
        "schema_version": CANONICAL_VERSION,
        "pass": structural_pass,
        "quality_pass": quality_pass,
        "content_quality_pass": quality_pass,
        "quality_certified": structural_pass and quality_pass and publish_authorized,
        "review_assisted_pass": review_assisted_pass,
        "production_pass": production_pass,
        "auto_publish_pass": production_pass,
        "checks": checks,
        "quality": quality,
    }
