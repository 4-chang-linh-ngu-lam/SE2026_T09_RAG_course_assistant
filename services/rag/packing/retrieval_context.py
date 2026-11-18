"""Budgeted parent/child context assembly over already ranked text chunks.

This offline helper does not retrieve, check grants, call a model, or expose a
service endpoint. Its caller must provide the CURRENT authorized child IDs.
"""
from __future__ import annotations

import math

from ..chunking.token_budget import contextualize
from .neighbor_context import neighbor_context
from ..chunking.chunk_views import eligible_with_context, materialize, partition


def expand_context(bundle: dict, ranked_child_ids: list[str], *, allowed_child_ids: set[str],
                   counter, max_tokens: int = 2048, mode: str = "auto",
                   merge_ratio: float = 0.5, neighbor_radius: int = 1,
                   compact_seed_reservation: bool = False) -> dict:
    """Auto merges only when >=2 distinct hits cover merge_ratio of a parent.

    Parent expansion additionally requires ALL its children to be authorized,
    eligible and within the total context budget. Otherwise retain the child.
    `child` and `parent` modes let the caller choose a narrower/broader scope;
    auto is a hit-coverage heuristic, not an inference of question intent.
    """
    if mode not in {"auto", "child", "parent", "neighbors", "parent_then_neighbors"}:
        raise ValueError("mode must be auto, child, parent or neighbors")
    if type(neighbor_radius) is not int or not 0 <= neighbor_radius <= 3:
        raise ValueError("neighbor_radius must be an integer in 0..3")
    if type(compact_seed_reservation) is not bool:
        raise ValueError("compact_seed_reservation must be bool")
    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    if counter.count("") > max_tokens:
        raise ValueError("budget cannot accommodate tokenizer special tokens")
    if not isinstance(merge_ratio, (int, float)) or isinstance(merge_ratio, bool) or not math.isfinite(merge_ratio) or not 0 < merge_ratio <= 1:
        raise ValueError("merge_ratio must be in (0, 1]")
    if not isinstance(allowed_child_ids, set):
        raise ValueError("an explicit current set of allowed_child_ids is required")
    children = {c["id"]: c for c in bundle["children"]}
    parents = {p["id"]: p for p in bundle["parents"]}
    if len(children) != len(bundle["children"]) or len(parents) != len(bundle["parents"]):
        raise ValueError("duplicate IDs in chunk export")
    eligible = {cid for cid, c in children.items() if c.get("retrieval_eligible") and cid in allowed_child_ids}
    eligible = eligible_with_context(children, parents, eligible)
    ranked = list(dict.fromkeys(cid for cid in ranked_child_ids if cid in eligible))
    if mode in {"neighbors", "parent_then_neighbors"}:
        return neighbor_context(children, parents, ranked, eligible, counter=counter,
                                max_tokens=max_tokens, radius=neighbor_radius,
                                parent_first=mode == "parent_then_neighbors",
                                compact_seed_reservation=compact_seed_reservation)
    hits = {}
    for cid in ranked:
        hits.setdefault(children[cid]["parent_id"], set()).add(cid)
    selected, covered, skipped = [], set(), []

    def render(records):
        return "\n\n".join(f"[{r['id']}]\n{r['search_text']}" for r in records)

    def fits(record):
        view = materialize(record, children, parents, eligible)
        return view is not None and counter.count(render(selected + [view])) <= max_tokens

    for cid in ranked:
        if cid in covered:
            continue
        child = children[cid]
        parent = parents.get(child["parent_id"])
        if not parent or cid not in parent["child_ids"]:
            raise ValueError("broken parent/child link")
        siblings = set(parent["child_ids"])
        valid_parent = bool(siblings) and siblings <= eligible and partition(parent, children)
        want_parent = mode == "parent" or (mode == "auto" and len(hits[parent["id"]]) >= 2
            and len(hits[parent["id"]]) / len(siblings) >= merge_ratio)
        parent_record = {"id": parent["id"], "level": "parent", "source_id": parent["source_id"],
            "section_path": list(parent["section_path"]), "text": parent["text"],
            "context_path": list(parent.get("context_path", parent["section_path"])),
            "parent_id": parent["id"], "parent_start": 0, "parent_end": len(parent["text"]),
            "search_text": contextualize(parent.get("context_path", parent["section_path"]), parent["text"]),
            "source_spans": parent["source_spans"], "child_ids": list(parent["child_ids"])}
        warnings = sorted({w for s in siblings for w in children.get(s, {}).get("quality_warnings", [])})
        if warnings:
            parent_record["source_quality_warnings"] = warnings
        if want_parent and valid_parent and not (siblings & covered) and fits(parent_record):
            selected.append(materialize(parent_record, children, parents, eligible))
            covered.update(siblings)
            continue
        child_record = {"id": cid, "level": "child", "source_id": child["source_id"],
            "section_path": list(child["section_path"]), "text": child["text"],
            "context_path": list(child.get("context_path", child["section_path"])),
            "parent_id": child["parent_id"], "parent_start": child["parent_start"], "parent_end": child["parent_end"],
            "search_text": child["search_text"], "source_spans": child["source_spans"], "child_ids": [cid]}
        if child.get("quality_warnings"):
            child_record["source_quality_warnings"] = list(child["quality_warnings"])
        if fits(child_record):
            selected.append(materialize(child_record, children, parents, eligible))
            covered.add(cid)
        else:
            skipped.append(cid)
    context = render(selected)
    return {"context": context, "items": selected, "budget_count": counter.count(context),
        "budget_unit": counter.identity["unit"], "skipped_budget_child_ids": skipped,
        "mode": mode, "grants_authorization": False}
