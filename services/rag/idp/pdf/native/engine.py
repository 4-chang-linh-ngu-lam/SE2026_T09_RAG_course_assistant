"""Compose native PDF text, figures, page facts and physical layout; never OCR."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace
from time import monotonic
from typing import Protocol, runtime_checkable, TYPE_CHECKING

from idp.evidence.contracts import (
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
from idp.pdf.native.analysis import collect_page_facts
from idp.pdf.native.budget import PdfWorkBudget
from idp.pdf.native.contracts import _fingerprint, _physical_role, bind_pdf_result
from idp.pdf.native.evidence import _EvidenceAdmissionError, admit_verification, input_fingerprint
from idp.pdf.native.extractors.figure import FigureDescriber, describe_pdf_figure, extract_pdf_figures
from idp.pdf.native.extractors.text import extract_native_text
from idp.pdf.native.geometry import bbox_in_page
from idp.pdf.native.layout import PdfLayoutPolicy, apply_pdf_layout
from idp.pdf.native.preflight import PdfAdmissionError, PdfAdmissionPolicy, PdfSource, source_scope
from idp.pdf.native.quality import PdfQualityPolicy, assess_candidate
from idp.pdf.native.reconcile import reconcile_pages
from idp.pdf.native.structures import PdfStructurePolicy, attach_native_structures
from .result import NativeExtraction, EmptyNativeError, _NativeCompletionContext, validate_idp_contracts

if TYPE_CHECKING:
    from idp.pdf.merge import PreparedExtraction


@dataclass(frozen=True, slots=True)
class PdfVerifier:
    capability: DeepDocCapability
    producer: DeepDocProducer
    independence_family: str
    resource: str = "CPU"

    def __post_init__(self):
        validate_idp_contracts((self.capability, self.producer))
        if self.resource not in {"CPU", "GPU", "REMOTE"} or not self.independence_family or self.independence_family.strip() != self.independence_family:
            raise ValueError("verifier requires an explicit resource and backend family")


@dataclass(frozen=True, slots=True)
class PdfWorkResponse:
    request_id: str
    input_sha256: str
    trace: DeepDocExtractionTrace | None = None
    reroute_to: DeepDocCapability | None = None

    def __post_init__(self):
        validate_idp_contracts((self.trace, self.reroute_to))
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
            extraction = self.extract_native(data, glyph_corrections=glyph_corrections, source=source)
            return self._finalize(
                extraction, source=source, layout_policy=layout_policy,
                structure_policy=structure_policy, quality_policy=quality_policy,
                work_limits=work_limits, runtime=runtime, verifiers=verifiers,
                figure_describer=figure_describer, reconciliation_policy=reconciliation_policy,
            )

    def extract_native(
        self, data: bytes, *, glyph_corrections=None,
        policy: PdfAdmissionPolicy | None = None, source: PdfSource | None = None,
    ) -> NativeExtraction:
        """Extract native content/facts; empty is valid. Never performs OCR.

        Pass a caller-owned PdfSource to keep one session across stages. Without
        it, this method owns and closes its session before returning detached data.
        """
        validate_idp_contracts((policy, source))
        if source is not None and policy is not None and source.policy != policy:
            raise ValueError("native extraction policy differs from the open source")
        with source_scope(data, source, policy) as source:
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
            facts = collect_page_facts(observations, diagnostics, native.report.native_producer.name, source)
            return NativeExtraction(
                data, source.report, source.policy, tuple(source.geometry.values()), facts,
                observations, figures, tuple(diagnostics), figure_status, _NativeCompletionContext(native),
            )

    def finalize(
        self, extraction: NativeExtraction, *, source: PdfSource | None = None, prepared: PreparedExtraction | None = None,
        layout_policy: PdfLayoutPolicy | None = None,
        structure_policy: PdfStructurePolicy | None = None,
        quality_policy: PdfQualityPolicy | None = None,
        work_limits: DeepDocWorkLimits | None = None,
        reconciliation_policy: DeepDocReconciliationPolicy | None = None,
    ) -> DeepDocParseResult:
        """Bind, structure, lay out, reconcile and assess native content once.

        Empty content cannot form a legacy manifest and raises the legacy error.
        No OCR/verifier/describer is invoked. The input remains reusable and
        immutable; repeated calls create equal results, never relayout a result.
        A supplied session remains owned by the caller.
        """
        if isinstance(extraction, NativeExtraction) and extraction.empty and (prepared is None or not prepared.observations):
            raise EmptyNativeError("Native extraction has no content; acquisition/merge is required before finalization")
        return self._finalize(
            extraction, source=source, prepared=prepared, layout_policy=layout_policy,
            structure_policy=structure_policy, quality_policy=quality_policy,
            work_limits=work_limits, reconciliation_policy=reconciliation_policy,
        )

    def _finalize(
        self, extraction: NativeExtraction, *, source=None, prepared=None, layout_policy=None,
        structure_policy=None, quality_policy=None, work_limits=None, runtime=None,
        verifiers=(), figure_describer=None, reconciliation_policy=None,
    ) -> DeepDocParseResult:
        if not isinstance(extraction, NativeExtraction):
            raise TypeError("finalize requires NativeExtraction")
        if prepared is not None:
            from idp.pdf.merge import PreparedExtraction, ContractViolation
            if not isinstance(prepared, PreparedExtraction) or prepared.source_sha256 != extraction.admission.source_sha256:
                raise ContractViolation("prepared source/type mismatch")
            validate_idp_contracts(prepared)
            for obs in prepared.observations:
                for loc in obs.locations:
                    if loc.page < 1 or loc.page > extraction.page_count: raise ContractViolation("prepared page out of range")
                    geometry=extraction.geometry[loc.page-1]
                    if (loc.page_width,loc.page_height)!=(geometry.width,geometry.height): raise ContractViolation("prepared geometry mismatch")
                    # Native and OCR boxes are clipped by clip_to_page at entry;
                    # anything still outside here was not produced by IDP.
                    if loc.bbox is None or not bbox_in_page((loc.bbox.x0, loc.bbox.y0, loc.bbox.x1, loc.bbox.y1), geometry.width, geometry.height): raise ContractViolation("prepared bbox invalid")
            by_id = {o.source_id:o for o in prepared.observations}
            for original in (*extraction.observations,*extraction.figures):
                current = by_id.get(original.source_id)
                if current is None or replace(current, extraction=original.extraction) != original:
                    raise ContractViolation("prepared native observation rewrite")
                before, after = original.extraction, current.extraction
                if (before.region,before.raw_candidate_id,before.source_candidate_id)!=(after.region,after.raw_candidate_id,after.source_candidate_id):
                    raise ContractViolation("prepared source candidate rewrite")
                for name in ("evidence","candidates","decisions"):
                    values=getattr(before,name)
                    if getattr(after,name)[:len(values)]!=values: raise ContractViolation("prepared evidence rewrite")
        if extraction.empty and (prepared is None or not prepared.observations):
            raise ValueError("PDF has no extractable native text or figures; Plain Text ingestion never falls back to OCR")
        validate_idp_contracts(extraction)
        for option in (source, layout_policy, structure_policy, quality_policy, work_limits, verifiers, reconciliation_policy):
            validate_idp_contracts(option)
        data = extraction.data
        with source_scope(data, source, extraction.policy) as source:
            if source.report != extraction.admission:
                raise ValueError("finalization source admission does not match native extraction")
            native = extraction._completion.text
            observations, figures = extraction.observations, extraction.figures
            diagnostics, figure_status = extraction.diagnostics, extraction.figure_status
            merged = prepared.observations if prepared is not None else (*observations,*figures)
            diagnostics = prepared.diagnostics if prepared is not None else diagnostics
            observations = tuple(replace(item, order=index) for index, item in enumerate(merged))
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
                    "ocr_used": any(item.extraction_source.value == "OCR" for item in observations),
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
            if prepared is not None and prepared.acquisitions:
                from idp.evidence.serde import dump as dump_acquisition
                parsed = replace(parsed, attributes={**parsed.attributes,"ocr_proposals":tuple({"record_json":dump_acquisition(a),"artifact":a.artifact_ref,"sha256":a.artifact_sha256,"render_id":a.frame.render_id,"blocks":tuple({"key":b.key,"payload":b.payload,"confidence":b.confidence} for b in a.blocks)} for a in prepared.acquisitions)})
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
            bound = replace(bound, manifest=replace(bound.manifest, admission=extraction.admission, pages=extraction.pages))
            bound = apply_pdf_layout(bound, policy=layout_policy, check_deadline=source.check_deadline)
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
        validate_idp_contracts(parsed)
        validate_idp_contracts(reconciliation_policy)
        validate_idp_contracts(kwargs)
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
                        from idp.pdf.native.evidence import admit_description

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
        scoped = _scoped_findings(traces, findings, narrow=quality_policy.scoped_findings)
        assessments = []
        for region_id, initial in tuple(traces.items()):
            queue = deque(c.id for c in initial.candidates)
            reasons = {}
            while queue:
                candidate_id = queue.popleft()
                trace = traces[region_id]
                candidate = next(c for c in trace.candidates if c.id == candidate_id)
                assessment = assess_candidate(trace, candidate, scoped[region_id], policy=quality_policy)
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


def _scoped_findings(traces, findings, *, narrow=False):
    by_source, by_page, document = defaultdict(list), defaultdict(list), []
    targets = {}
    if narrow:
        from idp.pdf.native.scoping import finding_targets

        texts = defaultdict(list)
        for trace in traces.values():
            raw = next(c for c in trace.candidates if c.id == trace.raw_candidate_id)
            for page in {loc.page for loc in trace.region.locations}:
                texts[page].append((trace.region.source_id, raw.text or ""))
        targets = finding_targets(findings, texts)
    for finding in findings:
        target = targets.get(finding.id)
        if target is not None:
            for source_id in target:
                by_source[source_id].append(finding)
        elif finding.scope == "REGION":
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
        # Running headers (top 15%) and running footers (bottom 10%) are
        # page furniture only when the same signature repeats on >= 3 pages.
        zone = "header" if box.y1 < location.page_height * 0.15 else "footer" if box.y0 > location.page_height * 0.9 else None
        # Page 1 is left to publication (see publication.FURNITURE_ROLES) so
        # native records stay equivalent to the relocated Parser engine.
        if zone and location.page > 1 and len(short) <= 180 and not number:
            signature = (zone, re.sub(r"^\d+\s+|\s+\d+$", "", short))
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
        replace(
            item,
            type_hint=header_candidates[item.source_id][0].upper(),
            extraction_source=DeepDocExtractionSource.DERIVED,
            attributes={**item.attributes, "source_zone": header_candidates[item.source_id][0]},
        )
        if item.source_id in header_candidates and len(headers[header_candidates[item.source_id]]) >= 3
        else item
        for item in decorated
    )
    return tuple(replace(item, extraction=replace(item.extraction, region=replace(item.extraction.region, source_role=_physical_role(item)))) for item in decorated)
