"""Level 4 Canonical v1 quality gate, publish authorization, and artifact validation."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath

from idp.config import resolve_profile
from idp.evidence import cross_read
from idp.validation import content_checks
from idp.input.validation import encoding_issues
from idp.validation.calibration import (
    CONFIDENCE_SCHEMA_VERSION,
    NATIVE_SCORE_SOURCES,
    infer_score_kind,
)

CANONICAL_VERSION = "idp-canonical-1"
LOW_CONFIDENCE = 0.60
PUBLISH_DECISION_VERSION = "idp-publish-decision-1"

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

PUBLISH_POLICIES = {"page", "block"}
DEFAULT_PUBLISH_POLICY = "block"
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
    "WATERMARK_CANDIDATE_REVIEW",
}
REGION_LOSS_CODES = {
    "STRUCTURED_BUDGET_EXHAUSTED", "STRUCTURED_PIXEL_LIMIT",
    "STRUCTURED_REGION_UNRESOLVED",
    "OCR_REGION_UNRESOLVED", "OCR_REGION_BUDGET_EXHAUSTED",
    "OCR_REGION_DISAGREEMENT", "OCR_REGION_COMPLEX_CONTENT",
}
RECOVERY_GAP_CODES = {
    "budget_limit": "OCR_REGION_BUDGET_EXHAUSTED",
    "pixel_limit": "OCR_REGION_UNRESOLVED",
    "unresolved": "OCR_REGION_UNRESOLVED",
    "failed": "OCR_REGION_FAILED",
    "disagreement": "OCR_REGION_DISAGREEMENT",
}
STRUCTURED_GAP_CODES = {
    "budget_limit": "STRUCTURED_BUDGET_EXHAUSTED",
    "pixel_limit": "STRUCTURED_PIXEL_LIMIT",
    "unresolved": "STRUCTURED_REGION_UNRESOLVED",
}
BLOCK_ADVISORY_CODES = {
    "FAST_OCR_REVIEW", "FAST_MODE_REVIEW", "FALLBACK_ENGINE_REVIEW",
    "QUESTION_GROUP_REVIEW",
    "FIGURE_NO_CAPTION", "FIGURE_REFERENCE_REVIEW", "FIGURE_NO_IMAGE",
    "LOW_LAYOUT_CONFIDENCE",
}
NON_TEXT_TYPES = {
    "Picture", "PictureGroup", "Diagram", "Chart",
    "PageHeader", "PageFooter", "PageNumber",
}
VERIFIED_CODES = {"OCR_DUAL_READ_AGREED", "HUMAN_CORRECTED", cross_read.FORMULA_AGREED}
CROSS_READ_SCORED_CODES = {
    cross_read.FORMULA_CONSISTENT, cross_read.TABLE_AGREED, cross_read.TABLE_PARTIAL,
}
CROSS_READ_RESOLVES = {"STRUCTURED_EXTRACTION_REVIEW", "TABLE_OCR_REVIEW", "TABLE_HEADER_UNKNOWN"}
SUPERSEDED_CODES = {cross_read.LINE_SUPERSEDED}
VERIFICATION_TIERS = ("none", "scored", "verified", "trusted")
SCORE_ONLY_CODES = {"LOW_CONFIDENCE"}


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
    return {flag.get("code") for flag in block.get("review_flags") or []}


def _score_ok(confidence) -> bool:
    return (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(confidence)
        and LOW_CONFIDENCE <= confidence <= 1
    )


def block_verification(block: dict, trusted: set[str]) -> str:
    """Why a block's text may be published: trusted / verified / scored / none."""
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
    text = block.get("text")
    return (
        not block.get("excluded")
        and block.get("retrieval_eligible") is not False
        and block.get("type") not in NON_TEXT_TYPES
        and isinstance(text, str) and bool(text.strip())
    )


def _resolved_codes(block: dict, page_blocks: list[dict] | None) -> set[str]:
    """Warning codes that say nothing about this block's own text (see content_checks)."""
    if page_blocks is None:
        return set()
    codes = _flag_codes(block)
    resolved = set()
    if content_checks.BUDGET_CODE in codes and content_checks.budget_hold_is_infrastructure(block):
        resolved.add(content_checks.BUDGET_CODE)
    if content_checks.DISAGREEMENT_CODE in codes and content_checks.resolved_disagreements(block, page_blocks):
        resolved.add(content_checks.DISAGREEMENT_CODE)
    return resolved


