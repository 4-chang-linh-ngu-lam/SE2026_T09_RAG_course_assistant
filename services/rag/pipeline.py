"""Composition of the extracted RAG stages for offline/local text evaluation.

This module owns orchestration only. It does not create a service endpoint,
perform authorization itself, or replace the Core/Document permission checks.
"""
from __future__ import annotations

import copy
import time
from dataclasses import replace

from .generation.rag_answer import answer_version, answer_schema, evidence_items, messages_for, validate_answer
from .generation.extractive_reader import (
    EXTRACTIVE_ANSWER_VERSION,
    EXTRACTIVE_FALLBACK_ANSWER_VERSION,
    EXTRACTIVE_FALLBACK_ERRORS,
    extractive_answer_schema,
    extractive_messages_for,
    validate_extractive_answer,
)
from .generation.vi_mrc_reader import (
    VI_MRC_ANSWER_VERSION,
    answer_from_result,
)
from .retrieval.corpus import load_retriever
from .retrieval.retrieval import AccessChangedError, RetrievalConfig, authorize as validate_authorization
from .retrieval.mrc_recovery import LexicalDateRecovery, relative_event_candidate
from .retrieval.multihop import MultiHopDecision
from .search.retrieval_plan import SearchRequest
from .citations.source_quotes import SourceBoundSchemaError
from .citations.quote_alignment import ALIGNMENT_VERSION, align_quotes
from .packing.evidence_budget import fit_evidence

RAG_VERSION = "idp-text-rag-3"
EDUCATION_BASELINE_VERSION = "idp-education-baseline-1"
VIETNAMESE_EDUCATION_VERSION = "idp-vietnamese-education-1"
FOCUSED_RAG_VERSION = "idp-text-rag-focused-quotes-1"
QUESTION_FOCUSED_RAG_VERSION = "idp-text-rag-question-focused-1"
DIRECT_ANSWER_RAG_VERSION = "idp-text-rag-direct-answer-1"
EXTRACTIVE_RAG_VERSION = "idp-text-rag-extractive-1"
EXTRACTIVE_FALLBACK_RAG_VERSION = "idp-text-rag-extractive-fallback-1"
SOURCE_QUOTES_RAG_VERSION = "idp-text-rag-source-quotes-1"
ALIGNED_SOURCE_QUOTES_RAG_VERSION = "idp-text-rag-source-quotes-aligned-1"
VI_MRC_RAG_VERSION = "idp-vi-mrc-large-rag-1"


def _rag_version(policy, citation_alignment):
    if citation_alignment != "none":
        return ALIGNED_SOURCE_QUOTES_RAG_VERSION
    return {"baseline": RAG_VERSION, "question_focused": QUESTION_FOCUSED_RAG_VERSION,
            "direct_answer": DIRECT_ANSWER_RAG_VERSION, "extractive": EXTRACTIVE_RAG_VERSION,
            "extractive_fallback": EXTRACTIVE_FALLBACK_RAG_VERSION,
            "focused_quotes": FOCUSED_RAG_VERSION, "source_quotes": SOURCE_QUOTES_RAG_VERSION,
            "vi_mrc": VI_MRC_RAG_VERSION}[policy]


def _answer_version(policy):
    if policy == "extractive_fallback":
        return EXTRACTIVE_FALLBACK_ANSWER_VERSION
    if policy == "vi_mrc":
        return VI_MRC_ANSWER_VERSION
    return EXTRACTIVE_ANSWER_VERSION if policy == "extractive" else answer_version(policy)


def _messages_for_policy(query, evidence, context_hint, policy):
    if policy in {"extractive", "extractive_fallback"}:
        return extractive_messages_for(query, evidence, context_hint)
    # The reader itself does not consume chat messages, but the packer still
    # needs a deterministic prompt-shaped representation for token budgeting.
    if policy == "vi_mrc":
        return messages_for(query, evidence, context_hint, policy="direct_answer")
    return messages_for(query, evidence, context_hint, policy=policy)


