"""Score-transparent fusion of already authorized, bounded retrieval arms."""
from __future__ import annotations

import math


def _lexical_weight(arm, weight):
    return weight if (arm == "lexical" or arm == "lexical_accent_fallback"
                      or arm.startswith("focus_lexical")) else 1.0


def fuse_rankings(arms, *, method, rrf_constant, lexical_weight=1.0):
    """Keep candidate union and raw scores, with an explicit selected score.

    Relative scores are min/max normalized independently inside each returned
    arm. A singleton contributes one; a flat multi-item arm contributes zero
    because it supplies no ordering evidence. Missing candidates contribute zero.
    This is a ranking heuristic, never a calibrated relevance probability.
    """
    if method not in {"rrf", "relative_score"}:
        raise ValueError("unsupported fusion method")
    if (type(lexical_weight) not in (int, float) or not math.isfinite(lexical_weight)
            or not 0 < lexical_weight <= 10):
        raise ValueError("lexical_weight must be finite numeric in (0, 10]")
    fused = {}
    for arm, qi, ranking in arms:
        if len({cid for cid, _ in ranking}) != len(ranking):
            raise ValueError("duplicate candidate inside retrieval arm")
        if any(not math.isfinite(score) for _, score in ranking):
            raise ValueError("non-finite retrieval score")
        low = min((score for _, score in ranking), default=0.)
        high = max((score for _, score in ranking), default=0.)
        for rank, (cid, score) in enumerate(ranking, 1):
            rrf = 1 / (rrf_constant + rank)
            relative = ((score - low) / (high - low) if high > low
                        else float(len(ranking) == 1))
            weight = _lexical_weight(arm, lexical_weight)
            contribution = (rrf if method == "rrf" else relative) * weight
            item = fused.setdefault(cid, {"id": cid, "rrf_score": 0.,
                                         "fusion_score": 0., "matches": []})
            item["rrf_score"] += rrf
            item["fusion_score"] += contribution
            item["matches"].append({"arm": arm, "query_index": qi, "rank": rank,
                                    "score": score, "fusion_weight": weight,
                                    "fusion_contribution": contribution})
    return sorted(fused.values(), key=lambda c: (-c["fusion_score"], c["id"]))
