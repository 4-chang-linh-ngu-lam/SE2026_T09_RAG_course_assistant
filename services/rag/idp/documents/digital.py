"""Digital-document ingestion: text PDF, DOCX, TXT.

This is the fast path for files that already contain text. It does not OCR.
PDF uses PyMuPDF; DOCX uses pandoc when available (OMML equations -> LaTeX);
TXT is read directly.
"""

from __future__ import annotations

import argparse
import csv
import email
import hashlib
import html
import io
import json
import re
import subprocess
import time
import zipfile
from contextlib import nullcontext
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

from idp.canonical import audit_canonical, build_canonical
from idp.input.filetypes import InputError, InputLimits, detect_file_type, validate_input
from idp.documents.normalize import normalize_text
from idp.input.profiles import resolve_profile
from idp.documents.text_quality import is_garbled_text, needs_ocr, repeated_watermark_tokens
from idp.validation.validate import incomplete_formula_reasons, validate_latex
from idp.validation.validate_output import validate_outputs
from idp.structured.enrichment import enrichment_summary

PIPELINE_VERSION = "idp-digital-0.16"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def _strip_html(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _encoding_issues(text: str) -> list[str]:
    issues = []
    if "\ufffd" in text:
        issues.append("replacement_char")
    if re.search(r"\(cid:\d+\)", text):
        issues.append("cid_text")
    controls = sum(
        1 for ch in text if ord(ch) < 32 and ch not in "\n\t\r"
    )
    if controls:
        issues.append("control_chars")
    letters = sum(1 for ch in text if ch.isalpha())
    middle_dots = text.count("·")
    if middle_dots >= 3 and middle_dots / max(1, letters) > 0.02:
        issues.append("middle_dot_substitution")
    return issues


def _column_reading_order(entries: list[dict], page_width: float) -> list[dict]:
    """Order a clean two-column page left column then right column.

    The plain y-then-x sort interleaves columns. This conservative pass only
    activates when every entry lives wholly in one half and both columns have
    real text; a full-width header/footer or a spanning table disables it.
    Mirrors RAGFlow's final reading-order merge without inventing column IDs.
    """
    if len(entries) < 6 or page_width <= 0:
        return entries
    mid = page_width / 2
    gutter = max(4.0, page_width * 0.03)
    left, right = [], []
    for entry in entries:
        bbox = entry.get("bbox")
        if not bbox or len(bbox) < 4:
            return entries
        x1, x2 = float(bbox[0]), float(bbox[2])
        if x2 <= mid - gutter:
            left.append(entry)
        elif x1 >= mid + gutter:
            right.append(entry)
        else:
            return entries
    text_left = sum(1 for entry in left if entry.get("kind") == "text")
    text_right = sum(1 for entry in right if entry.get("kind") == "text")
    if text_left < 3 or text_right < 3:
        return entries

    def order(column):
        return sorted(
            column,
            key=lambda entry: (float(entry["bbox"][1]), float(entry["bbox"][0])),
        )

    return order(left) + order(right)


def _drop_watermark_entries(
    entries: list[dict]
) -> tuple[list[dict], list[str]]:
    tokens = repeated_watermark_tokens([
        entry.get("text") or ""
        for entry in entries
        if entry.get("kind") == "text"
    ])
    # Compatibility name: repetition alone cannot distinguish a watermark
    # from answer labels, diagram labels or table cells. Never delete them.
    return entries, tokens


def _clean_table_rows(rows: list[list[str]]) -> list[list[str]]:
    """Drop all-empty rows before scoring or rendering a table.

    RAGFlow drops all-empty rows before emitting a table. Empty columns are
    kept here: without TSR cell coordinates a sparse one-column table is still
    a real table and must be flagged, not silently narrowed.
    """
    cleaned = []
    for row in rows or []:
        cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]
        if any(cells):
            cleaned.append(cells)
    return cleaned


def _md_table(rows: list[list[str]]) -> str:
    cleaned = _clean_table_rows(rows)
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header = cleaned[0]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in cleaned[1:]:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def _rows_to_html(rows: list[list[str]]) -> str:
    cleaned = _clean_table_rows(rows)
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    out = ["<table>"]
    for row in cleaned:
        row = row + [""] * (width - len(row))
        out.append(
            "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
        )
    out.append("</table>")
    return "".join(out)


def _table_metrics(rows: list[list[str]]) -> dict:
    source_rows = []
    for row in rows or []:
        cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]
        if any(cells):
            source_rows.append(cells)
    if not source_rows:
        return {
            "rows": 0, "cols": 0, "filled": 0, "fill_ratio": 0.0,
            "empty_cols": 0, "ragged": 0, "score": 0.0, "needs_review": True,
        }
    n_rows = len(source_rows)
    n_cols = max(len(row) for row in source_rows)
    ragged = sum(1 for row in source_rows if len(row) != n_cols)
    padded = [row + [""] * (n_cols - len(row)) for row in source_rows]
    filled = sum(1 for row in padded for cell in row if cell)
    fill_ratio = filled / max(1, n_rows * n_cols)
    header_filled = sum(1 for cell in padded[0] if cell)
    empty_cols = sum(
        1 for col in range(n_cols)
        if not any(padded[row][col] for row in range(n_rows))
    )
    long_cells = sum(1 for row in padded for cell in row if len(cell) > 300)
    max_cell_len = max(
        (len(cell) for row in padded for cell in row), default=0
    )
    math_cells = sum(
        1 for row in padded for cell in row
        if re.search(r"[=^_{}\\]|[a-z]\s+\d", cell)
    )
    score = 0.0
    if n_rows >= 2:
        score += 0.30
    if n_cols >= 2:
        score += 0.25
    if n_cols >= 3:
        score += 0.05
    score += min(0.25, fill_ratio * 0.35)
    if header_filled >= 1:
        score += 0.10
    if n_rows >= 3:
        score += 0.05
    if empty_cols == 0:
        score += 0.05
    score -= min(0.3, empty_cols * 0.1 + ragged * 0.05)
    score -= min(0.3, long_cells / max(1, filled) * 0.5)
    score = round(max(0.0, min(1.0, score)), 4)
    needs_review = (
        n_rows < 2 or n_cols < 2 or filled < 2 or fill_ratio < 0.25
        or header_filled == 0 or empty_cols > 0 or ragged > 0
        or math_cells > 0
    )
    return {
        "rows": n_rows, "cols": n_cols, "filled": filled,
        "fill_ratio": round(fill_ratio, 4), "empty_cols": empty_cols,
        "ragged": ragged, "max_cell_len": max_cell_len, "math_cells": math_cells,
        "score": score, "needs_review": needs_review,
    }


def _score_tables(tables: list[dict]) -> dict:
    metrics = [_table_metrics(table["rows"]) for table in tables]
    weight = sum(max(1, m["filled"]) for m in metrics) or 1
    score = (
        sum(m["score"] * max(1, m["filled"]) for m in metrics) / weight
        if metrics else 0.0
    )
    return {
        "score": round(score, 4),
        "tables": metrics,
        "needs_review": any(m["needs_review"] for m in metrics),
    }


def _usable_tables(tables: list[dict], width: float, height: float) -> list[dict]:
    usable = []
    page_area = max(1.0, float(width) * float(height))
    for table in tables:
        rows = table.get("rows") or []
        metrics = _table_metrics(rows)
        if metrics["rows"] < 2 or metrics["cols"] < 2 or metrics["filled"] < 2:
            continue
        bbox = table.get("bbox") or [0, 0, 0, 0]
        area_ratio = (
            max(0.0, float(bbox[2]) - float(bbox[0]))
            * max(0.0, float(bbox[3]) - float(bbox[1]))
            / page_area
        )
        layout_table = (
            area_ratio >= 0.55
            and metrics["rows"] <= 4
            and (
                metrics["max_cell_len"] > 80
                or metrics["fill_ratio"] < 0.5
            )
        )
        full_page_layout = (
            area_ratio >= 0.8
            and metrics["rows"] <= 4
            and metrics["cols"] <= 4
            and metrics["max_cell_len"] > 40
        )
        grid_graph = metrics["cols"] >= 6 and metrics["fill_ratio"] < 0.2
        if layout_table or full_page_layout or grid_graph or metrics["max_cell_len"] > 2000:
            continue
        usable.append(table)
    return usable


TABLE_ENGINES = ("auto", "pymupdf", "pdfplumber")


def _engine_order(engine: str) -> list[str]:
    if engine == "auto":
        return ["pdfplumber", "pymupdf"]
    return [engine]


def _open_pdfplumber(path: Path, engine: str):
    if engine not in {"auto", "pdfplumber"}:
        return None
    try:
        import pdfplumber
    except ImportError as exc:
        if engine == "pdfplumber":
            raise RuntimeError(
                "table engine pdfplumber cần cài `pip install pdfplumber`"
            ) from exc
        return None
    return pdfplumber.open(path)


def _pymupdf_tables(page) -> list[dict]:
    tables = []
    for table in page.find_tables().tables:
        rows = _clean_table_rows(table.extract())
        if rows:
            tables.append({"rows": rows, "bbox": list(table.bbox)})
    return tables


def _pdfplumber_tables(plumber_page) -> list[dict]:
    tables = []
    found = plumber_page.find_tables()
    for table in found:
        rows = _clean_table_rows(table.extract())
        if not rows:
            continue
        bbox = getattr(table, "bbox", None)
        if not bbox:
            continue
        tables.append({"rows": rows, "bbox": [float(x) for x in bbox]})
    return tables


def _block(block_id, block_type, bbox, text="", markdown=None, latex=None,
           asset_paths=None, review_flags=None, section_path=None,
           excluded=False, formula_text=None):
    return {
        "block_id": block_id,
        "block_type": block_type,
        "bbox": list(bbox) if bbox else None,
        "text": text or "",
        "markdown": markdown if markdown is not None else (text or ""),
        "latex": list(latex or []),
        "asset_paths": list(asset_paths or []),
        "review_flags": list(review_flags or []),
        "section_path": list(section_path or []),
        "excluded_from_content": bool(excluded),
        "formula_text": formula_text or "",
    }


