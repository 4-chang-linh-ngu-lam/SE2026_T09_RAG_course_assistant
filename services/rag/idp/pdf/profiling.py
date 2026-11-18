"""Measured native page signals. Unknown visual/hidden-layer facts stay None."""

import re
import unicodedata
from dataclasses import dataclass

from .native.result import NativeExtraction
from .native.scoping import finding_targets


@dataclass(frozen=True, slots=True)
class RegionSignal:
    bbox: tuple[float, float, float, float]
    reason: str
    target_region_id: str | None = None


@dataclass(frozen=True, slots=True)
class PageSignals:
    page: int
    width: float
    height: float
    char_count: int
    block_count: int
    text_coverage: float
    image_count: int
    image_coverage: float | None
    letter_ratio: float
    garbled_ratio: float
    repeated_noise: bool
    encoding_suspect: bool
    glyph_suspect: bool
    regions: tuple[RegionSignal, ...] = ()
    blank_confirmed: bool | None = None
    hidden_layer_suspect: bool | None = None
    math_signal: bool = False
    structure_signal: bool | None = None
    hidden_text_ratio: float | None = None


# Share of shown characters drawn in an invisible render mode (3 or 7) above
# which the whole text layer is treated as an unverified OCR layer. A few
# invisible markers on an otherwise visible page do not make it a scan.
HIDDEN_LAYER_RATIO = 0.5
_SHOW = {b"Tj", b"TJ", b"'", b'"'}


# Layout whitespace that text extractors emit between words, lines and pages
# (pdftotext separates pages with a form feed). It is Unicode category Cc, but
# it is structure, not a damaged glyph. Other C0 controls (e.g. \x00, \x1c)
# stay suspect even though ``str.isspace`` accepts some of them.
LAYOUT_WHITESPACE = frozenset(" \t\n\r\x0b\x0c")
SUSPECT_CATEGORIES = frozenset({"Co", "Cc"})
# Form XObjects nest; bound the walk so a hostile PDF cannot recurse forever.
MAX_XOBJECT_DEPTH = 8


def _ignorable(c):
    return c in LAYOUT_WHITESPACE or (
        c.isspace() and unicodedata.category(c) not in SUSPECT_CATEGORIES
    )


def suspect_char(c):
    """A replacement, private-use or control character that is not layout."""
    return not _ignorable(c) and (
        c == "�" or unicodedata.category(c) in SUSPECT_CATEGORIES
    )


def text_health(text):
    """Shared page/block text measure: ``(content_chars, suspect_count)``.

    Page profiling and block region detection must use the same predicate.
    They previously did not: the block check counted the newline of every
    multi-line native block as a damaged glyph, so clean native PDFs were
    sent to region OCR (audit IDP-001).
    """
    chars = [c for c in text or "" if not _ignorable(c)]
    return chars, sum(suspect_char(c) for c in chars)


def _shown_length(operands, operator):
    if operator == b"TJ":
        return sum(len(item) for item in (operands[0] if operands else ()) if isinstance(item, (str, bytes)))
    value = operands[-1] if operands else b""
    return len(value) if isinstance(value, (str, bytes)) else 0


def _resolve(value):
    return value.get_object() if hasattr(value, "get_object") else value


def _form_xobject(resources, name):
    try:
        xobjects = _resolve((resources or {}).get("/XObject"))
        form = _resolve((xobjects or {}).get(name))
        if form is None or form.get("/Subtype") != "/Form":
            return None
    except Exception:  # noqa: BLE001 - malformed resources are not a form.
        return None
    return form


def _count_shown(source, contents, resources, mode=0, depth=0, seen=None):
    """Characters shown, and those shown in invisible render modes (3/7).

    Form XObjects invoked with ``Do`` are walked as well: OCR tools often put
    their invisible text layer inside a form (audit IDP-017). A form inherits
    the caller's text render mode and ``Do`` restores the graphics state, so
    the caller's mode is unchanged afterwards.
    """
    seen = set() if seen is None else seen
    stack, shown, invisible = [], 0, 0
    for operands, operator in contents.operations if contents is not None else ():
        source.check_deadline()
        if operator == b"q":
            stack.append(mode)
        elif operator == b"Q" and stack:
            mode = stack.pop()
        elif operator == b"Tr":
            mode = int(operands[0])
        elif operator in _SHOW:
            length = max(1, _shown_length(operands, operator))
            shown += length
            if mode in (3, 7):
                invisible += length
        elif operator == b"Do" and operands and depth < MAX_XOBJECT_DEPTH:
            form = _form_xobject(resources, operands[0])
            if form is None or id(form) in seen:
                continue
            seen.add(id(form))
            from pypdf.errors import PyPdfError
            from pypdf.generic import ContentStream

            try:
                nested = ContentStream(form, source.reader)
                operations = nested.operations
            except (PyPdfError, ValueError, TypeError, KeyError, AttributeError, OSError):
                # pypdf raises assorted parse errors for a damaged form; an
                # unreadable form adds no measurement, never a failure. The
                # deadline check below stays outside this guard.
                continue
            inner = _count_shown(
                source,
                nested if operations is not None else None,
                _resolve(form.get("/Resources")) or resources,
                mode,
                depth + 1,
                seen,
            )
            shown += inner[0]
            invisible += inner[1]
    return shown, invisible


