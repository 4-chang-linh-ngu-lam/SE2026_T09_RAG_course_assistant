"""Offline metrics for QAS-06 (QA) and quiz quality (§8).

These functions only aggregate labelled outcomes; they never claim a KPI. A
report is meaningful only with the real model/config recorded alongside it and
human (or calibrated-judge) labels.
"""
from __future__ import annotations


def _ratio(numerator, denominator):
    return None if not denominator else round(numerator / denominator, 4)


def qa_report(cases) -> dict:
    """``cases``: dicts with
    ``answerable`` (bool, gold), ``status`` (engine output),
    ``citations``: list of ``{"supports": bool, "class_ok": bool}`` (human labels),
    ``claims``: list of ``{"basis": "source"|"general", "grounded": bool}``.
    """
    cases = list(cases)
    citations = [c for case in cases for c in case.get("citations", [])]
    source_claims = [c for case in cases for c in case.get("claims", []) if c.get("basis") == "source"]
    unanswerable = [c for c in cases if not c["answerable"]]
    answerable = [c for c in cases if c["answerable"]]
    return {
        "cases": len(cases),
        "citation_accuracy": _ratio(sum(c["supports"] for c in citations), len(citations)),
        "groundedness": _ratio(sum(c["grounded"] for c in source_claims), len(source_claims)),
        "correct_refusal_rate": _ratio(sum(c["status"] == "insufficient_evidence" for c in unanswerable),
                                       len(unanswerable)),
        "false_refusal_rate": _ratio(sum(c["status"] == "insufficient_evidence" for c in answerable),
                                     len(answerable)),
        "cross_class_leaks": sum(not c.get("class_ok", True) for c in citations),
        "thresholds_qas06": {"citation_accuracy": 0.9, "groundedness": 0.9, "correct_refusal_rate": 0.9,
                             "cross_class_leaks": 0},
    }


def quiz_report(drafts, audits=()) -> dict:
    """``drafts``: job drafts after teacher review; ``audits``: manual audit labels
    ``{"draft_id", "key_correct": bool}`` on a sample of PASSED/FLAGGED items."""
    drafts = list(drafts)
    reviewed = [d for d in drafts if d["status"] in ("ACCEPTED", "EDITED_ACCEPTED", "REJECTED", "EXPORTED")]
    accepted_clean = [d for d in reviewed if d["status"] in ("ACCEPTED", "EXPORTED")
                      and not d.get("edited_after_generation")]
    by_id = {d["id"]: d for d in drafts}
    audits = list(audits)
    wrong = [a for a in audits if not a["key_correct"]]
    wrong_unflagged = [a for a in wrong if by_id.get(a["draft_id"], {}).get("status_at_generation",
                       by_id.get(a["draft_id"], {}).get("status")) == "PASSED"]
    flagged = [a for a in audits if by_id.get(a["draft_id"], {}).get("flags")]
    reasons = {}
    for draft in drafts:
        if draft.get("review_reason"):
            reasons[draft["review_reason"]] = reasons.get(draft["review_reason"], 0) + 1
    return {
        "items": len(drafts),
        "accepted_without_edit_rate": _ratio(len(accepted_clean), len(reviewed)),
        "audited": len(audits),
        "wrong_key_rate": _ratio(len(wrong), len(audits)),
        "wrong_key_passed_unflagged": len(wrong_unflagged),
        "flag_precision": _ratio(sum(not a["key_correct"] for a in flagged), len(flagged)),
        "flag_recall": _ratio(len(wrong) - len(wrong_unflagged), len(wrong)),
        "reject_reasons": dict(sorted(reasons.items())),
        # Release gate (§8.2): no audited PASSED item may have a wrong key.
        "release_gate_ok": bool(audits) and not wrong_unflagged,
    }
