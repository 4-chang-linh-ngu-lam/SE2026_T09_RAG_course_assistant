"""Reporting, caching, post-OCR auto-profile normalization, and output persistence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from idp.canonical import build_canonical
from idp.config import NATIVE_TRUSTED_PARSERS, PIPELINE_VERSION, resolve_profile
from idp.evidence.fusion import enrichment_summary
from idp.input.validation import InputError
from idp.pipeline.scheduler import GLOBAL_MODEL_POOL
from idp.processing.figure import classify_page
from idp.processing.formula import incomplete_formula_reasons, normalize_text, validate_latex
from idp.processing.render import atomic_write_text
from idp.runtime.compatibility import runtime_manifest
from idp.validation.quality_gate import (
    audit_canonical,
    digital_consistency_audit,
    stamp_publish_decisions,
    validate_outputs,
)
from idp.validation.review import collect_review, write_review_queue

UNTRUSTED_AUTO_PARSERS = frozenset({
    "tesseract",
    "tesseract_ocr",
    "paddleocr_vl_gguf",
    "paddleocr_vl_primary",
    "paddleocr",
    "easyocr",
    "structured_region",
    "ocr_region_recovery",
})


def add_page_flag(
    page: dict,
    code: str,
    *,
    severity: str = "warning",
    block_id: str | None = None,
    **extra,
) -> None:
    review = page.setdefault("review", [])
    if not any(f.get("code") == code and f.get("block_id") == block_id for f in review):
        review.append({
            "page": page.get("page_id"),
            "block_id": block_id,
            "bbox": None,
            "code": code,
            "severity": severity,
            **extra,
        })


def add_block_flag(block: dict, code: str, *, severity: str = "warning", **extra) -> None:
    flags = block.setdefault("review_flags", [])
    if not any(f.get("code") == code for f in flags):
        flags.append({"code": code, "severity": severity, **extra})


def page_has_extractable_content(page: dict) -> bool:
    for block in page.get("blocks") or []:
        if block.get("excluded_from_content"):
            continue
        if (block.get("text") or "").strip():
            return True
        if block.get("latex") or block.get("table_html") or block.get("table_cells") or block.get("visual_labels"):
            return True
    return False


def scale_box(box: list[float] | tuple[float, float, float, float], sx: float, sy: float) -> list[float]:
    return [float(box[0]) * sx, float(box[1]) * sy, float(box[2]) * sx, float(box[3]) * sy]


def resolve_trusted_parsers(
    trusted_parsers: set[str] | None,
    *,
    is_marker_input: bool = False,
) -> set[str]:
    if trusted_parsers is None:
        return set() if is_marker_input else set(NATIVE_TRUSTED_PARSERS)
    return {p for p in trusted_parsers if p not in UNTRUSTED_AUTO_PARSERS}


def copy_cached_artifacts(cached_canonical: Path, out_dir: Path) -> dict | None:
    cached_dir = cached_canonical.parent.resolve()
    target_dir = out_dir.resolve()
    report_file = cached_dir / "report.json"
    if not report_file.is_file():
        return None
    if cached_dir != target_dir:
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "canonical.json",
            "ingestion_report.json",
            "report.json",
            "manifest.json",
            "audit_report.json",
            "markdown.md",
            "review_queue.jsonl",
        ):
            src = cached_dir / name
            if src.is_file():
                shutil.copy2(src, target_dir / name)
        for sub in ("pages", "assets"):
            src_sub = cached_dir / sub
            if src_sub.is_dir():
                shutil.copytree(src_sub, target_dir / sub, dirs_exist_ok=True)
    report = json.loads((target_dir / "report.json").read_text(encoding="utf-8"))
    report["canonical_path"] = str(target_dir / "canonical.json")
    report["markdown_path"] = str(target_dir / "markdown.md")
    report["review_queue_path"] = str(target_dir / "review_queue.jsonl")
    report["ingestion_report_path"] = str(target_dir / "ingestion_report.json")
    report["cache_hit"] = True
    return report


def write_page_files(out_dir: Path, page: dict, markdown_text: str) -> None:
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pid = int(page["page_id"])
    atomic_write_text(pages_dir / f"p{pid:04d}.json", json.dumps(page, ensure_ascii=False, indent=1))
    atomic_write_text(pages_dir / f"p{pid:04d}.md", markdown_text)


def maybe_upgrade_auto_profile(
    pages: list[dict],
    *,
    requested_profile: str,
    current_profile,
):
    """Resolve profile='auto' after OCR/extraction when pre-OCR text was empty or sparse."""
    if (requested_profile or "auto").strip().lower() != "auto":
        return current_profile
    if current_profile.name == "math_vi":
        return current_profile
    sample = "\n".join(
        (b.get("text") or "").strip()
        for page in pages[:5]
        for b in page.get("blocks") or []
        if not b.get("excluded_from_content") and (b.get("text") or "").strip()
    )
    detected = resolve_profile("auto", sample)
    if detected.name == current_profile.name:
        return current_profile
    for page in pages:
        page["profile"] = detected.name
        for block in page.get("blocks") or []:
            if block.get("block_type") == "Equation" or not (block.get("text") or "").strip():
                continue
            fixed, _ = normalize_text(block["text"], detected)
            if fixed != block["text"]:
                block["text"] = fixed
                if block.get("block_type") == "SectionHeader":
                    existing_md = str(block.get("markdown") or "")
                    prefix = existing_md.split(" ", 1)[0] if existing_md.lstrip().startswith("#") else "##"
                    block["markdown"] = f"{prefix} {fixed}".strip()
                elif block.get("markdown") and block.get("block_type") == "Text":
                    block["markdown"] = fixed
    return detected


def finalize_and_write_outputs(
    *,
    pages: list[dict],
    source: Path,
    out: Path,
    source_sha256: str,
    file_kind: str,
    source_type: str,
    resolved_profile,
    ocr_lang: str | None,
    page_decisions: list[dict],
    page_manifest: list[dict],
    content_loss: dict[str, Any],
    telemetry: dict[str, Any],
    trusted_parsers: set[str] | None,
    is_marker_input: bool,
    source_acl: dict | None,
    source_metadata: dict | None,
    max_chars: int,
    elapsed: float,
    markdown_for_page_fn,
    calibrator_registry=None,
) -> tuple[dict, dict]:
    source_label_map = {
        "pdf_text": "pymupdf",
        "pdf_hybrid": "pymupdf",
        "docx": "pandoc",
        "txt": "text",
        "markdown": "markdown",
        "html": "html",
        "csv": "csv",
        "xlsx": "openpyxl",
        "pptx": "python-pptx",
        "email": "email",
    }
    default_native_source = source_label_map.get(source_type) if not is_marker_input else None
    pages.sort(key=lambda p: p["page_id"])
    total_chars = 0
    for page in pages:
        page.setdefault("profile", resolved_profile.name)
        page.setdefault("classification", classify_page(page.get("blocks") or []))
        page.setdefault("processing_status", "ok")
        if ocr_lang and page.get("ocr_language") is None and page.get("parser") != "pymupdf":
            page["ocr_language"] = ocr_lang
        for idx, block in enumerate(page.get("blocks") or []):
            block["order"] = idx
            block["page"] = page["page_id"]
            if default_native_source is not None and not block.get("source"):
                block["source"] = default_native_source
            total_chars += len(block.get("text") or "")
            if block.get("latex"):
                validations = [validate_latex(value).as_dict() for value in block["latex"]]
                block["latex_validation"] = validations
                if not all(item["valid"] for item in validations):
                    add_block_flag(block, "LATEX_INVALID")
                    add_page_flag(page, "LATEX_INVALID", block_id=block.get("block_id"))
                if resolved_profile.math_formula_checks:
                    incomplete = incomplete_formula_reasons(block["latex"])
                    if incomplete:
                        add_block_flag(block, "FORMULA_INCOMPLETE", reasons=incomplete)
                        add_page_flag(
                            page,
                            "FORMULA_INCOMPLETE",
                            block_id=block.get("block_id"),
                            reasons=incomplete,
                        )
        page_md = markdown_for_page_fn(page.get("blocks") or [])
        page["markdown"] = page_md
        write_page_files(out, page, page_md)

    if total_chars > max_chars:
        raise InputError(
            "TEXT_LIMIT_EXCEEDED",
            f"document has {total_chars} text chars; limit is {max_chars}",
        )
    truncated_tables = sum(
        1
        for p in pages
        for b in p.get("blocks") or []
        if any(f.get("code") == "TABLE_TRUNCATED" for f in b.get("review_flags") or [])
    )
    if truncated_tables:
        content_loss["truncated_tables"] = truncated_tables

    all_markdown = "\n\n---\n\n".join(
        md for page in pages if (md := markdown_for_page_fn(page.get("blocks") or []))
    )
    markdown_path = out / "markdown.md"
    atomic_write_text(markdown_path, all_markdown + ("\n" if all_markdown else ""))

    effective_trusted = resolve_trusted_parsers(trusted_parsers, is_marker_input=is_marker_input)
    expected_pages = [p["page_id"] for p in pages]
    if not page_manifest:
        page_manifest = [
            {
                "page_id": p["page_id"],
                "status": p.get("processing_status"),
                "parser": p.get("parser"),
                "route": (p.get("page_route") or {}).get("route"),
            }
            for p in pages
        ]
    parser_meta = {
        "name": "adaptive_hybrid",
        "version": PIPELINE_VERSION,
        "source_type": source_type,
        "trusted": bool(effective_trusted),
    }
    runtime_info = runtime_manifest(include_external_binaries=False)
    canonical = build_canonical(
        pages,
        source,
        source_sha256,
        PIPELINE_VERSION,
        parser=parser_meta,
        page_manifest=page_manifest,
        expected_pages=expected_pages,
        profile=resolved_profile.name,
        source_acl=source_acl,
        source_metadata=source_metadata,
        runtime_info=runtime_info,
        calibrator_registry=calibrator_registry,
    )
    audit = audit_canonical(
        canonical,
        trusted_parsers=effective_trusted,
        profile=resolved_profile.name,
    )
    stamp_publish_decisions(canonical, audit)

    review_items = collect_review(pages, audit["quality"].get("page_quality"))
    canonical_path = out / "canonical.json"
    atomic_write_text(canonical_path, json.dumps(canonical, ensure_ascii=False, indent=1))
    ingestion_report_path = out / "ingestion_report.json"
    atomic_write_text(ingestion_report_path, json.dumps(audit, ensure_ascii=False, indent=1))
    review_queue_path = write_review_queue(out, review_items)

    require_bbox = file_kind in {"pdf", "image"} and not is_marker_input
    output_errors = validate_outputs(out, pages, require_bbox=require_bbox)
    consistency = digital_consistency_audit(pages, content_loss, source_type, output_errors)
    audit_report_path = out / "audit_report.json"
    atomic_write_text(audit_report_path, json.dumps(consistency, ensure_ascii=False, indent=1))

    page_count = len(pages)
    telemetry_out = {
        "page_routes": dict(telemetry["page_routes"]),
        "region_actions": dict(telemetry["region_actions"]),
        "render_count": telemetry["render_count"],
        "rerender_count": telemetry["rerender_count"],
        "ocr_calls": telemetry["ocr_calls"],
        "vlm_calls": telemetry["vlm_calls"],
        "vlm_skipped_early_exit": telemetry["vlm_skipped_early_exit"],
        "vlm_budget_skipped": telemetry["vlm_budget_skipped"],
        "model_pool": GLOBAL_MODEL_POOL.stats(),
    }
    report = {
        "schema_version": canonical["schema_version"],
        "canonical_contract_version": canonical.get("canonical_contract_version"),
        "pipeline_version": PIPELINE_VERSION,
        "runtime_manifest": runtime_info,
        "doc_id": source_sha256,
        "document_version": canonical.get("document_version"),
        "source": str(source),
        "source_sha256": source_sha256,
        "file_type": file_kind,
        "source_type": source_type,
        "profile": resolved_profile.name,
        "language": ocr_lang,
        "parser": parser_meta,
        "pages": page_count,
        "blocks": sum(len(p.get("blocks") or []) for p in pages),
        "review_items": len(review_items),
        "failed_pages": [],
        "canonical_path": str(canonical_path),
        "markdown_path": str(markdown_path),
        "review_queue_path": str(review_queue_path),
        "ingestion_report_path": str(ingestion_report_path),
        "audit_report_path": str(audit_report_path),
        "ingestion_pass": audit["pass"],
        "ingestion_quality_pass": audit["quality_pass"],
        "ingestion_review_assisted_pass": audit["review_assisted_pass"],
        "ingestion_auto_publish_pass": audit["auto_publish_pass"],
        "output_validation_errors": output_errors,
        "digital_consistency": consistency,
        "structured_enrichment": enrichment_summary(pages),
        "page_routes": telemetry_out["page_routes"],
        "region_actions": telemetry_out["region_actions"],
        "page_decisions": page_decisions,
        "telemetry": telemetry_out,
        "elapsed_seconds": round(elapsed, 4),
        "page_latency_ms": round((elapsed * 1000.0) / max(1, page_count), 2),
    }
    manifest = {
        "doc_id": source_sha256,
        "source": str(source),
        "source_sha256": source_sha256,
        "pipeline_version": PIPELINE_VERSION,
        "runtime_manifest": runtime_info,
        "pages": page_manifest,
        "telemetry": telemetry_out,
    }
    atomic_write_text(out / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    atomic_write_text(out / "report.json", json.dumps(report, ensure_ascii=False, indent=1))
    return report, canonical
