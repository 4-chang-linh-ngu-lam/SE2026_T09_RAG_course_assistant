"""Local evaluation harness: real existing chunker + SQLite + fielded BM25.

This is not an AI Service or a production permission provider. Every retrieval
requires an external current-access decision; class/scope filters grant nothing.
"""

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

if "." in __package__:
    from ..chunking.chunking import chunk_text, validate_chunking
    from ..search.retrieval_bridge import bridge_rank
    from ..search.retrieval_lexical import FieldedBM25
    from ..search.retrieval_plan import (
        anchors,
        exercise_anchors,
        exercise_query_anchors,
        terms,
    )
else:
    from chunking.chunking import chunk_text, validate_chunking
    from search.retrieval_bridge import bridge_rank
    from search.retrieval_lexical import FieldedBM25
    from search.retrieval_plan import (
        anchors,
        exercise_anchors,
        exercise_query_anchors,
        terms,
    )

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


def _document_version(canonical):
    if canonical["schema_version"] == "idp-canonical-1":
        version = (canonical.get("source_metadata") or {}).get("document_version")
        if version is None:
            return "sha256:" + canonical["source_sha256"]
        if not isinstance(version, str) or not version.strip():
            raise ValueError("invalid legacy document version")
        return version
    return canonical["document_version"]


def iter_retrievable_blocks(canonical, *, trusted_parsers=(), block_scoped_codes=(), policy=None,
                            min_verification=None):
    blocks, _ = _retrievable(canonical, trusted_parsers, block_scoped_codes, policy, min_verification)
    yield from blocks


def _retrievable(canonical, trusted_parsers=(), block_scoped_codes=(), policy=None,
                 min_verification=None):
    """Eligible blocks in reading order, and the IDs held on approved pages.

    ``after_held``/``before_held`` mark a held (unverified or untranscribed)
    block right before/after this one on the same page, so consumers never
    read text across the gap as if it were continuous. Each block carries
    ``verification`` (trusted / verified / scored); ``min_verification``
    drops weaker blocks, which then count as held. A line held only because
    a verified formula replaces it is not a gap.
    """
    schema = canonical.get("schema_version")
    if schema == "idp-canonical-2":
        try:
            from idp.publish import iter_retrievable_blocks as validate_v2
        except ModuleNotFoundError as error:
            if error.name != "idp.publish":
                raise
            raise ValueError("Canonical v2 requires the Unified IDP publisher") from error
        return list(validate_v2(canonical)), set()
    if schema != "idp-canonical-1":
        raise ValueError("unsupported canonical schema")

    from idp.canonical import (
        SUPERSEDED_CODES, VERIFICATION_TIERS, audit_canonical, block_verification,
    )

    if min_verification is not None and min_verification not in VERIFICATION_TIERS[1:]:
        raise ValueError(f"min_verification must be one of {VERIFICATION_TIERS[1:]}")
    # None: no extra floor beyond the publication policy itself.
    floor = VERIFICATION_TIERS.index(min_verification) if min_verification else 0
    trusted = set(trusted_parsers)
    sha = canonical.get("source_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("invalid canonical source checksum")
    page_ids = [page["page_id"] for page in canonical["pages"]]
    if any(type(pid) is not int or pid < 1 for pid in page_ids) or len(page_ids) != len(set(page_ids)):
        raise ValueError("invalid or duplicate legacy canonical page")
    audit = audit_canonical(
        canonical, trusted_parsers=set(trusted_parsers),
        block_scoped_codes=frozenset(block_scoped_codes), policy=policy,
    )
    if not audit["pass"]:
        raise ValueError("Canonical v1 failed IDP structural audit")
    approved_pages = set(audit["quality"]["auto_publish_pages"])
    # Held blocks stay out of the index even though the rest of their page
    # is published.
    held_blocks = set(audit["quality"]["held_blocks"])
    output = []
    for page in canonical["pages"]:
        if page["page_id"] not in approved_pages:
            continue
        after_held = False
        previous = None
        for block in page["blocks"]:
            text = block.get("text", "")
            bbox = block.get("bbox")
            key = block.get("block_id")
            if key in held_blocks and any(
                f.get("code") in SUPERSEDED_CODES for f in block.get("review_flags") or []
            ):
                continue  # replaced by the verified formula placed after it
            tier = block_verification(block, trusted)
            if key in held_blocks or (
                isinstance(text, str) and text.strip()
                and VERIFICATION_TIERS.index(tier) < floor
                and block.get("type") not in {"PageHeader", "PageFooter", "PageNumber"}
            ):
                after_held = True
                if previous is not None:
                    previous["before_held"] = True
                if key not in held_blocks:
                    held_blocks.add(key)
                continue
            if (
                block.get("excluded")
                or block.get("retrieval_eligible") is False
                or block.get("type") in {"PageHeader", "PageFooter", "PageNumber", "Picture", "PictureGroup", "Diagram", "Chart"}
                or not isinstance(text, str)
                or not text.strip()
            ):
                continue
            if (
                not isinstance(key, str) or not key
                or not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in bbox)
                or not (0 <= bbox[0] < bbox[2] and 0 <= bbox[1] < bbox[3])
            ):
                continue
            # Legacy blocks have text and coordinates but no L1 identities.
            previous = {
                "block_id": key, "source_id": key, "text": text,
                "page": page["page_id"], "bbox": list(bbox),
                "region_id": None, "candidate_id": None, "evidence_refs": [],
                "type": block.get("type"),
                "section_path": [
                    x for x in block.get("section_path") or [] if isinstance(x, str)
                ],
                "after_held": after_held,
                "before_held": False,
                "verification": tier,
            }
            output.append(previous)
            after_held = False
    return output, held_blocks


