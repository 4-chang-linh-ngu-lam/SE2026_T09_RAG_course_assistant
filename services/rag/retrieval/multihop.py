"""Optional query planning for conversation-aware and multi-hop retrieval.

The planner decides which additional queries to run.  It never supplies
evidence and it never changes the answer contract.  Every query is executed by
the already-authorized retriever owned by ``RagPipeline``.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Mapping


MULTIHOP_VERSION = "idp-rag-multihop-planner-1"
_FOLLOW_UP = re.compile(
    r"\b(?:nó|này|đó|đây|người này|vị này|sự kiện này|sau đó|khi đó|cái đó|"
    r"it|this|that|they|he|she|then|there)\b",
    re.IGNORECASE,
)
_COMPOSITE = re.compile(
    r"\b(?:và|so sánh|so với|hơn|tại sao|vì sao|sau khi|and|compare|versus|why|after)\b",
    re.IGNORECASE,
)

MULTIHOP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "rewrite", "subqueries"],
    "properties": {
        "mode": {"type": "string", "enum": ["direct", "rewrite", "decompose"]},
        "rewrite": {"type": ["string", "null"], "maxLength": 512},
        "subqueries": {
            "type": "array", "maxItems": 2,
            "items": {"type": "string", "minLength": 1, "maxLength": 512},
        },
    },
}

MULTIHOP_SYSTEM = """You are a query planner for a Vietnamese document-grounded RAG system.
Use the current question and conversation context to decide whether one retrieval
query is enough. Return JSON only.
- direct: use the current question as-is.
- rewrite: produce one standalone query that resolves references from context.
- decompose: produce up to two standalone queries for distinct facts needed by
  the question. Preserve names, negation, numbers, dates and units exactly.
Never answer the question and never invent facts. An empty context means the
current question must be treated as standalone."""


@dataclass(frozen=True)
class MultiHopDecision:
    """Validated planner output consumed by the pipeline."""

    mode: str = "direct"
    queries: tuple[str, ...] = ()

    def __post_init__(self):
        if self.mode not in {"direct", "rewrite", "decompose"}:
            raise ValueError("invalid multi-hop mode")
        if not isinstance(self.queries, tuple) or len(self.queries) > 2:
            raise ValueError("multi-hop planner supports at most two queries")
        if any(not isinstance(q, str) or not q.strip() or len(q) > 512 for q in self.queries):
            raise ValueError("multi-hop queries must be nonempty strings of at most 512 characters")
        if self.mode == "direct" and self.queries:
            raise ValueError("direct multi-hop decision cannot contain queries")
        if self.mode == "rewrite" and len(self.queries) != 1:
            raise ValueError("rewrite multi-hop decision requires one query")
        if self.mode == "decompose" and not self.queries:
            raise ValueError("decompose multi-hop decision requires queries")

    @property
    def is_additional(self):
        return bool(self.queries)


def _normalize(value: Mapping) -> MultiHopDecision:
    if not isinstance(value, Mapping) or set(value) != {"mode", "rewrite", "subqueries"}:
        raise ValueError("invalid multi-hop planner response")
    mode = value["mode"]
    rewrite = value["rewrite"]
    subqueries = value["subqueries"]
    if not isinstance(mode, str) or not isinstance(subqueries, list):
        raise ValueError("invalid multi-hop planner fields")
    if rewrite is not None and (not isinstance(rewrite, str) or not rewrite.strip()):
        raise ValueError("invalid multi-hop rewrite")
    clean = []
    for query in subqueries:
        if not isinstance(query, str) or not query.strip() or query.strip() in clean:
            continue
        clean.append(query.strip())
    if mode == "direct":
        return MultiHopDecision()
    if mode == "rewrite":
        if rewrite is None:
            raise ValueError("rewrite mode requires a rewrite")
        return MultiHopDecision(mode="rewrite", queries=(rewrite.strip(),))
    if mode == "decompose":
        return MultiHopDecision(mode="decompose", queries=tuple(clean[:2]))
    raise ValueError("invalid multi-hop mode")


def should_plan(query: str, context_hint: str = "") -> bool:
    """Cheap gate that avoids a planner model call for ordinary direct queries."""
    return bool(context_hint.strip() or _FOLLOW_UP.search(query) or _COMPOSITE.search(query))


class CallableMultiHopPlanner:
    """Adapter for an application-owned planner or a deterministic test fixture."""

    def __init__(self, planner, *, identity=None):
        if not callable(planner):
            raise ValueError("multi-hop planner must be callable")
        self._planner = planner
        self.identity = copy.deepcopy(identity or {"adapter": "callable-multihop-planner-1"})
        if not isinstance(self.identity, dict):
            raise ValueError("multi-hop planner identity must be a dictionary")

    def plan(self, request):
        value = self._planner(request)
        return value if isinstance(value, MultiHopDecision) else _normalize(value)


class GeneratorMultiHopPlanner:
    """Use the injected generator for bounded query planning.

    The same generator may still be used for final answer generation. Planning
    is gated by ``should_plan`` and its output is validated before retrieval.
    """

    def __init__(self, generator, *, max_queries=2):
        if not callable(getattr(generator, "generate", None)):
            raise ValueError("multi-hop generator must expose generate")
        if type(max_queries) is not int or not 1 <= max_queries <= 2:
            raise ValueError("max_queries must be an integer in 1..2")
        self.generator, self.max_queries = generator, max_queries
        self.identity = {"version": MULTIHOP_VERSION, "adapter": "generator-multihop-planner-1",
                         "max_queries": max_queries,
                         "generator": copy.deepcopy(generator.identity)}

    def plan(self, request):
        if not should_plan(request.query, request.context_hint):
            return MultiHopDecision()
        payload = json.dumps({"question": request.query, "context_hint": request.context_hint},
                             ensure_ascii=False)
        raw = self.generator.generate([
            {"role": "system", "content": MULTIHOP_SYSTEM},
            {"role": "user", "content": payload},
        ], MULTIHOP_SCHEMA)
        if not isinstance(raw, Mapping) or raw.get("finish_reason") != "stop":
            raise ValueError("multi-hop planner generation incomplete")
        try:
            value = json.loads(raw.get("text", ""))
        except (TypeError, ValueError):
            raise ValueError("multi-hop planner returned invalid JSON") from None
        decision = _normalize(value)
        if len(decision.queries) > self.max_queries:
            raise ValueError("multi-hop planner exceeded query budget")
        return decision
