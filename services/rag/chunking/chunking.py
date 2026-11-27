"""Structure-first text chunking for the RAG pipeline.

This module owns only derived chunking artifacts; it does not publish to an
index or grant retrieval access. Inputs are UTF-8 Markdown or plain text.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import hashlib
import json
import re
import unicodedata

from .boundary_cost import candidate_points, merge_protected, normalize_policy, quoted_spans, split_cost
from .chunk_boundaries import BOUNDARY_PACKETS_VERSION, fitting_layout_ranges
from .chunk_relations import RELATIONS_VERSION, child_refs, shared_passages
from .chunk_views import index_parts
from .text_atoms import inspect_table, math_closed
from .hierarchy import HIERARCHY_VERSION, build_hierarchy
from .text_source import MATH_ENVIRONMENTS, TEXT_SOURCE_VERSION, is_display_line, parse_text
from .text_units import TEXT_UNITS_VERSION, plan_units
from .token_budget import MemoCounter, contextualize, memoize_counter

CHUNKING_VERSION = "idp-text-chunking-10"
CONTENT_POLICY = "idp-text-atoms-3"
VALIDATION_LEVELS = ("fast", "full")
# A multi-line formula never spans a blank line: a stray `$$` or `\[` must not
# turn the rest of a section into one indivisible protected span.
_NO_BLANK = r"(?:(?!\n[ \t]*\r?\n)[\s\S])*?"
_PROTECTED = re.compile(
    rf"(?<!\\)\$\$(?!\$){_NO_BLANK}(?<!\\)\$\$"
    r"|(?<!\\)\$[^$\n]+?(?<!\\)\$"
    rf"|\\\({_NO_BLANK}\\\)"
    rf"|\\\[{_NO_BLANK}\\\]"
    rf"|\\begin\{{(?P<env>{'|'.join(MATH_ENVIRONMENTS)})(?P<star>\*?)\}}{_NO_BLANK}\\end\{{(?P=env)(?P=star)\}}"
    r"|`[^`\n]+`")
# Held only because they are larger than one search input. Their source is
# complete and closed, so packing may still show them next to an eligible seed.
SIZE_ONLY_FLAGS = frozenset({"indivisible_text_exceeds_budget", "atomic_block_exceeds_budget",
                             "table_row_exceeds_budget", "table_header_exceeds_budget"})
_SPLIT_REASONS = SIZE_ONLY_FLAGS | {"breadcrumb_exceeds_budget", "unsupported_math_structure",
                                    "unsupported_table_structure"}


def protected_spans(text: str) -> list[tuple[int, int]]:
    """Return protected formula/code spans for downstream text packing."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return [(match.start(), match.end()) for match in _PROTECTED.finditer(text)]


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_MemoCounter = MemoCounter
_memo = memoize_counter