def _blocks(canonical, trusted_parsers, block_scoped_codes=(), policy=None, min_verification=None):
    if canonical.get("schema_version") == "idp-canonical-1":
        return iter_retrievable_blocks(
            canonical, trusted_parsers=trusted_parsers,
            block_scoped_codes=block_scoped_codes, policy=policy,
            min_verification=min_verification,
        )
    return iter_retrievable_blocks(canonical)


def _drop_running(blocks, running):
    """Remove running heads/page numbers without losing a gap marker.

    A dropped line between a held block and the next text must pass its
    gap flags on; otherwise the next block would look continuous.
    """
    kept, carry = [], None
    for block in blocks:
        if block["block_id"] in running:
            if block.get("after_held"):
                carry = block["page"]
            if block.get("before_held") and kept and kept[-1]["page"] == block["page"]:
                kept[-1] = {**kept[-1], "before_held": True}
            continue
        if carry == block["page"] and not block.get("after_held"):
            block = {**block, "after_held": True}
        carry = None
        kept.append(block)
    return kept


_WINDOW_START = {"SectionHeader", "Table"}
# A page number stands alone or is set apart from the head by whitespace;
# "1.3." keeps its digits.
_EDGE_NUMBER = re.compile(r"^\s*\d+\s*$|^\s*\d+\s+|\s+\d+\s*$")


def _running_lines(canonical, min_pages=3):
    """Block IDs of page-edge lines repeated across pages (running heads).

    Counted over every canonical page, published or not, because a running
    head recurs regardless of publication. Only the first/last text block of
    a page qualifies; its text minus a leading/trailing page number must recur
    at a page edge on ``min_pages`` pages, or be a bare number. This is an
    index policy: the canonical block itself is untouched.
    """
    keyed, seen = [], {}
    for page in canonical.get("pages") or []:
        texts = [
            b for b in page.get("blocks") or []
            if not b.get("excluded") and isinstance(b.get("text"), str) and b["text"].strip()
        ]
        if not texts:
            continue
        for block in {id(b): b for b in (texts[0], texts[-1])}.values():
            text = block["text"].strip()
            if len(text) > 160:
                continue
            key = " ".join(_EDGE_NUMBER.sub("", text).casefold().split())
            keyed.append((block.get("block_id"), key))
            if key:
                seen.setdefault(key, set()).add(page.get("page_id"))
    # A recurring key needs two words: "Chương 1".."Chương 3" reduce to one
    # repeated word but are chapter headings, not running heads.
    return {
        block_id for block_id, key in keyed
        if not key or (
            len(re.findall(r"[^\W\d_]{2,}", key)) >= 2
            and len(seen.get(key, ())) >= min_pages
        )
    }


