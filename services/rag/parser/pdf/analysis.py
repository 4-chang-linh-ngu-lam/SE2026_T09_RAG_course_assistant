"""Advisory physical page facts; no OCR, lexical correction or model routing."""

from collections import defaultdict
from dataclasses import replace

from ..source_observation import DeepDocDiagnosticLevel, DeepDocExtractionSource, DeepDocObservationKind, DeepDocPageFacts, DeepDocPageReason
from .preflight import PdfSource


def attach_page_analysis(parsed, source: PdfSource, *, pages=None):
    if parsed.manifest is None:
        raise ValueError("page analysis requires a source-bound extraction manifest")
    selected = tuple(source.geometry) if pages is None else tuple(pages)
    by_page = defaultdict(list)
    for observation in parsed.observations:
        if observation.kind == DeepDocObservationKind.TEXT and observation.locations:
            by_page[observation.locations[0].page].append(observation)
    findings = defaultdict(set)
    for diagnostic in parsed.diagnostics:
        page = diagnostic.metadata.get("page")
        if type(page) is not int:
            continue
        if ("FONT" in diagnostic.code or "GLYPH" in diagnostic.code) and diagnostic.level == DeepDocDiagnosticLevel.WARNING and diagnostic.metadata.get("status") not in {"CLEAN", "VERIFIED"}:
            findings[page].add(DeepDocPageReason.FONT_MAPPING_SUSPECT)
    facts = []
    for number in selected:
        source.check_deadline()
        geometry = source.geometry[number]
        native = [item for item in by_page[number] if item.extraction_source == DeepDocExtractionSource.NATIVE or item.attributes.get("text_extraction_source") == "NATIVE"]
        char_count = sum(len(item.text or "") for item in native)
        font_count, image_count = source.resource_counts[number]
        layout = []
        verification = sorted(findings[number])
        assessed = parsed.parser_name == "poppler-pdftotext" or bool(native)
        if assessed and not char_count:
            layout.append(DeepDocPageReason.NO_NATIVE_TEXT)
        if image_count:
            layout.append(DeepDocPageReason.IMAGE_RESOURCES)
        boxes = [item.locations[0].bbox for item in native if item.locations[0].bbox is not None]
        if _column_candidate(boxes, geometry.width):
            layout.append(DeepDocPageReason.COLUMN_LAYOUT_CANDIDATE)
        if any("\ufffd" in (item.text or "") or any(ord(char) < 32 and char not in "\n\r\t" for char in (item.text or "")) for item in native):
            verification.append(DeepDocPageReason.TEXT_ENCODING_SUSPECT)
        facts.append(DeepDocPageFacts(number, geometry.width, geometry.height, geometry.rotation, char_count, len(native), font_count, image_count, assessed, tuple(layout), tuple(verification)))
    return replace(parsed, manifest=replace(parsed.manifest, admission=source.report, pages=tuple(facts)))


def _column_candidate(boxes, width):
    left = sorted((box for box in boxes if box.x1 < width * 0.48), key=lambda box: box.y0)
    right = sorted((box for box in boxes if box.x0 > width * 0.52), key=lambda box: box.y0)
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        if min(a.y1, b.y1) > max(a.y0, b.y0):
            return True
        if a.y1 <= b.y0:
            i += 1
        else:
            j += 1
    return False
