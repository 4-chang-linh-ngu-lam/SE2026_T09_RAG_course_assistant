"""Version-bound, authorization-scoped offline retrieval for educational text.

Owns no service DB, source grants or ingestion pipeline. Exact search is a small
corpus reference, not an ANN/HTTP server. Authorization is a REQUIRED fresh caller
callback, checked before retrieval and again before returning any source payload.
"""
from __future__ import annotations

from collections import defaultdict
import copy
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import math
import time

from ..chunking.chunking import validate_chunking
from ..chunking.chunk_views import eligible_with_context
from ..indexing.embedding_store import load_generation, profile_id
from ..packing.retrieval_context import expand_context
from ..search.retrieval_bridge import bridge_rankings
from ..search.retrieval_lexical import FieldedBM25, accent_fold
from ..search.retrieval_diversity import mmr_ids
from ..search.retrieval_fusion import fuse_rankings
from ..search.retrieval_probes import augment_fused, probe_candidates
from ..packing.passage_context import passage_context
from ..search.retrieval_plan import (
    SearchRequest, anchors, exercise_anchors, exercise_query_anchors,
    facet_supported, make_plan, topic_terms,
)
from ..search.text_reranking import PairBudgetError

RETRIEVAL_VERSION = "idp-text-retrieval-2"


class AccessChangedError(PermissionError):
    """Discard this result; the caller must retry with fresh current grants."""


