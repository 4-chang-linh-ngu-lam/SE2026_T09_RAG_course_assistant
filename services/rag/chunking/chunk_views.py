"""Pure construction helpers for bounded cross-parent chunk context refs.

Callers must enforce their authorization and budget policies. These helpers
fail closed on malformed references and prove the referenced parent partition
before reading its text.
"""
from __future__ import annotations

import hashlib

from .token_budget import contextualize


def _partition(parent, children):
    ids = parent.get("child_ids")
    if not isinstance(ids, list) or not ids:
        return False
    try:
        if len(ids) != len(set(ids)):
            return False
    except TypeError:
        return False
    cursor = 0
    for cid in ids:
        child = children.get(cid)
        if not child:
            return False
        a, b = child.get("parent_start"), child.get("parent_end")
        if (type(a) is not int or type(b) is not int or a != cursor or not a < b <= len(parent.get("text", ""))
                or child.get("text") != parent["text"][a:b]
                or child.get("parent_id") != parent.get("id")
                or child.get("source_id") != parent.get("source_id")):
            return False
        cursor = b
    if cursor != len(parent.get("text", "")):
        return False
    parent_spans = parent.get("source_spans", [])
    if (not isinstance(parent_spans, list)
            or any(not _valid_span(parent["text"], span) for span in parent_spans)
            or not _ordered_span_coverage(parent["text"], parent_spans)):
        return False
    for cid in ids:
        child = children[cid]
        child_spans = child.get("source_spans", [])
        if (not isinstance(child_spans, list)
                or any(not _valid_span(child["text"], span) for span in child_spans)
                or not _ordered_span_coverage(child["text"], child_spans)):
            return False
        expected = []
        ca, cb = child["parent_start"], child["parent_end"]
        for span in parent_spans:
            left, right = max(ca, span["start"]), min(cb, span["end"])
            if left < right:
                expected.append((left - ca, right - ca,
                    span.get("block_id"), span.get("section_id"),
                    span["source_start"] + left - span["start"],
                    span["source_start"] + right - span["start"]))
        actual = [(span["start"], span["end"], span.get("block_id"), span.get("section_id"),
                   span["source_start"], span["source_end"]) for span in child_spans]
        if actual != expected:
            return False
    return True


def partition(parent, children):
    """Public structural proof used by retrieval and packing stages."""
    return _partition(parent, children)


def _valid_span(text, span):
    try:
        a, b = span["start"], span["end"]
        sa, sb = span["source_start"], span["source_end"]
        return (type(a) is int and type(b) is int and type(sa) is int and type(sb) is int
                and 0 <= a < b <= len(text) and sa < sb and b - a == sb - sa
                and span.get("text_sha256") == hashlib.sha256(text[a:b].encode("utf-8")).hexdigest())
    except (KeyError, TypeError, AttributeError):
        return False


def _ordered_span_coverage(text, spans):
    """Require ordered disjoint spans and only whitespace gaps in text coverage."""
    cursor = 0
    for span in spans:
        a, b = span["start"], span["end"]
        if a < cursor or text[cursor:a].strip():
            return False
        cursor = b
    return not text[cursor:].strip()


def _reference(ref, owner, children, parents):
    if not isinstance(ref, dict):
        return None
    pid, a, b = ref.get("parent_id"), ref.get("start"), ref.get("end")
    parent = parents.get(pid)
    if (not parent or type(a) is not int or type(b) is not int or not 0 <= a < b <= len(parent.get("text", ""))
            or ref.get("role") not in {"table_header", "shared_passage"}
            or not _partition(parent, children)
            or parent.get("source_id") != owner.get("source_id")):
        return None
    return parent


def dependency_ids(child, children, parents):
    """Return child IDs intersecting this child's refs, or None if any ref is invalid."""
    result = set()
    owner = children.get(child.get("id"), child)
    for ref in owner.get("context_refs", []):
        parent = _reference(ref, owner, children, parents)
        if parent is None:
            return None
        a, b = ref["start"], ref["end"]
        for cid in parent["child_ids"]:
            member = children[cid]
            if member["parent_start"] < b and a < member["parent_end"]:
                result.add(cid)
    return result


