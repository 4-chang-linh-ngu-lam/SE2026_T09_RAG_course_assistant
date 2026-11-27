"""Validation of derived chunk bundles against source conservation and policy."""
from __future__ import annotations

import unicodedata

from .boundary_cost import normalize_policy
from .chunk_boundaries import BOUNDARY_PACKETS_VERSION
from .chunk_relations import RELATIONS_VERSION, child_refs, shared_passages
from .chunk_views import index_parts
from .hierarchy import HIERARCHY_VERSION, build_hierarchy
from .text_source import TEXT_SOURCE_VERSION, parse_text
from .text_units import TEXT_UNITS_VERSION, plan_units
from .token_budget import memoize_counter


def _boundary_errors(parent, ranges, table):
    """Structural invariants of a child partition, checked without re-splitting.

    Every cut lies outside formula/code atoms and inline math/code, never splits
    a combining sequence, falls on a row boundary of a valid table, and an
    atomic parent has one child. Fast validation relies on these.
    """
    from .chunking import _hard_ranges

    text = parent["text"]
    cuts = [a for a, _ in ranges[1:]]
    if not cuts:
        return []
    if parent["atomic"] and parent["kind"] != "table":
        return ["atomic parent split into several children"]
    if table and table["valid"] and table["columns"] > 1:
        # Row-split table: only row boundaries (rows hold no display formulas).
        points = {table["header_end"], *(b for _, b in table["rows"])}
        return ["cut inside a table row or header"] if any(cut not in points for cut in cuts) else []
    errors = []
    if any(a < cut < b for cut in cuts for a, b in _hard_ranges(parent)):
        errors.append("cut inside a formula/code atom")
    if any(cut < len(text) and (unicodedata.combining(text[cut]) or text[cut] in {"\u200d", "\ufe0e", "\ufe0f"}
                                or text[cut - 1] == "\u200d") for cut in cuts):
        errors.append("cut inside a combining character sequence")
    return errors


