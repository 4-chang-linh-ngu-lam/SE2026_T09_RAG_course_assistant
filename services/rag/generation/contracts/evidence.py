"""Evidence items handed to prompts, and span-preserving text slicing.

An evidence item is ``{"id": "S1", "text", "title", "record", "source_warnings"?}``
where ``record`` is the retrieval/IDP record carrying ``source_id``,
``section_path`` and ``source_spans``. ``record["text"]`` always equals
``item["text"]`` so exact quotes can be mapped back to source offsets.
Evidence must already be filtered to the class's active grants by the caller.
"""
from __future__ import annotations

import copy
import hashlib
import re

from ..runtime.sampling import canonical_json

_SENTENCE_END = re.compile(r"[.!?;:](?=\s)|\n+")


def evidence_items(records) -> list[dict]:
    items = []
    for index, record in enumerate(records, 1):
        if (not isinstance(record, dict) or not isinstance(record.get("text"), str)
                or not record["text"].strip() or not isinstance(record.get("section_path"), (list, tuple))
                or not isinstance(record.get("source_spans"), list) or not record.get("source_id")):
            raise ValueError("invalid_evidence_record")
        item = {"id": f"S{index}", "text": record["text"],
                "title": " > ".join(map(str, record["section_path"])),
                "record": copy.deepcopy(record)}
        if record.get("source_quality_warnings"):
            item["source_warnings"] = list(record["source_quality_warnings"])
        items.append(item)
    return items


def prompt_view(evidence) -> list[dict]:
    """The only evidence fields a model sees."""
    return [{k: e[k] for k in ("id", "title", "text", "source_warnings") if k in e} for e in evidence]


def evidence_fingerprint(evidence) -> dict:
    parts = [{"id": e["id"], "source_id": e["record"].get("source_id"),
              "text_sha256": hashlib.sha256(e["text"].encode()).hexdigest()} for e in evidence]
    return {"evidence_ids": [p["id"] for p in parts],
            "evidence_sha256": hashlib.sha256(canonical_json(parts).encode()).hexdigest()}


def slice_record(record: dict, start: int, end: int) -> dict:
    """Return a copy of ``record`` restricted to ``text[start:end]`` with spans clipped."""
    text = record["text"]
    if not 0 <= start < end <= len(text):
        raise ValueError("invalid_slice")
    spans = []
    for span in record.get("source_spans", []):
        a, b = max(span["start"], start), min(span["end"], end)
        if a >= b:
            continue
        clipped = dict(span)
        clipped["start"], clipped["end"] = a - start, b - start
        clipped["source_start"] = span["source_start"] + (a - span["start"])
        clipped["source_end"] = clipped["source_start"] + (b - a)
        spans.append(clipped)
    out = copy.deepcopy({k: v for k, v in record.items() if k not in {"text", "source_spans"}})
    out["text"], out["source_spans"] = text[start:end], spans
    return out


def concat_records(records, separator: str = "\n\n") -> dict:
    """Join records of one source into one record with offset-shifted spans."""
    if not records:
        raise ValueError("records_required")
    first = records[0]
    text, spans = "", []
    for record in records:
        if record.get("source_id") != first.get("source_id"):
            raise ValueError("cannot_join_different_sources")
        offset = len(text) + (len(separator) if text else 0)
        text = record["text"] if not text else text + separator + record["text"]
        for span in record.get("source_spans", []):
            moved = dict(span)
            moved["start"], moved["end"] = span["start"] + offset, span["end"] + offset
            spans.append(moved)
    warnings = sorted({w for r in records for w in r.get("source_quality_warnings", [])})
    out = {k: copy.deepcopy(v) for k, v in first.items()
           if k not in {"text", "source_spans", "source_quality_warnings", "id"}}
    out.update(text=text, source_spans=spans,
               id="+".join(str(r.get("id", "")) for r in records))
    if warnings:
        out["source_quality_warnings"] = warnings
    return out


def sentence_cut(text: str, limit: int) -> int:
    """Largest sentence boundary <= limit (falls back to whitespace, then limit)."""
    if limit >= len(text):
        return len(text)
    best = 0
    for match in _SENTENCE_END.finditer(text, 0, limit):
        best = match.end()
    if best == 0:
        best = text.rfind(" ", 0, limit)
    return best if best > 0 else limit


def truncate_item(item: dict, length: int) -> dict:
    length = len(item["text"][:length].rstrip())
    if length <= 0:
        raise ValueError("invalid_slice")
    record = slice_record(item["record"], 0, length)
    out = dict(item)
    out["text"], out["record"] = record["text"], record
    return out
