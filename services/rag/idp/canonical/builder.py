"""Unified Canonical document builder (schema_version='idp-canonical-1', unified contract)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from idp.canonical.contract import (
    CANONICAL_CONTRACT_VERSION,
    PROVENANCE_VERSION,
    resolve_document_version,
)
from idp.canonical.questions import analyze_questions
from idp.canonical.schema import CANONICAL_VERSION, canonical_blocks
from idp.runtime.compatibility import runtime_manifest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    runtime_info: dict | None = None,
    calibrator_registry=None,
) -> dict:
    questions = analyze_questions(pages)
    profile_name = profile or "general"
    canonical_pages = []
    for page in pages:
        page_id = page.get("page_id")
        page_number = page.get("page_number")
        if type(page_number) is not int or page_number < 1:
            page_number = page_id
        canonical_pages.append({
            "page_id": page_id,
            "page_number": page_number,
            "page_size": page.get("page_size"),
            "status": page.get("processing_status") or page.get("status") or "ok",
            "classification": page.get("classification"),
            "profile": page.get("profile"),
            "parser": page.get("parser"),
            "ocr_language": page.get("ocr_language"),
            "source_image_sha256": page.get("source_image_sha256"),
            "render_provenance": page.get("render_provenance"),
            "preprocessing": page.get("preprocessing"),
            "page_route": page.get("page_route"),
            "region_tasks": page.get("region_tasks"),
            "region_recovery": page.get("region_recovery"),
            "structured_enrichment": page.get("structured_enrichment"),
            "vl_primary": page.get("vl_primary"),
            "dual_read": page.get("dual_read"),
            "math_context": page.get("math_context"),
            "question_context": page.get("question_context"),
            "region_windows": page.get("region_windows"),
            "hybrid_source": page.get("hybrid_source"),
            "text_recognition": page.get("text_recognition"),
            "question_groups": page.get("question_groups") or [],
            "watermark_candidates": page.get("watermark_candidates") or [],
            "text_layer_audit": page.get("text_layer_audit"),
            "quality_source": page.get("quality_source"),
            "review": [f for f in page.get("review") or [] if f.get("block_id") is None],
            "blocks": canonical_blocks(
                page,
                calibrator_registry=calibrator_registry,
                profile=profile_name,
            ),
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

    meta = dict(source_metadata or {})
    doc_version = resolve_document_version(
        {"source_sha256": source_sha256, "source_metadata": meta}
    )

    return {
        "schema_version": CANONICAL_VERSION,
        "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
        "provenance_version": PROVENANCE_VERSION,
        "created_at": _utc_now(),
        "doc_id": source_sha256,
        "document_version": doc_version,
        "source": str(source_path),
        "source_sha256": source_sha256,
        "pipeline_version": pipeline_version,
        "runtime_manifest": (
            dict(runtime_info)
            if runtime_info is not None
            else runtime_manifest(include_external_binaries=False)
        ),
        "profile": profile_name,
        "source_acl": source_acl or {
            "owner": None, "users": [], "groups": [], "is_public": False,
        },
        "source_metadata": meta,
        "parser": parser_info,
        "expected_pages": list(expected_pages or [p["page_id"] for p in canonical_pages]),
        "page_manifest": list(page_manifest or []),
        "failed_pages": list(failed_pages or []),
        "question_grouping_version": questions["version"],
        "question_groups": questions["groups"],
        "pages": canonical_pages,
    }
