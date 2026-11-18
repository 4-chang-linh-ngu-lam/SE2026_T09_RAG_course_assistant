"""OCR-aware publication policy, separate from the immutable evidence gate.

This chooses authoritative content without deleting any L1 evidence.

``pdf-publication:3`` (default) adds, on top of ``pdf-publication:2``:

* page furniture (running header/footer, folio) is never published;
* a native page whose text an independent OCR family reproduces exactly is
  published as ``independent_agreement`` even if the page looked suspect;
* ruled/filled native table grids are published once as a table, and the
  text blocks that are only cell shards of that grid are withheld.

``pdf-publication:5`` (default) changes only OCR duplicate selection:

* on a page routed ``ocr_page`` (native text layer unusable or absent), a
  native region that is itself withheld no longer blocks the OCR reading of
  the same area, so OCR replaces a damaged hidden layer (audit IDP-004);
* two OCR readings of the same area (IoU >= 0.5) still exclude each other,
  but a partial overlap is a duplicate only when the text is similar too;
  axis-aligned boxes of a slightly skewed scan overlap without repeating
  each other (audit IDP-005).

``pdf-publication:6`` (default) keeps version 5 and:

* withholds suspect native text per region, not per page: a native block is
  ``SUSPECT_NATIVE_REQUIRES_REVIEW`` when its own region was routed as
  ``NATIVE_GLYPH_OR_ENCODING`` (or the page's text layer is hidden/noise).
  Correct prose beside one damaged TeX delimiter is no longer withheld;
* recognises folios outside the narrow folio band: a number-only block in
  the top/bottom 15% whose value follows the physical page number with one
  shared offset on at least three pages is ``PAGE_FURNITURE``;
* withholds an OCR block holding a token Tesseract itself scored below
  ``OCR_TOKEN_FLOOR`` when that token carries digits, operators or symbols
  (``Js?`` for a square root, ``=5/2.`` for a stacked fraction, ``(#®)``
  for an icon), or a single-letter variable read as ``s?`` (``s²``):
  ``OCR_TOKEN_UNVERIFIED``. Prose words with low confidence are kept;
* withholds the remaining fragments of one printed row when another
  fragment of that row is withheld for its recognition
  (``OCR_ROW_INCOMPLETE``): a data series must not be published with
  values missing as if it were complete. An OCR lead-in ending with ":"
  directly above such withheld data is ``OCR_DATA_INCOMPLETE`` (the
  question would otherwise be published without its data).

Older version semantics are kept so stored canonical v2 artifacts still
validate.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass

from .merge import box_of, overlap
from .native.evidence import evidence_family
from .ocr_tokens import suspect_ocr_tokens
from .render import digest
from .tables import publishable_tables, table_sources

POLICY_VERSIONS = (
    "pdf-publication:2",
    "pdf-publication:3",
    "pdf-publication:4",
    "pdf-publication:5",
    "pdf-publication:6",
)
CURRENT_VERSION = "pdf-publication:6"
# Two overlapping OCR readings repeat each other when their word sets agree
# this much (Jaccard), or one nearly contains the other (retry/line vs.
# paragraph readings of one area).
OCR_DUPLICATE_JACCARD = 0.5
OCR_DUPLICATE_CONTAINMENT = 0.9
OCR_DUPLICATE_MIN_WORDS = 4
OCR_SAME_AREA_IOU = 0.5
# Scanned pages have no native layout roles, so folios and running headers
# are recognised from OCR geometry/text (pdf-publication:4).
OCR_FOLIO_BAND = 0.08
OCR_RUNNING_BAND = 0.10
OCR_RUNNING_MIN_PAGES = 3
# Running headers/footers and folios are page furniture: kept in L1, never
# published as document content or retrieval text.
FURNITURE_ROLES = frozenset({"HEADER", "FOOTER", "PAGE_NUMBER"})
# Gate reasons that only concern grid topology/headers, never the cell text.
TABLE_TOPOLOGY_ONLY = frozenset(
    {"TABLE_CELLS_HEADERS_UNVERIFIED", "CAPABILITY_UNAVAILABLE"}
)
TABLE_STATUS = "NATIVE_TABLE_TOPOLOGY_UNVERIFIED"
# pdf-publication:6 folio series: number-only text in this top/bottom band
# whose value minus the physical page number repeats on this many pages.
FOLIO_SERIES_BAND = 0.15
FOLIO_SERIES_MIN_PAGES = 3
# pdf-publication:6 OCR row integrity: fragments of one printed row.
ROW_GAP_HEIGHTS = 3.0
ROW_OVERLAP = 0.5
RECOGNITION_REASONS = frozenset(
    {"OCR_LOW_CONFIDENCE", "OCR_CONFIDENCE_REVIEW", "OCR_TOKEN_UNVERIFIED"}
)


@dataclass(frozen=True, slots=True)
class PublicationPolicy:
    version: str = CURRENT_VERSION
    min_ocr_confidence: float = 0.80
    low_ocr_confidence: float = 0.60

    def __post_init__(self):
        if (
            self.version not in POLICY_VERSIONS
            or not 0 <= self.low_ocr_confidence <= self.min_ocr_confidence <= 1
        ):
            raise ValueError("invalid OCR publication policy")

    @property
    def fingerprint(self):
        return digest(asdict(self))

    @property
    def structured(self):
        return self.version != "pdf-publication:2"

    @property
    def ocr_furniture(self):
        return self.version not in {"pdf-publication:2", "pdf-publication:3"}

    @property
    def ocr_primary(self):
        """OCR may replace withheld native text on ``ocr_page`` routes, and
        OCR/OCR duplicates need similar text (``pdf-publication:5``)."""
        return self.version not in {
            "pdf-publication:2",
            "pdf-publication:3",
            "pdf-publication:4",
        }

    @property
    def scoped(self):
        """Region-level native suspicion, folio series, OCR token and row
        integrity gates (``pdf-publication:6``)."""
        return self.version == "pdf-publication:6"


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    source_id: str
    eligible: bool
    status: str
    reasons: tuple[str, ...]
    confidence: float | None


def _comparable(text):
    return "".join(unicodedata.normalize("NFC", text or "").split())


def _words(text):
    normalized = unicodedata.normalize("NFC", text or "").casefold()
    return frozenset(re.findall(r"\w+", normalized))


def similar_text(a, b):
    """True when two readings of overlapping areas repeat each other."""
    left, right = _words(a), _words(b)
    if not left or not right:
        return _comparable(a) == _comparable(b)
    common = len(left & right)
    if common / len(left | right) >= OCR_DUPLICATE_JACCARD:
        return True
    smaller = min(len(left), len(right))
    return (
        smaller >= OCR_DUPLICATE_MIN_WORDS
        and common / smaller >= OCR_DUPLICATE_CONTAINMENT
    )


def ocr_duplicate(box_a, text_a, box_b, text_b):
    """Two OCR readings that must not both be published (version 5).

    Readings of the *same area* (IoU >= 0.5) conflict or repeat whatever
    their text says. A partial overlap is a duplicate only when the text
    repeats too: on a skewed scan the axis-aligned boxes of neighbouring
    lines/paragraphs overlap while reading different words (IDP-005).
    """
    iou, coverage = overlap(box_a, box_b)
    return iou >= OCR_SAME_AREA_IOU or (
        coverage > 0.2 and similar_text(text_a, text_b)
    )


def independent_agreement(trace) -> bool:
    """True when an independent OCR reading reproduces the native source text.

    The OCR lines that the merger attached to this native region are grouped
    per acquisition artifact, joined in recognition order and compared with
    the selected native candidate after NFC and whitespace normalization.
    Agreement only promotes the *native* candidate; OCR text never replaces
    source text, and any disagreement keeps the region in review.
    """
    source = next(c for c in trace.candidates if c.id == trace.source_candidate_id)
    if source.table or source.formula or not (source.text or "").strip():
        return False
    evidence = {e.id: e for e in trace.evidence}
    native_families = {
        evidence_family(evidence[i]) for i in source.evidence_ids if i in evidence
    }
    readings = {}
    for candidate in trace.candidates:
        if not candidate.id.startswith("candidate:ocr:"):
            continue
        for ref in candidate.evidence_ids:
            item = evidence.get(ref)
            if item is None or evidence_family(item) in native_families | {"unknown"}:
                continue
            readings.setdefault(item.input_sha256, []).append(candidate.text or "")
    target = _comparable(source.text)
    return any(_comparable("".join(lines)) == target for lines in readings.values())


def _zone(obs):
    loc = obs.locations[0]
    b = loc.bbox
    if b is None:
        return None
    if b.y1 < loc.page_height * 0.15:
        return "HEADER"
    return "FOOTER" if b.y0 > loc.page_height * 0.9 else None


def _signature(obs):
    return re.sub(r"^\d+\s+|\s+\d+$", "", " ".join((obs.text or "").split()))


def furniture_sources(record):
    """Source ids of running headers/footers and folios.

    Native extraction marks repeats from page 2 on (unchanged from the Parser
    engine); the same signature in the same zone on page 1 is the first
    occurrence of that running header/footer.
    """
    found, running = set(), set()
    for obs in record.observations:
        role = obs.extraction.region.source_role
        if role in FURNITURE_ROLES:
            found.add(obs.source_id)
            if role in {"HEADER", "FOOTER"}:
                running.add((role, _signature(obs)))
    for obs in record.observations:
        if (
            obs.locations[0].page == 1
            and obs.source_id not in found
            and obs.extraction_source.value != "OCR"
            and (_zone(obs), _signature(obs)) in running
        ):
            found.add(obs.source_id)
    return found


def _ocr_band(obs, band):
    loc = obs.locations[0]
    b = loc.bbox
    if b is None:
        return None
    if b.y1 <= loc.page_height * band:
        return "top"
    return "bottom" if b.y0 >= loc.page_height * (1 - band) else None


def _ocr_signature(text):
    """Running-header identity: letters only, so a changing folio or OCR
    punctuation noise does not split one header into many signatures."""
    normalized = unicodedata.normalize("NFC", text or "").casefold()
    return "".join(c for c in normalized if c.isalpha())


def ocr_furniture_sources(record):
    """Folios and running headers/footers on OCR'd pages."""
    found, running = set(), {}
    for obs in record.observations:
        if obs.extraction_source.value != "OCR":
            continue
        text = obs.text or ""
        if _ocr_band(obs, OCR_FOLIO_BAND) and re.fullmatch(
            r"\d{1,4}", re.sub(r"[\W_]", "", text)
        ):
            found.add(obs.source_id)
            continue
        zone = _ocr_band(obs, OCR_RUNNING_BAND)
        signature = _ocr_signature(text)
        if zone and len(signature) >= 4:
            running.setdefault((zone, signature), []).append(obs)
    for items in running.values():
        if len({o.locations[0].page for o in items}) >= OCR_RUNNING_MIN_PAGES:
            found.update(o.source_id for o in items)
    return found


