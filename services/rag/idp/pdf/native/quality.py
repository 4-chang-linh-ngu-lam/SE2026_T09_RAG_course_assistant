"""Conservative, versioned candidate gate; acceptance is scoped to evidence."""

from dataclasses import asdict, dataclass

from idp.evidence.contracts import DeepDocCapability, DeepDocContentOrigin, DeepDocDecisionAction, DeepDocGateAssessment
from idp.pdf.native.contracts import _fingerprint
from idp.pdf.native.evidence import evidence_family


QUALITY_GATE_VERSIONS = ("pdf-quality-gate:1", "pdf-quality-gate:2", "pdf-quality-gate:3")


@dataclass(frozen=True, slots=True)
class PdfQualityPolicy:
    """``pdf-quality-gate:2`` accepts new OCR regions as transcriptions.

    ``pdf-quality-gate:3`` keeps version 2 and scopes glyph/font findings to
    the native regions that can contain the affected glyph
    (``idp.pdf.native.scoping``) instead of every region of their page.
    """

    version: str = "pdf-quality-gate:1"

    def __post_init__(self):
        if self.version not in QUALITY_GATE_VERSIONS:
            raise ValueError("unsupported PDF quality policy")

    @property
    def scoped_findings(self):
        return self.version == "pdf-quality-gate:3"

    @property
    def fingerprint(self):
        return _fingerprint(asdict(self))


def assess_candidate(trace, candidate, findings=(), *, policy=None):
    evidence = [item for item in trace.evidence if item.id in candidate.evidence_ids]
    families = tuple(sorted({evidence_family(item) for item in evidence}))
    capability = (
        DeepDocCapability.FIGURE
        if candidate.figure or trace.figure
        else DeepDocCapability.TABLE
        if candidate.table
        else DeepDocCapability.MATH
        if candidate.formula
        else DeepDocCapability(trace.region.labels[0].value)
    )
    action, reason = "UNRESOLVED", "UNSUPPORTED_EVIDENCE"
    if candidate.origin == DeepDocContentOrigin.MODEL_INFERENCE:
        action, reason = "VERIFY", "MODEL_INFERENCE_REQUIRES_SOURCE_PROOF"
    elif capability == DeepDocCapability.MATH:
        action, reason = "VERIFY", "MATH_SYMBOL_STRUCTURE_UNVERIFIED"
    elif capability == DeepDocCapability.TABLE:
        action, reason = "VERIFY", "TABLE_CELLS_HEADERS_UNVERIFIED"
    elif capability == DeepDocCapability.FIGURE:
        assets = {key for item in evidence for key in item.asset_ids}
        action, reason = ("ACCEPT", "SOURCE_FIGURE_ASSET_CONTEXT_ONLY") if assets else ("UNRESOLVED", "SOURCE_CROP_UNAVAILABLE")
    elif policy is not None and policy.version != "pdf-quality-gate:1" and trace.region.source_id.startswith("ocr:") and candidate.id == trace.source_candidate_id:
        # Native NO_TEXT/glyph findings do not invalidate a new OCR region.
        # ACCEPT preserves transcription only; publication separately requires
        # measured confidence and rejects overlaps/unresolved page state.
        action, reason = "ACCEPT", "OCR_TRANSCRIPTION_PRESERVED_NOT_SOURCE_PROOF"
    elif candidate.id == trace.source_candidate_id:
        proof = any(item.review or item.glyph_proofs for item in evidence)
        suspect = any(item.status in {"SUSPECT", "CONFLICT"} for item in findings)
        if proof:
            action, reason = "ACCEPT", "EXACT_SOURCE_BOUND_TEXT_PROOF"
        elif suspect:
            action, reason = "VERIFY", "SOURCE_TEXT_FINDINGS_UNRESOLVED"
        else:
            action, reason = "ACCEPT", "SOURCE_TRANSCRIPTION_PRESERVED_NOT_LEXICALLY_VERIFIED"
    elif any(item.review or item.glyph_proofs for item in evidence):
        # A competing evidenced correction is not selected without resolving conflict.
        action, reason = "UNRESOLVED", "ALTERNATIVE_SOURCE_PROOF_NOT_SELECTED"
    else:
        action, reason = "UNRESOLVED", "BACKEND_AGREEMENT_IS_NOT_SOURCE_PROOF"
    return DeepDocGateAssessment(
        trace.region.id,
        candidate.id,
        capability,
        DeepDocDecisionAction(action),
        (reason,),
        candidate.evidence_ids,
        families,
        (False,) * (len(candidate.figure.claims) if candidate.figure else 0),
    )
