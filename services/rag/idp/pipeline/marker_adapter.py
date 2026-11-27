"""Marker JSON ingestion adapter for precomputed structured page artifacts."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from idp.backends.native.pdf import make_block, make_page
from idp.evidence.cross_read import dual_read_page
from idp.evidence.fusion import vl_reread_page
from idp.processing.figure import (
    assign_section_paths,
    attach_captions,
    classify_page,
    decode_images,
    load_blocks,
    prepare_page_figures,
)
from idp.processing.formula import normalize_latex, normalize_text, validate_latex
from idp.processing.render import sha256_file


def run_marker_pages(
    marker_json_by_page: dict[int, str | Path],
    page_images_by_page: dict[int, str | Path],
    out_dir: Path,
    assets_dir: Path,
    *,
    profile_name: str,
    region_enricher,
    vl_reader,
    dual_reader,
) -> tuple[list[dict], str]:
    pages: list[dict] = []
    for pid in sorted(marker_json_by_page):
        raw_blocks = load_blocks(marker_json_by_page[pid])
        img_path = Path(page_images_by_page[pid]) if pid in page_images_by_page else None
        page_size = [1000.0, 1400.0]
        img_sha = None
        if img_path is not None and img_path.is_file():
            with Image.open(img_path) as opened:
                page_size = [float(opened.width), float(opened.height)]
            img_sha = sha256_file(img_path)

        blocks: list[dict] = []
        for order, raw in enumerate(raw_blocks):
            bid = f"p{pid:04d}_b{order:03d}"
            saved_assets = decode_images(raw.get("images") or {}, assets_dir / f"p{pid:04d}", bid)
            text, _ = normalize_text(raw.get("text") or "", profile_name)
            latex = [normalize_latex(x, profile_name) for x in raw.get("latex") or [] if str(x).strip()]
            blk = make_block(
                bid,
                raw.get("block_type") or "Text",
                raw.get("bbox"),
                text,
                text or (f"$$\n{latex[0]}\n$$" if latex else ""),
                latex=latex,
                asset_paths=saved_assets,
                excluded=bool(raw.get("excluded_from_content")),
                review_flags=list(raw.get("provider_review_flags") or []),
            )
            blk["latex_validation"] = [validate_latex(x).as_dict() for x in latex]
            blk["layout_score"] = raw.get("layout_score")
            blk["confidence"] = raw.get("confidence")
            blk["source"] = raw.get("engine") or "marker"
            blk["source_evidence"] = raw.get("source_evidence")
            blk["recovery_region_id"] = raw.get("recovery_region_id")
            blocks.append(blk)

        page = make_page(
            pid,
            blocks,
            page_size,
            page_number=pid,
            source_image_sha256=img_sha,
            page_image=str(img_path) if img_path else None,
        )
        page["parser"] = "marker"
        page["profile"] = profile_name
        if region_enricher is not None and img_path is not None:
            region_enricher.enrich_page(page, out_dir, img_path)
        if vl_reader is not None and img_path is not None:
            vl_reread_page(page, img_path, vl_reader, replace_all_text=False)
        if dual_reader is not None and img_path is not None:
            dual_read_page(page, img_path, dual_reader)
        prepare_page_figures(page, out_dir)
        assign_section_paths(page["blocks"])
        attach_captions(page["blocks"])
        page["classification"] = classify_page(page["blocks"])
        page["processing_status"] = "ok"
        pages.append(page)
    return pages, "pdf_ocr"
