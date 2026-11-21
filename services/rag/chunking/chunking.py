"""Structure-first text chunking for the RAG pipeline.

This module owns only derived chunking artifacts; it does not publish to an
index or grant retrieval access. Inputs are UTF-8 Markdown or plain text.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .atomic_io import atomic_write_text
from .boundary_cost import candidate_points, merge_protected, normalize_policy, quoted_spans, split_cost
from .chunk_boundaries import BOUNDARY_PACKETS_VERSION, fitting_layout_ranges
from .chunk_relations import RELATIONS_VERSION, child_refs, shared_passages
from .chunk_views import index_text
from .text_atoms import inspect_table, math_closed
from .hierarchy import HIERARCHY_VERSION, build_hierarchy
from .text_source import TEXT_SOURCE_VERSION, parse_text
from .text_units import TEXT_UNITS_VERSION, plan_units
from .token_budget import LocalTokenizer, PrefixCounter, Utf8Budget, contextualize

CHUNKING_VERSION = "idp-text-chunking-7"
_PROTECTED = re.compile(r"(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$|(?<!\\)\$[^$\n]+?(?<!\\)\$|\\\([\s\S]*?\\\)|`[^`\n]+`")


def protected_spans(text: str) -> list[tuple[int, int]]:
    """Return protected formula/code spans for downstream text packing."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return [(match.start(), match.end()) for match in _PROTECTED.finditer(text)]


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_text(text: str, path: list[str], counter, limit: int, *,
               protected_ranges=()) -> list[tuple[int, int, str | None]]:
    """Exact, disjoint slices. Prefer paragraph, sentence, word, then character.

    Character fallback never cuts a combining sequence, inline math or code.
    Token counts are checked on the exact contextualized string, not estimated
    by adding per-piece counts. A non-monotonic tokenizer may underfill a slice;
    the emitted input still has to pass the actual budget check.
    """
    def fits(a, b):
        return counter.count(contextualize(path, text[a:b])) <= limit

    if fits(0, len(text)):
        return [(0, len(text), None)]
    if counter.count(contextualize(path, "")) >= limit:
        return [(0, len(text), "breadcrumb_exceeds_budget")]
    protected = merge_protected([(m.start(), m.end()) for m in _PROTECTED.finditer(text)] + list(protected_ranges))
    preferred = [[m.end() for m in re.finditer(r"\n[ \t]*\n+", text)],
                 candidate_points(text)[1:-1],
                 [m.end() for m in re.finditer(r"\s+", text)]]

    def can_cut(pos):
        if pos < len(text) and (unicodedata.combining(text[pos])
                or text[pos] in {"\u200d", "\ufe0e", "\ufe0f"} or text[pos - 1:pos] == "\u200d"):
            return False
        return not any(a < pos < b for a, b in protected)

    result, start = [], 0
    while start < len(text):
        if fits(start, len(text)):
            result.append((start, len(text), None))
            break
        low, high = start, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if fits(start, middle):
                low = middle
            else:
                high = middle - 1
        end = low
        while end > start and not can_cut(end):
            end -= 1
        # Token counts need not be monotonic after moving to a safe boundary.
        while end > start and not fits(start, end):
            end -= 1
            while end > start and not can_cut(end):
                end -= 1
        if end == start:
            # Isolate only the oversized protected span/grapheme, then resume.
            # Previously this discarded prior cuts and held the entire parent.
            end = next((b for a, b in protected if a <= start < b), start + 1)
            while end < len(text) and not can_cut(end):
                end += 1
            result.append((start, end, "indivisible_text_exceeds_budget"))
            start = end
            continue
        for boundaries in preferred:
            index = bisect_right(boundaries, end) - 1
            while index >= 0 and boundaries[index] > start:
                point = boundaries[index]
                if can_cut(point) and text[start:point].strip() and fits(start, point):
                    end = point
                    break
                index -= 1
            else:
                continue
            break
        result.append((start, end, None))
        start = end
    return result


