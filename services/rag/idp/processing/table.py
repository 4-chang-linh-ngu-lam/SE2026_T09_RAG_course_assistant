"""Table extraction, scoring, HTML/OTSL parsing, OpenCV ruled grids, and word alignment."""

from __future__ import annotations

import html
import math
import re
import time
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

TABLE_ENGINES = ("auto", "pymupdf", "pdfplumber")
TABLE_ALIGNMENT_VERSION = "idp-table-word-alignment-1"
OTSL_TOKENS = re.compile(r"(<fcel>|<ecel>|<lcel>|<ucel>|<xcel>|<nl>)")


# ---------------------------------------------------------------------------
# Native table cleaning, metrics, and extraction (PyMuPDF / pdfplumber)
# ---------------------------------------------------------------------------

def clean_table_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned = []
    for row in rows or []:
        cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]
        if any(cells):
            cleaned.append(cells)
    return cleaned


def md_table(rows: list[list[str]]) -> str:
    cleaned = clean_table_rows(rows)
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header = cleaned[0]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in cleaned[1:]:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def rows_to_html(rows: list[list[str]]) -> str:
    cleaned = clean_table_rows(rows)
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    out = ["<table>"]
    for row in cleaned:
        row = row + [""] * (width - len(row))
        out.append("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


def table_metrics(rows: list[list[str]]) -> dict:
    source_rows = clean_table_rows(rows)
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
    max_cell_len = max((len(cell) for row in padded for cell in row), default=0)
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


def score_tables(tables: list[dict]) -> dict:
    metrics = [table_metrics(table["rows"]) for table in tables]
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


def usable_tables(tables: list[dict], width: float, height: float) -> list[dict]:
    usable = []
    page_area = max(1.0, float(width) * float(height))
    for table in tables:
        rows = table.get("rows") or []
        metrics = table_metrics(rows)
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
            and (metrics["max_cell_len"] > 80 or metrics["fill_ratio"] < 0.5)
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


def table_engine_order(engine: str) -> list[str]:
    return ["pdfplumber", "pymupdf"] if engine == "auto" else [engine]


def open_pdfplumber(path: Path, engine: str):
    if engine not in {"auto", "pdfplumber"}:
        return None
    try:
        import pdfplumber
    except ImportError as exc:
        if engine == "pdfplumber":
            raise RuntimeError("table engine pdfplumber requires `pip install pdfplumber`") from exc
        return None
    return pdfplumber.open(path)


def pymupdf_tables(page) -> list[dict]:
    tables = []
    for table in page.find_tables().tables:
        rows = clean_table_rows(table.extract())
        if rows:
            tables.append({"rows": rows, "bbox": list(table.bbox)})
    return tables


def pdfplumber_tables(plumber_page) -> list[dict]:
    tables = []
    for table in plumber_page.find_tables():
        rows = clean_table_rows(table.extract())
        if not rows:
            continue
        bbox = getattr(table, "bbox", None)
        if bbox:
            tables.append({"rows": rows, "bbox": [float(x) for x in bbox]})
    return tables


def has_table_grid(page) -> bool:
    try:
        drawings = page.get_drawings()
    except Exception:
        return False
    horizontal = vertical = 0
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


# ---------------------------------------------------------------------------
# HTML table parsing, normalization, and OTSL decoding
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    def __init__(self, limit: int):
        super().__init__(convert_charrefs=True)
        self.limit, self.depth, self.row, self.cell = limit, 0, -1, None
        self.cells, self.occupied = [], set()
        self.top_tables = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.depth == 0:
                self.top_tables += 1
                if self.top_tables > 1:
                    raise ValueError("multiple tables require separate source blocks")
            self.depth += 1
            if self.depth > 1:
                raise ValueError("nested table needs a specialized reader")
        if self.depth != 1:
            return
        if tag == "tr":
            self.row += 1
        elif tag in {"td", "th"}:
            if self.row < 0 or self.cell is not None or len(self.cells) >= self.limit:
                raise ValueError("invalid or oversized table")
            attr_map = dict(attrs)
            try:
                rs, cs = int(attr_map.get("rowspan", 1)), int(attr_map.get("colspan", 1))
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid table span") from exc
            if not 1 <= rs <= 256 or not 1 <= cs <= 256:
                raise ValueError("invalid table span")
            if len(self.occupied) + rs * cs > self.limit * 4:
                raise ValueError("expanded table exceeds limits")
            col = 0
            while (self.row, col) in self.occupied:
                col += 1
            covered = {(r, c) for r in range(self.row, self.row + rs) for c in range(col, col + cs)}
            if covered & self.occupied:
                raise ValueError("overlapping table cells")
            self.occupied.update(covered)
            self.cell = {
                "row": self.row, "column": col, "rowspan": rs,
                "colspan": cs, "is_header": tag == "th", "text": "",
            }
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.cell["text"] = self.cell["text"].strip()
            self.cells.append(self.cell)
            self.cell = None
        if tag == "table":
            self.depth -= 1
            if self.depth < 0:
                raise ValueError("unbalanced table closing tag")


def parse_table_html(value: str, max_cells: int = 2048) -> dict:
    if len(value) > 2_000_000:
        raise ValueError("table HTML exceeds limit")
    parser = _TableParser(max_cells)
    parser.feed(value)
    parser.close()
    if parser.depth != 0 or parser.cell is not None or not parser.cells:
        raise ValueError("incomplete or empty table")
    cells = parser.cells
    rows = max(c["row"] + c["rowspan"] for c in cells)
    cols = max(c["column"] + c["colspan"] for c in cells)
    headers = []
    for row in range(rows):
        items = [c for c in cells if c["row"] == row]
        if items and all(c["is_header"] for c in items):
            headers.append(row)
        else:
            break
    complete = len(parser.occupied) == rows * cols
    return {"cells": cells, "rows": rows, "columns": cols, "header_rows": headers, "rectangular": complete}


def table_html(cells: list[dict]) -> str:
    output = ["<table>"]
    for row in sorted({c["row"] for c in cells}):
        output.append("<tr>")
        for cell in sorted((c for c in cells if c["row"] == row), key=lambda c: c["column"]):
            tag = "th" if cell.get("is_header") else "td"
            attrs = "".join(f' {key}="{int(cell.get(key, 1))}"' for key in ("rowspan", "colspan") if cell.get(key, 1) > 1)
            output.append(f"<{tag}{attrs}>{html.escape(cell.get('text') or '')}</{tag}>")
        output.append("</tr>")
    return "".join(output) + "</table>"


def table_parts(block: dict, max_chars: int) -> list[str]:
    value = block.get("table_html") or block.get("markdown") or ""
    if len(value) <= max_chars:
        return [value]
    try:
        data = parse_table_html(value)
    except ValueError:
        return [value]
    cells, headers = data["cells"], data["header_rows"]
    if not headers or not data["rectangular"] or any(c["rowspan"] > 1 for c in cells):
        return [value]
    head = [c for c in cells if c["row"] in headers]
    parts, current = [], []
    for row in sorted({c["row"] for c in cells if c["row"] not in headers}):
        items = [c for c in cells if c["row"] == row]
        if current and len(table_html(head + current + items)) > max_chars:
            parts.append(table_html(head + current))
            current = []
        current.extend(items)
    if current:
        parts.append(table_html(head + current))
    return parts or [value]


def otsl_to_html(value: str) -> str:
    """Decode bounded PaddleOCR-VL OTSL-v1 table strings into HTML."""
    if not isinstance(value, str) or len(value) > 32768:
        raise ValueError("OTSL response exceeds limits")
    pieces = OTSL_TOKENS.split(value)
    if pieces[0].strip() or len(pieces) < 3:
        raise ValueError("OTSL must start with a cell token")
    rows, row = [], []
    for index in range(1, len(pieces), 2):
        token, text = pieces[index], pieces[index + 1]
        if token != "<fcel>" and text.strip():
            raise ValueError("OTSL continuation/empty/separator token carries text")
        if token == "<nl>":
            if not row or len(rows) >= 256 or (rows and len(row) != len(rows[0])):
                raise ValueError("OTSL has empty or ragged rows")
            rows.append(row)
            row = []
        else:
            row.append((token, text.strip()))
            if len(row) > 256 or sum(len(r) for r in rows) + len(row) > 8192:
                raise ValueError("OTSL grid exceeds limits")
    if row or not rows:
        raise ValueError("OTSL missing terminal row separator")
    grid, cells = [], []
    for r, source_row in enumerate(rows):
        grid.append([])
        for c, (token, text) in enumerate(source_row):
            if token in {"<fcel>", "<ecel>"}:
                if len(cells) >= 2048:
                    raise ValueError("OTSL cell limit")
                owner = len(cells)
                cells.append({"row": r, "column": c, "text": text, "slots": []})
            elif token == "<lcel>" and c:
                owner = grid[r][c - 1]
                if cells[owner]["row"] != r:
                    raise ValueError("OTSL left continuation is not on origin row")
            elif token == "<ucel>" and r:
                owner = grid[r - 1][c]
                if cells[owner]["column"] != c:
                    raise ValueError("OTSL upper continuation is not on origin column")
            elif token == "<xcel>" and r and c:
                owner = grid[r - 1][c]
                if owner != grid[r][c - 1] or cells[owner]["row"] >= r or cells[owner]["column"] >= c:
                    raise ValueError("OTSL cross continuation has inconsistent owners")
            else:
                raise ValueError("OTSL orphan continuation")
            grid[r].append(owner)
            cells[owner]["slots"].append((r, c))
    output = ["<table>"]
    for r in range(len(rows)):
        output.append("<tr>")
        for cell in (cell for cell in cells if cell["row"] == r):
            slots = cell["slots"]
            rs = max(y for y, _ in slots) - r + 1
            cs = max(x for _, x in slots) - cell["column"] + 1
            if len(slots) != rs * cs:
                raise ValueError("OTSL merged cell is not rectangular")
            attrs = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cs}"' if cs > 1 else "")
            output.append(f"<td{attrs}>{html.escape(cell['text'])}</td>")
        output.append("</tr>")
    return "".join(output) + "</table>"