def validate_chunking(bundle: dict, source_text: str, counter, *, level: str = "full") -> list[str]:
    """Recheck source conservation, section boundaries, links and input budgets.

    Both levels re-parse the source, rebuild the heading tree and logical units,
    and recheck every span, hash, partition, reference, index input, real token
    count, flag and eligibility rule. "full" also re-derives every child boundary
    with the splitter (CI, audit, benchmark). "fast" accepts any exact partition
    whose eligible inputs fit; it is for loading a bundle that was full-checked
    when built. Neither level grants publication or authorization.
    """
    from .chunking import (
        CHUNKING_VERSION,
        CONTENT_POLICY,
        SIZE_ONLY_FLAGS,
        VALIDATION_LEVELS,
        _SPLIT_REASONS,
        _child_spans,
        _content_atoms,
        _context_eligible,
        _flags,
        _parent_ranges,
        _sha,
        _table_info,
        _warnings,
    )

    if level not in VALIDATION_LEVELS:
        raise ValueError("level must be fast or full")
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
        if config["content_policy"] != CONTENT_POLICY or config["relations"] != RELATIONS_VERSION:
            raise ValueError("unsupported content/relation policy")
        if (config["source_reader"] != TEXT_SOURCE_VERSION or config["unit_reader"] != TEXT_UNITS_VERSION
                or config["hierarchy_version"] != HIERARCHY_VERSION):
            raise ValueError("unsupported reader version")
    except (KeyError, ValueError, TypeError):
        return ["invalid boundary strategy/policy"]
    counter = memoize_counter(counter)
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
    unit = counter.identity["unit"]
    if len(plans) != len(bundle["parents"]):
        errors.append("logical unit parent count differs from source")
    for parent_index, parent in enumerate(bundle["parents"]):
        pid = parent["id"]
        if parent_index < len(plans):
            plan = plans[parent_index]
            metadata_keys = ("section_id", "unit_kind", "unit_subtype", "unit_label", "unit_basis", "unit_anchor",
                             "unit_boundary_ambiguous", "kind", "atomic")
            anchor_block = source_blocks.get(plan["unit_anchor"].split(":")[0])
            expected_path = list(node_map[plan["section_id"]]["path"])
            context_path = expected_path + ([plan["unit_label"]] if plan["unit_label"] and
                (not anchor_block or anchor_block["kind"] != "heading") else [])
            unit_id = "unit_" + _sha(bundle["document_id"] + plan["unit_anchor"])[:20] if plan["unit_anchor"] else None
            if (any(parent.get(k) != plan[k] for k in metadata_keys)
                    or parent.get("unit_id") != unit_id or parent.get("context_path") != context_path
                    or parent.get("content_atoms") != _content_atoms(plan, source_blocks)
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
        table = _table_info(parent)
        expected_ranges = None
        if level == "full":
            expected_ranges, diagnostic = _parent_ranges(parent, counter, bundle["config"], table)
            if parent.get("split_diagnostics") != diagnostic:
                errors.append(f"{pid}: changed boundary diagnostics")
            if len(expected_ranges) != len(parent["child_ids"]):
                errors.append(f"{pid}: child partition differs from budget policy")
        cursor = 0
        warnings = _warnings(parent, table)
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
                    ("context_path", "unit_id", "unit_kind", "unit_subtype", "unit_label", "unit_basis", "kind")):
                errors.append(f"{child_id}: changed logical unit metadata")
            refs = child_refs(parent, a, shared=shared, parents=parent_map, table=table)
            if child.get("context_refs") != refs:
                errors.append(f"{child_id}: changed source context references")
            if child.get("quality_warnings") != warnings:
                errors.append(f"{child_id}: changed content warning policy")
            expected_search, expected_body = index_parts({**child, "context_refs": refs}, parent_map)
            if child.get("index_body") != expected_body:
                errors.append(f"{child_id}: changed index body")
            count = counter.count(expected_search)
            fits = count <= bundle["config"]["max_input_budget"]
            flags = child.get("review_flags")
            if expected_ranges is not None:
                if child_index < len(expected_ranges):
                    expected_a, expected_b, reason = expected_ranges[child_index]
                    if a != expected_a or b != expected_b or flags != _flags(parent, reason, unit):
                        errors.append(f"{child_id}: changed partition/eligibility policy")
            elif (not isinstance(flags, list) or len(flags) > 3
                  or flags != _flags(parent, flags[0] if flags and flags[0] in _SPLIT_REASONS else None, unit)):
                errors.append(f"{child_id}: changed partition/eligibility policy")
            flags = flags if isinstance(flags, list) else ["invalid_flags"]
            if (child["retrieval_eligible"] != (not flags and bool(child["text"].strip()))
                    or child.get("context_eligible") != _context_eligible(flags, child["text"], unit)):
                errors.append(f"{child_id}: changed partition/eligibility policy")
            if (child["search_text"] != expected_search or child["budget_count"] != count or child["budget_fit"] != fits
                    or child["budget_unit"] != unit or child["token_count"] != (count if unit == "tokens" else None)):
                errors.append(f"{child_id}: stale token input/count")
            if child["source_id"] != parent["source_id"] or child["document_id"] != parent["document_id"]:
                errors.append(f"{child_id}: invalid document/source metadata")
            if child["retrieval_eligible"] and (not fits or child["review_flags"] or child["budget_unit"] != "tokens"):
                errors.append(f"{child_id}: ineligible content enabled")
            if fits and set(flags) & SIZE_ONLY_FLAGS:
                # A size hold on an input that fits withholds searchable content.
                errors.append(f"{child_id}: size hold on content that fits the budget")
            if child.get("publishable") is not False:
                errors.append(f"{child_id}: chunking cannot grant publication")
        if cursor != len(parent["text"]):
            errors.append(f"{pid}: incomplete child coverage")
        ranges = [(child_map[c]["parent_start"], child_map[c]["parent_end"])
                  for c in parent["child_ids"] if c in child_map]
        errors.extend(f"{pid}: {message}" for message in _boundary_errors(parent, ranges, table))
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
