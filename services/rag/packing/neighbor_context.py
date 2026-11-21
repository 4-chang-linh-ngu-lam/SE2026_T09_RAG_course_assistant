"""Seed-preserving neighbor windows over currently authorized child payloads.

No index writes, retrieval, reranking or grant inference. Windows are derived
only from a provably contiguous parent partition and authorized eligible children.
"""
from __future__ import annotations

import hashlib

from ..chunking.token_budget import contextualize
from ..chunking.chunk_views import materialize, partition as source_partition

CONTEXT_VERSION = "idp-text-context-2"


def _child_record(child):
    # Own evidence only. An enriched future index view is not automatically
    # authorized evidence to display to the answer model.
    return {"id": child["id"], "level": "child", "source_id": child["source_id"],
        "section_path": list(child["section_path"]), "text": child["text"],
        "context_path": list(child.get("context_path", child["section_path"])),
        "parent_id": child["parent_id"], "parent_start": child["parent_start"], "parent_end": child["parent_end"],
        "search_text": contextualize(child.get("context_path", child["section_path"]), child["text"]),
        "source_spans": child["source_spans"], "child_ids": [child["id"]],
        **({"source_quality_warnings": list(child["quality_warnings"])} if child.get("quality_warnings") else {})}


def partition(parent, children):
    return source_partition(parent, children)


def window(ids, children):
    if len(ids) == 1:
        return _child_record(children[ids[0]])
    selected = [children[cid] for cid in ids]
    first, last = selected[0], selected[-1]
    text = "".join(c["text"] for c in selected)
    spans = []
    for child in selected:
        shift = child["parent_start"] - first["parent_start"]
        spans.extend({**s, "start": s["start"] + shift, "end": s["end"] + shift}
                     for s in child["source_spans"])
    signature = f"{first['parent_id']}:{first['parent_start']}:{last['parent_end']}"
    return {"id": "window_" + hashlib.sha256(signature.encode()).hexdigest()[:16],
        "level": "window", "source_id": first["source_id"],
        "section_path": list(first["section_path"]), "text": text,
        "context_path": list(first.get("context_path", first["section_path"])),
        "search_text": contextualize(first.get("context_path", first["section_path"]), text),
        "source_spans": spans, "child_ids": ids,
        **({"source_quality_warnings": sorted({w for c in selected for w in c.get("quality_warnings", [])})}
           if any(c.get("quality_warnings") for c in selected) else {}),
        "parent_id": first["parent_id"], "parent_start": first["parent_start"], "parent_end": last["parent_end"]}


