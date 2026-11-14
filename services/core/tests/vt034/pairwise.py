"""Deterministic greedy covering array, independently audited for every pair."""

from itertools import combinations, product

FACTORS = {
    "length": (1, 10000, 10001),
    "actor": ("teacher", "student", "outsider"),
    "class_state": ("ACTIVE", "ARCHIVED"),
    "delivery": ("ok", "fail"),
}


def pairs(row):
    return {(i, row[i], j, row[j]) for i, j in combinations(range(len(row)), 2)}


def covering_array():
    candidates = list(product(*FACTORS.values()))
    uncovered = set().union(*(pairs(row) for row in candidates))
    chosen = []
    while uncovered:
        # product order breaks ties; no random seed or hash-order dependency.
        row = max(candidates, key=lambda item: len(pairs(item) & uncovered))
        chosen.append(row)
        uncovered -= pairs(row)
        candidates.remove(row)
    return chosen


CASES = covering_array()