def split_text(text: str, path: list[str], counter, limit: int, *,
               protected_ranges=(), inline_protection: bool = True) -> list[tuple[int, int, str | None]]:
    """Exact, disjoint slices. Prefer paragraph, sentence, word, then character.

    Character fallback never cuts a combining sequence, inline math or code.
    Token counts are checked on the exact contextualized string, not estimated
    by adding per-piece counts. A non-monotonic tokenizer may underfill a slice;
    the emitted input still has to pass the actual budget check.

    Bounded greedy: each cut is searched by galloping from the current start
    (window doubling, then bisection), so a long parent is never tokenized
    as a whole remainder on every iteration.
    """
    def fits(a, b):
        return counter.count(contextualize(path, text[a:b])) <= limit

    if fits(0, len(text)):
        return [(0, len(text), None)]
    if counter.count(contextualize(path, "")) >= limit:
        return [(0, len(text), "breadcrumb_exceeds_budget")]
    inline = [(m.start(), m.end()) for m in _PROTECTED.finditer(text)] if inline_protection else []
    protected = merge_protected(inline + list(protected_ranges))
    protected_starts = [a for a, _ in protected]
    preferred = [[m.end() for m in re.finditer(r"\n[ \t]*\n+", text)],
                 candidate_points(text)[1:-1],
                 [m.end() for m in re.finditer(r"\s+", text)]]

    def can_cut(pos):
        if pos < len(text) and (unicodedata.combining(text[pos])
                or text[pos] in {"\u200d", "\ufe0e", "\ufe0f"} or text[pos - 1:pos] == "\u200d"):
            return False
        # Merged ranges are disjoint: only the last one starting before pos matters.
        k = bisect_left(protected_starts, pos) - 1
        return k < 0 or pos >= protected[k][1]

    first_window = max(64, 4 * limit)
    result, start = [], 0
    while start < len(text):
        low, high, window = start, None, first_window
        while high is None:
            probe = min(len(text), start + window)
            if not fits(start, probe):
                high = probe - 1
            elif probe == len(text):
                low = high = probe
            else:
                low, window = probe, window * 2
        if low == len(text):
            result.append((start, len(text), None))
            break
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
            # The flag follows the exact count of this very input.
            result.append((start, end, None if fits(start, end) else "indivisible_text_exceeds_budget"))
            start = end
            continue
        min_paragraph_span = (end - start) // 3
        for level, boundaries in enumerate(preferred):
            index = bisect_right(boundaries, end) - 1
            found = False
            while index >= 0 and boundaries[index] > start:
                point = boundaries[index]
                # Do not snap back to an early paragraph break that leaves a tiny
                # fragment when more readable text fits up to a later sentence break.
                if level == 0 and point - start < min_paragraph_span and text[point:end].strip():
                    break
                if can_cut(point) and text[start:point].strip() and fits(start, point):
                    end = point
                    found = True
                    break
                index -= 1
            if found:
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


