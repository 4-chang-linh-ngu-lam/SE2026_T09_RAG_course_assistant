"""Bounded OTSL-v1 table decoding at the standalone IDP model boundary.

Token meanings follow PaddleOCR-VL's OTSL format (PaddleX paddleocr_vl/uilts.py).
This decoder rejects ragged/incomplete topology instead of padding missing cells.
It does not infer headers, fix cell text, or establish recognition correctness.
"""
from __future__ import annotations

import html
import re

TOKENS = re.compile(r"(<fcel>|<ecel>|<lcel>|<ucel>|<xcel>|<nl>)")


def otsl_to_html(value: str) -> str:
    if not isinstance(value, str) or len(value) > 32768:
        raise ValueError("OTSL response exceeds limits")
    pieces = TOKENS.split(value)
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
