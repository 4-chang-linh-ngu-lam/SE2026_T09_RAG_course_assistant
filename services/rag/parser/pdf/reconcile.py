"""Single-pass adjacent-page reconciliation with revisioned dirty windows."""

from collections import Counter
from dataclasses import replace

from ..source_observation import (
    DeepDocPageLink,
    DeepDocReconcilePage,
    DeepDocReconcileWindow,
    DeepDocReconciliationPolicy,
    DeepDocReconciliationReport,
    DeepDocRegionAlias,
    _alias_signature,
    _chapter_start,
    _paragraph_cue,
    _paragraph_region,
    _reconcile_page_fingerprint,
    _reconcile_window_fingerprint,
    _reconciliation_inputs,
    _source_candidate,
    _table_caption,
    _table_columns,
)
from .contracts import _fingerprint
from .fusion import fuse_windows

_MARGINAL = {"HEADER", "FOOTER", "PAGE_NUMBER", "FOOTNOTE", "NAVIGATION", "CAPTION"}


def _box(trace):
    if len(trace.region.locations) != 1 or trace.region.locations[0].bbox is None:
        return None
    loc = trace.region.locations[0]
    box = loc.bbox
    return box.x0 / loc.page_width, box.y0 / loc.page_height, box.x1 / loc.page_width, box.y1 / loc.page_height


def _aliases(traces):
    seen, aliases = {}, []
    for trace in sorted(traces, key=lambda trace: trace.region.id):
        signature = _alias_signature(trace)
        if signature is None:
            continue
        if signature in seen:
            aliases.append(DeepDocRegionAlias(trace.region.id, seen[signature]))
        else:
            seen[signature] = trace.region.id
    return tuple(aliases)


def _caption(table, rows):
    location = table.region.locations[0]
    bbox = location.bbox
    found = []
    for trace in rows:
        box = _box(trace)
        caption = _table_caption(_source_candidate(trace).text)
        if box is None or caption is None or trace.region.source_role in _MARGINAL - {"CAPTION"}:
            continue
        loc = trace.region.locations[0]
        if 0 <= bbox.y0 - loc.bbox.y1 <= 48 and min(bbox.x1, loc.bbox.x1) > max(bbox.x0, loc.bbox.x0):
            found.append((bbox.y0 - loc.bbox.y1, trace.region.id, caption))
    return min(found) if found else None


def _table_reason(first, second, left_rows, right_rows, policy):
    one, two = _source_candidate(first).table, _source_candidate(second).table
    a, b = first.region.locations[0], second.region.locations[0]
    columns1, columns2 = _table_columns(one, a), _table_columns(two, b)
    if one.columns != two.columns or columns1 is None or columns2 is None or any(abs(x - y) > policy.alignment_tolerance for x, y in zip(columns1, columns2, strict=True)):
        return "BLOCKED", "TABLE_COLUMN_GEOMETRY_CONFLICT", ()
    if one.text_coverage != 1.0 or two.text_coverage != 1.0:
        return "UNRESOLVED", "TABLE_SOURCE_COVERAGE_INCOMPLETE", ()
    left, right = _caption(first, left_rows), _caption(second, right_rows)
    supports = tuple(item[1] for item in (left, right) if item)
    if left is None or right is None:
        return "UNRESOLVED", "TABLE_IDENTIFIER_MISSING", supports
    if left[2][0] != right[2][0]:
        return "BLOCKED", "TABLE_IDENTIFIER_CHANGED", supports
    if not right[2][1]:
        return "UNRESOLVED", "TABLE_CONTINUATION_NOT_EXPLICIT", supports
    return "SUPPORTED", "ALIGNED_COLUMNS_AND_EXPLICIT_CONTINUATION_CAPTION", supports