def _page(page_id, blocks, page_size=None, classification="content", page_number=None):
    review = [f for b in blocks for f in b["review_flags"] if f.get("severity") in {"warning", "error"}]
    return {
        "page_id": page_id,
        "page_number": page_number if page_number is not None else page_id,
        "page_size": list(page_size) if page_size else None,
        "classification": classification,
        "blocks": blocks,
        "review": review,
        "processing_status": "ok",
        "pipeline_version": PIPELINE_VERSION,
    }


def _markdown_for_page(blocks) -> str:
    out = []
    for b in blocks:
        if b.get("excluded_from_content"):
            continue
        md = (b.get("markdown") or b.get("text") or "").strip()
        if md:
            out.append(md)
    return "\n\n".join(out).strip()


def _has_table_grid(page) -> bool:
    try:
        drawings = page.get_drawings()
    except Exception:
        return False
    horizontal = vertical = 0
    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.x - p2.x) <= 1.0:
                vertical += 1
            elif abs(p1.y - p2.y) <= 1.0:
                horizontal += 1
    return horizontal >= 4 and vertical >= 3


def _render_pdf_page(
    pdf_path: Path,
    page_id: int,
    target: Path,
    dpi: int,
    max_longest_dim: int = 2000,
) -> Path:
    import fitz

    with fitz.open(pdf_path) as doc:
        page = doc[page_id - 1]
        longest = max(page.rect.width, page.rect.height)
        scale = min(dpi / 72.0, max_longest_dim / max(1.0, longest))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(target))
    return target