def folio_series_sources(record):
    """Folios recognised by their numbering, not by a narrow band alone.

    A running header often carries the folio on its own line 11-13% below the
    top edge, outside the 8-10% folio bands. A number-only text block in the
    top/bottom ``FOLIO_SERIES_BAND`` is a folio when ``value - page`` (the
    offset between printed and physical numbering) is shared by blocks on at
    least ``FOLIO_SERIES_MIN_PAGES`` pages.
    """
    candidates = []
    for obs in record.observations:
        if obs.kind.value != "TEXT":
            continue
        loc = obs.locations[0]
        b = loc.bbox
        if b is None:
            continue
        core = re.sub(r"[\W_]", "", obs.text or "")
        if not re.fullmatch(r"\d{1,4}", core):
            continue
        band = loc.page_height * FOLIO_SERIES_BAND
        if b.y1 <= band or b.y0 >= loc.page_height - band:
            candidates.append((obs.source_id, loc.page, int(core) - loc.page))
    pages = {}
    for _, page, offset in candidates:
        pages.setdefault(offset, set()).add(page)
    series = {o for o, found in pages.items() if len(found) >= FOLIO_SERIES_MIN_PAGES}
    return {source_id for source_id, _, offset in candidates if offset in series}


def _single_line(obs):
    payload = obs.attributes.get("recognition", {}).get("payload", {})
    lines = payload.get("lines")
    if lines is not None:
        return lines == 1
    return "\n" not in (obs.text or "")