def _reconcile_window(left, by_page, layouts, revisions, source_sha, policy, excluded):
    fingerprint = _reconcile_window_fingerprint(source_sha, policy, left, revisions)
    if left not in by_page or left + 1 not in by_page:
        return DeepDocReconcileWindow(left, fingerprint, "UNRESOLVED", ("NEIGHBOR_NOT_AVAILABLE",))
    first, second = by_page[left], by_page[left + 1]
    if _chapter_start(second):
        return DeepDocReconcileWindow(left, fingerprint, "BLOCKED", ("CHAPTER_OR_HEADING_BOUNDARY",))
    if any(layouts[page].column_count > 1 for page in (left, left + 1) if page in layouts):
        return DeepDocReconcileWindow(left, fingerprint, "UNRESOLVED", ("MULTI_COLUMN_BOUNDARY_UNASSESSED",))

    def boundary(rows, outgoing):
        return [
            trace for trace in rows if trace.region.id not in excluded and (box := _box(trace)) is not None and (box[3] >= 1 - policy.edge_fraction if outgoing else box[1] <= policy.edge_fraction)
        ]

    last, beginning = boundary(first, True), boundary(second, False)
    if len(last) > policy.max_boundary_regions or len(beginning) > policy.max_boundary_regions:
        return DeepDocReconcileWindow(left, fingerprint, "UNRESOLVED", ("BOUNDARY_REGION_BUDGET_EXHAUSTED",))
    pairs = []
    paragraphs1, paragraphs2 = [trace for trace in first if _paragraph_region(trace)], [trace for trace in second if _paragraph_region(trace)]
    if paragraphs1 and paragraphs2 and paragraphs1[-1] in last and paragraphs2[0] in beginning:
        pairs.append(("PARAGRAPH", paragraphs1[-1], paragraphs2[0]))
    tables1 = [trace for trace in last if _source_candidate(trace).table is not None]
    tables2 = [trace for trace in beginning if _source_candidate(trace).table is not None]
    # Do not let a dense/malicious page decide a winner by proposal truncation.
    if len(pairs) + len(tables1) * len(tables2) > min(policy.max_pair_checks, policy.max_links):
        return DeepDocReconcileWindow(left, fingerprint, "UNRESOLVED", ("PAIR_OR_LINK_BUDGET_EXHAUSTED",))
    pairs.extend(("TABLE", one, two) for one in tables1 for two in tables2)
    links = []
    for kind, one, two in pairs:
        support = ()
        if kind == "TABLE":
            state, reason, support = _table_reason(one, two, first, second, policy)
        elif abs(_box(one)[0] - _box(two)[0]) > policy.alignment_tolerance:
            state, reason = "BLOCKED", "PARAGRAPH_ALIGNMENT_CONFLICT"
        elif _paragraph_cue(_source_candidate(one).text, _source_candidate(two).text):
            state, reason = "SUPPORTED", "ALIGNED_BOUNDARY_TEXT_WITH_CONTINUATION_CUE"
        else:
            state, reason = "UNRESOLVED", "PARAGRAPH_CONTINUATION_NOT_EXPLICIT"
        link_id = "page-link:" + _fingerprint({"window": fingerprint, "kind": kind, "from": one.region.id, "to": two.region.id})
        links.append(DeepDocPageLink(link_id, kind, one.region.id, two.region.id, _source_candidate(one).id, _source_candidate(two).id, state, (reason,), support))
    out = Counter((link.kind, link.from_region_id) for link in links if link.state == "SUPPORTED")
    inc = Counter((link.kind, link.to_region_id) for link in links if link.state == "SUPPORTED")
    links = tuple(
        replace(link, state="UNRESOLVED", reason_codes=(*link.reason_codes, "AMBIGUOUS_BOUNDARY_NO_WINNER"))
        if link.state == "SUPPORTED" and (out[link.kind, link.from_region_id] > 1 or inc[link.kind, link.to_region_id] > 1)
        else link
        for link in links
    )
    state = "UNRESOLVED" if any(link.state == "UNRESOLVED" for link in links) else "COMPLETE"
    return DeepDocReconcileWindow(left, fingerprint, state, ("PHYSICAL_BOUNDARY_ASSESSED" if links else "NO_BOUNDARY_CANDIDATES",), links)


def reconcile_pages(parsed, *, previous=None, dirty_pages=None, policy=None):
    """Only changed adjacent windows run heuristics; canonical validation stays global."""
    if parsed.manifest is None:
        raise ValueError("reconciliation requires a source-bound PDF result")
    previous = previous if previous is not None else parsed.manifest.reconciliation
    policy = policy or (previous.policy if previous else DeepDocReconciliationPolicy())
    if previous is not None and previous.source_sha256 != parsed.manifest.source_sha256:
        raise ValueError("cross-source reconciliation cache reuse is forbidden")
    by_page, layouts, count = _reconciliation_inputs(parsed.manifest, tuple(item.extraction for item in parsed.observations))
    dirty_pages = tuple(dirty_pages) if dirty_pages is not None else None
    if dirty_pages is not None and any(type(page) is not int or page < 1 or page > count for page in dirty_pages):
        raise ValueError("dirty pages outside source scope")
    dirty = set(dirty_pages) if dirty_pages is not None else set(by_page)
    old_pages = {item.page: item for item in previous.pages} if previous and previous.policy == policy else {}
    pages = []
    for page in sorted(by_page):
        if page in old_pages and page not in dirty:
            pages.append(old_pages[page])
        else:
            pages.append(DeepDocReconcilePage(page, _reconcile_page_fingerprint(by_page[page], layouts.get(page)), _aliases(by_page[page])))
    revisions = {item.page: item.revision_sha256 for item in pages}
    excluded = {alias.region_id for page in pages for alias in page.aliases}
    old_windows = {item.left_page: item for item in previous.windows} if previous and previous.policy == policy else {}
    windows = []
    for left in sorted({left for page in by_page for left in (page - 1, page) if 1 <= left < count}):
        fingerprint = _reconcile_window_fingerprint(parsed.manifest.source_sha256, policy, left, revisions)
        old = old_windows.get(left)
        windows.append(old if old is not None and old.input_sha256 == fingerprint else _reconcile_window(left, by_page, layouts, revisions, parsed.manifest.source_sha256, policy, excluded))
    traces = {trace.region.id: trace for rows in by_page.values() for trace in rows}
    fusions, conflicts = fuse_windows(windows, traces)
    report = DeepDocReconciliationReport(parsed.manifest.source_sha256, policy, count, tuple(pages), tuple(windows), fusions, conflicts)
    return replace(parsed, manifest=replace(parsed.manifest, reconciliation=report))