def _recover_bad_blocks(
    page: dict,
    image_path: Path,
    profile: str,
    language: str | None,
    work: Path,
) -> int:
    """OCR only empty/garbled text blocks, preserving the good text layer.

    This mirrors MinerU's native-text + empty-span OCR instead of replacing the
    whole page when a single region is broken.
    """
    from idp.ocr.fallback import crop_text_with_orientation
    from idp.input.filetypes import choose_ocr_language

    bad = [
        block for block in page["blocks"]
        if block.get("block_type") in {"Text", "ListGroup", "SectionHeader"}
        and block.get("bbox")
        and (
            not (block.get("text") or "").strip()
            or is_garbled_text(block.get("text") or "")
        )
    ]
    if not bad:
        return 0
    chosen, _ = choose_ocr_language(language)
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    work.mkdir(parents=True, exist_ok=True)
    recovered_count = 0
    for block in bad:
        x1, y1, x2, y2 = [int(round(float(v))) for v in block["bbox"]]
        pad = 6
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(width, x2 + pad), min(height, y2 + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = image.crop((x1, y1, x2, y2))
        try:
            recovered, confidence, angle = crop_text_with_orientation(
                crop,
                work,
                block["block_id"],
                lang=chosen,
                psm=6,
                profile=profile,
            )
        except Exception as exc:
            block["review_flags"].append({
                "code": "TEXT_OCR_RECOVERY_FAILED",
                "severity": "warning",
                "reason": str(exc)[:200],
            })
            continue
        recovered, _ = normalize_text(recovered, profile)
        recovered = recovered.strip()
        if recovered and not needs_ocr(recovered)[0]:
            block["text"] = recovered
            block["markdown"] = recovered
            block["source"] = "tesseract"
            block["confidence"] = confidence
            block["ocr_rotation"] = angle
            block["review_flags"].append({
                "code": "TEXT_OCR_RECOVERED",
                "severity": "info",
                "confidence": confidence,
                "rotation": angle,
            })
            if confidence < 0.60:
                block["review_flags"].append({
                    "code": "TEXT_OCR_RECOVERY_LOW_CONFIDENCE",
                    "severity": "warning",
                    "confidence": confidence,
                    "rotation": angle,
                })
            recovered_count += 1
        elif recovered:
            block["review_flags"].append({
                "code": "TEXT_OCR_RECOVERY_LOW_QUALITY",
                "severity": "warning",
                "text": recovered[:200],
                "confidence": confidence,
                "rotation": angle,
            })
        else:
            block["review_flags"].append({
                "code": "EMPTY_BLOCK",
                "severity": "warning",
            })
    page_review = [
        {
            "page": page["page_id"],
            "block_id": block["block_id"],
            "block_type": block["block_type"],
            "bbox": block["bbox"],
            **flag,
        }
        for block in page["blocks"]
        for flag in block.get("review_flags") or []
        if flag.get("severity") in {"warning", "error"}
    ]
    existing = {
        (item.get("block_id"), item.get("code")) for item in page.get("review") or []
    }
    for item in page_review:
        if (item.get("block_id"), item.get("code")) not in existing:
            page.setdefault("review", []).append(item)
    return recovered_count


def _marker_confidence(path: Path) -> float:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        children = data["children"][0].get("children") or []
        values = [
            float(child["_idp_confidence"]) / 100.0
            for child in children
            if child.get("_idp_confidence") is not None
        ]
        return sum(values) / len(values) if values else 0.0
    except Exception:
        return 0.0


def _marker_line_count(path: Path) -> int:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return len(data["children"][0].get("children") or [])
    except Exception:
        return 0


def _ocr_pdf_page(
    pdf_path: Path,
    page_id: int,
    out: Path,
    profile: str,
    language: str | None,
    dpi: int,
    region_recovery: bool = True,
    layout_detector=None,
    recovery_options=None,
) -> dict:
    from idp.ocr.fallback import tesseract_marker
    from idp.input.filetypes import choose_ocr_language
    from idp.orchestration.pipeline import extract_page
    from idp.documents.preprocess import analyze_page, preprocess_image

    work = out / "work" / "ocr_fallback"
    image = _render_pdf_page(
        pdf_path, page_id, work / "images" / f"p{page_id:04d}.png", dpi
    )
    analysis = analyze_page(image)
    chosen, _ = choose_ocr_language(language)
    attempts = []

    def run_marker(candidate_image: Path, stage: str, stage_dpi: int, longest: int):
        try:
            found = tesseract_marker(
                candidate_image, page_id, work / f"markers_{stage}",
                lang=chosen, profile=profile,
                recover_regions=False,
            )
            found_confidence = _marker_confidence(found)
            found_lines = _marker_line_count(found)
            attempts.append({
                "stage": stage,
                "dpi": stage_dpi,
                "longest_px": longest,
                "confidence": round(found_confidence, 4),
                "lines": found_lines,
            })
            return found, found_confidence, found_lines
        except Exception as exc:
            attempts.append({
                "stage": stage,
                "dpi": stage_dpi,
                "longest_px": longest,
                "error": str(exc)[:200],
            })
            return None, 0.0, 0

    marker, confidence, line_count = run_marker(image, "base", dpi, 2000)
    current_dpi = dpi

    # RAGFlow re-renders a page at a higher zoom when OCR produced nothing
    # useful. Only pay for the second render on genuinely bad pages.
    if (
        dpi < 450
        and not analysis.get("blank")
        and (marker is None or confidence < 0.45 or line_count < 3)
    ):
        high_dpi = min(max(dpi + 150, int(round(dpi * 1.5))), 450)
        high_image = _render_pdf_page(
            pdf_path, page_id, work / "images_high" / f"p{page_id:04d}.png",
            high_dpi, max_longest_dim=3000,
        )
        high_marker, high_confidence, high_lines = run_marker(
            high_image, "high_dpi", high_dpi, 3000
        )
        if high_marker is not None and (
            marker is None or high_confidence > confidence
        ):
            image = high_image
            marker, confidence, line_count = (
                high_marker, high_confidence, high_lines
            )
            current_dpi = high_dpi
            # Retry geometry/contrast decisions must describe the selected
            # render, not the lower-resolution image that lost selection.
            analysis = analyze_page(image)
            analysis["ocr_high_dpi_improved"] = True
        elif high_marker is not None:
            analysis["ocr_high_dpi_no_gain"] = True

    should_retry = (
        marker is None
        or confidence < 0.60
        or analysis.get("blurry")
        or analysis.get("low_contrast")
        or analysis.get("needs_deskew")
    )
    if should_retry:
        corrected = preprocess_image(
            image, work / "preprocessed" / f"p{page_id:04d}.png", analysis
        )
        if analysis.get("blurry"):
            corrected_image = Image.open(corrected)
            corrected_image = corrected_image.resize(
                (int(corrected_image.width * 1.5), int(corrected_image.height * 1.5)),
                Image.Resampling.LANCZOS,
            )
            corrected_image.save(corrected)
        with Image.open(corrected) as probe:
            corrected_longest = max(probe.size)
        retry_marker, retry_confidence, retry_lines = run_marker(
            Path(corrected), "preprocess", current_dpi, corrected_longest
        )
        if retry_marker is not None and (
            marker is None or retry_confidence > confidence
        ):
            image = Path(corrected)
            marker = retry_marker
            confidence = retry_confidence
            line_count = retry_lines
            analysis["ocr_preprocess_improved"] = True
        elif retry_marker is not None:
            analysis["ocr_preprocess_no_gain"] = True
        else:
            analysis["ocr_preprocess_failed"] = True
    analysis["ocr_attempts"] = attempts

    if marker is None:
        raise RuntimeError("tesseract produced no text after preprocess retry")
    recovery = None
    if region_recovery:
        from idp.ocr.recovery import recover_marker

        marker, recovery = recover_marker(
            marker, image, work / "recovery" / f"p{page_id:04d}",
            lang=chosen, profile=profile, detector=layout_detector, options=recovery_options,
        )
    page = extract_page(
        page_id=page_id,
        page_image_path=image,
        marker_json_path=marker,
        out_dir=out,
        run_text_candidate=False,
        source_label="tesseract_fallback",
        profile=profile,
        language=chosen,
    )
    page["processing_status"] = "ok"
    page["page_number"] = page_id
    page["ocr_language"] = chosen
    page["preprocessing"] = analysis
    page["ocr_confidence"] = round(confidence, 4)
    page.setdefault("review", [])
    page["review"].append({
        "page": page_id, "block_id": None, "block_type": "Page", "bbox": None,
        "code": "FALLBACK_ENGINE_REVIEW", "severity": "warning",
    })
    if recovery is not None:
        page["region_recovery"] = recovery
        page["review"].extend({"page": page_id, "block_id": None, "block_type": "Page", "bbox": None, **f} for f in recovery["flags"])
    if confidence < 0.60:
        page["review"].append({
            "page": page_id, "block_id": None, "block_type": "Page",
            "bbox": None, "code": "OCR_LOW_CONFIDENCE",
            "severity": "warning", "confidence": round(confidence, 4),
        })
    if analysis.get("ocr_high_dpi_improved"):
        page["review"].append({
            "page": page_id, "block_id": None, "block_type": "Page",
            "bbox": None, "code": "OCR_HIGH_DPI_IMPROVED",
            "severity": "info", "dpi": current_dpi,
        })
    if analysis.get("ocr_preprocess_improved"):
        page["review"].append({
            "page": page_id, "block_id": None, "block_type": "Page",
            "bbox": None, "code": "OCR_PREPROCESS_IMPROVED",
            "severity": "info",
        })
    for key, code in (
        ("needs_deskew", "PAGE_NEEDS_DESKEW"),
        ("low_contrast", "PAGE_LOW_CONTRAST"),
        ("faint_content_only", "PAGE_FAINT_CONTENT_REVIEW"),
        ("blurry", "PAGE_BLURRY"),
    ):
        if analysis.get(key):
            page["review"].append({
                "page": page_id,
                "block_id": None,
                "block_type": "Page",
                "bbox": None,
                "code": code,
                "severity": "warning",
            })
    return page


def _pdf_blocks(path: Path, assets: Path, tables: str = "off", table_engine: str = "auto"):
    plumber = _open_pdfplumber(path, table_engine) if tables != "off" else None
    try:
        return _pdf_blocks_open(path, assets, tables, table_engine, plumber)
    finally:
        if plumber is not None:
            plumber.close()


def _pdf_blocks_open(path: Path, assets: Path, tables: str, table_engine: str, plumber):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(path)
    all_sizes = []
    pages_raw = []

    for page_index, page in enumerate(doc):
        entries = []
        table_rects = []
        attempts = []
        chosen_engine = None
        try:
            page_text = page.get_text()
        except Exception:
            page_text = ""
        is_toc = bool(re.search(
            r"\bmục\s*lục\b|\bcontents\b|table of contents",
            page_text, re.I,
        ))
        if tables != "off" and not is_toc:
            has_grid = _has_table_grid(page)
            if tables == "on" or (tables == "auto" and has_grid):
                candidates = []
                for engine in _engine_order(table_engine):
                    if engine == "pdfplumber":
                        if plumber is None:
                            attempts.append({"engine": engine, "error": "unavailable"})
                            continue
                        try:
                            plumber_page = plumber.pages[page_index]
                            detected = _pdfplumber_tables(plumber_page)
                            raw_tables = _usable_tables(
                                detected, plumber_page.width, plumber_page.height
                            )
                        except Exception as exc:
                            attempts.append({
                                "engine": engine, "error": repr(exc)[:300],
                            })
                            continue
                    else:
                        try:
                            detected = _pymupdf_tables(page)
                            raw_tables = _usable_tables(
                                detected, page.rect.width, page.rect.height
                            )
                        except Exception as exc:
                            attempts.append({
                                "engine": engine, "error": repr(exc)[:300],
                            })
                            continue
                    scored = _score_tables(raw_tables)
                    attempts.append({
                        "engine": engine,
                        "tables": len(raw_tables),
                        "rejected": max(0, len(detected) - len(raw_tables)),
                        "score": scored["score"],
                        "needs_review": scored["needs_review"],
                    })
                    if raw_tables:
                        candidates.append((scored["score"], engine, raw_tables, scored))
                    if engine == table_engine:
                        break
                    if table_engine == "auto" and (raw_tables or detected or not has_grid):
                        break
                if candidates:
                    candidates.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
                    _, chosen_engine, raw_tables, scored = candidates[0]
                    for raw_table, metrics in zip(raw_tables, scored["tables"]):
                        md = _md_table(raw_table["rows"])
                        if not md:
                            continue
                        flags = []
                        if metrics["needs_review"]:
                            flags.append({
                                "code": "TABLE_STRUCTURE_REVIEW",
                                "severity": "warning",
                                "reason": "table extraction looks incomplete or irregular",
                                "metrics": metrics,
                            })
                        if len(raw_tables) > 1 and metrics["needs_review"]:
                            flags.append({
                                "code": "TABLE_MULTI_REVIEW",
                                "severity": "info",
                                "table_count": len(raw_tables),
                            })
                        entries.append({
                            "kind": "table", "bbox": raw_table["bbox"], "markdown": md,
                            "text": _strip_html(md), "table_engine": chosen_engine,
                            "table_metrics": metrics, "review_flags": flags,
                        })
                        table_rects.append(fitz.Rect(raw_table["bbox"]))

        try:
            data = page.get_text("dict")
        except Exception:
            data = {"blocks": []}
        for raw in data.get("blocks", []):
            if raw.get("type") != 0:
                continue
            lines = []
            sizes = []
            fonts = []
            for line in raw.get("lines", []):
                parts = []
                for span in line.get("spans", []):
                    txt = span.get("text", "")
                    if txt:
                        parts.append(txt)
                        sizes.append(float(span.get("size", 0)))
                        fonts.append(span.get("font", ""))
                if parts:
                    lines.append("".join(parts))
            text = "\n".join(lines).strip()
            if not text:
                continue
            bbox = list(raw.get("bbox", [0, 0, 0, 0]))
            rect = fitz.Rect(bbox)
            if any((rect & tr).get_area() > max(1, rect.get_area()) * 0.5 for tr in table_rects):
                continue
            size = max(sizes) if sizes else 0
            all_sizes.append(size)
            entries.append({
                "kind": "text", "bbox": bbox, "text": text,
                "size": size, "fonts": fonts,
            })

        # Extract images.
        seen = set()
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            if not rects:
                continue
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            ext = info.get("ext", "png")
            target = assets / f"p{page_index + 1:04d}_img{xref}.{ext}"
            target.write_bytes(info["image"])
            entries.append({
                "kind": "image", "bbox": list(rects[0]),
                "asset": str(target), "caption": "",
            })

        entries.sort(key=lambda e: (float(e["bbox"][1]), float(e["bbox"][0])))
        entries = _column_reading_order(entries, float(page.rect.width))
        entries, watermark_tokens = _drop_watermark_entries(entries)
        pages_raw.append({
            "page": page, "index": page_index, "entries": entries,
            "width": float(page.rect.width), "height": float(page.rect.height),
            "table_attempts": attempts, "table_engine": chosen_engine,
            "watermark_tokens": watermark_tokens,
        })

    median_size = sorted(all_sizes)[len(all_sizes) // 2] if all_sizes else 10.0
    pages = []
    for item in pages_raw:
        page_no = item["index"] + 1
        blocks = []
        section_path = []
        section_stack = []
        for idx, e in enumerate(item["entries"]):
            bbox = e["bbox"]
            bid = f"p{page_no:04d}_b{idx:03d}"
            if e["kind"] == "table":
                table_block = _block(
                    bid, "Table", bbox, e["text"], e["markdown"],
                    section_path=list(section_path),
                    review_flags=e.get("review_flags") or [],
                )
                table_block["table_engine"] = e.get("table_engine")
                table_block["table_metrics"] = e.get("table_metrics")
                blocks.append(table_block)
                continue
            if e["kind"] == "image":
                blocks.append(_block(bid, "Picture", bbox, e.get("caption", ""),
                                     f"![]({e['asset']})", asset_paths=[e["asset"]],
                                     section_path=list(section_path)))
                continue
            text = e["text"]
            size = e["size"]
            fonts = " ".join(e.get("fonts") or [])
            y0, y1 = float(bbox[1]), float(bbox[3])
            btype = "Text"
            flags = []
            level = None
            if y0 < item["height"] * 0.04 or y1 > item["height"] * 0.96:
                btype = "PageHeader" if y0 < item["height"] * 0.5 else "PageFooter"
            elif size >= median_size * 1.12 and len(text) <= 180 and "\n" not in text:
                btype = "SectionHeader"
                level = 1 if size >= median_size * 1.35 else 2
            else:
                math_chars = len(re.findall(r"[=+\-×÷^_{}\\√∑∫∞≤≥<>]", text))
                math_font = bool(re.search(r"CMMI|CMSY|CMEX|Symbol|Math", fonts, re.I))
                if math_chars >= 4 and (math_font or math_chars / max(1, len(text)) > 0.08):
                    btype = "Equation"
                    flags.append({
                        "block_id": bid, "code": "FORMULA_TEXT_LAYER_UNVERIFIED",
                        "severity": "warning",
                    })
            if btype == "SectionHeader":
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, text))
                section_path[:] = [x[1] for x in section_stack]
            if btype not in {"PageHeader", "PageFooter"}:
                encoding_issues = _encoding_issues(text)
                if encoding_issues:
                    flags.append({
                        "code": "TEXT_ENCODING_REVIEW",
                        "severity": "warning",
                        "issues": encoding_issues,
                    })
            md = text
            if btype == "SectionHeader":
                md = f"{'#' * min(6, level)} {text}"
            blocks.append(_block(
                bid, btype, bbox, text, md, section_path=list(section_path),
                review_flags=flags,
                formula_text=text if btype == "Equation" else None,
            ))
        page_obj = _page(page_no, blocks, [item["width"], item["height"]],
                         page_number=page_no)
        page_obj["table_extraction"] = {
            "engine": item.get("table_engine"),
            "attempts": item.get("table_attempts", []),
        }
        tokens = item.get("watermark_tokens") or []
        if tokens:
            page_obj["watermark_candidates"] = tokens
            page_obj["review"].append({
                "page": page_no,
                "block_id": None,
                "block_type": "Page",
                "bbox": None,
                "code": "WATERMARK_CANDIDATE_REVIEW",
                "severity": "warning",
                "tokens": tokens,
            })
        layer_text = " ".join(b.get("text") or "" for b in blocks)
        needed, layer_reason = needs_ocr(layer_text)
        if layer_reason == "repeated_url_only_text_layer":
            page_obj["text_layer_audit"] = {"status": "rejected_for_primary", "reason": layer_reason, "text": layer_text, "source": "pymupdf"}
            page_obj["review"].append({"page": page_no, "block_id": None,
                "code": "PAGE_TEXT_LAYER_UNUSABLE", "severity": "warning", "reason": layer_reason})
        pages.append(page_obj)
    return pages