def _column_path(obs):
    run = obs.attributes.get("recognition", {}).get("payload", {}).get("column_run")
    return (run["run"], tuple(run["path"])) if run else None


def ocr_rows(observations):
    """Groups of single-line OCR blocks that are fragments of one printed row.

    Two blocks are row neighbours when their vertical extents overlap by at
    least ``ROW_OVERLAP`` of the lower one and the horizontal gap between
    them is at most ``ROW_GAP_HEIGHTS`` row heights. Segments that
    ``idp.pdf.columns`` split into different columns never join.
    """
    items = [
        obs
        for obs in observations
        if obs.extraction_source.value == "OCR"
        and obs.kind.value == "TEXT"
        and obs.locations[0].bbox is not None
        and _single_line(obs)
    ]
    parent = {obs.source_id: obs.source_id for obs in items}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for i, a in enumerate(items):
        ba = a.locations[0].bbox
        for b in items[i + 1 :]:
            bb = b.locations[0].bbox
            height = min(ba.y1 - ba.y0, bb.y1 - bb.y0)
            if height <= 0:
                continue
            if min(ba.y1, bb.y1) - max(ba.y0, bb.y0) < ROW_OVERLAP * height:
                continue
            gap = max(ba.x0, bb.x0) - min(ba.x1, bb.x1)
            if gap > ROW_GAP_HEIGHTS * max(ba.y1 - ba.y0, bb.y1 - bb.y0):
                continue
            pa, pb = _column_path(a), _column_path(b)
            if pa and pb and pa[0] == pb[0] and pa[1] != pb[1]:
                continue
            parent[root(a.source_id)] = root(b.source_id)
    groups = {}
    for obs in items:
        groups.setdefault(root(obs.source_id), []).append(obs.source_id)
    return [members for members in groups.values() if len(members) > 1]