def _answer_schema_for_policy(evidence, policy):
    return (extractive_answer_schema(evidence) if policy in {"extractive", "extractive_fallback"}
            else answer_schema(evidence, policy="direct_answer") if policy == "vi_mrc"
            else answer_schema(evidence, policy=policy))


def _validate_answer_for_policy(raw, evidence, policy):
    if policy in {"extractive", "extractive_fallback"}:
        return validate_extractive_answer(raw, evidence)[0]
    if policy == "vi_mrc":
        raise ValueError("vi_mrc_answer_is_reader_owned")
    return validate_answer(raw, evidence, policy=policy)


def _validate_citation_alignment(answer_policy, citation_alignment):
    if citation_alignment not in ("none", "bm25"):
        raise ValueError("invalid_citation_alignment")
    if citation_alignment == "bm25" and answer_policy != "source_quotes":
        raise ValueError("quote_alignment_requires_source_quotes")


def _merge_multihop_retrieval(results, *, counter, decision):
    """Merge child/context records returned by bounded subquery retrievals."""
    if not results:
        raise ValueError("multi-hop retrieval requires at least one result")
    if len(results) == 1:
        return results[0]
    merged_items, seen_items = [], set()
    ranked_ids, seen_ids = [], set()
    max_rank = max(len(result.get("ranked_child_ids", ())) for result in results)
    for rank in range(max_rank):
        for result in results:
            ranked = result.get("ranked_child_ids", ())
            if rank < len(ranked) and ranked[rank] not in seen_ids:
                seen_ids.add(ranked[rank])
                ranked_ids.append(ranked[rank])
    for result in results:
        for item in result.get("context", {}).get("items", ()):
            item_id = item.get("id")
            if item_id not in seen_items:
                seen_items.add(item_id)
                merged_items.append(copy.deepcopy(item))
    context_text = "\n\n".join(f"[{item['id']}]\n{item['text']}" for item in merged_items)
    first = copy.deepcopy(results[0])
    first["status"] = "retrieved_unverified" if merged_items else "no_context"
    first["ranked_child_ids"] = ranked_ids
    first["context"] = {
        **first.get("context", {}),
        "context": context_text,
        "items": merged_items,
        "seed_child_ids": list(dict.fromkeys(
            seed for result in results
            for seed in result.get("context", {}).get("seed_child_ids", ())
        )),
        "budget_count": counter.count(context_text),
        "skipped_budget_child_ids": list(dict.fromkeys(
            skipped for result in results
            for skipped in result.get("context", {}).get("skipped_budget_child_ids", ())
        )),
    }
    traces = [result.get("trace", {}) for result in results]
    flags = list(dict.fromkeys(flag for result in results for flag in result.get("flags", ())))
    first["flags"] = flags
    first["trace"] = {
        **first.get("trace", {}),
        "total_ms": sum(trace.get("total_ms", 0.0) for trace in traces),
        "query_embeddings_computed": sum(trace.get("query_embeddings_computed", 0) for trace in traces),
        "passes": [stage for trace in traces for stage in trace.get("passes", ())],
        "multi_hop": {"status": "applied", "mode": decision.mode,
                      "queries": list(decision.queries), "hops": len(results)},
    }
    return first


def baseline_config():
    return RetrievalConfig(arms=("dense", "lexical"), decompose_comparisons=False,
        balance_facets=False, enable_recovery=False, neighbor_radius=0, linked_unit_limit=0)


def education_baseline_config():
    """Router-free hybrid baseline; metadata expansion never evicts reserved hits."""
    return replace(baseline_config(), context_expansion="parent_then_neighbors", neighbor_radius=1)


def vietnamese_education_config():
    """Explicit corpus-language policy, retaining baseline RRF and all source text.

    Does not classify a question's subject or restore guessed accents. Enable
    for Vietnamese educational corpora; folding remains ambiguous at collisions.
    """
    return replace(education_baseline_config(), accent_fallback=True)


def vi_mrc_config():
    """Retrieval profile used by the adapted Vietnamese MRC benchmark path."""
    return vietnamese_education_config()


