"""Bounded post-generation quote alignment experiment; not wired into defaults.

For each already accepted citation, rank only that source's schema-allowed
exact quote snippets against the unchanged claim text. Lexical overlap is a
selection heuristic, not evidence of entailment or semantic citation quality.
"""
from __future__ import annotations

import copy

from ..search.passage_rank import PassageBM25
from .span_mapping import quote_spans
from .source_quotes import source_quote_enums


ALIGNMENT_VERSION = "idp-source-quote-alignment-bm25-1"


def _body_rank(query: str, snippets: list[str]) -> tuple[list[tuple[str, float]], dict[str, float]]:
    rows = [{"id": f"quote-{index:06d}", "text": quote, "index_body": quote,
             "section_path": [], "context_path": []}
            for index, quote in enumerate(snippets)]
    lexical = PassageBM25(rows, fold_accents=True, bigrams=True)
    ranked = lexical.rank(query)
    return ranked, {row_id: score for row_id, score in ranked}


def align_quotes(answer, evidence):
    """Return a copy with each existing citation quote lexically aligned.

    Claim text/order, status, citation IDs/order/count, and raw response hash
    are preserved. Only a citation quote and its exact source-span mapping may
    change. Invalid/unvalidated citations raise; they are not repaired.
    """
    if not isinstance(answer, dict) or not isinstance(answer.get("claims"), list):
        raise ValueError("invalid_answer_for_quote_alignment")
    quote_enums = source_quote_enums(evidence)
    by_id = {item["id"]: item for item in evidence}
    output = copy.deepcopy(answer)
    events = []

    for claim_index, claim in enumerate(output["claims"]):
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str) or not claim["text"].strip():
            raise ValueError("invalid_claim_for_quote_alignment")
        citations = claim.get("evidence")
        if not isinstance(citations, list):
            raise ValueError("invalid_citations_for_quote_alignment")
        for citation_index, citation in enumerate(citations):
            if not isinstance(citation, dict):
                raise ValueError("invalid_citation_for_quote_alignment")
            source_id, original_quote = citation.get("id"), citation.get("quote")
            if (not isinstance(source_id, str) or source_id not in by_id
                    or not isinstance(original_quote, str)
                    or original_quote not in quote_enums.get(source_id, ())):
                raise ValueError("invalid_source_quote_for_alignment")

            original_spans = quote_spans(by_id[source_id], original_quote)
            if (citation.get("citation_scope") != "exact_quote"
                    or citation.get("source_spans") != original_spans):
                raise ValueError("invalid_source_mapping_for_alignment")

            candidates = quote_enums[source_id]
            ranked, score_by_row = _body_rank(claim["text"], candidates)
            rank_position = {row_id: rank for rank, (row_id, _score) in enumerate(ranked, 1)}
            score_by_quote = {
                candidates[int(row_id.rsplit("-", 1)[1])]: score
                for row_id, score in score_by_row.items()
            }
            ranked_quotes = [
                (candidates[int(row_id.rsplit("-", 1)[1])], score)
                for row_id, score in ranked if score > 0
            ]
            positive_count = len(ranked_quotes)
            if ranked_quotes:
                selected_quote, selected_score = ranked_quotes[0]
                reason = "highest_positive_body_score"
            else:
                selected_quote = original_quote
                selected_score = 0.0
                reason = "no_positive_body_score_keep_original"

            changed = selected_quote != original_quote
            citation["quote"] = selected_quote
            citation["source_spans"] = quote_spans(by_id[source_id], selected_quote)
            citation["citation_scope"] = "exact_quote"
            original_row = f"quote-{quote_enums[source_id].index(original_quote):06d}"
            events.append({
                "claim_index": claim_index,
                "citation_index": citation_index,
                "source_id": source_id,
                "candidate_count": len(candidates),
                "positive_candidate_count": positive_count,
                "original_score": score_by_quote.get(original_quote, 0.0),
                "original_rank": rank_position.get(original_row),
                "selected_score": selected_score,
                "changed": changed,
                "reason": reason,
                "original_quote": original_quote,
                "selected_quote": selected_quote,
            })

    output["answer"] = "\n".join(
        claim["text"] + " " + " ".join(f"[{cite['id']}]" for cite in claim["evidence"])
        for claim in output["claims"]
    )
    output["semantic_grounding_verified"] = False
    output["quote_alignment"] = {
        "version": ALIGNMENT_VERSION,
        "method": "same-source exact candidates ranked by _PassageBM25 body only",
        "semantic_grounding_verified": False,
        "changed_citations": sum(event["changed"] for event in events),
        "citations": events,
    }
    return output
