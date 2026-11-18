"""Group observed native math fragments without inventing symbols or LaTeX."""

import re
import unicodedata
from collections import defaultdict
from statistics import median

from idp.evidence.contracts import DeepDocBoundingBox, DeepDocDiagnostic, DeepDocFormula, DeepDocProducer, DeepDocSourceLocation, _region_contains
from idp.pdf.native.structures import _structure_region
from idp.pdf.native.extractors.math_geometry import verify_exceptional_geometry

_CUE = re.compile(r"[=<>≤≥≠∈∉∫∑√±×÷∞]|[A-Za-z0-9]+/[A-Za-z0-9]+|[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]")
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_OPERATORS = {"minimize", "maximize", "subject", "to", "min", "max", "sin", "cos", "tan", "log", "exp", "lim", "inf", "sup", "otherwise", "if", "for", "and", "or"}
_PROGRAM = re.compile(r"^(?:minimize|maximize|subject\s+to)\b", re.IGNORECASE)
MIN_MATH_REGIONS_PER_PAGE = 64
_NUMBER = re.compile(r"^\(\d+(?:\.\d+)*[a-z]?\)(?:\s+[A-Za-z][\w.:-]*\d[\w.:-]*)?[.,]?$", re.IGNORECASE)


def _delimiter(text):
    return bool(text.strip()) and len(text.strip()) <= 4 and not any(char.isalnum() for char in text) and any(char in "{}[]⎧⎪⎨⎩⎫⎬⎭" or unicodedata.category(char) == "Co" for char in text)


def _compact(text):
    """Grouping eligibility, distinct from broad inline-math cue detection."""
    words = _WORDS.findall(text)
    return len(text) <= 200 and all(word.lower() in _OPERATORS or (len(word) <= 3 and all(char.isascii() or "\u0370" <= char <= "\u03ff" for char in word)) for word in words)


