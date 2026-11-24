"""Bounded source-exact continuation for already packed prose context.

This helper only extends an existing record with complete source sentences. It
does not retrieve, summarize, rewrite, authorize or truncate evidence.
"""
from __future__ import annotations

import copy
import hashlib
import re

from ..chunking.boundary_cost import abbreviation_match, sentence_end_matches
from ..chunking.chunk_views import eligible_with_context, materialize, source_spans
from .neighbor_context import partition
from ..chunking.token_budget import contextualize

CONTINUATION_CONTEXT_VERSION = "idp-continuation-context-1"
MAX_CONTINUATION_SCAN_CHARS = 4096
MAX_SENTENCE_CANDIDATES = 16
_NOTE = re.compile(r"^\s*\(\d+\)\s+")
_STRUCTURED = re.compile(r"^\s*(?:#{1,6}\s|```|~~~|\|.*\||[-+*•]\s|\d+[.)]\s|>|\$\$|\\\[)")
_TERMINAL = re.compile(r"[.!?。！？][\"'’”»\)\]]*$")


def _render(records):
    return "\n\n".join(f"[{record['id']}]\n{record['search_text']}" for record in records)


def _sentence_ends(text, *, include_final=True):
    """Complete sentence endpoints; trailing paragraph whitespace is excluded."""
    result = []
    for match in sentence_end_matches(text):
        point = match.start() + len(match.group(0).rstrip())
        preceding = text[max(0, match.start() - 18):match.start() + 1].rstrip()
        if abbreviation_match(preceding):
            continue
        result.append(point)
    if include_final and text.rstrip() and _TERMINAL.search(text.rstrip()):
        point = len(text.rstrip())
        preceding = text[max(0, point - 18):point]
        if not abbreviation_match(preceding):
            result.append(point)
    return sorted(set(result))


def _paragraphs(text, start, limit=None):
    """Return nonempty parent-text paragraphs with absolute parent intervals."""
    tail = text[start:limit]
    cuts = [0]
    cuts.extend(match.end() for match in re.finditer(r"\n[ \t]*\n+", tail))
    cuts.append(len(tail))
    result = []
    for left, right in zip(cuts, cuts[1:]):
        value = tail[left:right]
        if value.strip():
            a = start + left
            b = start + right
            while a < b and text[a].isspace():
                a += 1
            while b > a and text[b - 1].isspace():
                b -= 1
            if a < b:
                result.append((a, b, text[a:b]))
    return result


def _is_prose(parent):
    return (not parent.get("atomic") and parent.get("kind", "text") in {"text", "quote"}
            and parent.get("unit_kind", "prose") == "prose")


def _unfinished_body(text):
    """Check the final non-note paragraph, allowing complete trailing notes."""
    paragraphs = _paragraphs(text, 0)
    notes = 0
    for _, _, value in reversed(paragraphs):
        if not _NOTE.match(value):
            break
        notes += 1
        if notes > 12:
            return False
    body = next((value for _, _, value in reversed(paragraphs) if not _NOTE.match(value)), None)
    if not body or _STRUCTURED.match(body.lstrip()):
        return False
    return not bool(_TERMINAL.search(body.rstrip()))


def _covered_source_ranges(items, source_id, exclude_index):
    ranges = []
    for index, record in enumerate(items):
        if index == exclude_index or record.get("source_id") != source_id:
            continue
        for span in record.get("source_spans", []):
            ranges.append((span.get("source_start"), span.get("source_end")))
    return ranges


def _next_body(parent_text, end, limit):
    paragraphs = _paragraphs(parent_text, end, limit)
    if not paragraphs:
        return None, "not_supported"
    note_count = 0
    index = 0
    while index < len(paragraphs) and _NOTE.match(paragraphs[index][2]):
        note_count += 1
        if note_count > 12:
            return None, "not_supported"
        index += 1
    if index >= len(paragraphs):
        return None, "not_supported"
    body = paragraphs[index]
    value = body[2].lstrip()
    if _STRUCTURED.match(value):
        return None, "not_supported"
    # Continuation detection is deliberately lexical and generic: lowercase
    # starts after an unfinished prose span can continue it without topic rules.
    if not value or not value[0].islower():
        return None, "not_supported"
    return (body, note_count), None


