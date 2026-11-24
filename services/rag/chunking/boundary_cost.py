"""Experimental CPU boundary optimizer; no embedding or language model.

Optimizes a declared heuristic objective over a bounded sentence/paragraph DAG.
The objective is not a semantic-quality score. Exact full-input token counts
enforce the hard cap; min/target are soft preferences, including a soft tail.
"""
from __future__ import annotations

import math
import re
import unicodedata

from .token_budget import contextualize

BOUNDARY_COST_VERSION = "idp-boundary-cost-1"
_DEPENDENT = re.compile(
    r"^(?:điều (?:đó|này|ấy)|như vậy|do đó|vì vậy|bởi vậy|từ đó|nó|họ|"
    r"ông ấy|bà ấy|người ấy|this (?:shows|means|suggests)|that (?:shows|means)|"
    r"therefore|thus|hence|he|she|it|they)\b", re.I)
_ABBREVIATION = re.compile(r"(?:\b(?:mr|mrs|ms|dr|prof|sr|jr|ts|ths|pgs)|\bv\.v|\be\.g|\bi\.e)\.$", re.I)
_SENTENCE_END = re.compile(r"[.!?。！？](?:[\"'’”»\)\]]*)\s+")
_PARAGRAPH_END = re.compile(r"\n[ \t>]*\n+")
# A line-initial enumerator or task label ("1.", "1.2.", "A.", "iv.", "Câu 2.")
# ends with a period but is not a sentence. Cutting there emits a chunk that
# holds only the marker and detaches it from its content.
_ENUMERATOR = re.compile(
    r"[ \t>]*(?:(?:bài tập|bài|câu hỏi|câu|ví dụ|hoạt động|luyện tập|vận dụng|hình|bảng|"
    r"exercise|problem|question|example|activity|figure|table)\s+)?"
    r"(?:\d{1,4}(?:\.\d{1,4})*|[A-Za-z]|[ivxlcdmIVXLCDM]{1,6})\.", re.I)