def _row_integrity(record, decisions):
    """Withhold the published fragments of a row whose other fragment was
    withheld for its recognition (``OCR_ROW_INCOMPLETE``)."""
    by_source = {d.source_id: d for d in decisions}
    by_page = {}
    for obs in record.observations:
        by_page.setdefault(obs.locations[0].page, []).append(obs)
    incomplete, lead_ins = set(), set()
    for observations in by_page.values():
        for members in ocr_rows(observations):
            if any(
                RECOGNITION_REASONS & set(by_source[key].reasons) for key in members
            ):
                incomplete.update(key for key in members if by_source[key].eligible)
        withheld = [
            obs
            for obs in observations
            if obs.source_id in by_source
            and obs.locations[0].bbox is not None
            and (
                obs.source_id in incomplete
                or RECOGNITION_REASONS & set(by_source[obs.source_id].reasons)
            )
        ]
        for obs in observations:
            decision = by_source.get(obs.source_id)
            if (
                decision is None
                or not decision.eligible
                or obs.source_id in incomplete
                or obs.extraction_source.value != "OCR"
                or not (obs.text or "").rstrip().endswith(":")
                or obs.locations[0].bbox is None
            ):
                continue
            if any(_directly_below(obs, other) for other in withheld):
                lead_ins.add(obs.source_id)
    if not incomplete and not lead_ins:
        return decisions
    return [
        PublicationDecision(
            d.source_id,
            False,
            d.status,
            (
                *d.reasons,
                "OCR_ROW_INCOMPLETE" if d.source_id in incomplete else "OCR_DATA_INCOMPLETE",
            ),
            d.confidence,
        )
        if d.source_id in incomplete or d.source_id in lead_ins
        else d
        for d in decisions
    ]