def _child_spans(parent, start, end):
    spans = []
    for span in parent["source_spans"]:
        a, b = max(start, span["start"]), min(end, span["end"])
        if a >= b:
            continue
        source_start = span["source_start"] + a - span["start"]
        spans.append({"block_id": span["block_id"], "start": a - start, "end": b - start,
            "source_start": source_start, "source_end": source_start + b - a,
            "section_id": span["section_id"],
            "text_sha256": _sha(parent["text"][a:b])})
    return spans


def _table_ranges(parent, counter, limit):
    text, path = parent["text"], parent["context_path"]
    table = inspect_table(text)
    if not table["valid"]:
        return split_text(text, path, counter, limit), "table_raw_text_fallback"
    # A single column has no inter-column relationships to reconstruct. Keep
    # literal Markdown as source prose, including long narrative header cells.
    if table["columns"] == 1:
        return split_text(text, path, counter, limit), "single_column_text"
    header_end = table["header_end"]
    header = text[:header_end]
    def count(a, b):
        value = text[a:b] if a == 0 else header + "\n\n" + text[a:b]
        return counter.count(contextualize(path, value))
    if count(0, len(text)) <= limit:
        return [(0, len(text), None)], "table_whole"
    if count(0, header_end) > limit:
        return [(0, len(text), "table_header_exceeds_budget")], "table_header_overflow"
    points = [header_end, *(b for _, b in table["rows"])]
    result, start, point_index = [], 0, 0
    while start < len(text):
        # Exact checks at row boundaries; binary search is a packing heuristic,
        # never a proof that arbitrary tokenizer counts are monotonic.
        low, high, best = point_index, len(points) - 1, None
        while low <= high:
            middle = (low + high) // 2
            if count(start, points[middle]) <= limit:
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if best is None:
            end = points[point_index]
            result.append((start, end, "table_row_exceeds_budget"))
            point_index += 1
        else:
            end = points[best]
            result.append((start, end, None))
            point_index = best + 1
        start = end
    return result, "table_rows"


def _parent_ranges(parent, counter, config):
    limit = config["max_input_budget"]
    diagnostic = {"requested_strategy": config["split_strategy"],
        "used_strategy": "atomic" if parent["atomic"] else "greedy", "fallback_reason": None,
        "candidate_units": 0, "transition_checks": 0, "objective": None}
    if parent["kind"] == "table":
        ranges, diagnostic["used_strategy"] = _table_ranges(parent, counter, limit)
        return ranges, diagnostic
    if parent["kind"] == "math" and not math_closed(parent["text"]):
        return [(0, len(parent["text"]), "unsupported_math_structure")], diagnostic
    if not parent["atomic"] and config["split_strategy"] == "cost":
        protected = [(m.start(), m.end()) for m in _PROTECTED.finditer(parent["text"])]
        protected += quoted_spans(parent["text"])
        if config["format"] == "markdown":
            for span in parent["source_spans"]:
                value = parent["text"][span["start"]:span["end"]]
                if value.startswith(">") and not re.search(r"(?m)^(?:>\s*)+#{1,6}\s+", value):
                    protected.append((span["start"], span["end"]))
        return split_cost(parent["text"], parent["context_path"], counter, limit,
                          config["boundary_policy"], protected=protected, fallback=split_text)
    if not parent["atomic"]:
        if counter.count(contextualize(parent["context_path"], parent["text"])) <= limit:
            return [(0, len(parent["text"]), None)], diagnostic
        hard = [(m.start(), m.end()) for m in _PROTECTED.finditer(parent["text"])]
        protected = fitting_layout_ranges(parent["text"], parent["context_path"], counter, limit,
                                         hard_ranges=hard)
        return split_text(parent["text"], parent["context_path"], counter, limit,
                          protected_ranges=protected), diagnostic
    reason = "atomic_block_exceeds_budget" if counter.count(
        contextualize(parent["context_path"], parent["text"])) > limit else None
    return [(0, len(parent["text"]), reason)], diagnostic


