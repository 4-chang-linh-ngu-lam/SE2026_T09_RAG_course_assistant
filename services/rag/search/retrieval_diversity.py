"""Optional MMR seed selection, not a relevance metric or an answer verifier."""
from __future__ import annotations

import math


def mmr_ids(ranked_ids, vectors, *, count, weight=.7):
    """Use reciprocal-rank relevance and nonnegative cosine redundancy.

    Caller supplies a bounded, already authorized, relevance-ranked pool and
    normalized passage vectors in exactly the same order. Stable input-order
    tie breaks; first result is preserved. No query inference or score mixing.
    """
    import numpy as np
    if (not isinstance(ranked_ids, list) or len(set(ranked_ids)) != len(ranked_ids)
            or any(not isinstance(cid, str) for cid in ranked_ids)
            or type(count) is not int or count < 1 or type(weight) not in (float, int)
            or not math.isfinite(weight) or not 0 <= weight <= 1
            or not isinstance(vectors, np.ndarray) or vectors.ndim != 2
            or vectors.shape[0] != len(ranked_ids) or not np.isfinite(vectors).all()
            or (len(ranked_ids) and not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=.001))):
        raise ValueError("MMR requires unique authorized IDs and aligned unit vectors")
    if not ranked_ids:
        return []
    similarity = np.maximum(vectors @ vectors.T, 0)
    selected = [0]
    remaining = set(range(1, len(ranked_ids)))
    while remaining and len(selected) < count:
        best = max(remaining, key=lambda i: (
            weight / (i + 1) - (1 - weight) * float(similarity[i, selected].max()), -i))
        selected.append(best)
        remaining.remove(best)
    return [ranked_ids[i] for i in selected]
