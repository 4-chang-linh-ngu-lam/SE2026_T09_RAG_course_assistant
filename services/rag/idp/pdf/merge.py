"""Source-preserving OCR merge before manifest binding/layout."""

import unicodedata
from dataclasses import dataclass, replace, asdict

from idp.evidence.contracts import (
    DeepDocBoundingBox,
    DeepDocCandidate,
    DeepDocContentOrigin,
    DeepDocDiagnostic,
    DeepDocEvidence,
    DeepDocExtractionSource,
    DeepDocObservation,
    DeepDocObservationKind,
    DeepDocSourceLocation,
)

from .acquire import AcquisitionResult
from .geometry import corners
from .native.contracts import _fingerprint, _source_trace
from .native.geometry import clip_to_page
from .native.result import NativeExtraction, validate_idp_contracts


class ContractViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedExtraction:
    source_sha256: str
    observations: tuple[DeepDocObservation, ...]
    acquisitions: tuple[AcquisitionResult, ...] = ()
    diagnostics: tuple[DeepDocDiagnostic, ...] = ()

    def __post_init__(self):
        validate_idp_contracts(self)
        for name in ("observations", "acquisitions", "diagnostics"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        from .render import sha

        sha(self.source_sha256)
        seen = set()
        for obs in self.observations:
            if not isinstance(obs, DeepDocObservation) or obs.extraction is None:
                raise ContractViolation("complete IDP traces required")
            trace = obs.extraction
            for identity in (
                obs.source_id,
                trace.region.id,
                *(e.id for e in trace.evidence),
                *(c.id for c in trace.candidates),
                *(d.id for d in trace.decisions),
            ):
                if identity in seen:
                    raise ContractViolation("duplicate source/evidence identity")
                seen.add(identity)
            if any(e.source_sha256 != self.source_sha256 for e in trace.evidence):
                raise ContractViolation("source SHA mismatch")


def overlap(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = ix * iy
    aa = (a[2] - a[0]) * (a[3] - a[1])
    bb = (b[2] - b[0]) * (b[3] - b[1])
    return area / (aa + bb - area) if area else 0, area / min(aa, bb) if area else 0


def box_of(loc):
    return (loc.bbox.x0, loc.bbox.y0, loc.bbox.x1, loc.bbox.y1)


def comparable_text(text):
    """NFC text without whitespace: the exact-agreement comparison key."""
    return "".join(unicodedata.normalize("NFC", text or "").split())


class EvidenceMerger:
    def merge(
        self,
        native: NativeExtraction,
        acquisitions=(),
        verifications=(),
        *,
        ocr_primary_pages=frozenset(),
    ):
        """Merge OCR into native evidence.

        ``ocr_primary_pages`` are pages whose native text layer was judged
        unusable (route ``OCR_PAGE`` although native text exists). There, OCR
        lines that reproduce a native region exactly are still attached to it
        as an independent verification; OCR that disagrees becomes its own OCR
        observation, with its recognition confidence, instead of an
        alternative candidate that publication can never select (IDP-004).
        """
        try:
            prepared = self._merge(
                native, acquisitions, frozenset(ocr_primary_pages)
            )
            observations = list(prepared.observations)
            from .native.engine import PdfWorkResponse
            from .native.evidence import admit_verification

            for response in verifications:
                validate_idp_contracts(response)
                if not isinstance(response, PdfWorkResponse) or response.trace is None:
                    raise ContractViolation("verification evidence required")
                matches = [
                    i
                    for i, o in enumerate(observations)
                    if o.extraction.region.id == response.trace.region.id
                ]
                if len(matches) != 1:
                    raise ContractViolation("verification target missing")
                i = matches[0]
                original = observations[i].extraction
                new = response.trace.evidence[len(original.evidence) :]
                if not new:
                    raise ContractViolation("verification has no new evidence")
                admit_verification(
                    original,
                    response.trace,
                    new[0].producer,
                    new[0].independence_family,
                )
                observations[i] = replace(observations[i], extraction=response.trace)
            return replace(prepared, observations=tuple(observations))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ContractViolation(str(exc)) from exc

    def _merge(self, native, acquisitions, ocr_primary_pages=frozenset()):
        validate_idp_contracts((native, acquisitions))
        if not isinstance(native, NativeExtraction):
            raise TypeError("NativeExtraction required")
        observations = [*native.observations, *native.figures]
        diagnostics = list(native.diagnostics)
        # Native text indices per page: each OCR block is matched against its
        # own page only (previously every block scanned the whole document).
        native_by_page = {}
        for i, obs in enumerate(observations[: len(native.observations)]):
            native_by_page.setdefault(obs.locations[0].page, []).append(i)
        unique = {}
        for result in acquisitions:
            if not isinstance(result, AcquisitionResult):
                raise TypeError("typed acquisition required")
            key = (result.frame.render_id, result.producer, result.attempt)
            if key in unique and unique[key] != result:
                raise ContractViolation("duplicate attempt payload conflict")
            unique[key] = result
        # native index -> [(result, block, box, polygon, identity)]; OCR on
        # OCR-primary pages is resolved once every reading of a region is seen.
        deferred = {}
        standalone = []
        for result in unique.values():
            frame = result.frame
            if (
                frame.source_sha256 != native.admission.source_sha256
                or frame.page > native.page_count
            ):
                raise ContractViolation("acquisition source/page mismatch")
            g = native.geometry[frame.page - 1]
            if tuple(frame.geometry) != (g.width, g.height, g.crop_box, g.rotation):
                raise ContractViolation("render geometry mismatch")
            diagnostics.extend(result.diagnostics)
            for block in result.blocks:
                w, h = frame.steps[-1].output_size
                if (
                    block.bbox_px[0] < 0
                    or block.bbox_px[1] < 0
                    or block.bbox_px[2] > w
                    or block.bbox_px[3] > h
                ):
                    raise ContractViolation("OCR bbox outside image")
                polygon = frame.polygon_to_pdf(corners(block.bbox_px))
                pt = frame.to_pdf_pt(block.bbox_px)
                # Same page-frame policy as native extraction. The pixel box
                # is already inside the rendered frame, so only transform
                # rounding can leave the page; a degenerate result is a
                # broken transform and stays a contract violation.
                normalized, _ = clip_to_page(pt, g.width, g.height)
                if normalized is None:
                    raise ContractViolation("OCR bbox outside PDF")
                targets = []
                partial_overlap = False
                for i in native_by_page.get(frame.page, ()):
                    obs = observations[i]
                    loc = obs.locations[0]
                    if loc.bbox is None:
                        continue
                    iou, coverage = overlap(normalized, box_of(loc))
                    partial_overlap = partial_overlap or iou > 0
                    if (obs.extraction.region.id == block.target_region_id and coverage > 0) or (
                        block.target_region_id is None
                        and (iou >= 0.5 or coverage >= 0.9)
                    ):
                        targets.append(i)
                if block.target_region_id is not None and len(targets) != 1:
                    raise ContractViolation("reread target missing or wrong page")
                material = [
                    frame.source_sha256,
                    frame.page,
                    frame.render_id,
                    result.family,
                    asdict(result.producer),
                    block.key,
                    result.config_sha256,
                    result.artifact_sha256,
                ]
                identity = _fingerprint(material)
                primary = frame.page in ocr_primary_pages
                if primary and len(targets) == 1 and block.target_region_id is None:
                    deferred.setdefault(targets[0], []).append(
                        (result, block, normalized, polygon, identity)
                    )
                    continue
                if len(targets) == 1:
                    index = targets[0]
                    obs = observations[index]
                    trace = obs.extraction
                    ev = DeepDocEvidence(
                        "evidence:ocr:" + identity,
                        trace.region.id,
                        DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
                        result.producer,
                        result.artifact_sha256,
                        frame.source_sha256,
                        independence_family=result.family,
                    )
                    candidate = DeepDocCandidate(
                        "candidate:ocr:" + identity,
                        trace.region.id,
                        ev.origin,
                        result.producer,
                        (ev.id,),
                        block.text,
                    )
                    observations[index] = replace(
                        obs,
                        extraction=replace(
                            trace,
                            evidence=(*trace.evidence, ev),
                            candidates=(*trace.candidates, candidate),
                        ),
                    )
                else:
                    # On OCR-primary pages the native layer is already known
                    # to be unusable, so overlapping it is not ambiguity;
                    # publication still refuses duplicates of selected text.
                    standalone.append(
                        (
                            result,
                            block,
                            normalized,
                            polygon,
                            identity,
                            not primary and (bool(targets) or partial_overlap),
                        )
                    )
        for index, items in sorted(deferred.items()):
            obs = observations[index]
            readings = {}
            for result, block, *_ in items:
                readings.setdefault(result.artifact_sha256, []).append(block.text)
            target = comparable_text(obs.text)
            if not target or not any(
                comparable_text("".join(lines)) == target
                for lines in readings.values()
            ):
                standalone.extend((*item, False) for item in items)
                continue
            # Exact independent agreement: attach as verification evidence.
            trace = obs.extraction
            for result, block, _box, _polygon, identity in items:
                ev = DeepDocEvidence(
                    "evidence:ocr:" + identity,
                    trace.region.id,
                    DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
                    result.producer,
                    result.artifact_sha256,
                    result.frame.source_sha256,
                    independence_family=result.family,
                )
                candidate = DeepDocCandidate(
                    "candidate:ocr:" + identity,
                    trace.region.id,
                    ev.origin,
                    result.producer,
                    (ev.id,),
                    block.text,
                )
                trace = replace(
                    trace,
                    evidence=(*trace.evidence, ev),
                    candidates=(*trace.candidates, candidate),
                )
            observations[index] = replace(obs, extraction=trace)
        for result, block, normalized, polygon, identity, review in standalone:
            frame = result.frame
            g = native.geometry[frame.page - 1]
            attrs = {
                "ocr_used": True,
                "recognition": {
                    "frame": frame.render_id,
                    "artifact": result.artifact_ref,
                    "sha256": result.artifact_sha256,
                    "confidence": block.confidence,
                    "pixel_bbox": block.bbox_px,
                    "polygon_pt": polygon,
                    "payload": block.payload,
                    "family": result.family,
                    "model": result.producer.model,
                    "config_sha256": result.config_sha256,
                },
                "matching_review": review,
            }
            if review:
                diagnostics.append(
                    DeepDocDiagnostic(
                        "OCR_MATCH_AMBIGUOUS",
                        "OCR overlaps multiple native regions; retained for review",
                        metadata={"page": frame.page},
                    )
                )
            obs = DeepDocObservation(
                "ocr:" + identity,
                len(observations),
                DeepDocObservationKind.TEXT,
                block.text,
                DeepDocExtractionSource.OCR,
                block.label,
                locations=(
                    DeepDocSourceLocation(
                        frame.page,
                        g.width,
                        g.height,
                        DeepDocBoundingBox(*normalized),
                    ),
                ),
                attributes=attrs,
            )
            observations.append(
                replace(
                    obs,
                    extraction=_source_trace(obs, frame.source_sha256, result.producer),
                )
            )
        return PreparedExtraction(
            native.admission.source_sha256,
            tuple(observations),
            tuple(unique.values()),
            tuple(diagnostics),
        )