def _own_ranges(record, parent_id, parent, children):
    ranges = []
    if record.get("parent_id") == parent_id:
        a, b = record.get("parent_start"), record.get("parent_end")
        if type(a) is not int or type(b) is not int or not 0 <= a <= b <= len(parent["text"]):
            return None
        if record.get("text") != parent["text"][a:b]:
            return None
        ranges.append((a, b))
    else:
        # A combined record may expose source spans but no parent interval.
        for cid in record.get("child_ids", []):
            child = children.get(cid)
            if child and child.get("parent_id") == parent_id:
                ranges.append((child["parent_start"], child["parent_end"]))
    return ranges


def _subtract(interval, covered):
    parts = [interval]
    for x, y in sorted(covered):
        next_parts = []
        for a, b in parts:
            if y <= a or b <= x:
                next_parts.append((a, b))
            else:
                if a < x:
                    next_parts.append((a, x))
                if y < b:
                    next_parts.append((y, b))
        parts = next_parts
    return [(a, b) for a, b in parts if a < b]


def _source_spans(parent, a, b, shift):
    spans = []
    for span in parent.get("source_spans", []):
        left, right = max(a, span["start"]), min(b, span["end"])
        if left >= right:
            continue
        # Source ranges must map codepoint-for-codepoint to parent text.
        if span["end"] - span["start"] != span["source_end"] - span["source_start"]:
            return None
        source_start = span["source_start"] + left - span["start"]
        source_end = source_start + right - left
        text_hash = hashlib.sha256(parent["text"][left:right].encode("utf-8")).hexdigest()
        spans.append({**span, "start": shift + left - a, "end": shift + right - a,
                      "source_start": source_start, "source_end": source_end})
        spans[-1]["text_sha256"] = text_hash
    return spans


def source_spans(parent, a, b, shift=0):
    """Map a parent interval to exact source spans."""
    return _source_spans(parent, a, b, shift)


def index_parts(child, parents) -> tuple[str, str]:
    """Construct contextualized index text and unprefixed index body from valid refs."""
    refs = {}
    for ref in child.get("context_refs", []):
        if not isinstance(ref, dict) or ref.get("index") is not True:
            continue
        pid = ref.get("parent_id")
        parent = parents.get(pid)
        if not parent or (child.get("source_id") is not None
                          and child.get("source_id") != parent.get("source_id")):
            continue
        a, b = ref.get("start"), ref.get("end")
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(parent.get("text", "")):
            continue
        refs.setdefault(pid, {"parent": parent, "intervals": []})["intervals"].append((a, b))
    pieces = []
    for pid, group in refs.items():
        covered = []
        if child.get("parent_id") == pid:
            a, b = child.get("parent_start"), child.get("parent_end")
            if type(a) is int and type(b) is int and 0 <= a <= b <= len(group["parent"]["text"]):
                covered.append((a, b))
        merged = []
        for a, b in sorted(group["intervals"]):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        for interval in merged:
            for a, b in _subtract(interval, covered):
                pieces.append((group["parent"], a, b))
    pieces.sort(key=lambda item: (item[0].get("source_id", ""),
                                 min((span["source_start"] + max(item[1], span["start"]) - span["start"]
                                      for span in item[0].get("source_spans", [])
                                      if span["start"] < item[2] and item[1] < span["end"]), default=10**30),
                                 item[1]))
    own = child.get("text", "")
    body = "\n\n".join([*(parent["text"][a:b] for parent, a, b in pieces), own])
    return contextualize(child.get("context_path", child.get("section_path", [])), body), body


def index_text(child, parents) -> str:
    """Construct contextualized index text from valid referenced slices and own text."""
    return index_parts(child, parents)[0]


