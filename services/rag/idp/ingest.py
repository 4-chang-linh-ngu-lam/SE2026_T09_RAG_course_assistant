"""Unified, fail-closed ingestion entry point for arbitrary uploads.

Routes text-like files to the digital lane, PDFs to the digital lane when a
text layer exists, and images to OCR. A scanned PDF with no precomputed OCR
markers returns ``NEEDS_OCR_ENGINE`` instead of silently producing empty text.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path

from PIL import Image, ImageOps

from idp.documents import digital
from idp.ocr.fallback import tesseract_marker
from idp.input.filetypes import (
    InputError,
    InputLimits,
    choose_ocr_language,
    detect_file_type,
    validate_input,
)
from idp.orchestration.pipeline import PIPELINE_VERSION, run_ingestion, sha256_file
from idp.input.profiles import resolve_profile
from idp.orchestration.registry import DocumentRegistry


def _image_frames(path: Path, limits: InputLimits) -> list[Image.Image]:
    frames = []
    total_pixels = 0
    with Image.open(path) as image:
        count = getattr(image, "n_frames", 1)
        if count > limits.max_pages:
            raise InputError(
                "PAGE_LIMIT_EXCEEDED",
                f"image has {count} frames; limit is {limits.max_pages}",
            )
        for index in range(count):
            image.seek(index)
            frame = ImageOps.exif_transpose(image).convert("RGB")
            total_pixels += frame.width * frame.height
            if total_pixels > limits.max_total_image_pixels:
                raise InputError(
                    "IMAGE_PIXEL_BUDGET_EXCEEDED",
                    f"image frames exceed the aggregate pixel budget "
                    f"({total_pixels} > {limits.max_total_image_pixels})",
                )
            frames.append(frame)
    return frames


def _ingest_image(
    source: Path,
    out: Path,
    *,
    profile: str,
    language: str | None,
    limits: InputLimits,
    trusted_parsers: set[str] | None,
    chart_cmd: str | None,
    chart_timeout: int,
    figure_cmd: str | None,
    figure_timeout: int,
    source_acl: dict | None,
    source_metadata: dict | None,
    region_recovery: bool,
    layout_detector,
    recovery_options,
    region_enricher,
) -> dict:
    resolved = resolve_profile(profile)
    chosen, assumed = choose_ocr_language(language or resolved.language)
    frames = _image_frames(source, limits)
    work = out / "work" / "image"
    images_dir = work / "images"
    markers_dir = work / "markers"
    images_dir.mkdir(parents=True, exist_ok=True)
    markers_dir.mkdir(parents=True, exist_ok=True)

    page_images = {}
    marker_paths = {}
    page_review = {}
    for index, frame in enumerate(frames, 1):
        image_path = images_dir / f"p{index:04d}.png"
        frame.save(image_path)
        page_images[index] = image_path
        try:
            marker_paths[index] = tesseract_marker(
                image_path, index, markers_dir, lang=chosen, profile=resolved.name,
                recover_regions=region_recovery, layout_detector=layout_detector,
                recovery_options=recovery_options,
            )
        except Exception as exc:
            if region_enricher and str(exc) == "tesseract fallback found no text":
                from idp.ocr.fallback import lines_to_marker
                marker = markers_dir / f"p{index:04d}.json"
                marker.write_text(json.dumps(lines_to_marker([], frame.width, frame.height, index, "tesseract_fallback")), "utf-8")
                marker_paths[index] = marker
                page_review[index] = [{"code": "OCR_BASELINE_EMPTY", "severity": "warning"}]
            else:
                raise InputError(
                    "NO_TEXT_IN_IMAGE",
                    f"OCR produced no text on page {index}: {exc}",
                ) from exc
        if assumed:
            page_review.setdefault(index, []).append({
                "code": "OCR_LANGUAGE_ASSUMED",
                "severity": "warning",
                "language": chosen,
            })

    pdf_path = work / "images.pdf"
    frames[0].save(
        pdf_path,
        "PDF",
        save_all=True,
        append_images=frames[1:],
        resolution=300.0,
    )
    result = run_ingestion(
        pdf_path=pdf_path,
        page_ids=list(range(1, len(frames) + 1)),
        marker_json_by_page=marker_paths,
        page_images_by_page=page_images,
        out_dir=out,
        page_review_by_page=page_review,
        skip_text_candidate_pages=set(page_images),
        trusted_parsers=trusted_parsers,
        profile=resolved.name,
        language=chosen,
        limits=limits,
        chart_cmd=chart_cmd,
        chart_timeout=chart_timeout,
        figure_cmd=figure_cmd,
        figure_timeout=figure_timeout,
        source_acl=source_acl,
        source_metadata=source_metadata,
        original_source_path=source,
        region_enricher=region_enricher,
    )
    result["ocr_language"] = chosen
    if not any(page.get("blocks") for page in result.get("pages") or []):
        raise InputError("NO_TEXT_IN_IMAGE", "neither OCR nor typed-region processing produced content")
    result["ocr_language_assumed"] = assumed
    return result


def ingest_file(
    input_path: str | Path,
    out_dir: str | Path,
    *,
    profile: str = "general",
    language: str | None = None,
    tables: str = "auto",
    limits: InputLimits | None = None,
    marker_json_by_page: dict[int, str | Path] | None = None,
    page_images_by_page: dict[int, str | Path] | None = None,
    trusted_parsers: set[str] | None = None,
    chart_cmd: str | None = None,
    chart_timeout: int = 120,
    figure_cmd: str | None = None,
    figure_timeout: int = 120,
    registry_path: str | Path | None = None,
    scope: str | None = None,
    source_acl: dict | None = None,
    source_metadata: dict | None = None,
    region_recovery: bool = True,
    layout_detector=None,
    recovery_options=None,
    region_enricher=None,
) -> dict:
    source = Path(input_path).resolve()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    limits = limits or InputLimits()
    kind = detect_file_type(source)
    info = validate_input(source, kind, limits)
    resolved = resolve_profile(profile)
    source_sha256 = sha256_file(source)
    if kind == "pdf" and (marker_json_by_page is not None or page_images_by_page is not None):
        expected = set(range(1, info["pages"] + 1))
        if (
            marker_json_by_page is None or page_images_by_page is None
            or set(marker_json_by_page) != expected or set(page_images_by_page) != expected
        ):
            raise InputError(
                "INCOMPLETE_OCR_MARKERS",
                "OCR markers must cover every PDF page when provided",
            )
    digital_route = kind not in ("pdf", "image") or (
        kind == "pdf"
        and marker_json_by_page is None
        and page_images_by_page is None
    )
    if digital_route and (chart_cmd or figure_cmd):
        raise InputError(
            "CHART_FIGURE_UNSUPPORTED_ON_DIGITAL_ROUTE",
            "chart_cmd/figure_cmd are only applied on the OCR-marker PDF route and "
            "the image route; the digital text route does not run them",
        )
    parser_name = f"{kind}:{resolved.name}"
    if registry_path and region_enricher and not region_enricher.cacheable:
        raise InputError("STRUCTURED_IDENTITY_REQUIRED", "all structured readers need stable identities for registry caching")
    if registry_path and region_recovery and layout_detector is not None and not getattr(layout_detector, "identity", None):
        raise InputError("LAYOUT_IDENTITY_REQUIRED", "a custom layout detector must expose a stable identity when registry caching is enabled")
    config = {
        "profile": profile, "language": language, "tables": tables,
        "trusted_parsers": sorted(trusted_parsers or ()),
        "chart_cmd": chart_cmd, "chart_timeout": chart_timeout,
        "figure_cmd": figure_cmd, "figure_timeout": figure_timeout,
        "source_acl": source_acl, "source_metadata": source_metadata,
        "region_recovery": region_recovery,
        "layout_detector": getattr(layout_detector, "identity", None),
        "recovery_options": vars(recovery_options) if recovery_options is not None else None,
        "structured_enrichment": region_enricher.identity if region_enricher else None,
        "markers": {str(p): sha256_file(path) for p, path in (marker_json_by_page or {}).items()} if registry_path else {},
        "images": {str(p): sha256_file(path) for p, path in (page_images_by_page or {}).items()} if registry_path else {},
    }
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()
    registry_scope = f"{scope or kind}:{config_sha}"
    registry = DocumentRegistry(registry_path) if registry_path else None
    if registry and registry.should_skip(
        source_sha256, parser_name, "unknown", PIPELINE_VERSION, registry_scope
    ):
        row = registry.lookup(
            source_sha256, parser_name, "unknown", PIPELINE_VERSION, registry_scope
        ) or {}
        return {
            "status": "skipped",
            "reason": "canonical document already exists",
            "canonical_path": row.get("canonical_path"),
            "ingestion_pass": True,
        }
    (out / "input.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "kind": kind,
                "profile": resolved.name,
                "language": language,
                "source_acl": source_acl,
                "source_metadata": source_metadata,
                **info,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    if kind == "image":
        result = _ingest_image(
            source, out, profile=resolved.name, language=language,
            limits=limits, trusted_parsers=trusted_parsers,
            chart_cmd=chart_cmd, chart_timeout=chart_timeout,
            figure_cmd=figure_cmd, figure_timeout=figure_timeout,
            source_acl=source_acl, source_metadata=source_metadata,
            region_recovery=region_recovery, layout_detector=layout_detector,
            recovery_options=recovery_options,
            region_enricher=region_enricher,
        )
    elif kind == "pdf":
        if marker_json_by_page is not None or page_images_by_page is not None:
            page_ids = sorted(marker_json_by_page or {})
            result = run_ingestion(
                pdf_path=source,
                page_ids=page_ids,
                marker_json_by_page=marker_json_by_page,
                page_images_by_page=page_images_by_page,
                out_dir=out,
                trusted_parsers=trusted_parsers,
                profile=resolved.name,
                language=language,
                limits=limits,
                chart_cmd=chart_cmd,
                chart_timeout=chart_timeout,
                figure_cmd=figure_cmd,
                figure_timeout=figure_timeout,
                source_acl=source_acl,
                source_metadata=source_metadata,
                region_enricher=region_enricher,
            )
        else:
            try:
                result = digital.process(
                    source, out, tables=tables, profile=resolved.name,
                    language=language, limits=limits, ingestion_only=True,
                    source_acl=source_acl, source_metadata=source_metadata,
                    region_recovery=region_recovery, layout_detector=layout_detector,
                    recovery_options=recovery_options,
                    region_enricher=region_enricher,
                )
            except RuntimeError as exc:
                if "text layer" not in str(exc):
                    raise
                raise InputError(
                    "NEEDS_OCR_ENGINE",
                    "PDF has no usable text layer and OCR fallback produced no "
                    "text; pass marker_json_by_page/page_images_by_page",
                ) from exc
    else:
        result = digital.process(
            source, out, tables=tables, profile=resolved.name,
            language=language, limits=limits, ingestion_only=True,
            source_acl=source_acl, source_metadata=source_metadata,
            region_recovery=region_recovery, layout_detector=layout_detector,
            recovery_options=recovery_options,
            region_enricher=region_enricher,
        )

    if registry:
        ingestion = result.get("ingestion") or result.get("report") or result
        succeeded = bool(
            ingestion.get("ingestion_review_assisted_pass", ingestion.get("pass"))
        )
        registry.record(
            doc_id=source_sha256,
            source_path=str(source),
            source_sha256=source_sha256,
            parser_name=parser_name,
            parser_version="unknown",
            pipeline_version=PIPELINE_VERSION,
            scope=registry_scope,
            status="succeeded" if succeeded else "failed",
            canonical_path=str(out / "canonical.json"),
            pages=ingestion.get("pages"),
        )
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generic ingestion entry point")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--profile", default="general")
    parser.add_argument("--language", default=None)
    parser.add_argument("--tables", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--chart-cmd", default=None)
    parser.add_argument("--chart-timeout", type=int, default=120)
    parser.add_argument("--figure-cmd", default=None)
    parser.add_argument("--figure-timeout", type=int, default=120)
    parser.add_argument("--registry", default=None)
    parser.add_argument("--no-region-recovery", action="store_true")
    parser.add_argument("--layout-model-dir", type=Path)
    parser.add_argument("--layout-policy", choices=("default", "v3_vl16"), default="default")
    parser.add_argument("--region-budget", type=float, default=15)
    from idp.structured.enrichment import add_structured_arguments, structured_context
    add_structured_arguments(parser)
    args = parser.parse_args()
    try:
        from idp.ocr.recovery import PaddleLayoutDetector, cli_recovery_options

        options = cli_recovery_options(parser, args)
        with (
            (PaddleLayoutDetector(args.layout_model_dir, layout_policy=args.layout_policy) if args.layout_model_dir else nullcontext(None)) as detector,
            structured_context(args, parser, detector, args.language or "vie") as enricher,
        ):
            result = ingest_file(
                args.input, args.out, profile=args.profile,
                language=args.language, tables=args.tables,
                chart_cmd=args.chart_cmd, chart_timeout=args.chart_timeout,
                figure_cmd=args.figure_cmd, figure_timeout=args.figure_timeout,
                registry_path=args.registry, region_recovery=not args.no_region_recovery,
                layout_detector=detector, recovery_options=options,
                region_enricher=enricher,
            )
    except InputError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    report = result.get("report", result)
    print(json.dumps({
        "pages": report.get("pages"),
        "ingestion_pass": report.get("ingestion_pass", report.get("pass")),
        "ingestion_quality_pass": report.get("ingestion_quality_pass"),
        "ingestion_production_pass": report.get("ingestion_production_pass"),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