class RagPipeline:
    def __init__(self, retriever, *, generator, answer_policy="baseline", citation_alignment="none",
                 verifier=None, on_verifier_error="keep", mrc_reader=None, mrc_recovery=None,
                 multihop_planner=None):
        if retriever.counter.identity != generator.counter.identity:
            raise ValueError("retrieval context must use the generator tokenizer")
        _answer_version(answer_policy)  # validates the selected offline answer contract
        _validate_citation_alignment(answer_policy, citation_alignment)
        if answer_policy == "vi_mrc" and not callable(getattr(mrc_reader, "answer", None)):
            raise ValueError("vi_mrc_reader_required")
        if mrc_reader is not None and not isinstance(getattr(mrc_reader, "identity", None), dict):
            raise ValueError("invalid_vi_mrc_reader")
        if mrc_reader is not None and answer_policy != "vi_mrc":
            raise ValueError("vi_mrc_reader_requires_vi_mrc_policy")
        if answer_policy == "vi_mrc" and mrc_recovery is None and hasattr(retriever, "sources"):
            mrc_recovery = LexicalDateRecovery(retriever.sources)
        if mrc_recovery is False:
            mrc_recovery = None
        if mrc_recovery is not None and (
            not callable(getattr(mrc_recovery, "rank_sources", None))
            or not callable(getattr(mrc_recovery, "evidence", None))
            or not isinstance(getattr(mrc_recovery, "identity", None), dict)
        ):
            raise ValueError("invalid_vi_mrc_recovery")
        if mrc_recovery is not None and answer_policy != "vi_mrc":
            raise ValueError("vi_mrc_recovery_requires_vi_mrc_policy")
        if verifier is not None and not callable(getattr(verifier, "verify", None)):
            raise ValueError("invalid_claim_verifier")
        if on_verifier_error not in ("keep", "refuse"):
            raise ValueError("invalid_on_verifier_error")
        if multihop_planner is not None and not callable(getattr(multihop_planner, "plan", None)):
            raise ValueError("invalid_multihop_planner")
        if multihop_planner is not None and not isinstance(getattr(multihop_planner, "identity", None), dict):
            raise ValueError("invalid_multihop_planner_identity")
        self.retriever, self.generator = retriever, generator
        self.multihop_planner = multihop_planner
        self.mrc_reader, self.mrc_recovery = mrc_reader, mrc_recovery
        self._verifier = verifier
        self._on_verifier_error = on_verifier_error
        self._answer_policy_binding = answer_policy
        self._citation_alignment_binding = citation_alignment
        version = _rag_version(answer_policy, citation_alignment)
        self.identity = {"version": version, "answer_version": _answer_version(answer_policy),
                         "answer_policy": answer_policy,
                         "citation_alignment": citation_alignment,
                         "quote_alignment_version": ALIGNMENT_VERSION if citation_alignment == "bm25" else None,
                         "verifier": copy.deepcopy(getattr(verifier, "identity", None)) if verifier is not None else None,
                         "on_verifier_error": on_verifier_error if verifier is not None else None,
                         "retrieval": copy.deepcopy(retriever.identity),
                         "generator": copy.deepcopy(generator.identity),
                         "multihop_planner": copy.deepcopy(getattr(multihop_planner, "identity", None)),
                         "mrc_reader": copy.deepcopy(getattr(mrc_reader, "identity", None)),
                         "mrc_recovery": copy.deepcopy(getattr(mrc_recovery, "identity", None))}

    @property
    def answer_policy(self):
        return self._answer_policy_binding

    @classmethod
    def from_corpus(cls, directory, *, encoder, generator, config=None, reranker=None,
                    answer_policy="baseline", citation_alignment="none", verifier=None,
                    on_verifier_error="keep", mrc_reader=None, mrc_recovery=None,
                    multihop_planner=None):
        _answer_version(answer_policy)
        _validate_citation_alignment(answer_policy, citation_alignment)
        retriever, _, _ = load_retriever(directory, encoder=encoder, context_counter=generator.counter,
            config=baseline_config() if config is None else config, reranker=reranker)
        return cls(retriever, generator=generator, answer_policy=answer_policy,
                   citation_alignment=citation_alignment, verifier=verifier,
                   on_verifier_error=on_verifier_error, mrc_reader=mrc_reader,
                   mrc_recovery=mrc_recovery, multihop_planner=multihop_planner)

    def answer(self, request: SearchRequest, *, authorize):
        started = time.perf_counter()
        if (self.identity.get("answer_policy") != self._answer_policy_binding
                or self.identity.get("answer_version") != _answer_version(self._answer_policy_binding)
                or self.identity.get("citation_alignment") != self._citation_alignment_binding
                or self.identity.get("quote_alignment_version") != (
                    ALIGNMENT_VERSION if self._citation_alignment_binding == "bm25" else None)
                or self.identity.get("version") != _rag_version(
                    self._answer_policy_binding, self._citation_alignment_binding)
                or self.generator.identity != self.identity["generator"]
                or getattr(self.multihop_planner, "identity", None) != self.identity["multihop_planner"]
                or getattr(self.mrc_reader, "identity", None) != self.identity["mrc_reader"]
                or getattr(self.mrc_recovery, "identity", None) != self.identity["mrc_recovery"]
                or self.retriever.identity != self.identity["retrieval"]
                or self.retriever.counter.identity != self.generator.counter.identity):
            raise ValueError("RAG component identity changed after binding")
        known = set(self.retriever.children)
        initial = validate_authorization(authorize, known)

        def current():
            value = validate_authorization(authorize, known)
            if value != initial:
                raise AccessChangedError("authorization changed during RAG; discard and retry")
            return value

        planner_trace = None
        decision = MultiHopDecision()
        if self.multihop_planner is not None:
            try:
                planned = self.multihop_planner.plan(request)
                if not isinstance(planned, MultiHopDecision):
                    raise ValueError("multi-hop planner must return MultiHopDecision")
                decision = planned
                planner_trace = {"status": "planned", "mode": decision.mode,
                                 "queries": list(decision.queries), "hops": None}
            except (ValueError, RuntimeError, OSError) as error:
                decision = MultiHopDecision()
                planner_trace = {"status": "planner_failed",
                                 "error": error.safe() if callable(getattr(error, "safe", None))
                                 else type(error).__name__, "mode": "direct", "queries": [], "hops": 1}
            current()
        if decision.mode == "rewrite" and decision.queries:
            retrieval_requests = [replace(
                request, query=decision.queries[0], facets=(), context_hint=""
            )]
        else:
            retrieval_requests = [request]
            for query in decision.queries:
                if query.strip() == request.query.strip():
                    continue
                retrieval_requests.append(replace(request, query=query, facets=(), context_hint=""))
        if planner_trace is not None:
            planner_trace["hops"] = len(retrieval_requests)
        retrieved_results = [self.retriever.retrieve(subrequest, authorize=current)
                             for subrequest in retrieval_requests]
        retrieved = _merge_multihop_retrieval(
            retrieved_results, counter=self.generator.counter, decision=decision,
        )
        if planner_trace is not None:
            merged_trace = {**retrieved["trace"].get("multi_hop", {}), **planner_trace}
            merged_trace["hops"] = len(retrieved_results)
            retrieved["trace"]["multi_hop"] = merged_trace
            planner_trace = merged_trace
        evidence = evidence_items(retrieved["context"])
        fitted_result = fit_evidence(
            evidence,
            build_messages=lambda records: _messages_for_policy(
                request.query, records, request.context_hint, self._answer_policy_binding
            ),
            count_messages=self.generator.count_messages,
            context_tokens=self.generator.context_tokens,
            max_new_tokens=self.generator.max_new_tokens,
        )
        fitted = fitted_result["evidence"]
        fitted_messages = fitted_result["messages"]
        prompt_tokens = fitted_result["prompt_tokens"]
        dropped = fitted_result["dropped_evidence_ids"]
        # Dropping whole records preserves source positions; never crop evidence
        # text or rewrite it to fit a generator's tokenizer/template.
        current()
        raw, answer = None, {"status": "insufficient_evidence", "claims": [], "answer": "",
                            "citation_location_verified": False, "semantic_grounding_verified": False}
        generation_seconds, failure, reader_trace = 0., None, None
        fallback_error, primary_raw = None, None
        verification, verification_seconds = None, 0.
        if evidence and not fitted:
            failure, answer["status"] = "prompt_budget_exhausted", "generation_failed"
        if fitted:
            begin = time.perf_counter()
            try:
                if self._answer_policy_binding == "vi_mrc":
                    reader_evidence = fitted[: getattr(self.mrc_reader, "top_passages", 3)]
                    reader_result = self.mrc_reader.answer(request.query, reader_evidence)
                    reader_trace = {"primary": reader_result}
                    answer = answer_from_result(reader_result, reader_evidence)
                    if answer["status"] == "insufficient_evidence" and self.mrc_recovery is not None:
                        eligible_source_ids = {
                            self.retriever.children[cid]["source_id"]
                            for cid in initial
                            if self.retriever.children[cid].get("retrieval_eligible", True)
                            and (request.scope_source_ids is None
                                 or self.retriever.children[cid]["source_id"] in request.scope_source_ids)
                        }
                        original_source_ids = [
                            item.get("record", {}).get("source_id") or item.get("source_id")
                            for item in fitted
                        ]
                        recovered_ids = self.mrc_recovery.rank_sources(
                            request.query,
                            original_source_ids=original_source_ids,
                            eligible_source_ids=sorted(eligible_source_ids),
                        )
                        recovered_evidence = self.mrc_recovery.evidence(recovered_ids)
                        recovery_result = None
                        if recovered_evidence:
                            current()
                            recovery_result = self.mrc_reader.answer(request.query, recovered_evidence)
                            current()
                            candidate = recovery_result.get("candidate")
                            accepted = isinstance(candidate, dict) and candidate.get("null_margin", float("-inf")) > getattr(
                                self.mrc_recovery, "margin_floor", 0.0
                            )
                            if not accepted:
                                temporal = relative_event_candidate(
                                    request.query, recovery_result, recovered_evidence
                                )
                                if temporal is not None:
                                    recovery_result = {
                                        **recovery_result,
                                        "status": "answered",
                                        "candidate": temporal,
                                    }
                                    accepted = True
                            if accepted:
                                answer = answer_from_result(recovery_result, recovered_evidence)
                                fallback_error = "mrc_lexical_date_recovery"
                        reader_trace["recovery"] = {
                            "source_ids": recovered_ids,
                            "result": recovery_result,
                        }
                else:
                    raw = self.generator.generate(fitted_messages, _answer_schema_for_policy(
                        fitted, self._answer_policy_binding))
                    try:
                        answer = _validate_answer_for_policy(raw, fitted, self._answer_policy_binding)
                    except ValueError as error:
                        if self._answer_policy_binding != "extractive_fallback" \
                                or str(error) not in EXTRACTIVE_FALLBACK_ERRORS:
                            raise
                        fallback_error, primary_raw = str(error), raw
                        raw = self.generator.generate(
                            messages_for(request.query, fitted, request.context_hint, policy="direct_answer"),
                            answer_schema(fitted, policy="direct_answer"))
                        answer = validate_answer(raw, fitted, policy="direct_answer")
                    if self._citation_alignment_binding == "bm25":
                        answer = align_quotes(answer, fitted)
            except (ValueError, RuntimeError, OSError) as error:
                if self._answer_policy_binding == "vi_mrc":
                    failure = "mrc_reader_failed"
                    answer = {**answer, "status": "generation_failed"}
                else:
                    failure = str(error) if (isinstance(error, SourceBoundSchemaError)
                        or (type(error) is ValueError and str(error) in {
                        "generation_not_complete", "invalid_generation_text", "invalid_answer_json",
                        "invalid_answer_schema", "answer_status_claims_conflict", "invalid_claim_schema",
                        "invalid_citation_schema", "citation_quote_not_in_evidence", "citation_quote_lacks_source_mapping",
                        "focused_quote_required", "source_quote_required", "citation_quote_not_in_source_enum"
                    })) else "generator_or_output_validation_failed"
                    if self._citation_alignment_binding == "bm25":
                        answer = {"status": "generation_failed", "claims": [], "answer": "",
                                  "citation_location_verified": False,
                                  "semantic_grounding_verified": False}
                    else:
                        answer = {**answer, "status": "generation_failed"}
            generation_seconds = time.perf_counter() - begin
        if self._verifier is not None and answer.get("status") == "answered" and answer.get("claims"):
            # Optional second-pass claim review: the verifier may only filter
            # original claims, never rewrite them. A completed review that keeps
            # no claim downgrades the answer to insufficient_evidence instead of
            # letting an unsupported answer through.
            begin = time.perf_counter()
            try:
                cited = []
                for claim in answer["claims"]:
                    for cite in claim["evidence"]:
                        if cite["id"] not in cited:
                            cited.append(cite["id"])
                cited_set = set(cited)
                subset = [item for item in fitted if item["id"] in cited_set][:12]
                # One retry: the reviewer occasionally paraphrases its required
                # exact quote, which fails validation deterministically at temp 0.
                for attempt in range(2):
                    verification = self._verifier.verify(request.query, copy.deepcopy(answer),
                                                         copy.deepcopy(subset))
                    if verification.get("state") != "verifier_error" or attempt == 1:
                        break
            except Exception:
                verification = {"state": "verifier_error", "error_code": "verifier_runtime_failed"}
            verification_seconds = time.perf_counter() - begin
            current()  # The added model call must not outlive a mid-review revocation.
            if verification.get("state") == "verifier_error" and self._on_verifier_error == "refuse":
                # Fail closed: an answer whose claims could not be checked is
                # treated as unsupported rather than passed through unverified.
                answer = {**answer, "status": "insufficient_evidence", "claims": [], "answer": "",
                          "semantic_grounding_verified": False}
            elif verification.get("state") == "completed":
                kept = verification.get("claims", [])
                originals = answer["claims"]
                cursor, valid_subset = 0, isinstance(kept, list)
                for claim in kept if valid_subset else []:
                    while cursor < len(originals) and originals[cursor] != claim:
                        cursor += 1
                    if cursor == len(originals):
                        valid_subset = False
                        break
                    cursor += 1
                if valid_subset and verification.get("all_filtered") is (not bool(kept)):
                    answer = {**answer, "claims": copy.deepcopy(kept),
                              "status": "answered" if kept else "insufficient_evidence",
                              "answer": "\n".join(c["text"] + " " + " ".join(
                                  f"[{e['id']}]" for e in c["evidence"]) for c in kept),
                              "semantic_grounding_verified": True}
        current()  # No answer, citation or source trace survives mid-generation revocation.
        return {**answer, "version": self.identity["version"], "answer_version": self.identity["answer_version"], "retrieval": retrieved,
            "evidence": fitted, "identity": copy.deepcopy(self.identity),
            "trace": {"total_seconds": time.perf_counter() - started,
                "generation_seconds": generation_seconds, "prompt_tokens": prompt_tokens,
                "generation_failure": failure, "dropped_evidence_ids": dropped,
                "claim_verification": verification,
                "claim_verification_seconds": verification_seconds,
                "finish_reason": raw.get("finish_reason") if isinstance(raw, dict) else None,
                "raw_generation_text": raw.get("text") if isinstance(raw, dict) else None,
                "usage": raw.get("usage", {}) if isinstance(raw, dict) else {},
                "answer_policy": self._answer_policy_binding,
                "mrc_reader": reader_trace,
                "answer_fallback": fallback_error,
                "primary_raw_generation_text": primary_raw.get("text") if isinstance(primary_raw, dict) else None,
                "primary_usage": primary_raw.get("usage", {}) if isinstance(primary_raw, dict) else {},
                "citation_alignment": self._citation_alignment_binding,
                "quote_alignment_version": ALIGNMENT_VERSION if self._citation_alignment_binding == "bm25" else None,
                "server_timings": raw.get("server_timings", {}) if isinstance(raw, dict) else {},
                **({"multi_hop": planner_trace} if planner_trace is not None else {})},
            "grants_authorization": False, "certifies_answer_correctness": False}
