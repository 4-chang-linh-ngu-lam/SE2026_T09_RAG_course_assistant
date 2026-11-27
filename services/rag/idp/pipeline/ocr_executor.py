"""OCR page execution, retry-DPI rescue, missed-ink recovery, and region task execution."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Callable

from PIL import Image

from idp.backends.layout import detect_missed_ink_regions, normalize_layout_kind
from idp.backends.native.pdf import make_block, make_page
from idp.backends.text_ocr import lines_to_blocks, ocr_labels
from idp.backends.vision_ocr import SOURCE as VL_SOURCE, _unwrap_latex
from idp.evidence.cross_read import dual_read_page, table_agreement
from idp.evidence.fusion import vl_reread_page
from idp.evidence.recovery import RecoveryOptions, recover_text_regions
from idp.pipeline.native_escalation import apply_budget_skipped_flags
from idp.pipeline.page_router import PageDecision
from idp.pipeline.region_router import RegionAction, RegionRouter, RegionTask, _area, _intersect_area
from idp.pipeline.reporting import add_block_flag, add_page_flag, page_has_extractable_content, scale_box
from idp.pipeline.scheduler import AdaptiveScheduler
from idp.processing.figure import (
    assign_section_paths,
    attach_captions,
    classify_page,
    is_structural_section_header,
    merge_adjacent_section_headers,
    prepare_page_figures,
    section_level,
)
from idp.processing.formula import normalize_latex, normalize_text, validate_latex
from idp.processing.preprocess import analyze_page, preprocess_image, write_preprocess_metadata
from idp.processing.reading_order import order_page_blocks, sort_page_headers
from idp.processing.render import PageRenderCache
from idp.processing.table import GridTableReader, RuledTableDetector, parse_table_html, table_html
from idp.validation.calibration import build_confidence_meta


def _median_line_confidence(lines: list[dict]) -> float:
    confs = []
    for line in lines:
        raw = line.get("confidence")
        if raw is None:
            continue
        val = float(raw) / 100.0 if float(raw) > 1.0 else float(raw)
        confs.append(val)
    return statistics.median(confs) if confs else 0.0


def _line_yield_score(lines: list[dict]) -> tuple[int, float]:
    chars = sum(len((line.get("text") or "").strip()) for line in lines)
    return chars, _median_line_confidence(lines)


def _apply_layout_block_types(page: dict, tasks: list[RegionTask]) -> None:
    """Propagate SectionHeader and decorative margin block types onto finalized page blocks."""
    by_id = {b.get("block_id"): b for b in page.get("blocks") or [] if b.get("block_id")}
    for task in tasks:
        if task.kind == "SectionHeader" and task.action == RegionAction.NATIVE_KEEP:
            for bid in task.source_block_ids:
                blk = by_id.get(bid)
                if blk is None or blk.get("block_type") != "Text":
                    continue
                text = (blk.get("text") or "").strip()
                if is_structural_section_header(text):
                    blk["block_type"] = "SectionHeader"
                    if not str(blk.get("markdown") or "").lstrip().startswith("#"):
                        blk["markdown"] = f"{'#' * min(6, section_level(text))} {text}"
        elif task.action == RegionAction.SKIP_DECORATIVE and task.kind in {"PageHeader", "PageFooter", "PageNumber"}:
            for bid in task.source_block_ids:
                blk = by_id.get(bid)
                if blk is not None and blk.get("block_type") == "Text":
                    blk["block_type"] = task.kind


def _suppress_table_overlapping_ocr_blocks(page: dict) -> None:
    """Drop redundant full-page Tesseract blocks covered by structured Table extractions."""
    table_boxes = [
        b["bbox"]
        for b in page.get("blocks") or []
        if b.get("block_type") == "Table" and b.get("table_html") and b.get("table_cells") and b.get("bbox")
    ]
    if not table_boxes:
        return
    kept = []
    for blk in page.get("blocks") or []:
        box = blk.get("bbox")
        if (
            blk.get("block_type") in {"Text", "ListGroup", "Equation"}
            and blk.get("source") in {"tesseract_ocr", "ocr_region_recovery", "tesseract_fast"}
            and box
            and len(box) == 4
            and any(_intersect_area(box, tb) / _area(box) > 0.55 for tb in table_boxes)
        ):
            continue
        kept.append(blk)
    page["blocks"] = kept


def run_scan_page_with_retry(
    dec: PageDecision,
    *,
    profile_width: float,
    profile_height: float,
    ocr_reason: str | None,
    out_dir: Path,
    assets_dir: Path,
    lang: str,
    profile_name: str,
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    telemetry: dict,
    config,
    detector,
    vl_reader,
    region_enricher,
    dual_reader,
    region_router: RegionRouter,
    recovery_options: RecoveryOptions,
    has_vlm: bool,
    record_task_telemetry: Callable,
    inc_ocr_calls: Callable[[dict, int], None],
    ocr_page_image_fn: Callable,
    detect_panels_fn: Callable,
) -> dict:
    pid = dec.page_id
    rendered = render_cache.get_page_image(pid)
    analysis = analyze_page(rendered.path)
    active_path = rendered.path
    if analysis.get("needs_deskew") or analysis.get("low_contrast"):
        prep_path = out_dir / "preprocessed" / f"p{pid:04d}.png"
        preprocess_image(rendered.path, prep_path, analysis)
        render_cache.register_external_image(pid, prep_path)
        active_path = prep_path
    write_preprocess_metadata(analysis, out_dir / "pages" / f"p{pid:04d}.preprocess.json")

    ocr_work = out_dir / "ocr" / f"p{pid:04d}"
    inc_ocr_calls(telemetry, 1)
    lines = ocr_page_image_fn(active_path, ocr_work, pid, lang=lang, profile=profile_name)
    med_conf = _median_line_confidence(lines)

    can_retry_dpi = (
        render_cache.pdf_path is not None
        and pid not in render_cache.precomputed
        and not analysis.get("blank")
        and config.render.retry_dpi > rendered.dpi
    )
    should_retry = (
        (not lines)
        or (med_conf < config.router.min_ocr_confidence)
        or (bool(analysis.get("blurry")) and med_conf < config.router.early_exit_ocr_confidence)
    )
    if can_retry_dpi and should_retry:
        retry_max_pixels = min(
            12_000_000,
            max(
                config.render.max_page_pixels,
                int(config.render.max_page_pixels * (config.render.retry_dpi / max(1, config.render.base_dpi)) ** 2),
            ),
        )
        retry_rendered = render_cache.get_page_image(
            pid,
            dpi=config.render.retry_dpi,
            max_pixels=retry_max_pixels,
            force_rerender=True,
        )
        retry_analysis = analyze_page(retry_rendered.path)
        retry_active = retry_rendered.path
        if retry_analysis.get("needs_deskew") or retry_analysis.get("low_contrast"):
            retry_prep = out_dir / "preprocessed" / f"p{pid:04d}_d{retry_rendered.dpi}.png"
            preprocess_image(retry_rendered.path, retry_prep, retry_analysis)
            render_cache.register_external_image(pid, retry_prep, dpi=retry_rendered.dpi)
            retry_active = retry_prep
        inc_ocr_calls(telemetry, 1)
        retry_lines = ocr_page_image_fn(
            retry_active,
            ocr_work / f"d{retry_rendered.dpi}",
            pid,
            lang=lang,
            profile=profile_name,
        )
        if _line_yield_score(retry_lines) >= _line_yield_score(lines):
            rendered = retry_rendered
            analysis = retry_analysis
            active_path = retry_active
            lines = retry_lines
            write_preprocess_metadata(analysis, out_dir / "pages" / f"p{pid:04d}.preprocess.json")

    page = process_ocr_page(
        pid,
        [profile_width, profile_height],
        active_path,
        rendered.sha256,
        analysis,
        dec,
        out_dir,
        assets_dir,
        lang=lang,
        profile_name=profile_name,
        render_cache=render_cache,
        scheduler=scheduler,
        telemetry=telemetry,
        config=config,
        detector=detector,
        vl_reader=vl_reader,
        region_enricher=region_enricher,
        dual_reader=dual_reader,
        region_router=region_router,
        recovery_options=recovery_options,
        has_vlm=has_vlm,
        record_task_telemetry=record_task_telemetry,
        inc_ocr_calls=inc_ocr_calls,
        ocr_page_image_fn=ocr_page_image_fn,
        detect_panels_fn=detect_panels_fn,
        precomputed_lines=lines,
    )
    page["render_provenance"] = {
        "dpi": rendered.dpi,
        "width": rendered.width,
        "height": rendered.height,
    }
    if ocr_reason == "repeated_url_only_text_layer":
        add_page_flag(page, "PAGE_TEXT_LAYER_UNUSABLE", reason=ocr_reason)
    return page


def process_ocr_page(
    page_id: int,
    page_size: list[float],
    image_path: Path,
    image_sha256: str,
    analysis: dict,
    decision: PageDecision,
    out_dir: Path,
    assets_dir: Path,
    *,
    lang: str,
    profile_name: str,
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    telemetry: dict,
    config,
    detector,
    vl_reader,
    region_enricher,
    dual_reader,
    region_router: RegionRouter,
    recovery_options: RecoveryOptions,
    has_vlm: bool,
    record_task_telemetry: Callable,
    inc_ocr_calls: Callable[[dict, int], None],
    ocr_page_image_fn: Callable,
    detect_panels_fn: Callable,
    precomputed_lines: list[dict] | None = None,
) -> dict:
    with Image.open(image_path) as opened:
        img_w, img_h = opened.size
    pw, ph = float(page_size[0] or img_w), float(page_size[1] or img_h)
    sx_to_page = pw / max(1.0, float(img_w))
    sy_to_page = ph / max(1.0, float(img_h))

    layout_regions: list[dict] = []
    layout_failed = False
    if decision.layout_required and detector is not None:
        try:
            layout_regions = list(detector(image_path) or [])
        except Exception:
            layout_failed = True
            layout_regions = []

    if (
        config.tables != "off"
        and config.router.enable_ruled_tables
        and not any(normalize_layout_kind(r.get("kind") or "") == "Table" for r in layout_regions)
    ):
        try:
            layout_regions.extend(RuledTableDetector()(image_path))
        except Exception:
            pass

    ocr_work = out_dir / "ocr" / f"p{page_id:04d}"
    if precomputed_lines is None:
        inc_ocr_calls(telemetry, 1)
        lines = ocr_page_image_fn(image_path, ocr_work, page_id, lang=lang, profile=profile_name)
    else:
        lines = list(precomputed_lines)

    recovery_report = None
    if config.router.enable_region_recovery:
        try:
            panel_hints = detect_panels_fn(image_path)
        except Exception:
            panel_hints = []
        layout_text = [
            r for r in layout_regions
            if str(r.get("kind") or "").lower() in {"text", "paragraph_title", "doc_title", "header", "footer"}
        ]
        missed_ink: list[dict] = []
        if not layout_text:
            try:
                excluded = [
                    r["bbox"] for r in layout_regions
                    if normalize_layout_kind(r.get("kind") or "") in {"Table", "Picture", "Diagram", "Chart", "PictureGroup"}
                    and r.get("bbox")
                ]
                missed_ink = detect_missed_ink_regions(image_path, lines, excluded_boxes=excluded)
            except Exception:
                missed_ink = []
        proposed = [*panel_hints, *layout_text, *missed_ink]
        if proposed:
            inc_ocr_calls(telemetry, 1)
            lines, recovery_report = recover_text_regions(
                image_path,
                lines,
                ocr_work / "recovery",
                lang=lang,
                profile=profile_name,
                options=recovery_options,
                proposed_regions=proposed,
            )

    for line in lines:
        if line.get("bbox"):
            line["bbox"] = scale_box(line["bbox"], sx_to_page, sy_to_page)
    blocks = lines_to_blocks(
        page_id,
        lines,
        source="tesseract_ocr",
        image_path=image_path,
        out_dir=out_dir,
        make_crops=False,
    )
    blocks = order_page_blocks(blocks, pw)
    sort_page_headers(blocks, pw)

    page = make_page(
        page_id,
        blocks,
        [pw, ph],
        page_number=page_id,
        source_image_sha256=image_sha256,
        page_image=str(image_path),
        preprocessing=analysis,
    )
    page["profile"] = profile_name
    page["ocr_language"] = lang
    page["parser"] = "adaptive_ocr"
    page["page_route"] = decision.as_dict()
    if recovery_report is not None:
        page["region_recovery"] = recovery_report
    if layout_failed:
        add_page_flag(page, "STRUCTURED_LAYOUT_FAILED")
    if analysis.get("blurry"):
        add_page_flag(page, "PAGE_BLURRY")
    if analysis.get("low_contrast"):
        add_page_flag(page, "PAGE_LOW_CONTRAST")
    if analysis.get("needs_deskew"):
        add_page_flag(page, "PAGE_NEEDS_DESKEW")
    if analysis.get("faint_content_only"):
        add_page_flag(page, "PAGE_FAINT_CONTENT_REVIEW")

    tasks = region_router.route_ocr_page_regions(
        page,
        layout_regions,
        has_vlm=has_vlm,
        image_size=(img_w, img_h),
    )
    page["region_tasks"] = [t.as_dict() for t in tasks]
    record_task_telemetry(telemetry, tasks)

    if region_enricher is not None:
        region_enricher.enrich_page(page, out_dir, image_path, precomputed_layout=layout_regions)
    else:
        execute_ocr_region_tasks(
            page,
            tasks,
            out_dir,
            assets_dir,
            image_path=image_path,
            lang=lang,
            profile_name=profile_name,
            render_cache=render_cache,
            scheduler=scheduler,
            telemetry=telemetry,
            config=config,
            vl_reader=vl_reader,
            inc_ocr_calls=inc_ocr_calls,
        )

    _suppress_table_overlapping_ocr_blocks(page)

    if dual_reader is not None:
        dual_read_page(
            page,
            image_path,
            dual_reader,
            selective=config.router.enable_selective_verification,
            risk_confidence_threshold=config.router.early_exit_ocr_confidence,
        )

    apply_budget_skipped_flags(page, tasks)
    _apply_layout_block_types(page, tasks)
    page["blocks"] = order_page_blocks(page["blocks"], pw)
    sort_page_headers(page["blocks"], pw)
    page["blocks"] = merge_adjacent_section_headers(page["blocks"])
    for order, blk in enumerate(page["blocks"]):
        blk["order"] = order
    prepare_page_figures(page, out_dir)
    assign_section_paths(page["blocks"])
    attach_captions(page["blocks"])
    page["classification"] = classify_page(page["blocks"])
    if layout_failed and not page_has_extractable_content(page):
        add_page_flag(page, "PAGE_LAYOUT_FAILED", severity="error")
        page["processing_status"] = "layout_failed"
    else:
        page["processing_status"] = "ok"
    return page


def execute_ocr_region_tasks(
    page: dict,
    tasks: list[RegionTask],
    out_dir: Path,
    assets_dir: Path,
    *,
    image_path: Path,
    lang: str,
    profile_name: str = "general",
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    telemetry: dict,
    config,
    vl_reader,
    inc_ocr_calls: Callable[[dict, int], None],
) -> None:
    pid = int(page["page_id"])
    for task in tasks:
        if task.action == RegionAction.FIGURE_PRESERVE:
            execute_figure_task(
                page,
                task,
                out_dir,
                assets_dir,
                lang=lang,
                render_cache=render_cache,
                region_timeout_seconds=config.router.region_timeout_seconds,
            )
        elif task.action in {RegionAction.RULED_TABLE_OCR, RegionAction.VLM_TABLE}:
            execute_ruled_table_task(
                page,
                task,
                target_block=None,
                out_dir=out_dir,
                assets_dir=assets_dir,
                lang=lang,
                render_cache=render_cache,
                scheduler=scheduler,
                telemetry=telemetry,
                region_timeout_seconds=config.router.region_timeout_seconds,
                vl_reader=vl_reader,
                inc_ocr_calls=inc_ocr_calls,
                force_vlm=(task.action == RegionAction.VLM_TABLE),
            )

    vlm_tasks = [
        t for t in tasks
        if t.action in {RegionAction.VLM_FORMULA, RegionAction.VLM_TEXT} and not t.budget_skipped
    ]
    if vlm_tasks and vl_reader is not None:
        if callable(vl_reader):
            vl_regions = [
                (
                    "Equation" if t.action == RegionAction.VLM_FORMULA else ("SectionHeader" if t.kind == "SectionHeader" else "Text"),
                    tuple(t.bbox),
                    list(t.line_boxes),
                )
                for t in vlm_tasks
            ]
            try:
                vl_reread_page(
                    page,
                    image_path,
                    vl_reader,
                    page_regions=vl_regions,
                    replace_all_text=(config.router.vlm_mode == "full" and not any(t.budget_skipped for t in tasks)),
                    gpu_queue=scheduler.gpu_queue,
                )
            except Exception as exc:
                add_page_flag(page, "OCR_VL_FALLBACK_FAILED", reason=type(exc).__name__)
        elif hasattr(vl_reader, "read_region_structured"):
            vlm_structured_ocr_tasks(
                page,
                vlm_tasks,
                out_dir,
                render_cache,
                scheduler,
                vl_reader=vl_reader,
                region_timeout_seconds=config.router.region_timeout_seconds,
                profile_name=profile_name,
            )

    skipped_tasks = [t for t in tasks if t.budget_skipped]
    if skipped_tasks:
        enrichment = page.setdefault("structured_enrichment", {"regions": [], "flags": [], "seconds": 0})
        if not enrichment.get("image_size"):
            rendered = render_cache.get_page_image(pid)
            enrichment["image_size"] = [rendered.width, rendered.height]
        pw, ph = page.get("page_size") or enrichment["image_size"]
        sx = enrichment["image_size"][0] / max(1.0, float(pw))
        sy = enrichment["image_size"][1] / max(1.0, float(ph))
        for task in skipped_tasks:
            bx0, by0, bx1, by1 = task.bbox
            enrichment["regions"].append({
                "kind": "Equation" if task.kind == "Equation" else ("Table" if task.kind == "Table" else "Text"),
                "pixel_bbox": [bx0 * sx, by0 * sy, bx1 * sx, by1 * sy],
                "status": "budget_limit",
                "recognition_skipped": "budget_limit",
            })


def execute_figure_task(
    page: dict,
    task: RegionTask,
    out_dir: Path,
    assets_dir: Path,
    *,
    lang: str,
    render_cache: PageRenderCache,
    region_timeout_seconds: float,
) -> None:
    del out_dir
    pid = int(page["page_id"])
    page_size = page.get("page_size") or [1000, 1400]
    fig_dir = assets_dir / f"p{pid:04d}" / "figures"
    crop_path = fig_dir / f"{task.region_id}.png"
    render_cache.crop_region(pid, task.bbox, page_size, save_path=crop_path)
    labels = []
    try:
        labels = ocr_labels(crop_path, fig_dir, lang=lang, timeout=min(15.0, region_timeout_seconds))
    except Exception:
        labels = []
    bid = f"p{pid:04d}_{task.region_id}"
    blk = make_block(
        bid,
        task.kind if task.kind in {"Picture", "Diagram", "Chart", "PictureGroup"} else "Picture",
        list(task.bbox),
        "",
        f"![]({crop_path.as_posix()})",
        asset_paths=[str(crop_path)],
    )
    blk["layout_score"] = task.layout_score
    blk["source"] = "layout_figure"
    blk["block_crop_path"] = str(crop_path)
    blk["visual_labels"] = [{"text": l["text"], "bbox": l.get("bbox")} for l in labels if l.get("text")]
    blk["figure_kind"] = "content"
    page["blocks"].append(blk)


def execute_ruled_table_task(
    page: dict,
    task: RegionTask,
    *,
    target_block: dict | None,
    out_dir: Path,
    assets_dir: Path,
    lang: str,
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    telemetry: dict,
    region_timeout_seconds: float,
    vl_reader,
    inc_ocr_calls: Callable[[dict, int], None],
    force_vlm: bool = False,
) -> None:
    del out_dir
    pid = int(page["page_id"])
    page_size = page.get("page_size") or [1000, 1400]
    tbl_dir = assets_dir / f"p{pid:04d}" / "tables"
    crop_path = tbl_dir / f"{task.region_id}.png"
    crop_img, _ = render_cache.crop_region(pid, task.bbox, page_size, save_path=crop_path)

    timeout = region_timeout_seconds
    reading: dict | None = None
    cpu_failed = force_vlm
    if not force_vlm:
        reader = GridTableReader(lang)
        try:
            inc_ocr_calls(telemetry, 1)
            reading = reader(crop_path, timeout)
        except Exception:
            cpu_failed = True

    weak_cpu = bool(
        reading
        and (
            reading.get("cell_disagreements")
            or reading.get("ocr_budget_exhausted")
            or (
                reading.get("ocr_confidence") is not None
                and float(reading.get("ocr_confidence")) < 0.70
            )
        )
    )
    vlm_error: str | None = None
    if (
        (cpu_failed or weak_cpu)
        and (force_vlm or task.fallback == RegionAction.VLM_TABLE)
        and vl_reader is not None
        and hasattr(vl_reader, "read_region_structured")
    ):
        vlm_timeout = max(
            float(timeout),
            min(float(getattr(vl_reader, "timeout", 120.0) or 120.0), 90.0),
        )
        try:
            vlm_res = scheduler.gpu_queue.submit_call(
                vl_reader.read_region_structured,
                crop_img,
                "Table",
                timeout=vlm_timeout,
            )
            parsed = parse_table_html(vlm_res.get("table_html") or "")
            if parsed.get("rectangular"):
                reading = {
                    "table_html": table_html(parsed["cells"]),
                    "cells": parsed["cells"],
                    "ocr_confidence": None,
                    "score_kind": "vlm_unscored",
                    "source": VL_SOURCE,
                }
                cpu_failed = False
        except Exception as exc:
            vlm_error = f"{type(exc).__name__}: {exc}"[:200]

    bid = target_block["block_id"] if target_block else f"p{pid:04d}_{task.region_id}"
    blk = target_block or make_block(bid, "Table", list(task.bbox), "", "")
    blk["block_crop_path"] = str(crop_path)
    if str(crop_path) not in blk.setdefault("asset_paths", []):
        blk["asset_paths"].append(str(crop_path))

    if reading and reading.get("table_html"):
        parsed = parse_table_html(reading["table_html"])
        safe_html = table_html(parsed["cells"])
        blk["table_html"] = safe_html
        blk["markdown"] = safe_html
        blk["table_cells"] = parsed["cells"]
        blk["table_shape"] = [parsed["rows"], parsed["columns"]]
        blk["table_header_rows"] = parsed["header_rows"]
        blk["source"] = reading.get("source") or "opencv_grid_tesseract"
        raw_conf = reading.get("ocr_confidence")
        blk["confidence"] = round(float(raw_conf), 4) if raw_conf is not None else None
        blk["confidence_meta"] = build_confidence_meta(
            blk["confidence"],
            source=blk["source"],
            score_kind=reading.get("score_kind"),
        )
        blk["review_flags"] = [
            f for f in blk.get("review_flags") or []
            if f.get("code") != "TABLE_STRUCTURE_REVIEW"
        ]
        blk["structured_provenance"] = {
            "version": "adaptive-table-1",
            "producer": {"name": blk["source"]},
        }
        blk.pop("table_metrics", None)
        agr = table_agreement(reading.get("cells") or [])
        if agr:
            blk["text"] = agr["text"]
            add_block_flag(blk, agr["code"], severity="info")
        else:
            blk["text"] = " ".join(c.get("text") or "" for c in parsed["cells"]).strip()
            add_block_flag(blk, "TABLE_OCR_REVIEW")
        if blk["confidence"] is None:
            add_block_flag(blk, "TABLE_OCR_REVIEW")
    else:
        blk["source"] = blk.get("source") or "structured_region"
        blk["confidence"] = None
        blk["confidence_meta"] = build_confidence_meta(None, source=blk["source"], score_kind="none")
        blk["structured_provenance"] = {
            "version": "adaptive-table-1",
            "producer": {"name": blk["source"]},
            **({"error": vlm_error} if vlm_error else {}),
        }
        add_block_flag(blk, "TABLE_EMPTY")
        add_block_flag(blk, "STRUCTURED_REGION_UNRESOLVED")
        add_block_flag(blk, "STRUCTURED_EXTRACTION_REVIEW")

    if target_block is None:
        page["blocks"].append(blk)


def vlm_structured_ocr_tasks(
    page: dict,
    tasks: list[RegionTask],
    out_dir: Path,
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    *,
    vl_reader,
    region_timeout_seconds: float,
    profile_name: str = "general",
) -> None:
    pid = int(page["page_id"])
    page_size = page.get("page_size") or [1000, 1400]
    vlm_dir = out_dir / "assets" / f"p{pid:04d}" / "vlm"
    vlm_dir.mkdir(parents=True, exist_ok=True)

    def run_one(task: RegionTask) -> tuple[RegionTask, Path, dict | None]:
        if task.action == RegionAction.VLM_FORMULA:
            kind = "Equation"
        elif task.action == RegionAction.VLM_TABLE:
            kind = "Table"
        else:
            kind = "Text"
        crop_path = vlm_dir / f"{task.region_id}.png"
        crop_img, _ = render_cache.crop_region(pid, task.bbox, page_size, save_path=crop_path)
        try:
            res = vl_reader.read_region_structured(
                crop_img, kind, timeout=region_timeout_seconds
            )
            return task, crop_path, res
        except Exception:
            return task, crop_path, None

    results = scheduler.gpu_queue.map_calls(run_one, tasks)
    replaced_block_ids: set[str] = set()
    for task, crop_path, res in results:
        if not res:
            continue
        bid = f"p{pid:04d}_{task.region_id}"
        if task.action == RegionAction.VLM_FORMULA and res.get("latex"):
            tex = normalize_latex(_unwrap_latex(res["latex"]), profile_name)
            if not tex:
                continue
            val = validate_latex(tex).as_dict()
            flags = [] if val["valid"] else [{"code": "LATEX_INVALID", "severity": "warning"}]
            flags.append({"code": "VLM_UNSCORED_REVIEW", "severity": "warning"})
            blk = make_block(
                bid,
                "Equation",
                list(task.bbox),
                tex,
                f"$$\n{tex}\n$$",
                latex=[tex],
                asset_paths=[str(crop_path)],
                review_flags=flags,
            )
            blk["latex_validation"] = [val]
            blk["source"] = VL_SOURCE
            blk["confidence"] = None
            blk["confidence_meta"] = build_confidence_meta(
                None, source=VL_SOURCE, score_kind="vlm_unscored"
            )
            blk["block_crop_path"] = str(crop_path)
            page["blocks"].append(blk)
        elif task.action == RegionAction.VLM_TEXT and res.get("text"):
            norm, _ = normalize_text(str(res["text"]), profile_name)
            text_clean = norm.strip()
            if not text_clean:
                continue
            btype = "SectionHeader" if task.kind == "SectionHeader" and is_structural_section_header(text_clean) else "Text"
            md = f"{'#' * min(6, section_level(text_clean))} {text_clean}" if btype == "SectionHeader" else text_clean
            blk = make_block(
                bid,
                btype,
                list(task.bbox),
                text_clean,
                md,
                asset_paths=[str(crop_path)],
                review_flags=[{"code": "VLM_UNSCORED_REVIEW", "severity": "warning"}],
            )
            blk["source"] = VL_SOURCE
            blk["confidence"] = None
            blk["confidence_meta"] = build_confidence_meta(
                None, source=VL_SOURCE, score_kind="vlm_unscored"
            )
            blk["block_crop_path"] = str(crop_path)
            replaced_block_ids.update(task.source_block_ids)
            page["blocks"].append(blk)
        elif task.action == RegionAction.VLM_TABLE and res.get("table_html"):
            try:
                parsed = parse_table_html(res["table_html"])
            except ValueError:
                continue
            safe_html = table_html(parsed["cells"])
            text = " ".join(c.get("text") or "" for c in parsed["cells"]).strip()
            blk = make_block(
                bid,
                "Table",
                list(task.bbox),
                text,
                safe_html,
                asset_paths=[str(crop_path)],
                review_flags=[{"code": "TABLE_OCR_REVIEW", "severity": "warning"}],
            )
            blk["table_html"] = safe_html
            blk["table_cells"] = parsed["cells"]
            blk["table_shape"] = [parsed["rows"], parsed["columns"]]
            blk["table_header_rows"] = parsed["header_rows"]
            blk["source"] = VL_SOURCE
            blk["confidence"] = None
            blk["confidence_meta"] = build_confidence_meta(
                None, source=VL_SOURCE, score_kind="vlm_unscored"
            )
            blk["block_crop_path"] = str(crop_path)
            page["blocks"].append(blk)

    if replaced_block_ids:
        page["blocks"] = [
            b for b in page["blocks"] if b.get("block_id") not in replaced_block_ids
        ]
