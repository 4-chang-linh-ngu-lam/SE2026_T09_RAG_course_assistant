import hashlib
import json
import os
import shlex
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .canonical import audit_canonical, build_canonical
from .chunk import build_chunks, build_document
from .questions import analyze_questions
from .extract import extract_page
from .filetypes import InputError, InputLimits
from .parsers import detect_parser, merge_parser_specs
from .normalize import MATH_RE, TAG_RE
from .preprocess import analyze_page, write_preprocess_metadata
from .review_report import write_review_html
from .validate_output import validate_outputs
from .verifier import needs_verification, verify_page
from .enrichment import enrichment_summary
from .export_audit import audit_chunk_export
import html as html_lib
import re

PIPELINE_VERSION = "idp-poc-0.49"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _marker_source(marker_path: str | Path) -> str:
    try:
        data = json.loads(Path(marker_path).read_text(encoding="utf-8"))
        metadata = data.get("metadata") or {}
        return metadata.get("engine") or "marker"
    except Exception:
        return "marker"


def _fallback_meta(marker_path: str | Path) -> dict | None:
    path = Path(marker_path)
    sidecar = path.with_name(path.name + ".fallback")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return {"engine": "unknown"}


def _extract_charts(
    page: dict,
    command: str,
    timeout: int,
    out_dir: Path,
) -> None:
    """Run an operator-supplied chart model on flagged chart crops.

    The command receives IDP_CHART_IMAGE and IDP_CHART_OUTPUT and must write
    JSON/CSV there. The output is attached for review; it does not bypass
    auto-publish gates.
    """
    argv = shlex.split(command, posix=(os.name != "nt"))
    for block in page.get("blocks") or []:
        codes = {flag.get("code") for flag in block.get("review_flags") or []}
        if "CHART_NOT_EXTRACTED" not in codes:
            continue
        crop = block.get("block_crop_path") or block.get("crop_path")
        if not crop or not Path(crop).exists():
            continue
        target = out_dir / "charts" / f"{block['block_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["IDP_CHART_IMAGE"] = str(crop)
        env["IDP_CHART_OUTPUT"] = str(target)
        env["IDP_PAGE_ID"] = str(page["page_id"])
        env["IDP_BLOCK_ID"] = str(block["block_id"])
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                timeout=timeout, env=env,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout)[-500:])
            if target.exists():
                data = json.loads(target.read_text(encoding="utf-8"))
            else:
                data = json.loads(proc.stdout)
            block["chart_data"] = data
            block["review_flags"].append({
                "code": "CHART_EXTRACTED",
                "severity": "info",
                "output": str(target),
            })
        except Exception as exc:
            block["review_flags"].append({
                "code": "CHART_EXTRACTION_FAILED",
                "severity": "warning",
                "reason": str(exc)[:300],
            })


