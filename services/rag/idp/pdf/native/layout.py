"""Deterministic page flow shared by typed extraction and visual text merging."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from itertools import pairwise

from idp.evidence.contracts import DeepDocDiagnostic, DeepDocLayoutNode, DeepDocPageLayout, DeepDocPageReason, DeepDocParseStatus, DeepDocRegionEdge, DeepDocRegionGraph, DeepDocRegionRelation


@dataclass(frozen=True, slots=True)
class PdfLayoutPolicy:
    version: str = "pdf-layout:1"
    max_columns: int = 4
    max_pair_checks_per_page: int = 200_000
    max_edges: int = 100_000

    def __post_init__(self):
        for value in (self.max_columns, self.max_pair_checks_per_page, self.max_edges):
            if type(value) is not int or value < 1:
                raise ValueError("layout limits must be positive integers")
        if self.max_columns > 4 or self.version not in {"pdf-layout:1", "pdf-layout:2", "pdf-layout:3"}:
            raise ValueError("unsupported PDF layout policy")

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class _Box:
    key: str
    order: int
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    width: float
    height: float
    role: str
    kind: str


_MARGINAL = {"HEADER", "FOOTER", "PAGE_NUMBER", "FOOTNOTE", "CAPTION", "FORMULA", "HEADING", "TITLE"}


def _columns(boxes, policy):
    """Column gutters and, for ``pdf-layout:3`` columns, the keys of
    one-line rows that separate flow bands (see below)."""
    if not boxes:
        return (), frozenset()
    width, height = boxes[0].width, boxes[0].height
    candidates = [box for box in boxes if box.kind == "TEXT" and box.role not in _MARGINAL and width * 0.12 <= box.x1 - box.x0 <= width * 0.65]
    # Recurrent paragraph starts provide column evidence. Sparse centered titles
    # and isolated labels must not bridge the gutter between body columns.
    starts = []
    for box in sorted(candidates, key=lambda item: item.x0):
        if starts and box.x0 - starts[-1][0].x0 <= max(12, width * 0.04):
            starts[-1].append(box)
        else:
            starts.append([box])
    candidates = [box for group in starts if len(group) >= 2 or max(item.y1 - item.y0 for item in group) >= height * 0.12 for box in group]
    gutters = _gutters(candidates, width, height, policy)
    if gutters or policy.version != "pdf-layout:3" or len(candidates) < 6:
        return gutters, frozenset()
    # pdf-layout:3: a one-line heading or lead-in ("Bài tập 10: Giải các
    # phương trình sau:") spanning the gutter between two exercise columns
    # merged both columns into one, so the list was read row by row (1, 8,
    # 2, 9, ...). Such a line shares no vertical extent with any other
    # candidate; without it the columns must still be well evidenced (each
    # with >= 3 boxes, >= 2 rows paired across the gutter). The removed lines
    # cross the gutter and become flow barriers in ``_page_flow``; so do
    # the short ones inside one column ("Bài tập 2: ..."), otherwise the
    # next exercise would be read before the right column of this one.
    lines = sorted(box.y1 - box.y0 for box in candidates)
    line_height = lines[len(lines) // 2]
    spanning = {
        box.key
        for box in candidates
        if box.y1 - box.y0 <= 1.6 * line_height
        and not any(other.key != box.key and min(box.y1, other.y1) > max(box.y0, other.y0) for other in candidates)
    }
    rest = [box for box in candidates if box.key not in spanning]
    if not spanning or len(rest) < 6:
        return (), frozenset()
    # Another heading merged by Poppler with the formula beside it starts at
    # the headings' margin inside a column; column order would then move the
    # right column of one exercise after the next heading. Keep row order.
    margin = min(box.x0 for box in candidates if box.key in spanning)
    if any(abs(box.x0 - margin) <= 3 for box in rest):
        return (), frozenset()
    gutters = _gutters(rest, width, height, policy, min_boxes=3, min_rows=2)
    if not gutters:
        return (), frozenset()
    # Band separators must be alone in their row among *all* body boxes
    # (narrow formula pieces beside an item are not candidates above).
    body = [box for box in boxes if box.role not in _MARGINAL or box.role in {"HEADING", "TITLE"}]
    rows = frozenset(
        key
        for key in spanning
        for box in [next(item for item in candidates if item.key == key)]
        if not any(other.key != key and min(box.y1, other.y1) > max(box.y0, other.y0) for other in body)
    )
    return gutters, rows


def _gutters(candidates, width, height, policy, *, min_boxes=1, min_rows=1):
    groups = []
    for box in sorted(candidates, key=lambda item: (item.x0, item.x1)):
        if groups and box.x0 <= groups[-1][1] + 2:
            groups[-1][1] = max(groups[-1][1], box.x1)
            groups[-1][2].append(box)
        else:
            groups.append([box.x0, box.x1, [box]])
    if not 2 <= len(groups) <= policy.max_columns:
        return ()
    for group in groups:
        if len(group[2]) < 2 and max(box.y1 - box.y0 for box in group[2]) < height * 0.12:
            return ()
        if len(group[2]) < min_boxes:
            return ()
    for left, right in pairwise(groups):
        if right[0] - left[1] < max(12, width * 0.025) or not _vertical_overlap(left[2], right[2]):
            return ()
        rows = sum(any(min(a.y1, b.y1) > max(a.y0, b.y0) for b in right[2]) for a in left[2])
        if rows < min_rows:
            return ()
    return tuple((left[1] + right[0]) / 2 for left, right in pairwise(groups))


def _vertical_overlap(left, right):
    left = sorted(left, key=lambda box: box.y0)
    right = sorted(right, key=lambda box: box.y0)
    i = j = 0
    while i < len(left) and j < len(right):
        if min(left[i].y1, right[j].y1) > max(left[i].y0, right[j].y0):
            return True
        if left[i].y1 <= right[j].y0:
            i += 1
        else:
            j += 1
    return False


def _flow_key(box):
    return box.y0, box.x0, box.order, box.key


def _page_flow(boxes, policy, check_deadline=None):
    gutters, rows = _columns(boxes, policy)
    positions = {}

    def column(box):
        if box.key in rows:
            return None
        return None if any(box.x0 < gutter < box.x1 for gutter in gutters) else sum(box.x0 >= gutter for gutter in gutters)

    def sort_key(box):
        return box.y0, box.x0, box.order, box.key

    headers = sorted((box for box in boxes if box.role == "HEADER"), key=sort_key)
    tails = sorted((box for box in boxes if box.role in {"FOOTNOTE", "FOOTER", "PAGE_NUMBER"}), key=lambda box: (box.role != "FOOTNOTE", *sort_key(box)))
    marginal = {box.key for box in [*headers, *tails]}
    body = [box for box in boxes if box.key not in marginal]
    barriers = sorted((box for box in body if column(box) is None), key=sort_key)
    pending = [box for box in body if column(box) is not None]
    output = list(headers)
    for band, barrier in enumerate([*barriers, None]):
        if check_deadline:
            check_deadline()
        before = [box for box in pending if barrier is None or box.y0 < barrier.y0]
        selected = {box.key for box in before}
        pending = [box for box in pending if box.key not in selected]
        for box in sorted(before, key=lambda box: (column(box), *sort_key(box))):
            output.append(box)
            positions[box.key] = (band, column(box))
        if barrier is not None:
            output.append(barrier)
            positions[barrier.key] = (band, None)
    output.extend(tails)
    for box in [*headers, *tails]:
        positions[box.key] = (-1 if box.role == "HEADER" else len(barriers) + 1, None)
    return output, positions, len(gutters) + 1


def order_observations(observations, *, caption_links=(), policy=None, check_deadline=None, structures=()):
    """Reorder whole records; source ID/text/locations/candidates stay unchanged."""
    policy = policy or PdfLayoutPolicy()
    by_page = defaultdict(list)
    missing = []
    unpositioned = defaultdict(list)
    for item in observations:
        if not item.locations:
            missing.append(item)
            continue
        location = item.locations[0]
        bbox = location.bbox
        if bbox is None or bbox.x1 <= bbox.x0 or bbox.y1 <= bbox.y0:
            unpositioned[location.page].append(item)
            continue
        by_page[location.page].append(
            _Box(item.source_id, item.order, location.page, bbox.x0, bbox.y0, bbox.x1, bbox.y1, location.page_width, location.page_height, item.type_hint or "", item.kind.value)
        )
    by_id = {item.source_id: item for item in observations}
    ordered, columns, counts = [], {}, {}
    for page in sorted(by_page.keys() | unpositioned.keys()):
        page_boxes = by_page[page]
        groups = {}
        if policy.version in {"pdf-layout:2", "pdf-layout:3"}:
            for structured in structures:
                trace = structured.trace
                candidate = next(c for c in trace.candidates if c.id == trace.source_candidate_id)
                if candidate.table is None or not trace.region.locations or trace.region.locations[0].page != page:
                    continue
                location = trace.region.locations[0]
                b = location.bbox
                if b is None:
                    continue
                cells = []
                for box in page_boxes:
                    area = (box.x1-box.x0)*(box.y1-box.y0)
                    intersection = max(0,min(box.x1,b.x1)-max(box.x0,b.x0))*max(0,min(box.y1,b.y1)-max(box.y0,b.y0))
                    if area > 0 and intersection / area >= .8:
                        cells.append(box)
                if not cells:
                    continue
                ids = {box.key for box in cells}
                key = trace.region.id
                groups[key] = sorted(cells, key=lambda box:(round(box.y0/3), box.x0, box.order))
                page_boxes = [box for box in page_boxes if box.key not in ids]
                page_boxes.append(_Box(key,min(box.order for box in cells),page,b.x0,b.y0,b.x1,b.y1,location.page_width,location.page_height,"TABLE","TABLE"))
            # OCR lines split at a column gutter (idp.pdf.columns) carry their
            # run and column path. A run is placed once in the page flow and
            # expanded column by column; source records are unchanged.
            runs = defaultdict(list)
            for box in page_boxes:
                if box.key in groups:
                    continue
                recognition = (by_id[box.key].attributes or {}).get("recognition") or {}
                hint = (recognition.get("payload") or {}).get("column_run")
                if hint:
                    runs[(recognition.get("frame"), hint["run"])].append((tuple(hint["path"]), box))
            for (frame, run), members in sorted(runs.items(), key=lambda item: min(box.order for _, box in item[1])):
                key = "column-run:" + str(frame) + ":" + run
                cells = [box for _, box in sorted(members, key=lambda item: (item[0], *_flow_key(item[1])))]
                groups[key] = cells
                ids = {box.key for box in cells}
                page_boxes = [box for box in page_boxes if box.key not in ids]
                first = cells[0]
                page_boxes.append(_Box(key, min(box.order for box in cells), page, min(box.x0 for box in cells), min(box.y0 for box in cells), max(box.x1 for box in cells), max(box.y1 for box in cells), first.width, first.height, "COLUMN_RUN", "TEXT"))
        boxes, positions, count = _page_flow(page_boxes, policy, check_deadline)
        expanded = []
        for box in boxes:
            if box.key in groups:
                for cell in groups[box.key]:
                    expanded.append(cell)
                    positions[cell.key] = positions[box.key]
            else:
                expanded.append(box)
        boxes = expanded
        counts[page] = count
        columns.update({key: column for key, (_, column) in positions.items()})
        ordered.extend(by_id[box.key] for box in boxes)
        ordered.extend(sorted(unpositioned[page], key=lambda item: item.order))
    ordered.extend(sorted(missing, key=lambda item: item.order))
    # Move each caption once, adjacent to its source figure/table. The structural
    # relation is separate from the resulting precedence chain.
    targets = dict(caption_links)
    if any(key not in by_id or target not in by_id or key == target or target in targets or not by_id[key].locations or not by_id[key].locations[0].bbox for key, target in targets.items()):
        raise ValueError("caption flow links must reference known independent source regions with geometry")
    attached = defaultdict(list)
    for item in ordered:
        if item.source_id in targets:
            attached[targets[item.source_id]].append(item)
    result = []
    for item in ordered:
        if item.source_id in targets:
            continue
        captions = attached[item.source_id]
        middle = (item.locations[0].bbox.y0 + item.locations[0].bbox.y1) / 2 if item.locations and item.locations[0].bbox else -math.inf
        above = [caption for caption in captions if caption.locations[0].bbox.y1 <= middle]
        above_ids = {caption.source_id for caption in above}
        result.extend(above)
        result.append(item)
        result.extend(caption for caption in captions if caption.source_id not in above_ids)
    if len(result) != len(observations) or {item.source_id for item in result} != by_id.keys():
        raise ValueError("PDF reading order must preserve each source observation exactly once")
    return tuple(replace(item, order=index, source_order=item.source_order if item.source_order is not None else item.order) for index, item in enumerate(result)), columns, counts


def annotate_box_flow(boxes, *, page_sizes):
    """Assign flow groups before the visual parser merges source line boxes."""
    by_page = defaultdict(list)
    fallback = {}
    for box in boxes:
        page = box["page_number"]
        width, height = fallback.get(page, (0, 0))
        fallback[page] = max(width, box["x1"]), max(height, box["bottom"])
    for index, box in enumerate(boxes):
        page = box["page_number"]
        width, height = page_sizes.get(page, fallback[page])
        role = str(box.get("layout_type", "text")).upper().replace(" ", "_")
        kind = "FIGURE" if role == "FIGURE" else "TABLE" if role == "TABLE" else "TEXT"
        if role in {"EQUATION", "FIGURE_CAPTION", "TABLE_CAPTION"}:
            role = "FORMULA" if role == "EQUATION" else "CAPTION"
        by_page[page].append(_Box(str(index), index, page, float(box["x0"]), float(box["top"]), float(box["x1"]), float(box["bottom"]), float(width), float(height), role, kind))
    output = []
    for page in sorted(by_page):
        flow, positions, _ = _page_flow(by_page[page], PdfLayoutPolicy())
        for item in flow:
            box = boxes[item.order]
            band, column = positions[item.key]
            box["col_id"] = column
            box["_flow_group"] = (band, column)
            output.append(box)
    return output


def apply_pdf_layout(parsed, *, policy=None, check_deadline=None):
    from idp.pdf.native.regions import geometry_relations
    from idp.pdf.native.routing import route_regions

    if parsed.manifest is None:
        raise ValueError("PDF layout requires a source-bound extraction manifest")
    if parsed.manifest.region_graph is not None:
        if policy is not None and parsed.manifest.region_graph.policy_sha256 != policy.fingerprint:
            raise ValueError("PDF layout policy conflicts with existing graph")
        return parsed
    policy = policy or PdfLayoutPolicy()
    edges, diagnostics = geometry_relations(parsed.observations, policy, check_deadline=check_deadline)
    by_region = {item.extraction.region.id: item for item in parsed.observations}
    captions = [(by_region[edge.from_region_id].source_id, by_region[edge.to_region_id].source_id) for edge in edges if edge.relation == DeepDocRegionRelation.CAPTION_OF]
    observations, columns, counts = order_observations(parsed.observations, caption_links=captions, policy=policy, check_deadline=check_deadline, structures=parsed.manifest.structures.regions if parsed.manifest.structures else ())
    nodes = tuple(DeepDocLayoutNode(item.extraction.region.id, item.source_id, item.source_order, columns.get(item.source_id)) for item in observations)
    reading_order = tuple(node.region_id for node in nodes)
    remaining = max(0, policy.max_edges - len(edges))
    precedence = [DeepDocRegionEdge(left, right, DeepDocRegionRelation.PRECEDES, "PAGE_FLOW") for left, right in pairwise(reading_order)]
    if len(precedence) > remaining:
        diagnostics = (
            *diagnostics,
            DeepDocDiagnostic("PDF_LAYOUT_EDGE_LIMIT", "Precedence chain exceeded the graph budget; full reading order and source records were preserved", affects_structural_completeness=True),
        )
    edges.extend(precedence[:remaining])
    facts = {page.page: page for page in parsed.manifest.pages}
    missing_geometry = {item.locations[0].page for item in observations if item.locations and item.locations[0].bbox is None}
    pages = []
    for page in sorted(facts.keys() | counts.keys()):
        fact = facts.get(page)
        reasons = []
        if fact is not None and DeepDocPageReason.NO_NATIVE_TEXT in fact.layout_reasons:
            reasons.append("NO_NATIVE_TEXT")
        if page in missing_geometry:
            reasons.append("MISSING_GEOMETRY")
        if fact is not None and DeepDocPageReason.COLUMN_LAYOUT_CANDIDATE in fact.layout_reasons and counts.get(page, 1) == 1:
            reasons.append("COLUMN_GEOMETRY_UNRESOLVED")
        pages.append(DeepDocPageLayout(page, counts.get(page, 1), "NATIVE_GEOMETRY" if parsed.parser_name == "poppler-pdftotext" else "OBSERVED_LAYOUT", tuple(reasons)))
    graph = DeepDocRegionGraph(nodes, tuple(edges), reading_order, route_regions(observations, edges), tuple(pages), policy.fingerprint, complete=not diagnostics)
    # Page revisions include physical layout; its first construction invalidates
    # any boundary report assembled before layout was available.
    manifest = replace(parsed.manifest, region_graph=graph, reconciliation=None, status=DeepDocParseStatus.PARTIAL if diagnostics else parsed.manifest.status)
    return replace(parsed, observations=observations, manifest=manifest, diagnostics=(*parsed.diagnostics, *diagnostics))
