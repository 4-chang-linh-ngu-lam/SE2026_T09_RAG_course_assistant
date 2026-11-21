"""Token budget planning with the real chat template and tokenizer (§6.3).

prompt_tokens <= context_tokens - max_new_tokens - margin. Evidence is reduced
whole items first; a single remaining item is cut at a sentence boundary. The
caller builds the grammar *after* packing, so quote enums never reference text
the model did not see.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts.evidence import sentence_cut, truncate_item

TRIM_NONE = "none"
TRIM_DROP_TAIL = "drop_tail"          # drop whole trailing evidence items
TRIM_SENTENCES = "sentences"          # drop items, then cut the last item at sentence ends


class BudgetError(ValueError):
    code = "prompt_over_budget"


@dataclass(frozen=True)
class PackedPrompt:
    messages: list
    evidence: list
    prompt_tokens: int
    dropped_ids: tuple
    truncated_ids: tuple


class BudgetPlanner:
    def __init__(self, count_messages, context_tokens: int, margin: int = 64):
        if type(context_tokens) is not int or context_tokens < 512 or type(margin) is not int or margin < 0:
            raise ValueError("invalid budget")
        self.count_messages, self.context_tokens, self.margin = count_messages, context_tokens, margin

    def available(self, max_new_tokens: int) -> int:
        return self.context_tokens - max_new_tokens - self.margin

    def pack(self, build_messages, evidence, max_new_tokens: int, *, trim: str = TRIM_DROP_TAIL,
             min_items: int = 0) -> PackedPrompt:
        if trim not in (TRIM_NONE, TRIM_DROP_TAIL, TRIM_SENTENCES):
            raise ValueError("invalid trim policy")
        limit = self.available(max_new_tokens)
        if limit <= 0:
            raise BudgetError("output budget leaves no prompt room")
        evidence, dropped, truncated = list(evidence), [], []
        while True:
            messages = build_messages(evidence)
            tokens = self.count_messages(messages)
            if tokens <= limit:
                return PackedPrompt(messages, evidence, tokens, tuple(dropped), tuple(truncated))
            if trim == TRIM_NONE:
                raise BudgetError("prompt_over_budget")
            if len(evidence) > max(min_items, 1):
                dropped.append(evidence.pop()["id"])
                continue
            if trim != TRIM_SENTENCES or not evidence:
                raise BudgetError("prompt_over_budget")
            last = evidence[-1]
            # Proportional first guess, snapped back to a sentence boundary.
            target = int(len(last["text"]) * max(0.05, (limit / tokens) * 0.95))
            cut = sentence_cut(last["text"], min(target, len(last["text"]) - 1))
            if cut < 16:
                raise BudgetError("prompt_over_budget")
            evidence[-1] = truncate_item(last, cut)
            if last["id"] not in truncated:
                truncated.append(last["id"])
