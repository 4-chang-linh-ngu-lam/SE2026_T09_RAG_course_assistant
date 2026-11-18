"""Typed, source-near observations emitted by DeepDOC extractors.

The contract in this module intentionally contains no RAG, storage, chunking, or
indexing types.  DeepDOC reports what it observed; downstream packages decide how
to normalize and interpret those observations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, SupportsFloat

type DeepDocJsonScalar = str | int | float | bool | None
type DeepDocJsonValue = DeepDocJsonScalar | list[DeepDocJsonValue] | tuple[DeepDocJsonValue, ...] | Mapping[str, DeepDocJsonValue]


class DeepDocObservationKind(StrEnum):
    TEXT = "TEXT"
    TABLE = "TABLE"
    FIGURE = "FIGURE"


DEEPDOC_OBSERVATION_CONTRACT_VERSION = "11"
DEEPDOC_EXTRACTION_INVENTORY_VERSION = "pdf-evidence-inventory:1"
DEEPDOC_SOURCE_RETRIEVAL_POLICY_VERSION = "source-only:1"


class DeepDocContentOrigin(StrEnum):
    SOURCE_TRANSCRIPTION = "SOURCE_TRANSCRIPTION"
    STRUCTURAL_EXTRACTION = "STRUCTURAL_EXTRACTION"
    MODEL_INFERENCE = "MODEL_INFERENCE"


class DeepDocRegionLabel(StrEnum):
    TEXT = "TEXT"
    MATH = "MATH"
    TABLE = "TABLE"
    FIGURE = "FIGURE"


class DeepDocRegionRelation(StrEnum):
    CONTAINS = "CONTAINS"
    OVERLAPS = "OVERLAPS"
    CAPTION_OF = "CAPTION_OF"
    LABEL_OF = "LABEL_OF"
    PRECEDES = "PRECEDES"


class DeepDocCapability(StrEnum):
    TEXT = "TEXT"
    MATH = "MATH"
    TABLE = "TABLE"
    FIGURE = "FIGURE"


class DeepDocDecisionAction(StrEnum):
    ACCEPT = "ACCEPT"
    VERIFY = "VERIFY"
    REROUTE = "REROUTE"
    UNRESOLVED = "UNRESOLVED"


class DeepDocParseStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeepDocPageReason(StrEnum):
    NO_NATIVE_TEXT = "NO_NATIVE_TEXT"
    IMAGE_RESOURCES = "IMAGE_RESOURCES"
    COLUMN_LAYOUT_CANDIDATE = "COLUMN_LAYOUT_CANDIDATE"
    TEXT_ENCODING_SUSPECT = "TEXT_ENCODING_SUSPECT"
    FONT_MAPPING_SUSPECT = "FONT_MAPPING_SUSPECT"


class _ExtractionContract:
    __slots__ = ()
    # Pydantic consumers must reject unknown wire fields; DeepDOC itself stays
    # dependency-free and uses immutable standard-library dataclasses.
    __pydantic_config__: ClassVar[dict] = {"extra": "forbid"}


class DeepDocExtractionSource(StrEnum):
    """How DeepDOC obtained an observation.

    ``DERIVED`` is the conservative value when native-text and OCR contributions
    cannot be distinguished for one merged observation.
    """

    NATIVE = "NATIVE"
    OCR = "OCR"
    DERIVED = "DERIVED"


class DeepDocDiagnosticLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class DeepDocBoundingBox:
    """Page-local absolute coordinates with a top-left origin."""

    x0: int | float
    y0: int | float
    x1: int | float
    y1: int | float

    def __post_init__(self) -> None:
        values = tuple(_finite_number(value, "DeepDOC bounding-box coordinate") for value in (self.x0, self.y0, self.x1, self.y1))
        x0, y0, x1, y1 = values
        if x1 < x0 or y1 < y0:
            raise ValueError("DeepDOC bounding-box extents are invalid")
        object.__setattr__(self, "x0", x0)
        object.__setattr__(self, "y0", y0)
        object.__setattr__(self, "x1", x1)
        object.__setattr__(self, "y1", y1)


@dataclass(frozen=True, slots=True)
class DeepDocSourceLocation:
    page: int
    page_width: int | float
    page_height: int | float
    bbox: DeepDocBoundingBox | None = None

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("DeepDOC source pages are 1-based")
        page_width = _finite_number(self.page_width, "DeepDOC page width")
        page_height = _finite_number(self.page_height, "DeepDOC page height")
        if page_width <= 0 or page_height <= 0:
            raise ValueError("DeepDOC source page dimensions must be finite and positive")
        object.__setattr__(self, "page_width", page_width)
        object.__setattr__(self, "page_height", page_height)


@dataclass(frozen=True, slots=True)
class DeepDocProducer(_ExtractionContract):
    name: str
    version: str
    model: str | None = None
    prompt_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.name)
        _identifier(self.version)
        if self.model is not None:
            _identifier(self.model)
        if self.prompt_sha256 is not None:
            _sha256(self.prompt_sha256)


@dataclass(frozen=True, slots=True)
class DeepDocRegion(_ExtractionContract):
    id: str
    source_id: str
    labels: tuple[DeepDocRegionLabel, ...]
    locations: tuple[DeepDocSourceLocation, ...]
    source_role: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.id)
        _identifier(self.source_id)
        labels = tuple(DeepDocRegionLabel(label) for label in self.labels)
        if not labels or len(set(labels)) != len(labels):
            raise ValueError("region labels must be non-empty and unique")
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "locations", tuple(self.locations))
        if self.source_role is not None:
            _identifier(self.source_role)
            if len(self.source_role) > 128:
                raise ValueError("physical source role exceeds supported length")


@dataclass(frozen=True, slots=True)
class DeepDocGeometryCharacter(_ExtractionContract):
    index: int
    text: str
    bbox: DeepDocBoundingBox

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0 or not self.text or self.text.isspace():
            raise ValueError("geometry character requires a source index and literal non-whitespace text")
        if min(self.bbox.x0, self.bbox.y0) < 0 or max(self.bbox.x1, self.bbox.y1) > 1 or self.bbox.x1 <= self.bbox.x0 or self.bbox.y1 <= self.bbox.y0:
            raise ValueError("geometry character requires normalized character bounds")


@dataclass(frozen=True, slots=True)
class DeepDocSpanGeometry(_ExtractionContract):
    original_location: DeepDocSourceLocation
    producer: DeepDocProducer
    characters: tuple[DeepDocGeometryCharacter, ...]
    whitespace_indices: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "characters", tuple(self.characters))
        indices = [char.index for char in self.characters]
        if not indices or indices != sorted(set(indices)) or self.producer.name != "pypdfium2" or self.original_location.bbox is None:
            raise ValueError("secondary geometry requires original bounds, backend identity and ordered source characters")
        whitespace = tuple(self.whitespace_indices)
        if (
            whitespace != tuple(sorted(set(whitespace)))
            or any(type(index) is not int or not indices[0] < index < indices[-1] or index in indices for index in whitespace)
            or len(whitespace) != indices[-1] - indices[0] + 1 - len(indices)
        ):
            raise ValueError("secondary geometry cannot skip unknown source character indices")
        object.__setattr__(self, "whitespace_indices", whitespace)


@dataclass(frozen=True, slots=True)
class DeepDocSourceSpan(_ExtractionContract):
    candidate_id: str
    start: int
    end: int
    text: str
    location: DeepDocSourceLocation
    geometry: DeepDocSpanGeometry | None = None

    def __post_init__(self):
        _identifier(self.candidate_id)
        if type(self.start) is not int or type(self.end) is not int or self.start < 0 or self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("source span requires exact half-open text offsets")
        if self.location.bbox is None:
            raise ValueError("structured source span requires observed geometry")
        if self.geometry is not None:
            proof = self.geometry
            original = proof.original_location
            if (original.page, original.page_width, original.page_height) != (self.location.page, self.location.page_width, self.location.page_height) or "".join(
                char.text for char in proof.characters
            ) != re.sub(r"\s+", "", self.text):
                raise ValueError("secondary geometry must preserve exact source text and page frame")
            boxes = [char.bbox for char in proof.characters]
            union = (
                min(box.x0 for box in boxes) * self.location.page_width,
                min(box.y0 for box in boxes) * self.location.page_height,
                max(box.x1 for box in boxes) * self.location.page_width,
                max(box.y1 for box in boxes) * self.location.page_height,
            )
            if any(abs(a - b) > 0.01 for a, b in zip(union, (self.location.bbox.x0, self.location.bbox.y0, self.location.bbox.x1, self.location.bbox.y1), strict=True)):
                raise ValueError("secondary geometry must equal its observed character bounds")


@dataclass(frozen=True, slots=True)
class DeepDocTableCell(_ExtractionContract):
    row: int
    column: int
    row_span: int
    column_span: int
    location: DeepDocSourceLocation
    source_spans: tuple[DeepDocSourceSpan, ...] = ()
    header_role: str = "UNKNOWN"

    def __post_init__(self):
        if any(type(value) is not int for value in (self.row, self.column, self.row_span, self.column_span)) or min(self.row, self.column) < 0 or min(self.row_span, self.column_span) < 1:
            raise ValueError("table cell requires non-negative indices and positive spans")
        if self.location.bbox is None or self.header_role != "UNKNOWN":
            raise ValueError("native geometry alone cannot establish table header semantics")
        object.__setattr__(self, "source_spans", tuple(self.source_spans))


@dataclass(frozen=True, slots=True)
class DeepDocTable(_ExtractionContract):
    rows: int
    columns: int
    cells: tuple[DeepDocTableCell, ...]
    unassigned_source_spans: tuple[DeepDocSourceSpan, ...] = ()
    geometry_method: str = "RULED"

    def __post_init__(self):
        if type(self.rows) is not int or type(self.columns) is not int or min(self.rows, self.columns) < 2:
            raise ValueError("native grid candidate requires at least two rows and columns")
        if self.geometry_method not in {"RULED", "FILLED_CELLS", "TEXT_ALIGNMENT"}:
            raise ValueError("unsupported native table geometry method")
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(self, "unassigned_source_spans", tuple(self.unassigned_source_spans))
        occupied = []
        spans = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.rows or cell.column + cell.column_span > self.columns:
                raise ValueError("table cell is outside its grid")
            bounds = (cell.row, cell.column, cell.row + cell.row_span, cell.column + cell.column_span)
            if any(bounds[0] < other[2] and other[0] < bounds[2] and bounds[1] < other[3] and other[1] < bounds[3] for other in occupied):
                raise ValueError("table cells overlap in the logical grid")
            occupied.append(bounds)
        for span in (*tuple(span for cell in self.cells for span in cell.source_spans), *self.unassigned_source_spans):
            key = (span.candidate_id, span.start, span.end)
            if key in spans:
                raise ValueError("a table source span cannot be assigned twice")
            spans.add(key)

    @property
    def text_coverage(self) -> float | None:
        mapped = sum(len(span.text) for cell in self.cells for span in cell.source_spans)
        total = mapped + sum(len(span.text) for span in self.unassigned_source_spans)
        return mapped / total if total else None


@dataclass(frozen=True, slots=True)
class DeepDocFormula(_ExtractionContract):
    """An extraction alternative, never an implicit claim of verified math."""

    native_text: str
    latex: str | None = None
    mathml: str | None = None
    source_spans: tuple[DeepDocSourceSpan, ...] = ()
    layout_hints: tuple[str, ...] = ()
    source_lines: tuple[DeepDocSourceSpan, ...] = ()

    def __post_init__(self) -> None:
        if not self.native_text and not self.latex and not self.mathml:
            raise ValueError("formula requires at least one representation")
        object.__setattr__(self, "source_spans", tuple(self.source_spans))
        object.__setattr__(self, "layout_hints", _references(self.layout_hints))
        object.__setattr__(self, "source_lines", tuple(self.source_lines))
        if self.source_lines and "\n".join(line.text for line in self.source_lines) != self.native_text:
            raise ValueError("native formula must preserve its exact source lines")


@dataclass(frozen=True, slots=True)
class DeepDocTextEdit(_ExtractionContract):
    start: int
    end: int
    original: str
    replacement: str

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or self.start < 0 or self.end <= self.start or self.end - self.start != len(self.original) or not self.replacement:
            raise ValueError("text edits require a non-empty exact half-open source span and replacement")


@dataclass(frozen=True, slots=True)
class DeepDocReviewProof(_ExtractionContract):
    source_sha256: str
    page: int
    block: int
    original_sha256: str
    replacement_sha256: str
    note: str

    def __post_init__(self):
        for value in (self.source_sha256, self.original_sha256, self.replacement_sha256):
            _sha256(value)
        if type(self.page) is not int or type(self.block) is not int or self.page < 1 or self.block < 0 or not self.note.strip():
            raise ValueError("review proof requires a source page/block and explicit review note")


@dataclass(frozen=True, slots=True)
class DeepDocGlyphProof(_ExtractionContract):
    page: int
    font_fingerprint: str
    embedded_font_sha256: str
    equals_font_fingerprints: tuple[str, ...]
    equals_font_program_hashes: tuple[str, ...]
    glyph_bbox_normalized: tuple[float, float, float, float]
    equals_bbox_normalized: tuple[float, float, float, float]
    overlap_ratio: int | float
    glyph_name: str = "/negationslash"
    equals_character_code_glyph_name: str = "/equal"
    source_backend: str = "pypdf_content_stream_and_font_resources"
    secondary_backend: str = "pypdfium2"
    location_resolution: str = "character_bbox"
    resource_scope: str | None = None
    character_code_hex: str | None = None
    cid: int | None = None
    glyph_id: int | None = None
    source_unicode_mapping: str | None = None
    pdfium_text: str | None = None

    def __post_init__(self):
        _identifier(self.font_fingerprint)
        _sha256(self.embedded_font_sha256)
        object.__setattr__(self, "equals_font_fingerprints", _references(self.equals_font_fingerprints))
        object.__setattr__(self, "equals_font_program_hashes", tuple(self.equals_font_program_hashes))
        if not self.equals_font_fingerprints or not self.equals_font_program_hashes:
            raise ValueError("glyph proof requires separately mapped equals font evidence")
        for value in self.equals_font_program_hashes:
            _sha256(value)
        for name in ("glyph_bbox_normalized", "equals_bbox_normalized"):
            box = tuple(float(value) for value in getattr(self, name))
            if len(box) != 4 or not all(math.isfinite(value) and 0 <= value <= 1 for value in box) or box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("glyph proof requires normalized character boxes")
            object.__setattr__(self, name, box)
        if self.page < 1 or not math.isfinite(self.overlap_ratio) or not 0.5 <= self.overlap_ratio <= 1:
            raise ValueError("glyph proof requires a source page and geometry overlap")
        a, b = self.glyph_bbox_normalized, self.equals_bbox_normalized
        overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        ratio = overlap / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
        if ratio < 0.5 or abs(ratio - self.overlap_ratio) > 0.00001:
            raise ValueError("glyph proof overlap must agree with character geometry")
        if (self.source_backend, self.secondary_backend, self.glyph_name, self.equals_character_code_glyph_name, self.location_resolution) != (
            "pypdf_content_stream_and_font_resources",
            "pypdfium2",
            "/negationslash",
            "/equal",
            "character_bbox",
        ):
            raise ValueError("unsupported font glyph proof")


@dataclass(frozen=True, slots=True)
class DeepDocSecondaryTextEvidence(_ExtractionContract):
    page: int
    character_ranges: tuple[tuple[int, int], ...]
    character_sha256: str
    scope: str = "UNIQUELY_ASSIGNED_CHARACTERS"

    def __post_init__(self):
        _sha256(self.character_sha256)
        ranges = tuple(tuple(value) for value in self.character_ranges)
        previous = -1
        for start, end in ranges:
            if type(start) is not int or type(end) is not int or start < 0 or end <= start or start < previous:
                raise ValueError("secondary character ranges must be ordered and non-overlapping")
            previous = end
        if self.page < 1 or not ranges or self.scope != "UNIQUELY_ASSIGNED_CHARACTERS":
            raise ValueError("secondary evidence requires a page and assigned character ranges")
        object.__setattr__(self, "character_ranges", ranges)


@dataclass(frozen=True, slots=True)
class DeepDocEvidence(_ExtractionContract):
    id: str
    region_id: str
    origin: DeepDocContentOrigin
    producer: DeepDocProducer
    input_sha256: str
    source_sha256: str
    asset_ids: tuple[str, ...] = ()
    font_evidence_ids: tuple[str, ...] = ()
    glyph_proofs: tuple[DeepDocGlyphProof, ...] = ()
    review: DeepDocReviewProof | None = None
    secondary_text: DeepDocSecondaryTextEvidence | None = None
    independence_family: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.id)
        _identifier(self.region_id)
        _sha256(self.input_sha256)
        _sha256(self.source_sha256)
        object.__setattr__(self, "origin", DeepDocContentOrigin(self.origin))
        object.__setattr__(self, "asset_ids", _references(self.asset_ids))
        object.__setattr__(self, "font_evidence_ids", _references(self.font_evidence_ids))
        object.__setattr__(self, "glyph_proofs", tuple(self.glyph_proofs))
        if self.review is not None and self.review.source_sha256 != self.source_sha256:
            raise ValueError("review evidence must match source hash")
        if sum((bool(self.glyph_proofs), self.review is not None, self.secondary_text is not None)) > 1:
            raise ValueError("recovery and secondary observations require separate evidence records")
        if self.origin == DeepDocContentOrigin.MODEL_INFERENCE and not self.producer.model:
            raise ValueError("model evidence requires model identity")
        if self.independence_family is not None:
            _identifier(self.independence_family)


@dataclass(frozen=True, slots=True)
class DeepDocFigureReference(_ExtractionContract):
    id: str
    kind: str
    source_id: str
    text: str
    location: DeepDocSourceLocation | None = None

    def __post_init__(self):
        for value in (self.id, self.source_id, self.text):
            _identifier(value)
        if self.kind not in {"CAPTION", "LABEL", "PASSAGE"}:
            raise ValueError("unsupported figure source reference kind")


class DeepDocFigureType(StrEnum):
    PHOTO = "PHOTO"
    ILLUSTRATION = "ILLUSTRATION"
    CHART = "CHART"
    DIAGRAM = "DIAGRAM"
    DECORATIVE = "DECORATIVE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DeepDocFigureClaim(_ExtractionContract):
    text: str
    evidence_source: str
    reference_ids: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    uncertainty: str | None = None

    def __post_init__(self):
        _identifier(self.text)
        if self.evidence_source not in {"VISIBLE_CROP", "SOURCE_CONTEXT", "BOTH", "UNKNOWN"}:
            raise ValueError("figure claim requires explicit evidence source")
        object.__setattr__(self, "reference_ids", _references(self.reference_ids))
        object.__setattr__(self, "asset_ids", _references(self.asset_ids))
        if self.evidence_source in {"VISIBLE_CROP", "BOTH"} and not self.asset_ids:
            raise ValueError("visible figure claims require crop asset references")
        if self.evidence_source in {"SOURCE_CONTEXT", "BOTH"} and not self.reference_ids:
            raise ValueError("context claims require source reference ids")
        if self.uncertainty is not None:
            _identifier(self.uncertainty)
        if not self.asset_ids and not self.reference_ids and not self.uncertainty:
            raise ValueError("unsupported figure claim requires explicit uncertainty")
        if self.evidence_source == "UNKNOWN" and not self.uncertainty:
            raise ValueError("unknown figure support requires explicit uncertainty")


@dataclass(frozen=True, slots=True)
class DeepDocFigureInterpretation(_ExtractionContract):
    figure_type: DeepDocFigureType
    claims: tuple[DeepDocFigureClaim, ...]
    uncertainty: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "figure_type", DeepDocFigureType(self.figure_type))
        object.__setattr__(self, "claims", tuple(self.claims))
        if not 1 <= len(self.claims) <= 32:
            raise ValueError("figure interpretation requires 1 to 32 claims")
        if sum(len(claim.text) + len(claim.uncertainty or "") for claim in self.claims) > 16384:
            raise ValueError("figure interpretation exceeds the retained claim text budget")
        if self.uncertainty is not None:
            _identifier(self.uncertainty)


@dataclass(frozen=True, slots=True)
class DeepDocFigureInventory(_ExtractionContract):
    references: tuple[DeepDocFigureReference, ...] = ()
    figure_type: DeepDocFigureType = DeepDocFigureType.UNKNOWN
    type_reasons: tuple[str, ...] = ("VISUAL_TYPE_UNASSESSED",)
    image_sha256: str | None = None
    repeated_source_ids: tuple[str, ...] = ()
    source_retrieval_allowed: bool = True
    retrieval_reason: str = "SOURCE_CONTEXT_AVAILABLE"
    version: str = "pdf-figure:2"

    def __post_init__(self):
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "figure_type", DeepDocFigureType(self.figure_type))
        object.__setattr__(self, "type_reasons", _references(self.type_reasons))
        object.__setattr__(self, "repeated_source_ids", _references(self.repeated_source_ids))
        if len({item.id for item in self.references}) != len(self.references) or not self.type_reasons or self.version != "pdf-figure:2":
            raise ValueError("figure inventory requires unique references and explicit type evidence")
        if self.image_sha256 is not None:
            _sha256(self.image_sha256)
        if self.retrieval_reason not in {"SOURCE_CONTEXT_AVAILABLE", "NO_SOURCE_TEXT", "REPEATED_MARGINAL_ASSET"}:
            raise ValueError("unsupported figure retrieval eligibility reason")
        if self.source_retrieval_allowed != (self.retrieval_reason == "SOURCE_CONTEXT_AVAILABLE"):
            raise ValueError("figure retrieval eligibility must match its reason")
        if self.retrieval_reason == "REPEATED_MARGINAL_ASSET" and (self.figure_type != DeepDocFigureType.DECORATIVE or len(self.repeated_source_ids) < 3 or self.image_sha256 is None):
            raise ValueError("decorative exclusion requires repeated source image evidence")


@dataclass(frozen=True, slots=True)
class DeepDocCandidate(_ExtractionContract):
    id: str
    region_id: str
    origin: DeepDocContentOrigin
    producer: DeepDocProducer
    evidence_ids: tuple[str, ...]
    text: str | None = None
    formula: DeepDocFormula | None = None
    parent_candidate_id: str | None = None
    edits: tuple[DeepDocTextEdit, ...] = ()
    table: DeepDocTable | None = None
    figure: DeepDocFigureInterpretation | None = None

    def __post_init__(self) -> None:
        _identifier(self.id)
        _identifier(self.region_id)
        object.__setattr__(self, "origin", DeepDocContentOrigin(self.origin))
        object.__setattr__(self, "evidence_ids", _references(self.evidence_ids))
        object.__setattr__(self, "edits", tuple(self.edits))
        if bool(self.edits) != (self.parent_candidate_id is not None):
            raise ValueError("recovery candidate requires both parent and exact source edits")
        if not self.evidence_ids:
            raise ValueError("candidate requires evidence references")
        if self.table is not None and self.formula is not None:
            raise ValueError("table and formula require separate region candidates")
        if self.figure is not None and (
            self.origin != DeepDocContentOrigin.MODEL_INFERENCE or self.table is not None or self.formula is not None or self.text != "\n".join(claim.text for claim in self.figure.claims)
        ):
            raise ValueError("figure interpretation must be separate model inference with exact claim text")
        if self.origin == DeepDocContentOrigin.MODEL_INFERENCE and not self.producer.model:
            raise ValueError("model inference requires model identity")


@dataclass(frozen=True, slots=True)
class DeepDocDecision(_ExtractionContract):
    id: str
    candidate_id: str
    action: DeepDocDecisionAction
    reason_code: str
    policy_version: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (self.id, self.candidate_id, self.reason_code, self.policy_version):
            _identifier(value)
        object.__setattr__(self, "action", DeepDocDecisionAction(self.action))
        object.__setattr__(self, "evidence_ids", _references(self.evidence_ids))
        if not self.evidence_ids:
            raise ValueError("decision requires evidence references")


@dataclass(frozen=True, slots=True)
class DeepDocExtractionTrace(_ExtractionContract):
    """Source-bound inventory; no candidate text is implicitly retrievable."""

    region: DeepDocRegion
    evidence: tuple[DeepDocEvidence, ...]
    candidates: tuple[DeepDocCandidate, ...]
    source_candidate_id: str
    raw_candidate_id: str
    decisions: tuple[DeepDocDecision, ...] = ()
    figure: DeepDocFigureInventory | None = None

    def __post_init__(self) -> None:
        for name in ("evidence", "candidates", "decisions"):
            items = tuple(getattr(self, name))
            if len({item.id for item in items}) != len(items):
                raise ValueError(f"duplicate extraction {name} ids")
            object.__setattr__(self, name, items)
        evidence = {item.id: item for item in self.evidence}
        candidates = {item.id: item for item in self.candidates}
        if self.source_candidate_id not in candidates or candidates[self.source_candidate_id].origin == DeepDocContentOrigin.MODEL_INFERENCE:
            raise ValueError("source candidate must reference a source extraction, never model inference")
        if (
            self.raw_candidate_id not in candidates
            or candidates[self.raw_candidate_id].origin == DeepDocContentOrigin.MODEL_INFERENCE
            or candidates[self.raw_candidate_id].parent_candidate_id is not None
        ):
            raise ValueError("raw candidate must reference original source extraction")
        if any(evidence[key].glyph_proofs or evidence[key].review or evidence[key].secondary_text for key in candidates[self.raw_candidate_id].evidence_ids if key in evidence):
            raise ValueError("raw candidate cannot contain recovery or secondary evidence")
        for item in (*self.evidence, *self.candidates):
            if item.region_id != self.region.id:
                raise ValueError("extraction reference points outside its region")
        for candidate in self.candidates:
            if set(candidate.evidence_ids) - evidence.keys():
                raise ValueError("candidate references unknown evidence")
            if candidate.origin != DeepDocContentOrigin.MODEL_INFERENCE and any(evidence[key].origin == DeepDocContentOrigin.MODEL_INFERENCE for key in candidate.evidence_ids):
                raise ValueError("model evidence cannot become source transcription or structural extraction")
            if candidate.parent_candidate_id is not None:
                if candidate.parent_candidate_id != self.raw_candidate_id or candidate.origin != DeepDocContentOrigin.SOURCE_TRANSCRIPTION:
                    raise ValueError("text recovery must derive directly from raw source transcription")
                original = candidates[self.raw_candidate_id].text
                if original is None:
                    raise ValueError("text recovery requires original native text")
                value = original
                previous = len(original) + 1
                for edit in reversed(candidate.edits):
                    if edit.end > len(original) or edit.end > previous or original[edit.start : edit.end] != edit.original:
                        raise ValueError("recovery edits must match non-overlapping raw source spans")
                    value = value[: edit.start] + edit.replacement + value[edit.end :]
                    previous = edit.start
                if candidate.text != value:
                    raise ValueError("recovery candidate text must equal its exact source edits")
        for decision in self.decisions:
            if decision.candidate_id not in candidates or set(decision.evidence_ids) - evidence.keys():
                raise ValueError("decision references unknown candidate or evidence")
            if set(decision.evidence_ids) - set(candidates[decision.candidate_id].evidence_ids):
                raise ValueError("decision evidence must support its candidate")
        if len({item.source_sha256 for item in self.evidence}) > 1:
            raise ValueError("region evidence cannot mix source documents")
        if self.figure is not None:
            if DeepDocRegionLabel.FIGURE not in self.region.labels:
                raise ValueError("figure inventory requires a figure region")
            refs = {item.id for item in self.figure.references}
            assets = {key for item in self.evidence for key in item.asset_ids if item.origin != DeepDocContentOrigin.MODEL_INFERENCE}
            for candidate in self.candidates:
                if candidate.figure is not None:
                    for claim in candidate.figure.claims:
                        if set(claim.reference_ids) - refs or set(claim.asset_ids) - assets:
                            raise ValueError("figure claim references unknown source evidence")
        elif any(item.figure is not None for item in self.candidates):
            raise ValueError("figure claims require source inventory")
        if self.source_candidate_id != self.raw_candidate_id:
            selected = candidates[self.source_candidate_id]
            support = [evidence[key] for key in selected.evidence_ids]
            if selected.parent_candidate_id != self.raw_candidate_id or not any(item.glyph_proofs or item.review for item in support):
                raise ValueError("alternative backend text cannot replace raw text without recovery proof")
            if not any(
                decision.candidate_id == selected.id and decision.action == DeepDocDecisionAction.ACCEPT and decision.policy_version == "native-text-selection:1" for decision in self.decisions
            ):
                raise ValueError("selected text recovery requires an explicit selection decision")
            for item in support:
                if item.review is not None:
                    proof = item.review
                    if (
                        self.region.source_id != f"pdf:text:{proof.page}:{proof.block}"
                        or proof.original_sha256 != hashlib.sha256(candidates[self.raw_candidate_id].text.encode()).hexdigest()
                        or proof.replacement_sha256 != hashlib.sha256(selected.text.encode()).hexdigest()
                    ):
                        raise ValueError("review proof must bind exact raw and selected text")
                for proof in item.glyph_proofs:
                    if len(selected.edits) != len(item.glyph_proofs) or any(edit.replacement != "≠" or not re.fullmatch(r"6\s*=", edit.original) for edit in selected.edits):
                        raise ValueError("glyph proof only supports evidenced negation/equality edits")
                    if not any(location.page == proof.page for location in self.region.locations):
                        raise ValueError("glyph proof must match source region page")
                    for box in (proof.glyph_bbox_normalized, proof.equals_bbox_normalized):
                        if not any(
                            location.page == proof.page
                            and location.bbox is not None
                            and location.bbox.x0 / location.page_width - 0.02 <= box[0]
                            and location.bbox.y0 / location.page_height - 0.02 <= box[1]
                            and location.bbox.x1 / location.page_width + 0.02 >= box[2]
                            and location.bbox.y1 / location.page_height + 0.02 >= box[3]
                            for location in self.region.locations
                        ):
                            raise ValueError("glyph proof character geometry must belong to the source block")


@dataclass(frozen=True, slots=True)
class DeepDocGateAssessment(_ExtractionContract):
    region_id: str
    candidate_id: str
    capability: DeepDocCapability
    action: DeepDocDecisionAction
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    independence_families: tuple[str, ...] = ()
    claim_retrieval_eligible: tuple[bool, ...] = ()

    def __post_init__(self):
        _identifier(self.region_id)
        _identifier(self.candidate_id)
        object.__setattr__(self, "capability", DeepDocCapability(self.capability))
        object.__setattr__(self, "action", DeepDocDecisionAction(self.action))
        for name in ("reason_codes", "evidence_ids", "independence_families"):
            object.__setattr__(self, name, _references(getattr(self, name)))
        object.__setattr__(self, "claim_retrieval_eligible", tuple(self.claim_retrieval_eligible))
        if not self.reason_codes or not self.evidence_ids or any(type(value) is not bool or value for value in self.claim_retrieval_eligible):
            raise ValueError("gate requires evidence/reasons and source-only claim eligibility")


@dataclass(frozen=True, slots=True)
class DeepDocWorkLimits(_ExtractionContract):
    max_work: int = 32
    cpu: int = 32
    gpu: int = 0
    remote: int = 0
    verify_per_lineage: int = 1
    reroute_per_lineage: int = 1
    describe_per_lineage: int = 1
    timeout_seconds: int = 30

    def __post_init__(self):
        if any(
            type(value) is not int or value < 0
            for value in (self.max_work, self.cpu, self.gpu, self.remote, self.verify_per_lineage, self.reroute_per_lineage, self.describe_per_lineage, self.timeout_seconds)
        ):
            raise ValueError("work budgets require non-negative integer limits")


@dataclass(frozen=True, slots=True)
class DeepDocWorkRequest(_ExtractionContract):
    id: str
    source_sha256: str
    input_sha256: str
    region_id: str
    lineage_id: str
    candidate_id: str
    capability: DeepDocCapability
    operation: str
    resource: str
    producer: DeepDocProducer
    independence_family: str
    ordinal: int
    input_candidate_count: int
    input_evidence_count: int
    input_decision_count: int

    def __post_init__(self):
        for value in (self.id, self.region_id, self.lineage_id, self.candidate_id, self.independence_family):
            _identifier(value)
        _sha256(self.source_sha256)
        _sha256(self.input_sha256)
        object.__setattr__(self, "capability", DeepDocCapability(self.capability))
        if self.operation not in {"VERIFY", "REROUTE", "DESCRIBE"} or self.resource not in {"CPU", "GPU", "REMOTE"} or type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("invalid bounded PDF work request")
        if any(type(value) is not int or value < minimum for value, minimum in ((self.input_candidate_count, 1), (self.input_evidence_count, 1), (self.input_decision_count, 0))):
            raise ValueError("work requires exact input snapshot prefix counts")
        identity = {
            "source": self.source_sha256,
            "input": self.input_sha256,
            "capability": self.capability,
            "operation": self.operation,
            "producer": asdict(self.producer),
            "family": self.independence_family,
            "resource": self.resource,
            "ordinal": self.ordinal,
        }
        if self.id != "work:" + _pdf_record_fingerprint(identity):
            raise ValueError("work identity must match its input/backend/operation")


@dataclass(frozen=True, slots=True)
class DeepDocWorkRecord(_ExtractionContract):
    request: DeepDocWorkRequest
    status: str
    reason_code: str

    def __post_init__(self):
        if self.status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("work records require a terminal status")
        _identifier(self.reason_code)


@dataclass(frozen=True, slots=True)
class DeepDocGateReport(_ExtractionContract):
    source_sha256: str
    policy_sha256: str
    limits: DeepDocWorkLimits
    assessments: tuple[DeepDocGateAssessment, ...]
    work: tuple[DeepDocWorkRecord, ...] = ()
    version: str = "pdf-quality-gate:1"

    def __post_init__(self):
        _sha256(self.source_sha256)
        _sha256(self.policy_sha256)
        object.__setattr__(self, "assessments", tuple(self.assessments))
        object.__setattr__(self, "work", tuple(self.work))
        if self.version != "pdf-quality-gate:1" or len({item.candidate_id for item in self.assessments}) != len(self.assessments):
            raise ValueError("gate requires unique candidate assessments and a supported version")
        if any(item.action not in {DeepDocDecisionAction.ACCEPT, DeepDocDecisionAction.UNRESOLVED} for item in self.assessments):
            raise ValueError("synchronous gate must terminate every candidate")
        if len({item.request.id for item in self.work}) != len(self.work) or len(self.work) > self.limits.max_work:
            raise ValueError("work budget exceeded or duplicate request identity")
        for resource in ("CPU", "GPU", "REMOTE"):
            if sum(item.request.resource == resource for item in self.work) > getattr(self.limits, resource.lower()):
                raise ValueError("resource budget exceeded")
        counts = {}
        for item in self.work:
            request = item.request
            if request.source_sha256 != self.source_sha256:
                raise ValueError("work must match the report source")
            key = (request.lineage_id, request.operation)
            counts[key] = counts.get(key, 0) + 1
            if request.ordinal != counts[key] or counts[key] > getattr(self.limits, request.operation.lower() + "_per_lineage"):
                raise ValueError("lineage work budget exceeded or invalid attempt order")

    def validate_traces(self, traces, configuration_sha256):
        by_region = {trace.region.id: trace for trace in traces}
        candidates = {candidate.id: candidate for trace in traces for candidate in trace.candidates}
        if {item.candidate_id for item in self.assessments} != candidates.keys():
            raise ValueError("gate must assess every candidate exactly once")
        for item in self.assessments:
            candidate = candidates[item.candidate_id]
            trace = by_region.get(item.region_id)
            if trace is None or candidate.region_id != item.region_id or set(item.evidence_ids) != set(candidate.evidence_ids):
                raise ValueError("gate candidate/evidence references must match source trace")
            if candidate.origin == DeepDocContentOrigin.MODEL_INFERENCE and item.action == DeepDocDecisionAction.ACCEPT:
                raise ValueError("model consensus cannot establish source truth")
            capability = (
                DeepDocCapability.FIGURE
                if candidate.figure or trace.figure
                else DeepDocCapability.TABLE
                if candidate.table
                else DeepDocCapability.MATH
                if candidate.formula
                else DeepDocCapability(trace.region.labels[0].value)
            )
            if item.capability != capability:
                raise ValueError("gate capability must match candidate payload")
            if item.action == DeepDocDecisionAction.ACCEPT and (capability in {DeepDocCapability.TABLE, DeepDocCapability.MATH} or candidate.id != trace.source_candidate_id):
                raise ValueError("gate policy cannot accept unverified structure or unselected alternatives")
            if len(item.claim_retrieval_eligible) != (len(candidate.figure.claims) if candidate.figure else 0):
                raise ValueError("gate must report eligibility for every figure claim")
        for item in self.work:
            request = item.request
            trace = by_region.get(request.region_id)
            if trace is None or request.candidate_id not in {candidate.id for candidate in trace.candidates}:
                raise ValueError("work references unknown region/candidate")
            if request.lineage_id != trace.region.id:
                raise ValueError("work cannot reset its region lineage")
            if request.input_candidate_count > len(trace.candidates) or request.input_evidence_count > len(trace.evidence) or request.input_decision_count > len(trace.decisions):
                raise ValueError("work input snapshot exceeds preserved trace")
            before = replace(
                trace, candidates=trace.candidates[: request.input_candidate_count], evidence=trace.evidence[: request.input_evidence_count], decisions=trace.decisions[: request.input_decision_count]
            )
            if request.candidate_id not in {candidate.id for candidate in before.candidates} or request.input_sha256 != _work_input_fingerprint(
                before, request.candidate_id, configuration_sha256, self.policy_sha256
            ):
                raise ValueError("work fingerprint must match its exact input snapshot")


@dataclass(frozen=True, slots=True)
class DeepDocReconciliationPolicy(_ExtractionContract):
    edge_fraction: int | float = 0.18
    alignment_tolerance: int | float = 0.025
    max_boundary_regions: int = 32
    max_pair_checks: int = 256
    max_links: int = 128
    version: str = "pdf-reconcile:1"

    def __post_init__(self):
        if self.version != "pdf-reconcile:1" or not 0 < _finite_number(self.edge_fraction, "edge fraction") <= 0.25 or not 0 < _finite_number(self.alignment_tolerance, "alignment tolerance") <= 0.05:
            raise ValueError("unsupported reconciliation geometry policy")
        if any(type(value) is not int or value < 1 for value in (self.max_boundary_regions, self.max_pair_checks, self.max_links)):
            raise ValueError("reconciliation limits require positive integers")


@dataclass(frozen=True, slots=True)
class DeepDocSpanRef(_ExtractionContract):
    candidate_id: str
    start: int
    end: int
    location: DeepDocSourceLocation

    def __post_init__(self):
        _identifier(self.candidate_id)
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError("fusion source range must be a nonempty half-open interval")
        if self.location.bbox is None:
            raise ValueError("fusion reference requires an observed source anchor")


@dataclass(frozen=True, slots=True)
class DeepDocRegionAlias(_ExtractionContract):
    region_id: str
    preferred_region_id: str

    def __post_init__(self):
        _identifier(self.region_id)
        _identifier(self.preferred_region_id)
        if self.region_id == self.preferred_region_id:
            raise ValueError("region alias must reference a distinct source proposal")


@dataclass(frozen=True, slots=True)
class DeepDocReconcilePage(_ExtractionContract):
    page: int
    revision_sha256: str
    aliases: tuple[DeepDocRegionAlias, ...] = ()

    def __post_init__(self):
        if type(self.page) is not int or self.page < 1:
            raise ValueError("reconciliation requires positive source pages")
        _sha256(self.revision_sha256)
        object.__setattr__(self, "aliases", tuple(self.aliases))


@dataclass(frozen=True, slots=True)
class DeepDocPageLink(_ExtractionContract):
    id: str
    kind: str
    from_region_id: str
    to_region_id: str
    from_candidate_id: str
    to_candidate_id: str
    state: str
    reason_codes: tuple[str, ...]
    support_region_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.id, self.from_region_id, self.to_region_id, self.from_candidate_id, self.to_candidate_id):
            _identifier(value)
        if self.kind not in {"PARAGRAPH", "TABLE"} or self.state not in {"SUPPORTED", "UNRESOLVED", "BLOCKED"} or self.from_region_id == self.to_region_id:
            raise ValueError("invalid physical cross-page link")
        object.__setattr__(self, "reason_codes", _references(self.reason_codes))
        object.__setattr__(self, "support_region_ids", _references(self.support_region_ids))
        if not self.reason_codes:
            raise ValueError("physical continuation must retain evidence reasons")


@dataclass(frozen=True, slots=True)
class DeepDocReconcileWindow(_ExtractionContract):
    left_page: int
    input_sha256: str
    state: str
    reason_codes: tuple[str, ...]
    links: tuple[DeepDocPageLink, ...] = ()

    def __post_init__(self):
        if type(self.left_page) is not int or self.left_page < 1 or self.state not in {"COMPLETE", "UNRESOLVED", "BLOCKED"}:
            raise ValueError("invalid adjacent-page reconciliation window")
        _sha256(self.input_sha256)
        object.__setattr__(self, "reason_codes", _references(self.reason_codes))
        object.__setattr__(self, "links", tuple(self.links))
        if not self.reason_codes or len({item.id for item in self.links}) != len(self.links):
            raise ValueError("window requires explicit reasons and unique proposals")


@dataclass(frozen=True, slots=True)
class DeepDocFusionPart(_ExtractionContract):
    region_id: str
    candidate_id: str
    source_refs: tuple[DeepDocSpanRef, ...]

    def __post_init__(self):
        _identifier(self.region_id)
        _identifier(self.candidate_id)
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
        if not self.source_refs:
            raise ValueError("fusion requires exact preserved source ranges")


@dataclass(frozen=True, slots=True)
class DeepDocFusionGroup(_ExtractionContract):
    id: str
    kind: str
    link_ids: tuple[str, ...]
    parts: tuple[DeepDocFusionPart, ...]

    def __post_init__(self):
        _identifier(self.id)
        object.__setattr__(self, "link_ids", _references(self.link_ids))
        object.__setattr__(self, "parts", tuple(self.parts))
        if self.kind not in {"TABLE", "PARAGRAPH"} or len(self.parts) < 2 or len(self.link_ids) != len(self.parts) - 1 or len({item.region_id for item in self.parts}) != len(self.parts):
            raise ValueError("fusion group requires a non-cyclic physical continuation chain")


@dataclass(frozen=True, slots=True)
class DeepDocFusionConflict(_ExtractionContract):
    link_ids: tuple[str, ...]
    reason_code: str

    def __post_init__(self):
        object.__setattr__(self, "link_ids", _references(self.link_ids))
        _identifier(self.reason_code)
        if not self.link_ids:
            raise ValueError("fusion conflict requires exact physical links")


@dataclass(frozen=True, slots=True)
class DeepDocReconciliationReport(_ExtractionContract):
    source_sha256: str
    policy: DeepDocReconciliationPolicy
    page_count: int
    pages: tuple[DeepDocReconcilePage, ...]
    windows: tuple[DeepDocReconcileWindow, ...]
    fusions: tuple[DeepDocFusionGroup, ...] = ()
    fusion_conflicts: tuple[DeepDocFusionConflict, ...] = ()
    version: str = "pdf-reconcile:1"

    def __post_init__(self):
        _sha256(self.source_sha256)
        for name in ("pages", "windows", "fusions", "fusion_conflicts"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.version != "pdf-reconcile:1" or type(self.page_count) is not int or self.page_count < 0:
            raise ValueError("unsupported reconciliation inventory")
        pages = [item.page for item in self.pages]
        if pages != sorted(set(pages)) or any(page > self.page_count for page in pages):
            raise ValueError("reconciliation page scope is invalid")
        expected = sorted({left for page in pages for left in (page - 1, page) if 1 <= left < self.page_count})
        if [item.left_page for item in self.windows] != expected:
            raise ValueError("reconciliation must cover adjacent windows including missing neighbors")
        revisions = {item.page: item.revision_sha256 for item in self.pages}
        for window in self.windows:
            expected_hash = _reconcile_window_fingerprint(self.source_sha256, self.policy, window.left_page, revisions)
            if window.input_sha256 != expected_hash or len(window.links) > self.policy.max_links:
                raise ValueError("window input fingerprint or proposal budget is invalid")
        if len({item.id for item in self.fusions}) != len(self.fusions):
            raise ValueError("duplicate fusion group identity")


@dataclass(frozen=True, slots=True)
class DeepDocExtractionManifest(_ExtractionContract):
    source_sha256: str
    configuration_sha256: str
    producer: DeepDocProducer
    status: DeepDocParseStatus
    contract_version: str = DEEPDOC_OBSERVATION_CONTRACT_VERSION
    retrieval_policy: str = "SOURCE_ONLY"
    inventory_version: str = DEEPDOC_EXTRACTION_INVENTORY_VERSION
    policy_version: str = DEEPDOC_SOURCE_RETRIEVAL_POLICY_VERSION
    admission: DeepDocPdfAdmission | None = None
    pages: tuple[DeepDocPageFacts, ...] = ()
    region_graph: DeepDocRegionGraph | None = None
    text_extraction: DeepDocTextExtractionReport | None = None
    structures: DeepDocStructuredExtractionReport | None = None
    quality_gate: DeepDocGateReport | None = None
    reconciliation: DeepDocReconciliationReport | None = None

    def __post_init__(self) -> None:
        _sha256(self.source_sha256)
        _sha256(self.configuration_sha256)
        object.__setattr__(self, "status", DeepDocParseStatus(self.status))
        if self.contract_version != DEEPDOC_OBSERVATION_CONTRACT_VERSION:
            raise ValueError("unsupported DeepDOC observation contract")
        if self.retrieval_policy != "SOURCE_ONLY":
            raise ValueError("only source text retrieval is currently implemented")
        if self.inventory_version != DEEPDOC_EXTRACTION_INVENTORY_VERSION or self.policy_version != DEEPDOC_SOURCE_RETRIEVAL_POLICY_VERSION:
            raise ValueError("unsupported extraction inventory or retrieval policy version")
        if self.text_extraction is not None and self.text_extraction.source_sha256 != self.source_sha256:
            raise ValueError("native text report must match extraction source hash")
        if self.structures is not None and self.structures.source_sha256 != self.source_sha256:
            raise ValueError("structure candidates must match extraction source hash")
        if self.quality_gate is not None and self.quality_gate.source_sha256 != self.source_sha256:
            raise ValueError("quality gate must match extraction source hash")
        if self.reconciliation is not None and self.reconciliation.source_sha256 != self.source_sha256:
            raise ValueError("reconciliation must match extraction source hash")
        object.__setattr__(self, "pages", tuple(self.pages))
        page_numbers = [page.page for page in self.pages]
        if page_numbers != sorted(set(page_numbers)):
            raise ValueError("page facts require unique ascending source pages")
        if self.admission is not None:
            if self.admission.source_sha256 != self.source_sha256:
                raise ValueError("PDF admission must match extraction source hash")
            if any(number > self.admission.page_count for number in page_numbers):
                raise ValueError("page facts are outside admitted source pages")
            if self.region_graph is not None and any(page.page > self.admission.page_count for page in self.region_graph.pages):
                raise ValueError("region graph is outside admitted source pages")
            if self.structures is not None and (
                any(page > self.admission.page_count for page in self.structures.inspected_table_pages)
                or any(location.page > self.admission.page_count for item in self.structures.regions for location in item.trace.region.locations)
            ):
                raise ValueError("structure inventory is outside admitted source pages")
            if self.text_extraction is not None:
                report = self.text_extraction
                referenced_pages = (*report.requested_secondary_pages, *(font.page for font in report.font_evidence), *(item.page for item in report.findings if item.page is not None))
                if any(page > self.admission.page_count for page in referenced_pages):
                    raise ValueError("native text report is outside admitted source pages")

    def validate_text_traces(self, traces):
        all_traces = (*traces, *(item.trace for item in self.structures.regions)) if self.structures else traces
        for records in (all_traces, tuple(candidate for trace in all_traces for candidate in trace.candidates), tuple(item for trace in all_traces for item in trace.evidence)):
            identifiers = [item.region.id if isinstance(item, DeepDocExtractionTrace) else item.id for item in records]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("extraction region/candidate/evidence identities must be globally unique")
        _validate_figure_traces(traces)
        if self.structures is not None:
            self.structures.validate_source_traces(traces)
        if self.quality_gate is not None:
            self.quality_gate.validate_traces((*traces, *(item.trace for item in self.structures.regions)) if self.structures else traces, self.configuration_sha256)
        if self.reconciliation is not None:
            _validate_reconciliation(self, traces)
        by_source = {trace.region.source_id: trace for trace in traces}
        candidates = {candidate.id: candidate for trace in traces for candidate in trace.candidates}
        evidence = {item.id: item for trace in traces for item in trace.evidence}
        fonts = {font.id: font for font in self.text_extraction.font_evidence} if self.text_extraction is not None else {}
        for item in evidence.values():
            if set(item.font_evidence_ids) - fonts.keys():
                raise ValueError("text evidence references unknown source font evidence")
            selected_fonts = [fonts[key] for key in item.font_evidence_ids]
            for proof in item.glyph_proofs:
                if not any(font.page == proof.page and font.font_fingerprint == proof.font_fingerprint and font.embedded_font_sha256 == proof.embedded_font_sha256 for font in selected_fonts):
                    raise ValueError("glyph proof must match inspected source font identity and program hash")
                if any(
                    not any(font.page == proof.page and font.font_fingerprint == fingerprint and font.embedded_font_sha256 in proof.equals_font_program_hashes for font in selected_fonts)
                    for fingerprint in proof.equals_font_fingerprints
                ):
                    raise ValueError("glyph proof requires inspected equals font programs")
        if self.text_extraction is not None:
            for finding in self.text_extraction.findings:
                if set(finding.candidate_ids) - candidates.keys() or set(finding.evidence_ids) - evidence.keys() or set(finding.font_evidence_ids) - fonts.keys():
                    raise ValueError("glyph finding contains dangling candidate/evidence references")
                if any(fonts[key].page != finding.page for key in finding.font_evidence_ids):
                    raise ValueError("glyph finding font evidence must match its page")
                if finding.source_id is not None:
                    trace = by_source.get(finding.source_id)
                    if trace is None or finding.page not in {location.page for location in trace.region.locations}:
                        raise ValueError("glyph finding must match an exact source region")
                    if set(finding.candidate_ids) - {candidate.id for candidate in trace.candidates} or set(finding.evidence_ids) - {item.id for item in trace.evidence}:
                        raise ValueError("glyph finding references evidence outside its source region")
                    if finding.raw_character_span is not None:
                        raw = candidates[trace.raw_candidate_id]
                        if raw.text is None or finding.raw_character_span[1] > len(raw.text) or finding.candidate_ids != (raw.id,):
                            raise ValueError("glyph anomaly span must reference raw native text")


@dataclass(frozen=True, slots=True)
class DeepDocStructuredRegion(_ExtractionContract):
    trace: DeepDocExtractionTrace
    parent_region_id: str | None = None

    def __post_init__(self):
        if self.parent_region_id is not None:
            _identifier(self.parent_region_id)
        if self.trace.source_candidate_id != self.trace.raw_candidate_id:
            raise ValueError("structure inventory must preserve its raw source proposal")
        candidate = self.trace.candidates[0]
        if (candidate.table is None) == (candidate.formula is None):
            raise ValueError("structure region requires either table or formula payload")
        label = DeepDocRegionLabel.TABLE if candidate.table else DeepDocRegionLabel.MATH
        if self.trace.region.labels != (label,) or len(self.trace.region.locations) != 1:
            raise ValueError("structure payload requires a matching single-page region")
        if not self.trace.decisions or any(decision.action != DeepDocDecisionAction.UNRESOLVED for decision in self.trace.decisions):
            raise ValueError("native structure proposals remain unresolved until verified")


@dataclass(frozen=True, slots=True)
class DeepDocStructuredExtractionReport(_ExtractionContract):
    source_sha256: str
    policy_sha256: str
    regions: tuple[DeepDocStructuredRegion, ...]
    inspected_table_pages: tuple[int, ...]
    unavailable_capabilities: tuple[str, ...] = ("TABLE_TSR", "MATH_RECOGNITION")
    version: str = "pdf-native-structures:2"

    def __post_init__(self):
        _sha256(self.source_sha256)
        _sha256(self.policy_sha256)
        object.__setattr__(self, "regions", tuple(self.regions))
        if len({item.trace.region.id for item in self.regions}) != len(self.regions):
            raise ValueError("structure region identities must be unique")
        pages = tuple(self.inspected_table_pages)
        if pages != tuple(sorted(set(pages))) or any(type(page) is not int or page < 1 for page in pages):
            raise ValueError("table page coverage requires unique ascending pages")
        object.__setattr__(self, "inspected_table_pages", pages)
        object.__setattr__(self, "unavailable_capabilities", _references(self.unavailable_capabilities))
        if self.version != "pdf-native-structures:2":
            raise ValueError("unsupported native structure inventory")

    @property
    def work_requests(self) -> tuple[DeepDocCapabilityRequest, ...]:
        return tuple(
            DeepDocCapabilityRequest(
                DeepDocCapability.TABLE if item.trace.candidates[0].table is not None else DeepDocCapability.MATH, item.trace.region.id, (item.trace.region.id,), "UNVERIFIED_NATIVE_STRUCTURE"
            )
            for item in self.regions
        )

    def validate_source_traces(self, traces):
        source_regions = {trace.region.id: trace.region for trace in traces}
        source_candidates = {candidate.id: candidate for trace in traces for candidate in trace.candidates}
        raw_ids = {trace.raw_candidate_id for trace in traces}
        candidates = {item.trace.region.id: item for item in self.regions}
        if candidates.keys() & source_regions.keys():
            raise ValueError("structure proposals cannot replace source regions")
        known = {**source_regions, **{key: item.trace.region for key, item in candidates.items()}}
        edges = []
        for item in self.regions:
            trace = item.trace
            region = trace.region
            if any(evidence.source_sha256 != self.source_sha256 for evidence in trace.evidence):
                raise ValueError("structure evidence must match source hash")
            if item.parent_region_id is not None:
                parent = known.get(item.parent_region_id)
                if parent is None:
                    raise ValueError("structure parent references unknown region")
                if not _region_contains(parent.locations, region.locations):
                    raise ValueError("structure parent geometry must contain child region")
                edges.append(DeepDocRegionEdge(parent.id, region.id, DeepDocRegionRelation.CONTAINS, "NATIVE_STRUCTURE_PARENT"))
            for candidate in trace.candidates:
                _validate_structure_candidate(candidate, region, source_candidates, raw_ids, source_regions)
        _validate_region_dag(set(known), edges, DeepDocRegionRelation.CONTAINS)


def _validate_structure_candidate(candidate, region, source_candidates, raw_ids, source_regions):
    if (candidate.table is None) == (candidate.formula is None):
        raise ValueError("structure alternatives require typed table or formula payload")
    expected_label = DeepDocRegionLabel.TABLE if candidate.table else DeepDocRegionLabel.MATH
    if region.labels != (expected_label,):
        raise ValueError("structure alternatives must preserve region type")
    spans = (
        (*candidate.formula.source_spans, *candidate.formula.source_lines)
        if candidate.formula
        else tuple(span for cell in candidate.table.cells for span in cell.source_spans) + candidate.table.unassigned_source_spans
    )
    for span in spans:
        source = source_candidates.get(span.candidate_id)
        if (
            source is None
            or span.candidate_id not in raw_ids
            or source.text is None
            or source.text[span.start : span.end] != span.text
            or not _region_contains(region.locations, (span.location,))
            or not _region_contains(source_regions[source.region_id].locations, (span.location,))
            or (span.geometry is not None and not _region_contains(source_regions[source.region_id].locations, (span.geometry.original_location,)))
        ):
            raise ValueError("structure span must match exact source text and region geometry")
    if candidate.formula and (not candidate.formula.source_lines or candidate.text != candidate.formula.native_text):
        raise ValueError("native formula requires exact source line spans")
    if candidate.table:
        for cell in candidate.table.cells:
            if not _region_contains(region.locations, (cell.location,)) or any(not _region_contains((cell.location,), (span.location,)) for span in cell.source_spans):
                raise ValueError("table source spans must belong to their cell geometry")


def _validate_figure_traces(traces):
    by_source = {trace.region.source_id: trace for trace in traces}
    for trace in traces:
        inventory = trace.figure
        if inventory is None:
            continue
        selected_text = next(candidate.text for candidate in trace.candidates if candidate.id == trace.source_candidate_id)
        has_source_text = bool(selected_text and selected_text.strip())
        if inventory.retrieval_reason == "NO_SOURCE_TEXT" and has_source_text or inventory.retrieval_reason == "SOURCE_CONTEXT_AVAILABLE" and not has_source_text:
            raise ValueError("figure retrieval reason must match preserved source text")
        for reference in inventory.references:
            source = by_source.get(reference.source_id)
            if source is None:
                raise ValueError("figure reference points to an unknown source observation")
            texts = [candidate.text for candidate in source.candidates if candidate.id in {source.raw_candidate_id, source.source_candidate_id} and candidate.text]
            if not any(" ".join(reference.text.split()) in " ".join(text.split()) for text in texts):
                raise ValueError("figure reference must preserve observed source text")
            if reference.location is not None and not _region_contains(source.region.locations, (reference.location,)):
                raise ValueError("figure reference location must belong to its source region")
        if inventory.retrieval_reason == "REPEATED_MARGINAL_ASSET":
            if trace.region.source_id not in inventory.repeated_source_ids:
                raise ValueError("repeated figure exclusion must include its own source identity")
            locations = []
            for key in inventory.repeated_source_ids:
                other = by_source.get(key)
                if (
                    other is None
                    or other.figure is None
                    or other.figure.image_sha256 != inventory.image_sha256
                    or any(ref.kind in {"CAPTION", "LABEL"} for ref in other.figure.references)
                    or len(other.region.locations) != 1
                ):
                    raise ValueError("decorative exclusion requires matching uncaptained source images")
                loc = other.region.locations[0]
                box = loc.bbox
                if box is None or (box.x1 - box.x0) * (box.y1 - box.y0) > loc.page_width * loc.page_height * 0.025 or not (box.y1 <= loc.page_height * 0.17 or box.y0 >= loc.page_height * 0.83):
                    raise ValueError("decorative exclusion requires small marginal source images")
                locations.append(loc)
            if len({loc.page for loc in locations}) < 3:
                raise ValueError("decorative exclusion requires at least three source pages")
            normalized = [(loc.bbox.x0 / loc.page_width, loc.bbox.y0 / loc.page_height, loc.bbox.x1 / loc.page_width, loc.bbox.y1 / loc.page_height) for loc in locations]
            if any(any(abs(a - b) > 0.02 for a, b in zip(normalized[0], box, strict=True)) for box in normalized[1:]):
                raise ValueError("decorative exclusion requires consistent marginal placement")


def _region_contains(parents, children):
    return bool(children) and all(
        any(
            parent.page == child.page
            and parent.page_width == child.page_width
            and parent.page_height == child.page_height
            and parent.bbox is not None
            and child.bbox is not None
            and parent.bbox.x0 - 0.01 <= child.bbox.x0
            and parent.bbox.y0 - 0.01 <= child.bbox.y0
            and parent.bbox.x1 + 0.01 >= child.bbox.x1
            and parent.bbox.y1 + 0.01 >= child.bbox.y1
            for parent in parents
        )
        for child in children
    )


@dataclass(frozen=True, slots=True)
class DeepDocFontEvidence(_ExtractionContract):
    id: str
    page: int
    resource_name: str
    resource_scope: str
    font_fingerprint: str
    embedded_font_sha256: str | None
    encoding_sha256: str
    to_unicode_sha256: str | None
    encoding_status: str
    to_unicode_status: str
    base_font: str | None = None

    def __post_init__(self):
        for value in (self.id, self.resource_name, self.resource_scope, self.font_fingerprint, self.encoding_status, self.to_unicode_status):
            _identifier(value)
        for value in (self.embedded_font_sha256, self.to_unicode_sha256, self.encoding_sha256):
            if value is not None:
                _sha256(value)
        if self.page < 1:
            raise ValueError("font evidence requires a source page")


@dataclass(frozen=True, slots=True)
class DeepDocGlyphFinding(_ExtractionContract):
    id: str
    code: str
    status: str
    scope: str
    reason: str
    page: int | None = None
    source_id: str | None = None
    candidate_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    font_evidence_ids: tuple[str, ...] = ()
    glyph_name: str | None = None
    character_code_hex: str | None = None
    unicode_mapping: str | None = None
    raw_extracted_text: str | None = None
    secondary_text: str | None = None
    resource_scope: str | None = None
    operator_index: int | None = None
    string_index: int | None = None
    code_index: int | None = None
    cid: int | None = None
    cid_status: str | None = None
    glyph_id: int | None = None
    glyph_id_status: str | None = None
    bbox_normalized: tuple[float, float, float, float] | None = None
    raw_character_span: tuple[int, int] | None = None
    unicode_codepoint: str | None = None
    location_resolution: str | None = None

    def __post_init__(self):
        for value in (self.id, self.code, self.reason):
            _identifier(value)
        if self.status not in {"CLEAN", "SUSPECT", "CONFLICT", "VERIFIED"} or self.scope not in {"DOCUMENT", "PAGE", "FONT_RESOURCE", "REGION"}:
            raise ValueError("glyph findings require explicit status and evidence scope")
        for name in ("candidate_ids", "evidence_ids", "font_evidence_ids"):
            object.__setattr__(self, name, _references(getattr(self, name)))
        if self.scope != "DOCUMENT" and (self.page is None or self.page < 1):
            raise ValueError("scoped glyph finding requires a source page")
        if self.scope == "REGION" and (not self.source_id or not self.candidate_ids or not self.evidence_ids):
            raise ValueError("region glyph finding requires exact source/candidate/evidence links")
        if self.scope == "FONT_RESOURCE" and not self.font_evidence_ids:
            raise ValueError("font glyph finding requires inspected font evidence")
        for value in (self.operator_index, self.string_index, self.code_index, self.cid, self.glyph_id):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("glyph code positions and identities must be non-negative integers")
        if self.raw_character_span is not None:
            start, end = self.raw_character_span
            if self.scope != "REGION" or type(start) is not int or type(end) is not int or start < 0 or end <= start:
                raise ValueError("native text anomaly span requires an exact source region")
            object.__setattr__(self, "raw_character_span", (start, end))
        if self.bbox_normalized is not None:
            box = tuple(float(value) for value in self.bbox_normalized)
            if len(box) != 4 or not all(math.isfinite(value) and 0 <= value <= 1 for value in box) or box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("glyph finding requires normalized character geometry")
            object.__setattr__(self, "bbox_normalized", box)


@dataclass(frozen=True, slots=True)
class DeepDocTextExtractionReport(_ExtractionContract):
    source_sha256: str
    native_producer: DeepDocProducer
    font_producer: DeepDocProducer
    secondary_producer: DeepDocProducer | None
    font_evidence: tuple[DeepDocFontEvidence, ...]
    findings: tuple[DeepDocGlyphFinding, ...]
    requested_secondary_pages: tuple[int, ...] = ()
    extracted_secondary_pages: tuple[int, ...] = ()
    version: str = "pdf-native-text:1"
    selection_policy_version: str = "native-text-selection:1"

    def __post_init__(self):
        _sha256(self.source_sha256)
        for name in ("font_evidence", "findings"):
            items = tuple(getattr(self, name))
            if len({item.id for item in items}) != len(items):
                raise ValueError("native text report records must have unique evidence ids")
            object.__setattr__(self, name, items)
        for name in ("requested_secondary_pages", "extracted_secondary_pages"):
            pages = tuple(getattr(self, name))
            if pages != tuple(sorted(set(pages))) or any(type(page) is not int or page < 1 for page in pages):
                raise ValueError("secondary pages must be unique ascending source pages")
            object.__setattr__(self, name, pages)
        if set(self.extracted_secondary_pages) - set(self.requested_secondary_pages):
            raise ValueError("secondary extraction must stay within requested pages")
        if self.requested_secondary_pages and self.secondary_producer is None:
            raise ValueError("secondary verification requires backend identity")
        if self.version != "pdf-native-text:1" or self.selection_policy_version != "native-text-selection:1":
            raise ValueError("unsupported native text report policy")


@dataclass(frozen=True, slots=True)
class DeepDocPdfAdmission(_ExtractionContract):
    source_sha256: str
    source_byte_size: int
    page_count: int
    object_count: int
    policy_version: str
    policy_sha256: str

    def __post_init__(self):
        _sha256(self.source_sha256)
        _sha256(self.policy_sha256)
        _identifier(self.policy_version)
        if any(type(value) is not int or value < 1 for value in (self.source_byte_size, self.page_count, self.object_count)):
            raise ValueError("PDF admission counts must be positive integers")


@dataclass(frozen=True, slots=True)
class DeepDocPageFacts(_ExtractionContract):
    page: int
    width: float
    height: float
    rotation: int
    native_text_char_count: int
    native_block_count: int
    font_resource_count: int
    image_resource_count: int
    native_text_assessed: bool = True
    layout_reasons: tuple[DeepDocPageReason, ...] = ()
    verification_reasons: tuple[DeepDocPageReason, ...] = ()
    analysis_version: str = "pdf-page-analysis:1"

    def __post_init__(self):
        if type(self.page) is not int or self.page < 1 or self.rotation not in (0, 90, 180, 270):
            raise ValueError("page facts require a 1-based page and display rotation")
        for name in ("width", "height"):
            value = _finite_number(getattr(self, name), name)
            if value <= 0:
                raise ValueError("page dimensions must be positive")
            object.__setattr__(self, name, value)
        for name in ("native_text_char_count", "native_block_count", "font_resource_count", "image_resource_count"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError("page fact counts must be non-negative integers")
        if not self.native_text_assessed and (self.native_text_char_count or self.native_block_count):
            raise ValueError("unassessed native text must not carry measured native counts")
        if self.analysis_version != "pdf-page-analysis:1":
            raise ValueError("unsupported PDF page analysis version")
        for name in ("layout_reasons", "verification_reasons"):
            values = tuple(DeepDocPageReason(value) for value in getattr(self, name))
            if len(values) != len(set(values)):
                raise ValueError("page reasons must be unique")
            object.__setattr__(self, name, values)


@dataclass(frozen=True, slots=True)
class DeepDocLayoutNode(_ExtractionContract):
    region_id: str
    source_id: str
    source_order: int
    column: int | None = None

    def __post_init__(self):
        _identifier(self.region_id)
        _identifier(self.source_id)
        if type(self.source_order) is not int or self.source_order < 0:
            raise ValueError("layout source order must be a non-negative integer")
        if self.column is not None and (type(self.column) is not int or self.column < 0):
            raise ValueError("layout column must be non-negative or unknown")


@dataclass(frozen=True, slots=True)
class DeepDocRegionEdge(_ExtractionContract):
    from_region_id: str
    to_region_id: str
    relation: DeepDocRegionRelation
    reason: str

    def __post_init__(self):
        for value in (self.from_region_id, self.to_region_id, self.reason):
            _identifier(value)
        object.__setattr__(self, "relation", DeepDocRegionRelation(self.relation))
        if self.from_region_id == self.to_region_id:
            raise ValueError("region edge cannot reference itself")


@dataclass(frozen=True, slots=True)
class DeepDocCapabilityRequest(_ExtractionContract):
    capability: DeepDocCapability
    target_region_id: str
    evidence_region_ids: tuple[str, ...]
    reason: str

    def __post_init__(self):
        object.__setattr__(self, "capability", DeepDocCapability(self.capability))
        _identifier(self.target_region_id)
        object.__setattr__(self, "evidence_region_ids", _references(self.evidence_region_ids))
        _identifier(self.reason)
        if not self.evidence_region_ids:
            raise ValueError("capability request requires source region evidence")


@dataclass(frozen=True, slots=True)
class DeepDocRegionRoute(_ExtractionContract):
    region_id: str
    labels: tuple[DeepDocRegionLabel, ...]
    requests: tuple[DeepDocCapabilityRequest, ...]

    def __post_init__(self):
        _identifier(self.region_id)
        labels = tuple(DeepDocRegionLabel(label) for label in self.labels)
        requests = tuple(self.requests)
        if not labels or len(labels) != len(set(labels)):
            raise ValueError("route labels must be non-empty and unique")
        if {item.capability.value for item in requests} != {label.value for label in labels} or len(requests) != len(labels):
            raise ValueError("region route requires exactly one request per label")
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "requests", requests)


@dataclass(frozen=True, slots=True)
class DeepDocPageLayout(_ExtractionContract):
    page: int
    column_count: int
    method: str
    learned_layout_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.page) is not int or self.page < 1 or type(self.column_count) is not int or self.column_count < 1:
            raise ValueError("page layout requires positive page and column count")
        if self.method not in {"NATIVE_GEOMETRY", "OBSERVED_LAYOUT"}:
            raise ValueError("unsupported page layout method")
        object.__setattr__(self, "learned_layout_reasons", _references(self.learned_layout_reasons))


@dataclass(frozen=True, slots=True)
class DeepDocRegionGraph(_ExtractionContract):
    nodes: tuple[DeepDocLayoutNode, ...]
    edges: tuple[DeepDocRegionEdge, ...]
    reading_order: tuple[str, ...]
    routes: tuple[DeepDocRegionRoute, ...]
    pages: tuple[DeepDocPageLayout, ...]
    policy_sha256: str
    version: str = "pdf-layout-graph:1"
    complete: bool = True

    def __post_init__(self):
        _sha256(self.policy_sha256)
        if self.version != "pdf-layout-graph:1":
            raise ValueError("unsupported PDF region graph version")
        for name in ("nodes", "edges", "routes", "pages"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        known = {node.region_id for node in self.nodes}
        if len(known) != len(self.nodes) or len({node.source_id for node in self.nodes}) != len(self.nodes) or len({node.source_order for node in self.nodes}) != len(self.nodes):
            raise ValueError("layout nodes require unique region/source/order identities")
        reading_order = _references(self.reading_order)
        if set(reading_order) != known:
            raise ValueError("layout reading order must cover every region exactly once")
        object.__setattr__(self, "reading_order", reading_order)
        edge_keys = {(item.relation, item.from_region_id, item.to_region_id) for item in self.edges}
        if len(edge_keys) != len(self.edges):
            raise ValueError("duplicate region graph edges")
        for edge in self.edges:
            if {edge.from_region_id, edge.to_region_id} - known:
                raise ValueError("region graph edge references unknown regions")
        for relation in (DeepDocRegionRelation.CONTAINS, DeepDocRegionRelation.PRECEDES):
            _validate_region_dag(known, self.edges, relation)
        positions = {key: index for index, key in enumerate(reading_order)}
        if any(positions[edge.from_region_id] >= positions[edge.to_region_id] for edge in self.edges if edge.relation == DeepDocRegionRelation.PRECEDES):
            raise ValueError("precedence edges disagree with reading order")
        if len(self.routes) != len(known) or {route.region_id for route in self.routes} != known:
            raise ValueError("routing must cover every region exactly once")
        for route in self.routes:
            for request in route.requests:
                if request.target_region_id not in known or set(request.evidence_region_ids) - known:
                    raise ValueError("capability request references unknown evidence regions")
        work = {}
        for route in self.routes:
            for request in route.requests:
                key = (request.target_region_id, request.capability)
                if key in work and work[key] != request:
                    raise ValueError("conflicting capability requests for the same source region")
                work[key] = request
        pages = [page.page for page in self.pages]
        if pages != sorted(set(pages)):
            raise ValueError("layout pages must be unique and ascending")

    @property
    def work_requests(self) -> tuple[DeepDocCapabilityRequest, ...]:
        work = {(request.target_region_id, request.capability): request for route in self.routes for request in route.requests}
        return tuple(work[key] for key in sorted(work))


def _validate_region_dag(known, edges, relation):
    children = {key: [] for key in known}
    indegree = dict.fromkeys(known, 0)
    for edge in edges:
        if edge.relation == relation:
            children[edge.from_region_id].append(edge.to_region_id)
            indegree[edge.to_region_id] += 1
    pending = deque(key for key, count in indegree.items() if not count)
    visited = 0
    while pending:
        key = pending.popleft()
        visited += 1
        for child in children[key]:
            indegree[child] -= 1
            if not indegree[child]:
                pending.append(child)
    if visited != len(known):
        raise ValueError(f"{relation.value} region graph must be acyclic")


@dataclass(frozen=True, slots=True)
class DeepDocStyle:
    font_name: str | None = None
    font_size: int | float | None = None
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None
    alignment: str | None = None
    indentation: int | float | None = None
    attributes: Mapping[str, DeepDocJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.font_size is not None:
            font_size = _finite_number(self.font_size, "DeepDOC font size")
            if font_size <= 0:
                raise ValueError("DeepDOC font size must be finite and positive")
            object.__setattr__(self, "font_size", font_size)
        if self.indentation is not None:
            object.__setattr__(self, "indentation", _finite_number(self.indentation, "DeepDOC indentation"))
        object.__setattr__(self, "attributes", _freeze_json_object(self.attributes))


@dataclass(frozen=True, slots=True)
class DeepDocObservation:
    source_id: str
    order: int
    kind: DeepDocObservationKind
    text: str | None
    extraction_source: DeepDocExtractionSource = DeepDocExtractionSource.DERIVED
    type_hint: str | None = None
    layout_type: str | None = None
    locations: tuple[DeepDocSourceLocation, ...] = ()
    style: DeepDocStyle | None = None
    attributes: Mapping[str, DeepDocJsonValue] = field(default_factory=dict)
    extraction: DeepDocExtractionTrace | None = None
    source_order: int | None = None

    def __post_init__(self) -> None:
        if not self.source_id or self.source_id.strip() != self.source_id:
            raise ValueError("DeepDOC observation source_id must be trimmed and non-blank")
        if len(self.source_id) > 4096:
            raise ValueError("DeepDOC observation source_id must not exceed 4096 characters")
        if self.order < 0:
            raise ValueError("DeepDOC observation order must be non-negative")
        if self.source_order is not None and (type(self.source_order) is not int or self.source_order < 0):
            raise ValueError("DeepDOC source_order must be a non-negative integer")
        if self.type_hint is not None and self.type_hint.strip() != self.type_hint:
            raise ValueError("DeepDOC observation type_hint must be trimmed")
        if self.type_hint is not None and len(self.type_hint) > 128:
            raise ValueError("DeepDOC observation type_hint must not exceed 128 characters")
        if self.layout_type is not None and self.layout_type.strip() != self.layout_type:
            raise ValueError("DeepDOC observation layout_type must be trimmed")
        object.__setattr__(self, "locations", tuple(self.locations))
        object.__setattr__(self, "attributes", _freeze_json_object(self.attributes))
        if self.extraction is not None:
            if self.extraction.region.source_id != self.source_id or self.extraction.region.locations != self.locations:
                raise ValueError("extraction region must preserve observation identity and locations")
            selected = next(item for item in self.extraction.candidates if item.id == self.extraction.source_candidate_id)
            if selected.text != self.text:
                raise ValueError("source candidate must preserve observation text")


@dataclass(frozen=True, slots=True)
class DeepDocOutlineItem:
    title: str
    level: int
    page: int | None = None

    def __post_init__(self) -> None:
        if not self.title or self.title.strip() != self.title:
            raise ValueError("DeepDOC outline title must be trimmed and non-blank")
        if self.level < 1:
            raise ValueError("DeepDOC outline levels are 1-based")
        if self.page is not None and self.page < 1:
            raise ValueError("DeepDOC outline pages are 1-based")


@dataclass(frozen=True, slots=True)
class DeepDocDiagnostic:
    code: str
    message: str
    level: DeepDocDiagnosticLevel = DeepDocDiagnosticLevel.WARNING
    affects_structural_completeness: bool = False
    metadata: Mapping[str, DeepDocJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or self.code.strip() != self.code:
            raise ValueError("DeepDOC diagnostic code must be trimmed and non-blank")
        if len(self.code) > 128:
            raise ValueError("DeepDOC diagnostic code must not exceed 128 characters")
        if not self.message or self.message.strip() != self.message:
            raise ValueError("DeepDOC diagnostic message must be trimmed and non-blank")
        if len(self.message) > 4096:
            raise ValueError("DeepDOC diagnostic message must not exceed 4096 characters")
        object.__setattr__(self, "metadata", _freeze_json_object(self.metadata))


@dataclass(frozen=True, slots=True)
class DeepDocParseResult:
    parser_name: str
    parser_version: str
    media_type: str
    observations: tuple[DeepDocObservation, ...]
    outline: tuple[DeepDocOutlineItem, ...] = ()
    diagnostics: tuple[DeepDocDiagnostic, ...] = ()
    attributes: Mapping[str, DeepDocJsonValue] = field(default_factory=dict)
    manifest: DeepDocExtractionManifest | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("parser_name", self.parser_name),
            ("parser_version", self.parser_version),
            ("media_type", self.media_type),
        ):
            if not value or value.strip() != value:
                raise ValueError(f"DeepDOC {field_name} must be trimmed and non-blank")
        if len(self.parser_name) > 256:
            raise ValueError("DeepDOC parser_name must not exceed 256 characters")
        if len(self.parser_version) > 128:
            raise ValueError("DeepDOC parser_version must not exceed 128 characters")
        if len(self.media_type) > 256:
            raise ValueError("DeepDOC media_type must not exceed 256 characters")

        observations = tuple(self.observations)
        orders = [item.order for item in observations]
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            raise ValueError("DeepDOC observations must have unique ascending order values")
        source_ids = [item.source_id for item in observations]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("DeepDOC observations must have unique source ids")

        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "outline", tuple(self.outline))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "attributes", _freeze_json_object(self.attributes))
        if self.manifest is not None:
            if (self.manifest.producer.name, self.manifest.producer.version) != (self.parser_name, self.parser_version):
                raise ValueError("extraction manifest producer must match parser identity")
            for observation in observations:
                if observation.extraction is None:
                    raise ValueError("manifest requires an extraction trace for every observation")
                if any(item.source_sha256 != self.manifest.source_sha256 for item in observation.extraction.evidence):
                    raise ValueError("evidence source hash does not match extraction manifest")
            self.manifest.validate_text_traces(tuple(observation.extraction for observation in observations))
            if self.manifest.region_graph is not None:
                graph = self.manifest.region_graph
                regions = tuple(obs.extraction.region.id for obs in observations)
                if graph.reading_order != regions:
                    raise ValueError("region graph reading order must match observations")
                source_ids = {obs.extraction.region.id: obs.source_id for obs in observations}
                if any(source_ids.get(node.region_id) != node.source_id for node in graph.nodes):
                    raise ValueError("region graph source identities must match observations")


def _reconciliation_inputs(manifest, traces):
    by_page = defaultdict(list)
    for trace in traces:
        for page in sorted({loc.page for loc in trace.region.locations}):
            by_page[page].append(trace)
    if manifest.structures:
        for item in manifest.structures.regions:
            by_page[item.trace.region.locations[0].page].append(item.trace)
    for page in manifest.pages:
        by_page[page.page]
    layouts = {page.page: page for page in manifest.region_graph.pages} if manifest.region_graph else {}
    for page in layouts:
        by_page[page]
    count = manifest.admission.page_count if manifest.admission else max(by_page, default=0)
    return by_page, layouts, count


def _reconcile_page_fingerprint(traces, layout):
    records = []
    for trace in traces:
        chosen = [item for item in trace.candidates if item.id in {trace.source_candidate_id, trace.raw_candidate_id}]
        records.append({"region": asdict(trace.region), "candidates": [asdict(item) for item in chosen]})
    return _pdf_record_fingerprint({"regions": records, "layout": asdict(layout) if layout else None})


def _reconcile_window_fingerprint(source_sha256, policy, left, revisions):
    return _pdf_record_fingerprint({"source": source_sha256, "policy": asdict(policy), "pages": [(page, revisions.get(page)) for page in (left, left + 1)]})


def _source_candidate(trace):
    return next(item for item in trace.candidates if item.id == trace.source_candidate_id)


def _table_columns(table, location):
    positions = defaultdict(list)
    for cell in table.cells:
        positions[cell.column].append(cell.location.bbox.x0 / location.page_width)
        positions[cell.column + cell.column_span].append(cell.location.bbox.x1 / location.page_width)
    if set(positions) != set(range(table.columns + 1)) or any(max(values) - min(values) > 0.002 for values in positions.values()):
        return None
    return tuple(sum(positions[index]) / len(positions[index]) for index in range(table.columns + 1))


def _table_caption(text):
    if not text or len(text) > 180 or len(text.splitlines()) > 3:
        return None
    match = re.match(r"^(?:table|bảng)\s+([A-Z]?\d+(?:[.\-]\d+)*)(?:[.:])?(?:\s|$)(.*)$", " ".join(text.split()), re.IGNORECASE)
    return (match[1].casefold(), bool(re.search(r"\b(?:continued|cont\.?|tiếp theo|tiếp tục|tiếp)\b", match[2], re.IGNORECASE))) if match else None


def _chapter_start(traces):
    for trace in traces:
        role = trace.region.source_role
        if role in {"HEADER", "FOOTER", "PAGE_NUMBER", "FOOTNOTE", "CAPTION", "NAVIGATION"}:
            continue
        if DeepDocRegionLabel.TEXT not in trace.region.labels:
            continue
        text = _source_candidate(trace).text or ""
        if not text.strip():
            continue
        return role in {"HEADING", "TITLE"} or bool(re.match(r"^\s*(?:chapter|chương|part|phần)\s+(?:\d+|[IVXLCDM]+|một|hai|ba|bốn|năm)\b", text, re.IGNORECASE))
    return False


def _paragraph_cue(left, right):
    end = left.rstrip().rstrip('"”’)]}')
    start = right.lstrip()
    if not end or not start or re.search(r"[=∑∫√≠≤≥]", end.splitlines()[-1] + start.splitlines()[0]):
        return False
    if re.match(r"^(?:[-•*]|\d+[.)]|[a-z][.)])\s", start):
        return False
    return len(end.split()) >= 4 and len(start.split()) >= 3 and end[-1] not in ".!?:;" and (end[-1].isalnum() or end[-1] in "-,") and start[0].islower()


def _paragraph_region(trace):
    text = _source_candidate(trace).text or ""
    return (
        trace.region.labels == (DeepDocRegionLabel.TEXT,)
        and trace.region.source_role not in {"HEADER", "FOOTER", "PAGE_NUMBER", "FOOTNOTE", "NAVIGATION", "CAPTION", "TITLE", "HEADING", "FORMULA"}
        and len(text.split()) >= 3
        and not _table_caption(text)
        and not re.match(r"^\s*(?:hình|figure|fig\.)\s*\d", text, re.IGNORECASE)
    )


def _fusion_source_refs(parts):
    return tuple(dict.fromkeys(ref for part in parts for ref in part.source_refs))


def _fusion_refs_overlap(parts):
    previous = {}
    for ref in sorted(_fusion_source_refs(parts), key=lambda item: (item.candidate_id, item.start, item.end)):
        if ref.start < previous.get(ref.candidate_id, -1):
            return True
        previous[ref.candidate_id] = ref.end
    return False


def _alias_signature(trace):
    candidate = _source_candidate(trace)
    if candidate.table is None and candidate.formula is None:
        return None
    return _pdf_record_fingerprint(
        {
            "region": {"labels": trace.region.labels, "locations": [asdict(loc) for loc in trace.region.locations], "role": trace.region.source_role},
            "table": asdict(candidate.table) if candidate.table else None,
            "formula": asdict(candidate.formula) if candidate.formula else None,
        }
    )


def _fusion_part(trace, kind):
    candidate = _source_candidate(trace)
    if kind == "TABLE":
        if candidate.table is None:
            raise ValueError("table fusion requires typed source cells")
        spans = [span for cell in sorted(candidate.table.cells, key=lambda cell: (cell.row, cell.column)) for span in cell.source_spans]
        spans.extend(candidate.table.unassigned_source_spans)
        refs = tuple(DeepDocSpanRef(span.candidate_id, span.start, span.end, span.location) for span in spans)
    else:
        if not candidate.text:
            raise ValueError("paragraph fusion requires preserved source text")
        refs = (DeepDocSpanRef(candidate.id, 0, len(candidate.text), trace.region.locations[0]),)
    return DeepDocFusionPart(trace.region.id, candidate.id, refs)


def _validate_reconciliation(manifest, traces):
    report = manifest.reconciliation
    by_page, layouts, count = _reconciliation_inputs(manifest, traces)
    if report.page_count != count or [page.page for page in report.pages] != sorted(by_page):
        raise ValueError("reconciliation scope must match observed source pages")
    for page in report.pages:
        if page.revision_sha256 != _reconcile_page_fingerprint(by_page[page.page], layouts.get(page.page)):
            raise ValueError("stale page revision; dirty-page invalidation is required")
    all_traces = (*traces, *(item.trace for item in manifest.structures.regions)) if manifest.structures else traces
    regions = {trace.region.id: trace for trace in all_traces}
    source_region_ids = {trace.region.id for trace in traces}
    chapters = {page: _chapter_start([trace for trace in rows if trace.region.id in source_region_ids]) for page, rows in by_page.items()}
    source_candidates = {candidate.id: candidate for trace in traces for candidate in trace.candidates if candidate.id in {trace.source_candidate_id, trace.raw_candidate_id}}
    for page in report.pages:
        aliases = {alias.region_id for alias in page.aliases}
        if len(aliases) != len(page.aliases):
            raise ValueError("duplicate source alias")
        for alias in page.aliases:
            first, second = regions.get(alias.region_id), regions.get(alias.preferred_region_id)
            if (
                first is None
                or second is None
                or alias.preferred_region_id in aliases
                or _alias_signature(first) is None
                or _alias_signature(first) != _alias_signature(second)
                or len(first.region.locations) != 1
                or first.region.locations[0].page != page.page
            ):
                raise ValueError("source aliases require identical geometry, roles and source primitives")
    links = {}
    outgoing, incoming = set(), set()
    for window in report.windows:
        for link in window.links:
            if link.id in links:
                raise ValueError("duplicate cross-page link identity")
            links[link.id] = link
            first, second = regions.get(link.from_region_id), regions.get(link.to_region_id)
            if first is None or second is None or any(key not in regions for key in link.support_region_ids):
                raise ValueError("cross-page link references unknown source regions")
            if (_source_candidate(first).id, _source_candidate(second).id) != (link.from_candidate_id, link.to_candidate_id):
                raise ValueError("cross-page links require selected source candidates")
            if len(first.region.locations) != 1 or len(second.region.locations) != 1 or (first.region.locations[0].page, second.region.locations[0].page) != (window.left_page, window.left_page + 1):
                raise ValueError("continuation links must stay in their adjacent-page window")
            if link.state == "SUPPORTED":
                key1, key2 = (link.kind, link.from_region_id), (link.kind, link.to_region_id)
                if key1 in outgoing or key2 in incoming or chapters[window.left_page + 1]:
                    raise ValueError("supported continuation cannot branch or cross chapter boundaries")
                if any(layouts[page].column_count > 1 for page in (window.left_page, window.left_page + 1) if page in layouts):
                    raise ValueError("multi-column continuation requires additional evidence")
                outgoing.add(key1)
                incoming.add(key2)
                a, b = first.region.locations[0], second.region.locations[0]
                if not a.bbox or not b.bbox or a.bbox.y1 / a.page_height < 1 - report.policy.edge_fraction or b.bbox.y0 / b.page_height > report.policy.edge_fraction:
                    raise ValueError("supported continuation requires source page-edge geometry")
                if abs(a.bbox.x0 / a.page_width - b.bbox.x0 / b.page_width) > report.policy.alignment_tolerance:
                    raise ValueError("supported continuation requires aligned source geometry")
                if link.kind == "PARAGRAPH" and (
                    not _paragraph_region(first) or not _paragraph_region(second) or not _paragraph_cue(_source_candidate(first).text or "", _source_candidate(second).text or "")
                ):
                    raise ValueError("supported paragraph lacks a source continuation cue")
                if link.kind == "TABLE":
                    one, two = _source_candidate(first).table, _source_candidate(second).table
                    for key in link.support_region_ids:
                        region = regions[key].region
                        if len(region.locations) != 1 or region.locations[0].bbox is None or region.source_role in {"HEADER", "FOOTER", "PAGE_NUMBER", "FOOTNOTE", "NAVIGATION"}:
                            raise ValueError("table caption requires an eligible source anchor")
                        loc = region.locations[0]
                        target = a if loc.page == window.left_page else b if loc.page == window.left_page + 1 else None
                        if target is None or not 0 <= target.bbox.y0 - loc.bbox.y1 <= 48 or min(target.bbox.x1, loc.bbox.x1) <= max(target.bbox.x0, loc.bbox.x0):
                            raise ValueError("table caption must be adjacent to its source table")
                    captions = [_table_caption(_source_candidate(regions[key]).text) for key in link.support_region_ids]
                    left_captions = [c for key, c in zip(link.support_region_ids, captions, strict=True) if c and regions[key].region.locations[0].page == window.left_page]
                    right_captions = [c for key, c in zip(link.support_region_ids, captions, strict=True) if c and regions[key].region.locations[0].page == window.left_page + 1]
                    if one is None or two is None or not any(x[0] == y[0] and y[1] for x in left_captions for y in right_captions):
                        raise ValueError("supported table continuation needs explicit matching source captions")
                    columns1, columns2 = _table_columns(one, a), _table_columns(two, b)
                    if (
                        one.columns != two.columns
                        or columns1 is None
                        or columns2 is None
                        or any(abs(x - y) > report.policy.alignment_tolerance for x, y in zip(columns1, columns2, strict=True))
                        or one.text_coverage != 1.0
                        or two.text_coverage != 1.0
                    ):
                        raise ValueError("supported table requires aligned complete source cells")
    used = []
    for group in report.fusions:
        if _fusion_refs_overlap(group.parts):
            raise ValueError("overlapping source ranges must remain a fusion conflict")
        for part in group.parts:
            trace = regions.get(part.region_id)
            if trace is None or part != _fusion_part(trace, group.kind):
                raise ValueError("fusion parts must preserve exact source ranges and roles")
            for ref in part.source_refs:
                candidate = source_candidates.get(ref.candidate_id)
                if (
                    candidate is None
                    or candidate.origin == DeepDocContentOrigin.MODEL_INFERENCE
                    or candidate.text is None
                    or ref.end > len(candidate.text)
                    or not _region_contains(regions[candidate.region_id].region.locations, (ref.location,))
                ):
                    raise ValueError("fusion cannot contain model text or unknown source ranges")
        for index, key in enumerate(group.link_ids):
            link = links.get(key)
            if link is None or link.state != "SUPPORTED" or link.kind != group.kind or (link.from_region_id, link.to_region_id) != (group.parts[index].region_id, group.parts[index + 1].region_id):
                raise ValueError("fusion must follow supported physical links")
        used.extend(group.link_ids)
    for conflict in report.fusion_conflicts:
        if any(key not in links or links[key].state != "SUPPORTED" for key in conflict.link_ids):
            raise ValueError("fusion conflict requires supported source links")
        used.extend(conflict.link_ids)
    if len(used) != len(set(used)) or set(used) != {key for key, link in links.items() if link.state == "SUPPORTED"}:
        raise ValueError("fusion/conflicts must account for every supported physical link once")


def _pdf_record_fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _work_input_fingerprint(trace, candidate_id, configuration_sha256, policy_sha256):
    return _pdf_record_fingerprint({"trace": asdict(trace), "candidate_id": candidate_id, "configuration": configuration_sha256, "policy": policy_sha256})


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > 4096:
        raise ValueError("extraction identifiers must be trimmed, non-blank strings up to 4096 characters")


def _sha256(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("extraction fingerprint must be a lowercase SHA-256 digest")


def _references(values: tuple[str, ...]) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        _identifier(value)
    if len(result) != len(set(result)):
        raise ValueError("extraction references must be unique")
    return result


def _freeze_json_object(
    value: Mapping[str, DeepDocJsonValue],
) -> Mapping[str, DeepDocJsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("DeepDOC attributes must be a mapping")
    frozen: dict[str, DeepDocJsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("DeepDOC attribute keys must be strings")
        frozen[key] = _freeze_json_value(item)
    return MappingProxyType(frozen)


def _finite_number(value: SupportsFloat, label: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite")
    return normalized


def _freeze_json_value(value: DeepDocJsonValue) -> DeepDocJsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("DeepDOC attributes cannot contain non-finite floats")
        return value
    if isinstance(value, Mapping):
        return _freeze_json_object(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise TypeError(f"DeepDOC attributes contain unsupported value {type(value)!r}")


__all__ = [
    "DEEPDOC_OBSERVATION_CONTRACT_VERSION",
    "DeepDocBoundingBox",
    "DeepDocCandidate",
    "DeepDocCapability",
    "DeepDocCapabilityRequest",
    "DeepDocContentOrigin",
    "DeepDocDecision",
    "DeepDocDecisionAction",
    "DeepDocDiagnostic",
    "DeepDocDiagnosticLevel",
    "DeepDocEvidence",
    "DeepDocExtractionManifest",
    "DeepDocExtractionSource",
    "DeepDocExtractionTrace",
    "DeepDocFigureClaim",
    "DeepDocFigureInterpretation",
    "DeepDocFigureInventory",
    "DeepDocFigureReference",
    "DeepDocFigureType",
    "DeepDocFontEvidence",
    "DeepDocFormula",
    "DeepDocFusionConflict",
    "DeepDocFusionGroup",
    "DeepDocFusionPart",
    "DeepDocGateAssessment",
    "DeepDocGateReport",
    "DeepDocGeometryCharacter",
    "DeepDocGlyphFinding",
    "DeepDocGlyphProof",
    "DeepDocJsonValue",
    "DeepDocLayoutNode",
    "DeepDocObservation",
    "DeepDocObservationKind",
    "DeepDocOutlineItem",
    "DeepDocPageFacts",
    "DeepDocPageLayout",
    "DeepDocPageLink",
    "DeepDocPageReason",
    "DeepDocParseResult",
    "DeepDocParseStatus",
    "DeepDocPdfAdmission",
    "DeepDocProducer",
    "DeepDocReconcilePage",
    "DeepDocReconcileWindow",
    "DeepDocReconciliationPolicy",
    "DeepDocReconciliationReport",
    "DeepDocRegion",
    "DeepDocRegionAlias",
    "DeepDocRegionEdge",
    "DeepDocRegionGraph",
    "DeepDocRegionLabel",
    "DeepDocRegionRelation",
    "DeepDocRegionRoute",
    "DeepDocReviewProof",
    "DeepDocSecondaryTextEvidence",
    "DeepDocSourceLocation",
    "DeepDocSourceSpan",
    "DeepDocSpanGeometry",
    "DeepDocSpanRef",
    "DeepDocStructuredExtractionReport",
    "DeepDocStructuredRegion",
    "DeepDocStyle",
    "DeepDocTable",
    "DeepDocTableCell",
    "DeepDocTextEdit",
    "DeepDocTextExtractionReport",
    "DeepDocWorkLimits",
    "DeepDocWorkRecord",
    "DeepDocWorkRequest",
]
