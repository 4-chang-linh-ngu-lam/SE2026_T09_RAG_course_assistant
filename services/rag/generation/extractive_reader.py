"""Optional single-fact extractive reader with source-mapped citations."""
from __future__ import annotations

import json

from jsonschema import ValidationError, validate

from .evidence_selection import (
    EXTRACTIVE_SYSTEM,
    extractive_schema,
    resolve_answer_span,
    selected_evidence,
    span_catalog,
)
from .rag_answer import validate_answer


EXTRACTIVE_ANSWER_VERSION = "idp-text-rag-answer-extractive-1"
EXTRACTIVE_FALLBACK_ANSWER_VERSION = "idp-text-rag-answer-extractive-fallback-1"
EXTRACTIVE_FALLBACK_ERRORS = {"invalid_answer_schema", "answer_not_exact_span_substring",
                              "unknown_answer_span", "unknown_answer_evidence"}


def extractive_messages_for(query, evidence, context_hint=""):
    catalog = span_catalog(evidence)
    payload = {"question": query, "context_hint": context_hint,
               "span_catalog": [{"span_id": span["span_id"], "evidence_id": span["evidence_id"],
                                 "text": span["text"]} for span in catalog]}
    return [{"role": "system", "content": EXTRACTIVE_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def extractive_answer_schema(evidence):
    return extractive_schema(span_catalog(evidence))


def validate_extractive_answer(raw, evidence):
    if raw.get("finish_reason") != "stop":
        raise ValueError("generation_not_complete")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 32768:
        raise ValueError("invalid_generation_text")

    def unique_object(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("duplicate JSON keys")
        return value

    try:
        value = json.loads(text, object_pairs_hook=unique_object)
        validate(value, extractive_answer_schema(evidence))
    except (ValueError, TypeError, ValidationError):
        raise ValueError("invalid_answer_schema") from None
    if value["status"] == "insufficient_evidence":
        if any(value[key] for key in ("answer_substring", "evidence_id", "span_id")):
            raise ValueError("answer_status_claims_conflict")
        reader_raw = {**raw, "text": json.dumps({"status": "insufficient_evidence", "claims": []})}
        answer = validate_answer(reader_raw, evidence, policy="direct_answer")
        return answer, []
    if not value["answer_substring"]:
        raise ValueError("invalid_answer_schema")
    catalog = span_catalog(evidence)
    span, expanded = resolve_answer_span(evidence, catalog, value)
    selected = selected_evidence(evidence, [span], [span["span_id"]])
    reader_raw = {**raw, "text": json.dumps({"status": "answered", "claims": [{
        "text": value["answer_substring"], "evidence": [{"id": value["evidence_id"]}]}]}, ensure_ascii=False)}
    answer = validate_answer(reader_raw, selected, policy="direct_answer")
    answer["extractive_span_expanded"] = expanded
    return answer, selected
