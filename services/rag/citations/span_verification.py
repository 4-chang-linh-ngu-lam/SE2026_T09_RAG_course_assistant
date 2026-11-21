"""Opt-in source-unit selection; source code, rather than a model, copies witnesses."""
from __future__ import annotations

import json
import re
import unicodedata

from .claim_verification import (ClaimVerifier, MAX_RESPONSE_CHARS, SYSTEM as QUOTE_SYSTEM,
                                 _CLAIM_ID, _VerifierError, _schema)

VERSION = "idp-span-claim-verification-1"
MAX_UNIT_CHARS = 160
MAX_UNITS = 256
_BREAK = re.compile(r'[.!?。！？;](?:["\u201d\u2019)\]]*)\s+|\n+')
SYSTEM = QUOTE_SYSTEM.replace(
    "For supported, provide one allowed evidence_id and one exact contiguous quote (3–160 characters) copied from that evidence item's text. For other verdicts use empty evidence_id and quote.",
    "For supported, provide one allowed evidence_id and one nonempty span_id from that evidence item's spans (3–160 source characters). For other verdicts use empty evidence_id and span_id. Spans contain the entire original evidence body in source order; judge using the full context, not the selected witness alone.")


def unit_ranges(text):
    """Partition all source characters; prefer nearby sentence/word boundaries."""
    start = 0
    while start < len(text):
        end = min(start + MAX_UNIT_CHARS, len(text))
        if end < len(text):
            floor = start + MAX_UNIT_CHARS // 2
            natural = [m.end() for m in _BREAK.finditer(text, start, end) if m.end() >= floor]
            words = [i + 1 for i in range(floor, end) if text[i].isspace()]
            end = natural[-1] if natural else (words[-1] if words else end)
            # Preserve decomposed accents and common joined Unicode sequences.
            while end > start and (unicodedata.combining(text[end])
                    or text[end] in {"\u200d", "\ufe0e", "\ufe0f"} or text[end - 1] == "\u200d"):
                end -= 1
        if end == start:
            raise _VerifierError("unbreakable_witness_unit")
        yield start, end
        start = end


def mapped_interval(item, start, end):
    """Resolve this occurrence by offsets; never search for a duplicate string."""
    text = item["text"]
    covered = [False] * (end - start)
    sources = []
    for span in sorted(item["record"]["source_spans"], key=lambda x: x["start"]):
        a, b = max(start, span["start"]), min(end, span["end"])
        if a >= b:
            continue
        covered[a - start:b - start] = [True] * (b - a)
        offset = span["source_start"] + a - span["start"]
        sources.append({"source_id": item["record"]["source_id"], "start": offset, "end": offset + b - a})
    if not all(ch.isspace() or covered[i] for i, ch in enumerate(text[start:end])):
        return None
    return sources


class SpanClaimVerifier(ClaimVerifier):
    """Same filtering contract as ClaimVerifier, with a distinct witness protocol."""

    version = VERSION

    def _prepare(self, question, answer, evidence):
        prepared = super()._prepare(question, answer, evidence)
        units, catalog, count = {}, [], 0
        for entry in prepared["evidence_catalog"]:
            item = prepared["evidence_by_id"][entry["evidence_id"]]
            if not item["id"].strip():
                raise _VerifierError("invalid_evidence_records")
            spans = []
            for start, end in unit_ranges(item["text"]):
                count += 1
                if count > MAX_UNITS:
                    raise _VerifierError("witness_unit_limit_exceeded")
                quote = item["text"][start:end]
                sources = mapped_interval(item, start, end)
                selectable = 3 <= len(quote) <= MAX_UNIT_CHARS and bool(quote.strip()) and bool(sources)
                sid = f"W{count}" if selectable else ""
                spans.append({"span_id": sid, "text": quote})
                if selectable:
                    units[sid] = {"evidence_id": item["id"], "quote": quote, "local_start": start,
                                  "local_end": end, "source_id": item["record"]["source_id"], "source_spans": sources}
            catalog.append({"evidence_id": item["id"], "spans": spans})
        if not units:
            raise _VerifierError("no_mapped_witness_spans")
        return {**prepared, "evidence_catalog": catalog, "witness_units": units}

    def _request(self, question, prepared):
        payload = {"question": question,
                   "claims": [{k: c[k] for k in ("id", "text", "allowed_evidence_ids")} for c in prepared["claims"]],
                   "evidence_catalog": prepared["evidence_catalog"]}
        schema = _schema(prepared["claims"], prepared["evidence_catalog"])
        properties = schema["properties"]["decisions"]["items"]
        properties["required"][-1] = "span_id"
        properties["properties"].pop("quote")
        properties["properties"]["span_id"] = {"type": "string", "enum": ["", *prepared["witness_units"]]}
        return [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], schema

    def _validate(self, raw, prepared):
        if not isinstance(raw, dict) or raw.get("finish_reason") != "stop":
            raise _VerifierError("generation_not_complete")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_RESPONSE_CHARS:
            raise _VerifierError("invalid_generation_text")
        def unique(pairs):
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError("duplicate")
            return value
        try:
            value = json.loads(text, object_pairs_hook=unique)
        except (ValueError, TypeError):
            raise _VerifierError("invalid_verifier_json") from None
        if not isinstance(value, dict) or set(value) != {"decisions"} or not isinstance(value["decisions"], list):
            raise _VerifierError("invalid_verifier_schema")
        expected = {c["id"]: c for c in prepared["claims"]}
        if len(value["decisions"]) != len(expected):
            raise _VerifierError("decision_set_incomplete")
        seen, result = set(), []
        for decision in value["decisions"]:
            if not isinstance(decision, dict) or set(decision) != {"claim_id", "verdict", "question_match", "evidence_id", "span_id"}:
                raise _VerifierError("invalid_decision_schema")
            cid, verdict, match = decision["claim_id"], decision["verdict"], decision["question_match"]
            if not isinstance(cid, str) or not _CLAIM_ID.fullmatch(cid) or cid not in expected:
                raise _VerifierError("unknown_claim_id")
            if cid in seen:
                raise _VerifierError("duplicate_claim_id")
            seen.add(cid)
            if (not isinstance(verdict, str) or verdict not in {"supported", "contradicted", "insufficient_evidence"}
                    or not isinstance(match, str) or match not in {"yes", "no", "uncertain"}):
                raise _VerifierError("invalid_verdict")
            eid, sid = decision["evidence_id"], decision["span_id"]
            if not isinstance(eid, str) or not isinstance(sid, str):
                raise _VerifierError("invalid_witness_id")
            unit = None
            if verdict == "supported":
                if eid not in expected[cid]["allowed_evidence_ids"]:
                    raise _VerifierError("evidence_id_outside_citation_scope")
                unit = prepared["witness_units"].get(sid)
                if unit is None or unit["evidence_id"] != eid:
                    raise _VerifierError("unknown_or_mismatched_witness_id")
            elif eid or sid:
                raise _VerifierError("unexpected_witness_for_non_supported")
            result.append({**decision, "source_id": unit["source_id"] if unit else "",
                           "quote": unit["quote"] if unit else "", "source_quote_valid": unit is not None,
                           "local_start": unit["local_start"] if unit else None,
                           "local_end": unit["local_end"] if unit else None,
                           "source_spans": unit["source_spans"] if unit else []})
        return result
