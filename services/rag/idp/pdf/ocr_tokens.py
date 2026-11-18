"""Tesseract tokens whose reading must not be published on trust.

Tesseract scores every word. On the SGK Toán 10 benchmark the formula and
icon tokens it misread are the ones it scored lowest: ``Js?`` for a square
root (0.15), ``=5/2.`` for the stacked fraction 26/5 (0.16), ``Q.=`` for
``Q₂ =`` (0.41), ``(#®)`` for an activity icon (0.12). A squared variable is
read as ``s?``/``a?`` even with high confidence. Low-scored *prose* words
are mostly diacritic slips and stay readable, so they are not suspect.

Shared by OCR paragraph grouping (a line holding a suspect token becomes its
own block) and publication (such a block is ``OCR_TOKEN_UNVERIFIED``).
"""

import re

# Tesseract word confidence (0..1) below which a non-prose token is suspect.
OCR_TOKEN_FLOOR = 0.50
# Below this Tesseract has no reading at all (icons, rules, bleed-through).
OCR_TOKEN_NOISE_FLOOR = 0.20
# Letters and ordinary prose punctuation are not suspicious on their own.
PROSE_PUNCTUATION = frozenset(".,;:!?…'\"()[]«»“”‘’-–—/")
_STRIP = "".join(PROSE_PUNCTUATION)
# A token made only of these is a list bullet, dash or quote mark printed
# before prose ("+ Khoảng biến thiên", "« Điểm G ..."), not a formula.
BULLET_MARKS = PROSE_PUNCTUATION | frozenset("+_*•·¬~›‹°")
_SQUARED_VARIABLE = re.compile(r"^[A-Za-z]\?")
# A radical sign read as "./", "\/" or "V/" before its digits ("./5,2").
_RADICAL = re.compile(r"(?:\./|\\/|V/)\d")
# A subscript read as punctuation: "Q,=" / "Q.=" (Q₁ =, Q₂ =), "A„", "x„".
_SUBSCRIPT = re.compile(r"^[A-Za-z](?:[,.]=|„)")


def suspect_ocr_tokens(words):
    """Return the suspect token texts among recognition ``words``.

    A token is suspect when it is a single ASCII letter followed by ``?``
    (a squared variable), holds a radical read as ``./`` before digits, is a
    subscript read as punctuation (``Q,=``, ``A„``), or is the only token of
    its line and a single letter; or when Tesseract scored it below
    ``OCR_TOKEN_FLOOR`` and it carries a digit, an operator or a symbol, or
    is a single letter, or it is scored below ``OCR_TOKEN_NOISE_FLOOR``.
    Tokens made only of bullet/punctuation marks are never suspect.
    """
    found = []
    words = [word for word in words or () if word.get("text")]
    if len(words) == 1 and len(words[0]["text"]) == 1 and words[0]["text"].isalpha():
        # A line holding one letter is a piece of a built-up formula.
        return [words[0]["text"]]
    for word in words:
        text = word.get("text") or ""
        if _SQUARED_VARIABLE.match(text) or _RADICAL.search(text) or _SUBSCRIPT.match(text):
            found.append(text)
            continue
        confidence = word.get("confidence")
        if confidence is None or confidence >= OCR_TOKEN_FLOOR:
            continue
        if all(c in BULLET_MARKS for c in text):
            continue
        if confidence < OCR_TOKEN_NOISE_FLOOR:
            found.append(text)
            continue
        symbol = any(not c.isalpha() and c not in PROSE_PUNCTUATION for c in text)
        single_letter = len(text.strip(_STRIP)) == 1 and text.strip(_STRIP).isalpha()
        if symbol or single_letter:
            found.append(text)
    return found


def isolate_suspect_line(line):
    """Grouping predicate: keep a line with a suspect token on its own."""
    return bool(suspect_ocr_tokens((line.payload or {}).get("words")))


def _data_row(text):
    tokens = text.split()
    numbers = sum(any(c.isdigit() for c in token) for token in tokens)
    return len(tokens) >= 2 and numbers * 2 >= len(tokens)


def numeric_block(lines):
    """Most lines are data rows (at least half of their tokens carry digits):
    a table or data series, not prose that mentions numbers.

    Such a paragraph is not split around a suspect line; publishing its other
    rows would present an incomplete table as complete."""
    rows = sum(_data_row(line.text) for line in lines)
    return rows * 2 >= len(lines)
