"""Draft item lifecycle and the export payload for Learning (D1, §5.8).

AI-generated items stay drafts until a teacher accepts them; only ACCEPTED or
EDITED_ACCEPTED items may be exported. These are pure functions over plain
dicts: persistence, the reviewer's permission check and the Learning import API
belong to the AI service (TASK-018) and Learning (TASK-019), whose contracts are
not yet approved. The payload below is a PROPOSAL to agree with Learning.
"""
from __future__ import annotations

from ...contracts.errors import ContractError
from . import items as item_contracts

GENERATED, PASSED, FLAGGED, REJECTED_AUTO = "GENERATED", "PASSED", "FLAGGED", "REJECTED_AUTO"
ACCEPTED, EDITED_ACCEPTED, REJECTED, REGENERATE = "ACCEPTED", "EDITED_ACCEPTED", "REJECTED", "REGENERATE"
EXPORT_PENDING, EXPORTED, BLOCKED = "EXPORT_PENDING", "EXPORTED", "BLOCKED"

REJECT_REASONS = ("wrong_key", "ambiguous", "off_curriculum", "too_easy", "too_hard", "language",
                  "duplicate", "unsupported_by_source", "other")

TRANSITIONS = {
    GENERATED: {PASSED, FLAGGED, REJECTED_AUTO},
    PASSED: {ACCEPTED, EDITED_ACCEPTED, REJECTED, REGENERATE, BLOCKED},
    FLAGGED: {ACCEPTED, EDITED_ACCEPTED, REJECTED, REGENERATE, BLOCKED},
    REJECTED_AUTO: {REGENERATE, REJECTED},
    REGENERATE: {GENERATED},
    ACCEPTED: {EXPORT_PENDING, BLOCKED, REJECTED},
    EDITED_ACCEPTED: {EXPORT_PENDING, BLOCKED, REJECTED},
    EXPORT_PENDING: {EXPORTED, BLOCKED},
    REJECTED: set(), EXPORTED: set(), BLOCKED: set(),
}


def transition(draft: dict, new_status: str, **fields) -> dict:
    if new_status not in TRANSITIONS.get(draft["status"], set()):
        raise ValueError(f"invalid_transition:{draft['status']}->{new_status}")
    return {**draft, **fields, "status": new_status}


def review(draft: dict, decision: str, *, reviewer_id: str, reason: str | None = None,
           edited_item: dict | None = None) -> dict:
    """Apply a teacher decision: accept | edit | reject | regenerate."""
    if not reviewer_id:
        raise ValueError("reviewer_required")
    if decision == "accept":
        return transition(draft, ACCEPTED, reviewer_id=reviewer_id)
    if decision == "reject":
        if reason not in REJECT_REASONS:
            raise ValueError("reject_reason_required")
        return transition(draft, REJECTED, reviewer_id=reviewer_id, review_reason=reason)
    if decision == "regenerate":
        return transition(draft, REGENERATE, reviewer_id=reviewer_id, review_reason=reason)
    if decision == "edit":
        checked = validate_edit(draft["item"], edited_item)
        return transition(draft, EDITED_ACCEPTED, reviewer_id=reviewer_id, item=checked,
                          original_item=draft["item"], edited_after_generation=True)
    raise ValueError("invalid_decision")


def validate_edit(original: dict, edited: dict | None) -> dict:
    """Re-run the structural rules on a teacher edit; evidence stays as generated.

    The teacher owns edited content; the citation still points to the source the
    item was generated from and is marked ``edited_after_generation`` on export.
    """
    if not isinstance(edited, dict) or edited.get("type") != original["type"]:
        raise ContractError("edit_type_mismatch")
    item_type = original["type"]
    texts = []
    if item_type in ("single_choice", "multiple_choice"):
        correct = [edited.get("correct_answer")] if item_type == "single_choice" else edited.get("correct_answers")
        if not isinstance(correct, list) or not all(isinstance(c, str) and c.strip() for c in correct):
            raise ContractError("edit_invalid_key")
        if item_type == "multiple_choice" and len(correct) < 2:
            raise ContractError("edit_invalid_key")
        distractors = edited.get("distractors")
        if not isinstance(distractors, list) or len(distractors) < 2 or not all(
                isinstance(d, dict) and isinstance(d.get("text"), str) and d["text"].strip() for d in distractors):
            raise ContractError("edit_invalid_distractors")
        texts = correct + [d["text"] for d in distractors]
        item_contracts.distinct(texts)
    elif item_type == "true_false_4":
        statements = edited.get("statements")
        if (not isinstance(statements, list) or len(statements) != 4
                or not all(isinstance(s, dict) and isinstance(s.get("truth"), bool) for s in statements)):
            raise ContractError("edit_invalid_statements")
        texts = [s.get("text", "") for s in statements]
        item_contracts.distinct(texts, "duplicate_statements")
        if not 1 <= sum(s["truth"] for s in statements) <= 3:
            raise ContractError("true_false_balance")
    elif item_type == "short_answer":
        answer = edited.get("answer")
        if not isinstance(answer, dict) or answer.get("kind") not in ("number", "text"):
            raise ContractError("edit_invalid_answer")
    for text in texts + [edited.get("stem") or edited.get("context") or "", edited.get("explanation", "")]:
        if not isinstance(text, str) or not text.strip() or not item_contracts.latex_balanced(text):
            raise ContractError("edit_invalid_text")
    return {**edited, "evidence": original.get("evidence", edited.get("evidence", []))}


def export_payload(draft: dict, *, job: dict, approved_by: str) -> dict:
    """Payload for the Learning import call; idempotency key = draft id."""
    if draft["status"] not in (ACCEPTED, EDITED_ACCEPTED):
        raise ValueError("only_accepted_items_export")
    provenance = draft.get("provenance") or {}
    item = draft["item"]
    evidence = item.get("evidence") or [c for s in item.get("statements", []) for c in s.get("evidence", [])]
    return {
        "idempotency_key": draft["id"],
        "item": {k: v for k, v in item.items() if k != "evidence"},
        "level": draft["level"],
        "generated_by": "AI", "approved_by": approved_by,
        "edited_after_generation": draft["status"] == EDITED_ACCEPTED,
        "provenance": {"job_id": job["id"], "item_draft_id": draft["id"],
                       "task_version": provenance.get("task_version"),
                       "model_sha256": provenance.get("model_sha256"), "seed": draft.get("seed"),
                       "evidence_sha256": provenance.get("evidence_sha256")},
        "sources": [{"source_id": c["source_id"], "source_spans": c["source_spans"]} for c in evidence],
    }