def _pandoc_json_file(path: Path, assets: Path):
    try:
        import pypandoc
    except ImportError as exc:
        raise RuntimeError(
            "DOCX cần pypandoc/pandoc. Cài `pip install pypandoc_binary` "
            "hoặc cài pandoc hệ thống."
        ) from exc
    assets.mkdir(parents=True, exist_ok=True)
    raw = pypandoc.convert_file(
        str(path), "json", format="docx",
        extra_args=[f"--extract-media={assets}"],
    )
    return json.loads(raw)


def _pandoc_json_text(text: str):
    try:
        import pypandoc
    except ImportError:
        return None
    try:
        return json.loads(pypandoc.convert_text(
            text, "json",
            format="markdown+pipe_tables+tex_math_dollars",
        ))
    except Exception:
        return None


def _asset_path(assets: Path, target: str) -> Path | None:
    if not target:
        return None
    candidate = Path(target)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    candidates = [
        assets / target,
        assets / candidate.name,
        assets / "media" / candidate.name,
    ]
    if target.startswith("/c/"):
        candidates.append(Path("C:/" + target[3:]))
    for p in candidates:
        if p.exists():
            return p
    return None


def _inlines_text(inlines) -> str:
    out = []
    for node in inlines or []:
        t = node.get("t")
        c = node.get("c")
        if t == "Str":
            out.append(str(c))
        elif t == "Space":
            out.append(" ")
        elif t in {"SoftBreak", "LineBreak"}:
            out.append("\n" if t == "LineBreak" else " ")
        elif t in {"Emph", "Strong", "Strikeout", "Superscript", "Subscript", "SmallCaps", "Quoted"}:
            out.append(_inlines_text(c[1] if t == "Quoted" else c))
        elif t == "Code":
            out.append(str(c[1]) if isinstance(c, list) and len(c) > 1 else str(c))
        elif t == "Math":
            out.append("$" + str(c[1]) + "$")
        elif t == "Link":
            out.append(_inlines_text(c[1]))
        elif t == "Image":
            out.append(_inlines_text(c[1]))
        elif t == "Note":
            out.append(_blocks_text(c))
    return "".join(out)


def _inlines_md(inlines, assets: Path, latex: list, images: list) -> str:
    out = []
    for node in inlines or []:
        t = node.get("t")
        c = node.get("c")
        if t == "Str":
            out.append(str(c))
        elif t == "Space":
            out.append(" ")
        elif t == "SoftBreak":
            out.append(" ")
        elif t == "LineBreak":
            out.append("\n")
        elif t == "Emph":
            out.append("*" + _inlines_md(c, assets, latex, images) + "*")
        elif t == "Strong":
            out.append("**" + _inlines_md(c, assets, latex, images) + "**")
        elif t == "Strikeout":
            out.append("~~" + _inlines_md(c, assets, latex, images) + "~~")
        elif t == "Superscript":
            out.append("^" + _inlines_md(c, assets, latex, images) + "^")
        elif t == "Subscript":
            out.append("~" + _inlines_md(c, assets, latex, images) + "~")
        elif t == "Code":
            out.append("`" + str(c[1]) + "`")
        elif t == "Math":
            tex = str(c[1])
            latex.append(tex)
            out.append(("$$" + tex + "$$") if c[0].get("t") == "DisplayMath" else ("$" + tex + "$"))
        elif t == "Link":
            out.append("[" + _inlines_md(c[1], assets, latex, images) + "](" + str(c[2][0]) + ")")
        elif t == "Image":
            target = str(c[2][0])
            asset = _asset_path(assets, target)
            if asset:
                images.append((str(asset), _inlines_text(c[1])))
            out.append("![" + _inlines_text(c[1]) + "](" + target + ")")
        elif t == "Quoted":
            out.append("“" + _inlines_md(c[1], assets, latex, images) + "”")
        elif t == "Note":
            out.append(_blocks_md(c, assets, latex, images))
    return "".join(out)


def _blocks_text(blocks) -> str:
    out = []
    for b in blocks or []:
        t = b.get("t")
        c = b.get("c")
        if t in {"Para", "Plain"}:
            out.append(_inlines_text(c))
        elif t == "Header":
            out.append(_inlines_text(c[2]))
        elif t == "CodeBlock":
            out.append(str(c[1]))
        elif t == "BlockQuote":
            out.append(_blocks_text(c))
        elif t == "Table":
            out.append(_table_text(c))
        elif t in {"BulletList", "OrderedList"}:
            items = c[1] if t == "OrderedList" else c
            out.append("\n".join(_blocks_text(x) for x in items))
        elif t == "Figure":
            out.append(_blocks_text(c[1]) + "\n" + _blocks_text(c[2]))
    return "\n".join(x for x in out if x.strip())


def _blocks_md(blocks, assets: Path, latex: list, images: list) -> str:
    out = []
    for b in blocks or []:
        t = b.get("t")
        c = b.get("c")
        if t in {"Para", "Plain"}:
            out.append(_inlines_md(c, assets, latex, images))
        elif t == "Header":
            out.append("#" * min(6, int(c[0])) + " " + _inlines_md(c[2], assets, latex, images))
        elif t == "CodeBlock":
            out.append("```\n" + str(c[1]) + "\n```")
        elif t == "BlockQuote":
            out.append("> " + _blocks_md(c, assets, latex, images).replace("\n", "\n> "))
        elif t == "Table":
            out.append(_table_html(c, assets, latex, images))
        elif t in {"BulletList", "OrderedList"}:
            items = c[1] if t == "OrderedList" else c
            for idx, item in enumerate(items, 1):
                prefix = f"{idx}. " if t == "OrderedList" else "- "
                out.append(prefix + _blocks_md(item, assets, latex, images).replace("\n", "\n  "))
        elif t == "Figure":
            cap = _blocks_md(c[1], assets, latex, images)
            body = _blocks_md(c[2], assets, latex, images)
            out.append((cap + "\n" + body).strip())
    return "\n\n".join(x for x in out if x.strip())


def _table_text(tbl) -> str:
    _, caption, _, head, bodies, foot = tbl
    rows = []
    if head and head[1]:
        rows.extend(head[1])
    for body in bodies or []:
        rows.extend(body[3])
    if foot and foot[1]:
        rows.extend(foot[1])
    text_rows = []
    for row in rows:
        cells = []
        for cell in row[1]:
            cells.append(_blocks_text(cell[4]))
        text_rows.append(" | ".join(cells))
    cap = _blocks_text(caption[1]) if caption and len(caption) > 1 else ""
    return (cap + "\n" + "\n".join(text_rows)).strip()



def _blocks_html(blocks, assets: Path, latex: list, images: list) -> str:
    out = []
    for b in blocks or []:
        t = b.get("t")
        c = b.get("c")
        if t in {"Para", "Plain"}:
            md = _inlines_md(c, assets, latex, images)
            out.append(html.escape(md).replace("\n", "<br/>"))
        elif t == "Table":
            out.append(_table_html(c, assets, latex, images))
        elif t == "Header":
            md = _inlines_md(c[2], assets, latex, images)
            out.append("<strong>" + html.escape(md) + "</strong>")
        elif t in {"BulletList", "OrderedList"}:
            items = c[1] if t == "OrderedList" else c
            tag = "ol" if t == "OrderedList" else "ul"
            body = "".join("<li>" + _blocks_html(item, assets, latex, images) + "</li>" for item in items)
            out.append(f"<{tag}>{body}</{tag}>")
        elif t == "CodeBlock":
            out.append("<pre>" + html.escape(str(c[1])) + "</pre>")
        elif t == "BlockQuote":
            out.append("<blockquote>" + _blocks_html(c, assets, latex, images) + "</blockquote>")
        elif t == "Figure":
            out.append(_blocks_html(c[2], assets, latex, images))
    return "".join(out)


def _table_html(tbl, assets: Path, latex: list, images: list) -> str:
    _, caption, colspecs, head, bodies, foot = tbl
    rows = []
    merged = False
    if head and head[1]:
        rows.append(("head", head[1]))
    for body in bodies or []:
        if body[2]:
            rows.append(("head", body[2]))
        rows.append(("body", body[3]))
    if foot and foot[1]:
        rows.append(("body", foot[1]))

    out = ["<table>"]
    cap = _blocks_text(caption[1]) if caption and len(caption) > 1 else ""
    if cap:
        out.append(f"<caption>{html.escape(cap)}</caption>")
    for section, section_rows in rows:
        if section == "head":
            out.append("<thead>")
        elif section == "body" and (not out or out[-1] != "<tbody>"):
            out.append("<tbody>")
        for row in section_rows:
            out.append("<tr>")
            for cell in row[1]:
                _, align, rowspan, colspan, cell_blocks = cell
                if int(rowspan) > 1 or int(colspan) > 1:
                    merged = True
                tag = "th" if section == "head" else "td"
                attrs = []
                if align and align.get("t") == "AlignCenter":
                    attrs.append('style="text-align:center"')
                if align and align.get("t") == "AlignRight":
                    attrs.append('style="text-align:right"')
                if int(rowspan) > 1:
                    attrs.append(f'rowspan="{int(rowspan)}"')
                if int(colspan) > 1:
                    attrs.append(f'colspan="{int(colspan)}"')
                _blocks_md(cell_blocks, assets, latex, images)
                plain_cell = _blocks_text(cell_blocks)
                cell_html = html.escape(plain_cell).replace("\n", "<br/>")
                out.append(f"<{tag} {' '.join(attrs)}>{cell_html}</{tag}>")
            out.append("</tr>")
        if section == "head":
            out.append("</thead>")
        else:
            out.append("</tbody>")
    out.append("</table>")
    return "".join(out)


