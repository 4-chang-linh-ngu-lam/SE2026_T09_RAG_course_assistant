"""Split OCR lines that run across side-by-side columns.

Tesseract's page segmentation (psm 3) sometimes reads a framed two-column box
or a table next to a sidebar as single lines: "THUẬT NGỮ ¡ KIẾN THỨC, KĨ NĂNG".
Reordering blocks cannot repair that, because one line block already holds
words of both columns. This step regroups the *same recognized words* using
their own pixel boxes:

1. Lines whose vertical extents overlap are one visual row.
2. A row gap is a horizontal whitespace interval between two consecutive
   content words (thin glyphs such as a dashed column rule read as ``¡``/``j``
   are ignored for gap detection but keep their words).
3. A column run is a vertically contiguous set of rows that share one
   whitespace channel. It needs at least two rows with words on both sides,
   and prose-wide text on each side, so a single row of numbers or a table's
   narrow cells is not a column boundary.
4. Every word of the run's rows is assigned to the side of the channel its
   centre falls on (recursively, for three columns). Lines become per-side
   segments; words, pixel boxes and Tesseract confidences are unchanged and
   no word is dropped or duplicated.

Each segment records ``column_run`` (run id, column path, channel) in its
payload. The shared PDF layout (``order_observations``, ``pdf-layout:2``)
reads that hint and keeps a run's columns together in column-major order, so
the projector and chunker receive the corrected order without a second
finalize pipeline. Lines outside any run are returned unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from statistics import median

from .acquire import OcrBlock

VERSION = "word-gutter:1"
# Gap needed between two content words of one row to be a column candidate,
# in units of the row's median word height. Prose word spacing stays far below.
GAP_HEIGHTS = 1.2
# Minimum width of the shared channel across a run, in word heights.
CHANNEL_HEIGHTS = 0.5
# Rows further apart than this (in word heights) do not continue a run.
ROW_GAP_HEIGHTS = 1.3
# Words narrower than this fraction of their row height are rule/noise glyphs.
THIN = 0.25
# Each side must hold prose: median segment width >= this fraction of the page.
MIN_SIDE_WIDTH = 0.12
MAX_DEPTH = 2


def _words(block):
    words = block.payload.get("words") or ()
    out = []
    for index, word in enumerate(words):
        x0, y0, x1, y1 = word["bbox_px"]
        out.append(
            {
                "line": block.key,
                "index": index,
                "text": word["text"],
                "bbox": (x0, y0, x1, y1),
                "confidence": word["confidence"],
            }
        )
    return out


def _rows(words):
    """Group words into rows by vertical overlap of their Tesseract lines."""
    lines = {}
    for word in words:
        lines.setdefault(word["line"], []).append(word)
    spans = []
    for key, items in lines.items():
        spans.append(
            (
                min(w["bbox"][1] for w in items),
                max(w["bbox"][3] for w in items),
                median(w["bbox"][3] - w["bbox"][1] for w in items),
                key,
            )
        )
    spans.sort()
    rows = []
    for y0, y1, height, key in spans:
        if rows:
            row = rows[-1]
            overlap = min(row["y1"], y1) - max(row["y0"], y0)
            if overlap >= 0.5 * min(height, row["h"]):
                row["y0"], row["y1"] = min(row["y0"], y0), max(row["y1"], y1)
                row["lines"].append(key)
                row["words"].extend(lines[key])
                row["h"] = median(w["bbox"][3] - w["bbox"][1] for w in row["words"])
                continue
        rows.append(
            {"y0": y0, "y1": y1, "h": height, "lines": [key], "words": list(lines[key])}
        )
    for row in rows:
        row["words"].sort(key=lambda w: (w["bbox"][0], w["bbox"][2]))
        content = [
            w for w in row["words"] if w["bbox"][2] - w["bbox"][0] > THIN * row["h"]
        ]
        need = GAP_HEIGHTS * row["h"]
        row["gaps"] = [
            (a["bbox"][2], b["bbox"][0])
            for a, b in pairwise(content)
            if b["bbox"][0] - a["bbox"][2] >= need
        ]
        row["content"] = content
    return rows


def _crosses(row, lo, hi):
    return any(w["bbox"][0] < hi and w["bbox"][2] > lo for w in row["content"])


def _sides(row, lo, hi):
    middle = (lo + hi) / 2
    left = any((w["bbox"][0] + w["bbox"][2]) / 2 < middle for w in row["content"])
    right = any((w["bbox"][0] + w["bbox"][2]) / 2 >= middle for w in row["content"])
    return left, right


def _contiguous(upper, lower):
    height = max(upper["h"], lower["h"])
    return lower["y0"] - upper["y1"] <= ROW_GAP_HEIGHTS * height


def _grow(rows, start, gap, floor):
    """Extend a channel seeded at ``rows[start]`` as far as it holds.

    Downward, rows sharing the channel or lying wholly on one side of it
    continue the run. Upward (never above ``floor``), only one-sided rows are
    taken: a heading such as "Giải" directly above a table and a sidebar
    belongs to the column it sits in, not to a separate paragraph.
    """
    lo, hi = gap
    members, split = [start], 1
    for k in range(start + 1, len(rows)):
        row = rows[k]
        if not _contiguous(rows[k - 1], row):
            break
        shared = [
            (max(lo, a), min(hi, b))
            for a, b in row["gaps"]
            if min(hi, b) - max(lo, a) >= CHANNEL_HEIGHTS * row["h"]
        ]
        if shared:
            lo, hi = max(shared, key=lambda g: g[1] - g[0])
            split += 1
        elif _crosses(row, lo, hi):
            # A one-sided row may narrow the channel ("Công thức tính diện
            # tích" under a short "THUẬT NGỮ") while it stays wide enough.
            if not row["content"]:
                break
            x0 = min(w["bbox"][0] for w in row["content"])
            x1 = max(w["bbox"][2] for w in row["content"])
            need = CHANNEL_HEIGHTS * row["h"]
            if x1 <= hi - need and x0 < lo:
                lo = x1
            elif x0 >= lo + need and x1 > hi:
                hi = x0
            else:
                break
        members.append(k)
    for k in range(start - 1, floor - 1, -1):
        if not _contiguous(rows[k], rows[k + 1]) or _crosses(rows[k], lo, hi):
            break
        members.insert(0, k)
    return members, (lo, hi), split


def _valid(rows, members, channel, page_width):
    """Accept only runs that look like independently flowing columns.

    Row-major structures must stay rows: a 2x2 grid of answer options
    ("A. … B. …" / "C. … D. …"), a data table split down the middle, or a
    two-column table whose every row has both cells. Rejecting a run only
    keeps Tesseract's original lines, so every guard errs on that side.
    """
    lo, hi = channel
    middle = (lo + hi) / 2
    widths = ([], [])
    tabular = ([], [])
    two_sided = one_sided = ruled = 0
    for k in members:
        row = rows[k]
        left = [w for w in row["content"] if (w["bbox"][0] + w["bbox"][2]) / 2 < middle]
        right = [w for w in row["content"] if (w["bbox"][0] + w["bbox"][2]) / 2 >= middle]
        if left and right:
            two_sided += 1
        elif left or right:
            one_sided += 1
        # A dashed column rule is read as thin glyphs ("¡", "ị", "j") inside
        # the channel on row after row.
        slack = 0.5 * row["h"]
        if any(
            w["bbox"][2] - w["bbox"][0] <= THIN * row["h"]
            and w["bbox"][0] >= lo - slack
            and w["bbox"][2] <= hi + slack
            for w in row["words"]
        ):
            ruled += 1
        need = GAP_HEIGHTS * row["h"]
        for side, items in enumerate((left, right)):
            if items:
                widths[side].append(
                    max(w["bbox"][2] for w in items) - min(w["bbox"][0] for w in items)
                )
                tabular[side].append(
                    any(b["bbox"][0] - a["bbox"][2] >= need for a, b in pairwise(items))
                )
    return (
        # Two rows are too few to tell a grid of short items from columns.
        two_sided >= 3
        # Columns flow independently (somewhere one side has a row the other
        # lacks) or are separated by a drawn rule. Every row paired across a
        # blank channel is a table's signature.
        and (one_sided >= 1 or ruled * 2 >= two_sided)
        and all(items for items in widths)
        and all(median(items) >= MIN_SIDE_WIDTH * page_width for items in widths)
        # Cells on both sides: a table split between its own columns.
        and not all(sum(flags) * 2 >= len(flags) for flags in tabular)
    )


def _find_runs(words, page_width):
    rows = _rows(words)
    runs, i, floor = [], 0, 0
    while i < len(rows):
        best = None
        for gap in rows[i]["gaps"]:
            members, channel, split = _grow(rows, i, gap, floor)
            if not _valid(rows, members, channel, page_width):
                continue
            rank = (split, len(members), channel[1] - channel[0])
            if best is None or rank > best[0]:
                best = (rank, members, channel)
        if best is None:
            i += 1
            continue
        _, members, channel = best
        runs.append(([w for k in members for w in rows[k]["words"]], channel))
        i = floor = members[-1] + 1
    return runs


def _assign(words, channel, page_width, path, depth, out):
    """Map each word to a column path; recurse for further channels."""
    middle = (channel[0] + channel[1]) / 2
    for side in (0, 1):
        items = [
            w
            for w in words
            if ((w["bbox"][0] + w["bbox"][2]) / 2 >= middle) == bool(side)
        ]
        nested = _find_runs(items, page_width) if depth < MAX_DEPTH else []
        nested_ids = set()
        for number, (inner, inner_channel) in enumerate(nested):
            nested_ids.update(id(w) for w in inner)
            _assign(
                inner,
                inner_channel,
                page_width,
                (*path, side, number),
                depth + 1,
                out,
            )
        for w in items:
            if id(w) not in nested_ids:
                out[id(w)] = ((*path, side), channel)


def split_columns(result, page_width_px=None):
    """Return ``result`` with lines spanning column gutters split per column.

    Only Tesseract line results (``page:block:par:line`` keys with word boxes)
    of whole pages are considered; anything else is returned unchanged.
    """
    blocks = result.blocks
    if not blocks or any(
        len(b.key.split(":")) != 4
        or b.target_region_id is not None
        or not b.payload.get("words")
        for b in blocks
    ):
        return result
    width = page_width_px or result.frame.steps[-1].output_size[0]
    words = [w for b in blocks for w in _words(b)]
    assignment = {}
    for number, (members, channel) in enumerate(_find_runs(words, width)):
        _assign(members, channel, width, (number,), 1, assignment)
    if not assignment:
        return result
    by_line = {}
    for w in words:
        by_line.setdefault(w["line"], []).append(w)
    out = []
    for block in blocks:
        items = by_line[block.key]
        if not any(id(w) in assignment for w in items):
            out.append(block)
            continue
        segments = {}
        for w in items:
            path, channel = assignment[id(w)]
            segments.setdefault(path, (channel, []))[1].append(w)
        page, number, par, line = block.key.split(":")
        for path, (channel, members) in sorted(segments.items()):
            members.sort(key=lambda w: w["index"])
            run = "r" + str(path[0])
            column = "c" + ".".join(str(p) for p in path[1:])
            weights = [max(1, len(w["text"])) for w in members]
            out.append(
                OcrBlock(
                    f"{page}:{number}:{par}~{run}{column}:{line}",
                    " ".join(w["text"] for w in members),
                    (
                        min(w["bbox"][0] for w in members),
                        min(w["bbox"][1] for w in members),
                        max(w["bbox"][2] for w in members),
                        max(w["bbox"][3] for w in members),
                    ),
                    sum(c * w["confidence"] for c, w in zip(weights, members))
                    / sum(weights),
                    label=block.label,
                    payload={
                        "words": tuple(
                            {
                                "text": w["text"],
                                "bbox_px": w["bbox"],
                                "confidence": w["confidence"],
                            }
                            for w in members
                        ),
                        "column_run": {
                            "version": VERSION,
                            "run": run,
                            "path": list(path[1:]),
                            "channel_px": [channel[0], channel[1]],
                            "source_line": block.key,
                        },
                    },
                )
            )
    return replace(result, blocks=tuple(out))
