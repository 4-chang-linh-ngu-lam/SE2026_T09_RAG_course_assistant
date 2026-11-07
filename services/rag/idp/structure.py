"""Table structure and visual evidence at the standalone IDP boundary."""
from __future__ import annotations

import html
import time
from html.parser import HTMLParser
from pathlib import Path

import cv2
import numpy as np


class _TableParser(HTMLParser):
    def __init__(self, limit):
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
            attrs = dict(attrs)
            try:
                rs, cs = int(attrs.get("rowspan", 1)), int(attrs.get("colspan", 1))
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
            self.cell = {"row": self.row, "column": col, "rowspan": rs, "colspan": cs, "is_header": tag == "th", "text": ""}
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
    """Repeat explicit headers; keep rowspan/unknown-header tables atomic."""
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


def visual_evidence(page: dict, block: dict) -> dict | None:
    if block.get("block_type", block.get("type")) not in {"Table", "Equation", "Picture", "Diagram", "Chart", "PictureGroup"} and not block.get("latex"):
        return None
    image = block.get("block_crop_path") or block.get("crop_path") or next(iter(block.get("asset_paths") or []), None)
    return {
        "page_id": page.get("page_id"), "block_id": block.get("block_id"),
        "kind": block.get("block_type", block.get("type")), "bbox": block.get("bbox"),
        "image_path": image, "page_image": page.get("page_image"),
        "image_sha256": block.get("crop_sha256"),
        "source_image_sha256": page.get("source_image_sha256"),
        "pixel_bbox": block.get("pixel_bbox"),
        "page_image_size": (page.get("structured_enrichment") or {}).get("image_size"),
        "related_block_ids": block.get("related_block_ids") or [],
        "context_relation": "spatial_nearby",
        "context_blocks": [{"block_id": b["block_id"], "text": (b.get("text") or "")[:800], "bbox": b.get("bbox")} for b in page.get("blocks") or [] if b["block_id"] in (block.get("related_block_ids") or [])],
        "caption": block.get("caption"), "description": block.get("description"),
        "figure_description_provenance": block.get("figure_description_provenance"),
        "visual_facts": block.get("visual_facts"),
        "extraction_status": block.get("structured_status"),
    }


