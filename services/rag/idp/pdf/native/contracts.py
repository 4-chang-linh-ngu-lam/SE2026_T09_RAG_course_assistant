"""Bind extraction records to source bytes without running a quality gate.

Output types live in source_observation so canonical consumers reuse one contract.
This module owns deterministic construction, not storage or model resolution.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, replace

from idp.evidence.contracts import (
    DEEPDOC_EXTRACTION_INVENTORY_VERSION,
    DEEPDOC_OBSERVATION_CONTRACT_VERSION,
    DEEPDOC_SOURCE_RETRIEVAL_POLICY_VERSION,
    DeepDocBoundingBox,
    DeepDocCandidate,
    DeepDocContentOrigin,
    DeepDocDecision,
    DeepDocDecisionAction,
    DeepDocEvidence,
    DeepDocExtractionManifest,
    DeepDocExtractionTrace,
    DeepDocFigureInterpretation,
    DeepDocFigureInventory,
    DeepDocFigureReference,
    DeepDocFigureType,
    DeepDocFormula,
    DeepDocObservation,
    DeepDocParseResult,
    DeepDocParseStatus,
    DeepDocProducer,
    DeepDocRegion,
    DeepDocRegionLabel,
    DeepDocSourceLocation,
    DeepDocTextExtractionReport,
)

_SOURCE_POLICY = DEEPDOC_SOURCE_RETRIEVAL_POLICY_VERSION


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _source_trace(observation: DeepDocObservation, source_sha256: str, producer: DeepDocProducer) -> DeepDocExtractionTrace:
    """Inventory existing extraction; absence of a decision means unassessed."""
    if observation.kind.value == "FIGURE":
        producer = DeepDocProducer("pdf-figure-source-context", "1")
    labels = [DeepDocRegionLabel(observation.kind.value)]
    if observation.type_hint == "FORMULA":
        labels.append(DeepDocRegionLabel.MATH)
    region = DeepDocRegion(
        id="region:" + _fingerprint({"source": source_sha256, "id": observation.source_id, "locations": [asdict(loc) for loc in observation.locations]}),
        source_id=observation.source_id,
        labels=tuple(labels),
        locations=observation.locations,
        source_role=_physical_role(observation),
    )
    figure = observation.attributes.get("figure", {})
    assets = (figure["asset"],) if "asset" in figure else figure.get("assets", ())
    asset_ids = tuple(asset["id"] for asset in assets)
    origin = DeepDocContentOrigin.STRUCTURAL_EXTRACTION if observation.kind.value in {"FIGURE", "TABLE"} else DeepDocContentOrigin.SOURCE_TRANSCRIPTION
    evidence_payload = {
        "region": region.id,
        "text": observation.text,
        "assets": asset_ids,
        "producer": asdict(producer),
        "extraction_source": observation.extraction_source.value,
    }
    input_sha256 = _fingerprint({"source": source_sha256, "region": region.id, "assets": asset_ids})
    evidence = DeepDocEvidence("evidence:" + _fingerprint({**evidence_payload, "input": input_sha256}), region.id, origin, producer, input_sha256, source_sha256, asset_ids)
    formula = DeepDocFormula(observation.text) if DeepDocRegionLabel.MATH in labels and observation.text else None
    candidate = DeepDocCandidate(
        "candidate:" + _fingerprint({**evidence_payload, "formula": asdict(formula) if formula else None}), region.id, origin, producer, (evidence.id,), observation.text, formula
    )
    return DeepDocExtractionTrace(region, (evidence,), (candidate,), candidate.id, candidate.id, figure=_figure_inventory(observation, source_sha256) if observation.kind.value == "FIGURE" else None)


def _physical_role(observation):
    return "NAVIGATION" if observation.attributes.get("source_zone") == "navigation" else observation.type_hint


def _figure_inventory(observation, source_sha256):
    metadata = observation.attributes.get("figure", {})
    primary = observation.locations[0] if observation.locations else None
    records = {}

    def add(kind, source_id, text, box=None):
        if not isinstance(text, str) or not text.strip():
            return
        text = text.strip()[:1200]
        location = DeepDocSourceLocation(primary.page, primary.page_width, primary.page_height, DeepDocBoundingBox(*box)) if primary is not None and box is not None else None
        material = {"source": source_sha256, "kind": kind, "source_id": source_id, "text": text, "location": asdict(location) if location else None}
        ref = DeepDocFigureReference("figure-ref:" + _fingerprint(material), kind, source_id, text, location)
        records[ref.id] = ref

    add("CAPTION", metadata.get("caption_source_id") or observation.source_id, metadata.get("caption", ""))
    if metadata.get("label_regions"):
        for item in metadata["label_regions"]:
            add("LABEL", item["source_id"], item["text"], item.get("bbox"))
    else:
        for label in metadata.get("labels", ()):
            add("LABEL", observation.source_id, label)
    for item in metadata.get("source_context", ()):
        add("PASSAGE", item["source_id"], item["text"])
    caption = metadata.get("caption", "").casefold()
    figure_type = DeepDocFigureType.UNKNOWN
    reasons = ("VISUAL_TYPE_UNASSESSED",)
    for pattern, label in (
        (r"\b(chart|graph|biểu đồ|đồ thị)\b", DeepDocFigureType.CHART),
        (r"\b(diagram|sơ đồ)\b", DeepDocFigureType.DIAGRAM),
        (r"\b(photograph|photo|ảnh chụp)\b", DeepDocFigureType.PHOTO),
        (r"\b(illustration|minh họa|map|bản đồ)\b", DeepDocFigureType.ILLUSTRATION),
    ):
        if re.search(pattern, caption):
            figure_type = label
            reasons = ("SOURCE_CAPTION_TYPE_CUE",)
            break
    allowed = bool(observation.text and observation.text.strip())
    return DeepDocFigureInventory(
        tuple(records[key] for key in sorted(records)), figure_type, reasons, source_retrieval_allowed=allowed, retrieval_reason="SOURCE_CONTEXT_AVAILABLE" if allowed else "NO_SOURCE_TEXT"
    )


def figure_description_trace(observation: DeepDocObservation, interpretation: DeepDocFigureInterpretation, producer: DeepDocProducer) -> DeepDocExtractionTrace:
    figure = observation.attributes["figure"]
    assets = (figure["asset"],) if "asset" in figure else figure.get("assets", ())
    if len(assets) != 1:
        raise ValueError("figure description requires exactly one source-bound asset")
    source_sha256 = assets[0]["source_pdf_sha256"]
    trace = observation.extraction or _source_trace(observation, source_sha256, DeepDocProducer("pdf-figure-source-context", "1"))
    # Context participates in identity even when the visible crop is unchanged.
    input_sha256 = _fingerprint({"asset": assets[0]["id"], "references": [asdict(ref) for ref in trace.figure.references]})
    text = "\n".join(claim.text for claim in interpretation.claims)
    material = {"region": trace.region.id, "input": input_sha256, "producer": asdict(producer), "interpretation": asdict(interpretation)}
    evidence = DeepDocEvidence("evidence:" + _fingerprint(material), trace.region.id, DeepDocContentOrigin.MODEL_INFERENCE, producer, input_sha256, source_sha256, (assets[0]["id"],))
    candidate = DeepDocCandidate(
        "candidate:" + _fingerprint({**material, "evidence": evidence.id}), trace.region.id, DeepDocContentOrigin.MODEL_INFERENCE, producer, (evidence.id,), text, figure=interpretation
    )
    decision = DeepDocDecision(
        "decision:" + _fingerprint({"candidate": candidate.id, "policy": _SOURCE_POLICY}), candidate.id, DeepDocDecisionAction.UNRESOLVED, "UNVERIFIED_MODEL_INFERENCE", _SOURCE_POLICY, (evidence.id,)
    )
    return DeepDocExtractionTrace(
        trace.region, (*trace.evidence, evidence), (*trace.candidates, candidate), trace.source_candidate_id, trace.raw_candidate_id, (*trace.decisions, decision), trace.figure
    )


def bind_pdf_result(parsed: DeepDocParseResult, source: bytes, *, configuration: dict | None = None, text_extraction: DeepDocTextExtractionReport | None = None) -> DeepDocParseResult:
    """Freeze source/config identity at the producer or adapter boundary."""
    if parsed.media_type != "application/pdf" or not isinstance(source, bytes) or not source:
        raise ValueError("PDF evidence requires exact non-empty PDF source bytes")
    source_sha256 = hashlib.sha256(source).hexdigest()
    producer = DeepDocProducer(parsed.parser_name, parsed.parser_version)
    config = {
        "contract_version": DEEPDOC_OBSERVATION_CONTRACT_VERSION,
        "inventory_version": DEEPDOC_EXTRACTION_INVENTORY_VERSION,
        "producer": asdict(producer),
        "policy": _SOURCE_POLICY,
        "configuration": configuration or {},
    }
    configuration_sha256 = _fingerprint(config)
    if parsed.manifest is not None:
        if parsed.manifest.source_sha256 != source_sha256:
            raise ValueError("extraction manifest does not match exact source bytes")
        if configuration is not None and parsed.manifest.configuration_sha256 != configuration_sha256:
            raise ValueError("extraction manifest does not match supplied configuration")
        if text_extraction is not None and parsed.manifest.text_extraction != text_extraction:
            raise ValueError("native text report conflicts with extraction manifest")
        return parsed
    observations = tuple(replace(obs, extraction=obs.extraction or _source_trace(obs, source_sha256, producer)) for obs in parsed.observations)
    return replace(
        parsed,
        observations=observations,
        manifest=DeepDocExtractionManifest(
            source_sha256,
            configuration_sha256,
            producer,
            DeepDocParseStatus.PARTIAL if any(d.affects_structural_completeness for d in parsed.diagnostics) else DeepDocParseStatus.COMPLETE,
            text_extraction=text_extraction,
        ),
    )
