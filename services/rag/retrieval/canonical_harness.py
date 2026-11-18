"""Local evaluation harness: real existing chunker + SQLite + fielded BM25.

This is not an AI Service or a production permission provider. Every retrieval
requires an external current-access decision; class/scope filters grant nothing.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

if "." in __package__:
    from ..chunking.chunking import chunk_text, validate_chunking
    from ..search.retrieval_lexical import FieldedBM25
    from ..search.retrieval_plan import (
        anchors,
        exercise_anchors,
        exercise_query_anchors,
        terms,
    )
else:
    from chunking.chunking import chunk_text, validate_chunking
    from search.retrieval_lexical import FieldedBM25
    from search.retrieval_plan import (
        anchors,
        exercise_anchors,
        exercise_query_anchors,
        terms,
    )

from idp.publish import iter_retrievable_blocks

_DOTTED_ITEM = re.compile(r"(?m)^[ \t]?(\d+(?:\.\d+)+)[.)][ \t]+\S")


class LexicalTokenBudget:
    """Exact tokens used by our BM25 backend, not embedding-token estimates."""

    identity: ClassVar = {"kind": "existing_bm25_terms", "unit": "tokens", "version": 1}

    def count(self, text):
        return len(terms(text))


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def build_chunks(canonical, *, max_tokens=256):
    blocks = list(iter_retrievable_blocks(canonical))
    by_source = {b["source_id"]: b for b in blocks}
    groups, assigned = [], set()
    for group in canonical["structures"].get("questions", ()):
        keys = [r["block_id"] for r in group["source_blocks"]]
        context = [r["block_id"] for r in group.get("shared_context_segments", ())]
        keys = list(dict.fromkeys(context + keys))
        if not keys or any(key not in by_source for key in keys):
            # Do not index a partial question after publication excludes data.
            assigned.update(keys)
            continue
        unit = [by_source[key] for key in keys]
        assigned.update(keys)
        groups.append((group["id"], unit, group.get("related_structures", [])))
    for block in blocks:
        if block["source_id"] not in assigned:
            groups.append((None, [block], []))
    output = []
    counter = LexicalTokenBudget()
    for question_id, unit, related_structures in groups:
        text, spans = "", []
        for block in unit:
            if text:
                text += "\n\n"
            start = len(text)
            text += block["text"]
            spans.append((start, len(text), block))
        source_id = _digest(
            [
                canonical["source_sha256"],
                canonical["document_version"],
                [b["block_id"] for b in unit],
            ]
        )
        budget = max(max_tokens, counter.count(text)) if question_id else max_tokens
        bundle = chunk_text(
            text, counter=counter, source_id=source_id, max_tokens=budget
        )
        errors = validate_chunking(bundle, text, counter)
        if errors:
            raise ValueError("existing chunker validation failed: " + str(errors))
        for child in bundle["children"]:
            if not child["retrieval_eligible"]:
                continue
            references = []
            for source_span in child["source_spans"]:
                lo, hi = source_span["source_start"], source_span["source_end"]
                for a, b, block in spans:
                    if max(a, lo) >= min(b, hi):
                        continue
                    references.append(
                        {
                            "block_id": block["block_id"],
                            "source_id": block["source_id"],
                            "region_id": block["region_id"],
                            "candidate_id": block["candidate_id"],
                            "evidence_refs": block["evidence_refs"],
                            "page": block["page"],
                            "bbox": block["bbox"],
                            "start": max(a, lo) - a,
                            "end": min(b, hi) - a,
                            "source_sha256": canonical["source_sha256"],
                            "document_version": canonical["document_version"],
                        }
                    )
            if not references:
                raise ValueError("chunk lost source attribution")
            output.append(
                {
                    **child,
                    "references": references,
                    "question_id": question_id,
                    "related_structures": related_structures,
                    "original_source_sha256": canonical["source_sha256"],
                    "document_version": canonical["document_version"],
                }
            )
    if len({c["id"] for c in output}) != len(output):
        raise ValueError("duplicate chunk identity")
    return output


class LocalRagIndex:
    def __init__(self, path):
        self.path = Path(path)
        self._lexical_snapshot = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, source_sha TEXT NOT NULL, document_version TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def index(self, canonical):
        chunks = build_chunks(canonical)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "DELETE FROM chunks WHERE source_sha=? AND document_version=?",
                (canonical["source_sha256"], canonical["document_version"]),
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?)",
                [
                    (
                        c["id"],
                        c["original_source_sha256"],
                        c["document_version"],
                        json.dumps(c, ensure_ascii=False),
                    )
                    for c in chunks
                ],
            )
        return len(chunks)

    def retrieve(self, query, *, actor, access_check, top_k=5, scope_source_ids=None):
        if not actor or not callable(access_check):
            raise ValueError("explicit actor/current-access checker required")
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise ValueError("invalid top_k")
        def can_read(source, version):
            try:
                return access_check(actor, source, version) is True
            except Exception:  # noqa: BLE001 - authorization errors deny access.
                return False

        with closing(sqlite3.connect(self.path)) as connection:
            documents = connection.execute(
                "SELECT DISTINCT source_sha, document_version FROM chunks ORDER BY source_sha, document_version"
            ).fetchall()
            payloads = []
            allowed_documents = []
            for source, version in documents:
                if scope_source_ids is not None and source not in scope_source_ids:
                    continue
                if not can_read(source, version):
                    continue
                allowed_documents.append((source, version))
                payloads.extend(
                    row[0]
                    for row in connection.execute(
                        "SELECT payload FROM chunks WHERE source_sha=? AND document_version=? ORDER BY id",
                        (source, version),
                    )
                )
        key = tuple(payloads)
        snapshot = self._lexical_snapshot
        if snapshot is None or snapshot[0] != key:
            rows = [json.loads(payload) for payload in key]
            by_id = {row["id"]: row for row in rows}
            # Canonical extraction can omit the printed practice heading while
            # preserving each numbered item. Treat a dotted line label as a cue.
            labels = {
                row["id"]: exercise_anchors(row)
                | {("exercise", n) for n in _DOTTED_ITEM.findall(row["text"])}
                for row in rows
            }
            snapshot = self._lexical_snapshot = (
                key, FieldedBM25(rows, fold_accents=True), by_id, labels
            )
        _, bm25, by_id, labels = snapshot
        ranked = bm25.rank(query)
        wanted = exercise_query_anchors(anchors(query, accept_unaccented=True))
        if wanted:
            ranked.sort(key=lambda item: not wanted <= labels[item[0]])
        if not all(can_read(source, version) for source, version in allowed_documents):
            return []
        return [
            {**deepcopy(by_id[identity]), "score": score}
            for identity, score in ranked[:top_k]
        ]


def resolve_citation(hit, canonical):
    by_id = {b["block_id"]: b for b in iter_retrievable_blocks(canonical)}
    if (
        hit["original_source_sha256"] != canonical["source_sha256"]
        or hit["document_version"] != canonical["document_version"]
    ):
        raise ValueError("retrieved document/version mismatch")
    resolved = []
    for reference in hit["references"]:
        block = by_id.get(reference["block_id"])
        if block is None or any(
            reference[k] != block[k]
            for k in (
                "source_id",
                "region_id",
                "candidate_id",
                "evidence_refs",
                "page",
                "bbox",
            )
        ):
            raise ValueError(
                "citation does not resolve to eligible extraction evidence"
            )
        if (
            reference["source_sha256"] != canonical["source_sha256"]
            or reference["document_version"] != canonical["document_version"]
        ):
            raise ValueError("citation source/version mismatch")
        a, b = reference["start"], reference["end"]
        if not 0 <= a < b <= len(block["text"]):
            raise ValueError("citation source span invalid")
        if block["text"][a:b] not in hit["text"]:
            raise ValueError("citation text mismatch")
        resolved.append({**reference, "text": block["text"][a:b]})
    if not resolved or re.sub(r"\s+", "", hit["text"]) != "".join(
        re.sub(r"\s+", "", r["text"]) for r in resolved
    ):
        raise ValueError("retrieved text contains content outside cited source spans")
    return resolved
