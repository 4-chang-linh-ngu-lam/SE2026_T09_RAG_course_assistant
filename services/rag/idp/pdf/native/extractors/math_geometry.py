"""Independent character geometry for exceptional native font-metric boxes."""

import re
from collections import defaultdict
from dataclasses import replace
from importlib.metadata import version
from statistics import median

from idp.pdf.native.glyph.backend import PdfiumTextBackend
from idp.evidence.contracts import DeepDocBoundingBox, DeepDocDiagnostic, DeepDocGeometryCharacter, DeepDocProducer, DeepDocSourceLocation, DeepDocSpanGeometry, _region_contains
from idp.pdf.native.preflight import PdfAdmissionError


def _verified_span(span, characters, producer, source_region, *, whitespace_indices=frozenset()):
    expected = re.sub(r"\s+", "", span.text)
    if not expected:
        return None
    location = span.location
    box = location.bbox
    bounds = (box.x0 / location.page_width, box.y0 / location.page_height, box.x1 / location.page_width, box.y1 / location.page_height)
    matches = []
    for index, char in enumerate(characters):
        if char.bbox is None or not expected.startswith(char.text):
            continue
        selected = []
        value = ""
        for item in characters[index : index + len(expected)]:
            if item.bbox is None:
                break
            if selected and any(position not in whitespace_indices for position in range(selected[-1].index + 1, item.index)):
                break
            x, y = (item.bbox[0] + item.bbox[2]) / 2, (item.bbox[1] + item.bbox[3]) / 2
            if not bounds[0] - 0.002 <= x <= bounds[2] + 0.002 or not bounds[1] - 0.002 <= y <= bounds[3] + 0.002:
                break
            value += item.text
            if not expected.startswith(value):
                break
            selected.append(item)
            if value == expected:
                matches.append(selected)
                break
    if len(matches) != 1:
        return None
    chars = matches[0]
    bbox = DeepDocBoundingBox(
        min(char.bbox[0] for char in chars) * location.page_width,
        min(char.bbox[1] for char in chars) * location.page_height,
        max(char.bbox[2] for char in chars) * location.page_width,
        max(char.bbox[3] for char in chars) * location.page_height,
    )
    refined = DeepDocSourceLocation(location.page, location.page_width, location.page_height, bbox)
    if not _region_contains(source_region.locations, (refined,)):
        return None
    proof = DeepDocSpanGeometry(
        location,
        producer,
        tuple(DeepDocGeometryCharacter(char.index, char.text, DeepDocBoundingBox(*char.bbox)) for char in chars),
        tuple(sorted(index for index in whitespace_indices if chars[0].index < index < chars[-1].index)),
    )
    return replace(span, location=refined, geometry=proof)


def verify_exceptional_geometry(source, lines, words, traces, policy):
    by_page = defaultdict(list)
    for line in lines:
        by_page[line.location.page].append(line)
    replacements = {}
    word_replacements = {}
    diagnostics = []
    page_count = 0
    by_candidate = defaultdict(list)
    for word in words:
        by_candidate[word.candidate_id].append(word)
    for page, page_lines in sorted(by_page.items()):
        source.check_deadline()
        heights = [line.location.bbox.y1 - line.location.bbox.y0 for line in page_lines if line.location.bbox.y1 > line.location.bbox.y0 and any(char.isalnum() for char in line.text)]
        typical = median(heights) if heights else 10
        outliers = [
            line for line in page_lines if len(re.sub(r"\s+", "", line.text)) <= 12 and any(char.isalnum() for char in line.text) and line.location.bbox.y1 - line.location.bbox.y0 > typical * 2.5
        ]
        if not outliers:
            continue
        if page_count >= policy.max_math_geometry_pages:
            diagnostics.append(DeepDocDiagnostic("PDF_MATH_GEOMETRY_PAGE_LIMIT", "Independent math geometry exhausted its page budget; original bounds were preserved", metadata={"page": page}))
            break
        page_count += 1
        try:
            producer = DeepDocProducer("pypdfium2", version("pypdfium2"))
            raw = PdfiumTextBackend().extract_pages(source.data, (page,), source=source, include_font_names=False)[page]
            if any(char.page != page or type(char.index) is not int or char.index < 0 for char in raw) or [char.index for char in raw] != sorted({char.index for char in raw}):
                raise ValueError("secondary math geometry has a conflicting source frame")
            characters = tuple(char for char in raw if char.text and not char.text.isspace())
            whitespace = frozenset(char.index for char in raw if char.text.isspace())
            for line in outliers:
                source.check_deadline()
                refined = _verified_span(line, characters, producer, traces[line.candidate_id].region, whitespace_indices=whitespace)
                if refined is None:
                    continue
                tokens = [word for word in by_candidate[line.candidate_id] if line.start <= word.start < word.end <= line.end]
                updated = []
                for word in tokens:
                    verified = _verified_span(word, characters, producer, traces[word.candidate_id].region, whitespace_indices=whitespace)
                    if verified is None or not _region_contains((refined.location,), (verified.location,)):
                        break
                    updated.append(verified)
                else:
                    replacements[(line.candidate_id, line.start, line.end)] = refined
                    for word in updated:
                        word_replacements[(word.candidate_id, word.start, word.end)] = word
                    diagnostics.append(
                        DeepDocDiagnostic(
                            "PDF_MATH_GEOMETRY_VERIFIED",
                            "Retained native text with independently matched character geometry",
                            metadata={"page": page, "source_candidate_id": line.candidate_id, "start": line.start, "end": line.end},
                        )
                    )
        except PdfAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 - optional geometry failure preserves raw spans.
            diagnostics.append(DeepDocDiagnostic("PDF_MATH_GEOMETRY_UNAVAILABLE", f"{type(exc).__name__}: {exc}"[:1000], metadata={"page": page}))

    def key(span):
        return span.candidate_id, span.start, span.end

    return tuple(replacements.get(key(line), line) for line in lines), tuple(word_replacements.get(key(word), word) for word in words), tuple(diagnostics)