def _describe_figures(
    page: dict,
    command: str,
    timeout: int,
    out_dir: Path,
    revision: str | None = None,
) -> None:
    argv = command if os.name == "nt" else shlex.split(command)
    for block in page.get("blocks") or []:
        if block.get("block_type") not in {"Picture", "Diagram", "Chart"}:
            continue
        if block.get("description") or block.get("excluded_from_content") or block.get("figure_kind") == "decorative":
            continue
        crop = block.get("block_crop_path") or block.get("crop_path")
        if not crop or not Path(crop).exists():
            continue
        target = out_dir / "figures" / f"{block['block_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["IDP_FIGURE_IMAGE"] = str(crop)
        env["IDP_FIGURE_OUTPUT"] = str(target)
        env["IDP_PAGE_ID"] = str(page["page_id"])
        env["IDP_BLOCK_ID"] = str(block["block_id"])
        env.update(IDP_REGION_IMAGE=str(crop), IDP_REGION_OUTPUT=str(target), IDP_REGION_KIND=block["block_type"])
        target.unlink(missing_ok=True)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                timeout=timeout, env=env,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout)[-500:])
            if target.exists():
                if target.stat().st_size > 2_000_000:
                    raise ValueError("figure response exceeds byte limit")
                data = json.loads(target.read_text(encoding="utf-8"))
            else:
                data = json.loads(proc.stdout)
            if isinstance(data, str):
                description = data.strip()
            else:
                description = (
                    data.get("description") or data.get("caption")
                    or data.get("alt_text") or data.get("text") or ""
                )
            if (not isinstance(description, str) or not description.strip() or len(description) > 32768
                    or any(s in description.lower() for s in ("<unreadable>", "[unreadable]"))):
                raise RuntimeError("empty figure description")
            block["description"] = description.strip()
            if isinstance(data, dict) and isinstance(data.get("visual_facts"), dict):
                block["visual_facts"] = data["visual_facts"]
            block["figure_description_provenance"] = {"producer": "external_figure_command",
                "revision": revision, "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                "crop_sha256": sha256_file(crop), "source_caption_preserved": True}
            block["review_flags"].append({
                "code": "FIGURE_DESCRIPTION_REVIEW",
                "severity": "warning",
                "output": str(target),
            })
        except Exception as exc:
            block["review_flags"].append({
                "code": "FIGURE_DESCRIPTION_FAILED",
                "severity": "warning",
                "reason": str(exc)[:300],
            })


def collect_review(pages: list[dict], page_quality: list[dict] | None = None) -> list[dict]:
    review = []
    for page in pages:
        for item in page.get("review", []):
            if item.get("block_id") is None:
                review.append(item)
        for block in page["blocks"]:
            for flag in block.get("review_flags") or []:
                if flag.get("severity") in {"warning", "error"}:
                    review.append({
                        "page": page["page_id"],
                        "block_id": block["block_id"],
                        "block_type": block["block_type"],
                        "bbox": block["bbox"],
                        "block_crop_path": block.get("block_crop_path"),
                        **flag,
                    })
    for item in page_quality or []:
        if not item.get("publish_authorized") and item.get("status") != "blank":
            review.append({
                "page": item["page_id"], "block_id": None, "block_type": "Page",
                "bbox": None, "code": "PUBLISH_NOT_AUTHORIZED", "severity": "warning",
                "reason": "source has no eligible recognition score or explicit trust",
            })
    return review


def pdf_page_count(pdf_path: str | Path) -> int:
    try:
        # Only the ASCII structural field is needed. Metadata may contain UTF-8
        # curly quotes/diacritics that cannot be decoded by Windows cp1252.
        out = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, timeout=30)
        match = re.search(rb"^Pages:\s*(\d+)\s*$", out.stdout, re.M) if out.returncode == 0 else None
        if match and int(match[1]) > 0:
            return int(match[1])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError(
                "cannot determine PDF page count: install pdfinfo or pymupdf"
            ) from exc
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def ensure_page_image(pdf_path: str | Path, page_id: int, out_path: Path, dpi: int = 300) -> Path:
    provenance = {"source_sha256": sha256_file(pdf_path), "page_id": page_id, "dpi": dpi}
    sidecar = out_path.with_name(out_path.name + ".source.json")
    if out_path.exists() and sidecar.exists():
        try:
            if json.loads(sidecar.read_text(encoding="utf-8")) == provenance:
                return out_path
        except (ValueError, OSError):
            pass
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = out_path.with_suffix("")
    subprocess.run([
        "pdftoppm", "-f", str(page_id), "-l", str(page_id), "-png",
        "-r", str(dpi), "-singlefile", str(pdf_path), str(base),
    ], check=True)
    _atomic_write(sidecar, json.dumps(provenance))
    return out_path


def _block_markdown(block: dict) -> str:
    btype = block["block_type"]
    if btype == "SectionHeader":
        title = (block.get("markdown") or block.get("text") or "").strip()
        return f"## {title}"
    if block.get("markdown") and btype not in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}:
        return block["markdown"].strip()
    if btype in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}:
        caption = block.get("caption") or block.get("text") or ""
        assets = block.get("asset_paths") or []
        image = f"![]({assets[0]})" if assets else ""
        return "\n\n".join(x for x in [image, f"*{caption}*" if caption else ""] if x)
    return (block.get("text") or "").strip()


def page_markdown(page: dict) -> str:
    lines = []
    for block in page["blocks"]:
        if block.get("excluded_from_content"):
            continue
        if block["block_type"] == "Caption":
            continue
        md = _block_markdown(block)
        if md.strip():
            lines.append(md.strip())
    return "\n\n".join(lines) + "\n"


