"""Native rules, cell fills and captioned alignment; text references raw Poppler spans."""

import re
from collections import defaultdict
from dataclasses import dataclass
from importlib.metadata import version
from io import BytesIO
from statistics import median

from ...source_observation import DeepDocBoundingBox, DeepDocDiagnostic, DeepDocProducer, DeepDocSourceLocation, DeepDocTable, DeepDocTableCell, _region_contains
from ..preflight import PdfAdmissionError
from ..structures import _structure_region


@dataclass(frozen=True, slots=True)
class _Grid:
    cells: tuple[tuple[float, float, float, float], ...]
    bbox: tuple[float, float, float, float]


def _snap(values, tolerance=0.5):
    groups = []
    for value in sorted(set(values)):
        if groups and value - groups[-1][0] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return {value: sum(group) / len(group) for group in groups for value in group}


def _filled_grids(page, source):
    """Cell background rectangles are physical evidence even without strokes."""
    boxes = [
        (float(rect["x0"]), float(rect["top"]), float(rect["x1"]), float(rect["bottom"]))
        for rect in page.rects
        if rect.get("fill") and 3 <= rect["bottom"] - rect["top"] <= page.height * 0.15 and rect["x1"] - rect["x0"] >= 12
    ]
    xs = _snap([value for box in boxes for value in (box[0], box[2])])
    ys = _snap([value for box in boxes for value in (box[1], box[3])])
    boxes = sorted({(xs[box[0]], ys[box[1]], xs[box[2]], ys[box[3]]) for box in boxes}, key=lambda box: (-(box[2] - box[0]) * (box[3] - box[1]), box))
    outer = []
    for box in boxes:
        if not any(old[0] <= box[0] and old[1] <= box[1] and old[2] >= box[2] and old[3] >= box[3] for old in outer):
            outer.append(box)
    parents = list(range(len(outer)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, box in enumerate(outer):
        source.check_deadline()
        for other, old in enumerate(outer[:index]):
            xoverlap = min(box[2], old[2]) - max(box[0], old[0])
            yoverlap = min(box[3], old[3]) - max(box[1], old[1])
            vertical = min(abs(box[3] - old[1]), abs(old[3] - box[1])) <= 0.75 and xoverlap >= min(box[2] - box[0], old[2] - old[0]) * 0.8
            horizontal = min(abs(box[2] - old[0]), abs(old[2] - box[0])) <= 0.75 and yoverlap >= min(box[3] - box[1], old[3] - old[1]) * 0.8
            if vertical or horizontal:
                a, b = find(index), find(other)
                parents[max(a, b)] = min(a, b)
    components = defaultdict(list)
    for index, box in enumerate(outer):
        components[find(index)].append(box)
    return tuple(
        _Grid(tuple(sorted(group)), (min(box[0] for box in group), min(box[1] for box in group), max(box[2] for box in group), max(box[3] for box in group)))
        for group in components.values()
        if len(group) >= 3
    )


def _text_grids(page, words, source):
    """Conservative captioned alignment proposals when strokes/fills are absent."""
    if not words:
        return ()
    typical = median(word.location.bbox.y1 - word.location.bbox.y0 for word in words)
    if typical <= 0:
        return ()
    rows = []
    for word in sorted(words, key=lambda item: (item.location.bbox.y0, item.location.bbox.x0)):
        box = word.location.bbox
        if rows and min(box.y1, max(item.location.bbox.y1 for item in rows[-1])) - max(box.y0, min(item.location.bbox.y0 for item in rows[-1])) >= min(box.y1 - box.y0, typical) * 0.4:
            rows[-1].append(word)
        else:
            rows.append([word])
    chunks = []
    for row in rows:
        row_chunks = []
        for word in sorted(row, key=lambda item: item.location.bbox.x0):
            if not row_chunks or word.location.bbox.x0 - row_chunks[-1][-1].location.bbox.x1 > max(14, typical * 1.6):
                row_chunks.append([])
            row_chunks[-1].append(word)
        chunks.append(row_chunks)
    grids = []
    index = 0
    while index < len(rows):
        source.check_deadline()
        cols = len(chunks[index])
        if not 2 <= cols <= 8:
            index += 1
            continue
        top = min(word.location.bbox.y0 for word in rows[index])
        caption = any(
            re.match(r"^(?:table|bảng)\s*\d", " ".join(word.text for word in sorted(rows[above], key=lambda item: item.location.bbox.x0)), re.IGNORECASE)
            and 0 <= top - max(word.location.bbox.y1 for word in rows[above]) <= typical * 3
            for above in range(max(0, index - 3), index)
        )
        if not caption:
            index += 1
            continue
        end = index + 1
        starts = [chunk[0].location.bbox.x0 for chunk in chunks[index]]
        while (
            end < len(rows)
            and len(chunks[end]) == cols
            and all(abs(chunk[0].location.bbox.x0 - start) <= max(6, typical * 0.8) for chunk, start in zip(chunks[end], starts, strict=True))
            and min(word.location.bbox.y0 for word in rows[end]) - max(word.location.bbox.y1 for word in rows[end - 1]) <= typical * 3
        ):
            end += 1
        if end - index >= 3:
            groups = chunks[index:end]
            left = min(word.location.bbox.x0 for row in rows[index:end] for word in row)
            right = max(word.location.bbox.x1 for row in rows[index:end] for word in row)
            gutters = [(max(word.location.bbox.x1 for row in groups for word in row[col]), min(word.location.bbox.x0 for row in groups for word in row[col + 1])) for col in range(cols - 1)]
            if all(b - a >= max(12, typical) for a, b in gutters):
                xs = [left - 1, *[(a + b) / 2 for a, b in gutters], right + 1]
                ys = [
                    top - 1,
                    *[(max(word.location.bbox.y1 for word in rows[row - 1]) + min(word.location.bbox.y0 for word in rows[row])) / 2 for row in range(index + 1, end)],
                    max(word.location.bbox.y1 for word in rows[end - 1]) + 1,
                ]
                xoff, yoff = float(page.bbox[0]), float(page.bbox[1])
                cells = tuple((xs[col] + xoff, ys[row] + yoff, xs[col + 1] + xoff, ys[row + 1] + yoff) for row in range(end - index) for col in range(cols))
                grids.append(_Grid(cells, (xs[0] + xoff, ys[0] + yoff, xs[-1] + xoff, ys[-1] + yoff)))
        index = end
    return tuple(grids)


def _location(box, page, source):
    # pdfplumber uses rotated MediaBox coordinates; Poppler uses visible CropBox.
    # Reject unsupported frame differences rather than shifting table cells.
    geometry = source.geometry[page.page_number]
    if abs(float(page.width) - geometry.width) > 0.01 or abs(float(page.height) - geometry.height) > 0.01:
        raise ValueError("native table backend visible frame differs from admission")
    media = source.reader.pages[page.page_number - 1].mediabox
    crop = geometry.crop_box
    if any(abs(float(a) - b) > 0.01 for a, b in zip(media, crop, strict=True)):
        raise ValueError("native table backend CropBox mapping is unavailable")
    x0, top = float(page.bbox[0]), float(page.bbox[1])
    bounds = (float(box[0]) - x0, float(box[1]) - top, float(box[2]) - x0, float(box[3]) - top)
    if min(bounds) < 0 or bounds[2] > geometry.width + 0.01 or bounds[3] > geometry.height + 0.01:
        raise ValueError("native table geometry is outside the visible page")
    return DeepDocSourceLocation(page.page_number, geometry.width, geometry.height, DeepDocBoundingBox(*bounds))


def _candidate(table, page, source, words, policy, producer, *, method="RULED"):
    if len(table.cells) > policy.max_cells_per_table:
        raise ValueError("native table exceeds the cell budget")
    boxes = sorted({tuple(float(value) for value in box) for box in table.cells}, key=lambda box: (box[1], box[0]))
    xs = sorted({value for box in boxes for value in (box[0], box[2])})
    ys = sorted({value for box in boxes for value in (box[1], box[3])})
    if len(xs) < 3 or len(ys) < 3:
        return None
    location = _location(table.bbox, page, source)
    inside = [word for word in words if _region_contains((location,), (word.location,))]
    assignments = defaultdict(list)
    unassigned = []
    locations = [_location(box, page, source) for box in boxes]
    for word in inside:
        choices = [index for index, cell in enumerate(locations) if _region_contains((cell,), (word.location,))]
        if len(choices) == 1:
            assignments[choices[0]].append(word)
        else:
            unassigned.append(word)
    # A geometry-only mesh can also be a chart or a decorative frame.
    if len(assignments) < 3:
        return None
    cells = tuple(
        DeepDocTableCell(ys.index(box[1]), xs.index(box[0]), ys.index(box[3]) - ys.index(box[1]), xs.index(box[2]) - xs.index(box[0]), locations[index], tuple(assignments[index]))
        for index, box in enumerate(boxes)
    )
    payload = DeepDocTable(len(ys) - 1, len(xs) - 1, cells, tuple(unassigned), geometry_method=method)
    return _structure_region(source.report.source_sha256, producer, "TABLE", location, table=payload)


def extract_native_tables(source, words, policy):
    records, diagnostics, inspected = [], [], []
    by_page = defaultdict(list)
    for word in words:
        by_page[word.location.page].append(word)
    if not by_page:
        return (), (), ()
    try:
        import pdfplumber

        producer = DeepDocProducer("pdfplumber-native-grid", version("pdfplumber") + "/geometry:2")
        with pdfplumber.open(BytesIO(source.data), pages=sorted(by_page)) as pdf:
            for page in pdf.pages:
                source.check_deadline()
                if len(records) >= policy.max_regions:
                    diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_TABLE_REGION_LIMIT", "Native table proposals exhausted the shared region budget; source text was preserved"))
                    break
                try:
                    _location(page.bbox, page, source)
                    if len(page.edges) > policy.max_edges_per_page:
                        raise ValueError("native table page exceeds the edge budget")
                    inspected.append(page.page_number)
                    tables = [(table, "RULED") for table in page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"})]
                    tables.extend((table, "FILLED_CELLS") for table in _filled_grids(page, source))
                    tables.extend((table, "TEXT_ALIGNMENT") for table in _text_grids(page, by_page[page.page_number], source))
                    page_records = []
                    for table, method in sorted(tables, key=lambda item: (-((item[0].bbox[2] - item[0].bbox[0]) * (item[0].bbox[3] - item[0].bbox[1])), item[1], item[0].bbox)):
                        source.check_deadline()
                        if len(records) >= policy.max_regions:
                            raise ValueError("native structure region budget exhausted")
                        try:
                            candidate = _candidate(table, page, source, by_page[page.page_number], policy, producer, method=method)
                        except PdfAdmissionError:
                            raise
                        except ValueError as exc:
                            diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_TABLE_PROPOSAL_REJECTED", str(exc), metadata={"page": page.page_number, "geometry_method": method}))
                            continue
                        if candidate is not None:
                            if any(_region_contains(old.trace.region.locations, candidate.trace.region.locations) for old in page_records):
                                continue
                            page_records.append(candidate)
                            records.append(candidate)
                except PdfAdmissionError:
                    raise
                except ValueError as exc:
                    diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_TABLE_UNRESOLVED", str(exc), metadata={"page": page.page_number}))
                finally:
                    page.close()
    except PdfAdmissionError:
        raise
    except Exception as exc:  # noqa: BLE001 - optional native geometry cannot discard source text.
        diagnostics.append(DeepDocDiagnostic("PDF_NATIVE_TABLE_UNAVAILABLE", f"{type(exc).__name__}: {exc}"[:1000]))
    return tuple(records), tuple(diagnostics), tuple(sorted(set(inspected)))