class GridTableReader:
    """CPU ruled-table reader. Unknown headers/borderless tables stay review-only.

    Detect geometry first, then assign recognized words to cells. No invented
    first-row headers, no guess that a missing grid line means an empty cell.
    """
    identity = {"name": "opencv_grid_tesseract", "version": 4, "cell_source": "original_rgb_with_white_padding",
                "word_assignment": "idp-table-word-alignment-1"}

    def __init__(self, language="vie", max_cells=256, *, text_recognizer=None, recognition_options=None):
        from dataclasses import asdict
        from .recognition import RecognitionOptions
        self.language, self.max_cells = language, max_cells
        self.text_recognizer, self.recognition_options = text_recognizer, recognition_options or RecognitionOptions()
        self.identity = {**type(self).identity, "language": language, "max_cells": max_cells,
                         "text_recognizer": getattr(text_recognizer, "identity", None),
                         "recognition_options": asdict(self.recognition_options)}
        self.cacheable = text_recognizer is None or (bool(getattr(text_recognizer, "identity", None)) and getattr(text_recognizer, "cacheable", True))

    def __call__(self, crop: Path, timeout: float) -> dict:
        from .fast import _run_tesseract, parse_hocr_lines

        started = time.monotonic()
        image = cv2.imread(str(crop), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("cannot read table crop")
        height, width = image.shape
        original_rgb = cv2.imread(str(crop), cv2.IMREAD_COLOR)
        if original_rgb is None:
            raise ValueError("cannot read original RGB table crop")
        binary = cv2.adaptiveThreshold(image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(12, width // 12)), np.uint8))
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(12, height // 12), 1), np.uint8))

        def positions(mask, axis, length):
            values = np.flatnonzero(np.count_nonzero(mask, axis=axis) > .45 * length)
            groups = np.split(values, np.where(np.diff(values) > 3)[0] + 1)
            return [int(np.median(group)) for group in groups if len(group)]

        xs, ys = positions(vertical, 0, height), positions(horizontal, 1, width)
        if len(xs) < 2 or len(ys) < 2:
            raise ValueError("no reliable ruled-table grid; use an external table reader")
        nr, nc = len(ys) - 1, len(xs) - 1
        if nr * nc > self.max_cells or min(np.diff(xs)) < 8 or min(np.diff(ys)) < 8:
            raise ValueError("table grid exceeds cell limits or is ambiguous")
        if xs[0] > np.median(np.diff(xs)) * .6 or width - 1 - xs[-1] > np.median(np.diff(xs)) * .6 or ys[0] > np.median(np.diff(ys)) * .6 or height - 1 - ys[-1] > np.median(np.diff(ys)) * .6:
            raise ValueError("table outer boundary is missing; crop may truncate rows or columns")
        parent = list(range(nr * nc))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def join(a, b):
            parent[root(a)] = root(b)

        for r in range(nr):
            for c in range(nc):
                if c + 1 < nc:
                    edge = vertical[ys[r] + 3:ys[r + 1] - 3, xs[c + 1] - 2:xs[c + 1] + 3]
                    if not edge.size or np.mean(np.any(edge > 0, axis=1)) < .6:
                        join(r * nc + c, r * nc + c + 1)
                if r + 1 < nr:
                    edge = horizontal[ys[r + 1] - 2:ys[r + 1] + 3, xs[c] + 3:xs[c + 1] - 3]
                    if not edge.size or np.mean(np.any(edge > 0, axis=0)) < .6:
                        join(r * nc + c, (r + 1) * nc + c)
        groups = {}
        for r in range(nr):
            for c in range(nc):
                groups.setdefault(root(r * nc + c), []).append((r, c))
        cells = []
        for group in groups.values():
            r1, c1 = min(r for r, _ in group), min(c for _, c in group)
            r2, c2 = max(r for r, _ in group) + 1, max(c for _, c in group) + 1
            if len(group) != (r2 - r1) * (c2 - c1):
                raise ValueError("nonrectangular merged table cell")
            cells.append({"row": r1, "column": c1, "rowspan": r2 - r1, "colspan": c2 - c1, "is_header": False, "bbox": [xs[c1], ys[r1], xs[c2], ys[r2]], "text": ""})
        # Grid lines interfere with OCR segmentation. Read a derived image,
        # preserving the original crop as the only source evidence.
        grid = cv2.bitwise_or(horizontal, vertical)
        clean = cv2.inpaint(image, cv2.dilate(grid, np.ones((3, 3), np.uint8)), 3, cv2.INPAINT_TELEA)
        scale = min(2.0 if width < 800 else 1.0, (2_000_000 / (width * height)) ** .5)
        if scale != 1:
            clean = cv2.resize(clean, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ocr_image = crop.with_name(crop.stem + "_text.png")
        if not cv2.imwrite(str(ocr_image), clean):
            raise ValueError("cannot save table OCR image")
        lines = parse_hocr_lines(_run_tesseract(ocr_image, crop.with_name(crop.stem + "_table"), self.language, 6, timeout=max(.001, timeout - (time.monotonic() - started))))
        words = [word for line in lines for word in line["words"]]
        words = [{**word, "bbox": [x / scale for x in word["bbox"]]} for word in words]
        from .table_alignment import match_table_words
        alignment = match_table_words(words, cells, [width, height])
        assigned = {i: [] for i in range(len(cells))}
        for item in alignment["assignments"]:
            if item["status"] == "unique":
                assigned[item["cell_index"]].append(words[item["word_index"]])
        unassigned = [item["word_index"] for item in alignment["assignments"] if item["status"] != "unique"]
        # Preserve unresolved words in the retained hOCR instead of silently
        # dropping them or borrowing a nearest cell to make a table complete.
        # A later cell-local reading cannot resolve the whole-crop coverage gap.
        alignment_summary = {key: value for key, value in alignment.items() if key != "assignments"}
        alignment_summary.update(unassigned_word_indices=unassigned,
                                 source_hocr_path=str(crop.with_name(crop.stem + "_table").with_suffix(".hocr")))
        disagreements, budget_hit = len(unassigned), False
        for index, cell in enumerate(cells):
            x1, y1, x2, y2 = cell["bbox"]
            selected = assigned[index]
            cell["text"] = " ".join(word["text"] for word in sorted(selected, key=lambda w: (round(w["bbox"][1] / 8), w["bbox"][0])))
            cell["confidence"] = sum(w["confidence"] for w in selected) / (100 * len(selected)) if selected else None
            # Small tables get cell-local readings. For large tables retry only
            # weak cells, all within this region's shared subprocess budget.
            if len(cells) <= 32 or (cell["confidence"] or 0) < .75:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= .05:
                    budget_hit = True
                    continue
                # Inpainting can erase strokes touching a detected grid line.
                # Use it only for whole-table geometry/word assignment. Cell
                # recognition reads original colour pixels with an inset that
                # removes borders, then adds white segmentation padding.
                left, top, right, bottom = cell["bbox"]
                local = original_rgb[top + 3:bottom - 3, left + 3:right - 3]
                if not local.size:
                    continue
                if scale != 1:
                    local = cv2.resize(local, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                local = cv2.copyMakeBorder(local, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                cell_image = crop.with_name(crop.stem + f"_cell{index:03d}.png")
                cv2.imwrite(str(cell_image), local)
                try:
                    reading = parse_hocr_lines(_run_tesseract(cell_image, cell_image.with_suffix(""), self.language, 6, timeout=remaining))
                    text = " ".join(line["text"] for line in reading).strip()
                    if text:
                        if text != cell["text"]:
                            cell["whole_table_reading"] = cell["text"]
                            disagreements += 1
                        cell["text"] = text
                        cell["confidence"] = sum(line["confidence"] for line in reading) / (100 * len(reading))
                except RuntimeError:
                    budget_hit = True
        if self.text_recognizer:
            from PIL import Image
            from .recognition import RecognitionOptions, read_candidate
            limits = self.recognition_options or RecognitionOptions()
            with Image.open(crop) as source:
                original = source.convert("RGB")
            # Preserve RGB source pixels, independently of the inpainted image
            # used above. Empty Tess cells are also eligible for a second read.
            for index, cell in enumerate(cells):
                remaining = timeout - (time.monotonic() - started)
                if index >= limits.max_blocks or remaining <= .05:
                    budget_hit = True
                    break
                x1, y1, x2, y2 = cell["bbox"]
                box = [x1 + 3, y1 + 3, x2 - 3, y2 - 3]
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                reading = read_candidate(self.text_recognizer, original.crop(box),
                                         crop.with_name(crop.stem + f"_verify{index:03d}.png"),
                                         cell["text"], remaining, language=self.language, options=limits)
                reading["table_crop_bbox"] = box
                cell["text_recognition"] = reading
                if reading.get("deadline_exceeded"):
                    budget_hit = True
                if reading["status"] != "agreement" or reading["unsupported_baseline_characters"]:
                    disagreements += 1
        if not any(cell["text"] for cell in cells):
            raise ValueError("table OCR produced no text")
        return {"table_html": table_html(cells), "cells": cells, "header_known": False, "cell_disagreements": disagreements, "word_alignment": alignment_summary, "ocr_budget_exhausted": budget_hit, "ocr_confidence": sum(w["confidence"] for w in words) / (100 * len(words)) if words else 0}
