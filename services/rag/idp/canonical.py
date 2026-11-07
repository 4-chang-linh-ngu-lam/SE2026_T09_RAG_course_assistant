"""Canonical parsed-document contract for the ingestion stage.

Ingestion stops here: pages, typed blocks, text/LaTeX/table payloads, bbox,
provenance and review flags. Chunking, embeddings, BM25 and retrieval are
downstream consumers and are not part of this module.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import math
import re

from .profiles import resolve_profile
from .structure import visual_evidence, parse_table_html
from .questions import analyze_questions

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
    "PAGE_LAYOUT_FAILED", "FAST_MODE_REVIEW", "FALLBACK_ENGINE_REVIEW",
    "PAGE_ORIENTATION_REVIEW", "PAGE_ORIENTATION_UNRESOLVED",
    "REGION_WINDOWS_REVIEW", "REGION_WINDOWS_PARTIAL",
    "VERIFIER_FAILED",
}


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
            "blocks": [_block_payload(block, page) for block in page.get("blocks") or []],
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


def audit_canonical(
    document: dict,
    trusted_parsers: set[str] | None = None,
    profile: str | None = None,
) -> dict:
    trusted_parsers = set(trusted_parsers or ())
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
            if crop and not Path(crop).exists():
                missing_assets.append(block_id)
            for asset in block.get("asset_paths") or []:
                if asset and not Path(asset).exists():
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
    for page in pages:
        page_codes = {
            flag.get("code")
            for flag in page.get("review") or []
            if flag.get("severity") in {"warning", "error"}
        }
        block_codes = set()
        for block in page.get("blocks") or []:
            block_codes.update(_flag_codes(block))
        all_codes = page_codes | block_codes
        auto_publish = (
            structural_pass and authorized_pages[page.get("page_id")]
            and page.get("status") == "ok"
            and not all_codes
        )
        page_quality.append({
            "page_id": page.get("page_id"),
            "status": page.get("status"),
            "auto_publish": auto_publish,
            "publish_authorized": authorized_pages[page.get("page_id")],
            "review_codes": sorted(all_codes),
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
            item["auto_publish"] or item["status"] == "blank"
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