def _is_strong_para(inlines) -> bool:
    meaningful = [
        x for x in (inlines or [])
        if not (x.get("t") in {"Space", "SoftBreak", "LineBreak"})
    ]
    return bool(meaningful) and all(x.get("t") == "Strong" for x in meaningful)


def _ast_blocks(ast_blocks, assets: Path):
    blocks = []
    section_stack = []
    section_path = []

    def add(block_type, text="", markdown=None, latex=None, images=None,
            flags=None, bbox=None):
        block = _block(
            f"b{len(blocks):04d}", block_type, bbox, text,
            markdown if markdown is not None else text,
            latex=latex or [], asset_paths=images or [],
            section_path=list(section_path),
            review_flags=flags or [],
        )
        block["order"] = len(blocks)
        blocks.append(block)

    def walk(nodes):
        for node in nodes or []:
            t = node.get("t")
            c = node.get("c")
            if t == "Header":
                level = int(c[0])
                text = _inlines_text(c[2])
                tex = []
                imgs = []
                md = _inlines_md(c[2], assets, tex, imgs)
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, text))
                section_path[:] = [x[1] for x in section_stack]
                add("SectionHeader", text, "#" * min(6, level) + " " + md,
                    latex=tex, images=imgs)
            elif t in {"Para", "Plain"}:
                tex, imgs = [], []
                md = _inlines_md(c, assets, tex, imgs)
                text = _inlines_text(c)
                cap_heading = text.strip().isupper() and len(text.strip()) <= 90
                if (_is_strong_para(c) and len(text.strip()) <= 180) or cap_heading:
                    level = 2
                    while section_stack and section_stack[-1][0] >= level:
                        section_stack.pop()
                    section_stack.append((level, text.strip()))
                    section_path[:] = [x[1] for x in section_stack]
                    add("SectionHeader", text.strip(), "## " + md.strip(),
                        latex=tex, images=[x[0] for x in imgs])
                    continue
                if text.strip():
                    add("Text", text, md, latex=tex, images=[x[0] for x in imgs])
                for asset, alt in imgs:
                    flags = []
                    if not alt.strip():
                        flags.append({
                            "block_id": f"b{len(blocks):04d}",
                            "code": "FIGURE_CAPTION_REVIEW",
                            "severity": "warning",
                        })
                    add("Picture", alt, f"![{alt}]({Path(asset).as_posix()})",
                        images=[asset], flags=flags)
            elif t == "Table":
                tex, imgs = [], []
                table_html = _table_html(c, assets, tex, imgs)
                table_text = _table_text(c)
                merged = "rowspan=" in table_html or "colspan=" in table_html
                flags = [{
                    "block_id": f"b{len(blocks):04d}",
                    "code": "TABLE_MERGED_CELLS",
                    "severity": "warning",
                }] if merged else []
                add("Table", table_text, table_html, latex=tex,
                    images=[x[0] for x in imgs], flags=flags)
            elif t in {"BulletList", "OrderedList"}:
                items = c[1] if t == "OrderedList" else c
                text = "\n".join(_blocks_text(item) for item in items)
                tex, imgs = [], []
                md = _blocks_md([node], assets, tex, imgs)
                if text.strip():
                    add("Text", text, md, latex=tex, images=[x[0] for x in imgs])
            elif t == "Figure":
                cap = _blocks_text(c[1])
                tex, imgs = [], []
                body = _blocks_md(c[2], assets, tex, imgs)
                if imgs:
                    for asset, alt in imgs:
                        add("Picture", cap or alt,
                            f"![{cap or alt}]({Path(asset).as_posix()})",
                            images=[asset],
                            flags=[] if cap else [{
                                "block_id": f"b{len(blocks):04d}",
                                "code": "FIGURE_CAPTION_REVIEW",
                                "severity": "warning",
                            }])
                elif cap.strip():
                    add("Text", cap, cap)
            elif t == "Div":
                walk(c[1])
            elif t == "BlockQuote":
                text = _blocks_text(c)
                tex, imgs = [], []
                md = _blocks_md(c, assets, tex, imgs)
                if text.strip():
                    add("Text", text, "> " + md, latex=tex, images=[x[0] for x in imgs])
            elif t == "CodeBlock":
                text = str(c[1])
                add("Text", text, "```\n" + text + "\n```")
            # Ignore HorizontalRule, RawBlock, Null and unknown container blocks.

    walk(ast_blocks)
    return blocks


def _docx_pages(path: Path, assets: Path):
    ast = _pandoc_json_file(path, assets)
    blocks = _ast_blocks(ast.get("blocks", []), assets)
    return [_page(1, blocks, None, page_number=1)]


def _txt_pages(path: Path, assets: Path):
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        for enc in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")

    ast = _pandoc_json_text(text)
    if ast is not None:
        blocks = _ast_blocks(ast.get("blocks", []), assets)
        return [_page(1, blocks, None, page_number=1)]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    blocks = []
    for idx, p in enumerate(paragraphs):
        bid = f"p0001_b{idx:03d}"
        is_heading = len(p) <= 90 and (p.isupper() or p.endswith(":"))
        btype = "SectionHeader" if is_heading else "Text"
        md = f"# {p}" if btype == "SectionHeader" else p
        blocks.append(_block(bid, btype, None, p, md))
    return [_page(1, blocks, None, page_number=1)]


def _copy_asset(assets: Path, source_dir: Path, src: str, prefix: str) -> str | None:
    if not src or src.startswith(("http://", "https://", "data:")):
        return None
    path = Path(src)
    # Uploaded Markdown/HTML may reference local files. Only copy assets from
    # the upload's own directory, including after resolving symlinks/junctions.
    source_root = source_dir.resolve()
    if path.is_absolute():
        return None
    path = (source_root / path).resolve()
    if not path.is_relative_to(source_root):
        return None
    if not path.exists() or not path.is_file():
        return None
    suffix = path.suffix.lower() or ".bin"
    target = assets / f"{prefix}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(path.read_bytes())
    return str(target)


def _md_plain(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _md_pages(path: Path, assets: Path, profile: str):
    text, _ = _decode_txt(path)
    lines = text.splitlines()
    blocks: list[dict] = []
    section_path: list[str] = []

    def add(btype: str, plain: str, md: str, **kwargs) -> None:
        blocks.append(_block(
            f"p0001_b{len(blocks):03d}",
            btype,
            None,
            normalize_text(plain, profile)[0],
            md,
            **kwargs,
        ))

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("```"):
            idx += 1
            code = []
            while idx < len(lines) and not lines[idx].strip().startswith("```"):
                code.append(lines[idx])
                idx += 1
            idx += 1
            body = "\n".join(code)
            add("Text", body, "```\n" + body + "\n```")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = _md_plain(heading.group(2))
            section_path[:] = section_path[: level - 1]
            section_path.append(title)
            blocks.append(_block(
                f"p0001_b{len(blocks):03d}",
                "SectionHeader",
                None,
                normalize_text(title, profile)[0],
                stripped,
                section_path=list(section_path),
            ))
            idx += 1
            continue
        if stripped.startswith("|") and idx + 1 < len(lines):
            rows = []
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                cells = [
                    _md_plain(c)
                    for c in lines[idx].strip().strip("|").split("|")
                ]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                idx += 1
            if rows:
                table_html = _rows_to_html(rows)
                table_text = " ".join(" ".join(row) for row in rows)
                block = _block(
                    f"p0001_b{len(blocks):03d}",
                    "Table",
                    None,
                    table_text,
                    table_html,
                    section_path=list(section_path),
                )
                block["table_html"] = table_html
                blocks.append(block)
            continue
        image = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image:
            alt, src = image.group(1), image.group(2).strip()
            local = _copy_asset(assets, path.parent, src, f"md_{len(blocks):03d}")
            flags = [] if local else [{
                "code": "IMAGE_REMOTE_OR_MISSING",
                "severity": "warning",
            }]
            add("Picture", alt, stripped,
                asset_paths=[local] if local else [], review_flags=flags,
                section_path=list(section_path))
            idx += 1
            continue
        if stripped:
            paragraphs = [stripped]
            idx += 1
            while (
                idx < len(lines)
                and lines[idx].strip()
                and not lines[idx].strip().startswith(("#", "|", "```", "!["))
            ):
                paragraphs.append(lines[idx].strip())
                idx += 1
            body = " ".join(paragraphs)
            add("Text", _md_plain(body), body, section_path=list(section_path))
            continue
        idx += 1
    return [_page(1, blocks, None, page_number=1)]


class _HtmlCollector(HTMLParser):
    HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self, assets: Path, source_dir: Path, profile: str):
        super().__init__(convert_charrefs=True)
        self.assets = assets
        self.source_dir = source_dir
        self.profile = profile
        self.blocks: list[dict] = []
        self.section_path: list[str] = []
        self.current: dict | None = None
        self.skip = 0
        self.table_rows: list[list[str]] = []
        self.table_row: list[str] | None = None
        self.table_cell: list[str] | None = None
        self.loose_text: list[str] = []

    def _add(self, btype: str, text: str, md: str | None = None, **kwargs):
        text = normalize_text(text, self.profile)[0]
        if not text.strip() and btype not in {"Picture"}:
            return
        self.blocks.append(_block(
            f"p0001_b{len(self.blocks):03d}",
            btype,
            None,
            text,
            md if md is not None else text,
            **kwargs,
        ))

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            self.table_rows = []
            self.table_row = None
            self.table_cell = None
            return
        if self.table_rows is not None and tag == "tr":
            self.table_row = []
            return
        if self.table_row is not None and tag in {"td", "th"}:
            self.table_cell = []
            return
        if tag == "img":
            src = attrs.get("src", "")
            alt = attrs.get("alt", "")
            local = _copy_asset(
                self.assets, self.source_dir, src, f"html_{len(self.blocks):03d}"
            )
            self._add(
                "Picture", alt, f"![{alt}]({src})",
                asset_paths=[local] if local else [],
                review_flags=[] if local else [{
                    "code": "IMAGE_REMOTE_OR_MISSING", "severity": "warning",
                }],
            )
            return
        if self.current is not None or self.table_cell is not None:
            return
        if tag in self.HEADINGS:
            level = self.HEADINGS[tag]
            self.current = {"type": "SectionHeader", "level": level, "parts": []}
        elif tag in {"p", "li", "pre", "blockquote", "figcaption"}:
            btype = "Text"
            self.current = {"type": btype, "tag": tag, "parts": []}

    def handle_data(self, data):
        if self.skip:
            return
        if self.table_cell is not None:
            self.table_cell.append(data)
            return
        if self.current is not None:
            self.current["parts"].append(data)
        elif data.strip():
            self.loose_text.append(data.strip())

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "table":
            if self.table_rows:
                table_html = _rows_to_html(self.table_rows)
                text = " ".join(" ".join(r) for r in self.table_rows)
                block = _block(
                    f"p0001_b{len(self.blocks):03d}",
                    "Table",
                    None,
                    text,
                    table_html,
                    section_path=list(self.section_path),
                )
                block["table_html"] = table_html
                self.blocks.append(block)
            self.table_rows = []
            return
        if tag == "tr" and self.table_row is not None:
            if self.table_row:
                self.table_rows.append(self.table_row)
            self.table_row = None
            return
        if tag in {"td", "th"} and self.table_cell is not None:
            if self.table_row is not None:
                self.table_row.append(" ".join(self.table_cell).strip())
            self.table_cell = None
            return
        if self.current is None:
            return
        if tag in self.HEADINGS or tag in {"p", "li", "pre", "blockquote", "figcaption"}:
            body = " ".join(" ".join(self.current["parts"]).split())
            if self.current["type"] == "SectionHeader":
                level = self.current["level"]
                self.section_path[:] = self.section_path[: level - 1]
                self.section_path.append(body)
                self._add(
                    "SectionHeader", body, "#" * level + " " + body,
                    section_path=list(self.section_path),
                )
            else:
                self._add("Text", body, section_path=list(self.section_path))
            self.current = None