def _raw_text(item):
    trace = item.extraction
    if trace is None:
        return item.text or ""
    raw = next((c for c in trace.candidates if c.id == trace.raw_candidate_id), None)
    return (raw.text if raw is not None else item.text) or ""


def _scoped_suspects(native):
    """Native blocks and pages affected by unresolved glyph/font findings.

    A glyph or font finding marks only the blocks that can contain the
    affected glyph (``idp.pdf.native.scoping``); previously one finding on a
    page sent every block of that page to region OCR and review.
    """
    texts = {}
    for item in native.observations:
        texts.setdefault(item.locations[0].page, []).append(
            (item.source_id, _raw_text(item))
        )
    findings = native.text_findings
    targets = finding_targets(findings, texts)
    affected, glyph_pages = {}, set()
    for finding in findings:
        target = targets[finding.id]
        if target == frozenset():
            continue
        pages = [finding.page] if finding.page is not None else list(texts)
        for page in pages:
            if target is None:
                ids = {source_id for source_id, _ in texts.get(page, ())}
            else:
                ids = set(target)
            affected.setdefault(page, set()).update(ids)
            if "GLYPH" in finding.code or "FONT" in finding.code:
                glyph_pages.add(page)
    return affected, glyph_pages


def profile_pages(native: NativeExtraction, *, blank_confirmations=None, source=None):
    output = []
    by_page, figures_by_page = {}, {}
    for item in native.observations:
        by_page.setdefault(item.locations[0].page, []).append(item)
    for item in native.figures:
        figures_by_page.setdefault(item.locations[0].page, []).append(item)
    affected, glyph_pages = _scoped_suspects(native)
    # A block whose selected text is a proof-bound recovery (overlaid
    # negation, TeX glyph names, reviewed override) has its glyph findings
    # resolved; only characters still damaged in that text keep it suspect.
    recovered = {
        item.source_id
        for item in native.observations
        if item.extraction is not None
        and item.extraction.source_candidate_id != item.extraction.raw_candidate_id
    }
    for fact in native.pages:
        items = by_page.get(fact.page, [])
        text = "\n".join(o.text or "" for o in items)
        chars, suspect = text_health(text)
        garbled = suspect / max(1, len(chars))
        glyph = fact.page in glyph_pages
        suspects = affected.get(fact.page, set())
        regions = []
        area = 0
        for item in items:
            loc = item.locations[0]
            if loc.bbox is None:
                continue
            b = loc.bbox
            area += (b.x1 - b.x0) * (b.y1 - b.y0)
            if text_health(item.text)[1] or (
                item.source_id in suspects and item.source_id not in recovered
            ):
                regions.append(
                    RegionSignal(
                        (b.x0, b.y0, b.x1, b.y1),
                        "NATIVE_GLYPH_OR_ENCODING",
                        item.extraction.region.id,
                    )
                )
        # Glyph findings that only concern proof-recovered blocks leave the
        # page clean (otherwise a page without regions would go to review).
        glyph = glyph and bool(regions)
        figures = figures_by_page.get(fact.page, [])
        image_area = 0
        for item in figures:
            b = item.locations[0].bbox
            if b is not None:
                image_area += (b.x1 - b.x0) * (b.y1 - b.y0)
                if fact.image_resource_count:
                    regions.append(
                        RegionSignal((b.x0, b.y0, b.x1, b.y1), "IMAGE_CONTENT_UNREAD")
                    )
        hidden = ratio = None
        if source is not None and fact.native_text_char_count:
            # PDF text rendering modes 3/7 are explicitly invisible. Do not
            # infer hidden layers from low coverage or image resources alone,
            # and measure the share of invisible characters instead of letting
            # one invisible operator condemn a whole page.
            page_object = source.reader.pages[fact.page - 1]
            shown, invisible = _count_shown(
                source,
                page_object.get_contents(),
                _resolve(page_object.get("/Resources")),
            )
            if shown:
                ratio = invisible / shown
                hidden = ratio >= HIDDEN_LAYER_RATIO
        output.append(
            PageSignals(
                fact.page,
                fact.width,
                fact.height,
                fact.native_text_char_count,
                fact.native_block_count,
                min(1, area / (fact.width * fact.height)),
                fact.image_resource_count,
                min(1, image_area / (fact.width * fact.height)) if figures else None,
                sum(c.isalpha() for c in chars) / max(1, len(chars)),
                garbled,
                bool(chars) and len(re.sub(r"https?://\S+", "", text).strip()) < 5,
                # Font-mapping page facts count only while a scoped finding
                # still affects native text (a VERIFIED recovery does not).
                any(
                    reason.value != "FONT_MAPPING_SUSPECT"
                    for reason in fact.verification_reasons
                )
                or glyph
                or garbled > 0,
                glyph,
                tuple(regions),
                (blank_confirmations or {}).get(fact.page),
                hidden,
                math_signal=bool(re.search(r"[=∑∫√]", text)),
                hidden_text_ratio=ratio,
            )
        )
    return tuple(output)