def materialize(record, children, parents, eligible):
    """Add authorized raw reference slices to a record; return None on invalid refs."""
    member_ids = record.get("child_ids", [])
    if isinstance(member_ids, list) and not any(
            children.get(cid, {}).get("context_refs", []) for cid in member_ids):
        return record
    if not isinstance(member_ids, list) or not member_ids or any(cid not in children or cid not in eligible for cid in member_ids):
        return None
    refs = []
    for cid in member_ids:
        owner = children[cid]
        if owner.get("source_id") != record.get("source_id"):
            return None
        for ref in owner.get("context_refs", []):
            if not isinstance(ref, dict):
                return None
            parent = parents.get(ref.get("parent_id"))
            a, b = ref.get("start"), ref.get("end")
            if (not parent or type(a) is not int or type(b) is not int
                    or not 0 <= a < b <= len(parent.get("text", ""))):
                return None
            ids = parent.get("child_ids", [])
            if not isinstance(ids, list) or not ids or any(item not in children for item in ids):
                return None
            covering = [children[item] for item in ids
                        if children[item].get("parent_start", 0) < b
                        and a < children[item].get("parent_end", 0)]
            # Check the entire dependency set before inspecting referenced text.
            if not covering or any(item["id"] not in eligible or item.get("source_id") != record.get("source_id")
                                   for item in covering):
                return None
            parent = _reference(ref, owner, children, parents)
            if parent is None:
                return None
            refs.append((parent, ref))
    if not refs:
        return record

    # Union refs by parent, retaining roles and excluding source already in record.
    grouped = {}
    for parent, ref in refs:
        grouped.setdefault(parent["id"], {"parent": parent, "intervals": [], "roles": set()})
        grouped[parent["id"]]["intervals"].append((ref["start"], ref["end"]))
        grouped[parent["id"]]["roles"].add(ref["role"])
    slices = []
    for pid, group in grouped.items():
        parent = group["parent"]
        covered = _own_ranges(record, pid, parent, children)
        if covered is None:
            return None
        merged = []
        for a, b in sorted(group["intervals"]):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        for a, b in merged:
            for left, right in _subtract((a, b), covered):
                slices.append((pid, left, right, parent, sorted(group["roles"])))
    # Keep source order, then stable parent/offset order for ties.
    def source_order(item):
        pid, a, b, parent, _ = item
        spans = [s for s in parent.get("source_spans", []) if s["start"] < b and a < s["end"]]
        return (min((s["source_start"] + max(a, s["start"]) - s["start"] for s in spans), default=10**30), pid, a)
    slices.sort(key=source_order)
    if not slices:
        return record

    text_parts, roles, owner_ids = [], [], set(member_ids)
    source_warnings = list(record.get("source_quality_warnings", []))
    text = record.get("text", "")
    offset = 0
    prefix_spans = []
    for _, a, b, parent, ref_roles in slices:
        piece = parent["text"][a:b]
        if text_parts:
            text_parts.append("\n\n")
            offset += 2
        new_spans = _source_spans(parent, a, b, offset)
        if new_spans is None:
            return None
        prefix_spans.extend(new_spans)
        text_parts.append(piece)
        offset += b - a
        roles.extend(role for role in ref_roles if role not in roles)
        for cid in parent["child_ids"]:
            child = children[cid]
            if child["parent_start"] < b and a < child["parent_end"]:
                owner_ids.add(cid)
                for warning in child.get("quality_warnings", []):
                    if warning not in source_warnings:
                        source_warnings.append(warning)
    prefix_text = "".join(text_parts)
    separator = "\n\n" if prefix_text and text else ""
    new_text = prefix_text + separator + text
    shift = len(prefix_text) + len(separator)
    source_spans = prefix_spans + [
        {**span, "start": span["start"] + shift, "end": span["end"] + shift}
        for span in record.get("source_spans", [])
    ]
    output = {**record, "text": new_text, "source_spans": source_spans,
              "child_ids": sorted(owner_ids), "context_roles": roles}
    output["own_level"] = record.get("level", "child")
    output["level"] = "contextualized"
    output["context_view_version"] = "idp-source-context-view-1"
    output["source_quality_warnings"] = source_warnings
    output["search_text"] = contextualize(record.get("context_path", record.get("section_path", [])), new_text)
    return output


def eligible_with_context(children, parents, eligible):
    """Filter raw eligible IDs to those whose referenced owners are eligible."""
    allowed = set(eligible)
    result = set()
    for cid in allowed:
        child = children.get(cid)
        if child is None:
            continue
        dependencies = dependency_ids(child, children, parents)
        if dependencies is not None and dependencies <= allowed:
            result.add(cid)
    return result