def _directly_below(lead, other):
    """``other`` starts within two line heights under ``lead`` and shares its
    horizontal extent: the data a lead-in ending with ":" introduces."""
    a, b = lead.locations[0].bbox, other.locations[0].bbox
    lines = lead.attributes.get("recognition", {}).get("payload", {}).get("lines") or 1
    line = (a.y1 - a.y0) / max(1, lines)
    return (
        0 <= b.y0 - a.y1 + 0.5 * line <= 2.5 * line
        and min(a.x1, b.x1) > max(a.x0, b.x0)
    )


def table_region_ids(decisions):
    """Source ids of tables that ``assess_publication`` decided on."""
    return frozenset(d.source_id for d in decisions if d.status == TABLE_STATUS)


def assess_publication(record, plan, policy=None):
    policy = policy or PublicationPolicy()
    modern = policy.structured
    assessments = {a.candidate_id: a for a in record.manifest.quality_gate.assessments}
    routes = {p.page: p for p in plan.pages}
    # A grid whose own gate failed beyond topology review (e.g. a verifier
    # reported a conflict) is not published, and its cells stay text blocks.
    tables = tuple(
        item
        for item in (publishable_tables(record) if modern else ())
        if assessments[item[1].id].action.value == "ACCEPT"
        or set(assessments[item[1].id].reason_codes) <= TABLE_TOPOLOGY_ONLY
    )
    shards, contributors = table_sources(record, tables) if modern else ({}, {})
    furniture = furniture_sources(record) if modern else set()
    if policy.ocr_furniture:
        furniture |= ocr_furniture_sources(record)
    if policy.scoped:
        furniture |= folio_series_sources(record)
    # Native regions routed for their own glyph/encoding damage (version 6).
    suspect_regions = {
        page.page: {
            r.target_region_id
            for r in page.signals.regions
            if r.reason == "NATIVE_GLYPH_OR_ENCODING"
        }
        for page in plan.pages
    }
    decisions = []
    # Per-page indices keep overlap checks proportional to page size instead
    # of document size (previously O(blocks^2) over the whole document).
    text_by_page, selected_by_page = {}, {}
    for obs in record.observations:
        if obs.kind.value == "TEXT":
            text_by_page.setdefault(obs.locations[0].page, []).append(obs)
    for obs in record.observations:
        trace = obs.extraction
        raw = next(c for c in trace.candidates if c.id == trace.source_candidate_id)
        assessment = assessments[raw.id]
        ocr = obs.extraction_source.value == "OCR"
        recognition = obs.attributes.get("recognition", {})
        confidence = recognition.get("confidence") if ocr else None
        page = obs.locations[0].page
        agreed = modern and not ocr and independent_agreement(trace)
        reasons = []
        if assessment.action.value != "ACCEPT":
            reasons.append("SOURCE_GATE_UNRESOLVED")
        if obs.kind.value != "TEXT":
            reasons.append("NON_TEXT_CONTEXT")
        if obs.source_id in furniture:
            reasons.append("PAGE_FURNITURE")
        if obs.source_id in shards:
            reasons.append("TABLE_CELL_FRAGMENT")
        route = routes[page]
        if route.route.value in {"review", "blank"}:
            reasons.append("PAGE_NOT_AUTHORIZED")
        if policy.scoped:
            suspect_native = (
                route.signals.hidden_layer_suspect
                or route.signals.repeated_noise
                or trace.region.id in suspect_regions[page]
            )
        else:
            suspect_native = (
                route.signals.encoding_suspect
                or route.signals.glyph_suspect
                or route.signals.hidden_layer_suspect
                or route.signals.repeated_noise
            )
        if not ocr and not agreed and suspect_native:
            reasons.append("SUSPECT_NATIVE_REQUIRES_REVIEW")
        if ocr:
            if confidence is None or confidence < policy.low_ocr_confidence:
                reasons.append("OCR_LOW_CONFIDENCE")
            elif confidence < policy.min_ocr_confidence:
                reasons.append("OCR_CONFIDENCE_REVIEW")
            if policy.scoped and suspect_ocr_tokens(
                recognition.get("payload", {}).get("words")
            ):
                reasons.append("OCR_TOKEN_UNVERIFIED")
            if obs.attributes.get("matching_review"):
                reasons.append("OCR_OVERLAP_REVIEW")
            if recognition.get("payload", {}).get("latex") or recognition.get(
                "payload", {}
            ).get("table_html"):
                reasons.append("OCR_STRUCTURE_UNVERIFIED")
            # Conservative geometry selection. Up to version 4 it ignores
            # text entirely; version 5 lets OCR stand in for withheld native
            # text on OCR-routed pages and requires similar text for OCR/OCR.
            selected = selected_by_page.get(page, set())
            ocr_page = policy.ocr_primary and route.route.value == "ocr_page"
            for other in text_by_page.get(page, ()):
                if other.source_id == obs.source_id:
                    continue
                if not (other.locations[0].bbox and obs.locations[0].bbox):
                    continue
                a, b = box_of(other.locations[0]), box_of(obs.locations[0])
                if other.extraction_source.value != "OCR":
                    duplicate = (
                        not (ocr_page and other.source_id not in selected)
                        and overlap(a, b)[1] > 0.2
                    )
                elif other.source_id not in selected:
                    duplicate = False
                elif policy.ocr_primary:
                    duplicate = ocr_duplicate(a, other.text, b, obs.text)
                else:
                    duplicate = overlap(a, b)[1] > 0.2
                if duplicate:
                    reasons.append("DUPLICATE_REGION_REVIEW")
                    break

        eligible = not reasons
        if eligible:
            selected_by_page.setdefault(page, set()).add(obs.source_id)
        status = (
            "OCR_TRANSCRIPTION_UNVERIFIED"
            if ocr
            else "NATIVE_OCR_INDEPENDENT_AGREEMENT"
            if agreed
            else "NATIVE_SOURCE_PRESERVED"
        )
        decisions.append(
            PublicationDecision(
                obs.source_id, eligible, status, tuple(reasons), confidence
            )
        )
    if policy.scoped:
        decisions = _row_integrity(record, decisions)
    # A grid inherits every blocker of the text it was built from, except the
    # shard marker itself, plus its own gate state beyond topology review.
    by_source = {d.source_id: d for d in decisions}
    for trace, candidate, _table in tables:
        reasons = set()
        for source_id in contributors.get(trace.region.id, ()):
            reasons.update(by_source[source_id].reasons)
        reasons.discard("TABLE_CELL_FRAGMENT")
        page = trace.region.locations[0].page
        if routes[page].route.value in {"review", "blank"}:
            reasons.add("PAGE_NOT_AUTHORIZED")
        if not contributors.get(trace.region.id):
            reasons.add("TABLE_WITHOUT_SOURCE_TEXT")
        reasons = tuple(sorted(reasons))
        decisions.append(
            PublicationDecision(
                trace.region.source_id, not reasons, TABLE_STATUS, reasons, None
            )
        )
    return tuple(decisions)