def _html_pages(path: Path, assets: Path, profile: str):
    raw, _ = _decode_txt(path)
    parser = _HtmlCollector(assets, path.parent, profile)
    parser.feed(raw)
    parser.close()
    if not parser.blocks and parser.loose_text:
        parser._add("Text", " ".join(parser.loose_text))
    return [_page(1, parser.blocks, None, page_number=1)]


def _csv_pages(path: Path, assets: Path, profile: str):
    raw, _ = _decode_txt(path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = []
    flags = []
    for row in csv.reader(io.StringIO(raw), delimiter=delimiter):
        rows.append([str(cell) for cell in row])
        if len(rows) >= 2001:
            flags.append({
                "code": "TABLE_TRUNCATED", "severity": "warning",
                "reason": "row limit 2000",
            })
            break
    if not rows:
        raise InputError("EMPTY_DOCUMENT", "CSV has no rows")
    width = max(len(row) for row in rows)
    if width > 100:
        flags.append({
            "code": "TABLE_TRUNCATED", "severity": "warning",
            "reason": "column limit 100",
        })
        rows = [row[:100] for row in rows]
    table_html = _rows_to_html(rows)
    table_text = " ".join(" ".join(row) for row in rows)
    block = _block(
        "p0001_b000", "Table", None, table_text, table_html,
        review_flags=flags, section_path=[path.stem],
    )
    block["table_html"] = table_html
    return [_page(1, [block], None, page_number=1)]


def _xlsx_pages(path: Path, assets: Path, profile: str):
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError(
            "xlsx ingestion requires openpyxl (`pip install openpyxl`)"
        ) from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pages = []
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets, 1):
            rows = []
            truncated = False
            for values in sheet.iter_rows(values_only=True):
                if len(rows) >= 2000:
                    truncated = True
                    break
                row = ["" if value is None else str(value) for value in values[:100]]
                if len(values) > 100:
                    truncated = True
                rows.append(row)
            blocks = [_block(
                f"p{sheet_index:04d}_b000", "SectionHeader", None,
                sheet.title, f"# {sheet.title}", section_path=[sheet.title],
            )]
            if rows:
                table_html = _rows_to_html(rows)
                block = _block(
                    f"p{sheet_index:04d}_b001", "Table", None,
                    " ".join(" ".join(row) for row in rows), table_html,
                    review_flags=[{
                        "code": "TABLE_TRUNCATED", "severity": "warning",
                        "reason": "row limit 2000",
                    }] if truncated else [],
                    section_path=[sheet.title],
                )
                block["table_html"] = table_html
                blocks.append(block)
            else:
                blocks.append(_block(
                    f"p{sheet_index:04d}_b001", "Text", None,
                    "", "", review_flags=[{
                        "code": "SHEET_EMPTY", "severity": "warning",
                    }], section_path=[sheet.title],
                ))
            pages.append(_page(sheet_index, blocks, None, page_number=sheet_index))
    finally:
        workbook.close()
    if not pages:
        raise InputError("EMPTY_DOCUMENT", "workbook has no sheets")
    return pages


def _pptx_pages(path: Path, assets: Path, profile: str):
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError as exc:
        raise RuntimeError(
            "pptx ingestion requires python-pptx (`pip install python-pptx`)"
        ) from exc
    presentation = Presentation(path)
    pages = []
    slide_size = [presentation.slide_width, presentation.slide_height]
    for slide_index, slide in enumerate(presentation.slides, 1):
        blocks = []
        title_shape = slide.shapes.title

        def collect(shape):
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                for child in shape.shapes:
                    collect(child)
                return
            bbox = [
                shape.left or 0, shape.top or 0,
                (shape.left or 0) + (shape.width or 0),
                (shape.top or 0) + (shape.height or 0),
            ]
            if shape.has_text_frame:
                text = "\n".join(
                    p.text for p in shape.text_frame.paragraphs if p.text.strip()
                ).strip()
                if text:
                    is_title = shape is title_shape
                    blocks.append(_block(
                        f"p{slide_index:04d}_b{len(blocks):03d}",
                        "SectionHeader" if is_title else "Text",
                        bbox,
                        text,
                        f"# {text}" if is_title else text,
                        section_path=[title_shape.text] if title_shape else [],
                    ))
            if shape.has_table:
                rows = [
                    [cell.text for cell in row.cells]
                    for row in shape.table.rows
                ]
                table_html = _rows_to_html(rows)
                block = _block(
                    f"p{slide_index:04d}_b{len(blocks):03d}",
                    "Table", bbox,
                    " ".join(" ".join(row) for row in rows), table_html,
                    section_path=[title_shape.text] if title_shape else [],
                )
                block["table_html"] = table_html
                blocks.append(block)
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                suffix = Path(shape.image.filename or "image.png").suffix or ".png"
                target = assets / f"pptx_{slide_index:03d}_{len(blocks):03d}{suffix}"
                target.write_bytes(shape.image.blob)
                blocks.append(_block(
                    f"p{slide_index:04d}_b{len(blocks):03d}",
                    "Picture", bbox, shape.name,
                    f"![{shape.name}]({target.as_posix()})",
                    asset_paths=[str(target)],
                    section_path=[title_shape.text] if title_shape else [],
                ))
            if shape.has_chart:
                blocks.append(_block(
                    f"p{slide_index:04d}_b{len(blocks):03d}",
                    "Text", bbox, f"[Chart: {shape.name}]",
                    f"[Chart: {shape.name}]",
                    review_flags=[{
                        "code": "CHART_NOT_EXTRACTED", "severity": "warning",
                    }],
                    section_path=[title_shape.text] if title_shape else [],
                ))

        for shape in slide.shapes:
            collect(shape)
        if not blocks:
            blocks.append(_block(
                f"p{slide_index:04d}_b000", "Text", None, "", "",
                review_flags=[{"code": "SLIDE_EMPTY", "severity": "warning"}],
            ))
        pages.append(_page(
            slide_index, blocks, slide_size, page_number=slide_index,
        ))
    if not pages:
        raise InputError("EMPTY_DOCUMENT", "presentation has no slides")
    return pages


def _email_pages(path: Path, assets: Path, profile: str):
    message = email.parser.BytesParser(policy=policy.default).parsebytes(
        path.read_bytes()
    )
    subject = str(message.get("Subject") or "").strip()
    blocks = []
    if subject:
        blocks.append(_block(
            "p0001_b000", "SectionHeader", None, subject, f"# {subject}",
            section_path=[subject],
        ))
    headers = [
        f"{name}: {message.get(name)}"
        for name in ("From", "To", "Cc", "Date")
        if message.get(name)
    ]
    if headers:
        blocks.append(_block(
            f"p0001_b{len(blocks):03d}", "Text", None,
            "\n".join(headers), "\n".join(headers),
        ))
    body_text = ""
    attachments = []
    if message.is_multipart():
        for part in message.walk():
            disposition = part.get_content_disposition()
            filename = part.get_filename()
            if disposition == "attachment" or filename:
                attachments.append(filename or part.get_content_type())
                continue
            if part.get_content_type() == "text/plain" and not body_text:
                try:
                    body_text = part.get_content()
                except Exception:
                    body_text = part.get_payload(decode=True).decode("utf-8", "replace")
            elif part.get_content_type() == "text/html" and not body_text:
                try:
                    body_text = _strip_html(part.get_content())
                except Exception:
                    body_text = ""
    else:
        try:
            body_text = message.get_content()
        except Exception:
            body_text = message.get_payload(decode=True).decode("utf-8", "replace")
        if message.get_content_type() == "text/html":
            body_text = _strip_html(body_text)
    if body_text.strip():
        blocks.append(_block(
            f"p0001_b{len(blocks):03d}", "Text", None,
            body_text.strip(), body_text.strip(),
            review_flags=[{
                "code": "EMAIL_BODY", "severity": "info",
            }],
        ))
    for filename in attachments:
        blocks.append(_block(
            f"p0001_b{len(blocks):03d}", "Text", None,
            f"[Attachment: {filename}]", f"[Attachment: {filename}]",
            review_flags=[{
                "code": "ATTACHMENT_NOT_INGESTED", "severity": "warning",
            }],
        ))
    if not blocks:
        raise InputError("EMPTY_DOCUMENT", "email has no readable body")
    return [_page(1, blocks, None, page_number=1)]


