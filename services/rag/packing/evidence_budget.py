"""Final prompt-budget fitting for already selected evidence records."""
from __future__ import annotations

from collections.abc import Callable, Sequence


PACKING_VERSION = "idp-evidence-budget-1"


def fit_evidence(
    evidence: Sequence[dict],
    *,
    build_messages: Callable[[list[dict]], object],
    count_messages: Callable[[object], int],
    context_tokens: int,
    max_new_tokens: int,
    reserve_tokens: int = 64,
) -> dict:
    """Drop whole evidence records from the tail until the final prompt fits.

    The packer owns the budget decision but knows nothing about generation
    schemas. Callers provide message construction and token counting callbacks.
    Source records are never cropped or rewritten.
    """
    if not isinstance(evidence, (list, tuple)) or any(not isinstance(item, dict) for item in evidence):
        raise ValueError("evidence must be a sequence of records")
    if not callable(build_messages) or not callable(count_messages):
        raise ValueError("message builder and counter callbacks are required")
    for name, value in (("context_tokens", context_tokens), ("max_new_tokens", max_new_tokens),
                        ("reserve_tokens", reserve_tokens)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    fitted = list(evidence)
    dropped = []
    prompt_tokens = 0
    messages = None
    while fitted:
        messages = build_messages(fitted)
        prompt_tokens = count_messages(messages)
        if type(prompt_tokens) is not int or prompt_tokens < 0:
            raise ValueError("message counter must return a nonnegative integer")
        if prompt_tokens + max_new_tokens + reserve_tokens <= context_tokens:
            break
        item = fitted.pop()
        if isinstance(item.get("id"), str):
            dropped.append(item["id"])

    return {
        "version": PACKING_VERSION,
        "evidence": fitted,
        "messages": messages,
        "prompt_tokens": prompt_tokens,
        "dropped_evidence_ids": dropped,
        "exhausted": bool(evidence) and not fitted,
    }