def _paragraph_windows(blocks, counter, max_tokens):
    """Consecutive same-page blocks, opened by a heading, within the budget.

    A heading or caption alone ranks above the paragraph that answers; a
    window keeps them together. Tables stay their own unit. Citations remain
    per block through the chunk's source spans.
    """
    windows, current, used = [], [], 0
    for block in blocks:
        size = counter.count(block["text"])
        if current and (
            block["page"] != current[-1]["page"]
            # Never join text across held (unverified) source between them:
            # a statement with a missing middle must not read as complete.
            or block.get("after_held")
            or block.get("type") in _WINDOW_START
            or current[-1].get("type") == "Table"
            or used + size > max_tokens
        ):
            windows.append(current)
            current, used = [], 0
        current.append(block)
        used += size
    if current:
        windows.append(current)
    return windows


_TIER_ORDER = ("none", "scored", "verified", "trusted")


def _weakest(tiers):
    known = [t for t in tiers if t in _TIER_ORDER]
    return min(known, key=_TIER_ORDER.index) if known else None


def build_chunks(canonical, *, max_tokens=256, trusted_parsers=(), block_scoped_codes=(),
                 paragraph_windows=False, policy=None, min_verification=None):
    if canonical.get("schema_version") == "idp-canonical-1":
        blocks, held = _retrievable(canonical, trusted_parsers, block_scoped_codes, policy,
                                    min_verification)
    else:
        blocks, held = list(_blocks(canonical, trusted_parsers)), set()
    if paragraph_windows:
        blocks = _drop_running(blocks, _running_lines(canonical))
    version = _document_version(canonical)
    by_source = {b["source_id"]: b for b in blocks}
    groups, assigned = [], set()
    question_groups = (
        canonical.get("question_groups", ())
        if canonical["schema_version"] == "idp-canonical-1"
        else canonical["structures"].get("questions", ())
    )
    atomic = {g["id"] for g in question_groups if g.get("status") != "needs_review"}
    for group in question_groups:
        keys = [r["block_id"] for r in group["source_blocks"]]
        context = [r["block_id"] for r in group.get("shared_context_segments", ())]
        keys = list(dict.fromkeys(context + keys))
        if not keys or any(key not in by_source for key in keys):
            # Do not index a partial question after publication excludes data.
            # A detector-flagged group (status "needs_review") is only an
            # unverified grouping guess, e.g. a memo whose "A."/"4" tokens look
            # like options. It must not also withhold the publication-approved
            # blocks, which are then indexed as ordinary standalone text with
            # no question identity. Structurally grouped questions stay
            # withheld as a whole, as the phase-4 contract requires.
            if group.get("status") != "needs_review":
                assigned.update(keys)
            elif any(key in held for key in keys):
                # A guessed group that lost a member to a held (unverified or
                # untranscribed) block stays one unit, explicitly marked
                # incomplete, instead of loose fragments that read as whole
                # statements. Withholding it would drop most textbook
                # exercises, since nearly all of them contain a held formula.
                present = [by_source[key] for key in keys if key in by_source]
                assigned.update(keys)
                if present:
                    groups.append((group["id"], present, group.get("related_structures", []), True))
            continue
        unit = [by_source[key] for key in keys]
        assigned.update(keys)
        groups.append((group["id"], unit, group.get("related_structures", []), False))
    free = [b for b in blocks if b["source_id"] not in assigned]
    if paragraph_windows:
        groups.extend(
            (None, unit, [], False)
            for unit in _paragraph_windows(free, LexicalTokenBudget(), max_tokens)
        )
    else:
        groups.extend((None, [block], [], False) for block in free)
    output = []
    counter = LexicalTokenBudget()
    for question_id, unit, related_structures, incomplete in groups:
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
                version,
                [b["block_id"] for b in unit],
            ]
        )
        # Only a structurally grouped question is one atomic chunk. A guessed
        # ("needs_review") group keeps its question identity but uses the
        # normal budget: a textbook section misread as one question must not
        # become a single 2,000-character chunk.
        budget = max(max_tokens, counter.count(text)) if question_id in atomic else max_tokens
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
                            "document_version": version,
                        }
                    )
            if not references:
                raise ValueError("chunk lost source attribution")
            first, last = references[0], references[-1]
            first_block = next(b for _, _, b in spans if b["block_id"] == first["block_id"])
            last_block = next(b for _, _, b in spans if b["block_id"] == last["block_id"])
            # Held source sits right before/after this chunk's text: the
            # generator must not treat the passage as complete there.
            held_gap_before = bool(first_block.get("after_held")) and first["start"] == 0
            held_gap_after = (
                bool(last_block.get("before_held")) and last["end"] == len(last_block["text"])
            )
            section_path = child["section_path"]
            if paragraph_windows and not section_path:
                # The heading that opened a section is often on an earlier
                # window; the canonical path keeps it searchable as a title.
                section_path = next(
                    (b["section_path"] for b in unit if b.get("section_path")), []
                )
            output.append(
                {
                    **child,
                    "section_path": list(section_path),
                    "references": references,
                    "held_gap_before": held_gap_before,
                    "held_gap_after": held_gap_after,
                    # The weakest authorization among the cited blocks.
                    "verification": _weakest(
                        b.get("verification") for _, _, b in spans
                        if any(r["block_id"] == b["block_id"] for r in references)
                    ),
                    "question_id": question_id,
                    # Members of this question were held out of the index.
                    "question_incomplete": incomplete,
                    "related_structures": related_structures,
                    "original_source_sha256": canonical["source_sha256"],
                    "document_version": version,
                }
            )
    if len({c["id"] for c in output}) != len(output):
        raise ValueError("duplicate chunk identity")
    return output


