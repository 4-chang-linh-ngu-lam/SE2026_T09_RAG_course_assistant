"""Post-Level-0 selective recovery & VLM escalation for NATIVE_ADAPTIVE PDF pages."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from idp.backends.vision_ocr import SOURCE as VL_SOURCE, _unwrap_latex
from idp.evidence.cross_read import (
    LOW,
    dual_read_page,
    formula_agreement,
    line_confidence,
    repair_line,
    split_lines,
    word_probs,
)
from idp.evidence.recovery import recover_bad_native_blocks
from idp.input.validation import is_garbled_text, needs_ocr
from idp.pipeline.region_router import RegionAction, RegionTask
from idp.pipeline.reporting import add_block_flag, add_page_flag
from idp.pipeline.scheduler import AdaptiveScheduler
from idp.processing.figure import classify_page, prepare_page_figures
from idp.processing.formula import normalize_latex, normalize_text, validate_latex
from idp.processing.render import PageRenderCache
from idp.validation.calibration import build_confidence_meta


def apply_budget_skipped_flags(page: dict, tasks: list[RegionTask]) -> None:
    by_id = {b.get("block_id"): b for b in page.get("blocks") or [] if b.get("block_id")}
    for task in tasks:
        if not task.budget_skipped:
            continue
        for bid in task.source_block_ids:
            blk = by_id.get(bid)
            if blk is not None:
                add_block_flag(blk, "STRUCTURED_BUDGET_EXHAUSTED", reason="region_not_transcribed")
        add_page_flag(page, "STRUCTURED_BUDGET_EXHAUSTED")


def _extract_tokens_text_and_conf(
    tokens: list[tuple],
    kind: str,
    host_text: str,
) -> tuple[str, float | None, list[dict]]:
    tess_words = {w for w, _ in word_probs([(host_text, 1.0)])} if host_text else set()
    lines = split_lines(tokens)
    if not lines:
        return "", None, []
    out_lines: list[str] = []
    line_confs: list[float] = []
    all_repairs: list[dict] = []
    for line_tokens in lines:
        repaired, repairs = repair_line(line_tokens, tess_words)
        conf = line_confidence(repaired, kind, host_text, tess_words)
        text = "".join(t[0] for t in repaired).strip()
        if text:
            out_lines.append(text)
            if conf is not None:
                line_confs.append(conf)
        all_repairs.extend(repairs)
    joined = "\n".join(out_lines).strip()
    agg_conf = round(min(line_confs), 4) if line_confs else None
    return joined, agg_conf, all_repairs


def vlm_read_native_blocks(
    page: dict,
    blocks: list[dict],
    action: RegionAction,
    out_dir: Path,
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    profile_name: str,
    *,
    vl_reader,
    region_timeout_seconds: float,
) -> None:
    pid = int(page["page_id"])
    page_size = page.get("page_size") or [1000, 1400]
    kind = "Equation" if action == RegionAction.VLM_FORMULA else "Text"
    work = out_dir / "assets" / f"p{pid:04d}" / "vlm"

    def process_block(block: dict) -> None:
        crop_path = work / f"{block['block_id']}.png"
        crop, _ = render_cache.crop_region(pid, block["bbox"], page_size, save_path=crop_path)
        host_text = block.get("text") or ""
        raw_text = ""
        confidence: float | None = None
        score_kind = "vlm_unscored"
        repairs: list[dict] = []

        if callable(vl_reader):
            try:
                res = vl_reader(crop, kind)
                if isinstance(res, list):
                    raw_text, confidence, repairs = _extract_tokens_text_and_conf(res, kind, host_text)
                    score_kind = "vlm_min_token_prob"
                elif isinstance(res, dict):
                    raw_text = res.get("latex" if kind == "Equation" else "text") or res.get("text") or ""
            except Exception:
                raw_text = ""
        if not raw_text.strip() and hasattr(vl_reader, "read_region_structured"):
            try:
                reading = vl_reader.read_region_structured(
                    crop_path, kind, timeout=region_timeout_seconds
                )
                raw_text = reading.get("latex" if kind == "Equation" else "text") or ""
                confidence = None
                score_kind = "vlm_unscored"
            except Exception:
                raw_text = ""

        if not raw_text.strip():
            return

        if kind == "Equation":
            tex = normalize_latex(_unwrap_latex(raw_text), profile_name)
            if not tex:
                return
            val = validate_latex(tex).as_dict()
            block["latex"] = [tex]
            block["latex_validation"] = [val]
            block["markdown"] = f"$$\n{tex}\n$$"
            agreed = False
            if host_text:
                agr = formula_agreement(tex, host_text)
                if agr:
                    add_block_flag(block, agr["code"], severity="info")
                    block["text"] = tex
                    agreed = True
            if not host_text or not agreed:
                block["text"] = tex
            block["source"] = VL_SOURCE
            block["confidence"] = confidence
            block["confidence_meta"] = build_confidence_meta(
                confidence, source=VL_SOURCE, score_kind=score_kind
            )
            block["block_crop_path"] = str(crop_path)
            if crop_path and str(crop_path) not in block.setdefault("asset_paths", []):
                block["asset_paths"].append(str(crop_path))
            block["review_flags"] = [
                f for f in block.get("review_flags") or []
                if f.get("code") not in {"FORMULA_TEXT_LAYER_UNVERIFIED", "FORMULA_TEXT_LAYER_FRAGMENT"}
            ]
            if not val["valid"]:
                add_block_flag(block, "LATEX_INVALID")
            if confidence is not None and confidence < LOW:
                add_block_flag(block, "LOW_CONFIDENCE", confidence=confidence)
            elif confidence is None and not agreed:
                add_block_flag(block, "VLM_UNSCORED_REVIEW")
            if repairs:
                add_block_flag(block, "OCR_VL_MARKS_REPAIRED", severity="info", repairs=repairs)
        else:
            norm, _ = normalize_text(raw_text, profile_name)
            if norm.strip() and not needs_ocr(norm)[0]:
                block["text"] = norm.strip()
                block["markdown"] = norm.strip()
                block["source"] = VL_SOURCE
                block["confidence"] = confidence
                block["confidence_meta"] = build_confidence_meta(
                    confidence, source=VL_SOURCE, score_kind=score_kind
                )
                block["block_crop_path"] = str(crop_path)
                if crop_path and str(crop_path) not in block.setdefault("asset_paths", []):
                    block["asset_paths"].append(str(crop_path))
                block["review_flags"] = [
                    f for f in block.get("review_flags") or []
                    if f.get("code") != "TEXT_ENCODING_REVIEW"
                ]
                if confidence is not None and confidence < LOW:
                    add_block_flag(block, "LOW_CONFIDENCE", confidence=confidence)
                elif confidence is None:
                    add_block_flag(block, "VLM_UNSCORED_REVIEW")
                if repairs:
                    add_block_flag(block, "OCR_VL_MARKS_REPAIRED", severity="info", repairs=repairs)

    scheduler.gpu_queue.map_calls(process_block, blocks)


def escalate_native_page(
    page: dict,
    tasks: list[RegionTask],
    out_dir: Path,
    assets_dir: Path,
    *,
    lang: str,
    profile_name: str,
    render_cache: PageRenderCache,
    scheduler: AdaptiveScheduler,
    telemetry: dict,
    config,
    vl_reader,
    region_enricher,
    dual_reader,
    inc_ocr_calls: Callable[[dict, int], None],
    execute_ruled_table_fn: Callable,
) -> None:
    pid = int(page["page_id"])
    rendered = render_cache.get_page_image(pid)
    page["page_image"] = str(rendered.path)
    page["source_image_sha256"] = rendered.sha256
    page["render_provenance"] = {
        "dpi": rendered.dpi,
        "width": rendered.width,
        "height": rendered.height,
    }

    by_id = {b.get("block_id"): b for b in page.get("blocks") or [] if b.get("block_id")}
    bad_blocks = [
        by_id[bid]
        for task in tasks
        if task.action == RegionAction.TEXT_OCR
        for bid in task.source_block_ids
        if bid in by_id
    ]
    if bad_blocks:
        inc_ocr_calls(telemetry, len(bad_blocks))
        recover_bad_native_blocks(
            page,
            rendered.path,
            profile=profile_name,
            language=lang,
            work=out_dir / "ocr" / f"p{pid:04d}_recovery",
            bad_blocks=bad_blocks,
        )
        still_bad = [
            b for b in bad_blocks
            if not (b.get("text") or "").strip() or is_garbled_text(b.get("text") or "")
        ]
        if still_bad and vl_reader is not None and config.router.vlm_mode != "off":
            vlm_read_native_blocks(
                page,
                still_bad,
                RegionAction.VLM_TEXT,
                out_dir,
                render_cache,
                scheduler,
                profile_name,
                vl_reader=vl_reader,
                region_timeout_seconds=config.router.region_timeout_seconds,
            )

    if region_enricher is not None:
        region_enricher.enrich_page(page, out_dir, rendered.path)
    else:
        table_tasks = [t for t in tasks if t.action in {RegionAction.RULED_TABLE_OCR, RegionAction.VLM_TABLE}]
        for task in table_tasks:
            execute_ruled_table_fn(
                page,
                task,
                target_block=by_id.get(task.source_block_ids[0]) if task.source_block_ids else None,
                out_dir=out_dir,
                assets_dir=assets_dir,
                lang=lang,
                render_cache=render_cache,
                scheduler=scheduler,
                telemetry=telemetry,
            )
        formula_blocks = [
            by_id[bid]
            for task in tasks
            if task.action == RegionAction.VLM_FORMULA and not task.budget_skipped
            for bid in task.source_block_ids
            if bid in by_id
        ]
        if formula_blocks and vl_reader is not None:
            vlm_read_native_blocks(
                page,
                formula_blocks,
                RegionAction.VLM_FORMULA,
                out_dir,
                render_cache,
                scheduler,
                profile_name,
                vl_reader=vl_reader,
                region_timeout_seconds=config.router.region_timeout_seconds,
            )

    if dual_reader is not None:
        dual_read_page(
            page,
            rendered.path,
            dual_reader,
            selective=config.router.enable_selective_verification,
            risk_confidence_threshold=config.router.early_exit_ocr_confidence,
        )
    prepare_page_figures(page, out_dir)
    page["classification"] = classify_page(page.get("blocks") or [])
