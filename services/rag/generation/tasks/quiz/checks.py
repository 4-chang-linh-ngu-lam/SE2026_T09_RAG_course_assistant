"""Deterministic item checks (§5.5): answer leaks, item-writing rules, grounding.

Each check returns flag codes; they never decide on their own that an item is
wrong. The negative-stem rule is auto-fixed (lower-case "không" in a negative
question is upper-cased) and reported.
"""
from __future__ import annotations

import re
import unicodedata

from ...contracts.errors import norm_key
from ...grounding.lexical import unsupported_numbers

_BANNED = ("tất cả các đáp án", "tất cả đáp án", "cả a và b", "cả a, b", "không có đáp án nào",
           "các đáp án trên", "all of the above", "none of the above", "both a and b")
_NEGATIVE = re.compile(r"\b(không|chẳng)(?=\s+(phải|đúng|là|thuộc|có|được|nằm|chính xác))")
_WORDS = re.compile(r"\w+", re.UNICODE)


def _options(item) -> tuple[list[str], list[str]]:
    if item["type"] == "single_choice":
        return [item["correct_answer"]], [d["text"] for d in item["distractors"]]
    if item["type"] == "multiple_choice":
        return list(item["correct_answers"]), [d["text"] for d in item["distractors"]]
    return [], []


def _ngrams(text, n=3):
    words = [w.casefold() for w in _WORDS.findall(unicodedata.normalize("NFC", text))]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def fix_negative_stem(item) -> tuple[dict, list[str]]:
    key = "stem" if "stem" in item else "context"
    text = item[key]
    if "KHÔNG" in text or not _NEGATIVE.search(text):
        return item, []
    fixed = _NEGATIVE.sub(lambda m: m.group(1).upper(), text)
    return {**item, key: fixed}, ["negative_stem_auto_uppercased"]


def deterministic_flags(item: dict, unit_text: str) -> list[str]:
    flags = []
    correct, distractors = _options(item)
    stem = item.get("stem", item.get("context", ""))
    stem_key = norm_key(stem)
    options = correct + distractors
    if options:
        if any(len(norm_key(c)) >= 4 and norm_key(c) in stem_key for c in correct):
            flags.append("answer_in_stem")
        lengths = [len(o) for o in options]
        if distractors and max(len(c) for c in correct) > 1.6 * max(len(d) for d in distractors) and max(lengths) > 20:
            flags.append("correct_option_longest")
        if min(lengths) and max(lengths) / min(lengths) > 3 and max(lengths) > 20:
            flags.append("option_length_imbalance")
        if any(any(b in norm_key(o) for b in _BANNED) for o in options):
            flags.append("banned_option_phrase")
        stem_grams = _ngrams(stem)
        echo_correct = any(_ngrams(c) & stem_grams for c in correct)
        echo_distractor = any(_ngrams(d) & stem_grams for d in distractors)
        if echo_correct and not echo_distractor:
            flags.append("correct_echoes_stem")
    # Numbers in the key must exist in the unit unless a verified computation produced them.
    if item["type"] in ("single_choice", "multiple_choice"):
        if any(unsupported_numbers(c, unit_text) for c in correct):
            flags.append("key_number_not_in_source")
    elif item["type"] == "short_answer" and item["answer"]["kind"] == "number":
        if not item["answer"]["computation_verified"] and unsupported_numbers(item["answer"]["value"], unit_text):
            flags.append("key_number_not_in_source")
    elif item["type"] == "true_false_4":
        for statement in item["statements"]:
            if statement["truth"] and unsupported_numbers(statement["text"], unit_text):
                flags.append("true_statement_number_not_in_source")
                break
    return flags