PAGE_FUSION_RRF_CONSTANT = 60


def _page_rows(rows):
    """One lexical unit per (document, version, page) over eligible chunk text.

    OCR splits scanned forms and tables into many short blocks; a question
    often names a row label, a column header and a value that land in
    different chunks of the same page. A page unit sees them together.
    """
    texts, page_of = {}, {}
    for row in rows:
        keys = []
        for ref in row["references"]:
            key = f'{ref["source_sha256"]}\x1f{ref["document_version"]}\x1f{ref["page"]}'
            if key not in keys:
                keys.append(key)
        page_of[row["id"]] = keys
        for key in keys:
            texts.setdefault(key, []).append(row["text"])
    page_rows = [
        {"id": key, "text": "\n".join(parts), "section_path": []}
        for key, parts in sorted(texts.items())
    ]
    return page_rows, page_of


def _fuse_page_evidence(chunk_ranking, page_ranking, page_of):
    """Reciprocal-rank fusion of chunk BM25 with its best page's BM25 rank.

    Only reorders chunks already matched lexically; a chunk with no matched
    query term is never added. Scores are an ordering heuristic, not relevance.
    """
    k = PAGE_FUSION_RRF_CONSTANT
    page_rank = {key: rank for rank, (key, _) in enumerate(page_ranking, 1)}
    fused = []
    for rank, (identity, _) in enumerate(chunk_ranking, 1):
        best = min((page_rank[p] for p in page_of[identity] if p in page_rank), default=None)
        score = 1 / (k + rank) + (1 / (k + best) if best else 0.0)
        fused.append((identity, score))
    fused.sort(key=lambda item: (-item[1], item[0]))
    return fused