def run_pipeline(
    pdf_path: str | Path,
    page_ids: list[int],
    marker_json_by_page: dict[int, str | Path],
    page_images_by_page: dict[int, str | Path],
    out_dir: str | Path,
    dpi: int = 300,
    resume: bool = False,
    page_review_by_page: dict[int, list[dict]] | None = None,
    skip_text_candidate_pages: set[int] | None = None,
    ingestion_only: bool = False,
    verify_cmd: str | None = None,
    verify_timeout: int = 600,
    verify_max_pages: int = 0,
    trusted_parsers: set[str] | None = None,
    profile: str = "general",
    language: str | None = None,
    limits: InputLimits | None = None,
    chart_cmd: str | None = None,
    chart_timeout: int = 120,
    figure_cmd: str | None = None,
    figure_timeout: int = 120,
    figure_revision: str | None = None,
    workers: int = 1,
    source_acl: dict | None = None,
    source_metadata: dict | None = None,
    original_source_path: str | Path | None = None,
    region_enricher=None,
) -> dict:
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    if resume and region_enricher and not region_enricher.cacheable:
        raise InputError("STRUCTURED_IDENTITY_REQUIRED", "all structured readers need stable identities for resume")
    out_dir.mkdir(parents=True, exist_ok=True)
    limits = limits or InputLimits()
    if len(page_ids) > limits.max_pages:
        raise InputError(
            "PAGE_LIMIT_EXCEEDED",
            f"request has {len(page_ids)} pages; limit is {limits.max_pages}",
        )
    run_id = uuid.uuid4().hex
    started_at = _utc_now()
    pages = []
    page_manifest = []
    failed_pages = []
    source_path = Path(original_source_path) if original_source_path is not None else pdf_path
    source_sha256 = sha256_file(source_path)

    def _process_one(page_id):
        image_path = page_images_by_page[page_id]
        marker_path = marker_json_by_page[page_id]
        image_sha = sha256_file(image_path)
        marker_sha = sha256_file(marker_path)
        cache_path = out_dir / "pages" / f"p{page_id:04d}.json"
        page = None
        was_cached = False
        extraction_config = {
            "source_sha256": source_sha256,
            "profile": profile,
            "language": language,
            "dpi": dpi,
            "run_text_candidate": not (
                skip_text_candidate_pages and page_id in skip_text_candidate_pages
            ),
            "chart_cmd": chart_cmd,
            "chart_timeout": chart_timeout,
            "figure_cmd": figure_cmd,
            "figure_timeout": figure_timeout,
            "figure_revision": figure_revision,
            "structured_enrichment": region_enricher.identity if region_enricher else None,
        }
        if (resume and cache_path.exists() and (not figure_cmd or figure_revision)
                and (not region_enricher or getattr(region_enricher, "cacheable", False))):
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if (
                    cached.get("source_image_sha256") == image_sha
                    and cached.get("marker_json_sha256") == marker_sha
                    and cached.get("pipeline_version") == PIPELINE_VERSION
                    and cached.get("extraction_config") == extraction_config
                ):
                    page = cached
                    was_cached = True
            except Exception:
                page = None
        try:
            if page is None:
                pre = analyze_page(image_path)
                write_preprocess_metadata(
                    pre, out_dir / "pages" / f"p{page_id:04d}_preprocess.json"
                )
                page = extract_page(
                    page_id=page_id,
                    page_image_path=image_path,
                    marker_json_path=marker_path,
                    out_dir=out_dir,
                    run_text_candidate=not (
                        skip_text_candidate_pages
                        and page_id in skip_text_candidate_pages
                    ),
                    source_label=_marker_source(marker_path),
                    profile=profile,
                    language=language,
                )
                page["preprocessing"] = pre
                page["source_image_sha256"] = image_sha
                page["marker_json_sha256"] = marker_sha
                page["pipeline_version"] = PIPELINE_VERSION
                for key, code in (
                    ("needs_deskew", "PAGE_NEEDS_DESKEW"),
                    ("low_contrast", "PAGE_LOW_CONTRAST"),
                    ("faint_content_only", "PAGE_FAINT_CONTENT_REVIEW"),
                    ("blurry", "PAGE_BLURRY"),
                ):
                    if pre.get(key):
                        page["review"].append({
                            "page": page_id,
                            "block_id": None,
                            "block_type": "Page",
                            "bbox": None,
                            "code": code,
                            "severity": "warning",
                        })
            for flag in (page_review_by_page or {}).get(page_id, []):
                if not any(
                    existing.get("code") == flag.get("code")
                    for existing in page.get("review", [])
                ):
                    page.setdefault("review", []).append({
                        "page": page_id,
                        "block_id": None,
                        "block_type": "Page",
                        "bbox": None,
                        **flag,
                    })
            marker_metadata = json.loads(Path(marker_path).read_text("utf-8")).get("metadata") or {}
            if marker_metadata.get("render_provenance"):
                page["render_provenance"] = dict(marker_metadata["render_provenance"])
            if marker_metadata.get("quality_source"):
                page["quality_source"] = dict(marker_metadata["quality_source"])
                retained = sum(bool(b.get("source_evidence")) for b in page["blocks"])
                page["quality_source"]["canonical_regions"] = retained
                page["quality_source"]["source_regions_retained"] = retained == page["quality_source"].get("source_regions")
                if not page["quality_source"]["source_regions_retained"]:
                    if not any(f.get("code") == "QUALITY_REGION_LOSS" for f in page.get("review", [])):
                        page.setdefault("review", []).append({"page": page_id, "block_id": None,
                            "code": "QUALITY_REGION_LOSS", "severity": "error"})
                if page["quality_source"].get("recognition_completeness") != "verified":
                    if not any(f.get("code") == "QUALITY_COMPLETENESS_UNVERIFIED" for f in page.get("review", [])):
                        page.setdefault("review", []).append({"page": page_id, "block_id": None,
                            "code": "QUALITY_COMPLETENESS_UNVERIFIED", "severity": "warning"})
            if marker_metadata.get("review_code") == "FALLBACK_ENGINE_REVIEW":
                if not any(f.get("code") == "FALLBACK_ENGINE_REVIEW" for f in page.get("review", [])):
                    page.setdefault("review", []).append({
                        "page": page_id, "block_id": None, "block_type": "Page", "bbox": None,
                        "code": "FALLBACK_ENGINE_REVIEW", "severity": "warning",
                    })
            recovery = marker_metadata.get("region_recovery")
            if recovery:
                page["region_recovery"] = recovery
                for flag in recovery.get("flags", []):
                    if not any(f.get("code") == flag.get("code") for f in page.get("review", [])):
                        page.setdefault("review", []).append({"page": page_id, "block_id": None, "block_type": "Page", "bbox": None, **flag})
            if region_enricher and not was_cached:
                region_enricher.enrich_page(page, out_dir, image_path)
            page["processing_status"] = "ok"
            has_content = any(
                (b.get("text") or "").strip()
                or b.get("latex")
                or b.get("block_type") in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}
                for b in page["blocks"]
            )
            if not has_content:
                if page.get("preprocessing", {}).get("blank"):
                    page["processing_status"] = "blank"
                    page["classification"]["page_type"] = "blank"
                    page["review"] = []
                else:
                    page["processing_status"] = "layout_failed"
                    page["review"].append({
                        "page": page_id,
                        "block_id": None,
                        "block_type": "Page",
                        "bbox": None,
                        "code": "PAGE_LAYOUT_FAILED",
                        "severity": "error",
                    })
            if chart_cmd:
                _extract_charts(page, chart_cmd, chart_timeout, out_dir)
            if figure_cmd:
                _describe_figures(page, figure_cmd, figure_timeout, out_dir, revision=figure_revision)
            page["extraction_config"] = extraction_config
            manifest_entry = {
                "page_id": page_id,
                "status": "ok",
                "source_image_sha256": image_sha,
                "marker_json_sha256": marker_sha,
                "cached": was_cached,
            }
            return page, manifest_entry, None
        except Exception as exc:
            failed_entry = {"page": page_id, "error": str(exc)}
            manifest_entry = {
                "page_id": page_id,
                "status": "failed",
                "error": str(exc),
                "source_image_sha256": image_sha,
                "marker_json_sha256": marker_sha,
            }
            return None, manifest_entry, failed_entry

    if workers <= 1:
        for page_id in page_ids:
            page, manifest_entry, failed_entry = _process_one(page_id)
            if page is not None:
                pages.append(page)
            page_manifest.append(manifest_entry)
            if failed_entry is not None:
                failed_pages.append(failed_entry)
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for page, manifest_entry, failed_entry in pool.map(
                _process_one, page_ids
            ):
                if page is not None:
                    pages.append(page)
                page_manifest.append(manifest_entry)
                if failed_entry is not None:
                    failed_pages.append(failed_entry)
    total_chars = sum(
        len(block.get("text") or "")
        for page in pages for block in page.get("blocks") or []
    )
    if total_chars > limits.max_chars:
        raise InputError(
            "TEXT_LIMIT_EXCEEDED",
            f"document has {total_chars} text chars; limit is {limits.max_chars}",
        )
    parser_specs = [
        detect_parser(
            marker_json_by_page[page["page_id"]],
            _fallback_meta(marker_json_by_page[page["page_id"]]),
        )
        for page in pages
    ]
    verification_errors = []
    verified_pages = []
    analyze_questions(pages)
    if verify_cmd:
        candidates = [page for page in pages if needs_verification(page)]
        if verify_max_pages:
            candidates = candidates[:verify_max_pages]
        page_index = {page["page_id"]: index for index, page in enumerate(pages)}
        for original in candidates:
            page_id = original["page_id"]
            index = page_index[page_id]
            original_json = out_dir / "verify" / f"p{page_id:04d}.json"
            _atomic_write(original_json, json.dumps(original, ensure_ascii=False))
            try:
                verified_marker, verifier_meta = verify_page(
                    verify_cmd,
                    page_id,
                    page_images_by_page[page_id],
                    original_json,
                    out_dir / "verify" / f"p{page_id:04d}",
                    timeout=verify_timeout,
                )
                verified = extract_page(
                    page_id=page_id,
                    page_image_path=page_images_by_page[page_id],
                    marker_json_path=verified_marker,
                    out_dir=out_dir,
                    run_text_candidate=False,
                    source_label=verifier_meta.get("engine") or "verifier",
                    profile=profile,
                    language=language,
                )
                verified["preprocessing"] = original.get("preprocessing") or analyze_page(
                    page_images_by_page[page_id]
                )
                verified["source_image_sha256"] = original.get("source_image_sha256")
                verified["marker_json_sha256"] = sha256_file(verified_marker)
                verified["pipeline_version"] = PIPELINE_VERSION
                verified["extraction_config"] = original.get("extraction_config")
                verified["verification"] = {
                    "engine": verifier_meta.get("engine") or "verifier",
                    "original_status": original.get("processing_status"),
                    "original_source": original.get("verification", {}).get(
                        "original_source", "marker"
                    ),
                }
                for flag in (page_review_by_page or {}).get(page_id, []):
                    if not any(
                        existing.get("code") == flag.get("code")
                        for existing in verified.get("review", [])
                    ):
                        verified.setdefault("review", []).append({
                            "page": page_id,
                            "block_id": None,
                            "block_type": "Page",
                            "bbox": None,
                            **flag,
                        })
                verified.setdefault("review", []).append({
                    "page": page_id,
                    "block_id": None,
                    "block_type": "Page",
                    "bbox": None,
                    "code": "VERIFIED_BY",
                    "severity": "info",
                    "engine": verified["verification"]["engine"],
                })
                verified["processing_status"] = "ok"
                has_content = any(
                    (block.get("text") or "").strip()
                    or block.get("latex")
                    or block.get("block_type") in {
                        "Diagram", "Picture", "PictureGroup", "Table", "Chart",
                    }
                    for block in verified.get("blocks") or []
                )
                if not has_content:
                    if verified.get("preprocessing", {}).get("blank"):
                        verified["processing_status"] = "blank"
                    else:
                        verified["processing_status"] = "layout_failed"
                        verified["review"].append({
                            "page": page_id,
                            "block_id": None,
                            "block_type": "Page",
                            "bbox": None,
                            "code": "PAGE_LAYOUT_FAILED",
                            "severity": "error",
                        })
                pages[index] = verified
                parser_specs[index] = detect_parser(verified_marker, verifier_meta)
                for entry in page_manifest:
                    if entry.get("page_id") == page_id:
                        entry["marker_json_sha256"] = verified["marker_json_sha256"]
                        entry["verification_engine"] = verified["verification"]["engine"]
                verified_pages.append(page_id)
            except Exception as exc:
                verification_errors.append({"page": page_id, "error": str(exc)[:1000]})
                original.setdefault("review", []).append({
                    "page": page_id,
                    "block_id": None,
                    "block_type": "Page",
                    "bbox": None,
                    "code": "VERIFIER_FAILED",
                    "severity": "warning",
                })

    for page, spec in zip(pages, parser_specs):
        page["parser"] = spec.as_dict()
    parser = merge_parser_specs(parser_specs)
    page_profiles = Counter(page.get("profile", "general") for page in pages)
    document_profile = (
        page_profiles.most_common(1)[0][0] if page_profiles else (profile or "general")
    )
    canonical = build_canonical(
        pages=pages,
        source_path=source_path,
        source_sha256=source_sha256,
        pipeline_version=PIPELINE_VERSION,
        parser=parser,
        page_manifest=page_manifest,
        failed_pages=failed_pages,
        expected_pages=page_ids,
        profile=document_profile,
        source_acl=source_acl,
        source_metadata=source_metadata,
    )
    ingestion_report = audit_canonical(
        canonical,
        trusted_parsers=trusted_parsers,
        profile=document_profile,
    )
    if ingestion_only:
        chunks = []
        document = {}
    else:
        chunks = build_chunks(
            pages,
            publishable_pages=(
                set(ingestion_report["quality"]["auto_publish_pages"])
                if ingestion_report["pass"] else set()
            ),
        )
        document = build_document(pages, chunks)

    export_audit = audit_chunk_export(pages, chunks) if not ingestion_only else None
    if export_audit and not export_audit["pass"]:
        affected = {f["page"] for f in export_audit["failures"]}
        for chunk in chunks:
            if affected & set(chunk.get("pages", [])):
                chunk["review_flags"].append({"block_id": None, "code": "EXPORT_CONTENT_LOSS", "severity": "error"})
                chunk.update(publishable=False, review_required=True)
    review = collect_review(pages, ingestion_report["quality"]["page_quality"])
    formula_total = sum(len(b.get("latex") or []) for p in pages for b in p["blocks"])
    formula_valid = 0
    for page in pages:
        for block in page["blocks"]:
            for v in block.get("latex_validation", []):
                if v.get("valid"):
                    formula_valid += 1
    figure_blocks = [
        b for p in pages for b in p["blocks"]
        if b["block_type"] in {"Diagram", "Picture", "PictureGroup", "Table", "Chart"}
    ]
    content_figures = [b for b in figure_blocks if b.get("figure_kind") == "content"]
    decorative_figures = [b for b in figure_blocks if b.get("figure_kind") == "decorative"]
    captioned = [b for b in content_figures if b.get("caption")]
    normalized = sum(
        len(b.get("normalization_changes") or [])
        for p in pages for b in p["blocks"]
    )
    block_crops = sum(
        1 for p in pages for b in p["blocks"] if b.get("block_crop_path")
    )
    formula_crops = sum(
        len(b.get("formula_crops") or []) for p in pages for b in p["blocks"]
    )
    disagreements = sum(
        1 for p in pages for b in p["blocks"]
        if any(f["code"] == "TEXT_DISAGREEMENT" for f in b.get("review_flags") or [])
    )
    diacritic_variants = sum(
        1 for p in pages for b in p["blocks"]
        if any(f["code"] == "TEXT_DIACRITIC_VARIANT" for f in b.get("review_flags") or [])
    )
    text_chunks = [c for c in chunks if c.get("content_kind") == "text"]
    figure_chunks = [c for c in chunks if c.get("content_kind") == "figure"]
    formula_chunks = [c for c in chunks if c.get("content_kind") == "formula"]
    math_review_codes = {
        "FORMULA_SEMANTIC_REVIEW", "FORMULA_FRAGMENT",
        "MATH_TEXT_INTEGRITY", "FORMULA_PLACEHOLDER", "FORMULA_ALIGNMENT_REVIEW",
        "LATEX_INVALID", "FORMULA_INCOMPLETE",
        "FORMULA_SIGN_REVIEW", "FORMULA_SIGN_CORRECTED",
        "MISSING_NUMERIC_CONTEXT",
    }
    text_review = [
        c for c in text_chunks
        if c.get("review_required")
        and any(f.get("code") not in math_review_codes for f in c.get("review_flags", []))
    ]
    math_review = [
        c for c in chunks
        if any(f.get("code") in math_review_codes for f in c.get("review_flags", []))
    ]
    figure_review = [c for c in figure_chunks if c.get("review_required")]
    formula_review = [c for c in formula_chunks if c.get("review_required")]
    formula_semantic_flags = sum(
        1 for p in pages for b in p["blocks"]
        if any(f["code"] == "FORMULA_SEMANTIC_REVIEW" for f in b.get("review_flags") or [])
    )
    document_type = document_profile

    report = {
        "pipeline_version": PIPELINE_VERSION,
        "structured_enrichment": enrichment_summary(pages),
        "run_id": run_id,
        "document_type": document_type,
        "profile": document_profile,
        "language": language,
        "ingestion_pass": ingestion_report["pass"],
        "ingestion_quality_pass": ingestion_report.get("quality_pass"),
        "ingestion_review_assisted_pass": ingestion_report.get("review_assisted_pass"),
        "ingestion_production_pass": ingestion_report.get("production_pass"),
        "ingestion_auto_publish_pass": ingestion_report.get("auto_publish_pass"),
        "ingestion_quality_certified": ingestion_report.get("quality_certified"),
        "ingestion_checks": {k: v["pass"] for k, v in ingestion_report["checks"].items()},
        "ingestion_quality": ingestion_report["quality"],
        "canonical_version": canonical["schema_version"],
        "parser": parser,
        "requested_pages": len(page_ids),
        "pages": len(pages),
        "pages_without_content": sum(
            1 for p in pages if p.get("processing_status") == "layout_failed"
        ),
        "fallback_pages": sorted(
            p["page_id"] for p in pages
            if any(
                f.get("code") == "FALLBACK_ENGINE_REVIEW"
                for f in p.get("review", [])
            )
        ),
        "failed_pages": failed_pages,
        "blocks": sum(len(p["blocks"]) for p in pages),
        "figures": len(figure_blocks),
        "content_figures": len(content_figures),
        "decorative_figures": len(decorative_figures),
        "content_figures_with_caption": len(captioned),
        "figure_caption_rate": round(len(captioned) / max(1, len(content_figures)), 4),
        "formulas": formula_total,
        "formulas_valid": formula_valid,
        "formula_valid_rate": round(formula_valid / max(1, formula_total), 4),
        "normalization_changes": normalized,
        "block_crops": block_crops,
        "formula_crops": formula_crops,
        "text_disagreements": disagreements,
        "text_diacritic_variants": diacritic_variants,
        "chunks": len(chunks),
        "text_chunks": len(text_chunks),
        "text_review_required_chunks": len(text_review),
        "text_review_rate": round(len(text_review) / max(1, len(text_chunks)), 4),
        "math_review_required_chunks": len(math_review),
        "formula_semantic_review_chunks": sum(
            1 for c in chunks
            if any(f.get("code") == "FORMULA_SEMANTIC_REVIEW" for f in c.get("review_flags", []))
        ),
        "figure_chunks": len(figure_chunks),
        "figure_review_required_chunks": len(figure_review),
        "formula_chunks": len(formula_chunks),
        "formula_review_required_chunks": len(formula_review),
        "overall_review_rate": round(
            sum(1 for c in chunks if c.get("review_required")) / max(1, len(chunks)), 4
        ),
        "formula_semantic_flags": formula_semantic_flags,
        "verified_pages": verified_pages,
        "verification_errors": verification_errors,
        "publishable_chunks": sum(1 for c in chunks if c["publishable"]),
        "review_required_chunks": sum(1 for c in chunks if c["review_required"]),
        "review_items": len(review),
        "pages_needing_deskew": sum(1 for p in pages if p["preprocessing"].get("needs_deskew")),
        "pages_low_contrast": sum(1 for p in pages if p["preprocessing"].get("low_contrast")),
        "pages_blurry": sum(1 for p in pages if p["preprocessing"].get("blurry")),
        "page_types": {p["page_id"]: p["classification"]["page_type"] for p in pages},
    }
    manifest = {
        "ingestion_only": ingestion_only,
        "doc_id": source_sha256,
        "run_id": run_id,
        "source": str(source_path),
        "source_sha256": source_sha256,
        "document_type": document_type,
        "ingestion_pass": ingestion_report["pass"],
        "ingestion_quality_pass": ingestion_report.get("quality_pass"),
        "ingestion_review_assisted_pass": ingestion_report.get("review_assisted_pass"),
        "ingestion_production_pass": ingestion_report.get("production_pass"),
        "ingestion_auto_publish_pass": ingestion_report.get("auto_publish_pass"),
        "ingestion_quality_certified": ingestion_report.get("quality_certified"),
        "canonical_version": canonical["schema_version"],
        "parser": parser,
        "profile": document_profile,
        "language": language,
        "pdf_pages": pdf_page_count(pdf_path),
        "pages_requested": page_ids,
        "pages_processed": [p["page_id"] for p in pages],
        "failed_pages": failed_pages,
        "page_manifest": page_manifest,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "dpi": dpi,
        "pipeline_version": PIPELINE_VERSION,
        "engines": {
            "layout": "marker/surya (balanced, llama.cpp CPU)",
            "text": "marker baseline + Tesseract candidate",
            "math": "marker equation",
            "validation": "latex2mathml + structural",
        },
        "structured_enrichment": region_enricher.identity if region_enricher else None,
    }
    if region_enricher and region_enricher.identity.get("runner") == "idp-hybrid-runtime-1":
        manifest["engines"] = {"layout": "PP-DocLayoutV3 CPU",
            "text": "Tesseract CPU", "table": "CPU grid then bounded self-hosted fallback",
            "math": "self-hosted source-line alternatives", "validation": "structural, completion and export conservation"}

    for page in pages:
        pdir = out_dir / "pages"
        pdir.mkdir(exist_ok=True)
        _atomic_write(
            pdir / f"p{page['page_id']:04d}.json",
            json.dumps(page, ensure_ascii=False, indent=1),
        )
        _atomic_write(
            pdir / f"p{page['page_id']:04d}.md",
            page_markdown(page),
        )
    report["output_validation_errors"] = validate_outputs(out_dir, pages, chunks)
    report["export_pass"] = export_audit["pass"] if export_audit else None
    report["export_audit"] = export_audit
    if export_audit:
        report["output_validation_errors"].extend(
            f"{f['block_id']}: export content loss ({f['reason']})" for f in export_audit["failures"])
        _atomic_write(out_dir / "export_audit.json", json.dumps(export_audit, ensure_ascii=False, indent=1))

    _atomic_write(out_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    _atomic_write(out_dir / "report.json", json.dumps(report, ensure_ascii=False, indent=1))
    _atomic_write(out_dir / "canonical.json", json.dumps(canonical, ensure_ascii=False, indent=1))
    _atomic_write(
        out_dir / "ingestion_report.json",
        json.dumps(ingestion_report, ensure_ascii=False, indent=1),
    )
    if not ingestion_only:
        _atomic_write(out_dir / "document.json", json.dumps(document, ensure_ascii=False, indent=1))
        _atomic_write(
            out_dir / "chunks.jsonl",
            "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks),
        )
    _atomic_write(
        out_dir / "review_queue.jsonl",
        "\n".join(json.dumps(r, ensure_ascii=False) for r in review),
    )
    write_review_html(out_dir, review)
    return {
        "manifest": manifest,
        "report": report,
        "pages": pages,
        "chunks": chunks,
        "canonical": canonical,
        "ingestion": ingestion_report,
        "verified_pages": verified_pages,
        "verification_errors": verification_errors,
        "failed_pages": failed_pages,
    }


def run_ingestion(
    pdf_path: str | Path,
    page_ids: list[int],
    marker_json_by_page: dict[int, str | Path],
    page_images_by_page: dict[int, str | Path],
    out_dir: str | Path,
    dpi: int = 300,
    resume: bool = False,
    page_review_by_page: dict[int, list[dict]] | None = None,
    skip_text_candidate_pages: set[int] | None = None,
    verify_cmd: str | None = None,
    verify_timeout: int = 600,
    verify_max_pages: int = 0,
    trusted_parsers: set[str] | None = None,
    profile: str = "general",
    language: str | None = None,
    limits: InputLimits | None = None,
    chart_cmd: str | None = None,
    chart_timeout: int = 120,
    figure_cmd: str | None = None,
    figure_timeout: int = 120,
    figure_revision: str | None = None,
    workers: int = 1,
    source_acl: dict | None = None,
    source_metadata: dict | None = None,
    original_source_path: str | Path | None = None,
    region_enricher=None,
) -> dict:
    return run_pipeline(
        pdf_path=pdf_path,
        page_ids=page_ids,
        marker_json_by_page=marker_json_by_page,
        page_images_by_page=page_images_by_page,
        out_dir=out_dir,
        dpi=dpi,
        resume=resume,
        page_review_by_page=page_review_by_page,
        skip_text_candidate_pages=skip_text_candidate_pages,
        ingestion_only=True,
        verify_cmd=verify_cmd,
        verify_timeout=verify_timeout,
        verify_max_pages=verify_max_pages,
        trusted_parsers=trusted_parsers,
        profile=profile,
        language=language,
        limits=limits,
        chart_cmd=chart_cmd,
        chart_timeout=chart_timeout,
        figure_cmd=figure_cmd,
        figure_timeout=figure_timeout,
        figure_revision=figure_revision,
        workers=workers,
        source_acl=source_acl,
        source_metadata=source_metadata,
        original_source_path=original_source_path,
        region_enricher=region_enricher,
    )
