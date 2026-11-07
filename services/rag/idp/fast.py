from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import statistics
import time
import shutil
from contextlib import nullcontext
from pathlib import Path

from PIL import Image

from .chunk import build_chunks, build_document
from .normalize import normalize_text
from .pipeline import collect_review, ensure_page_image, sha256_file
from .preprocess import analyze_page
from .validate_output import validate_outputs
from .enrichment import enrichment_summary
from .filetypes import choose_ocr_language, assert_tesseract_languages_loaded

FAST_VERSION = "idp-fast-0.11"
LINE_SPLIT_RE = re.compile(r"(?=<span[^>]*class=['\"]ocr_line['\"])", re.I)
BBOX_RE = re.compile(r"bbox (\d+) (\d+) (\d+) (\d+)", re.I)
WORD_RE = re.compile(
    r"<span[^>]*class=['\"]ocrx_word['\"][^>]*title=['\"]([^'\"]*)['\"][^>]*>(.*?)</span>",
    re.S | re.I,
)


def _run_tesseract(
    image: Path,
    base: Path,
    lang: str,
    psm: int,
    timeout: int = 120,
) -> str:
    from .ocr_io import read_tesseract
    return read_tesseract(image, base, lang, psm, output_format="hocr", timeout=timeout).decode("utf-8", errors="replace")


def parse_hocr_lines(hocr: str, profile: str = "general") -> list[dict]:
    lines = []
    for chunk in LINE_SPLIT_RE.split(hocr)[1:]:
        bbox_match = BBOX_RE.search(chunk)
        if not bbox_match:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox_match.groups()]
        words = []
        for match in WORD_RE.finditer(chunk):
            title, raw = match.groups()
            score = re.search(r"x_wconf (\d+)", title)
            word_bbox = BBOX_RE.search(title)
            if score is None or word_bbox is None:
                continue
            text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if text:
                bbox = [int(v) for v in word_bbox.groups()]
                if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                    words.append({"text": text, "bbox": bbox, "confidence": int(score.group(1))})
        if not words:
            continue
        # hOCR line boxes can span a neighbouring column even when recognized
        # words occupy only one side. Use actual word geometry for coverage and
        # citations; split a clear column gap without changing recognized words.
        gap = max(30, 2.5 * statistics.median(w["bbox"][3] - w["bbox"][1] for w in words))
        groups = [[]]
        for word in words:
            if groups[-1] and word["bbox"][0] - groups[-1][-1]["bbox"][2] > gap:
                groups.append([])
            groups[-1].append(word)
        for group in groups:
            text, _ = normalize_text(" ".join(w["text"] for w in group), profile)
            lines.append({
                "bbox": [min(w["bbox"][0] for w in group), min(w["bbox"][1] for w in group), max(w["bbox"][2] for w in group), max(w["bbox"][3] for w in group)],
                "layout_bbox": [x1, y1, x2, y2],
                "text_bbox": [min(w["bbox"][0] for w in group), statistics.median(w["bbox"][1] for w in group), max(w["bbox"][2] for w in group), statistics.median(w["bbox"][3] for w in group)],
                "text": text, "words": group,
                "confidence": round(sum(w["confidence"] for w in group) / len(group), 1),
            })
    return lines