class LocalRagIndex:
    def __init__(self, path, *, page_fusion=False, bridge_seeds=0, paragraph_windows=False):
        if type(page_fusion) is not bool:
            raise ValueError("page_fusion must be bool")
        if type(bridge_seeds) is not int or not 0 <= bridge_seeds <= 4:
            raise ValueError("bridge_seeds must be an integer in 0..4")
        self.path = Path(path)
        if type(paragraph_windows) is not bool:
            raise ValueError("paragraph_windows must be bool")
        self.page_fusion = page_fusion
        self.paragraph_windows = paragraph_windows
        self.bridge_seeds = bridge_seeds
        self._lexical_snapshot = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, source_sha TEXT NOT NULL, document_version TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def index(self, canonical, *, trusted_parsers=(), block_scoped_codes=(), policy=None,
              min_verification=None):
        chunks = build_chunks(
            canonical, trusted_parsers=trusted_parsers,
            block_scoped_codes=block_scoped_codes,
            paragraph_windows=self.paragraph_windows, policy=policy,
            min_verification=min_verification,
        )
        version = _document_version(canonical)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "DELETE FROM chunks WHERE source_sha=? AND document_version=?",
                (canonical["source_sha256"], version),
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
            # Page-level statistics come from the same authorized rows only.
            page_rows, page_of = _page_rows(rows)
            snapshot = self._lexical_snapshot = (
                key, FieldedBM25(rows, fold_accents=True), by_id, labels,
                FieldedBM25(page_rows, fold_accents=True) if page_rows else None,
                page_of,
            )
        _, bm25, by_id, labels, page_bm25, page_of = snapshot
        ranked = bm25.rank(query)
        if self.bridge_seeds:
            ranked, _ = bridge_rank(bm25, query, ranked, lambda i: by_id[i]["text"],
                                    seeds=self.bridge_seeds)
        if page_bm25 is not None and self.page_fusion:
            ranked = _fuse_page_evidence(ranked, page_bm25.rank(query), page_of)
        wanted = exercise_query_anchors(anchors(query, accept_unaccented=True))
        if wanted:
            ranked.sort(key=lambda item: not wanted <= labels[item[0]])
        if not all(can_read(source, version) for source, version in allowed_documents):
            return []
        return [
            {**deepcopy(by_id[identity]), "score": score}
            for identity, score in ranked[:top_k]
        ]


def citation_index(canonical, *, trusted_parsers=(), block_scoped_codes=(), policy=None,
                   min_verification=None):
    """Eligible blocks by ID, audited once; pass to ``resolve_citation``.

    Resolving many hits against one document should not re-audit the whole
    document (and stat every asset) per hit.
    """
    return {
        "source_sha256": canonical.get("source_sha256"),
        "document_version": _document_version(canonical),
        "blocks": {
            b["block_id"]: b
            for b in _blocks(canonical, trusted_parsers, block_scoped_codes, policy,
                             min_verification)
        },
    }


def resolve_citation(hit, canonical, *, trusted_parsers=(), block_scoped_codes=(), policy=None,
                     index=None, min_verification=None):
    if index is None:
        index = citation_index(
            canonical, trusted_parsers=trusted_parsers,
            block_scoped_codes=block_scoped_codes, policy=policy,
            min_verification=min_verification,
        )
    elif (
        index["source_sha256"] != canonical["source_sha256"]
        or index["document_version"] != _document_version(canonical)
    ):
        raise ValueError("citation index belongs to another document/version")
    by_id = index["blocks"]
    version = _document_version(canonical)
    if (
        hit["original_source_sha256"] != canonical["source_sha256"]
        or hit["document_version"] != version
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
            or reference["document_version"] != version
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
