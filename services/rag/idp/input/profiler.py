"""Zero-render per-page PDF profiler for routing before rasterization."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from idp.input.validation import (
    encoding_issues,
    is_garbled_text,
    needs_ocr,
    open_fitz_doc,
)

_MATH_FONT_RE = re.compile(r"CMMI|CMSY|CMEX|Symbol|Math", re.I)
_MATH_CHAR_RE = re.compile(r"[=+\-×÷^_{}\\√∑∫∞≤≥<>]")
_PROSE_WORD_RE = re.compile(r"[^\W\d_]{2,}")
_TOC_RE = re.compile(r"\bmục\s*lục\b|\bcontents\b|table of contents", re.I)


@dataclass(frozen=True)
class PageProfile:
    """Cheap structural signals extracted directly from PDF objects without rendering."""

    page_id: int
    width: float
    height: float
    rotation: int
    char_count: int
    word_count: int
    letter_ratio: float
    text_block_count: int
    garbled_block_count: int
    garbled_block_ratio: float
    has_encoding_issues: bool
    encoding_issue_codes: list[str]
    garbled: bool
    repeated_url_only: bool
    scan_noise: bool
    ocr_reason: str | None
    math_font_spans: int
    math_char_count: int
    math_ratio: float
    has_fragment_math: bool
    has_table_grid: bool
    drawing_count: int
    image_count: int
    image_area_ratio: float
    max_single_image_ratio: float
    is_multi_column_native: bool
    is_toc: bool
    blank: bool
    text_area_ratio: float = 0.0
    uncovered_image_ratio: float = 0.0
    vector_text_risk: bool = False
    routing_risk_score: float = 0.0
    routing_signals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _rect_area(rect: list[float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _intersect_area(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _has_table_grid_lines(drawings: list[dict]) -> bool:
    horizontal = 0
    vertical = 0
    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item:
                continue
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) <= 1.0:
                    vertical += 1
                elif abs(p1.y - p2.y) <= 1.0:
                    horizontal += 1
            elif item[0] == "re":
                rect = item[1]
                if rect.width > 8 and rect.height > 8:
                    horizontal += 2
                    vertical += 2
    return horizontal >= 4 and vertical >= 3


def _is_two_column_native(block_boxes: list[list[float]], width: float) -> bool:
    if len(block_boxes) < 6 or width <= 0:
        return False
    mid = width / 2.0
    gutter = max(4.0, width * 0.03)
    left = sum(1 for b in block_boxes if b[2] <= mid - gutter)
    right = sum(1 for b in block_boxes if b[0] >= mid + gutter)
    spanning = sum(1 for b in block_boxes if not (b[2] <= mid - gutter or b[0] >= mid + gutter))
    return left >= 3 and right >= 3 and spanning == 0


def profile_pdf_page(page, page_id: int) -> PageProfile:
    """Profile one PyMuPDF page without rendering pixels."""
    width = float(page.rect.width)
    height = float(page.rect.height)
    page_area = max(1.0, width * height)
    rotation = int(getattr(page, "rotation", 0) or 0)

    try:
        data = page.get_text("dict")
    except Exception:
        data = {"blocks": []}

    text_parts: list[str] = []
    block_boxes: list[list[float]] = []
    text_block_count = 0
    garbled_block_count = 0
    math_font_spans = 0
    fragment_blocks = 0

    clean_parts: list[str] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        block_lines: list[str] = []
        for line in block.get("lines", []):
            line_parts: list[str] = []
            for span in line.get("spans", []):
                val = span.get("text") or ""
                if val:
                    line_parts.append(val)
                    if _MATH_FONT_RE.search(span.get("font") or ""):
                        math_font_spans += 1
            joined_line = "".join(line_parts).strip()
            if joined_line:
                block_lines.append(joined_line)
        block_text = "\n".join(block_lines).strip()
        if not block_text:
            continue
        text_block_count += 1
        text_parts.append(block_text)
        bbox = block.get("bbox")
        if bbox and len(bbox) == 4:
            block_boxes.append([float(v) for v in bbox])
        if is_garbled_text(block_text) or encoding_issues(block_text):
            garbled_block_count += 1
        else:
            clean_parts.append(block_text)
        if len(block_text) <= 60 and len(_PROSE_WORD_RE.findall(block_text)) < 2:
            fragment_blocks += 1

    full_text = " ".join(text_parts).strip()
    clean_text = " ".join(clean_parts).strip()
    char_count = len(full_text)
    word_count = len(_PROSE_WORD_RE.findall(full_text))
    letter_ratio = sum(1 for ch in full_text if ch.isalpha()) / char_count if char_count else 0.0
    garbled_block_ratio = garbled_block_count / max(1, text_block_count)
    enc_codes = encoding_issues(full_text) if full_text else []
    needed, ocr_reason = needs_ocr(clean_text if (text_block_count >= 2 and clean_text) else full_text)

    math_chars = len(_MATH_CHAR_RE.findall(full_text))
    math_ratio = math_chars / char_count if char_count else 0.0
    has_fragment_math = fragment_blocks >= 2 or (math_chars >= 4 and math_ratio >= 0.02)

    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    drawing_count = len(drawings)
    has_grid = _has_table_grid_lines(drawings)

    try:
        images = page.get_images(full=True)
    except Exception:
        images = []
    image_area = 0.0
    max_single_ratio = 0.0
    img_rects: list[list[float]] = []
    for img in images:
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        for rect in rects:
            box = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
            area = _rect_area(box)
            image_area += area
            max_single_ratio = max(max_single_ratio, area / page_area)
            if area > 0:
                img_rects.append(box)
    image_area_ratio = min(1.0, image_area / page_area)

    text_area = sum(_rect_area(b) for b in block_boxes)
    text_area_ratio = min(1.0, text_area / page_area)

    uncovered_img_area = 0.0
    for r in img_rects:
        r_area = _rect_area(r)
        if r_area <= 0:
            continue
        covered = sum(_intersect_area(r, tb) for tb in block_boxes)
        uncovered_img_area += max(0.0, r_area - min(r_area, covered))
    uncovered_image_ratio = min(1.0, uncovered_img_area / page_area)

    vector_text_risk = drawing_count >= 200 and char_count < 150 and text_area_ratio < 0.08
    scan_with_header_trap = (
        max_single_ratio >= 0.65
        and uncovered_image_ratio >= 0.50
        and (char_count < 250 or text_area_ratio < 0.06)
    )

    routing_signals: list[str] = []
    risk_score = 0.0
    if garbled_block_count > 0:
        routing_signals.append("garbled_blocks")
        risk_score += 0.5 * garbled_block_ratio
    if enc_codes:
        routing_signals.append("encoding_issues")
        risk_score += 0.25
    if needed:
        routing_signals.append(ocr_reason or "needs_ocr")
        risk_score += 0.35
    if scan_with_header_trap:
        routing_signals.append("scan_with_header_large_image")
        risk_score += 0.45
    if vector_text_risk:
        routing_signals.append("vector_outlined_text_risk")
        risk_score += 0.35
    if uncovered_image_ratio >= 0.40:
        routing_signals.append("large_uncovered_raster")
        risk_score += 0.20 * uncovered_image_ratio
    if drawing_count >= 100:
        routing_signals.append("dense_vector_drawings")
    routing_risk_score = round(min(1.0, risk_score), 4)

    blank = char_count == 0 and len(images) == 0 and drawing_count == 0

    return PageProfile(
        page_id=page_id,
        width=width,
        height=height,
        rotation=rotation,
        char_count=char_count,
        word_count=word_count,
        letter_ratio=round(letter_ratio, 4),
        text_block_count=text_block_count,
        garbled_block_count=garbled_block_count,
        garbled_block_ratio=round(garbled_block_ratio, 4),
        has_encoding_issues=bool(enc_codes),
        encoding_issue_codes=enc_codes,
        garbled=bool(needed and ocr_reason == "garbled_text_layer"),
        repeated_url_only=bool(needed and ocr_reason == "repeated_url_only_text_layer"),
        scan_noise=bool(needed and ocr_reason == "scan_noise"),
        ocr_reason=ocr_reason,
        math_font_spans=math_font_spans,
        math_char_count=math_chars,
        math_ratio=round(math_ratio, 4),
        has_fragment_math=has_fragment_math,
        has_table_grid=has_grid,
        drawing_count=drawing_count,
        image_count=len(images),
        image_area_ratio=round(image_area_ratio, 4),
        max_single_image_ratio=round(max_single_ratio, 4),
        is_multi_column_native=_is_two_column_native(block_boxes, width),
        is_toc=bool(_TOC_RE.search(full_text)),
        blank=blank,
        text_area_ratio=round(text_area_ratio, 4),
        uncovered_image_ratio=round(uncovered_image_ratio, 4),
        vector_text_risk=vector_text_risk,
        routing_risk_score=routing_risk_score,
        routing_signals=routing_signals,
    )


def profile_pdf_document(pdf_path: str | Path, pages: list[int] | None = None) -> list[PageProfile]:
    """Profile requested (or all) pages of a PDF without rendering."""
    with open_fitz_doc(pdf_path) as doc:
        wanted = pages or list(range(1, doc.page_count + 1))
        out: list[PageProfile] = []
        for page_no in wanted:
            if 1 <= page_no <= doc.page_count:
                out.append(profile_pdf_page(doc[page_no - 1], page_no))
        return out