def extend_continuations(bundle: dict, context: dict, *, allowed_child_ids: set,
                         counter, max_tokens: int, max_extra_tokens: int = 128) -> dict:
    """Extend eligible unfinished prose records by complete source sentences.

    The returned object is a deep copy of ``context``. Existing records are
    never dropped or edited except that a supported target record is replaced
    by a source-exact larger interval. All full-context and standalone extension
    costs use the caller's exact counter.
    """
    if not isinstance(context, dict) or not isinstance(context.get("items"), list):
        raise ValueError("context with an items list is required")
    if not isinstance(allowed_child_ids, set):
        raise ValueError("an explicit current set of allowed_child_ids is required")
    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    if type(max_extra_tokens) is not int or max_extra_tokens < 1:
        raise ValueError("max_extra_tokens must be a positive integer")
    if counter.count("") > max_tokens:
        raise ValueError("budget cannot accommodate tokenizer special tokens")

    output = copy.deepcopy(context)
    items = output["items"]
    child_rows, parent_rows = bundle.get("children", []), bundle.get("parents", [])
    children = {child["id"]: child for child in child_rows}
    parents = {parent["id"]: parent for parent in parent_rows}
    if len(children) != len(child_rows) or len(parents) != len(parent_rows):
        raise ValueError("duplicate chunk IDs in continuation source bundle")
    eligible = {cid for cid, child in children.items()
                if cid in allowed_child_ids and child.get("retrieval_eligible")}
    eligible = eligible_with_context(children, parents, eligible)
    rendered_base = _render(items)
    base_context = output.get("context", rendered_base)
    if base_context != rendered_base:
        raise ValueError("context text does not match its evidence items")
    base_count = counter.count(base_context)
    if base_count > max_tokens:
        raise ValueError("incoming context already exceeds the exact token budget")
    if output.get("budget_count") is not None and output["budget_count"] != base_count:
        raise ValueError("incoming context budget_count does not match the exact counter")
    trace = {"version": CONTINUATION_CONTEXT_VERSION, "max_extra_tokens": max_extra_tokens,
        "max_scan_chars": MAX_CONTINUATION_SCAN_CHARS,
        "max_sentence_candidates": MAX_SENTENCE_CANDIDATES, "work_limit_capped": False,
        "base_count": base_count, "attempted_count": 0, "applied_count": 0,
        "added_child_ids": [], "attempts": []}

    def block(record, reason, *, parent_id=None, **extra):
        trace["attempted_count"] += 1
        trace["attempts"].append({"record_id": record.get("id"), "parent_id": parent_id,
            "status": "blocked", "reason": reason, **extra})

    # Work from a stable snapshot; successful replacements never create a new
    # candidate in this pass.
    for index, original in enumerate(list(items)):
        child_ids = original.get("child_ids")
        if not isinstance(child_ids, list) or not child_ids or any(cid not in children for cid in child_ids):
            continue
        parent_ids = {children[cid].get("parent_id") for cid in child_ids}
        if len(parent_ids) != 1:
            continue
        parent_id = next(iter(parent_ids))
        parent = parents.get(parent_id)
        if not parent or not _is_prose(parent):
            continue
        if not partition(parent, children):
            block(original, "invalid_partition", parent_id=parent_id)
            continue
        start, end = original.get("parent_start"), original.get("parent_end")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(parent["text"])
                or original.get("text") != parent["text"][start:end]
                or original.get("source_id") != parent.get("source_id")):
            block(original, "not_supported", parent_id=parent_id, detail="record_interval_mismatch")
            continue
        interval_children = [cid for cid in parent["child_ids"]
            if children[cid]["parent_start"] < end and start < children[cid]["parent_end"]]
        if set(interval_children) != set(child_ids):
            block(original, "invalid_partition", parent_id=parent_id, detail="record_child_membership")
            continue
        if any(cid not in eligible or children[cid].get("unit_kind", "prose") != "prose" for cid in child_ids):
            block(original, "authorization", parent_id=parent_id)
            continue
        if not _unfinished_body(original["text"]):
            block(original, "not_supported", parent_id=parent_id, detail="already_complete")
            continue
        safe_end = len(parent["text"])
        auth_barrier = False
        for cid in parent["child_ids"]:
            child = children[cid]
            if child["parent_end"] <= end:
                continue
            if cid not in eligible or child.get("unit_kind", "prose") != "prose":
                safe_end = max(end, child["parent_start"])
                auth_barrier = True
                break
        scan_end = min(safe_end, end + MAX_CONTINUATION_SCAN_CHARS)
        scan_capped = scan_end < safe_end
        continuation, reason = _next_body(parent["text"], end, scan_end)
        if reason:
            work_limited = scan_capped
            trace["work_limit_capped"] |= work_limited
            blocked_reason = ("work_limit" if work_limited else
                              "authorization" if auth_barrier else reason)
            block(original, blocked_reason, parent_id=parent_id, work_limit_capped=work_limited,
                  authorization_barrier=auth_barrier)
            continue
        body, note_count = continuation
        body_start, body_end, body_text = body
        body_scan_capped = scan_capped and body_end == scan_end
        # Notes are preserved between the original tail and continuation. Any
        # held child in that interval stops the extension before source access.
        proposed_ends = _sentence_ends(body_text, include_final=not body_scan_capped)
        proposed_ends = [body_start + point for point in proposed_ends if body_start + point <= body_end]
        candidate_limit_capped = len(proposed_ends) > MAX_SENTENCE_CANDIDATES
        if candidate_limit_capped:
            proposed_ends = proposed_ends[:MAX_SENTENCE_CANDIDATES]
        work_limit_capped = body_scan_capped or candidate_limit_capped
        trace["work_limit_capped"] |= work_limit_capped
        if not proposed_ends:
            block(original, "work_limit" if work_limit_capped else "not_supported",
                  parent_id=parent_id, detail="no_complete_sentence",
                  work_limit_capped=work_limit_capped,
                  authorization_barrier=auth_barrier, candidate_endpoints_considered=0)
            continue

        chosen = None
        candidate_counts = []
        blocked_reason = None
        blocked_detail = None
        overlaps = _covered_source_ranges(items, original.get("source_id"), index)
        for new_end in proposed_ends:
            extension_text = parent["text"][end:new_end]
            candidate_child_ids = [cid for cid in parent["child_ids"]
                if children[cid]["parent_start"] < new_end and end < children[cid]["parent_end"]]
            if any(cid not in eligible for cid in candidate_child_ids):
                blocked_reason = "authorization"
                continue
            if any(children[cid].get("unit_kind", "prose") != "prose" for cid in candidate_child_ids):
                blocked_reason = "not_supported"
                continue
            added_spans = source_spans(parent, end, new_end, 0)
            if added_spans is None:
                blocked_reason = "invalid_partition"
                continue
            if any(a < span["source_end"] and span["source_start"] < b
                   for span in added_spans for a, b in overlaps
                   if type(a) is int and type(b) is int):
                blocked_reason = "not_supported"
                blocked_detail = "overlapping_existing_evidence"
                continue
            member_ids = list(dict.fromkeys([*child_ids, *candidate_child_ids]))
            signature = f"{original['id']}:{end}:{new_end}"
            new_id = "continuation_" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
            path = list(original.get("context_path", original.get("section_path", [])))
            candidate = {**original, "id": new_id,
                "text": parent["text"][start:new_end], "parent_end": new_end,
                "source_spans": source_spans(parent, start, new_end, 0),
                "child_ids": member_ids,
                "search_text": contextualize(path, parent["text"][start:new_end])}
            candidate["own_level"] = original.get("own_level", original.get("level"))
            candidate["level"] = "passage" if original.get("level") == "passage" else "continuation"
            warnings = list(dict.fromkeys([*original.get("source_quality_warnings", []),
                *(warning for cid in candidate_child_ids
                  for warning in children[cid].get("quality_warnings", []))]))
            if warnings:
                candidate["source_quality_warnings"] = warnings
            extra_count = counter.count(contextualize(path, extension_text))
            if candidate["source_spans"] is None:
                blocked_reason = "invalid_partition"
                continue
            materialized = materialize(candidate, children, parents, eligible)
            if materialized is None:
                blocked_reason = "authorization"
                continue
            proposed = list(items)
            proposed[index] = materialized
            rendered = _render(proposed)
            total_count = counter.count(rendered)
            candidate_counts.append({"end": new_end, "extra_count": extra_count,
                "context_count": total_count})
            if extra_count > max_extra_tokens or total_count > max_tokens:
                blocked_reason = "budget"
                continue
            chosen = (new_end, materialized, rendered, total_count, extra_count)

        if chosen is None:
            reason = blocked_reason or ("budget" if candidate_counts else "authorization")
            block(original, reason, parent_id=parent_id, candidate_counts=candidate_counts,
                  skipped_note_paragraphs=note_count, work_limit_capped=work_limit_capped,
                  authorization_barrier=auth_barrier, candidate_endpoints_considered=len(proposed_ends),
                  **({"detail": blocked_detail} if blocked_detail else {}))
            continue
        new_end, replacement, rendered, total_count, extra_count = chosen
        items[index] = replacement
        output["context"] = rendered
        output["budget_count"] = total_count
        trace["attempted_count"] += 1
        trace["applied_count"] += 1
        trace["added_child_ids"] = list(dict.fromkeys([*trace["added_child_ids"],
            *(cid for cid in replacement["child_ids"] if cid not in child_ids)]))
        trace["attempts"].append({"record_id": original["id"], "extended_record_id": replacement["id"],
            "parent_id": parent_id, "status": "applied", "reason": None,
            "parent_start": end, "parent_end": new_end,
            "source_spans": [{k: span[k] for k in ("source_start", "source_end", "block_id", "section_id")
                              if k in span} for span in source_spans(parent, end, new_end, 0)],
            "extra_count": extra_count,
            "context_count": total_count, "skipped_note_paragraphs": note_count,
            "work_limit_capped": work_limit_capped,
            "candidate_endpoints_considered": len(proposed_ends),
            "added_child_ids": [cid for cid in replacement["child_ids"] if cid not in child_ids]})

    if not trace["attempts"]:
        output["context"] = base_context
        output["budget_count"] = base_count
    elif counter.count(output.get("context", _render(items))) > max_tokens:
        # Defensive final assertion; no candidate that failed exact counting is
        # allowed to escape the hard context budget.
        raise ValueError("continuation extension exceeded exact context budget")
    trace["final_count"] = counter.count(output.get("context", _render(items)))
    output["continuation_extension"] = trace
    if trace["added_child_ids"]:
        output["added_continuation_child_ids"] = list(trace["added_child_ids"])
    if "selected_child_ids" in output:
        output["selected_child_ids"] = list(dict.fromkeys(
            cid for record in items for cid in record.get("child_ids", [])))
    return output
