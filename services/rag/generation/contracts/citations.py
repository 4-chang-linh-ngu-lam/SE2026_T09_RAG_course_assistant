"""Quote-enum citations shared by every grounded task.

A citation is ``{"id": "S1", "quote": "<exact source substring>"}``. The grammar
only offers quotes that occur verbatim in that evidence item (via
``source_quote_enums``), and :func:`resolve` maps each accepted quote back to
immutable source spans. Locating a quote is not proof that it supports a claim.
"""
from __future__ import annotations

from ...citations.source_quotes import (
    MAX_QUOTE_CHARS,
    MIN_QUOTE_CHARS,
    SourceBoundSchemaError,
    source_quote_enums,
)
from ...citations.span_mapping import quote_spans
from .errors import ContractError

__all__ = ["SourceBoundSchemaError", "citation_array", "quote_enums", "quotes_text", "resolve"]


def quote_enums(evidence) -> dict[str, list[str]]:
    return source_quote_enums(evidence)


def citation_array(enums: dict[str, list[str]], min_items: int = 1, max_items: int = 2) -> dict:
    branches = [{"type": "object", "additionalProperties": False, "required": ["id", "quote"],
                 "properties": {"id": {"const": item_id},
                                "quote": {"type": "string", "minLength": MIN_QUOTE_CHARS,
                                          "maxLength": MAX_QUOTE_CHARS, "enum": snippets}}}
                for item_id, snippets in enums.items()]
    return {"type": "array", "minItems": min_items, "maxItems": max_items,
            "items": {"oneOf": branches}}


def resolve(citations, evidence, enums, *, min_items: int = 1, max_items: int = 2) -> list[dict]:
    """Validate citations against the enums and attach mapped source spans.

    Duplicate (id, quote) pairs are collapsed. Raises ``ContractError``.
    """
    by_id = {e["id"]: e for e in evidence}
    if not isinstance(citations, list) or not min_items <= len(citations) <= max_items:
        raise ContractError("invalid_citation_count")
    out, seen = [], set()
    for cite in citations:
        if (not isinstance(cite, dict) or set(cite) != {"id", "quote"}
                or cite["id"] not in by_id or not isinstance(cite["quote"], str)):
            raise ContractError("invalid_citation_schema")
        if cite["quote"] not in enums.get(cite["id"], ()):
            raise ContractError("citation_quote_not_in_source_enum")
        key = (cite["id"], cite["quote"])
        if key in seen:
            continue
        seen.add(key)
        try:
            spans = quote_spans(by_id[cite["id"]], cite["quote"])
        except ValueError as error:
            raise ContractError(str(error)) from None
        out.append({"id": cite["id"], "quote": cite["quote"],
                    "source_id": by_id[cite["id"]]["record"]["source_id"], "source_spans": spans})
    return out


def quotes_text(citations) -> str:
    return "\n".join(c["quote"] for c in citations)
