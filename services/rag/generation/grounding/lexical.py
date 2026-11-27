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
_SENTENCE_START = re.compile(r"(?:^|[.!?:;\n•\-–—\"“'”«(]\s*|^\s*[-*+]\s*)$")
_LATEX_SCRIPT = re.compile(r"([A-Za-zα-ωΑ-Ω])[_^]\{([^{}]*)\}")
_LATEX_SIMPLE_SCRIPT = re.compile(r"([A-Za-zα-ωΑ-Ω])[_^](\d+)")
_SUB_SUPER_DIGIT = re.compile(r"([A-Za-zα-ωΑ-Ω])([₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
_VI_THOUSANDS = re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$")
_EN_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_PLAIN_INT = re.compile(r"^\d+$")
_ZERO_WORD_RE = re.compile(r"\b(?:số\s+không|bằng\s+không|âm\s+không)\b")
_FOUR_WORD_RE = re.compile(r"\b(?:thứ\s+tư|một\s+phần\s+tư|phần\s+tư)\b")
_NON_NUMERIC_NAM_RE = re.compile(
    r"\b(?:năm\s+\d{1,4}|năm\s+(?:học|nay|ngoái|tới|trước|sau|đầu|cuối|thứ)|"
    r"(?:hàng|trong|mỗi|suốt|quanh|cả|đầu|cuối|từ|vào|đến)\s+năm)\b"
)
_NON_NUMERIC_MOT_RE = re.compile(
    r"\b(?:một\s+(?:số|vài|ít|cách|lúc|chút|nữa|phần\s+trăm|mình|khi))\b"
)
_STRUCTURAL_CAP_SINGLES = frozenset({"bước", "chương", "mục", "phần"})
_STRUCTURAL_CAP_PHRASES = frozenset(
    {
        "định lý", "định lí", "định nghĩa", "hệ quả", "bổ đề", "tính chất",
        "mệnh đề", "phương trình", "hệ phương trình", "bất phương trình",
        "hàm số", "đạo hàm", "tích phân", "vi phân", "ví dụ", "bài tập",
        "bài toán", "chú ý", "nhận xét", "lưu ý", "kết luận", "trường hợp",
        "khái niệm", "công thức", "quy tắc", "phương pháp",
    }
)


def _normalize_math(text: str) -> str:
    """Fold math subscript/superscript notation (x_{0}, x_0, x₀ -> x0) for number checks."""
    value = unicodedata.normalize("NFC", text)
    previous = None
    while previous != value:
        previous = value
        value = _LATEX_SCRIPT.sub(r"\1\2", value)
    value = _LATEX_SIMPLE_SCRIPT.sub(r"\1\2", value)
    value = _SUB_SUPER_DIGIT.sub(lambda m: m.group(1) + unicodedata.normalize("NFKC", m.group(2)), value)
    return value

_NUMBER_WORDS = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5,
                 "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10, "trăm": 100,
                 "nghìn": 1000, "ngàn": 1000, "triệu": 1_000_000, "tỉ": 1_000_000_000,
                 "tỷ": 1_000_000_000, "đôi": 2, "nửa": 0.5, "rưỡi": 0.5}


def _readings(token: str) -> set[float]:
    token = token.replace("−", "-").replace(" ", "")
    percent = token.endswith("%")
    token = token.rstrip("%")
    sign = -1 if token.startswith("-") else 1
    body = token.lstrip("-")
    readings: set[float] = set()
    if _PLAIN_INT.fullmatch(body):
        readings.add(sign * float(body))
    else:
        if _VI_THOUSANDS.fullmatch(body):
            readings.add(sign * float(body.replace(".", "").replace(",", ".")))
        if _EN_THOUSANDS.fullmatch(body):
            readings.add(sign * float(body.replace(",", "")))
        if body.count(",") == 1 and "." not in body:
            readings.add(sign * float(body.replace(",", ".")))
        if body.count(".") == 1 and "," not in body:
            readings.add(sign * float(body))
    if percent:
        readings |= {r / 100 for r in readings}
    return readings


def number_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _NUMBER.finditer(_normalize_math(text))]


def _support_numbers(text: str) -> set[float]:
    norm = _normalize_math(text)
    values = set()
    for token in number_tokens(norm):
        values |= _readings(token)
    folded = norm.casefold()
    if _ZERO_WORD_RE.search(folded):
        values.add(0.0)
    if _FOUR_WORD_RE.search(folded):
        values.add(4.0)
    cleaned = _NON_NUMERIC_NAM_RE.sub(" ", folded)
    cleaned = _NON_NUMERIC_MOT_RE.sub(" ", cleaned)
    for word in _WORD.findall(cleaned):
        if word in _NUMBER_WORDS:
            values.add(float(_NUMBER_WORDS[word]))
    return values


def unsupported_numbers(claim: str, support: str) -> list[str]:
    available = _support_numbers(support)
    raw_support = {t.replace("−", "-").replace(" ", "") for t in number_tokens(support)}
    unsupported = []
    for token in number_tokens(claim):
        normalized = token.replace("−", "-").replace(" ", "")
        if normalized in raw_support:
            continue
        if not (_readings(token) & available):
            unsupported.append(token)
    return unsupported


def proper_names(text: str) -> list[str]:
    """Mid-sentence runs of capitalised words (``Nguyễn Trãi``, ``Newton``)."""
    text = unicodedata.normalize("NFC", text)
    matches = list(_WORD.finditer(text))
    names, current = [], []

    def _is_structural_heading(parts: list[str], next_word: str | None) -> bool:
        if len(parts) != 1:
            return False
        head = parts[0].casefold()
        if head in _STRUCTURAL_CAP_SINGLES:
            return True
        return next_word is not None and f"{head} {next_word.casefold()}" in _STRUCTURAL_CAP_PHRASES

    for idx, match in enumerate(matches):
        word = match.group(0)
        titlecase = word[0].isupper() and not word.isupper()  # all-caps emphasis is not a name
        at_start = bool(_SENTENCE_START.search(text[:match.start()]))
        if titlecase and (current or not at_start):
            current.append(word)
            continue
        if current and not _is_structural_heading(current, word if not titlecase else None):
            names.append(" ".join(current))
        current = []
    if current and not _is_structural_heading(current, None):
        names.append(" ".join(current))
    return names


def unsupported_names(claim: str, support: str) -> list[str]:
    # Names are compared word by word: proper_names() joins words with single
    # spaces, so "Lotka–Volterra" or "Pierre-Simon" in the support must be
    # compared without their joiners and line breaks.
    words = _WORD.findall(unicodedata.normalize("NFC", support).casefold())
    haystack = f" {' '.join(words)} "
    return [n for n in proper_names(claim) if f" {n.casefold()} " not in haystack]


def lexical_gaps(claim: str, support: str) -> dict:
    gaps = {}
    numbers = unsupported_numbers(claim, support)
    names = unsupported_names(claim, support)
    if numbers:
        gaps["numbers"] = numbers
    if names:
        gaps["names"] = names
    return gaps