def _flags(parent, reason, unit):
    flags = [reason] if reason else []
    if not parent["source_closed"]:
        flags.append("unclosed_source_block")
    if reason in {"unsupported_table_structure", "unsupported_math_structure"}:
        flags.append("deferred_content_kind")
    if unit != "tokens":
        flags.append("diagnostic_byte_budget")
    return flags


def _warnings(parent):
    return ["unstructured_table_text"] if parent["kind"] == "table" and not inspect_table(parent["text"])["valid"] else []


def chunk_text(text: str, *, counter, source_id: str, format: str = "markdown",
               max_tokens: int = 384, split_strategy: str = "greedy", boundary_policy: dict | None = None) -> dict:
    """Build a source tree, logical content parents and budgeted search children.

    max_tokens is in the supplied counter's declared unit; byte diagnostics
    remain explicitly ineligible for indexing. This is not a production grant.
    """
    if not isinstance(text, str) or not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("text and a nonempty source_id are required")
    if type(max_tokens) is not int or not 8 <= max_tokens <= 65536:
        raise ValueError("max_tokens must be an integer in 8..65536")
    if split_strategy not in {"greedy", "cost"}:
        raise ValueError("split_strategy must be greedy or cost")
    if boundary_policy is not None and split_strategy != "cost":
        raise ValueError("boundary_policy requires split_strategy=cost")
    policy = normalize_policy(boundary_policy, max_tokens) if split_strategy == "cost" else None
    identity = dict(counter.identity)
    if identity.get("unit") not in {"tokens", "utf8_bytes"}:
        raise ValueError("counter must declare tokens or utf8_bytes")
    blocks = parse_text(text, format=format)
    config = {"version": CHUNKING_VERSION, "hierarchy_version": HIERARCHY_VERSION,
        "source_reader": TEXT_SOURCE_VERSION, "unit_reader": TEXT_UNITS_VERSION, "format": format,
        "max_input_budget": max_tokens, "counter": identity}
    config.update(split_strategy=split_strategy, boundary_policy=policy,
                  boundary_packets=BOUNDARY_PACKETS_VERSION if split_strategy == "greedy" else None,
                  content_policy="idp-text-atoms-1", relations=RELATIONS_VERSION)
    document_id = _sha(source_id + "\0" + text)[:20]
    export_id = _sha(document_id + json.dumps(config, sort_keys=True))[:20]
    nodes, assignments = build_hierarchy(blocks, document_id)
    by_node = {n["id"]: n for n in nodes}
    parents = []
    source_blocks = {b["id"]: b for b in blocks}
    for plan in plan_units(blocks, nodes, assignments):
        section = plan["section_id"]
        metadata = {k: plan[k] for k in ("unit_kind", "unit_label", "unit_basis", "unit_anchor")}
        path = list(by_node[section]["path"])
        # Body labels need a breadcrumb on continuation children too. Heading
        # labels already occur in the original section path.
        anchor_block = source_blocks.get(plan["unit_anchor"].split(":")[0])
        context_path = path + ([plan["unit_label"]] if plan["unit_label"] and
            (not anchor_block or anchor_block["kind"] != "heading") else [])
        current = {"id": f"parent_{export_id}_{len(parents):05d}",
            "document_id": document_id, "source_id": source_id, "section_id": section,
            "section_path": path, "context_path": context_path, **metadata,
            "unit_id": "unit_" + _sha(document_id + plan["unit_anchor"])[:20] if plan["unit_anchor"] else None,
            "kind": plan["kind"], "atomic": plan["atomic"], "text": "",
            "source_spans": [], "child_ids": [], "source_closed": True}
        for fragment in plan["fragments"]:
            block = source_blocks[fragment["block_id"]]
            a, b = fragment["source_start"], fragment["source_end"]
            value = text[a:b]
            if current["text"]:
                current["text"] += "\n\n"
            start = len(current["text"])
            current["text"] += value
            current["source_spans"].append({**fragment, "start": start,
                "end": len(current["text"]), "text_sha256": _sha(value)})
            current["source_closed"] &= block.get("closed", True)
        parents.append(current)
    children = []
    parent_map = {p["id"]: p for p in parents}
    shared = shared_passages(parents, nodes)
    for parent in parents:
        parent["text_sha256"] = _sha(parent["text"])
        ranges, parent["split_diagnostics"] = _parent_ranges(parent, counter, config)
        for start, end, reason in ranges:
            value = parent["text"][start:end]
            refs = child_refs(parent, start, shared=shared, parents=parent_map,
                              table=inspect_table(parent["text"]) if parent["kind"] == "table" else None)
            search_text = index_text({"text": value, "parent_id": parent["id"],
                "source_id": parent["source_id"],
                "parent_start": start, "parent_end": end, "context_path": parent["context_path"],
                "section_path": parent["section_path"], "context_refs": refs}, parent_map)
            count = counter.count(search_text)
            index_body = search_text[len(" > ".join(parent["context_path"])) + 2:] if parent["context_path"] else search_text
            flags = _flags(parent, reason, identity["unit"])
            child = {"id": f"child_{export_id}_{len(children):05d}",
                "parent_id": parent["id"], "document_id": document_id,
                "source_id": source_id, "section_id": parent["section_id"],
                "section_path": list(parent["section_path"]), "kind": parent["kind"],
                "context_path": list(parent["context_path"]),
                **{k: parent[k] for k in ("unit_id", "unit_kind", "unit_label", "unit_basis")},
                "text": value, "search_text": search_text, "parent_start": start, "parent_end": end,
                "context_refs": refs,
                "index_body": index_body,
                "quality_warnings": _warnings(parent),
                "source_spans": _child_spans(parent, start, end),
                "budget_count": count, "budget_unit": identity["unit"],
                "token_count": count if identity["unit"] == "tokens" else None,
                "budget_fit": count <= max_tokens, "review_flags": flags,
                "retrieval_eligible": not flags and bool(value.strip()),
                "publishable": False}
            parent["child_ids"].append(child["id"])
            children.append(child)
    bundle = {"version": CHUNKING_VERSION, "document_id": document_id, "export_id": export_id,
        "source_id": source_id, "source_text_sha256": _sha(text), "config": config,
        "nodes": nodes, "parents": parents, "children": children}
    errors = validate_chunking(bundle, text, counter)
    bundle["report"] = {"pass": not errors, "errors": errors,
        "heading_count": len(nodes) - 1, "parent_count": len(parents), "child_count": len(children),
        "exercise_parent_count": sum(p["unit_kind"] == "exercise" and not p["atomic"] for p in parents),
        "retrieval_eligible_children": sum(c["retrieval_eligible"] for c in children),
        "budget_overflow_children": sum(not c["budget_fit"] for c in children),
        "deferred_children": sum("deferred_content_kind" in c["review_flags"] for c in children),
        "context_reference_children": sum(bool(c["context_refs"]) for c in children),
        "split_strategy": split_strategy,
        "cost_fallback_parents": sum(bool(p["split_diagnostics"]["fallback_reason"]) for p in parents),
        "certifies_ocr_accuracy": False, "certifies_retrieval_quality": False,
        "grants_publication": False}
    return bundle


