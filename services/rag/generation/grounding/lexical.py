"""Cheap lexical grounding checks: numbers and proper names (§4.4 tier 3).

A claim's numbers (digits) and mid-sentence capitalised names must occur in the
text it cites. This is a filter against invented figures, not entailment.
Number tokens are compared as *sets of readings* because "1.000" and "3,5" are
ambiguous between Vietnamese and English conventions.
"""
from __future__ import annotations

import re
import unicodedata

_NUMBER = re.compile(r"(?<![\w.,])[-−]?\d+(?:[.,]\d+)*(?:\s?%)?")
_WORD = re.compile(r"\w+", re.UNICODE)
_SENTENCE_START = re.compile(r"(?:^|[.!?:;\n•\-–—\"“(]\s*)$")

_NUMBER_WORDS = {"không": 0, "một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5,
                 "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10, "trăm": 100,
                 "nghìn": 1000, "ngàn": 1000, "triệu": 1_000_000, "tỉ": 1_000_000_000,
                 "tỷ": 1_000_000_000, "đôi": 2, "nửa": 0.5, "rưỡi": 0.5}


def _readings(token: str) -> set[float]:
    token = token.replace("−", "-").replace(" ", "")
    percent = token.endswith("%")
    token = token.rstrip("%")
    sign = -1 if token.startswith("-") else 1
    body = token.lstrip("-")
    readings = set()
    candidates = [body.replace(".", "").replace(",", ""),            # all separators are thousands
                  body.replace(".", "").replace(",", "."),           # vi: dot thousands, comma decimal
                  body.replace(",", "")]                             # en: comma thousands, dot decimal
    for candidate in candidates:
        try:
            readings.add(sign * float(candidate))
        except ValueError:
            pass
    if percent:
        readings |= {r / 100 for r in readings}
    return readings


def number_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _NUMBER.finditer(unicodedata.normalize("NFC", text))]


def _support_numbers(text: str) -> set[float]:
    text = unicodedata.normalize("NFC", text)
    values = set()
    for token in number_tokens(text):
        values |= _readings(token)
    for word in _WORD.findall(text.casefold()):
        if word in _NUMBER_WORDS:
            values.add(float(_NUMBER_WORDS[word]))
    return values


def unsupported_numbers(claim: str, support: str) -> list[str]:
    available = _support_numbers(support)
    return [t for t in number_tokens(claim) if not (_readings(t) & available)]


def proper_names(text: str) -> list[str]:
    """Mid-sentence runs of capitalised words (``Nguyễn Trãi``, ``Newton``)."""
    text = unicodedata.normalize("NFC", text)
    names, current = [], []
    for match in _WORD.finditer(text):
        word = match.group(0)
        titlecase = word[0].isupper() and not word.isupper()  # all-caps emphasis is not a name
        at_start = bool(_SENTENCE_START.search(text[:match.start()]))
        if titlecase and (current or not at_start):
            current.append(word)
            continue
        if current:
            names.append(" ".join(current))
        current = []
    if current:
        names.append(" ".join(current))
    return names


def unsupported_names(claim: str, support: str) -> list[str]:
    haystack = " ".join(unicodedata.normalize("NFC", support).casefold().split())
    return [n for n in proper_names(claim) if n.casefold() not in haystack]


def lexical_gaps(claim: str, support: str) -> dict:
    gaps = {}
    numbers = unsupported_numbers(claim, support)
    names = unsupported_names(claim, support)
    if numbers:
        gaps["numbers"] = numbers
    if names:
        gaps["names"] = names
    return gaps
