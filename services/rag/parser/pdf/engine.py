"""Compose native PDF text, figures, page facts and physical layout; never OCR."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace
from time import monotonic
from typing import Protocol, runtime_checkable

from ..source_observation import (
    DeepDocBoundingBox,
    DeepDocCapability,
    DeepDocDecisionAction,
    DeepDocDiagnostic,
    DeepDocExtractionSource,
    DeepDocExtractionTrace,
    DeepDocGateReport,
    DeepDocParseResult,
    DeepDocProducer,
    DeepDocReconciliationPolicy,
    DeepDocSourceLocation,
    DeepDocWorkLimits,
    DeepDocWorkRecord,
    DeepDocWorkRequest,
)
from .analysis import attach_page_analysis
from .budget import PdfWorkBudget
from .contracts import _fingerprint, _physical_role, bind_pdf_result
from .evidence import _EvidenceAdmissionError, admit_verification, input_fingerprint
from .extractors.figure import FigureDescriber, describe_pdf_figure, extract_pdf_figures
from .extractors.text import extract_native_text
from .layout import PdfLayoutPolicy, apply_pdf_layout
from .preflight import PdfAdmissionError, PdfAdmissionPolicy, PdfSource
from .quality import PdfQualityPolicy, assess_candidate
from .reconcile import reconcile_pages
from .structures import PdfStructurePolicy, attach_native_structures


@dataclass(frozen=True, slots=True)
class PdfVerifier:
    capability: DeepDocCapability
    producer: DeepDocProducer
    independence_family: str
    resource: str = "CPU"

    def __post_init__(self):
        if self.resource not in {"CPU", "GPU", "REMOTE"} or not self.independence_family or self.independence_family.strip() != self.independence_family:
            raise ValueError("verifier requires an explicit resource and backend family")


@dataclass(frozen=True, slots=True)
class PdfWorkResponse:
    request_id: str
    input_sha256: str
    trace: DeepDocExtractionTrace | None = None
    reroute_to: DeepDocCapability | None = None

    def __post_init__(self):
        if self.trace is not None and self.reroute_to is not None:
            raise ValueError("verifier must return evidence or a reroute, not both")


class PdfWorkDeferred(BaseException):
    """Suspend the parent without converting pending durable work into failure."""

    def __init__(self, request, trace):
        self.request = request
        self.trace = trace
        self.checkpoint = None


class PdfWorkTerminalError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@runtime_checkable
class PdfWorkRuntime(Protocol):
    def execute(self, request: DeepDocWorkRequest, trace: DeepDocExtractionTrace, *, timeout_seconds: float) -> PdfWorkResponse: ...


_HEADING = re.compile(
    r"^(?:(?:chương|chapter)\s+(?:\d+|[IVXLCDM]+)\b|\d+(?:\.\d+){1,4}\.?\s+[^\W\d_]|"
    r"(?:mục lục|contents|table of contents|mở đầu|lời nói đầu|preface|introduction|conclusion)$)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"^\d+$")
_LEADERS = re.compile(r"(?:\.\s*){5,}")


class PdfParsingEngine:
    """Compose source-bound native capabilities into the typed PDF contract."""

    def extract_source(
        self,
        data: bytes,
        *,
        glyph_corrections=None,
        figure_describer: FigureDescriber | None = None,
        policy: PdfAdmissionPolicy | None = None,
        layout_policy: PdfLayoutPolicy | None = None,
        structure_policy: PdfStructurePolicy | None = None,
        quality_policy: PdfQualityPolicy | None = None,
        work_limits: DeepDocWorkLimits | None = None,
        runtime: PdfWorkRuntime | None = None,
        verifiers: tuple[PdfVerifier, ...] = (),
        reconciliation_policy: DeepDocReconciliationPolicy | None = None,
    ) -> DeepDocParseResult:
        with PdfSource(data, policy) as source:
            native = extract_native_text(source, glyph_corrections=glyph_corrections)
            observations = _decorate_text(native.observations)
            diagnostics = list(native.diagnostics)
            figures = ()
            figure_status = "complete"
            try:
                text_by_id = {item.source_id: item for item in observations}
                figure_regions = tuple(
                    replace(
                        text_by_id[block.source_id],
                        text=line,
                        locations=(DeepDocSourceLocation(block.page, block.page_width, block.page_height, DeepDocBoundingBox(*bbox)),),
                        attributes={},
                        extraction=None,
                    )
                    for block in native.blocks
                    for line, bbox in zip(block.lines, block.line_boxes, strict=True)
                    if bbox is not None and line.strip() and len(line) <= 160
                )
                figures, figure_diagnostics = extract_pdf_figures(data, observations, text_regions=figure_regions, source=source)
                diagnostics.extend(figure_diagnostics)
                if any(item.affects_structural_completeness for item in figure_diagnostics):
                    figure_status = "partial"
            except PdfAdmissionError:
                raise
            except Exception as exc:  # noqa: BLE001 - optional figure failure preserves native source records.
                figure_status = "unavailable"
                diagnostics.append(
                    DeepDocDiagnostic(
                        "PDF_FIGURE_EXTRACTION_UNAVAILABLE",
                        "Figure extraction failed; native text was preserved",
                        affects_structural_completeness=True,
                        metadata={"reason": f"{type(exc).__name__}: {exc}"[:1000]},
                    )
                )
            if not observations and not figures:
                raise ValueError("PDF has no extractable native text or figures; Plain Text ingestion never falls back to OCR")
            observations = tuple(replace(item, order=index) for index, item in enumerate((*observations, *figures)))
            producer = native.report.native_producer
            summary = native.summary
            parsed = DeepDocParseResult(
                producer.name,
                producer.version,
                "application/pdf",
                observations,
                diagnostics=tuple(diagnostics),
                attributes={
                    "extraction_backend": "native_text",
                    "ocr_used": False,
                    "verified_glyph_correction_count": summary["manual_glyph_correction_count"] + summary["font_glyph_recovery_count"],
                    "manual_glyph_correction_count": summary["manual_glyph_correction_count"],
                    "font_glyph_recovery_count": summary["font_glyph_recovery_count"],
                    "pdf_glyph_inspection": summary,
                    "page_count": len(source.geometry),
                    "text_page_count": len({block.page for block in native.blocks}),
                    "figure_count": len(figures),
                    "figure_extraction_version": "2",
                    "figure_extraction_status": figure_status,
                    "block_order": "poppler_bbox_layout",
                    "heading_policy_version": "1",
                    "navigation_page_count": len({item.locations[0].page for item in observations if item.attributes.get("source_zone") == "navigation"}),
                },
            )
            layout_policy = layout_policy or PdfLayoutPolicy()
            structure_policy = structure_policy or PdfStructurePolicy()
            bound = bind_pdf_result(
                parsed,
                data,
                text_extraction=native.report,
                configuration={
                    "extractor_version": "pdf-engine:2",
                    "structure_policy_sha256": structure_policy.fingerprint,
                    "native_text_stage_version": native.report.version,
                    "selection_policy_version": native.report.selection_policy_version,
                    "layout_policy_sha256": layout_policy.fingerprint,
                    "admission_policy_sha256": source.policy.fingerprint,
                    "describe_figures": figure_describer is not None,
                    "quality_policy_sha256": (quality_policy or PdfQualityPolicy()).fingerprint,
                    "work_limits": asdict(work_limits or _default_limits(figure_describer)),
                    "glyph_corrections_sha256": native.corrections_sha256,
                    "reconciliation_policy": asdict(reconciliation_policy or DeepDocReconciliationPolicy()),
                },
            )
            bound = attach_native_structures(bound, source, native, policy=structure_policy)
            bound = apply_pdf_layout(attach_page_analysis(bound, source), policy=layout_policy, check_deadline=source.check_deadline)
            return self.evaluate(
                bound,
                quality_policy=quality_policy,
                work_limits=work_limits,
                runtime=runtime,
                verifiers=verifiers,
                figure_describer=figure_describer,
                data=data,
                source=source,
                reconciliation_policy=reconciliation_policy,
            )

    def evaluate(self, parsed: DeepDocParseResult, *, reconciliation_policy=None, **kwargs) -> DeepDocParseResult:
        parsed = reconcile_pages(parsed, policy=reconciliation_policy)
        try:
            return self._evaluate(parsed, **kwargs)
        except PdfWorkDeferred as pending:
            pending.checkpoint = parsed
            raise

    def _evaluate(
        self,
        parsed: DeepDocParseResult,
        *,
        quality_policy: PdfQualityPolicy | None = None,
        work_limits: DeepDocWorkLimits | None = None,
        runtime: PdfWorkRuntime | None = None,
        verifiers: tuple[PdfVerifier, ...] = (),
        figure_describer: FigureDescriber | None = None,
        data: bytes | None = None,
        source: PdfSource | None = None,
        clock=monotonic,
    ) -> DeepDocParseResult:
        """Run a finite synchronous controller; durable execution belongs to runtime."""
        if parsed.manifest is None:
            raise ValueError("quality gate requires source-bound extraction")
        if parsed.manifest.quality_gate is not None:
            # A completed run is immutable; replay must not reset its budgets.
            if runtime is not None or figure_describer is not None:
                raise ValueError("completed gate cannot execute work again")
            if (
                quality_policy is not None
                and parsed.manifest.quality_gate.policy_sha256 != quality_policy.fingerprint
                or work_limits is not None
                and parsed.manifest.quality_gate.limits != work_limits
            ):
                raise ValueError("completed gate cannot change policy or budget")
            return parsed
        quality_policy = quality_policy or PdfQualityPolicy()
        limits = work_limits or _default_limits(figure_describer)
        ledger = PdfWorkBudget(limits)
        deadline = clock() + limits.timeout_seconds
        work, diagnostics = [], list(parsed.diagnostics)
        observations = list(parsed.observations)
        traces = {item.extraction.region.id: item.extraction for item in observations}
        structures = parsed.manifest.structures
        if structures:
            traces.update({item.trace.region.id: item.trace for item in structures.regions})
        if figure_describer is not None:
            if data is None:
                raise ValueError("descriptions require exact source bytes")
            for index, item in enumerate(observations):
                if item.extraction.figure is None:
                    continue
                trace = item.extraction
                candidate = next(c for c in trace.candidates if c.id == trace.source_candidate_id)
                producer = DeepDocProducer("pdf-figure-description", "3", getattr(figure_describer, "model_name", None))
                request, reason = _request(parsed, trace, candidate, DeepDocCapability.FIGURE, "DESCRIBE", producer, "unknown", "REMOTE", quality_policy, ledger, deadline, clock)
                if request is None:
                    diagnostics.append(DeepDocDiagnostic("PDF_FIGURE_DESCRIPTION_BUDGET", reason, metadata={"source_id": item.source_id}))
                    continue
                try:
                    if clock() >= deadline:
                        raise TimeoutError("description deadline exceeded")
                    if runtime is None:
                        described = describe_pdf_figure(data, item, figure_describer, source=source)
                    else:
                        response = runtime.execute(request, trace, timeout_seconds=max(0.0, deadline - clock()))
                        if not isinstance(response, PdfWorkResponse) or (response.request_id, response.input_sha256) != (request.id, request.input_sha256) or response.trace is None:
                            raise _EvidenceAdmissionError("STALE_WORK_RESPONSE")
                        from .evidence import admit_description

                        updated = admit_description(trace, response.trace, producer)
                        described = replace(item, extraction=updated)
                    if clock() >= deadline:
                        raise TimeoutError("verification deadline exceeded")
                    observations[index] = described
                    traces[trace.region.id] = described.extraction
                    work.append(DeepDocWorkRecord(request, "SUCCEEDED", "DESCRIPTION_CANDIDATE_RETAINED"))
                except Exception as exc:  # noqa: BLE001 - optional model work cannot erase source.
                    reason = "DEADLINE_EXCEEDED" if isinstance(exc, TimeoutError) else exc.reason if isinstance(exc, PdfWorkTerminalError) else "DESCRIPTION_FAILED"
                    work.append(DeepDocWorkRecord(request, "FAILED", reason))
                    diagnostics.append(DeepDocDiagnostic("PDF_FIGURE_DESCRIPTION_FAILED", reason, metadata={"source_id": item.source_id}))
        findings = parsed.manifest.text_extraction.findings if parsed.manifest.text_extraction else ()
        scoped = _scoped_findings(traces, findings)
        assessments = []
        for region_id, initial in tuple(traces.items()):
            queue = deque(c.id for c in initial.candidates)
            reasons = {}
            while queue:
                candidate_id = queue.popleft()
                trace = traces[region_id]
                candidate = next(c for c in trace.candidates if c.id == candidate_id)
                assessment = assess_candidate(trace, candidate, scoped[region_id])
                if assessment.action != DeepDocDecisionAction.VERIFY:
                    assessments.append(assessment)
                    continue
                target, operation = assessment.capability, "VERIFY"
                while True:
                    matches = sorted((v for v in verifiers if v.capability == target), key=lambda v: ({"CPU": 0, "REMOTE": 1, "GPU": 2}[v.resource], v.producer.name, v.producer.version))
                    request, reason = None, "CAPABILITY_UNAVAILABLE"
                    if runtime is not None:
                        for verifier in matches:
                            request, reason = _request(
                                parsed, trace, candidate, target, operation, verifier.producer, verifier.independence_family, verifier.resource, quality_policy, ledger, deadline, clock
                            )
                            if request is not None:
                                break
                    if request is None:
                        reasons[candidate_id] = (*reasons.get(candidate_id, ()), reason)
                        break
                    try:
                        remaining = deadline - clock()
                        if remaining <= 0:
                            raise TimeoutError("verification deadline exceeded")
                        response = runtime.execute(request, trace, timeout_seconds=remaining)
                        if clock() >= deadline:
                            raise TimeoutError("verification deadline exceeded")
                        if not isinstance(response, PdfWorkResponse) or (response.request_id, response.input_sha256) != (request.id, request.input_sha256):
                            raise _EvidenceAdmissionError("STALE_WORK_RESPONSE")
                        if response.reroute_to is not None:
                            work.append(DeepDocWorkRecord(request, "SUCCEEDED", "REGION_TYPE_CONFLICT"))
                            reasons[candidate_id] = (*reasons.get(candidate_id, ()), "REGION_TYPE_CONFLICT")
                            target, operation = response.reroute_to, "REROUTE"
                            continue
                        if response.trace is None:
                            work.append(DeepDocWorkRecord(request, "SUCCEEDED", "VERIFIER_UNRESOLVED"))
                            reasons[candidate_id] = (*reasons.get(candidate_id, ()), "VERIFIER_UNRESOLVED")
                            break
                        updated = admit_verification(trace, response.trace, verifier.producer, verifier.independence_family)
                        # Validate global source/span references before retaining any new payload.
                        proposed = {**traces, region_id: updated}
                        try:
                            _replace_traces(parsed, observations, proposed)
                        except ValueError as exc:
                            raise _EvidenceAdmissionError("SOURCE_REFERENCE_CONFLICT") from exc
                        traces[region_id] = updated
                        queue.extend(c.id for c in updated.candidates[len(trace.candidates) :])
                        work.append(DeepDocWorkRecord(request, "SUCCEEDED", "EVIDENCE_ALTERNATIVES_RETAINED"))
                        reasons[candidate_id] = (*reasons.get(candidate_id, ()), "VERIFICATION_DID_NOT_ESTABLISH_SOURCE_TRUTH")
                        break
                    except Exception as exc:  # noqa: BLE001 - failure consumes budget and retains raw alternatives.
                        reason = "DEADLINE_EXCEEDED" if isinstance(exc, TimeoutError) else exc.reason if isinstance(exc, (_EvidenceAdmissionError, PdfWorkTerminalError)) else "VERIFIER_FAILURE"
                        work.append(DeepDocWorkRecord(request, "FAILED", reason))
                        reasons[candidate_id] = (*reasons.get(candidate_id, ()), reason)
                        if reason in {"DEADLINE_EXCEEDED", "EXECUTION_OUTCOME_UNKNOWN", "RUN_CANCELLED"}:
                            break
                        # The next reservation enforces both run and lineage limits.
                assessments.append(replace(assessment, action=DeepDocDecisionAction.UNRESOLVED, reason_codes=tuple(dict.fromkeys((*assessment.reason_codes, *reasons[candidate_id])))))
        result = _replace_traces(parsed, observations, traces)
        report = DeepDocGateReport(parsed.manifest.source_sha256, quality_policy.fingerprint, limits, tuple(assessments), tuple(work))
        return replace(result, manifest=replace(result.manifest, quality_gate=report), diagnostics=tuple(diagnostics))


def _default_limits(describer):
    return DeepDocWorkLimits(remote=16 if describer is not None else 0)


def _request(parsed, trace, candidate, capability, operation, producer, family, resource, policy, ledger, deadline, clock):
    if clock() >= deadline:
        return None, "DEADLINE_EXCEEDED"
    ordinal, reason = ledger.reserve(trace.region.id, operation, resource)
    if ordinal is None:
        return None, reason
    fingerprint = input_fingerprint(trace, candidate, parsed.manifest.configuration_sha256, policy.fingerprint)
    material = {
        "source": parsed.manifest.source_sha256,
        "input": fingerprint,
        "capability": capability,
        "operation": operation,
        "producer": asdict(producer),
        "family": family,
        "resource": resource,
        "ordinal": ordinal,
    }
    return DeepDocWorkRequest(
        "work:" + _fingerprint(material),
        parsed.manifest.source_sha256,
        fingerprint,
        trace.region.id,
        trace.region.id,
        candidate.id,
        capability,
        operation,
        resource,
        producer,
        family,
        ordinal,
        len(trace.candidates),
        len(trace.evidence),
        len(trace.decisions),
    ), None


def _replace_traces(parsed, observations, traces):
    structures = parsed.manifest.structures
    if structures:
        structures = replace(structures, regions=tuple(replace(item, trace=traces[item.trace.region.id]) for item in structures.regions))
    return replace(parsed, observations=tuple(replace(item, extraction=traces[item.extraction.region.id]) for item in observations), manifest=replace(parsed.manifest, structures=structures))


def _scoped_findings(traces, findings):
    by_source, by_page, document = defaultdict(list), defaultdict(list), []
    for finding in findings:
        if finding.scope == "REGION":
            by_source[finding.source_id].append(finding)
        elif finding.page is not None:
            by_page[finding.page].append(finding)
        else:
            document.append(finding)
    return {key: (*document, *by_source[trace.region.source_id], *(item for page in {loc.page for loc in trace.region.locations} for item in by_page[page])) for key, trace in traces.items()}


def _decorate_text(observations):
    by_page = defaultdict(list)
    for item in observations:
        by_page[item.locations[0].page].append(item)
    navigation = {page for page, items in by_page.items() if len(_LEADERS.findall(" ".join(item.text or "" for item in items))) >= 3}
    headers = defaultdict(set)
    header_candidates = {}
    decorated = []
    for item in observations:
        text = item.text or ""
        short = " ".join(text.split())
        location = item.locations[0]
        box = location.bbox
        heading = len(short) <= 180 and len(text.splitlines()) <= 3 and _HEADING.match(short) is not None
        number = _NUMBER.fullmatch(short) is not None and (box.y1 < location.page_height * 0.1 or box.y0 > location.page_height * 0.9)
        if location.page > 1 and box.y1 < location.page_height * 0.15 and len(short) <= 180 and not number:
            signature = re.sub(r"^\d+\s+|\s+\d+$", "", short)
            headers[signature].add(location.page)
            header_candidates[item.source_id] = signature
        decorated.append(
            replace(
                item,
                type_hint="PAGE_NUMBER" if number else "HEADING" if heading else "PARAGRAPH",
                extraction_source=DeepDocExtractionSource.DERIVED if heading else item.extraction_source,
                attributes={**item.attributes, "heading_rule_applied": heading, "source_zone": "navigation" if location.page in navigation else "body"},
            )
        )
    decorated = tuple(
        replace(item, type_hint="HEADER", extraction_source=DeepDocExtractionSource.DERIVED, attributes={**item.attributes, "source_zone": "header"})
        if item.source_id in header_candidates and len(headers[header_candidates[item.source_id]]) >= 3
        else item
        for item in decorated
    )
    return tuple(replace(item, extraction=replace(item.extraction, region=replace(item.extraction.region, source_role=_physical_role(item)))) for item in decorated)