def validate_chunking(bundle: dict, source_text: str, counter) -> list[str]:
    """Recheck source conservation, section boundaries, links and input budgets."""
    errors = []
    if bundle.get("version") != CHUNKING_VERSION:
        return ["unsupported text chunking version; regenerate the export"]
    config = bundle["config"]
    try:
        strategy = config["split_strategy"]
        if strategy not in {"greedy", "cost"}:
            raise ValueError("unknown strategy")
        expected_policy = normalize_policy(config["boundary_policy"], config["max_input_budget"]) if strategy == "cost" else None
        if config["boundary_policy"] != expected_policy:
            raise ValueError("noncanonical boundary policy")
        if config["boundary_packets"] != (BOUNDARY_PACKETS_VERSION if strategy == "greedy" else None):
            raise ValueError("unsupported layout packet policy")
        if config["content_policy"] != "idp-text-atoms-1" or config["relations"] != RELATIONS_VERSION:
            raise ValueError("unsupported content/relation policy")
    except (KeyError, ValueError, TypeError):
        return ["invalid boundary strategy/policy"]
    if _sha(source_text) != bundle["source_text_sha256"]:
        errors.append("source text hash mismatch")
    blocks = parse_text(source_text, format=bundle["config"]["format"])
    source_cursor = 0
    for block in blocks:
        if source_text[source_cursor:block["source_start"]].strip():
            errors.append("unmapped non-whitespace source text")
        source_cursor = block["source_end"]
    if source_text[source_cursor:].strip():
        errors.append("unmapped non-whitespace source suffix")
    nodes, assignments = build_hierarchy(blocks, bundle["document_id"])
    if nodes != bundle["nodes"]:
        errors.append("section tree differs from source headings")
    if dict(counter.identity) != bundle["config"]["counter"]:
        errors.append("tokenizer identity mismatch")
    parent_map = {p["id"]: p for p in bundle["parents"]}
    child_map = {c["id"]: c for c in bundle["children"]}
    if len(parent_map) != len(bundle["parents"]) or len(child_map) != len(bundle["children"]):
        errors.append("duplicate parent/child id")
    mapped = []
    source_blocks = {b["id"]: b for b in blocks}
    node_map = {n["id"]: n for n in nodes}
    plans = plan_units(blocks, nodes, assignments)
    shared = shared_passages(bundle["parents"], nodes)
    if len(plans) != len(bundle["parents"]):
        errors.append("logical unit parent count differs from source")
    for parent_index, parent in enumerate(bundle["parents"]):
        pid = parent["id"]
        if parent_index < len(plans):
            plan = plans[parent_index]
            metadata_keys = ("section_id", "unit_kind", "unit_label", "unit_basis", "unit_anchor", "kind", "atomic")
            anchor_block = source_blocks.get(plan["unit_anchor"].split(":")[0])
            expected_path = list(node_map[plan["section_id"]]["path"])
            context_path = expected_path + ([plan["unit_label"]] if plan["unit_label"] and
                (not anchor_block or anchor_block["kind"] != "heading") else [])
            unit_id = "unit_" + _sha(bundle["document_id"] + plan["unit_anchor"])[:20] if plan["unit_anchor"] else None
            if (any(parent.get(k) != plan[k] for k in metadata_keys)
                    or parent.get("unit_id") != unit_id or parent.get("context_path") != context_path
                    or parent.get("source_closed") != all(source_blocks[f["block_id"]].get("closed", True)
                                                           for f in plan["fragments"])
                    or [{k: s.get(k) for k in ("block_id", "source_start", "source_end", "section_id")}
                        for s in parent["source_spans"]] != plan["fragments"]):
                errors.append(f"{pid}: logical unit differs from source cues")
        section = node_map.get(parent["section_id"])
        if (not section or parent["section_path"] != section["path"]
                or parent["source_id"] != bundle["source_id"] or parent["document_id"] != bundle["document_id"]):
            errors.append(f"{pid}: invalid document/section metadata")
        if _sha(parent["text"]) != parent["text_sha256"]:
            errors.append(f"{pid}: stale parent hash")
        expected_parts = []
        for span in parent["source_spans"]:
            block = source_blocks.get(span["block_id"])
            if not block or block["kind"] == "heading":
                errors.append(f"{pid}: unknown content source")
                continue
            a, b = span["source_start"], span["source_end"]
            mapped.append((block["id"], a, b))
            value = source_text[a:b]
            expected_start = sum(len(p) for p in expected_parts) + 2 * len(expected_parts)
            expected_parts.append(value)
            if (span.get("section_id") != assignments[block["id"]]
                    or not block["source_start"] <= a < b <= block["source_end"]
                    or span["start"] != expected_start or span["end"] != expected_start + len(value)
                    or parent["text"][span["start"]:span["end"]] != value
                    or span["text_sha256"] != _sha(value)):
                errors.append(f"{pid}: source span or section mismatch")
        if parent["text"] != "\n\n".join(expected_parts):
            errors.append(f"{pid}: parent content differs from source blocks")
        expected_ranges, diagnostic = _parent_ranges(parent, counter, bundle["config"])
        if parent.get("split_diagnostics") != diagnostic:
            errors.append(f"{pid}: changed boundary diagnostics")
        if len(expected_ranges) != len(parent["child_ids"]):
            errors.append(f"{pid}: child partition differs from budget policy")
        cursor = 0
        for child_index, child_id in enumerate(parent["child_ids"]):
            child = child_map.get(child_id)
            if not child or child["parent_id"] != pid:
                errors.append(f"{pid}: invalid child link")
                continue
            a, b = child["parent_start"], child["parent_end"]
            if a != cursor or not a < b <= len(parent["text"]):
                errors.append(f"{child_id}: gap/overlap in parent coverage")
            cursor = b
            if child["text"] != parent["text"][a:b] or child["source_spans"] != _child_spans(parent, a, b):
                errors.append(f"{child_id}: changed text/provenance")
            if child["section_id"] != parent["section_id"] or child["section_path"] != parent["section_path"]:
                errors.append(f"{child_id}: crossed section boundary")
            if any(child.get(k) != parent.get(k) for k in
                    ("context_path", "unit_id", "unit_kind", "unit_label", "unit_basis")):
                errors.append(f"{child_id}: changed logical unit metadata")
            refs = child_refs(parent, a, shared=shared, parents=parent_map,
                              table=inspect_table(parent["text"]) if parent["kind"] == "table" else None)
            if child.get("context_refs") != refs:
                errors.append(f"{child_id}: changed source context references")
            if child.get("quality_warnings") != _warnings(parent):
                errors.append(f"{child_id}: changed content warning policy")
            expected_search = index_text({**child, "context_refs": refs}, parent_map)
            expected_body = expected_search[len(" > ".join(parent["context_path"])) + 2:] if parent["context_path"] else expected_search
            if child.get("index_body") != expected_body:
                errors.append(f"{child_id}: changed index body")
            count = counter.count(expected_search)
            fits = count <= bundle["config"]["max_input_budget"]
            unit = counter.identity["unit"]
            if child_index < len(expected_ranges):
                expected_a, expected_b, reason = expected_ranges[child_index]
                flags = _flags(parent, reason, unit)
                if (a != expected_a or b != expected_b or child["review_flags"] != flags
                        or child["retrieval_eligible"] != (not flags and bool(child["text"].strip()))):
                    errors.append(f"{child_id}: changed partition/eligibility policy")
            if (child["search_text"] != expected_search or child["budget_count"] != count or child["budget_fit"] != fits
                    or child["budget_unit"] != unit or child["token_count"] != (count if unit == "tokens" else None)):
                errors.append(f"{child_id}: stale token input/count")
            if child["source_id"] != parent["source_id"] or child["document_id"] != parent["document_id"]:
                errors.append(f"{child_id}: invalid document/source metadata")
            if child["retrieval_eligible"] and (not fits or child["review_flags"] or child["budget_unit"] != "tokens"):
                errors.append(f"{child_id}: ineligible content enabled")
            if child.get("publishable") is not False:
                errors.append(f"{child_id}: chunking cannot grant publication")
        if cursor != len(parent["text"]):
            errors.append(f"{pid}: incomplete child coverage")
    # Each source block may now be partitioned between several question units.
    # Coalesce only exactly adjacent fragments, then demand the original order
    # and complete intervals. No omissions (including internal whitespace),
    # duplicate fragments or text substitutions are accepted.
    coalesced = []
    for block_id, a, b in mapped:
        if coalesced and coalesced[-1][0] == block_id and coalesced[-1][2] == a:
            coalesced[-1] = (block_id, coalesced[-1][1], b)
        else:
            coalesced.append((block_id, a, b))
    expected = [(b["id"], b["source_start"], b["source_end"]) for b in blocks if b["kind"] != "heading"]
    if coalesced != expected:
        errors.append("source content missing, duplicated or reordered")
    listed = [cid for p in bundle["parents"] for cid in p["child_ids"]]
    if len(listed) != len(set(listed)) or set(listed) != set(child_map):
        errors.append("orphaned/duplicated child link")
    for c in bundle["children"]:
        if c["parent_id"] not in parent_map:
            errors.append(f"{c['id']}: unknown parent")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chunk a text textbook without OCR/ingestion outputs")
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 .md or .txt")
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    parser.add_argument("--source-id", help="Stable source/version identifier or source URL")
    parser.add_argument("--format", choices=["markdown", "text"])
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--split-strategy", choices=["greedy", "cost"], default="greedy")
    parser.add_argument("--min-tokens", type=int, help="Soft minimum for experimental cost splitting")
    parser.add_argument("--target-tokens", type=int, help="Soft target for experimental cost splitting")
    parser.add_argument("--input-prefix", default="", help="Model input prefix to include in the budget, e.g. 'passage: '")
    counter_group = parser.add_mutually_exclusive_group(required=True)
    counter_group.add_argument("--tokenizer-json", type=Path, help="Local embedding tokenizer.json; no downloads")
    counter_group.add_argument("--utf8-budget", action="store_true", help="Byte-budget diagnostic only; not token counts")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error("input must be a Markdown/text file, not an ingestion directory")
    if not args.format and args.input.suffix.lower() not in {".md", ".markdown", ".txt"}:
        parser.error("input must be .md/.markdown/.txt, or have an explicit text --format")
    if args.out.exists() and not args.out.is_dir():
        parser.error("output must be a directory")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("output directory must be new or empty")
    format = args.format or ("markdown" if args.input.suffix.lower() in {".md", ".markdown"} else "text")
    text = args.input.read_bytes().decode("utf-8-sig")
    counter = LocalTokenizer(args.tokenizer_json) if args.tokenizer_json else Utf8Budget()
    if args.input_prefix:
        counter = PrefixCounter(counter, args.input_prefix)
    if args.split_strategy != "cost" and (args.min_tokens is not None or args.target_tokens is not None):
        parser.error("--min-tokens/--target-tokens require --split-strategy cost")
    policy = {}
    if args.min_tokens is not None:
        policy["min_budget"] = args.min_tokens
    if args.target_tokens is not None:
        policy["target_budget"] = args.target_tokens
    try:
        if args.split_strategy == "cost":
            normalize_policy(policy, args.max_tokens)
    except ValueError as error:
        parser.error(str(error))
    result = chunk_text(text, counter=counter, source_id=args.source_id or str(args.input.resolve()),
                        format=format, max_tokens=args.max_tokens, split_strategy=args.split_strategy,
                        boundary_policy=policy if args.split_strategy == "cost" else None)
    args.out.mkdir(parents=True, exist_ok=True)
    document_json = json.dumps({k: v for k, v in result.items() if k not in {"children", "report"}}, ensure_ascii=False, indent=2)
    chunks_json = "\n".join(json.dumps(c, ensure_ascii=False) for c in result["children"])
    atomic_write_text(args.out / "document.json", document_json)
    atomic_write_text(args.out / "chunks.jsonl", chunks_json)
    # A report is a completion marker only after BOTH payloads were published.
    result["report"].update(completed=True, artifact_sha256={
        "document.json": _sha(document_json), "chunks.jsonl": _sha(chunks_json)})
    atomic_write_text(args.out / "chunking_report.json", json.dumps(result["report"], ensure_ascii=False, indent=2))
    print(json.dumps(result["report"], ensure_ascii=False))
    return 0 if result["report"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