def _formula_lines(text):
    """Per-formula intervals of a block made of one-line display formulas, else None.

    `$$a$$⏎$$b$$` is two independent formulas and may be split between them; a
    multi-line `$$…$$` or `\\begin{align}…` is one structure and stays whole.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) < 2 or not all(is_display_line(line) for line in lines):
        return None
    result, offset = [], 0
    for line in lines:
        body = line.rstrip("\r\n")
        lead = len(body) - len(body.lstrip())
        result.append((offset + lead, offset + len(body.rstrip())))
        offset += len(line)
    return result


def _content_atoms(plan, blocks):
    """Parent-text intervals of formula/code blocks merged into a prose parent."""
    if plan["atomic"]:
        return []
    atoms, cursor = [], 0
    for index, fragment in enumerate(plan["fragments"]):
        if index:
            cursor += 2
        length = fragment["source_end"] - fragment["source_start"]
        block = blocks[fragment["block_id"]]
        if block["kind"] in {"math", "code"}:
            pieces = (_formula_lines(block["text"]) if block["kind"] == "math" else None) or [(0, length)]
            atoms.extend({"start": cursor + a, "end": cursor + b, "kind": block["kind"]} for a, b in pieces)
        cursor += length
    return atoms


def _hard_ranges(parent):
    """Never-cut intervals: merged formula/code blocks and inline math/code.

    An inline match that only partly overlaps a code block paired a `$` inside
    the code with one outside it; that match is not a formula and is dropped.
    """
    atoms = [(a["start"], a["end"]) for a in parent.get("content_atoms", [])]
    inline = [(m.start(), m.end()) for m in _PROTECTED.finditer(parent["text"])]
    inline = [(x, y) for x, y in inline
              if all(y <= a or b <= x or (a <= x and y <= b) for a, b in atoms)]
    return merge_protected(atoms + inline)


def _table_info(parent):
    return inspect_table(parent["text"]) if parent["kind"] == "table" else None


def _table_ranges(parent, counter, limit, table):
    text, path = parent["text"], parent["context_path"]
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
            result.append((start, end, None if count(start, end) <= limit else "table_row_exceeds_budget"))
            point_index += 1
        else:
            end = points[best]
            result.append((start, end, None))
            point_index = best + 1
        start = end
    return result, "table_rows"


def _parent_ranges(parent, counter, config, table=None):
    limit = config["max_input_budget"]
    diagnostic = {"requested_strategy": config["split_strategy"],
        "used_strategy": "atomic" if parent["atomic"] else "greedy", "fallback_reason": None,
        "candidate_units": 0, "transition_checks": 0, "objective": None}
    if parent["kind"] == "table":
        ranges, diagnostic["used_strategy"] = _table_ranges(
            parent, counter, limit, table if table is not None else _table_info(parent))
        return ranges, diagnostic
    if parent["kind"] == "math" and not math_closed(parent["text"]):
        return [(0, len(parent["text"]), "unsupported_math_structure")], diagnostic
    hard = _hard_ranges(parent) if not parent["atomic"] else []
    if not parent["atomic"] and config["split_strategy"] == "cost":
        protected = hard + quoted_spans(parent["text"])
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
        protected = fitting_layout_ranges(parent["text"], parent["context_path"], counter, limit,
                                         hard_ranges=hard)
        return split_text(parent["text"], parent["context_path"], counter, limit,
                          protected_ranges=hard + protected, inline_protection=False), diagnostic
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


def _context_eligible(flags, text, unit):
    """Size-only holds stay out of search but may be packed next to a seed."""
    return bool(flags) and set(flags) <= SIZE_ONLY_FLAGS and unit == "tokens" and bool(text.strip())


def _warnings(parent, table):
    return ["unstructured_table_text"] if parent["kind"] == "table" and not table["valid"] else []


def chunk_text(text: str, *, counter, source_id: str, format: str = "markdown",
               max_tokens: int = 384, split_strategy: str = "greedy", boundary_policy: dict | None = None,
               validation: str = "full") -> dict:
    """Build a source tree, logical content parents and budgeted search children.

    max_tokens is in the supplied counter's declared unit; byte diagnostics
    remain explicitly ineligible for indexing. This is not a production grant.
    `validation` is the self-check level of the returned report ("full"
    re-derives every boundary; it reuses this build's exact count memo).
    """
    if not isinstance(text, str) or not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("text and a nonempty source_id are required")
    if type(max_tokens) is not int or not 8 <= max_tokens <= 65536:
        raise ValueError("max_tokens must be an integer in 8..65536")
    if split_strategy not in {"greedy", "cost"}:
        raise ValueError("split_strategy must be greedy or cost")
    if boundary_policy is not None and split_strategy != "cost":
        raise ValueError("boundary_policy requires split_strategy=cost")
    if validation not in VALIDATION_LEVELS:
        raise ValueError("validation must be fast or full")
    policy = normalize_policy(boundary_policy, max_tokens) if split_strategy == "cost" else None
    identity = dict(counter.identity)
    if identity.get("unit") not in {"tokens", "utf8_bytes"}:
        raise ValueError("counter must declare tokens or utf8_bytes")
    counter = _memo(counter)
    blocks = parse_text(text, format=format)
    config = {"version": CHUNKING_VERSION, "hierarchy_version": HIERARCHY_VERSION,
        "source_reader": TEXT_SOURCE_VERSION, "unit_reader": TEXT_UNITS_VERSION, "format": format,
        "max_input_budget": max_tokens, "counter": identity}
    config.update(split_strategy=split_strategy, boundary_policy=policy,
                  boundary_packets=BOUNDARY_PACKETS_VERSION if split_strategy == "greedy" else None,
                  content_policy=CONTENT_POLICY, relations=RELATIONS_VERSION)
    document_id = _sha(source_id + "\0" + text)[:20]
    export_id = _sha(document_id + json.dumps(config, sort_keys=True))[:20]
    nodes, assignments = build_hierarchy(blocks, document_id)
    by_node = {n["id"]: n for n in nodes}
    parents = []
    source_blocks = {b["id"]: b for b in blocks}
    for plan in plan_units(blocks, nodes, assignments):
        section = plan["section_id"]
        metadata = {k: plan[k] for k in ("unit_kind", "unit_subtype", "unit_label", "unit_basis", "unit_anchor",
                                         "unit_boundary_ambiguous")}
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
            "source_spans": [], "child_ids": [], "source_closed": True,
            "content_atoms": _content_atoms(plan, source_blocks)}
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
        table = _table_info(parent)
        ranges, parent["split_diagnostics"] = _parent_ranges(parent, counter, config, table)
        warnings = _warnings(parent, table)
        for start, end, reason in ranges:
            value = parent["text"][start:end]
            refs = child_refs(parent, start, shared=shared, parents=parent_map, table=table)
            search_text, index_body = index_parts({"text": value, "parent_id": parent["id"],
                "source_id": parent["source_id"],
                "parent_start": start, "parent_end": end, "context_path": parent["context_path"],
                "section_path": parent["section_path"], "context_refs": refs}, parent_map)
            count = counter.count(search_text)
            flags = _flags(parent, reason, identity["unit"])
            child = {"id": f"child_{export_id}_{len(children):05d}",
                "parent_id": parent["id"], "document_id": document_id,
                "source_id": source_id, "section_id": parent["section_id"],
                "section_path": list(parent["section_path"]), "kind": parent["kind"],
                "context_path": list(parent["context_path"]),
                **{k: parent[k] for k in ("unit_id", "unit_kind", "unit_subtype", "unit_label", "unit_basis")},
                "text": value, "search_text": search_text, "parent_start": start, "parent_end": end,
                "context_refs": refs,
                "index_body": index_body,
                "quality_warnings": list(warnings),
                "source_spans": _child_spans(parent, start, end),
                "budget_count": count, "budget_unit": identity["unit"],
                "token_count": count if identity["unit"] == "tokens" else None,
                "budget_fit": count <= max_tokens, "review_flags": flags,
                "retrieval_eligible": not flags and bool(value.strip()),
                "context_eligible": _context_eligible(flags, value, identity["unit"]),
                "publishable": False}
            parent["child_ids"].append(child["id"])
            children.append(child)
    bundle = {"version": CHUNKING_VERSION, "document_id": document_id, "export_id": export_id,
        "source_id": source_id, "source_text_sha256": _sha(text), "config": config,
        "nodes": nodes, "parents": parents, "children": children}
    build_stats = counter.stats()
    errors = validate_chunking(bundle, text, counter, level=validation)
    validation_stats = {k: v - build_stats[k] for k, v in counter.stats().items()}
    bundle["report"] = {"pass": not errors, "errors": errors,
        "heading_count": len(nodes) - 1, "parent_count": len(parents), "child_count": len(children),
        "exercise_parent_count": sum(p["unit_kind"] == "exercise" and not p["atomic"] for p in parents),
        "caption_unit_parents": sum(p["unit_kind"] == "caption" for p in parents),
        "ambiguous_unit_boundaries": sum(p["unit_boundary_ambiguous"] for p in parents),
        "statement_parent_count": sum(p["unit_kind"] in {"statement", "remark"} for p in parents),
        "mixed_content_parents": sum(bool(p["content_atoms"]) for p in parents),
        "atomic_parent_count": sum(p["atomic"] for p in parents),
        "retrieval_eligible_children": sum(c["retrieval_eligible"] for c in children),
        "context_eligible_children": sum(c["context_eligible"] for c in children),
        "budget_overflow_children": sum(not c["budget_fit"] for c in children),
        "deferred_children": sum("deferred_content_kind" in c["review_flags"] for c in children),
        "context_reference_children": sum(bool(c["context_refs"]) for c in children),
        "split_strategy": split_strategy,
        "cost_fallback_parents": sum(bool(p["split_diagnostics"]["fallback_reason"]) for p in parents),
        "validation_level": validation, "build_counter": build_stats, "validation_counter": validation_stats,
        "certifies_ocr_accuracy": False, "certifies_retrieval_quality": False,
        "grants_publication": False}
    return bundle


from .validator import _boundary_errors, validate_chunking  # noqa: E402


def main(argv=None):
    from .cli import main as _cli_main

    return _cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