def _page(
    page_id: int, image: Path, lines: list[dict], out: Path, make_crops: bool,
    analysis: dict | None = None,
) -> dict:
    image_obj = Image.open(image).convert("RGB")
    width, height = image_obj.size
    analysis = analysis or {}
    blocks = []
    for order, line in enumerate(lines):
        block_id = f"p{page_id:04d}_b{order:03d}"
        crop_path = None
        if make_crops:
            asset_dir = out / "assets" / f"p{page_id:04d}"
            asset_dir.mkdir(parents=True, exist_ok=True)
            crop_path = asset_dir / f"{block_id}_block.jpg"
            x1, y1, x2, y2 = line["bbox"]
            image_obj.crop((max(0, x1 - 2), max(0, y1 - 2), min(width, x2 + 2), min(height, y2 + 2))).save(
                crop_path, quality=88
            )
        blocks.append({
            "order": order,
            "block_id": block_id,
            "block_type": "Text",
            "bbox": line["bbox"],
            "html": f"<p>{html.escape(line['text'])}</p>",
            "text": line["text"],
            "markdown": line["text"],
            "latex": [],
            "latex_validation": [],
            "images": {},
            "section_hierarchy": {},
            "section_path": [],
            "asset_paths": [str(crop_path)] if crop_path else [],
            "block_crop_path": str(crop_path) if crop_path else None,
            "excluded_from_content": False,
            "review_flags": [{
                "code": "FAST_OCR_REVIEW",
                "severity": "warning",
                "confidence": line["confidence"],
            }],
            "page": page_id,
            "source": "tesseract_fast",
            "confidence": line["confidence"] / 100,
            "recovery_region_id": line.get("recovery_region_id"),
        })
    status = "ok"
    page_type = "fast_text"
    review = [{
        "page": page_id, "block_id": None, "block_type": "Page",
        "bbox": None, "code": "FAST_OCR_REVIEW", "severity": "warning",
    }]
    if not blocks:
        if analysis.get("blank"):
            status = "blank"
            page_type = "blank"
            review = []
        else:
            status = "layout_failed"
            page_type = "fast_empty"
            review = [{
                "page": page_id, "block_id": None, "block_type": "Page",
                "bbox": None, "code": "FAST_OCR_EMPTY", "severity": "error",
            }]
    else:
        for key, code in (
            ("needs_deskew", "PAGE_NEEDS_DESKEW"),
            ("low_contrast", "PAGE_LOW_CONTRAST"),
            ("blurry", "PAGE_BLURRY"),
            ("faint_content_only", "PAGE_FAINT_CONTENT_REVIEW"),
        ):
            if analysis.get(key):
                review.append({
                    "page": page_id, "block_id": None, "block_type": "Page",
                    "bbox": None, "code": code, "severity": "warning",
                })
    return {
        "page_id": page_id,
        "page_image": str(image),
        "page_size": [width, height],
        "page_number": None,
        "classification": {
            "page_type": page_type,
            "has_text": bool(blocks),
            "figure_count": 0,
            "formula_count": 0,
        },
        "blocks": blocks,
        "review": review,
        "processing_status": status,
        "pipeline_version": FAST_VERSION,
        "preprocessing": {**analysis, "width": width, "height": height, "fast_mode": True},
        "source_image_sha256": sha256_file(image),
        "marker_json_sha256": None,
    }


