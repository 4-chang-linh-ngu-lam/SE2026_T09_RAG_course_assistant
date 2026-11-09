"""Ingestion profiles separate the generic pipeline from domain policy.

The default profile must not apply math/Vietnamese-specific corrections:
users can upload contracts, invoices, slides, reports, tables, scans, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MATH_TERMS = {
    "tập hợp", "phần tử", "phân số", "số nguyên", "số tự nhiên", "nguyên tố",
    "hình học", "tam giác", "phương trình", "bất phương trình", "hàm số",
    "đạo hàm", "tích phân", "vectơ", "tọa độ", "xác suất", "thống kê",
}


@dataclass(frozen=True)
class IngestionProfile:
    name: str
    language: str | None = None
    apply_domain_text_fixes: bool = False
    math_formula_checks: bool = False
    require_formula_quality: bool = False
    text_review_max: float = 0.10
    page_risk_max: float = 0.10
    formula_valid_min: float = 0.95


GENERAL = IngestionProfile(name="general")
MATH_VI = IngestionProfile(
    name="math_vi",
    language="vie",
    apply_domain_text_fixes=True,
    math_formula_checks=True,
    require_formula_quality=True,
)

PROFILES = {
    "general": GENERAL,
    "math_vi": MATH_VI,
}

_MATH_SPAN_RE = re.compile(
    r"\$[^$]+\$|\\(?:frac|sqrt|left|right|begin|end|sum|int|lim)\b"
)
_MATH_SYMBOLS = set("=+-×÷^_{}√∑∫∞≤≥<>")


def detect_math_profile(sample: str) -> IngestionProfile:
    """Use math only when the page is clearly math-heavy.

    Ambiguous documents stay on the general profile; a missed math correction
    is safer than corrupting arbitrary prose.
    """
    text = sample or ""
    if not text.strip():
        return GENERAL
    math_spans = len(_MATH_SPAN_RE.findall(text))
    alnum = sum(ch.isalnum() for ch in text)
    math_chars = sum(ch in _MATH_SYMBOLS for ch in text)
    math_ratio = math_chars / max(1, alnum)
    lowered = text.lower()
    term_hits = sum(1 for term in _MATH_TERMS if term in lowered)
    if math_spans >= 5 or (math_spans >= 3 and term_hits >= 2) or math_ratio >= 0.03:
        return MATH_VI
    return GENERAL


def resolve_profile(
    value: str | IngestionProfile | None,
    sample: str | None = None,
) -> IngestionProfile:
    if isinstance(value, IngestionProfile):
        return value
    name = (value or "general").strip().lower()
    if name == "auto":
        return detect_math_profile(sample or "")
    return PROFILES.get(name, GENERAL)