def _docx_source_audit(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        app = z.read("docProps/app.xml").decode("utf-8", "replace") if "docProps/app.xml" in names else ""
    media = [n for n in names if n.startswith("word/media/")]
    equations = len(re.findall(r"<m:oMath(?:>|\s)", xml))
    tables = xml.count("<w:tbl>")
    textboxes = xml.count("<w:txbxContent")
    charts = sum(1 for n in names if n.startswith("word/charts/")) + xml.count("<c:chart")
    ole = xml.count("<o:OLEObject")
    smartart = sum(1 for n in names if n.startswith("word/diagrams/"))
    comments = "word/comments.xml" in names
    tracked = xml.count("<w:ins ") + xml.count("<w:del ")
    headers = [n for n in names if n.startswith("word/header")]
    footers = [n for n in names if n.startswith("word/footer")]
    m = re.search(r"<Pages>(\d+)</Pages>", app)
    unsupported = []
    if textboxes:
        unsupported.append({"part": "textboxes", "count": textboxes})
    if charts:
        unsupported.append({"part": "charts", "count": charts})
    if ole:
        unsupported.append({"part": "ole_objects", "count": ole})
    if smartart:
        unsupported.append({"part": "smartart", "count": smartart})
    if comments:
        unsupported.append({"part": "comments", "count": 1})
    if tracked:
        unsupported.append({"part": "tracked_changes", "count": tracked})
    return {
        "tables": tables,
        "equations": equations,
        "media": len(media),
        "textboxes": textboxes,
        "charts": charts,
        "ole_objects": ole,
        "smartart": smartart,
        "comments": comments,
        "tracked_changes": tracked,
        "headers": len(headers),
        "footers": len(footers),
        "declared_pages": int(m.group(1)) if m else None,
        "unsupported_parts": unsupported,
    }


def _decode_txt(path: Path) -> tuple[str, str | None]:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _text_output_audit(pages) -> dict:
    return {
        "tables": sum(1 for p in pages for b in p["blocks"] if b["block_type"] == "Table"),
        "equations": sum(len(b.get("latex") or []) for p in pages for b in p["blocks"]),
        "images": sum(len(b.get("asset_paths") or []) for p in pages for b in p["blocks"]),
        "pictures": sum(1 for p in pages for b in p["blocks"] if b["block_type"] == "Picture"),
        "table_elements": sum(
            (b.get("markdown") or "").count("<table>")
            for p in pages for b in p["blocks"] if b["block_type"] == "Table"
        ),
    }

def _digital_audit(
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
                elif source_type == "pdf_text":
                    metrics = block.get("table_metrics")
                    if not metrics:
                        table_consistency.append(block["block_id"])
                    elif bool(metrics.get("needs_review")) != ("TABLE_STRUCTURE_REVIEW" in codes):
                        table_consistency.append(block["block_id"])
                elif not (block.get("markdown") or block.get("text")):
                    table_consistency.append(block["block_id"])
            if (
                source_type == "pdf_text"
                and block["block_type"] not in {"PageHeader", "PageFooter"}
                and _encoding_issues(block.get("text") or "")
                and "TEXT_ENCODING_REVIEW" not in codes
            ):
                encoding_unflagged.append(block["block_id"])

    checks = {
        "pages_present": {
            "value": len(pages),
            "pass": bool(pages) and all(p.get("blocks") is not None for p in pages),
        },
        "table_metrics_consistent": {
            "value": table_consistency,
            "pass": not table_consistency,
        },
        "encoding_flagged": {
            "value": encoding_unflagged,
            "pass": not encoding_unflagged,
        },
        "no_content_loss": {
            "value": content_loss,
            "pass": not any(content_loss.values()),
        },
        "output_validation": {
            "value": output_errors or [],
            "pass": not output_errors,
        },
    }
    return {
        "checks": checks,
        "pass": all(check["pass"] for check in checks.values()),
    }


def process(
    input_path: str | Path,
    out_dir: str | Path,
    tables: str = "off",
    strict: bool = False,
    table_engine: str = "auto",
    profile: str = "general",
    language: str | None = None,
    limits: InputLimits | None = None,
    ingestion_only: bool = True,
    ocr_fallback: bool = True,
    dpi: int = 300,
    source_acl: dict | None = None,
    source_metadata: dict | None = None,
    region_recovery: bool = True,
    layout_detector=None,
    recovery_options=None,
    region_enricher=None,
) -> dict:
    if not ingestion_only:
        raise ValueError("Chunking was removed from IDP; use the downstream indexing service")
    source = Path(input_path).resolve()
    out = Path(out_dir).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    resolved_profile = resolve_profile(profile)
    limits = limits or InputLimits()
    file_kind = detect_file_type(source)
    input_info = validate_input(source, file_kind, limits)
    source_audit = {"file_kind": file_kind, **input_info}

    if file_kind == "pdf":
        pages = _pdf_blocks(source, assets, tables=tables, table_engine=table_engine)
        source_type = "pdf_text"
        ocr_fallback_pages = []
        if ocr_fallback:
            for index, page in enumerate(pages):
                page_text = " ".join(
                    block.get("text") or "" for block in page["blocks"]
                )
                needed, reason = needs_ocr(page_text)
                if not needed:
                    continue
                has_bad_blocks = any(
                    block.get("block_type") in {"Text", "ListGroup", "SectionHeader"}
                    and block.get("bbox")
                    and (
                        not (block.get("text") or "").strip()
                        or is_garbled_text(block.get("text") or "")
                    )
                    for block in page["blocks"]
                )
                if has_bad_blocks:
                    try:
                        recovery_image = _render_pdf_page(
                            source, page["page_id"],
                            out / "work" / "block_recovery" / f"p{page['page_id']:04d}.png",
                            dpi,
                        )
                        recovered = _recover_bad_blocks(
                            page, recovery_image, resolved_profile.name,
                            language, out / "work" / "block_recovery" / "crops",
                        )
                        if recovered:
                            source_audit["block_ocr_recovered"] = (
                                source_audit.get("block_ocr_recovered", 0) + recovered
                            )
                            page_text = " ".join(
                                block.get("text") or "" for block in page["blocks"]
                            )
                            needed, reason = needs_ocr(page_text)
                            if not needed:
                                continue
                    except Exception as exc:
                        page["review"].append({
                            "code": "BLOCK_OCR_RECOVERY_FAILED",
                            "severity": "warning",
                            "reason": str(exc)[:300],
                        })
                try:
                    replacement = _ocr_pdf_page(
                        source, page["page_id"], out,
                        resolved_profile.name, language, dpi,
                        **({"region_recovery": region_recovery, "layout_detector": layout_detector, "recovery_options": recovery_options}
                           if not region_recovery or layout_detector is not None or recovery_options is not None else {}),
                    )
                except Exception as exc:
                    page["review"].append({
                        "code": "PAGE_OCR_FALLBACK_FAILED",
                        "severity": "warning",
                        "reason": str(exc)[:300],
                    })
                    if reason == "garbled_text_layer":
                        page["review"].append({
                            "code": "PAGE_TEXT_GARBLED",
                            "severity": "warning",
                        })
                    elif reason == "scan_noise":
                        page["review"].append({
                            "code": "PAGE_SCAN_NOISE",
                            "severity": "warning",
                        })
                    if not page_text.strip() or reason == "repeated_url_only_text_layer":
                        page["processing_status"] = "layout_failed"
                        page["review"].append({
                            "code": "PAGE_LAYOUT_FAILED",
                            "severity": "error",
                        })
                    continue
                replacement_text = " ".join(
                    block.get("text") or "" for block in replacement["blocks"]
                )
                if not replacement_text.strip():
                    page["review"].append({
                        "code": "PAGE_OCR_EMPTY",
                        "severity": "warning",
                        "reason": reason,
                    })
                    page["processing_status"] = "layout_failed"
                    page["review"].append({
                        "code": "PAGE_LAYOUT_FAILED",
                        "severity": "error",
                    })
                    continue
                if is_garbled_text(replacement_text):
                    replacement["review"].append({
                        "code": "OCR_FALLBACK_GARBLED",
                        "severity": "warning",
                    })
                replacement["review"].append({
                    "code": "OCR_FALLBACK_USED",
                    "severity": "info",
                    "reason": reason,
                })
                if page.get("text_layer_audit"):
                    replacement["text_layer_audit"] = page["text_layer_audit"]
                pages[index] = replacement
                ocr_fallback_pages.append(page["page_id"])
        source_audit["ocr_fallback_pages"] = ocr_fallback_pages
    elif file_kind == "docx":
        pages = _docx_pages(source, assets)
        source_type = "docx"
        source_audit.update(_docx_source_audit(source))
    elif file_kind == "text":
        pages = _txt_pages(source, assets)
        source_type = "txt"
        text, encoding = _decode_txt(source)
        source_audit.update({"encoding": encoding, "chars": len(text)})
    elif file_kind == "markdown":
        pages = _md_pages(source, assets, resolved_profile.name)
        source_type = "markdown"
    elif file_kind == "html":
        pages = _html_pages(source, assets, resolved_profile.name)
        source_type = "html"
    elif file_kind == "csv":
        pages = _csv_pages(source, assets, resolved_profile.name)
        source_type = "csv"
    elif file_kind == "xlsx":
        pages = _xlsx_pages(source, assets, resolved_profile.name)
        source_type = "xlsx"
    elif file_kind == "pptx":
        pages = _pptx_pages(source, assets, resolved_profile.name)
        source_type = "pptx"
    elif file_kind == "email":
        pages = _email_pages(source, assets, resolved_profile.name)
        source_type = "email"
    elif file_kind == "image":
        raise InputError(
            "NEEDS_OCR_ENGINE",
            "image input needs the OCR/scan path, not the digital lane",
        )
    else:
        raise InputError("UNSUPPORTED_FILE_TYPE", f"unsupported file type: {file_kind}")

    if region_enricher:
        for page in pages:
            image_path = page.get("page_image")
            if not image_path and file_kind == "pdf":
                image_path = _render_pdf_page(source, page["page_id"], out / "work" / "structured_pages" / f"p{page['page_id']:04d}.png", dpi)
            region_enricher.enrich_page(page, out, image_path)
            if any(b.get("structured_status") and (b.get("latex") or b.get("asset_paths")) for b in page["blocks"]):
                page["processing_status"] = "ok"

    if len(pages) > limits.max_pages:
        raise InputError(
            "PAGE_LIMIT_EXCEEDED",
            f"document has {len(pages)} pages; limit is {limits.max_pages}",
        )
    total_chars = sum(
        len(block.get("text") or "")
        for page in pages for block in page["blocks"]
    )
    if total_chars > limits.max_chars:
        raise InputError(
            "TEXT_LIMIT_EXCEEDED",
            f"document has {total_chars} text chars; limit is {limits.max_chars}",
        )

    source_label = {
        "pdf_text": "pymupdf", "docx": "pandoc", "txt": "text",
        "markdown": "markdown", "html": "html", "csv": "csv",
        "xlsx": "openpyxl", "pptx": "python-pptx", "email": "email",
    }[source_type]
    for page in pages:
        page["profile"] = resolved_profile.name
        page["ocr_language"] = language
        for idx, block in enumerate(page["blocks"]):
            block["order"] = idx
            block["page"] = page["page_id"]
            block.setdefault("source", source_label)
            if block.get("latex"):
                validations = [
                    validate_latex(value).as_dict() for value in block["latex"]
                ]
                block["latex_validation"] = validations
                if not all(item["valid"] for item in validations):
                    flag = {
                        "code": "LATEX_INVALID",
                        "severity": "warning",
                    }
                    block.setdefault("review_flags", []).append(flag)
                    page.setdefault("review", []).append({
                        "page": page["page_id"],
                        "block_id": block["block_id"],
                        "block_type": block["block_type"],
                        "bbox": block["bbox"],
                        **flag,
                    })
                incomplete = (
                    incomplete_formula_reasons(block["latex"])
                    if resolved_profile.math_formula_checks else []
                )
                if incomplete:
                    flag = {
                        "code": "FORMULA_INCOMPLETE",
                        "severity": "warning",
                        "reasons": incomplete,
                    }
                    block.setdefault("review_flags", []).append(flag)
                    page.setdefault("review", []).append({
                        "page": page["page_id"],
                        "block_id": block["block_id"],
                        "block_type": block["block_type"],
                        "bbox": block["bbox"],
                        **flag,
                    })
        page["markdown"] = _markdown_for_page(page["blocks"])

    if source_type == "pdf_text" and not any(
        (block.get("text") or "").strip() or (region_enricher and (block.get("latex") or block.get("structured_status")))
        for page in pages for block in page["blocks"]
    ):
        raise RuntimeError("PDF không có text layer; hãy dùng pipeline OCR/marker.")

    fallback_pages = source_audit.get("ocr_fallback_pages") or []
    parser_name = "mixed" if fallback_pages else source_label
    parser = {
        "name": parser_name,
        "version": PIPELINE_VERSION,
        "kind": "mixed" if fallback_pages else "digital",
        "confidence_available": False,
        "sources": {
            "pymupdf": len(pages) - len(fallback_pages),
            "tesseract_fallback": len(fallback_pages),
        } if fallback_pages else {source_label: len(pages)},
    }
    source_sha256 = _sha256(source)
    canonical = build_canonical(
        pages=pages,
        source_path=source,
        source_sha256=source_sha256,
        pipeline_version=PIPELINE_VERSION,
        parser=parser,
        expected_pages=[page["page_id"] for page in pages],
        profile=resolved_profile.name,
        source_acl=source_acl,
        source_metadata=source_metadata,
    )
    ingestion = audit_canonical(
        canonical,
        trusted_parsers={
            "pymupdf", "pandoc", "text", "markdown", "html",
            "csv", "openpyxl", "python-pptx", "email",
        },
        profile=resolved_profile.name,
    )

    pages_dir = out / "pages"
    pages_dir.mkdir(exist_ok=True)
    for page in pages:
        (pages_dir / f"p{page['page_id']:04d}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (pages_dir / f"p{page['page_id']:04d}.md").write_text(
            page["markdown"], encoding="utf-8"
        )

    review = []
    for page in pages:
        for block in page["blocks"]:
            flags = [
                flag for flag in block.get("review_flags") or []
                if flag.get("severity") in {"warning", "error"}
            ]
            if flags:
                review.append({
                    "page": page["page_id"],
                    "block_id": block["block_id"],
                    "block_type": block["block_type"],
                    "bbox": block.get("bbox"),
                    "block_crop_path": block.get("block_crop_path"),
                    "flags": flags,
                })
    for item in ingestion["quality"]["page_quality"]:
        if not item["publish_authorized"] and item["status"] != "blank":
            review.append({
                "page": item["page_id"], "block_id": None, "block_type": "Page",
                "code": "PUBLISH_NOT_AUTHORIZED", "severity": "warning",
            })
    (out / "review_queue.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in review) + ("\n" if review else ""),
        encoding="utf-8",
    )

    out_audit = _text_output_audit(pages)
    content_loss = {}
    if source_type == "docx":
        content_loss = {
            "tables": max(0, int(source_audit.get("tables", 0)) - int(out_audit.get("table_elements", out_audit["tables"]))),
            "equations": max(0, int(source_audit.get("equations", 0)) - int(out_audit["equations"])),
            "media": max(0, int(source_audit.get("media", 0)) - int(out_audit["images"])),
        }
    output_errors = validate_outputs(
        out, pages, require_bbox=source_type == "pdf_text"
    )
    audit = _digital_audit(
        pages, content_loss, source_type, output_errors
    )
    chars = sum(len(p["markdown"]) for p in pages)
    formula_blocks = sum(
        1 for p in pages for b in p["blocks"]
        if b["block_type"] == "Equation" or b.get("latex")
    )
    formula_text_blocks = sum(1 for p in pages for b in p["blocks"] if b.get("formula_text"))
    table_blocks = sum(1 for p in pages for b in p["blocks"] if b["block_type"] == "Table")
    table_review_blocks = sum(
        1 for p in pages for b in p["blocks"]
        if any(f.get("code") == "TABLE_STRUCTURE_REVIEW" for f in b.get("review_flags", []))
    )
    table_engines = {}
    for page in pages:
        engine = (page.get("table_extraction") or {}).get("engine")
        if engine:
            table_engines[engine] = table_engines.get(engine, 0) + 1
    figure_blocks = sum(1 for p in pages for b in p["blocks"] if b["block_type"] == "Picture")
    elapsed = round(time.perf_counter() - started, 3)
    manifest = {
        "source": str(source),
        "source_type": source_type,
        "file_kind": file_kind,
        "source_acl": source_acl or {
            "owner": None, "users": [], "groups": [], "is_public": False,
        },
        "source_metadata": dict(source_metadata or {}),
        "profile": resolved_profile.name,
        "language": language,
        "structured_enrichment": enrichment_summary(pages),
        "table_mode": tables,
        "table_engine": table_engine,
        "table_engine_pages": table_engines,
        "source_sha256": source_sha256,
        "pipeline_version": PIPELINE_VERSION,
        "ingestion_pass": ingestion["pass"],
        "ingestion_quality_pass": ingestion.get("quality_pass"),
        "ingestion_review_assisted_pass": ingestion.get("review_assisted_pass"),
        "ingestion_production_pass": ingestion.get("production_pass"),
        "ingestion_auto_publish_pass": ingestion.get("auto_publish_pass"),
        "ingestion_quality_certified": ingestion.get("quality_certified"),
        "ingestion_checks": {k: v["pass"] for k, v in ingestion["checks"].items()},
        "ingestion_quality": ingestion["quality"],
        "canonical_version": canonical["schema_version"],
        "parser": parser,
        "ingestion_only": ingestion_only,
        "pages": len(pages),
        "chars": chars,
        "formula_blocks": formula_blocks,
        "formula_text_blocks": formula_text_blocks,
        "table_blocks": table_blocks,
        "table_review_blocks": table_review_blocks,
        "figure_blocks": figure_blocks,
        "review_items": len(review),
        "source_audit": source_audit,
        "ocr_fallback_pages": fallback_pages,
        "output_audit": out_audit,
        "content_loss": content_loss,
        "strict": strict,
        "audit_pass": audit["pass"],
        "seconds": elapsed,
    }
    _write_json(out / "manifest.json", manifest)
    _write_json(out / "report.json", manifest)
    _write_json(out / "audit_report.json", audit)
    _write_json(out / "canonical.json", canonical)
    _write_json(out / "ingestion_report.json", ingestion)
    if strict and (
        any(v for v in content_loss.values())
        or not audit["pass"]
        or not ingestion["pass"]
    ):
        raise RuntimeError(
            f"digital audit failed: content_loss={content_loss} "
            f"audit={audit['checks']} ingestion={ingestion['checks']}"
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest text-like documents without OCR"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--profile", default="general")
    parser.add_argument("--language", default=None)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-ocr-fallback", action="store_true")
    parser.add_argument("--tables", choices=["auto", "on", "off"], default="off")
    parser.add_argument(
        "--table-engine", choices=list(TABLE_ENGINES), default="auto",
        help="pdfplumber is faster; auto escalates to pymupdf on poor tables",
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--ingestion-only", action="store_true")
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
            result = process(
                args.input, args.out, tables=args.tables, strict=args.strict,
                table_engine=args.table_engine,
                profile=args.profile, language=args.language,
                ingestion_only=args.ingestion_only,
                ocr_fallback=not args.no_ocr_fallback,
                dpi=args.dpi, region_recovery=not args.no_region_recovery,
                layout_detector=detector, recovery_options=options,
                region_enricher=enricher,
            )
    except InputError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
