"""Level 0 native PDF extraction backend using PyMuPDF (CPU, zero render)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from idp.input.validation import encoding_issues, needs_ocr, open_fitz_doc, repeated_watermark_tokens
from idp.processing.figure import prepare_page_figures
from idp.processing.formula import reconstruct_page_math
from idp.processing.reading_order import column_reading_order, native_reading_order
from idp.processing.table import (
    has_table_grid,
    md_table,
    open_pdfplumber,
    pdfplumber_tables,
    pymupdf_tables,
    score_tables,
    table_engine_order,
    usable_tables,
)

NATIVE_PDF_VERSION = "idp-native-pdf-1.0"
_MATH_FONT = re.compile(r"CMMI|CMSY|CMEX|Symbol|Math", re.I)
_MATH_OPERATOR = re.compile(r"[=+\-×÷^_{}\\√∑∫∞≤≥<>]")
_DISPLAY_RELATION = re.compile(r"[=≤≥⩽⩾→]")
_PROSE_WORD = re.compile(r"[^\W\d_]{2,}")
_LABEL_NUMBER = re.compile(r"\(\d+(?:\.\d+)*[a-z]?\)|\d+(?:\.\d+)+\.?|\d+\.")
_EDGE_NUMBER = re.compile(r"^\s*\d+\s*$|^\s*\d+\s+|\s+\d+\s*$")
RUNNING_LINE_MIN_PAGES = 3


def _text_layer_fragment(text: str) -> bool:
    """True when a short text-layer line has fewer than two prose words (formula shard)."""
    value = text.strip()
    if _LABEL_NUMBER.fullmatch(value):
        return False
    return bool(value) and len(value) <= 60 and len(_PROSE_WORD.findall(value)) < 2


def _running_line_entries(pages_raw: list[dict]) -> set[tuple[int, int]]:
    """Identify (page_index, entry_index) of running headers/footers and page numbers."""
    keyed, pages_by_key = [], {}
    for item in pages_raw:
        texts = [
            idx for idx, e in enumerate(item["entries"])
            if e.get("kind") not in {"table", "image"} and (e.get("text") or "").strip()
        ]
        if not texts:
            continue
        for idx in dict.fromkeys((texts[0], texts[-1])):
            text = item["entries"][idx]["text"].strip()
            if len(text) > 160:
                continue
            key = " ".join(_EDGE_NUMBER.sub("", text).casefold().split())
            keyed.append(((item["index"], idx), key))
            if key:
                pages_by_key.setdefault(key, set()).add(item["index"])
    return {
        position for position, key in keyed
        if not key or (
            len(_PROSE_WORD.findall(key)) >= 2
            and len(pages_by_key.get(key, ())) >= RUNNING_LINE_MIN_PAGES
        )
    }


def _pdf_span_text(span: dict, *, horizontal: bool) -> str:
    """Recover word spaces omitted by a PDF text layer using glyph positions."""
    chars = span.get("chars", [])
    space_threshold = 0.25 * span["size"]
    join_words = horizontal and not _MATH_FONT.search(span.get("font", ""))
    parts = []
    previous = None
    for char in chars:
        value = char["c"]
        if (
            join_words and previous is not None
            and previous["c"].isalpha() and value.isalpha()
            and char["origin"][0] - previous["bbox"][2] >= space_threshold
        ):
            parts.append(" ")
        parts.append(value)
        previous = char
    return "".join(parts)


def _is_display_line(entry: dict, page_width: float) -> bool:
    left, _, right, _ = entry["bbox"]
    centered = abs((left + right) / 2 - page_width / 2) < page_width * 0.08
    return (
        entry["math_font"]
        and centered
        and right - left < page_width * 0.65
        and "\n" not in entry["text"]
        and entry["prose_words"] <= 2
        and bool(_DISPLAY_RELATION.search(entry["text"]))
    )


def _pdf_span_gap(previous: dict, span: dict) -> bool:
    left, right = previous["chars"][-1], span["chars"][0]
    a, b = left["c"], right["c"]
    text_boundary = (a.isalpha() and b.isalnum()) or (a.isdigit() and b.isalpha())
    relation_boundary = (a in "=≤≥⩽⩾<>∈∉" and b.isalnum()) or (a.isalnum() and b in "=≤≥⩽⩾<>∈∉")
    return (text_boundary or relation_boundary) and right["origin"][0] - left["bbox"][2] >= 0.25 * span["size"]


def _strip_html(value: str) -> str:
    import html as html_lib
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def make_block(
    block_id: str,
    block_type: str,
    bbox,
    text: str = "",
    markdown: str | None = None,
    latex: list[str] | None = None,
    asset_paths: list[str] | None = None,
    review_flags: list[dict] | None = None,
    section_path: list[str] | None = None,
    excluded: bool = False,
    formula_text: str | None = None,
) -> dict:
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


def make_page(
    page_id: int,
    blocks: list[dict],
    page_size=None,
    classification: str | dict = "content",
    page_number: int | None = None,
    **extra,
) -> dict:
    review = [
        {**f, "block_id": f.get("block_id") or b["block_id"]}
        for b in blocks for f in b.get("review_flags") or []
        if f.get("severity") in {"warning", "error"}
    ]
    page = {
        "page_id": page_id,
        "page_number": page_number if page_number is not None else page_id,
        "page_size": list(page_size) if page_size else None,
        "classification": classification,
        "blocks": blocks,
        "review": review,
        "processing_status": "ok",
        "pipeline_version": NATIVE_PDF_VERSION,
    }
    for key, val in extra.items():
        if val is not None:
            page[key] = val
    return page


def markdown_for_page(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        if b.get("excluded_from_content"):
            continue
        md = (b.get("markdown") or b.get("text") or "").strip()
        if md:
            out.append(md)
    return "\n\n".join(out).strip()


def extract_pdf_page_raw(
    page,
    page_index: int,
    doc,
    assets: Path,
    *,
    fitz,
    tables: str = "auto",
    table_engine: str = "auto",
    plumber_page=None,
) -> tuple[dict, list[float]]:
    """Extract raw PyMuPDF text spans, native tables, and embedded images for one page."""
    entries: list[dict] = []
    table_rects: list = []
    attempts: list[dict] = []
    chosen_engine = None
    sizes: list[float] = []

    try:
        page_text = page.get_text()
    except Exception:
        page_text = ""
    is_toc = bool(re.search(r"\bmục\s*lục\b|\bcontents\b|table of contents", page_text, re.I))
    if tables != "off" and not is_toc:
        has_grid = has_table_grid(page)
        if tables == "on" or (tables == "auto" and has_grid):
            candidates = []
            for engine in table_engine_order(table_engine):
                if engine == "pdfplumber":
                    if plumber_page is None:
                        attempts.append({"engine": engine, "error": "unavailable"})
                        continue
                    try:
                        detected = pdfplumber_tables(plumber_page)
                        raw_tables = usable_tables(detected, plumber_page.width, plumber_page.height)
                    except Exception as exc:
                        attempts.append({"engine": engine, "error": repr(exc)[:300]})
                        continue
                else:
                    try:
                        detected = pymupdf_tables(page)
                        raw_tables = usable_tables(detected, page.rect.width, page.rect.height)
                    except Exception as exc:
                        attempts.append({"engine": engine, "error": repr(exc)[:300]})
                        continue
                scored = score_tables(raw_tables)
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
                    md = md_table(raw_table["rows"])
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
                        "kind": "table",
                        "bbox": raw_table["bbox"],
                        "markdown": md,
                        "text": _strip_html(md),
                        "table_engine": chosen_engine,
                        "table_metrics": metrics,
                        "review_flags": flags,
                    })
                    table_rects.append(fitz.Rect(raw_table["bbox"]))

    try:
        data = page.get_text("rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
    except Exception:
        data = {"blocks": []}
    for raw in data.get("blocks", []):
        if raw.get("type") != 0:
            continue
        rows = []
        for line in raw.get("lines", []):
            parts = []
            line_sizes = []
            math_font = False
            prose_words = 0
            previous = None
            horizontal = line.get("dir") == (1.0, 0.0)
            for span in line.get("spans", []):
                txt = _pdf_span_text(span, horizontal=horizontal)
                if txt:
                    if horizontal and previous is not None and _pdf_span_gap(previous, span):
                        parts.append(" ")
                    parts.append(txt)
                    previous = span
                    line_sizes.append(float(span.get("size", 0)))
                    if _MATH_FONT.search(span.get("font", "")):
                        math_font = True
                    else:
                        prose_words += len(re.findall(r"[^\W\d_]{3,}", txt))
            if parts:
                rows.append({
                    "kind": "text",
                    "bbox": list(line["bbox"]),
                    "text": unicodedata.normalize("NFC", "".join(parts)).strip(),
                    "size": max(line_sizes),
                    "math_font": math_font,
                    "prose_words": prose_words,
                })
        rows = [row for row in rows if row["text"]]
        text = "\n".join(row["text"] for row in rows)
        if not text:
            continue
        bbox = list(raw.get("bbox", [0, 0, 0, 0]))
        rect = fitz.Rect(bbox)
        if any((rect & tr).get_area() > max(1, rect.get_area()) * 0.5 for tr in table_rects):
            continue
        size = max(row["size"] for row in rows)
        sizes.append(size)
        if len(rows) > 1 and _is_display_line(rows[0], page.rect.width):
            _, top, right, bottom = rows[0]["bbox"]
            if all(row["bbox"][0] > right and row["bbox"][1] < bottom and row["bbox"][3] > top for row in rows[1:]):
                entries.extend(rows)
                continue
        entries.append({
            "kind": "text",
            "bbox": bbox,
            "text": text,
            "size": size,
            "math_font": any(row["math_font"] for row in rows),
            "prose_words": sum(row["prose_words"] for row in rows),
        })

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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(info["image"])
        for rect in rects:
            entries.append({
                "kind": "image",
                "bbox": list(rect),
                "asset": str(target),
                "caption": "",
            })

    entries = column_reading_order(native_reading_order(entries), float(page.rect.width))
    watermark_tokens = repeated_watermark_tokens([
        entry.get("text") or "" for entry in entries if entry.get("kind") == "text"
    ])
    raw_page = {
        "page": page,
        "index": page_index,
        "entries": entries,
        "width": float(page.rect.width),
        "height": float(page.rect.height),
        "table_attempts": attempts,
        "table_engine": chosen_engine,
        "watermark_tokens": watermark_tokens,
    }
    return raw_page, sizes


def build_native_pdf_pages(
    pages_raw: list[dict],
    all_sizes: list[float],
    *,
    reconstruct_math: bool = True,
) -> list[dict]:
    """Convert raw PyMuPDF page entries into structured canonical-ready page dicts."""
    median_size = sorted(all_sizes)[len(all_sizes) // 2] if all_sizes else 10.0
    running_lines = _running_line_entries(pages_raw)
    pages: list[dict] = []
    for item in pages_raw:
        page_no = item["index"] + 1
        blocks: list[dict] = []
        section_path: list[str] = []
        section_stack: list[tuple[int, str]] = []
        for idx, e in enumerate(item["entries"]):
            left, top, right, bottom = e["bbox"]
            bbox = [max(0, left), max(0, top), min(item["width"], right), min(item["height"], bottom)]
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                continue
            bid = f"p{page_no:04d}_b{idx:03d}"
            if e["kind"] == "table":
                table_block = make_block(
                    bid, "Table", bbox, e["text"], e["markdown"],
                    section_path=list(section_path),
                    review_flags=e.get("review_flags") or [],
                )
                table_block["table_engine"] = e.get("table_engine")
                table_block["table_metrics"] = e.get("table_metrics")
                table_block["source"] = "pymupdf"
                blocks.append(table_block)
                continue
            if e["kind"] == "image":
                img_block = make_block(
                    bid, "Picture", bbox, e.get("caption", ""),
                    f"![]({e['asset']})", asset_paths=[e["asset"]],
                    section_path=list(section_path),
                )
                img_block["source"] = "pymupdf"
                blocks.append(img_block)
                continue
            text = e["text"]
            size = e["size"]
            y0, y1 = float(bbox[1]), float(bbox[3])
            btype = "Text"
            flags: list[dict] = []
            level = None
            if (
                y0 < item["height"] * 0.04
                or y1 > item["height"] * 0.96
                or (item["index"], idx) in running_lines
            ):
                btype = "PageHeader" if y0 < item["height"] * 0.5 else "PageFooter"
            elif size >= median_size * 1.12 and len(text) <= 180 and "\n" not in text:
                btype = "SectionHeader"
                level = 1 if size >= median_size * 1.35 else 2
            else:
                math_chars = len(_MATH_OPERATOR.findall(text))
                legacy_math = math_chars >= 4 and (e["math_font"] or math_chars / len(text) > 0.08)
                display = _is_display_line(e, item["width"])
                if (legacy_math and e["prose_words"] <= 2) or display:
                    btype = "Equation"
                if legacy_math or display:
                    flags.append({
                        "block_id": bid,
                        "code": "FORMULA_TEXT_LAYER_UNVERIFIED",
                        "severity": "warning",
                    })
                elif _text_layer_fragment(text):
                    flags.append({
                        "block_id": bid,
                        "code": "FORMULA_TEXT_LAYER_FRAGMENT",
                        "severity": "warning",
                    })
            if btype == "SectionHeader" and level is not None:
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, text))
                section_path[:] = [x[1] for x in section_stack]
            if btype not in {"PageHeader", "PageFooter"}:
                enc = encoding_issues(text)
                if enc:
                    flags.append({
                        "code": "TEXT_ENCODING_REVIEW",
                        "severity": "warning",
                        "issues": enc,
                    })
            md = f"{'#' * min(6, level)} {text}" if (btype == "SectionHeader" and level is not None) else text
            blk = make_block(
                bid, btype, bbox, text, md,
                section_path=list(section_path),
                review_flags=flags,
                formula_text=text if btype == "Equation" else None,
            )
            blk["source"] = "pymupdf"
            blocks.append(blk)
        if reconstruct_math:
            blocks = reconstruct_page_math(blocks, item["page"])
        page_obj = make_page(page_no, blocks, [item["width"], item["height"]], page_number=page_no)
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
        _, layer_reason = needs_ocr(layer_text)
        if layer_reason == "repeated_url_only_text_layer":
            page_obj["text_layer_audit"] = {
                "status": "rejected_for_primary",
                "reason": layer_reason,
                "text": layer_text,
                "source": "pymupdf",
            }
            page_obj["review"].append({
                "page": page_no,
                "block_id": None,
                "code": "PAGE_TEXT_LAYER_UNUSABLE",
                "severity": "warning",
                "reason": layer_reason,
            })
        pages.append(page_obj)
    return pages


def extract_pdf_native_pages(
    path: Path,
    assets: Path,
    *,
    tables: str = "auto",
    table_engine: str = "auto",
    page_indices: set[int] | None = None,
    reconstruct_math: bool = True,
) -> list[dict]:
    """Extract Level-0 native PyMuPDF pages for all or selected 0-based page indices."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    plumber = open_pdfplumber(path, table_engine) if tables != "off" else None
    try:
        with open_fitz_doc(path) as doc:
            all_sizes: list[float] = []
            pages_raw: list[dict] = []
            for page_index in range(doc.page_count):
                if page_indices is not None and page_index not in page_indices:
                    continue
                page = doc[page_index]
                plumber_page = plumber.pages[page_index] if plumber is not None else None
                raw_page, sizes = extract_pdf_page_raw(
                    page,
                    page_index,
                    doc,
                    assets,
                    fitz=fitz,
                    tables=tables,
                    table_engine=table_engine,
                    plumber_page=plumber_page,
                )
                all_sizes.extend(sizes)
                pages_raw.append(raw_page)
            pages = build_native_pdf_pages(pages_raw, all_sizes, reconstruct_math=reconstruct_math)
            out_dir = assets.parent
            for p in pages:
                prepare_page_figures(p, out_dir)
            return pages
    finally:
        if plumber is not None:
            plumber.close()


# Compatibility aliases
_block = make_block
_page = make_page
_encoding_issues = encoding_issues
_markdown_for_page = markdown_for_page