# ---------------------------------------------------------------------------
# Word-to-cell geometric alignment & OpenCV ruled-table grid reader
# ---------------------------------------------------------------------------

def _align_box(value):
    if (
        not isinstance(value, (list, tuple)) or len(value) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
        or value[2] <= value[0] or value[3] <= value[1]
    ):
        raise ValueError("invalid word/cell bbox")
    return list(value)


def _cell_polygon(cell):
    if "polygon" in cell:
        points = cell["polygon"]
        if (
            not isinstance(points, (list, tuple)) or len(points) != 4
            or any(
                not isinstance(p, (list, tuple)) or len(p) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000 for v in p)
                for p in points
            )
        ):
            raise ValueError("invalid cell polygon")
        polygon = np.array(points, dtype=np.float32)
    else:
        a, b, c, d = _align_box(cell.get("bbox"))
        if max(abs(v) for v in (a, b, c, d)) > 10000:
            raise ValueError("cell bbox exceeds coordinate limit")
        polygon = np.array([[a, b], [c, b], [c, d], [a, d]], dtype=np.float32)
    if not cv2.isContourConvex(polygon) or cv2.contourArea(polygon) <= 0:
        raise ValueError("cell polygon must be a nondegenerate convex quadrilateral")
    return polygon


def match_table_words(words, cells, image_size, *, min_coverage: float = 0.8, competing_coverage: float = 0.2):
    if (
        not isinstance(image_size, (list, tuple)) or len(image_size) != 2
        or any(type(v) is not int or not 0 < v <= 10000 for v in image_size)
    ):
        raise ValueError("invalid image size")
    if (
        not isinstance(words, list) or not isinstance(cells, list)
        or len(words) > 8192 or len(cells) > 2048 or len(words) * len(cells) > 2_000_000
    ):
        raise ValueError("table word/cell accounting exceeds limits")
    if (
        type(min_coverage) not in (int, float) or type(competing_coverage) not in (int, float)
        or not 0 <= competing_coverage < min_coverage <= 1
    ):
        raise ValueError("invalid assignment thresholds")
    width, height = image_size
    polygons, invalid = [], []
    for index, cell in enumerate(cells):
        try:
            polygon = _cell_polygon(cell)
            if (
                polygon[:, 0].min() < 0 or polygon[:, 1].min() < 0
                or polygon[:, 0].max() > width or polygon[:, 1].max() > height
            ):
                raise ValueError("cell polygon outside crop")
            polygons.append((
                index,
                polygon,
                [
                    float(polygon[:, 0].min()), float(polygon[:, 1].min()),
                    float(polygon[:, 0].max()), float(polygon[:, 1].max()),
                ],
            ))
        except (ValueError, TypeError, AttributeError):
            invalid.append(index)
    assignments, counts = [], {"unique": 0, "ambiguous": 0, "unmatched": 0, "partial": 0}
    for index, word in enumerate(words):
        if not isinstance(word, dict) or not isinstance(word.get("text"), str) or not word["text"].strip():
            raise ValueError("invalid source OCR word")
        box = _align_box(word.get("bbox"))
        x1, y1, x2, y2 = box
        if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
            raise ValueError("source OCR word outside crop")
        area = (x2 - x1) * (y2 - y1)
        rect = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32)
        overlaps = []
        for cell_index, polygon, bounds in polygons:
            if min(x2, bounds[2]) <= max(x1, bounds[0]) or min(y2, bounds[3]) <= max(y1, bounds[1]):
                continue
            intersection, _ = cv2.intersectConvexConvex(rect, polygon)
            if intersection > 0:
                overlaps.append((cell_index, min(1.0, max(0.0, float(intersection) / area))))
        overlaps.sort(key=lambda item: (-item[1], item[0]))
        top = overlaps[0][1] if overlaps else 0
        competitor = len(overlaps) > 1 and overlaps[1][1] > competing_coverage
        status = (
            "unmatched" if not overlaps else "ambiguous" if competitor
            else "partial" if top < min_coverage else "unique"
        )
        counts[status] += 1
        assignments.append({
            "word_index": index,
            "status": status,
            "cell_index": overlaps[0][0] if status == "unique" else None,
            "overlapping_cell_count": len(overlaps),
            "overlaps_truncated": len(overlaps) > 8,
            "overlaps": [{"cell_index": i, "word_coverage": round(score, 6)} for i, score in overlaps[:8]],
        })
    return {
        "version": TABLE_ALIGNMENT_VERSION,
        "coordinate_frame": "source_crop_pixels",
        "image_size": list(image_size),
        "word_count": len(words),
        "cell_count": len(cells),
        "invalid_cell_indices": invalid,
        "counts": counts,
        "assignments": assignments,
        "min_coverage": min_coverage,
        "competing_coverage": competing_coverage,
        "complete_unique_assignment": bool(words) and not invalid and counts["unique"] == len(words),
        "recognition_accuracy_verified": False,
        "topology_verified": False,
        "table_existence_verified": False,
    }


