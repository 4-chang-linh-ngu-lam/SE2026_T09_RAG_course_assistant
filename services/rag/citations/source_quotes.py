"""Source-bound quote candidate generation for the staged RAG profile.

This module is staged outside the repository. It constrains quote strings to
exact substrings of each supplied record; it does not certify that a claim is
supported by its quote.
"""
from __future__ import annotations

import re
from collections.abc import Mapping


MIN_QUOTE_CHARS = 3
MAX_QUOTE_CHARS = 160
MAX_SNIPPETS = 256
MAX_QUOTED_CHARS = 32_768
MAX_SOURCE_CHARS = 256_000
WINDOW_OVERLAP_CHARS = 32

_SENTENCE_END = re.compile(r"[.!?;](?=\s)|\n+")
_CLAUSE_END = re.compile(r"[,:(—–](?=\s)")
_WORD = re.compile(r"\S+")


class SourceBoundSchemaError(ValueError):
    """The supplied evidence cannot be represented under this schema budget."""


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Choose non-whitespace boundaries without modifying the source string."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _ranges(text: str, start: int, end: int, delimiter: re.Pattern[str]):
    cursor = start
    for match in delimiter.finditer(text, start, end):
        boundary = match.end()
        if cursor < boundary:
            yield cursor, boundary
        cursor = boundary
    if cursor < end:
        yield cursor, end


def _sentence_and_clause_ranges(text: str):
    for raw_start, raw_end in _ranges(text, 0, len(text), _SENTENCE_END):
        start, end = _trim_bounds(text, raw_start, raw_end)
        if start >= end:
            continue
        yield start, end
        # Keep sentence-level candidates when they fit and also offer exact
        # clause candidates. Long sentences receive full-coverage windows.
        for clause_start, clause_end in _ranges(text, start, end, _CLAUSE_END):
            clause_start, clause_end = _trim_bounds(text, clause_start, clause_end)
            if clause_start < clause_end:
                yield clause_start, clause_end


def _window_slices(text: str, start: int, end: int):
    words = [(match.start(), match.end()) for match in _WORD.finditer(text, start, end)]
    if not words:
        return
    index = 0
    while index < len(words):
        window_start = words[index][0]
        window_end_index = index
        while (window_end_index + 1 < len(words)
               and words[window_end_index + 1][1] - window_start <= MAX_QUOTE_CHARS):
            window_end_index += 1
        window_end = words[window_end_index][1]
        if window_end - window_start > MAX_QUOTE_CHARS:
            raise SourceBoundSchemaError(
                "unsupported_unbroken_token_over_quote_limit"
            )
        yield window_start, window_end
        if window_end_index == len(words) - 1:
            break

        # Start the next window at a word boundary close to the overlap target.
        # Advancing by at least one word guarantees progress for dense text.
        target = window_end - WINDOW_OVERLAP_CHARS
        next_index = index + 1
        while next_index + 1 <= window_end_index and words[next_index + 1][0] <= target:
            next_index += 1
        index = next_index


def _record_text(item: Mapping) -> tuple[str, str]:
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise SourceBoundSchemaError("evidence_id_must_be_a_nonempty_string")
    record = item.get("record")
    text = record.get("text") if isinstance(record, Mapping) else item.get("text")
    if not isinstance(text, str):
        raise SourceBoundSchemaError(f"evidence_record_text_missing:{item_id}")
    if "text" in item and item["text"] != text:
        raise SourceBoundSchemaError(f"evidence_text_mismatch:{item_id}")
    return item_id, text


def _snippets_for(text: str, item_id: str) -> list[str]:
    snippets = []
    seen = set()
    for segment_start, segment_end in _sentence_and_clause_ranges(text):
        if segment_end - segment_start <= MAX_QUOTE_CHARS:
            slices = [(segment_start, segment_end)]
        else:
            slices = _window_slices(text, segment_start, segment_end)
        for start, end in slices:
            quote = text[start:end]
            if not MIN_QUOTE_CHARS <= len(quote) <= MAX_QUOTE_CHARS:
                continue
            if quote not in seen:
                seen.add(quote)
                snippets.append(quote)
                if len(snippets) > MAX_SNIPPETS:
                    raise SourceBoundSchemaError("snippet_budget_exceeded")
    if not snippets:
        raise SourceBoundSchemaError(f"no_eligible_quote_snippet:{item_id}")
    return snippets


def source_quote_enums(evidence) -> dict[str, list[str]]:
    """Return bounded source-exact quote candidates keyed by provided source ID."""
    if not isinstance(evidence, (list, tuple)) or not evidence:
        raise SourceBoundSchemaError("evidence_records_required")

    total_source_chars = 0
    total_snippets = 0
    total_quoted_chars = 0
    seen_ids = set()
    quotes_by_id = {}
    for item in evidence:
        if not isinstance(item, Mapping):
            raise SourceBoundSchemaError("evidence_record_must_be_an_object")
        item_id, source_text = _record_text(item)
        if item_id in seen_ids:
            raise SourceBoundSchemaError(f"duplicate_evidence_id:{item_id}")
        seen_ids.add(item_id)
        total_source_chars += len(source_text)
        if total_source_chars > MAX_SOURCE_CHARS:
            raise SourceBoundSchemaError("source_work_budget_exceeded")

        snippets = _snippets_for(source_text, item_id)
        total_snippets += len(snippets)
        total_quoted_chars += sum(map(len, snippets))
        if total_snippets > MAX_SNIPPETS:
            raise SourceBoundSchemaError("snippet_budget_exceeded")
        if total_quoted_chars > MAX_QUOTED_CHARS:
            raise SourceBoundSchemaError("quoted_character_budget_exceeded")
        quotes_by_id[item_id] = snippets
    return quotes_by_id


def source_bound_schema(evidence):
    """Return a focused answer schema binding every quote enum to its source ID.

    Each enum value is an exact 3–160 character substring of that source's
    record text. All sentence/clause slices and overlapping long-text windows
    must fit the explicit caps; over-cap or unrepresentable input raises instead
    of silently omitting evidence.
    """
    quotes_by_id = source_quote_enums(evidence)
    branches = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "quote"],
            "properties": {
                "id": {"const": item_id},
                "quote": {"type": "string", "minLength": MIN_QUOTE_CHARS,
                          "maxLength": MAX_QUOTE_CHARS, "enum": snippets},
            },
        }
        for item_id, snippets in quotes_by_id.items()
    ]

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "claims"],
        "properties": {
            "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
            "claims": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "evidence"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 1600},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 2,
                            "items": {"oneOf": branches},
                        },
                    },
                },
            },
        },
    }
