"""Bounded, query-term lexical probes for experimental retrieval only.

Probes reuse the authorized FieldedBM25 instance and its body statistics. They
add candidate evidence without contributing another fusion vote.
"""
from __future__ import annotations

import hashlib
import copy

from .retrieval_plan import _STOP


def _probe_terms(query, lexical, limit):
    if type(limit) is not int or not 0 <= limit <= 4:
        raise ValueError("probe limit must be an integer in 0..4")
    if not limit:
        return [], 0
    _, _, body_postings = lexical.fields["body"]
    stopwords = {term for word in _STOP for term in lexical.query_terms(word)}
    seen, candidates = set(), []
    for order, term in enumerate(lexical.query_terms(query)):
        if term in seen:
            continue
        seen.add(term)
        if term in stopwords:
            continue
        df = len(body_postings.get(term, ()))
        if df:
            candidates.append((term, df, order))
    if len(candidates) < 2:
        return [], len(candidates)
    candidates.sort(key=lambda row: (row[1], row[2]))
    return candidates[:limit], len(candidates)


def probe_candidates(query, lexical, *, limit, hits):
    """Return selected body-supported term hits plus a redacted trace."""
    if type(hits) is not int or not 1 <= hits <= 4:
        raise ValueError("probe hits must be an integer in 1..4")
    selected, known_count = _probe_terms(query, lexical, limit)
    if not selected:
        reason = "disabled" if not limit else "fewer_than_two_known_body_terms"
        return [], [], {"status": "skipped", "reason": reason, "known_body_term_count": known_count,
                        "probes": [], "evicted_tail_child_ids": [], "skipped_probe_child_ids": []}

    body_postings = lexical.fields["body"][2]
    probes, trace_rows = [], []
    round_robin = []
    for index, (term, df, _) in enumerate(selected):
        term_hash = hashlib.sha256(term.encode("utf-8")).hexdigest()
        body_ids = {lexical.children[i]["id"] for i, _ in body_postings[term]}
        # FieldedBM25 supplies its existing single-term score; body support is
        # mandatory, so title/path-only matches can never become probe hits.
        ranked = [(cid, score) for cid, score in lexical.rank(term) if cid in body_ids][:hits]
        probe = {"index": index, "term": term, "term_sha256": term_hash,
                 "document_frequency": df, "hits": ranked}
        probes.append(probe)
        trace_rows.append({"term_sha256": term_hash, "document_frequency": df,
            "hits": [{"child_id": cid, "rank": rank, "score": float(score)}
                     for rank, (cid, score) in enumerate(ranked, 1)]})
    for rank in range(hits):
        for probe in probes:
            if rank < len(probe["hits"]):
                cid, score = probe["hits"][rank]
                round_robin.append((cid, probe["index"], rank + 1, float(score)))
    return probes, round_robin, {"status": "applied", "known_body_term_count": known_count,
        "probes": trace_rows, "evicted_tail_child_ids": [], "skipped_probe_child_ids": []}


def augment_fused(base, round_robin, probes, *, fusion_limit, seed_limit, trace):
    """Keep base ordering, reserve recalled probe IDs, then fill remaining slots."""
    if not probes:
        return base, trace, []
    base = copy.deepcopy(list(base[:fusion_limit]))
    trace = copy.deepcopy(trace)
    base_ids = [item["id"] for item in base]
    origins = {}
    for cid, probe_index, rank, score in round_robin:
        item = {"probe_index": probe_index, "rank": rank, "score": score,
                "term_sha256": probes[probe_index]["term_sha256"],
                "document_frequency": probes[probe_index]["document_frequency"]}
        origins.setdefault(cid, []).append(item)
    for row in base:
        if row["id"] in origins:
            row["probe_origins"] = origins[row["id"]]

    head = base[:seed_limit]
    head_ids = {item["id"] for item in head}
    base_tail = base[seed_limit:]
    tail_ids = {item["id"] for item in base_tail}
    capacity = max(0, fusion_limit - len(head))
    reserved_ids, skipped = set(), []
    for cid, _, _, _ in round_robin:
        if cid in head_ids or cid in reserved_ids:
            continue
        if len(reserved_ids) >= capacity:
            skipped.append(cid)
            continue
        reserved_ids.add(cid)
    new_ids = [cid for cid, _, _, _ in round_robin
               if cid in reserved_ids and cid not in tail_ids and cid not in head_ids]
    new_ids = list(dict.fromkeys(new_ids))
    additions = [{"id": cid, "rrf_score": 0.0, "fusion_score": 0.0,
                  "matches": [], "candidate_origin": "lexical_probe",
                  "probe_origins": origins[cid]} for cid in new_ids]
    required_tail = reserved_ids & tail_ids
    tail_capacity = max(0, fusion_limit - len(head) - len(additions))
    keep_tail = set(required_tail)
    optional_slots = max(0, tail_capacity - len(keep_tail))
    for row in base_tail:
        if row["id"] not in keep_tail and optional_slots:
            keep_tail.add(row["id"])
            optional_slots -= 1
    tail = [row for row in base_tail if row["id"] in keep_tail]
    output = head + additions + tail
    output_ids = {row["id"] for row in output}
    order = []
    for cid, _, _, _ in round_robin:
        if cid in output_ids and cid not in order:
            order.append(cid)
    # Report base-tail rows omitted to preserve admitted probe hits/cap.
    kept_base = {row["id"] for row in output if row["id"] in base_ids}
    trace["evicted_tail_child_ids"] = [cid for cid in base_ids[seed_limit:] if cid not in kept_base]
    trace["skipped_probe_child_ids"] = list(dict.fromkeys(skipped))
    for row in trace["probes"]:
        hit_ids = [hit["child_id"] for hit in row["hits"]]
        row["admitted_child_ids"] = [cid for cid in order if cid in hit_ids]
        row["skipped_child_ids"] = list(dict.fromkeys(cid for cid in hit_ids if cid not in output_ids))
    return output, trace, order