@dataclass(frozen=True)
class RetrievalConfig:
    arms: tuple[str, ...] = ("dense", "lexical", "structure", "section")
    recall_per_arm: int = 20
    fusion_limit: int = 40
    rerank_limit: int = 20
    seed_limit: int = 8
    context_tokens: int = 2048
    rrf_constant: int = 60
    neighbor_radius: int = 1
    linked_unit_limit: int = 4
    decompose_comparisons: bool = True
    balance_facets: bool = True
    enable_recovery: bool = True
    soft_deadline_ms: int = 10000
    seed_selection: str = "ranked"
    mmr_weight: float = .7
    accent_fallback: bool = True
    fusion_method: str = "rrf"
    lexical_fusion_weight: float = 1.0
    lexical_probe_limit: int = 0
    lexical_probe_hits: int = 2
    probe_seed_limit: int = 0
    context_selection: str = "chunks"
    passage_pool: str = "seeds"
    passage_window: int = 0
    passage_bigrams: bool = False
    context_expansion: str = "neighbors"
    compact_seed_reservation: bool = False
    extend_continuations: bool = False
    passage_strategy: str = "bm25"
    passage_gate: str = "always"
    # Lexical bridge hop (search/retrieval_bridge.py); 0 keeps it off.
    bridge_seeds: int = 0

    def __post_init__(self):
        if type(self.passage_window) is not int or not 0 <= self.passage_window <= 2:
            raise ValueError("invalid passage window")
        if type(self.passage_bigrams) is not bool:
            raise ValueError("passage_bigrams must be bool")
        if not isinstance(self.context_selection, str) or self.context_selection not in {"chunks", "passages"}:
            raise ValueError("invalid context selection")
        if not isinstance(self.passage_pool, str) or self.passage_pool not in {"seeds", "fused"}:
            raise ValueError("invalid passage pool")
        if not isinstance(self.passage_strategy, str) or self.passage_strategy not in {
                "bm25", "rank_lexical", "rank_lexical_density", "cross_encoder", "sentence_lexical"}:
            raise ValueError("invalid passage strategy")
        if not isinstance(self.passage_gate, str) or self.passage_gate not in {"always", "accent_fallback"}:
            raise ValueError("invalid passage gate")
        if not isinstance(self.fusion_method, str) or self.fusion_method not in {"rrf", "relative_score"}:
            raise ValueError("invalid fusion method")
        if (type(self.lexical_fusion_weight) not in (int, float)
                or not math.isfinite(self.lexical_fusion_weight)
                or not 0 < self.lexical_fusion_weight <= 10):
            raise ValueError("lexical_fusion_weight must be finite numeric in (0, 10]")
        if type(self.bridge_seeds) is not int or not 0 <= self.bridge_seeds <= 4:
            raise ValueError("bridge_seeds must be an integer in 0..4")
        if self.bridge_seeds and "lexical" not in self.arms:
            raise ValueError("bridge_seeds requires the lexical arm")
        if type(self.lexical_probe_limit) is not int or not 0 <= self.lexical_probe_limit <= 4:
            raise ValueError("lexical_probe_limit must be an integer in 0..4")
        if type(self.lexical_probe_hits) is not int or not 1 <= self.lexical_probe_hits <= 4:
            raise ValueError("lexical_probe_hits must be an integer in 1..4")
        if (type(self.probe_seed_limit) is not int or not 0 <= self.probe_seed_limit <= 4
                or type(self.seed_limit) is not int or self.probe_seed_limit > self.seed_limit - 1
                or (self.probe_seed_limit > 0 and self.lexical_probe_limit == 0)):
            raise ValueError("probe_seed_limit must be 0..4, below seed_limit, and enabled by lexical probes")
        if not isinstance(self.context_expansion, str) or self.context_expansion not in {"neighbors", "parent_then_neighbors"}:
            raise ValueError("invalid context expansion policy")
        if (not isinstance(self.seed_selection, str) or self.seed_selection not in {"ranked", "mmr"}
                or type(self.mmr_weight) not in (float, int)
                or not 0 <= self.mmr_weight <= 1):
            raise ValueError("invalid seed selection/MMR weight")
        if (not isinstance(self.arms, tuple) or not self.arms or len(set(self.arms)) != len(self.arms)
                or set(self.arms) - {"dense", "lexical", "structure", "section"}):
            raise ValueError("unique supported retrieval arms required")
        limits = {"recall_per_arm": (1, 200), "fusion_limit": (1, 500), "rerank_limit": (1, 100),
            "seed_limit": (1, 50), "context_tokens": (8, 32768), "rrf_constant": (1, 1000),
            "neighbor_radius": (0, 3), "linked_unit_limit": (0, 20), "soft_deadline_ms": (1, 60000)}
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid {name}")
        if not self.seed_limit <= self.rerank_limit <= self.fusion_limit:
            raise ValueError("seed_limit <= rerank_limit <= fusion_limit required")
        for name in ("decompose_comparisons", "balance_facets", "enable_recovery", "accent_fallback",
                     "compact_seed_reservation", "extend_continuations"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be bool")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _authorization(callback, known):
    if not callable(callback):
        raise PermissionError("fresh authorization callback is required")
    try:
        value = callback()
    except Exception:
        raise PermissionError("current authorization could not be verified") from None
    if not isinstance(value, set):
        raise PermissionError("authorization must return known current child IDs")
    # The provider may mutate and reuse the same set between checks.
    snapshot = set(value)
    if any(not isinstance(x, str) for x in snapshot) or not snapshot <= known:
        raise PermissionError("authorization must return known current child IDs")
    return snapshot


def authorize(callback, known):
    """Validate a fresh authorized child-ID snapshot for query serving."""
    return _authorization(callback, known)


class TextRetriever:
    def __init__(self, bundles, *, sources, generation_dir, encoder, chunk_counter,
                 context_counter=None, config=None, reranker=None):
        import numpy as np
        self.np, self.encoder, self.reranker = np, encoder, reranker
        self.config = RetrievalConfig() if config is None else config
        if not isinstance(self.config, RetrievalConfig):
            raise ValueError("RetrievalConfig required")
        self.counter = context_counter or encoder.counter
        if self.counter.identity.get("unit") != "tokens":
            raise ValueError("real tokenizer required for retrieval context budgets")
        bundles = copy.deepcopy(bundles)
        if not isinstance(bundles, list) or not bundles:
            raise ValueError("current source chunk bundles required")
        children, parents, bindings = {}, {}, {}
        source_ids = set()
        for bundle in bundles:
            sid = bundle["source_id"]
            if sid in source_ids or sid not in sources:
                raise ValueError("unique, current source texts required")
            source_ids.add(sid)
            errors = validate_chunking(bundle, sources[sid], chunk_counter)
            if errors:
                raise ValueError("current chunk export failed validation")
            for parent in bundle["parents"]:
                if parent["id"] in parents:
                    raise ValueError("duplicate parent ID")
                parents[parent["id"]] = parent
            for child in bundle["children"]:
                cid = child["id"]
                if cid in children:
                    raise ValueError("duplicate child ID")
                children[cid] = child
                bindings[cid] = {"chunk_id": cid, "source_id": sid,
                    "source_sha256": bundle["source_text_sha256"], "chunk_export_id": bundle["export_id"]}
        rows, vectors, profile, manifest = load_generation(generation_dir)
        if profile.get("encoder") != encoder.identity:
            raise ValueError("query encoder differs from stored passage profile")
        expected_ids = {cid for cid, c in children.items() if c["retrieval_eligible"]}
        if {r["chunk_id"] for r in rows} != expected_ids:
            raise ValueError("index does not cover exactly current eligible chunks")
        prefix = encoder.identity.get("passage_prefix", "")
        for row in rows:
            cid = row["chunk_id"]
            text = prefix + children[cid]["search_text"]
            expected = {**bindings[cid], "embedding_input_sha256": _sha(text),
                        "input_tokens": encoder.counter.count(text)}
            if any(row.get(k) != v for k, v in expected.items()):
                raise ValueError("index source/input/token binding differs from current chunks")
        # The generation is immutable. Runtime candidates are indexed by its row
        # order, never by a separately sorted chunk registry.
        self.children, self.parents = children, parents
        self.bundle = {"children": list(children.values()), "parents": list(parents.values())}
        self.row_ids = [r["chunk_id"] for r in rows]
        self.position = {cid: i for i, cid in enumerate(self.row_ids)}
        # Reuse only an identical authorized, eligible and scoped row set.
        # The bounded cache is local to this immutable corpus generation.
        self._lexical_index = lru_cache(maxsize=4)(self._build_lexical_index)
        self._path_anchors = {
            cid: anchors(" > ".join(c.get("context_path", c["section_path"])) + " " + c.get("unit_label", ""))
            for cid, c in children.items()
        }
        self._exercise_anchors = {cid: exercise_anchors(c) for cid, c in children.items()}
        self.vectors, self.profile = vectors, profile
        self.identity = {"version": RETRIEVAL_VERSION, "profile_id": profile_id(profile),
            "ordered_ids_sha256": manifest["ordered_ids_sha256"], "config": asdict(self.config),
            "chunk_counter": copy.deepcopy(chunk_counter.identity),
            "context_counter": copy.deepcopy(self.counter.identity),
            "reranker": copy.deepcopy(reranker.identity) if reranker else None}
        if self.config.passage_strategy in {"cross_encoder", "sentence_lexical"}:
            from ..packing.semantic_packing import SEMANTIC_PACKING_VERSION
            self.identity["semantic_packing"] = SEMANTIC_PACKING_VERSION

    def _build_lexical_index(self, eligible, fold_accents):
        return FieldedBM25([self.children[cid] for cid in self.row_ids if cid in eligible],
                           fold_accents=fold_accents)

    def _query_vector(self, text, cache):
        if text not in cache:
            vectors, _ = self.encoder.encode([text], role="query", batch_size=1)
            np = self.np
            if (not isinstance(vectors, np.ndarray) or vectors.shape != (1, self.vectors.shape[1])
                    or vectors.dtype != np.float32 or not np.isfinite(vectors).all()
                    or not .999 <= np.linalg.norm(vectors[0]) <= 1.001):
                raise ValueError("invalid query vector; refusing mismatched/corrupt search")
            cache[text] = vectors[0]
        return cache[text]

    def _collect(self, plan, eligible, lexical, request, depth, cache, folded=None):
        np = self.np
        children = [self.children[cid] for cid in self.row_ids if cid in eligible]
        arms = []
        accent_trace = []
        probe_lexical = lexical
        for qi, query in enumerate(plan["queries"]):
            dense, lex = {}, {}
            if "dense" in self.config.arms:
                ids = [c["id"] for c in children]
                indices = [self.position[cid] for cid in ids]
                values = self.vectors[indices] @ self._query_vector(query, cache)
                dense = dict(zip(ids, (float(x) for x in values)))
                ranked = sorted(ids, key=lambda cid: (-dense[cid], cid))
                arms.append(("dense", qi, [(cid, dense[cid]) for cid in ranked[:depth]]))
            if "lexical" in self.config.arms or "section" in self.config.arms:
                lex = dict(lexical.rank(query))
                lexical_arm = "lexical"
                if folded is not None and accent_fold(query) == query.casefold():
                    original_matches = lexical.matched_term_count(query)
                    folded_matches = folded.matched_term_count(query)
                    used = folded_matches > original_matches
                    accent_trace.append({"query_index": qi, "original_matched_terms": original_matches,
                        "folded_matched_terms": folded_matches, "applied": used})
                    if used:
                        # Replace a weaker lexical representation, rather than
                        # giving the lexical family two votes in RRF. The dense
                        # query, source text, units and citations stay original.
                        lex = dict(folded.rank(query))
                        lexical_arm = "lexical_accent_fallback"
                        if qi == 0:
                            probe_lexical = folded
                if "lexical" in self.config.arms:
                    arms.append((lexical_arm, qi, list(lex.items())[:depth]))
                if self.config.bridge_seeds and qi == 0:
                    # Second evidence for two-hop questions: one extra RRF arm
                    # per seed, from the same authorized lexical statistics.
                    bridge_index = folded if lexical_arm == "lexical_accent_fallback" else lexical
                    rankings, _ = bridge_rankings(
                        bridge_index, query, list(lex),
                        lambda cid: self.children[cid].get("index_body", self.children[cid]["text"]),
                        seeds=self.config.bridge_seeds)
                    arms.extend(("lexical_bridge", qi, ranking[:depth]) for ranking in rankings)
            if "structure" in self.config.arms:
                wanted = set(plan["query_anchors"][qi])
                tasks = exercise_query_anchors(wanted)
                remaining = {anchor for anchor in wanted if not exercise_query_anchors([anchor])}
                task_matches = [cid for cid in eligible if tasks and tasks <= self._exercise_anchors[cid]
                                and remaining <= self._path_anchors[cid]]
                # Prefer an actual numbered exercise over a same-number lesson.
                matches = task_matches or [cid for cid in eligible if wanted and wanted <= self._path_anchors[cid]]
                matches.sort(key=lambda cid: (-lex.get(cid, 0), -dense.get(cid, 0), cid))
                arms.append(("structure", qi, [(cid, float(len(wanted))) for cid in matches[:depth]]))
            if "section" in self.config.arms:
                wanted = topic_terms(query)
                groups = defaultdict(list)
                group_score = {}
                for child in children:
                    score = len(wanted & topic_terms(" > ".join(child["section_path"])))
                    if score:
                        key = (child["source_id"], child["section_id"])
                        groups[key].append(child["id"])
                        group_score[key] = score
                section_hits = []
                for key in sorted(groups, key=lambda k: (-group_score[k], k)):
                    best = sorted(groups[key], key=lambda cid: (-lex.get(cid, 0), -dense.get(cid, 0), cid))[:2]
                    section_hits.extend((cid, float(group_score[key])) for cid in best)
                arms.append(("section", qi, section_hits[:depth]))
            # A focus is a preference, never a replacement for globally allowed
            # recall. Explicit scope_source_ids, unlike focus, is a hard scope.
            if request.focus_source_ids:
                for name, idx, ranking in list(arms):
                    if idx == qi and name in {"dense", "lexical", "lexical_accent_fallback"}:
                        all_scores = dense if name == "dense" else lex
                        focused = [(cid, score) for cid, score in all_scores.items()
                                   if self.children[cid]["source_id"] in request.focus_source_ids]
                        focused.sort(key=lambda item: (-item[1], item[0]))
                        arms.append(("focus_" + name, qi, focused[:depth]))
        ordered = fuse_rankings(arms, method=self.config.fusion_method,
                                rrf_constant=self.config.rrf_constant,
                                lexical_weight=self.config.lexical_fusion_weight)
        direct_matches = {cid for name, qi, ranking in arms if name == "structure" and qi == 0
                          for cid, _ in ranking}
        if direct_matches:
            ordered.sort(key=lambda row: row["id"] not in direct_matches)
        selected = ordered[:self.config.fusion_limit]
        trace = {
            "depth": depth, "arms": [{"arm": a, "query_index": qi, "count": len(r)} for a, qi, r in arms],
            "union_count": len(ordered), "candidate_child_ids": [c["id"] for c in ordered],
            "accent_fallback": accent_trace,
            "fusion_method": self.config.fusion_method,
            "lexical_fusion_weight": self.config.lexical_fusion_weight,
            "fused": copy.deepcopy(selected)}
        probe_order = []
        if self.config.lexical_probe_limit:
            if probe_lexical is None:
                probe_trace = {"status": "skipped", "reason": "no_lexical_index",
                    "known_body_term_count": 0, "probes": [],
                    "evicted_tail_child_ids": [], "skipped_probe_child_ids": []}
                selected_order = []
            else:
                probes, hits, probe_trace = probe_candidates(request.query, probe_lexical,
                    limit=self.config.lexical_probe_limit, hits=self.config.lexical_probe_hits)
                selected, probe_trace, selected_order = augment_fused(selected, hits, probes,
                    fusion_limit=self.config.fusion_limit, seed_limit=self.config.seed_limit,
                    trace=probe_trace)
            base_ids = [c["id"] for c in ordered]
            recalled_probe_ids = [hit["child_id"] for probe in probe_trace.get("probes", [])
                                  for hit in probe.get("hits", [])]
            candidate_ids = list(dict.fromkeys(base_ids + recalled_probe_ids))
            auxiliary_count = sum(c.get("candidate_origin") == "lexical_probe" for c in selected)
            trace.update(base_union_count=len(ordered), union_count=len(candidate_ids),
                candidate_child_ids=candidate_ids,
                fused=copy.deepcopy(selected), probes=probe_trace,
                probe_seed_candidate_order=selected_order,
                probe_candidate_count=auxiliary_count,
                recalled_probe_hit_count=len(set(recalled_probe_ids)))
            probe_order = selected_order
        return selected, trace

    def _rank_and_pack(self, fused, plan, eligible, *, query, deadline, trace):
        config, np = self.config, self.np
        ranked = list(fused)
        rerank_trace = {"status": "not_configured", "count": 0}
        if self.reranker and ranked:
            if time.perf_counter() >= deadline:
                rerank_trace["status"] = "skipped_soft_deadline"
            else:
                head = ranked[:config.rerank_limit]
                try:
                    scores, stats = self.reranker.score(query, [self.children[c["id"]]["search_text"] for c in head])
                    if (not isinstance(scores, np.ndarray) or scores.shape != (len(head),)
                            or not np.isfinite(scores).all()):
                        raise ValueError("invalid reranker output")
                    rescored = [{**c, "reranker_score": float(s)} for c, s in zip(head, scores)]
                    rescored.sort(key=lambda c: (-c["reranker_score"], -c["fusion_score"], c["id"]))
                    ranked = rescored + ranked[config.rerank_limit:]
                    rerank_trace = {"status": "applied", "count": len(head), "stats": stats}
                except (ValueError, RuntimeError) as error:
                    # No score-scale mixing and no silent truncation. The whole
                    # candidate set retains RRF order on a declared fallback.
                    rerank_trace = {"status": "failed_fallback_rrf" if config.fusion_method == "rrf"
                                    else "failed_fallback_fusion", "count": len(head),
                        "reason": "pair_budget" if isinstance(error, PairBudgetError) else "invalid_output_or_runtime"}
        direct = {row["id"] for row in ranked if any(
            m["arm"] == "structure" and m["query_index"] == 0 for m in row["matches"])}
        if direct:
            ranked.sort(key=lambda row: row["id"] not in direct)
        seed_ids = [c["id"] for c in ranked[:config.seed_limit]]
        if config.seed_selection == "mmr" and ranked:
            pool_ids = [c["id"] for c in ranked[:config.rerank_limit]]
            seed_ids = mmr_ids(pool_ids, self.vectors[[self.position[cid] for cid in pool_ids]],
                               count=config.seed_limit, weight=config.mmr_weight)
            if direct:
                seed_ids = list(dict.fromkeys([ranked[0]["id"], *seed_ids]))[:config.seed_limit]
        if config.balance_facets and ranked and plan["facets"]:
            preferred = seed_ids
            seed_ids = [ranked[0]["id"]]
            pool = ranked[:config.rerank_limit]
            for facet in plan["facets"]:
                if len(seed_ids) >= config.seed_limit:
                    break
                if facet_supported(facet, [self.children[cid] for cid in seed_ids]):
                    continue
                match = next((c["id"] for c in pool if facet_supported(facet, [self.children[c["id"]]])), None)
                if match and match not in seed_ids:
                    seed_ids.append(match)
            seed_ids = list(dict.fromkeys(seed_ids + preferred + [c["id"] for c in ranked]))[:config.seed_limit]
        probe_selected, displaced = [], []
        if config.probe_seed_limit:
            pre_probe_seeds = list(seed_ids)
            ranked_ids = {row["id"] for row in ranked}
            probe_order = [cid for cid in trace.get("probe_seed_candidate_order", [])
                           if cid in eligible and cid in ranked_ids]
            protected = [pre_probe_seeds[0]] if pre_probe_seeds else []
            pre_probe_set = set(pre_probe_seeds)
            for cid in probe_order:
                if cid not in pre_probe_set and cid not in probe_selected:
                    probe_selected.append(cid)
                    if len(probe_selected) >= config.probe_seed_limit:
                        break
            seed_ids = list(dict.fromkeys(protected + probe_selected + pre_probe_seeds +
                                           [row["id"] for row in ranked]))[:config.seed_limit]
            displaced = [cid for cid in pre_probe_seeds if cid not in seed_ids]
        # Related task parts are secondary seeds; never authorize opaque held
        # content, synthesize relationships, or displace fitting primary seeds.
        related = []
        for cid in seed_ids:
            child = self.children[cid]
            if not child.get("unit_id"):
                continue
            for other in self.children.values():
                if (other["id"] in eligible and other["id"] not in seed_ids + related
                        and other.get("unit_id") == child["unit_id"]
                        and other["source_id"] == child["source_id"]):
                    if len(related) < config.linked_unit_limit:
                        related.append(other["id"])
        context, passage_trace = None, {"status": "not_configured"}
        if config.context_selection == "passages":
            gate_applied = (config.passage_gate == "always" or any(
                item.get("query_index") == 0 and item.get("applied") is True
                for item in trace.get("accent_fallback", [])))
            if gate_applied:
                pool = seed_ids + related if config.passage_pool == "seeds" else [c["id"] for c in ranked]
                fold = any(t["query_index"] == 0 and t["applied"] for t in trace.get("accent_fallback", []))
                context, passage_trace = passage_context(self.bundle, pool, query=query,
                    allowed_child_ids=eligible, counter=self.counter, max_tokens=config.context_tokens,
                    max_passages=config.seed_limit, fold_accents=fold, primary_seed_ids=seed_ids + related,
                    paragraph_window=config.passage_window, bigrams=config.passage_bigrams,
                    strategy=config.passage_strategy, reranker=self.reranker)
                passage_trace["status"] = "applied" if context is not None else "fallback_chunks"
                if config.passage_gate != "always":
                    passage_trace.update(gate=config.passage_gate, gate_applied=True)
            else:
                passage_trace = {"status": "skipped_gate", "gate": config.passage_gate,
                    "gate_applied": False}
            passage_trace["pool"] = config.passage_pool
        if context is None:
            context = expand_context(self.bundle, seed_ids + related, allowed_child_ids=eligible,
                counter=self.counter, max_tokens=config.context_tokens, mode=config.context_expansion,
                neighbor_radius=config.neighbor_radius,
                compact_seed_reservation=config.compact_seed_reservation)
        if config.extend_continuations:
            from ..packing.continuation_context import extend_continuations
            context = extend_continuations(self.bundle, context, allowed_child_ids=eligible,
                counter=self.counter, max_tokens=config.context_tokens)
        missing = [i for i, facet in enumerate(plan["facets"]) if not facet_supported(facet, context["items"])]
        trace.update(rerank=rerank_trace, passage_selection=passage_trace,
                     ranked=copy.deepcopy(ranked), primary_seeds=seed_ids,
                     related_unit_seeds=related, missing_lexical_facets=missing,
                     seed_selection=config.seed_selection,
                     mmr_weight=config.mmr_weight if config.seed_selection == "mmr" else None)
        if config.probe_seed_limit:
            trace.update(probe_selected_seed_ids=probe_selected, displaced_seed_ids=displaced)
        return ranked, context, missing

    def retrieve(self, request: SearchRequest, *, authorize):
        started = time.perf_counter()
        if self.encoder.identity != self.profile["encoder"]:
            raise ValueError("query encoder profile changed after index binding")
        if (self.reranker.identity if self.reranker else None) != self.identity["reranker"]:
            raise ValueError("reranker profile changed after index binding")
        if asdict(self.config) != self.identity["config"] or self.counter.identity != self.identity["context_counter"]:
            raise ValueError("retrieval configuration/counter changed after index binding")
        plan = make_plan(request, decompose_comparisons=self.config.decompose_comparisons,
                         accent_fallback=self.config.accent_fallback)
        allowed = _authorization(authorize, set(self.children))
        eligible = {cid for cid in allowed if self.children[cid]["retrieval_eligible"]
            and (request.scope_source_ids is None or self.children[cid]["source_id"] in request.scope_source_ids)}
        scoped_eligible_count = len(eligible)
        eligible = eligible_with_context(self.children, self.parents, eligible)
        deadline = started + self.config.soft_deadline_ms / 1000
        trace = {"identity": copy.deepcopy(self.identity), "query_sha256": _sha(request.query),
            "plan": {"version": plan["version"], "basis": plan["basis"], "query_count": len(plan["queries"]),
                "query_sha256": [_sha(q) for q in plan["queries"]], "facet_count": len(plan["facets"]),
                "has_context_hint": plan["has_context_hint"], "anchor_count": len(plan["anchors"])},
            "eligible_count": len(eligible), "context_dependency_exclusions": scoped_eligible_count - len(eligible),
            "passes": [], "soft_deadline_is_hard_timeout": False}
        scope_key = frozenset(eligible)
        lexical = self._lexical_index(scope_key, False) if (
            {"lexical", "section"} & set(self.config.arms)) else None
        # Build alternate statistics only for an entirely unaccented query and
        # only over the same authorized/scoped subset. Accented queries retain
        # the exact original lexical route; this does not guess missing accents.
        folded = self._lexical_index(scope_key, True) if (lexical is not None
            and self.config.accent_fallback and any(accent_fold(q) == q.casefold() for q in plan["queries"])) else None
        cache, ranked = {}, []
        context = {"context": "", "items": [], "budget_count": self.counter.count(""),
            "budget_unit": "tokens", "seed_child_ids": [], "skipped_budget_child_ids": []}
        for attempt in range(2 if self.config.enable_recovery else 1):
            if not eligible:
                break
            depth = min(200, self.config.recall_per_arm * (attempt + 1))
            begin = time.perf_counter()
            fused, stage = self._collect(plan, eligible, lexical, request, depth, cache, folded)
            stage["retrieval_ms"] = (time.perf_counter() - begin) * 1000
            ranked, context, missing = self._rank_and_pack(fused, plan, eligible,
                query=plan["queries"][0], deadline=deadline, trace=stage)
            trace["passes"].append(stage)
            anchor_hit = any(any(m["arm"] == "structure" for m in c["matches"]) for c in ranked)
            needs_recovery = bool(missing) or bool(plan["anchors"] and not anchor_hit) or not ranked
            if not needs_recovery or time.perf_counter() >= deadline:
                break
        # Revocation may occur during CPU inference. Return no payload/trace if
        # authorization changed, instead of leaking stale context or candidate IDs.
        if _authorization(authorize, set(self.children)) != allowed:
            raise AccessChangedError("authorization changed during retrieval; discard and retry")
        flags = ["answerability_not_verified"]
        if trace["passes"] and trace["passes"][-1]["passage_selection"]["status"] == "fallback_chunks":
            flags.append("passage_selection_fallback_chunks")
        if trace["passes"] and trace["passes"][-1]["missing_lexical_facets"]:
            flags.append("missing_lexical_facet_support")
        if context["skipped_budget_child_ids"]:
            flags.append("candidates_omitted_by_context_budget")
        if trace["passes"]:
            rerank_status = trace["passes"][-1]["rerank"]["status"]
            if rerank_status in {"failed_fallback_rrf", "failed_fallback_fusion"}:
                flags.append("reranker_fallback_rrf" if rerank_status == "failed_fallback_rrf"
                             else "reranker_fallback_fusion")
            elif rerank_status == "skipped_soft_deadline":
                flags.append("reranker_skipped_soft_deadline")
        if time.perf_counter() >= deadline:
            flags.append("soft_deadline_exceeded")
        trace["total_ms"] = (time.perf_counter() - started) * 1000
        trace["query_embeddings_computed"] = len(cache)
        return {"version": RETRIEVAL_VERSION, "status": "retrieved_unverified" if context["items"] else "no_context",
            "ranked_child_ids": [c["id"] for c in ranked], "context": context, "flags": flags,
            "trace": trace, "grants_authorization": False, "certifies_answerability": False}