def run_fast(
    pdf_path: str | Path,
    page_ids: list[int],
    out_dir: str | Path,
    dpi: int = 300,
    lang: str = "vie",
    psm: int = 3,
    make_crops: bool = True,
    profile: str = "general",
    region_recovery: bool = True,
    layout_detector=None,
    recovery_options=None,
    region_enricher=None,
    prepared_pages: dict[int, dict] | None = None,
) -> dict:
    pdf_path = Path(pdf_path)
    lang, _ = choose_ocr_language(lang)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work" / "tesseract"
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pages = []
    timings = []
    prepared_evidence = []
    source_sha256 = sha256_file(pdf_path)
    if prepared_pages is not None and (set(prepared_pages) != set(page_ids) or any(type(k) is not int for k in prepared_pages)):
        raise ValueError("prepared page manifest must cover exactly the requested pages")
    for page_id in page_ids:
        image = out / "work" / "pages" / f"p{page_id:04d}.png"
        if prepared_pages is None:
            ensure_page_image(pdf_path, page_id, image, dpi=dpi)
        else:
            item = prepared_pages[page_id]
            original = Path(item["image"]).resolve()
            if (item.get("source_sha256") != source_sha256 or not original.is_file()
                    or original.stat().st_size > 64_000_000 or sha256_file(original) != item.get("image_sha256")):
                raise ValueError("prepared page source/image hash mismatch or file limit")
            with Image.open(original) as opened:
                if opened.format not in {"PNG", "JPEG"} or opened.width * opened.height > 16_000_000:
                    raise ValueError("prepared page format/pixel limit")
                size = list(opened.size)
                opened.verify()
            image.parent.mkdir(parents=True, exist_ok=True)
            if original != image.resolve():
                shutil.copyfile(original, image)
            if sha256_file(image) != item["image_sha256"]:
                raise ValueError("prepared page bytes changed during copy")
            # Do not leave a prior pdftoppm/dpi sidecar authorizing these newly
            # supplied pixels as if they came from that old render operation.
            image.with_name(image.name + ".source.json").write_text(json.dumps({
                "source_sha256": source_sha256, "page_id": page_id, "rendering": "provided",
                "image_sha256": item["image_sha256"]}), "utf-8")
            prepared_evidence.append({"page": page_id, "source_sha256": source_sha256,
                "image_sha256": item["image_sha256"], "size": size})
        page_started = time.perf_counter()
        hocr = _run_tesseract(image, work / f"p{page_id:04d}", lang, psm)
        lines = parse_hocr_lines(hocr, profile=profile)
        recovery = None
        if region_recovery:
            from .recovery import recover_text_regions

            lines, recovery = recover_text_regions(
                image, lines, out / "work" / "recovery" / f"p{page_id:04d}",
                lang=lang, profile=profile, detector=layout_detector, options=recovery_options,
            )
        analysis = analyze_page(image)
        page = _page(page_id, image, lines, out, make_crops, analysis)
        if recovery is not None:
            page["region_recovery"] = recovery
            page["review"].extend({"page": page_id, "block_id": None, "block_type": "Page", "bbox": None, **flag} for flag in recovery["flags"])
        if region_enricher:
            region_enricher.enrich_page(page, out, image)
        pages.append(page)
        timings.append({
            "page": page_id,
            "seconds": round(time.perf_counter() - page_started, 3),
            "lines": len(lines),
            "status": page["processing_status"],
            "recovery_seconds": recovery["seconds"] if recovery else 0,
            "recovered_lines": recovery["lines_added"] if recovery else 0,
        })
        (out / "pages").mkdir(parents=True, exist_ok=True)
        (out / "pages" / f"p{page_id:04d}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (out / "pages" / f"p{page_id:04d}.md").write_text(
            "\n".join(block["markdown"] for block in page["blocks"]) + "\n",
            encoding="utf-8",
        )
    if sha256_file(pdf_path) != source_sha256:
        raise ValueError("source PDF changed during fast ingestion")
    chunks = build_chunks(pages)
    # Chunk analysis adds lossless question provenance and review flags.
    # Persist those annotations rather than leaving stale per-page JSON.
    for page in pages:
        (out / "pages" / f"p{page['page_id']:04d}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    document = build_document(pages, chunks)
    review = collect_review(pages)
    validation = validate_outputs(out, pages, chunks)
    report = {
        "mode": "fast_preview",
        "structured_enrichment": enrichment_summary(pages),
        "region_recovery_enabled": region_recovery,
        "recovered_lines": sum(t["recovered_lines"] for t in timings),
        "recovery_seconds": round(sum(t["recovery_seconds"] for t in timings), 3),
        "pages_with_recovery": [p["page_id"] for p in pages if (p.get("region_recovery") or {}).get("lines_added")],
        "recovery_unresolved_regions": sum(
            1 for p in pages for r in (p.get("region_recovery") or {}).get("regions", [])
            if r["status"] != "recovered"
        ),
        "pipeline_version": FAST_VERSION,
        "pages": len(pages),
        "lines": sum(t["lines"] for t in timings),
        "chunks": len(chunks),
        "publishable_chunks": sum(1 for c in chunks if c["publishable"]),
        "review_required_chunks": sum(1 for c in chunks if c["review_required"]),
        "pages_without_content": sum(
            1 for p in pages if p["processing_status"] == "layout_failed"
        ),
        "blank_pages": sum(1 for p in pages if p["processing_status"] == "blank"),
        "empty_pages": [
            p["page_id"] for p in pages if p["processing_status"] == "layout_failed"
        ],
        "pages_blurry": sum(
            1 for p in pages if p["preprocessing"].get("blurry")
        ),
        "pages_low_contrast": sum(
            1 for p in pages if p["preprocessing"].get("low_contrast")
        ),
        "pages_needing_deskew": sum(
            1 for p in pages if p["preprocessing"].get("needs_deskew")
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "page_seconds": timings,
        "output_validation_errors": validation,
    }
    manifest = {
        "doc_id": source_sha256,
        "mode": "fast_preview",
        "pipeline_version": FAST_VERSION,
        "pages_requested": page_ids,
        "pages_processed": [p["page_id"] for p in pages],
        "dpi": None if prepared_pages is not None else dpi,
        "rendering": "provided" if prepared_pages is not None else "pdftoppm",
        "prepared_pages": prepared_evidence,
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "document.json").write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8"
    )
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "review_queue.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in review), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast CPU text-only ingestion preview")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--lang", default="vie")
    parser.add_argument("--profile", default="general")
    parser.add_argument("--psm", type=int, default=3)
    parser.add_argument("--no-crops", action="store_true")
    parser.add_argument("--no-region-recovery", action="store_true")
    parser.add_argument("--prepared-pages", type=Path, help="optional hash-bound rendered-page manifest; no implicit PDF rerender")
    parser.add_argument("--layout-model-dir", type=Path, help="optional local PP-DocLayoutV2 model; requires PaddleOCR runtime")
    parser.add_argument("--layout-policy", choices=("default", "v3_vl16"), default="default", help="experimental upstream V3 nested-region policy")
    parser.add_argument("--region-budget", type=float, default=15)
    from .enrichment import add_structured_arguments, structured_context
    add_structured_arguments(parser)
    args = parser.parse_args()
    from .cli import parse_pages

    from .recovery import PaddleLayoutDetector, cli_recovery_options

    options = cli_recovery_options(parser, args)
    prepared_pages = None
    if args.prepared_pages:
        if args.prepared_pages.stat().st_size > 2_000_000:
            parser.error("prepared page manifest byte limit")
        rows = json.loads(args.prepared_pages.read_text("utf-8"))["pages"]
        if not isinstance(rows, list) or any(type(r.get("page")) is not int for r in rows):
            parser.error("prepared pages require integer page IDs")
        prepared_pages = {row["page"]: row for row in rows}
        if len(prepared_pages) != len(rows):
            parser.error("duplicate prepared page ID")
    with (
        (PaddleLayoutDetector(args.layout_model_dir, layout_policy=args.layout_policy) if args.layout_model_dir else nullcontext(None)) as detector,
        structured_context(args, parser, detector, args.lang) as enricher,
    ):
        report = run_fast(
            args.pdf, parse_pages(args.pages), args.out, args.dpi, args.lang,
            args.psm, not args.no_crops, profile=args.profile,
            region_recovery=not args.no_region_recovery, layout_detector=detector,
            recovery_options=options,
            region_enricher=enricher,
            prepared_pages=prepared_pages,
        )
    print(json.dumps({
        "pages": report["pages"],
        "lines": report["lines"],
        "chunks": report["chunks"],
        "publishable_chunks": report["publishable_chunks"],
        "elapsed_seconds": report["elapsed_seconds"],
        "page_seconds_p50": sorted(t["seconds"] for t in report["page_seconds"])[len(report["page_seconds"]) // 2],
        "page_seconds_p95": sorted(t["seconds"] for t in report["page_seconds"])[int(len(report["page_seconds"]) * 0.95) - 1],
    }, ensure_ascii=False, indent=1))
    return 0 if not report["output_validation_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