def normalize_policy(values, limit):
    policy = {"version": BOUNDARY_COST_VERSION, "min_budget": int(limit * .5),
        "target_budget": max(1, int(limit * .8)), "max_candidate_units": 64,
        "max_transition_checks": 20000, "size_weight": 1., "short_weight": 1.,
        "cut_weight": 1., "paragraph_reward": .4, "dependent_weight": 2.,
        "unfinished_weight": 2., "lexical_weight": 0., "window_units": 2}
    if values is not None:
        if not isinstance(values, dict) or set(values) - set(policy):
            raise ValueError("unknown boundary policy field")
        policy.update(values)
    if policy["version"] != BOUNDARY_COST_VERSION:
        raise ValueError("unsupported boundary cost version")
    for key in ("min_budget", "target_budget", "max_candidate_units", "max_transition_checks", "window_units"):
        if type(policy[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if not 0 <= policy["min_budget"] <= policy["target_budget"] <= limit or policy["target_budget"] < 1:
        raise ValueError("require 0 <= min_budget <= target_budget <= max_tokens")
    if not 1 <= policy["max_candidate_units"] <= 256 or not 1 <= policy["window_units"] <= 8:
        raise ValueError("candidate/window size out of range")
    if not 1 <= policy["max_transition_checks"] <= 1000000:
        raise ValueError("transition check limit out of range")
    for key in ("size_weight", "short_weight", "cut_weight", "paragraph_reward",
                "dependent_weight", "unfinished_weight", "lexical_weight"):
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    if policy["paragraph_reward"] > policy["cut_weight"]:
        raise ValueError("paragraph reward cannot make additional cuts profitable by themselves")
    return policy


def merge_protected(ranges):
    result = []
    for a, b in sorted(ranges):
        if result and a < result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return result


def quoted_spans(text):
    # Apostrophes are not quote delimiters. Unclosed quotations remain evidence
    # for the boundary penalty, not a guessed opaque span to end-of-document.
    return [(m.start(), m.end()) for m in re.finditer(r'“[^”]*”|(?<!\w)"[^"\n]+"(?!\w)', text)]


def candidate_points(text, protected=()):
    points = {0, len(text)}
    for match in _PARAGRAPH_END.finditer(text):
        points.add(match.end())
    segment_start = 0
    for match in _SENTENCE_END.finditer(text):
        head_start = max(segment_start, text.rfind("\n", 0, match.start()) + 1)
        if _ENUMERATOR.fullmatch(unicodedata.normalize("NFC", text[head_start:match.start() + 1])):
            continue
        preceding = text[max(0, match.start() - 16):match.start() + 1]
        if not _ABBREVIATION.search(unicodedata.normalize("NFC", preceding)):
            points.add(match.end())
            segment_start = match.end()
    return sorted(p for p in points if p in {0, len(text)} or (
        not unicodedata.combining(text[p]) and text[p] not in {"\u200d", "\ufe0e", "\ufe0f"}
        and text[p - 1] != "\u200d" and not any(a < p < b for a, b in protected)))


def _starts_dependent(value):
    value = re.sub(r'^[\s>\"“”‘’]+', "", unicodedata.normalize("NFC", value))
    return bool(_DEPENDENT.match(value))


def starts_dependent(value):
    """Public lexical continuation cue used by context packing."""
    return _starts_dependent(value)


def sentence_end_matches(text):
    """Yield sentence boundary matches using the chunking policy."""
    return _SENTENCE_END.finditer(text)


def abbreviation_match(text):
    """Return whether the supplied suffix is a known abbreviation."""
    return _ABBREVIATION.search(text)


def _words(value):
    return set(re.findall(r"\w+", unicodedata.normalize("NFC", value).casefold()))


def _boundary_cost(text, atoms, index, policy, open_scope=False):
    if index == len(atoms):
        return 0.
    pos = atoms[index][0]
    left, right = text[max(0, pos - 256):pos], text[pos:pos + 256]
    paragraph = bool(re.search(r"\n[ \t>]*\n[ \t\r\n>]*$", left))
    cost = (policy["cut_weight"] - policy["paragraph_reward"] * paragraph
            + policy["dependent_weight"] * _starts_dependent(right)
            + policy["unfinished_weight"] * (left.rstrip().endswith((":", "：")) or open_scope))
    if policy["lexical_weight"]:
        window = policy["window_units"]
        a = atoms[max(0, index - window)][0]
        b = atoms[min(len(atoms), index + window) - 1][1]
        before, after = _words(text[a:pos]), _words(text[pos:b])
        union = before | after
        similarity = len(before & after) / len(union) if union else 0.
        cost += policy["lexical_weight"] * similarity
    return cost


def _size_cost(count, final, policy):
    # A short last chunk is not a reason to absorb an unrelated preceding idea.
    deviation = (count - policy["target_budget"]) / policy["target_budget"]
    cost = policy["size_weight"] * deviation * deviation * (.25 if final else 1.)
    if not final and policy["min_budget"]:
        short = max(0, policy["min_budget"] - count) / policy["min_budget"]
        cost += policy["short_weight"] * short * short
    return cost


def split_cost(text, path, counter, limit, policy, *, protected, fallback):
    """Return exact ranges plus diagnostics, with bounded work and explicit fallback.

    The DP is optimal only for this candidate graph, transition window and cost
    profile. Non-monotonic tokenizers prohibit stopping at the first overflow.
    """
    protected = merge_protected(protected)
    diagnostic = {"requested_strategy": "cost", "used_strategy": "cost",
        "fallback_reason": None, "candidate_units": 0, "transition_checks": 0, "objective": None}

    def greedy(reason):
        diagnostic.update(used_strategy="greedy", fallback_reason=reason)
        return fallback(text, path, counter, limit, protected_ranges=protected), diagnostic

    if counter.count(contextualize(path, text)) <= limit:
        return [(0, len(text), None)], diagnostic
    if counter.count(contextualize(path, "")) >= limit:
        return [(0, len(text), "breadcrumb_exceeds_budget")], diagnostic
    points = candidate_points(text, protected)
    atoms = []
    for a, b in zip(points, points[1:]):
        if counter.count(contextualize(path, text[a:b])) <= limit:
            atoms.append((a, b, None))
        else:
            local_protected = [(max(a, x) - a, min(b, y) - a) for x, y in protected
                               if max(a, x) < min(b, y)]
            pieces = fallback(text[a:b], path, counter, limit, protected_ranges=local_protected)
            atoms.extend((a + x, a + y, reason) for x, y, reason in pieces)
    diagnostic["candidate_units"] = len(atoms)
    costs, previous = [0.] + [math.inf] * len(atoms), [None] * (len(atoms) + 1)
    cuts, curly, straight, parentheses = [], 0, 0, 0
    for i in range(len(atoms) + 1):
        if i:
            fragment = text[atoms[i - 1][0]:atoms[i - 1][1]]
            curly += fragment.count("“") - fragment.count("”")
            straight += fragment.count('"')
            parentheses += fragment.count("(") - fragment.count(")")
        cuts.append(_boundary_cost(text, atoms, i, policy, curly > 0 or straight % 2 == 1 or parentheses > 0))
    for end in range(1, len(atoms) + 1):
        if atoms[end - 1][2]:
            # An oversized protected atom is a held child, never silently cut or
            # allowed to poison readable neighbors. Its path cost is constant.
            costs[end], previous[end] = costs[end - 1], end - 1
            continue
        for start in range(end - 1, max(-1, end - policy["max_candidate_units"] - 1), -1):
            if atoms[start][2]:
                break
            if not math.isfinite(costs[start]):
                continue
            diagnostic["transition_checks"] += 1
            if diagnostic["transition_checks"] > policy["max_transition_checks"]:
                return greedy("transition_check_limit")
            count = counter.count(contextualize(path, text[atoms[start][0]:atoms[end - 1][1]]))
            if count > limit:
                continue
            value = costs[start] + _size_cost(count, end == len(atoms), policy) + cuts[end]
            if value < costs[end]:
                costs[end], previous[end] = value, start
    if previous[-1] is None:
        return greedy("no_feasible_candidate_path")
    result, end = [], len(atoms)
    while end:
        start = previous[end]
        result.append((atoms[start][0], atoms[end - 1][1], atoms[start][2] if end == start + 1 else None))
        end = start
    diagnostic["objective"] = costs[-1]
    return list(reversed(result)), diagnostic
