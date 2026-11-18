"""Publish native table grids as one source-text block instead of cell shards.

The grid topology stays ``structure_unverified``: rows/columns are measured
native geometry, never a verified semantic claim. Cell text is only ever the
exact native source spans that the extractor assigned to the cell, so the
linearized table text is source-preserved text in a different arrangement.
"""

from __future__ import annotations

import html

# TEXT_ALIGNMENT grids are inferred from whitespace only; their cells stay as
# ordinary text blocks until a verifier confirms the topology.
PUBLISHABLE_METHODS = frozenset({"RULED", "FILLED_CELLS"})


def cell_text(cell) -> str:
    return " ".join(span.text for span in cell.source_spans if span.text.strip())


def _rows(table):
    rows = {}
    for cell in table.cells:
        rows.setdefault(cell.row, []).append(cell)
    return [sorted(rows[r], key=lambda c: c.column) for r in sorted(rows)]


def table_text(table) -> str:
    """Deterministic row-major linearization used by both v1 and v2."""
    return "\n".join(
        " | ".join(cell_text(c) for c in row) for row in _rows(table)
    ).strip()


def table_html(table) -> str:
    parts = ["<table>"]
    for row in _rows(table):
        parts.append("<tr>")
        for c in row:
            attrs = ""
            if c.row_span > 1:
                attrs += f' rowspan="{c.row_span}"'
            if c.column_span > 1:
                attrs += f' colspan="{c.column_span}"'
            parts.append(f"<td{attrs}>{html.escape(cell_text(c))}</td>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def table_cells(table) -> list[dict]:
    return [
        {
            "row": c.row,
            "column": c.column,
            "row_span": c.row_span,
            "column_span": c.column_span,
            "text": cell_text(c),
            "bbox": [
                c.location.bbox.x0,
                c.location.bbox.y0,
                c.location.bbox.x1,
                c.location.bbox.y1,
            ],
        }
        for row in _rows(table)
        for c in row
    ]


def publishable_tables(record):
    """Native structure regions whose grid can replace their text shards."""
    structures = record.manifest.structures if record and record.manifest else None
    if not structures:
        return ()
    found = []
    for item in structures.regions:
        candidate = item.trace.candidates[0]
        table = candidate.table
        if (
            table is not None
            and table.geometry_method in PUBLISHABLE_METHODS
            and any(c.source_spans for c in table.cells)
            and table_text(table)
        ):
            found.append((item.trace, candidate, table))
    return tuple(found)


def covered_sources(record, tables=None) -> dict[str, str]:
    """Map observation source_id -> table region id for fully covered text.

    An observation is a table shard when every non-space character of its raw
    source candidate falls inside spans assigned to a publishable table. Text
    only partially inside a table (e.g. a caption merged into the same Poppler
    block) stays an ordinary block so no source text is lost.
    """
    return table_sources(record, tables)[0]


def table_sources(record, tables=None):
    """Return ``(shards, contributors)``.

    ``shards`` maps fully covered observation source_id -> table region id.
    ``contributors`` maps table region id -> source_ids of every observation
    that supplied at least one cell span (its publication state gates the
    table, so a suspect or unauthorized source cannot leak through a grid).
    """
    tables = publishable_tables(record) if tables is None else tables
    if not tables:
        return {}, {}
    spans_by_candidate: dict[str, list[tuple[int, int, str]]] = {}
    for trace, _candidate, table in tables:
        for cell in table.cells:
            for span in cell.source_spans:
                spans_by_candidate.setdefault(span.candidate_id, []).append(
                    (span.start, span.end, trace.region.id)
                )
    covered, contributors = {}, {trace.region.id: set() for trace, _, _ in tables}
    for obs in record.observations:
        trace = obs.extraction
        spans = spans_by_candidate.get(trace.raw_candidate_id)
        if not spans:
            continue
        raw = next(c for c in trace.candidates if c.id == trace.raw_candidate_id)
        text = raw.text or ""
        mask = [ch.isspace() for ch in text]
        regions = set()
        for start, end, region in spans:
            regions.add(region)
            contributors[region].add(obs.source_id)
            for i in range(max(0, start), min(len(text), end)):
                mask[i] = True
        if text.strip() and all(mask) and len(regions) == 1:
            covered[obs.source_id] = next(iter(regions))
    return covered, contributors
