"""Knowledge Units: document-driven evidence for question generation (§5.3 [2]).

Quiz generation walks the IDP section tree instead of retrieving per question.
Consecutive records of one source and one section path are joined until a
token budget is reached; oversized records are split at sentence boundaries.
Units are derived data keyed by document version and contain no personal data.
Exercise blocks (questions already printed in the book) are kept apart so they
are never used as knowledge (§5.7).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ...contracts.evidence import concat_records, sentence_cut, slice_record

KU_VERSION = "quiz-ku-1"


@dataclass(frozen=True)
class KnowledgeUnit:
    id: str
    document_version_id: str
    source_id: str
    section_path: tuple
    text: str
    record: dict
    token_count: int
    warnings: tuple = ()
    exercise: bool = False

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    def evidence(self, evidence_id: str = "S1") -> dict:
        item = {"id": evidence_id, "text": self.text, "title": " > ".join(self.section_path),
                "record": self.record}
        if self.warnings:
            item["source_warnings"] = list(self.warnings)
        return item

    def summary(self) -> dict:
        return {"id": self.id, "document_version_id": self.document_version_id, "source_id": self.source_id,
                "section_path": list(self.section_path), "token_count": self.token_count,
                "text_sha256": self.text_sha256, "warnings": list(self.warnings), "exercise": self.exercise}


def _unit(record, count_tokens, document_version_id, exercise) -> KnowledgeUnit:
    path = tuple(map(str, record["section_path"]))
    text = record["text"]
    digest = hashlib.sha256("\x1f".join([KU_VERSION, document_version_id, record["source_id"],
                                         *path, text]).encode()).hexdigest()
    return KnowledgeUnit(id="ku-" + digest[:20], document_version_id=document_version_id,
                         source_id=record["source_id"], section_path=path, text=text, record=record,
                         token_count=count_tokens(text),
                         warnings=tuple(record.get("source_quality_warnings", ())), exercise=exercise)


def _split(record, count_tokens, max_tokens):
    """Split one oversized record into sentence-bounded slices under the budget."""
    pieces, start, text = [], 0, record["text"]
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text):
            break
        remaining = text[start:]
        if count_tokens(remaining) <= max_tokens:
            pieces.append(slice_record(record, start, len(text)))
            break
        limit = max(16, int(len(remaining) * max_tokens / max(count_tokens(remaining), 1) * 0.95))
        cut = sentence_cut(remaining, limit)
        while cut > 16 and count_tokens(remaining[:cut]) > max_tokens:
            cut = sentence_cut(remaining, int(cut * 0.8))
        end = start + len(remaining[:cut].rstrip())
        if end <= start:
            raise ValueError("cannot_split_record_under_budget")
        pieces.append(slice_record(record, start, end))
        start = start + cut
    return pieces


def build_knowledge_units(records, *, count_tokens, max_tokens: int = 1500,
                          document_version_of=None, is_exercise=None) -> list[KnowledgeUnit]:
    """Group retrieval/IDP records into knowledge units, preserving document order.

    ``count_tokens(text) -> int`` should be the generator's tokenizer.
    ``document_version_of(record)`` defaults to ``record["document_version_id"]``
    or ``record["source_id"]``. ``is_exercise(record)`` marks printed exercises.
    """
    if type(max_tokens) is not int or max_tokens < 64:
        raise ValueError("invalid max_tokens")
    version_of = document_version_of or (lambda r: str(r.get("document_version_id") or r["source_id"]))
    exercise_of = is_exercise or (lambda r: False)
    units, group, group_key, group_tokens, seen = [], [], None, 0, set()

    def flush():
        nonlocal group, group_tokens
        if group:
            merged = concat_records(group) if len(group) > 1 else group[0]
            units.append(_unit(merged, count_tokens, group_key[0], group_key[3]))
        group, group_tokens = [], 0

    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("text"), str) or not record["text"].strip():
            continue
        record_id = record.get("id")
        if record_id is not None:
            if record_id in seen:
                continue
            seen.add(record_id)
        key = (version_of(record), record["source_id"], tuple(map(str, record["section_path"])),
               bool(exercise_of(record)))
        tokens = count_tokens(record["text"])
        parts = [record] if tokens <= max_tokens else _split(record, count_tokens, max_tokens)
        for part in parts:
            part_tokens = tokens if len(parts) == 1 else count_tokens(part["text"])
            if key != group_key or group_tokens + part_tokens > max_tokens:
                flush()
                group_key = key
            group.append(part)
            group_tokens += part_tokens
    flush()
    return units


def section_matches(unit: KnowledgeUnit, section) -> bool:
    """A matrix row's section is a label (any path element) or a path prefix."""
    path = [s.casefold().strip() for s in unit.section_path]
    if isinstance(section, str):
        return section.casefold().strip() in path
    wanted = [str(s).casefold().strip() for s in section]
    return path[:len(wanted)] == wanted