def _block_hold_reasons(
    block: dict,
    trusted: set[str],
    watermark_tokens: set[str],
    page_blocks: list[dict] | None = None,
) -> list[str]:
    codes = _flag_codes(block) - BLOCK_ADVISORY_CODES - _resolved_codes(block, page_blocks)
    if _all_flag_codes(block) & cross_read.CROSS_READ_CODES:
        codes -= CROSS_READ_RESOLVES
    verification = block_verification(block, trusted)
    if verification in {"trusted", "verified"}:
        codes -= SCORE_ONLY_CODES
    reasons = sorted(codes)
    if verification == "none":
        reasons.append("UNVERIFIED_SOURCE")
    if watermark_tokens and (block.get("text") or "").strip() in watermark_tokens:
        reasons.append("WATERMARK_CANDIDATE_TOKEN")
    return reasons


def _page_publish_authorized(page: dict, trusted: set[str]) -> bool:
    blocks = [b for b in page.get("blocks") or [] if not b.get("excluded")]
    if not blocks:
        return page.get("status") == "blank"
    for block in blocks:
        source = block.get("source")
        if not source:
            return False
        if source in trusted:
            continue
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


def stamp_publish_decisions(document: dict, report: dict) -> int:
    """Record per-block retrieval hold decisions onto ``document`` in place."""
    quality = report["quality"]
    by_page = {item["page_id"]: item for item in quality["page_quality"]}
    held_total = 0
    for page in document.get("pages") or []:
        item = by_page.get(page.get("page_id")) or {}
        held = set(item.get("held_blocks") or ())
        reasons = item.get("hold_reasons") or {}
        page_reasons = list(item.get("page_gating_codes") or ()) or ["PAGE_NOT_PUBLISHED"]
        for block in page.get("blocks") or []:
            block.pop("held", None)
            block.pop("hold_reasons", None)
            if block.get("excluded") or block.get("type") in NON_TEXT_TYPES:
                continue
            block_id = block.get("block_id")
            if block_id in held:
                why = list(reasons.get(block_id) or page_reasons)
            elif not item.get("auto_publish"):
                why = page_reasons
            else:
                block["held"] = False
                continue
            block["held"] = True
            block["hold_reasons"] = why
            held_total += 1
    document["publish_decision"] = {
        "version": PUBLISH_DECISION_VERSION,
        "policy": quality.get("publish_policy"),
        "held_blocks": held_total,
    }
    return held_total


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
    """Audit a Canonical v1 document structurally and per-block for publication."""
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
    layout_failed = [page["page_id"] for page in pages if page.get("status") == "layout_failed"]

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
                html_val = block.get("table_html") or ""
                markdown = block.get("markdown") or ""
                markdown_table = bool(
                    re.search(r"^\s*\|.+\|\s*$", markdown, re.M)
                    and re.search(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+", markdown, re.M)
                )
                if (
                    "<tr" not in html_val.lower()
                    and not markdown_table
                    and "TABLE_EMPTY" not in codes
                    and "TABLE_STRUCTURE_REVIEW" not in codes
                ):
                    table_issues.append(block_id)
            if (
                block.get("type") in {"Text", "SectionHeader", "PageHeader", "Equation"}
                and not block.get("excluded")
                and not _block_has_payload(block)
                and not (_all_flag_codes(block) & {"EMPTY_BLOCK", "EMPTY_BLOCK_RECOVERED", "EMPTY_BLOCK_LOW_CONFIDENCE"})
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
        "all_pages_present": {"value": missing_pages, "pass": not missing_pages and not failed_pages},
        "no_layout_failed_pages": {"value": layout_failed, "pass": not layout_failed},
        "blocks_valid": {"value": invalid_blocks, "pass": not invalid_blocks},
        "no_duplicate_blocks": {"value": duplicate_blocks, "pass": not duplicate_blocks},
        "assets_present": {"value": missing_assets, "pass": not missing_assets},
        "source_provenance": {"value": source_missing, "pass": not source_missing},
        "formulas_valid_or_flagged": {"value": formula_issues, "pass": not formula_issues},
        "tables_structured_or_flagged": {"value": table_issues, "pass": not table_issues},
        "no_unflagged_empty_blocks": {"value": empty_unflagged, "pass": not empty_unflagged},
        "low_confidence_flagged": {"value": confidence_unflagged, "pass": not confidence_unflagged},
    }

    review_pages = {
        page.get("page_id") for page in pages
        if any(flag.get("severity") in {"warning", "error"} for flag in page.get("review") or [])
    }
    text_review_pages = set()
    layout_review_pages = set()
    page_text_risk_pages = set()
    text_review_blocks = []
    layout_review_blocks = []
    text_block_count = 0
    review_codes = Counter()
    excluded_review_codes = MATH_REVIEW_CODES if resolved_profile.math_formula_checks else set()

    for page in pages:
        codes = {
            flag.get("code") for flag in page.get("review") or []
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
                if block_codes - excluded_review_codes - FIGURE_REVIEW_CODES - LAYOUT_REVIEW_CODES:
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
    scored_non_native = 0
    calibrated_non_native = 0
    score_kinds: Counter[str] = Counter()
    for page in pages:
        for block in page.get("blocks") or []:
            src = block.get("source")
            conf = block.get("confidence")
            meta = block.get("confidence_meta")
            kind = (
                meta.get("score_kind")
                if isinstance(meta, dict) and meta.get("score_kind")
                else infer_score_kind(src, raw_score=conf if isinstance(conf, (int, float)) else None)
            )
            score_kinds[str(kind)] += 1
            if src not in NATIVE_SCORE_SOURCES and conf is not None:
                scored_non_native += 1
                if (
                    isinstance(meta, dict)
                    and meta.get("is_calibrated") is True
                    and meta.get("calibrated_probability") is not None
                ):
                    calibrated_non_native += 1
    confidence_calibrated = scored_non_native > 0 and calibrated_non_native == scored_non_native
    confidence_semantics = (
        "calibrated_probability"
        if confidence_calibrated
        else (
            "deterministic_native_no_ocr_score"
            if scored_non_native == 0 and not recognition_confidence
            else "uncalibrated_heuristic_routing_score"
        )
    )
    authorized_pages = {page.get("page_id"): _page_publish_authorized(page, trusted_parsers) for page in pages}
    publish_authorized = bool(pages) and all(authorized_pages.values())
    structural_pass = all(check["pass"] for check in checks.values())

    page_quality = []
    tier_totals: dict[str, dict[str, int]] = {}
    indexable_totals = [0, 0]
    for page in pages:
        page_codes = {
            flag.get("code") for flag in page.get("review") or []
            if flag.get("severity") in {"warning", "error"}
        }
        block_codes = set()
        legacy_held = []
        resolved_holds: dict = {}
        for block in page.get("blocks") or []:
            codes = _flag_codes(block)
            block_codes.update(codes)
            if codes & block_scoped_codes:
                legacy_held.append(block.get("block_id"))
        all_codes = page_codes | block_codes
        strict_publish = (
            structural_pass
            and authorized_pages[page.get("page_id")]
            and page.get("status") == "ok"
            and not (page_codes | (block_codes - block_scoped_codes))
        )
        indexable = [b for b in page.get("blocks") or [] if _indexable_text(b)]
        if policy == "page":
            auto_publish, held_blocks, hold_reasons = strict_publish, legacy_held, {}
            page_gating = sorted(page_codes | (block_codes - block_scoped_codes))
        else:
            unowned_loss = (page_codes & REGION_LOSS_CODES) - block_codes
            page_gating = sorted((page_codes - PAGE_ADVISORY_CODES) | unowned_loss)
            auto_publish = structural_pass and page.get("status") == "ok" and not page_gating
            tokens = set(page.get("watermark_candidates") or [])
            held_blocks, hold_reasons = [], {}
            page_blocks = page.get("blocks") or []
            conflicts = content_checks.membership_conflicts(page_blocks)
            for block in page_blocks:
                if block.get("excluded") or block.get("type") in NON_TEXT_TYPES:
                    continue
                reasons = _block_hold_reasons(block, trusted_parsers, tokens, page_blocks)
                if block.get("block_id") in conflicts:
                    reasons.append(content_checks.MEMBERSHIP_CODE)
                resolved = sorted(_resolved_codes(block, page_blocks))
                if resolved:
                    resolved_holds[block.get("block_id")] = resolved
                if reasons:
                    held_blocks.append(block.get("block_id"))
                    hold_reasons[block.get("block_id")] = reasons
        held_set = set(held_blocks)
        published = [b for b in indexable if auto_publish and b.get("block_id") not in held_set]
        if policy == "block" and indexable and not published:
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
            "resolved_holds": resolved_holds,
        })

    block_counts = Counter(block.get("type") for page in pages for block in page.get("blocks") or [])
    text_chars = sum(len(block.get("text") or "") for page in pages for block in page.get("blocks") or [])
    formulas = [
        validation
        for page in pages for block in page.get("blocks") or []
        for validation in block.get("latex_validation") or []
    ]
    formula_valid_rate = (
        sum(1 for item in formulas if item.get("valid")) / len(formulas)
        if formulas else 1.0
    )
    formula_gate = not resolved_profile.require_formula_quality or formula_valid_rate >= resolved_profile.formula_valid_min
    block_count = sum(block_counts.values())
    quality_pass = (
        formula_gate
        and len(text_review_blocks) / max(1, text_block_count) <= resolved_profile.text_review_max
        and not layout_failed
        and not failed_pages
    )
    review_assisted_pass = structural_pass
    page_risk_gate = len(page_text_risk_pages) / max(1, len(pages)) <= resolved_profile.page_risk_max
    production_pass = (
        review_assisted_pass
        and quality_pass
        and publish_authorized
        and page_risk_gate
        and all(item["strict_publish"] or item["status"] == "blank" for item in page_quality)
    )
    quality = {
        "page_count": len(pages),
        "block_count": block_count,
        "block_types": dict(block_counts),
        "text_chars": text_chars,
        "text_blocks": text_block_count,
        "text_review_blocks": len(text_review_blocks),
        "text_review_block_rate": round(len(text_review_blocks) / max(1, text_block_count), 4),
        "layout_review_blocks": len(layout_review_blocks),
        "layout_review_block_rate": round(len(layout_review_blocks) / max(1, block_count), 4),
        "layout_review_pages": sorted(layout_review_pages),
        "layout_review_page_rate": round(len(layout_review_pages) / max(1, len(pages)), 4),
        "formula_count": len(formulas),
        "formulas_valid": sum(1 for item in formulas if item.get("valid")),
        "formula_valid_rate": round(formula_valid_rate, 4),
        "table_blocks": block_counts.get("Table", 0),
        "figure_blocks": sum(block_counts.get(name, 0) for name in ("Diagram", "Picture", "PictureGroup", "Chart")),
        "review_items": sum(len(page.get("review") or []) for page in pages),
        "review_pages": sorted(review_pages),
        "review_page_rate": round(len(review_pages) / max(1, len(pages)), 4),
        "text_review_pages": sorted(text_review_pages),
        "text_review_page_rate": round(len(text_review_pages) / max(1, len(pages)), 4),
        "page_text_risk_pages": sorted(page_text_risk_pages),
        "page_text_risk_rate": round(len(page_text_risk_pages) / max(1, len(pages)), 4),
        "review_codes": dict(review_codes),
        "auto_publish_pages": [item["page_id"] for item in page_quality if item["auto_publish"]],
        "block_scoped_codes": sorted(block_scoped_codes),
        "publish_policy": policy,
        "held_blocks": [
            block_id for item in page_quality if item["auto_publish"] for block_id in item["held_blocks"]
        ],
        "retrievable_blocks": sum(t["blocks"] for t in tier_totals.values()),
        "retrievable_block_rate": round(sum(t["blocks"] for t in tier_totals.values()) / max(1, indexable_totals[0]), 4),
        "retrievable_chars": sum(t["chars"] for t in tier_totals.values()),
        "retrievable_char_rate": round(sum(t["chars"] for t in tier_totals.values()) / max(1, indexable_totals[1]), 4),
        "retrievable_by_verification": {k: dict(v) for k, v in sorted(tier_totals.items())},
        "auto_publish_page_rate": round(sum(1 for item in page_quality if item["auto_publish"]) / max(1, len(page_quality)), 4),
        "page_quality": page_quality,
        "profile": resolved_profile.name,
        "profile_language": resolved_profile.language,
        "confidence_available": recognition_confidence,
        "confidence_schema_version": CONFIDENCE_SCHEMA_VERSION,
        "confidence_calibrated": confidence_calibrated,
        "confidence_semantics": confidence_semantics,
        "confidence_score_kinds": dict(score_kinds),
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


def validate_outputs(
    out_dir: str | Path,
    pages: list[dict],
    require_bbox: bool = True,
) -> list[str]:
    out_dir = Path(out_dir)
    errors = []
    seen_blocks = set()
    page_ids = set()
    for page in pages:
        page_id = page["page_id"]
        if page_id in page_ids:
            errors.append(f"duplicate page {page_id}")
        page_ids.add(page_id)
        page_json = out_dir / "pages" / f"p{page_id:04d}.json"
        if not page_json.exists():
            errors.append(f"missing page json {page_json}")
        for block in page["blocks"]:
            block_id = block.get("block_id")
            if block_id in seen_blocks:
                errors.append(f"duplicate block id {block_id}")
            seen_blocks.add(block_id)
            bbox = block.get("bbox")
            if require_bbox and (not bbox or len(bbox) != 4):
                errors.append(f"{block_id}: invalid bbox")
            elif require_bbox:
                page_width, page_height = page.get("page_size") or (float("inf"), float("inf"))
                if not (
                    0 <= float(bbox[0]) < float(bbox[2]) <= page_width + 1
                    and 0 <= float(bbox[1]) < float(bbox[3]) <= page_height + 1
                ):
                    errors.append(f"{block_id}: bbox outside page")
            crop = block.get("block_crop_path")
            if crop and not Path(crop).exists():
                errors.append(f"{block_id}: missing block crop {crop}")
            for asset in block.get("asset_paths") or []:
                if asset and not Path(asset).exists():
                    errors.append(f"{block_id}: missing asset {asset}")
            if block.get("latex") and not block.get("latex_validation"):
                errors.append(f"{block_id}: latex without validation")
    return errors


def check_ingestion_artifacts(out_dir: str | Path, expected_pages: list[int] | None = None) -> dict:
    out = Path(out_dir)
    errors = []
    try:
        canonical = json.loads((out / "canonical.json").read_text(encoding="utf-8"))
        ingestion = json.loads((out / "ingestion_report.json").read_text(encoding="utf-8"))
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"pass": False, "errors": [f"missing/invalid ingestion artifacts: {exc}"]}
    if not isinstance(canonical, dict) or not isinstance(ingestion, dict) or not isinstance(report, dict):
        return {"pass": False, "errors": ["ingestion artifacts must be JSON objects"]}
    if not canonical.get("schema_version") or not canonical.get("source_sha256"):
        errors.append("canonical schema or source hash missing")
    pages = canonical.get("pages")
    if not isinstance(pages, list):
        errors.append("canonical pages must be a list")
        pages = []
    seen = set()
    for page in pages:
        if not isinstance(page, dict) or type(page.get("page_id")) is not int:
            errors.append("invalid canonical page entry")
            continue
        pid = page["page_id"]
        if pid in seen:
            errors.append(f"duplicate canonical page {pid}")
        seen.add(pid)
        if not (out / "pages" / f"p{pid:04d}.json").is_file():
            errors.append(f"missing parsed page JSON: {pid}")
    if expected_pages is not None and set(expected_pages) != seen:
        errors.append(f"page coverage mismatch: expected {sorted(set(expected_pages))}, got {sorted(seen)}")
    for message in report.get("output_validation_errors") or []:
        errors.append(f"output validation: {message}")
    if canonical.get("failed_pages") or report.get("failed_pages"):
        errors.append("one or more pages failed ingestion")
    if not isinstance(ingestion.get("checks"), dict) or not isinstance(ingestion.get("pass"), bool):
        errors.append("missing canonical ingestion quality checks")
    return {
        "pass": not errors,
        "errors": errors,
        "checked_pages": len(seen),
        "ingestion_pass": ingestion.get("pass"),
    }


