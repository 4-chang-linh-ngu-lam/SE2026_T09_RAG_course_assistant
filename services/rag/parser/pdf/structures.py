"""Compose unverified native structure proposals without duplicating source text."""

from dataclasses import asdict, dataclass, replace

from ..source_observation import (
    DeepDocCandidate,
    DeepDocContentOrigin,
    DeepDocDecision,
    DeepDocDecisionAction,
    DeepDocEvidence,
    DeepDocExtractionTrace,
    DeepDocRegion,
    DeepDocRegionLabel,
    DeepDocStructuredExtractionReport,
    DeepDocStructuredRegion,
)
from .contracts import _fingerprint


@dataclass(frozen=True, slots=True)
class PdfStructurePolicy:
    max_edges_per_page: int = 500
    max_cells_per_table: int = 2000
    max_regions: int = 5000
    max_math_pair_checks_per_page: int = 50_000
    max_math_geometry_pages: int = 16
    version: str = "pdf-native-structures:2"

    def __post_init__(self):
        if self.version != "pdf-native-structures:2" or any(
            type(value) is not int or value < 1 for value in (self.max_edges_per_page, self.max_cells_per_table, self.max_regions, self.max_math_pair_checks_per_page, self.max_math_geometry_pages)
        ):
            raise ValueError("structure policy requires supported version and positive integer limits")

    @property
    def fingerprint(self):
        return _fingerprint(asdict(self))


def _structure_region(source_sha, producer, label, location, *, table=None, formula=None, parent=None):
    material = {
        "source": source_sha,
        "producer": asdict(producer),
        "label": label,
        "location": asdict(location),
        "table": asdict(table) if table else None,
        "formula": asdict(formula) if formula else None,
    }
    digest = _fingerprint(material)
    region = DeepDocRegion("region:" + digest, "pdf:structure:" + digest, (DeepDocRegionLabel(label),), (location,), source_role=label)
    origin = DeepDocContentOrigin.STRUCTURAL_EXTRACTION if table else DeepDocContentOrigin.SOURCE_TRANSCRIPTION
    evidence = DeepDocEvidence("evidence:" + digest, region.id, origin, producer, _fingerprint({"source": source_sha, "location": asdict(location)}), source_sha)
    candidate = DeepDocCandidate("candidate:" + digest, region.id, origin, producer, (evidence.id,), formula.native_text if formula else None, formula, table=table)
    decision = DeepDocDecision(
        "decision:" + digest,
        candidate.id,
        DeepDocDecisionAction.UNRESOLVED,
        "NATIVE_TABLE_GRID_REQUIRES_VERIFICATION" if table else "NATIVE_MATH_REQUIRES_VERIFICATION",
        "native-structure-selection:1",
        (evidence.id,),
    )
    return DeepDocStructuredRegion(DeepDocExtractionTrace(region, (evidence,), (candidate,), candidate.id, candidate.id, (decision,)), parent)


def attach_native_structures(parsed, source, native, *, policy=None):
    from .extractors.math import extract_native_math
    from .extractors.table import extract_native_tables

    policy = policy or PdfStructurePolicy()
    tables, diagnostics, pages = extract_native_tables(source, native.words, policy)
    math, math_diagnostics = extract_native_math(source, native.lines, native.words, parsed.observations, tables, policy)
    report = DeepDocStructuredExtractionReport(source.report.source_sha256, policy.fingerprint, (*tables, *math), pages)
    report.validate_source_traces(tuple(item.extraction for item in parsed.observations))
    return replace(parsed, manifest=replace(parsed.manifest, structures=report), diagnostics=(*parsed.diagnostics, *diagnostics, *math_diagnostics))