def neighbor_context(children, parents, ranked, eligible, *, counter, max_tokens, radius, parent_first=False,
                    compact_seed_reservation=False):
    """Reserve fitting hits, compact adjacent hits, then expand into spare budget.

    Denied/ineligible/missing neighbors are barriers, never jumped over. A failed
    structural proof disables merging/expansion for that parent, retaining only
    the already-authorized child payloads. Added text cannot evict reserved seeds.
    """
    def render(records):
        return "\n\n".join(f"[{r['id']}]\n{r['search_text']}" for r in records)

    valid, positions = {}, {}
    for cid in ranked:
        child = children[cid]
        parent = parents.get(child["parent_id"])
        if not parent or cid not in parent["child_ids"]:
            raise ValueError("broken parent/child link")
        pid = parent["id"]
        if pid not in valid:
            valid[pid] = partition(parent, children)
            if valid[pid]:
                positions.update({item: i for i, item in enumerate(parent["child_ids"])})

    def compact(ids, order):
        by_parent, singles, records = {}, [], []
        for cid in ids:
            pid = children[cid]["parent_id"]
            if valid.get(pid):
                by_parent.setdefault(pid, []).append(cid)
            else:
                singles.append(cid)
        for pid, members in by_parent.items():
            members.sort(key=positions.__getitem__)
            run = []
            for cid in members:
                if run and positions[cid] != positions[run[-1]] + 1:
                    records.append((min(order[c] for c in run), window(run, children)))
                    run = []
                run.append(cid)
            if run:
                records.append((min(order[c] for c in run), window(run, children)))
        records.extend((order[cid], _child_record(children[cid])) for cid in singles)
        records.sort(key=lambda item: (item[0], item[1]["id"]))
        views = [materialize(record, children, parents, eligible) for _, record in records]
        if any(record is None for record in views):
            # Only validated eligible members should reach compaction. Fail
            # closed if a caller supplied inconsistent cross-parent metadata.
            raise ValueError("invalid or unauthorized source context reference")
        return views

    seeds, raw, skipped = [], [], []
    priorities = {}
    reservation_trace = None
    if compact_seed_reservation:
        attempts = []
        chosen = set()
        records = []
        representation = "none"
        for priority, cid in enumerate(ranked):
            record = materialize(_child_record(children[cid]), children, parents, eligible)
            if record is None:
                skipped.append(cid)
                attempts.append({"child_id": cid, "raw_count": None, "compact_count": None,
                    "admitted": False, "representation": "none", "reason": "materialization"})
                continue
            tentative = chosen | {cid}
            order = {**priorities, cid: priority}
            compact_candidate = compact(tentative, order)
            compact_count = counter.count(render(compact_candidate))
            raw_candidate = raw + [record]
            raw_count = counter.count(render(raw_candidate))
            if compact_count <= max_tokens:
                chosen, priorities, records = tentative, order, compact_candidate
                raw.append(record)
                seeds.append(cid)
                representation = "compact"
                admitted, used, reason = True, "compact", None
            elif raw_count <= max_tokens:
                # Nonmonotonic tokenizers may price a compact window higher;
                # keep the raw records when they fit and never evict old seeds.
                chosen, priorities, records = tentative, order, raw_candidate
                raw = raw_candidate
                seeds.append(cid)
                representation = "raw_fallback"
                admitted, used, reason = True, "raw_fallback", None
            else:
                skipped.append(cid)
                admitted, used, reason = False, "none", "budget"
            attempts.append({"child_id": cid, "raw_count": raw_count,
                "compact_count": compact_count, "admitted": admitted,
                "representation": used, **({"reason": reason} if reason else {})})
        reservation_trace = {"policy": "compact_before_budget", "attempts": attempts,
            "raw_count": counter.count(render(raw)),
            "compact_count": counter.count(render(compact(chosen, priorities))) if chosen else 0,
            "admitted_seed_child_ids": list(seeds), "final_representation": representation}
    else:
        for priority, cid in enumerate(ranked):
            record = materialize(_child_record(children[cid]), children, parents, eligible)
            if record is None:
                skipped.append(cid)
                continue
            if counter.count(render(raw + [record])) <= max_tokens:
                raw.append(record)
                seeds.append(cid)
                priorities[cid] = priority
            else:
                skipped.append(cid)
        chosen = set(seeds)
        records = compact(chosen, priorities)
        if counter.count(render(records)) > max_tokens:
            # Tokenizers need not reward concatenation/shorter labels monotonically.
            records = raw
    parent_attempts, parent_added = [], set()
    if parent_first:
        visited = set()
        for seed in seeds:
            parent = parents[children[seed]["parent_id"]]
            pid = parent["id"]
            if pid in visited:
                continue
            visited.add(pid)
            siblings = set(parent["child_ids"])
            reason = ("invalid_partition" if not valid.get(pid) else
                      "not_fully_eligible" if not siblings <= eligible else None)
            if reason:
                parent_attempts.append({"parent_id": pid, "status": reason})
                continue
            candidate_ids = chosen | siblings
            order = dict(priorities)
            for cid in siblings - chosen:
                order[cid] = priorities[seed]
            candidate = compact(candidate_ids, order)
            if counter.count(render(candidate)) > max_tokens:
                parent_attempts.append({"parent_id": pid, "status": "budget"})
                continue
            added = len(siblings - chosen)
            parent_added.update(siblings - chosen)
            chosen, priorities, records = candidate_ids, order, candidate
            if reservation_trace is not None:
                reservation_trace["final_representation"] = "compact"
            parent_attempts.append({"parent_id": pid, "status": "expanded" if added else "already_covered",
                                    "added_children": added})
    for seed in seeds:
        parent = parents[children[seed]["parent_id"]]
        if not valid.get(parent["id"]):
            continue
        anchor = positions[seed]
        for direction in (-1, 1):
            for distance in range(1, radius + 1):
                index = anchor + direction * distance
                if not 0 <= index < len(parent["child_ids"]):
                    break
                cid = parent["child_ids"][index]
                if cid not in eligible:
                    break
                if cid in chosen:
                    continue
                candidate_ids = chosen | {cid}
                order = {**priorities, cid: priorities[seed]}
                candidate = compact(candidate_ids, order)
                if counter.count(render(candidate)) > max_tokens:
                    break
                chosen, priorities, records = candidate_ids, order, candidate
                if reservation_trace is not None:
                    reservation_trace["final_representation"] = "compact"
    context = render(records)
    result = {"version": CONTEXT_VERSION, "context": context, "items": records,
        "budget_count": counter.count(context), "budget_unit": counter.identity["unit"],
        "skipped_budget_child_ids": skipped, "seed_child_ids": seeds,
        "added_neighbor_child_ids": sorted(chosen - set(seeds) - parent_added),
        "added_parent_child_ids": sorted(parent_added),
        "added_context_child_ids": sorted(chosen - set(seeds)),
        "invalid_partition_parent_ids": sorted(pid for pid, ok in valid.items() if not ok),
        "mode": "parent_then_neighbors" if parent_first else "neighbors", "neighbor_radius": radius,
        "parent_attempts": parent_attempts, "grants_authorization": False}
    if reservation_trace is not None:
        result["seed_reservation"] = reservation_trace
    return result