def digital_consistency_audit(
    pages: list[dict],
    content_loss: dict,
    source_type: str,
    output_errors: list[str] | None = None,
) -> dict:
    table_consistency = []
    encoding_unflagged = []
    for page in pages:
        for block in page["blocks"]:
            codes = {f.get("code") for f in block.get("review_flags", [])}
            if block["block_type"] == "Table":
                if block.get("structured_provenance"):
                    if not block.get("table_cells") and "STRUCTURED_EXTRACTION_REVIEW" not in codes:
                        table_consistency.append(block["block_id"])
                elif source_type == "pdf_text" and block.get("table_metrics") is not None:
                    metrics = block["table_metrics"]
                    if bool(metrics.get("needs_review")) != ("TABLE_STRUCTURE_REVIEW" in codes):
                        table_consistency.append(block["block_id"])
                elif not (block.get("markdown") or block.get("text") or block.get("table_html")):
                    table_consistency.append(block["block_id"])
            if (
                source_type == "pdf_text"
                and block["block_type"] not in {"PageHeader", "PageFooter"}
                and encoding_issues(block.get("text") or "")
                and "TEXT_ENCODING_REVIEW" not in codes
            ):
                encoding_unflagged.append(block["block_id"])

    checks = {
        "pages_present": {"value": len(pages), "pass": bool(pages) and all(p.get("blocks") is not None for p in pages)},
        "table_metrics_consistent": {"value": table_consistency, "pass": not table_consistency},
        "encoding_flagged": {"value": encoding_unflagged, "pass": not encoding_unflagged},
        "no_content_loss": {"value": content_loss, "pass": not any(content_loss.values())},
        "output_validation": {"value": output_errors or [], "pass": not output_errors},
    }
    return {"checks": checks, "pass": all(check["pass"] for check in checks.values())}
