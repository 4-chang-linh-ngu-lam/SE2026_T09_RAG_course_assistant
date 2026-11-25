"""Source-position arithmetic shared by coverage audits and evaluation."""
from __future__ import annotations


def merge_ranges(ranges):
    merged = []
    for a, b in sorted(ranges):
        if a >= b:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def nonspace_prefix(text):
    values = [0]
    for char in text:
        values.append(values[-1] + int(not char.isspace()))
    return values
