"""Unified Canonical v1/v2 contract, normalization, and block-level provenance."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from idp.validation.calibration import build_confidence_meta
from idp.validation.quality_gate import (
    CANONICAL_VERSION,
    SUPERSEDED_CODES,
    VERIFICATION_TIERS,
    audit_canonical,
    block_verification,
)

SUPPORTED_CANONICAL_SCHEMAS = frozenset({"idp-canonical-1", "idp-canonical-2"})
CANONICAL_CONTRACT_VERSION = "idp-canonical-unified-1"
PROVENANCE_VERSION = "idp-provenance-1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_NON_RETRIEVABLE_TYPES = {
    "PageHeader",
    "PageFooter",
    "PageNumber",
    "Picture",
    "PictureGroup",
    "Diagram",
    "Chart",
}


def resolve_document_version(canonical: dict) -> str:
    """Resolve document_version consistently across Canonical v1 and v2."""
    top_version = canonical.get("document_version")
    if top_version is not None:
        if not isinstance(top_version, str) or not top_version.strip():
            raise ValueError("invalid canonical document_version")
        return top_version
    meta_version = (canonical.get("source_metadata") or {}).get("document_version")
    if meta_version is not None:
        if not isinstance(meta_version, str) or not meta_version.strip():
            raise ValueError("invalid legacy document version")
        return meta_version
    sha = canonical.get("source_sha256")
    if isinstance(sha, str) and _SHA256_RE.fullmatch(sha):
        return f"sha256:{sha}"
    raise ValueError("canonical missing source_sha256 and document_version")


def _infer_stage(source: str | None) -> str:
    src = (source or "").strip()
    if src in {
        "pymupdf", "pandoc", "text", "markdown", "html", "csv",
        "openpyxl", "python-pptx", "email", "pdf_text",
    }:
        return "native"
    if src in {"paddleocr_vl_gguf", "paddleocr_vl_primary"}:
        return "vlm_ocr"
    if src in {"tesseract", "tesseract_ocr", "tesseract_fast", "tesseract_fallback", "ocr_region_recovery"}:
        return "cpu_ocr"
    if src in {"opencv_grid_tesseract", "structured_region"}:
        return "structured_region"
    if src == "layout_figure":
        return "layout"
    return "unknown"


def build_block_provenance(
    block: dict,
    page: dict | None = None,
    *,
    calibrator: Any | None = None,
) -> dict[str, Any]:
    """Build normalized block provenance while keeping bare legacy blocks null-safe."""
    existing = block.get("provenance")
    if isinstance(existing, dict) and existing.get("version") == PROVENANCE_VERSION:
        return dict(existing)

    structured_prov = block.get("structured_provenance")
    region_id = (
        block.get("region_id")
        or block.get("recovery_region_id")
        or (structured_prov.get("region_id") if isinstance(structured_prov, dict) else None)
    )
    if region_id is not None:
        region_id = str(region_id)

    evidence_refs: list[dict[str, Any]] = list(block.get("evidence_refs") or [])
    if not evidence_refs:
        seen_paths: set[str] = set()
        crop_path = block.get("block_crop_path") or block.get("crop_path")
        if crop_path:
            seen_paths.add(str(crop_path))
            evidence_refs.append({
                "kind": "crop",
                "path": str(crop_path),
                "sha256": block.get("crop_sha256"),
            })
        for asset in block.get("asset_paths") or []:
            if asset and str(asset) not in seen_paths:
                seen_paths.add(str(asset))
                evidence_refs.append({
                    "kind": "asset",
                    "path": str(asset),
                    "sha256": None,
                })
        if (
            not evidence_refs
            and isinstance(page, dict)
            and page.get("source_image_sha256")
            and _infer_stage(block.get("source")) in {"cpu_ocr", "vlm_ocr", "structured_region", "layout"}
        ):
            evidence_refs.append({
                "kind": "page_image",
                "path": page.get("page_image"),
                "sha256": page.get("source_image_sha256"),
            })

    candidate_id = block.get("candidate_id")
    if candidate_id is None and block.get("block_id") and block.get("source"):
        if region_id or evidence_refs or structured_prov:
            candidate_id = f"{block['block_id']}:{block['source']}"

    confidence_meta = block.get("confidence_meta")
    if not isinstance(confidence_meta, dict):
        confidence_meta = build_confidence_meta(
            block.get("confidence"),
            source=block.get("source"),
            calibrator=calibrator,
        )

    producer_detail = structured_prov or block.get("source_evidence")
    return {
        "version": PROVENANCE_VERSION,
        "source": block.get("source"),
        "stage": _infer_stage(block.get("source")),
        "region_id": region_id,
        "candidate_id": candidate_id,
        "evidence_refs": evidence_refs,
        "producer": {
            "name": block.get("source"),
            "stage": _infer_stage(block.get("source")),
            "detail": producer_detail if isinstance(producer_detail, dict) else None,
        },
        "confidence": confidence_meta,
    }


def _normalize_page_number(page: dict) -> int:
    pid = page.get("page_id")
    pnum = page.get("page_number")
    if type(pid) is int and pid >= 1:
        return pid
    if type(pnum) is int and pnum >= 1:
        return pnum
    raise ValueError("invalid or duplicate canonical page")


def normalize_canonical(document: dict) -> dict:
    """Normalize Canonical v1 and Canonical v2 artifacts into one uniform view."""
    if not isinstance(document, dict):
        raise ValueError("canonical document must be an object")
    schema = document.get("schema_version")
    if schema not in SUPPORTED_CANONICAL_SCHEMAS:
        raise ValueError("unsupported canonical schema")

    doc = deepcopy(document)
    if "source_sha256" in doc and doc["source_sha256"] is not None:
        sha = doc["source_sha256"]
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            raise ValueError("invalid canonical source checksum")

    if doc.get("document_version") is not None or doc.get("source_sha256"):
        doc["document_version"] = resolve_document_version(doc)

    if "question_groups" not in doc:
        structures = doc.get("structures")
        if isinstance(structures, dict) and isinstance(structures.get("questions"), list):
            doc["question_groups"] = list(structures["questions"])
        else:
            doc["question_groups"] = []

    raw_pages = doc.get("pages")
    if not isinstance(raw_pages, list):
        raise ValueError("canonical pages must be a list")

    seen_pids: set[int] = set()
    normalized_pages: list[dict] = []
    for page in raw_pages:
        if not isinstance(page, dict):
            raise ValueError("invalid canonical page")
        pid = _normalize_page_number(page)
        if pid in seen_pids:
            raise ValueError("invalid or duplicate canonical page")
        seen_pids.add(pid)
        page["page_id"] = pid
        if type(page.get("page_number")) is not int or page["page_number"] < 1:
            page["page_number"] = pid
        if not page.get("status"):
            page["status"] = page.get("processing_status") or "ok"
        norm_blocks: list[dict] = []
        for idx, blk in enumerate(page.get("blocks") or []):
            if not isinstance(blk, dict):
                continue
            btype = blk.get("type") or blk.get("block_type")
            if btype is not None:
                blk["type"] = btype
            if "excluded" not in blk:
                blk["excluded"] = bool(blk.get("excluded_from_content"))
            if "order" not in blk:
                blk["order"] = idx
            if not isinstance(blk.get("confidence_meta"), dict):
                blk["confidence_meta"] = build_confidence_meta(
                    blk.get("confidence"),
                    source=blk.get("source"),
                )
            if not isinstance(blk.get("provenance"), dict):
                blk["provenance"] = build_block_provenance(blk, page)
            norm_blocks.append(blk)
        page["blocks"] = norm_blocks
        normalized_pages.append(page)

    doc["pages"] = normalized_pages
    if not doc.get("expected_pages"):
        doc["expected_pages"] = [p["page_id"] for p in normalized_pages]
    doc.setdefault("canonical_contract_version", CANONICAL_CONTRACT_VERSION)
    doc.setdefault("provenance_version", PROVENANCE_VERSION)
    return doc


def retrievable_blocks_with_held(
    canonical: dict,
    *,
    trusted_parsers: set[str] | tuple[str, ...] = (),
    block_scoped_codes: set[str] | frozenset[str] | tuple[str, ...] = (),
    policy: str | None = None,
    min_verification: str | None = None,
) -> tuple[list[dict], set[str]]:
    """Extract retrievable blocks and held block IDs uniformly for Canonical v1 and v2."""
    doc = normalize_canonical(canonical)
    if min_verification is not None and min_verification not in VERIFICATION_TIERS[1:]:
        raise ValueError(f"min_verification must be one of {VERIFICATION_TIERS[1:]}")
    floor = VERIFICATION_TIERS.index(min_verification) if min_verification else 0
    trusted = set(trusted_parsers)
    sha = doc.get("source_sha256")
    if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
        raise ValueError("invalid canonical source checksum")

    audit = audit_canonical(
        doc,
        trusted_parsers=trusted,
        block_scoped_codes=frozenset(block_scoped_codes),
        policy=policy,
    )
    if not audit["pass"]:
        raise ValueError("Canonical failed IDP structural audit")

    approved_pages = set(audit["quality"]["auto_publish_pages"])
    held_blocks = set(audit["quality"]["held_blocks"])
    output: list[dict] = []
    for page in doc["pages"]:
        if page["page_id"] not in approved_pages:
            continue
        after_held = False
        previous: dict | None = None
        for block in page["blocks"]:
            text = block.get("text", "")
            bbox = block.get("bbox")
            key = block.get("block_id")
            if key in held_blocks and any(
                f.get("code") in SUPERSEDED_CODES for f in block.get("review_flags") or []
            ):
                continue
            tier = block_verification(block, trusted)
            if key in held_blocks or (
                isinstance(text, str)
                and text.strip()
                and VERIFICATION_TIERS.index(tier) < floor
                and block.get("type") not in {"PageHeader", "PageFooter", "PageNumber"}
            ):
                after_held = True
                if previous is not None:
                    previous["before_held"] = True
                if key is not None and key not in held_blocks:
                    held_blocks.add(key)
                continue
            if (
                block.get("excluded")
                or block.get("retrieval_eligible") is False
                or block.get("type") in _NON_RETRIEVABLE_TYPES
                or not isinstance(text, str)
                or not text.strip()
            ):
                continue
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(bbox, (list, tuple))
                or len(bbox) != 4
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in bbox)
                or not (0 <= bbox[0] < bbox[2] and 0 <= bbox[1] < bbox[3])
            ):
                continue

            prov = block.get("provenance") or build_block_provenance(block, page)
            previous = {
                "block_id": key,
                "source_id": key,
                "text": text,
                "page": page["page_id"],
                "bbox": list(bbox),
                "region_id": prov.get("region_id"),
                "candidate_id": prov.get("candidate_id"),
                "evidence_refs": list(prov.get("evidence_refs") or []),
                "provenance": prov,
                "confidence_meta": block.get("confidence_meta"),
                "type": block.get("type"),
                "section_path": [
                    x for x in block.get("section_path") or [] if isinstance(x, str)
                ],
                "after_held": after_held,
                "before_held": False,
                "verification": tier,
            }
            output.append(previous)
            after_held = False
    return output, held_blocks


def iter_retrievable_blocks(
    canonical: dict,
    *,
    trusted_parsers: set[str] | tuple[str, ...] = (),
    block_scoped_codes: set[str] | frozenset[str] | tuple[str, ...] = (),
    policy: str | None = None,
    min_verification: str | None = None,
):
    blocks, _ = retrievable_blocks_with_held(
        canonical,
        trusted_parsers=trusted_parsers,
        block_scoped_codes=block_scoped_codes,
        policy=policy,
        min_verification=min_verification,
    )
    yield from blocks


__all__ = [
    "CANONICAL_CONTRACT_VERSION",
    "CANONICAL_VERSION",
    "PROVENANCE_VERSION",
    "SUPPORTED_CANONICAL_SCHEMAS",
    "build_block_provenance",
    "iter_retrievable_blocks",
    "normalize_canonical",
    "resolve_document_version",
    "retrievable_blocks_with_held",
]
