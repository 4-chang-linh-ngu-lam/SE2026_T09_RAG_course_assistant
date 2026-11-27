"""Page-level content checks used by the block publish gate.

Three narrow decisions, each explainable from the block text alone:

* ``budget_hold_is_infrastructure``: a plain-text block whose own OCR score is
  good was flagged only because a structured re-read ran out of budget.
* ``resolved_disagreements``: an ``OCR_REGION_DISAGREEMENT`` whose alternative
  reading either belongs to another block, or agrees with this block on every
  number and every relation symbol (only presentation differs).
* ``membership_conflicts``: "17 ∉ D" next to "D = {7; 11; 13; 17; 19}" on the
  same page. One of the two readings is wrong; the derived statement is held.

None of these certify OCR accuracy.
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

BUDGET_CODE = "STRUCTURED_BUDGET_EXHAUSTED"
DISAGREEMENT_CODE = "OCR_REGION_DISAGREEMENT"
MEMBERSHIP_CODE = "MATH_SET_MEMBERSHIP_CONFLICT"
PLAIN_TEXT_TYPES = {"Text", "SectionHeader", "ListItem", "Caption", "Footnote"}
BUDGET_MIN_CONFIDENCE = 0.80
DISAGREEMENT_MIN_CONFIDENCE = 0.90
DISAGREEMENT_MIN_SIMILARITY = 0.50
OTHER_BLOCK_MARGIN = 0.10

_RELATIONS = {
    "\\notin": "∉", "\\in": "∈", "\\neq": "≠", "\\ne": "≠", "\\leq": "≤", "\\le": "≤",
    "\\geq": "≥", "\\ge": "≥", "\\leqslant": "≤", "\\geqslant": "≥", "\\pm": "±",
}
_RELATION_CHARS = set("∈∉≠≤≥<>=±")
_MATH_MARKERS = re.compile(r"[\\$^_=<>≤≥≠∈∉±√∑∫]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _confidence(block: dict) -> float | None:
    value = block.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _symbols(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    for command in sorted(_RELATIONS, key=len, reverse=True):
        text = re.sub(re.escape(command) + r"(?![A-Za-z])", _RELATIONS[command], text)
    return text.replace("\\{", "{").replace("\\}", "}").replace("\\(", " ").replace("\\)", " ")


def _compact(text: str) -> str:
    """Folded letters, digits and relation symbols; LaTeX command names dropped."""
    text = re.sub(r"\\[A-Za-z]+", " ", _symbols(text))
    text = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    return "".join(c for c in text if c.isalnum() or c in _RELATION_CHARS)


def _numbers(text: str) -> set[str]:
    return {n.replace(".", ",") for n in _NUMBER.findall(_symbols(text))}


def _relations(text: str) -> set[str]:
    return {c for c in _symbols(text) if c in _RELATION_CHARS}


_FUNCTION_NAMES = re.compile(r"\\(sin|cos|tan|cot|ln|log|exp|lim|max|min)(?![A-Za-z])")


def _words(text: str) -> list[str]:
    """Accent-folded words, so a diacritic slip (bất/bắt/bát) is not a word change."""
    text = _FUNCTION_NAMES.sub(r" \1 ", _symbols(text))
    text = re.sub(r"\\[A-Za-z]+", " ", text)
    text = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", text)  # digits too: "THE0" is not "THEO"


def _word_changes(alternative: str, text: str) -> list[str]:
    """Alternative words with no counterpart in ``text``.

    Short words must match exactly ("ẩn" vs "lần" is a different word); longer
    ones may differ by one OCR slip ("sina" vs "sin a").
    """
    own = _words(text)
    joined = {a + b for a, b in zip(own, own[1:])}
    vocabulary = set(own) | joined
    changes = []
    for word in _words(alternative):
        if word in vocabulary:
            continue
        if len(word) > 3 and any(
            SequenceMatcher(None, word, w, autojunk=False).ratio() >= 0.85 for w in vocabulary
        ):
            continue
        changes.append(word)
    return changes


def _similarity(a: str, b: str) -> float:
    a, b = _compact(a), _compact(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def budget_hold_is_infrastructure(block: dict) -> bool:
    """True when STRUCTURED_BUDGET_EXHAUSTED says nothing about this block's text."""
    text = (block.get("text") or "").strip()
    confidence = _confidence(block)
    return (
        (block.get("type") or block.get("block_type")) in PLAIN_TEXT_TYPES
        and bool(text)
        and confidence is not None
        and confidence >= BUDGET_MIN_CONFIDENCE
        and not _MATH_MARKERS.search(text)
        and sum(c.isalpha() for c in text) >= 0.5 * len(text.replace(" ", ""))
    )


def resolved_disagreements(block: dict, page_blocks: list[dict]) -> bool:
    """True when every disagreement flag on ``block`` is presentation-only or foreign."""
    flags = [
        f for f in block.get("review_flags") or []
        if f.get("code") == DISAGREEMENT_CODE and f.get("severity") in {"warning", "error"}
    ]
    if not flags:
        return False
    text = block.get("text") or ""
    confidence = _confidence(block)
    if not text.strip() or confidence is None or confidence < DISAGREEMENT_MIN_CONFIDENCE:
        return False
    others = [
        b.get("text") or "" for b in page_blocks
        if b is not block and not b.get("excluded") and (b.get("text") or "").strip()
    ]
    for flag in flags:
        alternative = flag.get("alternative")
        if not isinstance(alternative, str) or not alternative.strip():
            return False
        own = _similarity(alternative, text)
        if others and max(_similarity(alternative, o) for o in others) >= own + OTHER_BLOCK_MARGIN:
            continue  # the alternative reads another line of the region
        if (
            own < DISAGREEMENT_MIN_SIMILARITY
            or not _numbers(alternative) <= _numbers(text)
            or not _relations(alternative) <= _relations(text)
            or _word_changes(alternative, text)
        ):
            return False
    return True


_SET_DEFINITION = re.compile(r"(?<![A-Za-z])([A-Z])\s*=\s*\{([^{}|]*)\}")
_MEMBERSHIP = re.compile(r"(?<![\d.,])(\d+)\s*([∈∉])\s*([A-Z])(?![A-Za-z])")


def _enumerations(text: str) -> list[tuple[str, frozenset[str]]]:
    found = []
    for name, body in _SET_DEFINITION.findall(_symbols(text).replace("$", " ")):
        items = [x.strip() for x in re.split(r"[;,]", body) if x.strip()]
        if items and all(re.fullmatch(r"-?\d+", x) for x in items):
            found.append((name, frozenset(items)))
    return found


def membership_conflicts(page_blocks: list[dict]) -> set[str]:
    """Block IDs whose ∈/∉ statement contradicts an enumerated set on the page."""
    definitions: dict[str, set[frozenset[str]]] = {}
    for block in page_blocks:
        if block.get("excluded"):
            continue
        for name, items in _enumerations(block.get("text") or ""):
            definitions.setdefault(name, set()).add(items)
    sets = {name: next(iter(v)) for name, v in definitions.items() if len(v) == 1}
    if not sets:
        return set()
    conflicts = set()
    for block in page_blocks:
        if block.get("excluded"):
            continue
        text = _symbols(block.get("text") or "").replace("$", " ")
        if _enumerations(text):
            continue
        for number, relation, name in _MEMBERSHIP.findall(text):
            if name in sets and (relation == "∈") != (number in sets[name]):
                conflicts.add(block.get("block_id"))
    return conflicts