def _groups(lines, source, policy, tables):
    by_page = defaultdict(list)
    owners = {}
    for index, line in enumerate(lines):
        if _compact(line.text) and not _NUMBER.fullmatch(line.text.strip()):
            by_page[line.location.page].append(index)
            owners[index] = None
            for table in tables:
                if _region_contains(table.trace.region.locations, (line.location,)):
                    cells = [cell for cell in table.trace.candidates[0].table.cells if _region_contains((cell.location,), (line.location,))]
                    owners[index] = (table.trace.region.id, cells[0].row, cells[0].column) if len(cells) == 1 else (table.trace.region.id, None, None)
                    break
    parent = list(range(len(lines)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def join(a, b):
        a, b = find(a), find(b)
        parent[max(a, b)] = min(a, b)

    diagnostics = []
    for page, indices in sorted(by_page.items()):
        heights = [lines[index].location.bbox.y1 - lines[index].location.bbox.y0 for index in indices]
        typical = median(value for value in heights if value > 0) if any(value > 0 for value in heights) else 10
        active = []
        comparisons = 0
        for index in sorted(indices, key=lambda key: (lines[key].location.bbox.y0, lines[key].location.bbox.x0, key)):
            source.check_deadline()
            box = lines[index].location.bbox
            active = [other for other in active if lines[other].location.bbox.y1 + typical * 3 >= box.y0]
            for other in active:
                comparisons += 1
                if comparisons > policy.max_math_pair_checks_per_page:
                    break
                if owners[index] != owners[other]:
                    continue
                old = lines[other].location.bbox
                overlap = min(box.y1, old.y1) - max(box.y0, old.y0)
                xgap = max(0, box.x0 - old.x1, old.x0 - box.x1)
                ygap = max(0, box.y0 - old.y1, old.y0 - box.y1)
                same_row = overlap >= min(box.y1 - box.y0, old.y1 - old.y0) * 0.3
                xoverlap = min(box.x1, old.x1) - max(box.x0, old.x0)
                # Vertical links require aligned spans, preserving column gutters.
                linked_delimiters = _delimiter(lines[index].text) and _delimiter(lines[other].text) and ygap <= typical * 3
                if (same_row and xgap <= lines[index].location.page_width * 0.22) or (xoverlap > 0 and (ygap <= typical * 0.9 or linked_delimiters)):
                    join(index, other)
            if comparisons > policy.max_math_pair_checks_per_page:
                diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_MATH_PAIR_LIMIT", "Math fragment comparisons exhausted the page budget; remaining fragments stay separate", metadata={"page": page}))
                break
            active.append(index)
    grouped = defaultdict(list)
    for index, line in enumerate(lines):
        # Only compact (symbol-dominated) lines may form math regions. Prose
        # that merely contains "=", "/" or "<" stays ordinary text; otherwise
        # nearly every line of a Vietnamese math textbook became a MATH
        # proposal and exhausted the shared region budget mid-document.
        if index in owners:
            grouped[find(index)].append(line)
    return tuple(grouped.values()), diagnostics


def extract_native_math(source, lines, words, observations, tables, policy):
    regions = []
    traces = {item.extraction.raw_candidate_id: item.extraction for item in observations}
    figures = [item.extraction.region for item in observations if item.kind.value == "FIGURE"]
    producer = DeepDocProducer("native-math-geometry", "3")
    lines, words, geometry_diagnostics = verify_exceptional_geometry(source, lines, words, traces, policy)
    words_by_candidate = defaultdict(list)
    for word in words:
        words_by_candidate[word.candidate_id].append(word)
    groups, diagnostics = _groups(lines, source, policy, tables)
    diagnostics.extend(geometry_diagnostics)
    # Per-page share of the document budget, so one dense page (or an early
    # chapter) cannot starve every later page of structure proposals.
    per_page = max(1, policy.max_regions // max(1, len(source.geometry)))
    per_page = max(per_page, MIN_MATH_REGIONS_PER_PAGE)
    counts, limited = defaultdict(int), set()
    for fragments in groups:
        source.check_deadline()
        if not any((_CUE.search(line.text) and any(char.isalnum() for char in line.text)) or _PROGRAM.search(line.text) for line in fragments):
            continue
        page = fragments[0].location.page
        if len(regions) + len(tables) >= policy.max_regions:
            diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_MATH_REGION_LIMIT", "Native math proposals exceeded the shared region budget; source text was preserved"))
            break
        if counts[page] >= per_page:
            if page not in limited:
                limited.add(page)
                diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_MATH_PAGE_LIMIT", "Native math proposals exceeded the page budget; source text was preserved", metadata={"page": page}))
            continue
        counts[page] += 1
        if all(_NUMBER.fullmatch(line.text.strip()) for line in fragments):
            continue
        fragments = sorted(fragments, key=lambda line: (line.location.bbox.y0, line.location.bbox.x0, line.candidate_id, line.start))
        first = fragments[0].location
        box = DeepDocBoundingBox(
            min(line.location.bbox.x0 for line in fragments),
            min(line.location.bbox.y0 for line in fragments),
            max(line.location.bbox.x1 for line in fragments),
            max(line.location.bbox.y1 for line in fragments),
        )
        location = DeepDocSourceLocation(first.page, first.page_width, first.page_height, box)
        tokens = tuple(
            word for line in fragments for word in words_by_candidate[line.candidate_id] if line.start <= word.start < word.end <= line.end and _region_contains((line.location,), (word.location,))
        )
        hints = ["NATIVE_TEXT_MATH_CUE"]
        if len(fragments) > 1:
            hints.append("GROUPED_NATIVE_FRAGMENTS")
            if max(line.location.bbox.y0 for line in fragments) - min(line.location.bbox.y0 for line in fragments) > median(line.location.bbox.y1 - line.location.bbox.y0 for line in fragments) * 0.7:
                hints.append("MULTILINE_LAYOUT")
            else:
                hints.append("PARALLEL_DISPLAY_ROW")
        text = "\n".join(line.text for line in fragments)
        if re.search(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]", text):
            hints.append("UNICODE_SUPERSCRIPT")
        if re.search(r"[₀-₉]", text):
            hints.append("UNICODE_SUBSCRIPT")
        if "/" in text:
            hints.append("SLASH_FRACTION_CUE")
        heights = [word.location.bbox.y1 - word.location.bbox.y0 for word in tokens]
        if heights and min(heights) < max(heights) * 0.8:
            hints.append("MIXED_TOKEN_HEIGHTS")
        containers = [item.trace.region for item in tables if _region_contains(item.trace.region.locations, (location,))]
        containers.extend(region for region in figures if _region_contains(region.locations, (location,)))
        source_keys = {line.candidate_id for line in fragments}
        if not containers:
            containers.extend(trace.region for key, trace in traces.items() if key in source_keys and _region_contains(trace.region.locations, (location,)))
        parent = min(containers, key=lambda region: sum((loc.bbox.x1 - loc.bbox.x0) * (loc.bbox.y1 - loc.bbox.y0) for loc in region.locations)) if containers else None
        formula = DeepDocFormula(text, source_spans=tokens, layout_hints=tuple(hints), source_lines=tuple(fragments))
        regions.append(_structure_region(source.report.source_sha256, producer, "MATH", location, formula=formula, parent=parent.id if parent else None))
    return tuple(regions), tuple(diagnostics)