def _grid_positions(mask, axis: int, length: int) -> list[int]:
    values = np.flatnonzero(np.count_nonzero(mask, axis=axis) > 0.45 * length)
    groups = np.split(values, np.where(np.diff(values) > 3)[0] + 1)
    return [int(np.median(group)) for group in groups if len(group)]


def _inset_cell(box: list[int]) -> list[int]:
    left, top, right, bottom = box
    inset = min(8, (right - left) // 8, (bottom - top) // 8)
    return [left + inset, top + inset, right - inset, bottom - inset]


class RuledTableDetector:
    """Propose page regions for connected, axis-aligned ruled tables using OpenCV."""

    identity = {"name": "opencv_ruled_table_detector", "version": 1, "device": "cpu"}

    def __call__(self, image_path: str | Path) -> list[dict]:
        with Image.open(image_path) as opened:
            darkest = np.asarray(opened.convert("RGB")).min(axis=2)
        height, width = darkest.shape
        binary = cv2.adaptiveThreshold(
            darkest, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
        )
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(12, width // 30)), np.uint8))
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(12, height // 30), 1), np.uint8))
        contours, _ = cv2.findContours(cv2.bitwise_or(horizontal, vertical), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        junctions = cv2.bitwise_and(horizontal, vertical)
        regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 0.08 * width or h < 0.05 * height:
                continue
            crop = np.s_[y:y + h, x:x + w]
            xs = _grid_positions(vertical[crop], 0, h)
            ys = _grid_positions(horizontal[crop], 1, w)
            if min(len(xs), len(ys)) < 3 or (len(xs) - 1) * (len(ys) - 1) > 256:
                continue
            hits = [
                [bool(junctions[max(0, y + row - 3):y + row + 4, max(0, x + col - 3):x + col + 4].any()) for col in xs]
                for row in ys
            ]
            if all(hits[r][c] for r in (0, -1) for c in (0, -1)) and sum(map(sum, hits)) >= 0.65 * len(xs) * len(ys):
                regions.append({"bbox": [x, y, x + w, y + h], "kind": "table"})
        return sorted(regions, key=lambda region: (region["bbox"][1], region["bbox"][0]))


class GridTableReader:
    """CPU ruled-table reader using OpenCV grid topology + Tesseract cell cross-read."""

    identity = {
        "name": "opencv_grid_tesseract",
        "version": 5,
        "cell_source": "original_rgb_with_inset_and_white_padding",
        "word_assignment": TABLE_ALIGNMENT_VERSION,
    }

    def __init__(self, language: str = "vie", max_cells: int = 256):
        self.language = language
        self.max_cells = max_cells
        self.identity = {**type(self).identity, "language": language, "max_cells": max_cells}
        self.cacheable = True

    def __call__(self, crop: str | Path, timeout: float) -> dict:
        from idp.backends.text_ocr import parse_hocr_lines, run_tesseract

        crop = Path(crop)
        started = time.monotonic()
        image = cv2.imread(str(crop), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("cannot read table crop")
        height, width = image.shape
        original_rgb = cv2.imread(str(crop), cv2.IMREAD_COLOR)
        if original_rgb is None:
            raise ValueError("cannot read original RGB table crop")
        binary = cv2.adaptiveThreshold(
            image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
        )
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(12, width // 12)), np.uint8))
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(12, height // 12), 1), np.uint8))

        xs, ys = _grid_positions(vertical, 0, height), _grid_positions(horizontal, 1, width)
        if len(xs) < 2 or len(ys) < 2:
            raise ValueError("no reliable ruled-table grid; use an external table reader")
        nr, nc = len(ys) - 1, len(xs) - 1
        if nr * nc > self.max_cells or min(np.diff(xs)) < 8 or min(np.diff(ys)) < 8:
            raise ValueError("table grid exceeds cell limits or is ambiguous")
        if (
            xs[0] > np.median(np.diff(xs)) * 0.6
            or width - 1 - xs[-1] > np.median(np.diff(xs)) * 0.6
            or ys[0] > np.median(np.diff(ys)) * 0.6
            or height - 1 - ys[-1] > np.median(np.diff(ys)) * 0.6
        ):
            raise ValueError("table outer boundary is missing; crop may truncate rows or columns")
        parent = list(range(nr * nc))

        def root(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def join(a: int, b: int) -> None:
            parent[root(a)] = root(b)

        for r in range(nr):
            for c in range(nc):
                if c + 1 < nc:
                    edge = vertical[ys[r] + 3:ys[r + 1] - 3, xs[c + 1] - 2:xs[c + 1] + 3]
                    if not edge.size or np.mean(np.any(edge > 0, axis=1)) < 0.6:
                        join(r * nc + c, r * nc + c + 1)
                if r + 1 < nr:
                    edge = horizontal[ys[r + 1] - 2:ys[r + 1] + 3, xs[c] + 3:xs[c + 1] - 3]
                    if not edge.size or np.mean(np.any(edge > 0, axis=0)) < 0.6:
                        join(r * nc + c, (r + 1) * nc + c)
        groups: dict[int, list[tuple[int, int]]] = {}
        for r in range(nr):
            for c in range(nc):
                groups.setdefault(root(r * nc + c), []).append((r, c))
        cells = []
        for group in groups.values():
            r1, c1 = min(r for r, _ in group), min(c for _, c in group)
            r2, c2 = max(r for r, _ in group) + 1, max(c for _, c in group) + 1
            if len(group) != (r2 - r1) * (c2 - c1):
                raise ValueError("nonrectangular merged table cell")
            cells.append({
                "row": r1, "column": c1, "rowspan": r2 - r1, "colspan": c2 - c1,
                "is_header": False, "bbox": [xs[c1], ys[r1], xs[c2], ys[r2]], "text": "",
            })
        grid = cv2.bitwise_or(horizontal, vertical)
        clean = cv2.inpaint(image, cv2.dilate(grid, np.ones((3, 3), np.uint8)), 3, cv2.INPAINT_TELEA)
        scale = min(2.0 if width < 800 else 1.0, (2_000_000 / (width * height)) ** 0.5)
        if scale != 1:
            clean = cv2.resize(clean, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ocr_image = crop.with_name(crop.stem + "_text.png")
        if not cv2.imwrite(str(ocr_image), clean):
            raise ValueError("cannot save table OCR image")
        lines = parse_hocr_lines(
            run_tesseract(
                ocr_image, crop.with_name(crop.stem + "_table"),
                self.language, 6, timeout=max(0.001, timeout - (time.monotonic() - started)),
            )
        )
        words = [word for line in lines for word in line["words"]]
        words = [{**word, "bbox": [x / scale for x in word["bbox"]]} for word in words]
        alignment = match_table_words(words, cells, [width, height])
        assigned = {i: [] for i in range(len(cells))}
        for item in alignment["assignments"]:
            if item["status"] == "unique":
                assigned[item["cell_index"]].append(words[item["word_index"]])
        unassigned = [item["word_index"] for item in alignment["assignments"] if item["status"] != "unique"]
        alignment_summary = {key: value for key, value in alignment.items() if key != "assignments"}
        alignment_summary.update(
            unassigned_word_indices=unassigned,
            source_hocr_path=str(crop.with_name(crop.stem + "_table").with_suffix(".hocr")),
        )
        disagreements, budget_hit = len(unassigned), False
        for index, cell in enumerate(cells):
            selected = assigned[index]
            cell["text"] = " ".join(
                word["text"] for word in sorted(selected, key=lambda w: (round(w["bbox"][1] / 8), w["bbox"][0]))
            )
            cell["confidence"] = sum(w["confidence"] for w in selected) / (100 * len(selected)) if selected else None
            if len(cells) <= 32 or (cell["confidence"] or 0) < 0.75:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0.05:
                    budget_hit = True
                    continue
                left, top, right, bottom = _inset_cell(cell["bbox"])
                local = original_rgb[top:bottom, left:right]
                if not local.size:
                    continue
                if scale != 1:
                    local = cv2.resize(local, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                local = cv2.copyMakeBorder(local, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                cell_image = crop.with_name(crop.stem + f"_cell{index:03d}.png")
                if not cv2.imwrite(str(cell_image), local):
                    raise ValueError("cannot save cell OCR image")
                try:
                    reading = parse_hocr_lines(run_tesseract(cell_image, cell_image.with_suffix(""), self.language, 6, timeout=remaining))
                    text = " ".join(line["text"] for line in reading).strip()
                    if text:
                        score = sum(line["confidence"] for line in reading) / (100 * len(reading))
                        baseline = cell["text"]
                        if baseline and text != baseline:
                            cell["cell_local_reading"] = text
                            disagreements += 1
                        elif text == baseline or (score >= 0.75 and any(ch.isalnum() for ch in text)):
                            cell["text"] = text
                            cell["confidence"] = max(cell["confidence"] or 0, score)
                except RuntimeError:
                    budget_hit = True
        if not any(cell["text"] for cell in cells):
            raise ValueError("table OCR produced no text")
        return {
            "table_html": table_html(cells),
            "cells": cells,
            "header_known": False,
            "cell_disagreements": disagreements,
            "word_alignment": alignment_summary,
            "ocr_budget_exhausted": budget_hit,
            "ocr_confidence": sum(w["confidence"] for w in words) / (100 * len(words)) if words else 0,
        }
