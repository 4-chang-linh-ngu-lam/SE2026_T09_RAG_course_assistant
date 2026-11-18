"""Acquisition contracts independent of existing extraction traces."""

from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from idp.evidence.contracts import (
    DeepDocDiagnostic,
    DeepDocProducer,
    _freeze_json_object,
)

from .geometry import corners
from .native.result import validate_idp_contracts
from .render import ImageFrame, sha


@dataclass(frozen=True, slots=True)
class OcrBlock:
    key: str
    text: str
    bbox_px: tuple[float, float, float, float]
    confidence: float
    label: str = "PARAGRAPH"
    target_region_id: str | None = None
    payload: object = None

    def __post_init__(self):
        corners(self.bbox_px)
        if not self.key or not self.text.strip() or not 0 <= self.confidence <= 1:
            raise ValueError("invalid OCR block")
        object.__setattr__(self, "bbox_px", tuple(self.bbox_px))
        object.__setattr__(self, "payload", _freeze_json_object(self.payload or {}))


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    frame: ImageFrame
    producer: DeepDocProducer
    family: str
    config_sha256: str
    artifact_ref: str
    artifact_sha256: str
    blocks: tuple[OcrBlock, ...] = ()
    diagnostics: tuple[DeepDocDiagnostic, ...] = ()
    attempt: str = "attempt:1"
    success: bool = True

    def __post_init__(self):
        validate_idp_contracts(self)
        sha(self.config_sha256)
        sha(self.artifact_sha256)
        if not isinstance(self.frame, ImageFrame) or not isinstance(
            self.producer, DeepDocProducer
        ):
            raise TypeError("IDP acquisition types required")
        if not self.family or not self.artifact_ref or not self.attempt:
            raise ValueError("missing acquisition provenance")
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not self.success and self.blocks:
            raise ValueError("failed attempt cannot publish blocks")
        if len({b.key for b in self.blocks}) != len(self.blocks):
            raise ValueError("duplicate OCR region identity")


def group_paragraphs(result, *, isolate=None, keep_whole=None):
    """Merge Tesseract line blocks into Tesseract's own paragraphs.

    Tesseract keys are ``page:block:par:line``; lines sharing the first three
    parts are one paragraph of its layout analysis. Used for pages with no
    native text only: a scanned page otherwise publishes one block -- and one
    retrieval chunk -- per printed line. The raw artifact is unchanged; the
    paragraph is a deterministic regrouping of the same recognized words.
    Results whose keys are not Tesseract line keys are returned unchanged.

    ``isolate(line) -> bool`` (``tesseract-paragraph:2``) keeps a line on its
    own and splits its paragraph around it. With
    ``idp.pdf.ocr_tokens.isolate_suspect_line`` one misread formula token
    withholds its own line instead of the whole paragraph. A paragraph for
    which ``keep_whole(lines)`` holds (``ocr_tokens.numeric_block``: a table
    or data series) is never split, so it is withheld as a whole.
    """
    from dataclasses import replace

    groups = {}
    for block in result.blocks:
        parts = block.key.split(":")
        if len(parts) != 4 or block.target_region_id is not None:
            return result
        groups.setdefault(":".join(parts[:3]), []).append(block)
    if isolate is not None:
        split = {}
        for key, lines in groups.items():
            if keep_whole is not None and keep_whole(lines):
                split[key] = lines
                continue
            segments, current = [], []
            for line in lines:
                if isolate(line):
                    if current:
                        segments.append(current)
                    segments.append([line])
                    current = []
                else:
                    current.append(line)
            if current:
                segments.append(current)
            if len(segments) == 1:
                split[key] = segments[0]
            else:
                for number, segment in enumerate(segments):
                    split[f"{key}/{number}"] = segment
        groups = split
    merged = []
    for key, lines in groups.items():
        weights = [max(1, len(line.text)) for line in lines]
        words = tuple(
            word for line in lines for word in (line.payload.get("words") or ())
        )
        payload = {
            "words": words,
            "lines": len(lines),
            "grouping": "tesseract-paragraph:1"
            if isolate is None
            else "tesseract-paragraph:2",
        }
        # Lines split at a column gutter (``idp.pdf.columns``) share one run
        # and column path per paragraph key; the layout reads this hint.
        runs = [line.payload.get("column_run") for line in lines]
        if any(runs):
            if not all(runs) or len(
                {(r["run"], tuple(r["path"]), tuple(r["channel_px"])) for r in runs}
            ) != 1:
                raise ValueError("paragraph mixes column runs")
            run = dict(lines[0].payload["column_run"])
            run.pop("source_line", None)
            run["source_lines"] = [
                line.payload["column_run"]["source_line"] for line in lines
            ]
            payload["column_run"] = run
        merged.append(
            OcrBlock(
                key,
                "\n".join(line.text for line in lines),
                (
                    min(line.bbox_px[0] for line in lines),
                    min(line.bbox_px[1] for line in lines),
                    max(line.bbox_px[2] for line in lines),
                    max(line.bbox_px[3] for line in lines),
                ),
                sum(w * line.confidence for w, line in zip(weights, lines))
                / sum(weights),
                payload=payload,
            )
        )
    return replace(result, blocks=tuple(merged))


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    key: str
    frame: ImageFrame
    regions: tuple[tuple[float, float, float, float], ...] = ()


class OcrAcquirer(Protocol):
    def acquire_page(
        self, source, page: int, plan: AcquisitionRequest, *, deadline: float
    ) -> AcquisitionResult: ...
    def acquire_regions(
        self, source, page: int, regions: AcquisitionRequest, *, deadline: float
    ) -> AcquisitionResult: ...


class BackendAcquirer:
    """Opt-in executor for an explicitly supplied acquisition backend."""

    def __init__(self, backend, ledger, *, render_precharged=False, resource="CPU"):
        self.backend, self.ledger = backend, ledger
        self.render_precharged = render_precharged
        self.resource = resource

    def acquire_page(self, source, page, plan, *, deadline):
        if (
            plan.frame.source_sha256 != source.report.source_sha256
            or plan.frame.page != page
        ):
            raise ValueError("acquisition source mismatch")
        source.check_deadline()
        if monotonic() >= deadline:
            raise TimeoutError("acquisition deadline")
        w, h = plan.frame.steps[-1].output_size
        self.ledger.reserve(
            plan.key,
            pixels=0 if self.render_precharged else w * h,
            regions=len(plan.regions),
            page=page,
            resource=self.resource,
        )
        ok = False
        try:
            result = self.backend(source, page, plan, deadline=deadline)
            if not isinstance(result, AcquisitionResult) or result.frame != plan.frame:
                raise ValueError("invalid backend acquisition result")
            if monotonic() >= min(deadline, self.ledger.deadline):
                raise TimeoutError("acquisition exceeded deadline")
            ok = result.success
            return result
        finally:
            self.ledger.settle(plan.key, ok)

    def acquire_regions(self, source, page, regions, *, deadline):
        return self.acquire_page(source, page, regions, deadline=deadline)
