"""Query-focused extractive context over current authorized candidate payloads.

No source rewriting, grants, gold spans or subject routing. An opt-in semantic
strategy may use a caller-supplied local scorer over bounded source windows.
Paragraphs are reader evidence units, not replacement embedding/index chunks.
"""
from __future__ import annotations

import hashlib
import math
import re

from ..chunking.boundary_cost import quoted_spans, starts_dependent
from ..chunking.chunking import protected_spans
from ..chunking.chunk_views import eligible_with_context, materialize
from .neighbor_context import partition, window
from ..search.passage_rank import PassageBM25
from ..chunking.token_budget import contextualize

PASSAGE_CONTEXT_VERSION = "idp-extractive-context-2"
MAX_CANDIDATE_PASSAGES = 512
_LIST = re.compile(r"^\s*(?:[-+*•–]|[A-Da-d](?:[).:]|[ \t]*[–—-])|\d+[).])\s")


def _paragraphs(text, *, atomic):
    if atomic:
        return [(0, len(text))]
    protected = protected_spans(text) + quoted_spans(text)
    cuts = [0] + [m.end() for m in re.finditer(r"\n[ \t]*\n+", text)
                  if not any(a < m.end() < b for a, b in protected)] + [len(text)]
    result, last_part = [], ""
    for a, b in zip(cuts, cuts[1:]):
        if not text[a:b].strip():
            continue
        previous = text[result[-1][0]:a] if result else ""
        current = text[a:b]
        if result and (previous.rstrip().endswith((":", "："))
                       or starts_dependent(current)
                       or (_LIST.match(last_part) and _LIST.match(current))):
            result[-1] = (result[-1][0], b)
        else:
            result.append((a, b))
        last_part = current
    return result


def _slice(run, a, b):
    original = run["record"]
    text = original["text"][a:b]
    spans = []
    for span in original["source_spans"]:
        x, y = max(a, span["start"]), min(b, span["end"])
        if x < y:
            start = span["source_start"] + x - span["start"]
            spans.append({**span, "start": x - a, "end": y - a,
                          "source_start": start, "source_end": start + y - x,
                          "text_sha256": hashlib.sha256(original["text"][x:y].encode()).hexdigest()})
    signature = f"{run['id']}:{a}:{b}"
    return {"id": "passage_" + hashlib.sha256(signature.encode()).hexdigest()[:20],
        "level": "passage", "source_id": original["source_id"],
        "section_path": list(original["section_path"]), "text": text,
        "context_path": list(run["path"]),
        "search_text": contextualize(run["path"], text), "source_spans": spans,
        **({"source_quality_warnings": list(original["source_quality_warnings"])}
           if original.get("source_quality_warnings") else {}),
        "child_ids": [cid for cid, x, y in run["children"] if max(x, a) < min(y, b)],
        "parent_id": run["parent_id"], "parent_start": run["parent_start"] + a,
        "parent_end": run["parent_start"] + b}


def _runs(children, parents, ids):
    pool = set(ids)
    priority = {cid: i for i, cid in enumerate(ids)}
    seen = set()
    runs = []
    for cid in ids:
        if cid in seen:
            continue
        child = children[cid]
        parent = parents.get(child["parent_id"])
        if not parent or cid not in parent["child_ids"]:
            raise ValueError("broken parent/child link")
        valid = partition(parent, children)
        siblings = parent["child_ids"] if valid else [cid]
        groups, group = [], []
        for other in siblings:
            if other in pool and other not in seen:
                group.append(other)
            elif group:
                groups.append(group); group = []
        if group:
            groups.append(group)
        for group in groups:
            seen.update(group)
            record = window(group, children)
            offset, spans = 0, []
            for other in group:
                end = offset + len(children[other]["text"])
                spans.append((other, offset, end)); offset = end
            first = children[group[0]]
            runs.append({"id": ":".join(group), "record": record, "children": spans,
                "path": list(first.get("context_path", first["section_path"])),
                "parent_id": first["parent_id"], "parent_start": first["parent_start"],
                "atomic": bool(parent.get("atomic")) or first.get("unit_kind", "prose") != "prose"
                          or not valid,
                "priority": min(priority[x] for x in group)})
    return runs


def _merge_source_ranges(ranges):
    merged = []
    for source_id, start, end in sorted(ranges):
        if merged and merged[-1][0] == source_id and start <= merged[-1][2]:
            old_source, old_start, old_end = merged[-1]
            merged[-1] = (old_source, old_start, max(old_end, end))
        else:
            merged.append((source_id, start, end))
    return merged


