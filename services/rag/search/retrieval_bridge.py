"""Bounded lexical bridge hop for questions whose evidence spans two units.

"Telos was an album by a band who formed in what city?" names the album, but
the city is in a unit about the band, whose name ("Forevermore") appears only
in the first-hop unit. The bridge hop reissues the query with a few rare terms
taken verbatim from the top first-hop unit and fuses that ranking with the
original by reciprocal rank. It reuses the caller's already authorized
FieldedBM25 instance, so statistics and candidates never leave that subset.

This is pseudo-relevance feedback, not entity linking or reasoning: the added
terms are unverified, and the fused order is a heuristic, never a relevance
probability or an answerability signal.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math

from .retrieval_plan import _STOP

BRIDGE_VERSION = "lexical-bridge-1"
BRIDGE_RRF_CONSTANT = 60


def bridge_terms(lexical, seed_text, query, *, limit):
    """Up to ``limit`` rare body terms of ``seed_text`` absent from the query.

    Only terms that also occur in another indexed unit qualify. Order: IDF over the authorized body field times log-damped seed frequency,
    then the term itself, so the choice is deterministic.
    """
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError("bridge term limit must be an integer in 1..16")
    _, _, postings = lexical.fields["body"]
    total = len(lexical.children)
    asked = set(lexical.query_terms(query))
    stop = {term for word in _STOP for term in lexical.query_terms(word)}
    # A term found only in the seed itself cannot link to another unit.
    counts = Counter(
        term for term in lexical.query_terms(seed_text)
        if term not in asked and term not in stop and len(term) > 2 and not term.isdigit()
        and len(postings.get(term, ())) >= 2
    )

    def weight(term):
        df = len(postings.get(term, ()))
        return math.log(1 + (total - df + .5) / (df + .5)) * (1 + math.log(counts[term]))

    return sorted(counts, key=lambda term: (-weight(term), term))[:limit]


def bridge_rankings(lexical, query, ranked_ids, text_of, *, seeds=1, limit=5):
    """One ``[(id, score), ...]`` bridge ranking per top first-hop seed.

    ``ranked_ids`` is the first-hop order from the same ``lexical`` index;
    ``text_of`` maps an id to the text that index scored. Seeds whose text
    yields no new rare term produce no ranking.
    """
    if type(seeds) is not int or not 0 <= seeds <= 4:
        raise ValueError("bridge seeds must be an integer in 0..4")
    rankings, trace = [], {"version": BRIDGE_VERSION, "seeds": [], "applied": False}
    for identity in list(ranked_ids)[:seeds]:
        extra = bridge_terms(lexical, text_of(identity), query, limit=limit)
        trace["seeds"].append({"id": identity, "term_count": len(extra)})
        if extra:
            rankings.append(lexical.rank(query + "\n" + " ".join(extra)))
    trace["applied"] = bool(rankings)
    return rankings, trace


def bridge_rank(lexical, query, ranked, text_of, *, seeds=1, limit=5):
    """Fuse the first-hop ranking with one bridge ranking per seed unit.

    ``ranked`` is the caller's first-hop ``[(id, score), ...]`` from the same
    ``lexical`` index. Returns ``(fused, trace)`` where ``fused`` is
    ``[(id, rrf_score), ...]`` holding exactly the first-hop ids plus ids the
    bridge queries matched lexically.
    """
    first = [identity for identity, _ in ranked]
    extra, trace = bridge_rankings(lexical, query, first, text_of, seeds=seeds, limit=limit)
    if not extra:
        return list(ranked), trace
    lists = [first] + [[identity for identity, _ in ranking] for ranking in extra]
    scores = defaultdict(float)
    for ranking in lists:
        for rank, identity in enumerate(ranking, 1):
            scores[identity] += 1 / (BRIDGE_RRF_CONSTANT + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0])), trace
