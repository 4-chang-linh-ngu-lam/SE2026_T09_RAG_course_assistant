"""Evidence families and source-preserving verifier admission."""

from idp.evidence.contracts import DeepDocContentOrigin, _work_input_fingerprint


class _EvidenceAdmissionError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def evidence_family(evidence):
    if evidence.independence_family is not None:
        return evidence.independence_family
    if evidence.origin == DeepDocContentOrigin.MODEL_INFERENCE:
        return "unknown"
    name = evidence.producer.name
    if name == "pypdfium2":
        return "pdfium"
    if name == "poppler-pdftotext":
        return "poppler"
    if name in {"font-glyph-recovery", "pypdf-font-inspector"}:
        return "pdf-font-program"
    if name == "reviewed-native-correction":
        return "source-review"
    return "unknown"


def input_fingerprint(trace, candidate, configuration_sha256, policy_sha256):
    return _work_input_fingerprint(trace, candidate.id, configuration_sha256, policy_sha256)


def admit_verification(original, updated, producer, family):
    """A verifier may append alternatives, never rewrite source or earlier proof."""
    if (updated.region, updated.raw_candidate_id, updated.source_candidate_id, updated.figure) != (original.region, original.raw_candidate_id, original.source_candidate_id, original.figure):
        raise _EvidenceAdmissionError("SOURCE_IDENTITY_CONFLICT")
    if updated.decisions != original.decisions:
        raise _EvidenceAdmissionError("VERIFIER_DECISION_NOT_ALLOWED")
    for name in ("evidence", "candidates", "decisions"):
        before = getattr(original, name)
        if getattr(updated, name)[: len(before)] != before:
            raise _EvidenceAdmissionError("EXISTING_EVIDENCE_REWRITE")
    evidence = updated.evidence[len(original.evidence) :]
    candidates = updated.candidates[len(original.candidates) :]
    if len(evidence) > 32 or len(candidates) > 16 or sum(len(item.text or "") for item in candidates) > 65536:
        raise _EvidenceAdmissionError("RESPONSE_LIMIT_EXCEEDED")
    if not evidence or not candidates:
        raise _EvidenceAdmissionError("EMPTY_VERIFICATION_EVIDENCE")
    source_sha = original.evidence[0].source_sha256
    if any(item.producer != producer or item.independence_family != family or item.source_sha256 != source_sha for item in evidence):
        raise _EvidenceAdmissionError("EVIDENCE_IDENTITY_CONFLICT")
    new_ids = {item.id for item in evidence}
    if any(item.producer != producer or not set(item.evidence_ids) & new_ids for item in candidates):
        raise _EvidenceAdmissionError("CANDIDATE_IDENTITY_CONFLICT")
    return updated


def admit_description(original, updated, producer):
    if (updated.region, updated.raw_candidate_id, updated.source_candidate_id, updated.figure) != (original.region, original.raw_candidate_id, original.source_candidate_id, original.figure):
        raise _EvidenceAdmissionError("SOURCE_IDENTITY_CONFLICT")
    for name in ("evidence", "candidates", "decisions"):
        before = getattr(original, name)
        if getattr(updated, name)[: len(before)] != before:
            raise _EvidenceAdmissionError("EXISTING_EVIDENCE_REWRITE")
    candidates = updated.candidates[len(original.candidates) :]
    evidence = updated.evidence[len(original.evidence) :]
    if len(candidates) != 1 or len(evidence) != 1 or candidates[0].figure is None:
        raise _EvidenceAdmissionError("INVALID_DESCRIPTION_RESPONSE")
    for item in (*candidates, *evidence):
        if item.origin != DeepDocContentOrigin.MODEL_INFERENCE or (item.producer.name, item.producer.version, item.producer.model) != (producer.name, producer.version, producer.model):
            raise _EvidenceAdmissionError("EVIDENCE_IDENTITY_CONFLICT")
    if evidence[0].source_sha256 != original.evidence[0].source_sha256 or candidates[0].evidence_ids != (evidence[0].id,):
        raise _EvidenceAdmissionError("SOURCE_REFERENCE_CONFLICT")
    decisions = updated.decisions[len(original.decisions) :]
    if len(decisions) != 1 or decisions[0].candidate_id != candidates[0].id or decisions[0].action.value != "UNRESOLVED":
        raise _EvidenceAdmissionError("VERIFIER_DECISION_NOT_ALLOWED")
    return updated