def _coverage(record, already_covered):
    """Count unique nonspace source characters newly represented by a record."""
    ranges = list(already_covered)
    added, total = 0, 0
    text = record["text"]
    for span in sorted(record.get("source_spans", []),
                       key=lambda x: (record["source_id"], x["source_start"], x["source_end"])):
        source_id = record["source_id"]
        source_start, source_end = span["source_start"], span["source_end"]
        local_start, local_end = span["start"], span["end"]
        value = text[local_start:local_end]
        if source_end - source_start != len(value):
            raise ValueError("invalid source span for passage coverage")
        covered_here = [(a, b) for sid, a, b in ranges if sid == source_id]
        for offset, char in enumerate(value):
            source_offset = source_start + offset
            if char.isspace():
                continue
            total += 1
            if not any(a <= source_offset < b for a, b in covered_here):
                added += 1
        ranges.append((source_id, source_start, source_end))
        ranges = _merge_source_ranges(ranges)
    return added, total, ranges


def passage_context(bundle, ranked_child_ids, *, query, allowed_child_ids, counter,
                    max_tokens, max_passages=8, fold_accents=False, primary_seed_ids=(),
                    paragraph_window=0, bigrams=False, strategy="bm25", reranker=None):
    """Return None with a reason when the explicit chunk fallback is needed.

    Body/title/path BM25 ranks indivisible evidence units; original child rank
    breaks ties. Zero-score units are not used to fill spare space. This lexical
    heuristic does not verify answerability or cover implicit semantic matches.
    ``cross_encoder`` scores bounded sentence windows with the supplied local
    reranker and falls back explicitly when it is absent or cannot score them.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("nonempty passage query required")
    if (type(max_tokens) is not int or max_tokens < 1 or type(max_passages) is not int
            or not 1 <= max_passages <= 50 or type(fold_accents) is not bool
            or type(paragraph_window) is not int or not 0 <= paragraph_window <= 2
            or type(bigrams) is not bool
            or not isinstance(strategy, str)
            or strategy not in {"bm25", "rank_lexical", "rank_lexical_density", "cross_encoder", "sentence_lexical"}
            or not isinstance(allowed_child_ids, set)):
        raise ValueError("invalid passage context policy")
    if counter.count("") > max_tokens:
        raise ValueError("budget cannot accommodate tokenizer special tokens")
    children = {c["id"]: c for c in bundle["children"]}
    parents = {p["id"]: p for p in bundle["parents"]}
    if len(children) != len(bundle["children"]) or len(parents) != len(bundle["parents"]):
        raise ValueError("duplicate chunk IDs")
    eligible = {cid for cid, c in children.items() if cid in allowed_child_ids and c["retrieval_eligible"]}
    eligible = eligible_with_context(children, parents, eligible)
    ids = list(dict.fromkeys(cid for cid in ranked_child_ids if cid in eligible))
    trace = {"version": PASSAGE_CONTEXT_VERSION, "candidate_child_ids": ids,
             "ranking": "fielded_bm25_then_child_rank", "fold_accents": fold_accents,
             "paragraph_window": paragraph_window, "bigrams": bigrams,
             "fallback_reason": None, "oversized_unit_fallbacks": 0}
    if strategy == "cross_encoder" and (reranker is None or not callable(getattr(reranker, "score", None))):
        return None, {**trace, "strategy": strategy, "fallback_reason": "reranker_unavailable"}
    render = lambda records: "\n\n".join(f"[{r['id']}]\n{r['search_text']}" for r in records)
    runs = _runs(children, parents, ids)
    candidates = []
    if strategy in {"cross_encoder", "sentence_lexical"}:
        from .semantic_packing import (MAX_SEMANTIC_WINDOWS, bounded_fair_windows,
            prioritize_windows, sentence_windows)
        per_run, ordering_steps = [], []
        for run in runs:
            natural = sentence_windows(run["record"]["text"], atomic=run["atomic"], context_sentences=1)
            ordered, steps = prioritize_windows(natural)
            per_run.append(ordered)
            ordering_steps.append(steps)
        bounded, dropped_runs = bounded_fair_windows(per_run,
            run_sources=[run["record"]["source_id"] for run in runs], limit=MAX_SEMANTIC_WINDOWS)
        eligible_sources = sorted({run["record"]["source_id"] for run in runs})
        dropped_source_counts = {}
        for i in dropped_runs:
            source_id = runs[i]["record"]["source_id"]
            dropped_source_counts[source_id] = dropped_source_counts.get(source_id, 0) + 1
        trace.update(strategy=strategy, window_candidate_count=sum(map(len, per_run)),
                     candidate_window_cap=MAX_SEMANTIC_WINDOWS, capped_window_count=len(dropped_runs),
                     capped_run_ids=[runs[i]["id"] for i in dropped_runs],
                     eligible_pool_sources=eligible_sources, cap_loss_by_source=dropped_source_counts,
                     sentence_context=1,
                     window_ordering="query_independent_novel_source_coverage_then_widest_then_later_anchor",
                     ordering_steps_by_run={runs[i]["id"]: steps for i, steps in enumerate(ordering_steps)})
        source_windows = [(ri, window) for ri, window in bounded]
    else:
        source_windows = []
        for ri, run in enumerate(runs):
            units = _paragraphs(run["record"]["text"], atomic=run["atomic"])
            for ui, (anchor_a, anchor_b) in enumerate(units):
                a = units[max(0, ui - paragraph_window)][0]
                b = units[min(len(units) - 1, ui + paragraph_window)][1]
                source_windows.append((ri, (a, b, anchor_a, anchor_b)))
    for ri, (a, b, anchor_a, anchor_b) in source_windows:
        run = runs[ri]
        record = _slice(run, a, b)
        intervals = [(a, b)]
        fallback = False
        if (counter.count(render([record])) > max_tokens and not run["atomic"]
                and strategy not in {"cross_encoder", "sentence_lexical"}):
            # Preserve the original validated chunk fallback, never clip an
            # oversized paragraph to a keyword or arbitrary character count.
            intervals = [(x, y) for _, x, y in run["children"] if max(x, anchor_a) < min(y, anchor_b)]
            fallback = True
            trace["oversized_unit_fallbacks"] += 1
        for x, y in intervals:
            r = _slice(run, x, y)
            candidates.append({"run": ri, "a": x, "b": y, "record": r,
                "anchor": r if fallback else _slice(run, anchor_a, anchor_b),
                "priority": run["priority"]})
            if len(candidates) > MAX_CANDIDATE_PASSAGES:
                return None, {**trace, "fallback_reason": "candidate_limit"}
    # Identical intervals can arise from oversized units sharing one child.
    candidates = list({(c["record"]["id"], c["anchor"]["id"]): c for c in candidates}.values())
    if strategy in {"cross_encoder", "sentence_lexical"}:
        source_counts = {}
        for candidate in candidates:
            source_id = candidate["record"]["source_id"]
            source_counts[source_id] = source_counts.get(source_id, 0) + 1
        trace["candidate_source_counts"] = source_counts
        trace["candidate_window_manifest"] = [{
            "passage_id": candidate["record"]["id"],
            "source_id": candidate["record"]["source_id"],
            "parent_id": candidate["record"]["parent_id"],
            "parent_start": candidate["record"]["parent_start"],
            "parent_end": candidate["record"]["parent_end"],
            "candidate_text_sha256": hashlib.sha256(candidate["record"]["text"].encode()).hexdigest(),
            "source_spans": [{"source_start": span["source_start"],
                "source_end": span["source_end"], "text_sha256": span["text_sha256"]}
                for span in candidate["record"].get("source_spans", [])],
        } for candidate in candidates]
    for i, c in enumerate(candidates):
        c["key"] = f"candidate_{i}"
    rows = [{**materialize(c["anchor"], children, parents, eligible), "id": c["key"],
             "context_path": runs[c["run"]]["path"]} for c in candidates]
    scores = {}
    rank_details = {}
    if strategy == "bm25":
        lexical = PassageBM25(rows, fold_accents=fold_accents, bigrams=bigrams)
        scores = dict(lexical.rank(query))
        ranked = sorted((c for c in candidates if scores.get(c["key"], 0) > 0),
            key=lambda c: (-scores[c["key"]], c["priority"], c["run"], c["a"]))
    elif strategy == "cross_encoder":
        from ..search.text_reranking import PairBudgetError
        trace["strategy"] = strategy
        trace["ranking"] = "local_cross_encoder_raw_logit"
        try:
            values, stats = reranker.score(query, [c["record"]["text"] for c in candidates])
            values = [float(x) for x in values]
            if len(values) != len(candidates) or any(not math.isfinite(x) for x in values):
                raise ValueError("invalid cross-encoder output")
        except PairBudgetError:
            return None, {**trace, "fallback_reason": "cross_encoder_pair_budget"}
        except Exception:
            return None, {**trace, "fallback_reason": "cross_encoder_runtime"}
        scores = {c["key"]: float(value) for c, value in zip(candidates, values)}
        for candidate in candidates:
            candidate["score"] = scores[candidate["key"]]
            rank_details[candidate["key"]] = {"passage_id": candidate["record"]["id"],
                "candidate_text_sha256": hashlib.sha256(candidate["record"]["text"].encode()).hexdigest(),
                "cross_encoder_score": candidate["score"]}
        ranked = sorted(candidates, key=lambda c: (-c["score"], c["priority"], c["run"], c["a"]))
        trace["score_stats"] = stats
        trace["rank_details"] = [rank_details[c["key"]] for c in ranked]
    elif strategy == "sentence_lexical":
        body_rows = [{"id": c["key"], "text": c["record"]["text"],
            "index_body": c["record"]["text"], "section_path": [], "context_path": []}
            for c in candidates]
        body_ranked = PassageBM25(body_rows, fold_accents=fold_accents, bigrams=bigrams).rank(query)
        body_positions = {cid: rank + 1 for rank, (cid, _) in enumerate(body_ranked)}
        ranked = sorted(candidates, key=lambda c: (body_positions.get(c["key"], 10**9),
            c["priority"], c["run"], c["a"], c["record"]["id"]))
        trace["ranking"] = "sentence_window_body_bm25_rank"
        trace["rank_details"] = [{"passage_id": c["record"]["id"],
            "body_bm25_rank": body_positions.get(c["key"])} for c in ranked]
    else:
        # The comparative rank arm intentionally scores only materialized body
        # text. Titles and paths are blank, and the query remains unmodified.
        body_rows = [{"id": c["key"], "text": row["text"],
            "index_body": row["text"], "section_path": [], "context_path": []}
            for c, row in zip(candidates, rows)]
        body_ranked = PassageBM25(body_rows, fold_accents=fold_accents, bigrams=bigrams).rank(query)
        body_scores = dict(body_ranked)
        body_positions = {cid: rank + 1 for rank, (cid, _) in enumerate(body_ranked)}
        child_positions = {cid: rank + 1 for rank, cid in enumerate(ids)}
        for candidate in candidates:
            anchor_children = candidate["anchor"].get("child_ids", [])
            positions = [child_positions[cid] for cid in anchor_children if cid in child_positions]
            if not positions:
                # A validated candidate always maps to at least one eligible
                # owner; fail closed if that invariant ever changes.
                continue
            child_rank = min(positions)
            body_rank = body_positions.get(candidate["key"])
            prior_score = 1.0 / (60 + child_rank)
            body_support = body_scores.get(candidate["key"], 0.0)
            score = prior_score + (1.0 / (60 + body_rank) if body_rank is not None and body_support > 0 else 0.0)
            candidate["score"] = score
            rank_details[candidate["key"]] = {"passage_id": candidate["record"]["id"],
                "child_prior_rank": child_rank, "body_bm25_rank": body_rank,
                "body_bm25_score": body_support, "combined_score": score}
        ranked = sorted((c for c in candidates if "score" in c),
            key=lambda c: (-c["score"], min(child_positions.get(cid, 10**9)
                for cid in c["anchor"].get("child_ids", [])), c["run"], c["a"], c["record"]["id"]))
        trace["strategy"] = strategy
        trace["ranking"] = "body_bm25_reciprocal_rank_plus_anchor_child_prior"
        trace["rank_details"] = [rank_details[c["key"]] for c in ranked]
    trace["candidate_passages"] = len(candidates)
    if ids and not ranked:
        return None, {**trace, "fallback_reason": "no_lexical_support"}

    def compact(selected):
        groups = {}
        for rank, c in enumerate(selected):
            groups.setdefault(c["run"], []).append((c["a"], c["b"], rank))
        output = []
        for ri, group in groups.items():
            merged = []
            for a, b, rank in sorted(group):
                if merged and a <= merged[-1][1]:
                    x, y, old_rank = merged[-1]
                    merged[-1] = (x, max(y, b), min(old_rank, rank))
                else:
                    merged.append((a, b, rank))
            output.extend((rank, _slice(runs[ri], a, b)) for a, b, rank in merged)
        return [materialize(r, children, parents, eligible)
                for _, r in sorted(output, key=lambda x: (x[0], x[1]["id"]))]

    selected, skipped, records, fingerprints = [], [], [], set()
    if strategy != "rank_lexical_density":
        for candidate in ranked:
            if len(selected) >= max_passages:
                break
            record = candidate["record"]
            fingerprint = (record["source_id"], tuple(record["section_path"]),
                           " ".join(record["text"].split()))
            if fingerprint in fingerprints:
                continue
            proposed = compact(selected + [candidate])
            if proposed == records:
                continue
            if counter.count(render(proposed)) > max_tokens:
                skipped.append(candidate)
                continue
            selected.append(candidate); records = proposed; fingerprints.add(fingerprint)
    else:
        remaining = list(ranked)
        density_attempts = []
        unit_records, unit_costs = {}, {}
        for candidate in ranked:
            unit = compact([candidate])[0]
            unit_records[candidate["key"]] = unit
            unit_costs[candidate["key"]] = counter.count(render([unit]))
        while remaining and len(selected) < max_passages:
            covered = []
            for record in records:
                _, _, covered = _coverage(record, covered)
            choices = []
            for candidate in remaining:
                record = unit_records[candidate["key"]]
                added, total, _ = _coverage(record, covered)
                fingerprint = (record["source_id"], tuple(record["section_path"]),
                               " ".join(record["text"].split()))
                unit_cost = unit_costs[candidate["key"]]
                fraction = added / total if total else 0.0
                utility = (candidate["score"] * fraction / math.sqrt(max(1, unit_cost)))
                choices.append((candidate, added, total, unit_cost, fraction, utility, fingerprint))
            # Highest estimated density first; stable rank and ID break ties.
            choices.sort(key=lambda x: (-x[5], -x[0]["score"],
                min(child_positions.get(cid, 10**9) for cid in x[0]["anchor"].get("child_ids", [])),
                x[0]["record"]["id"]))
            candidate, added, total, unit_cost, fraction, utility, fingerprint = choices[0]
            remaining.remove(candidate)
            attempt = {"passage_id": candidate["record"]["id"], "new_source_chars": added,
                "candidate_source_chars": total, "new_coverage_fraction": fraction,
                "single_unit_token_cost": unit_cost, "estimated_density": utility,
                "combined_context_token_count": None, "selected": False, "reason": None}
            if fingerprint in fingerprints:
                attempt["reason"] = "duplicate"
            elif added == 0 or total == 0:
                attempt["reason"] = "no_new_source_coverage"
            else:
                proposed = compact(selected + [candidate])
                if proposed == records:
                    attempt["reason"] = "no_context_change"
                else:
                    actual_count = counter.count(render(proposed))
                    attempt["combined_context_token_count"] = actual_count
                    if actual_count > max_tokens:
                        skipped.append(candidate)
                        attempt["reason"] = "exact_budget"
                    else:
                        selected.append(candidate); records = proposed
                        fingerprints.add(fingerprint); attempt["selected"] = True
            density_attempts.append(attempt)
        trace["selection_utility"] = "score * new_nonspace_source_fraction / sqrt(single_unit_rendered_tokens)"
        trace["selection_attempts"] = density_attempts
    text = render(records)
    if ids and not selected:
        return None, {**trace, "fallback_reason": "no_passage_fits"}
    trace["selected_passage_ids"] = [c["record"]["id"] for c in selected]
    trace["selected_scores"] = [scores[c["key"]] if strategy == "bm25" else c.get("score")
                                 for c in selected]
    return {"version": PASSAGE_CONTEXT_VERSION, "context": text, "items": records,
        "budget_count": counter.count(text), "budget_unit": counter.identity["unit"],
        "mode": "passages", "seed_child_ids": [cid for cid in primary_seed_ids if cid in eligible],
        "candidate_child_ids": ids,
        "selected_child_ids": list(dict.fromkeys(cid for r in records for cid in r["child_ids"])),
        "skipped_budget_child_ids": list(dict.fromkeys(cid for c in skipped for cid in c["record"]["child_ids"])),
        "skipped_budget_passage_ids": [c["record"]["id"] for c in skipped],
        "grants_authorization": False}, trace
