"""Auditable, PDF-specific corrections for demonstrably broken native glyph mappings.

No heuristic replacement is performed here: ASCII text such as "6=" can be valid.
A correction is applied only when its SHA-256, page, Poppler block index, and
entire original block text all match. Evidence must be supplied by the caller.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .source_observation import DeepDocGlyphProof, DeepDocReviewProof


@dataclass(frozen=True, slots=True)
class ReviewedNativeCorrection:
    pdf_sha256: str
    page: int
    block: int
    original_text: str
    corrected_text: str
    evidence: str


def prepare_verified_glyph_corrections(pdf_data: bytes, corrections: Sequence[Mapping[str, Any]] | None) -> dict[tuple[int, int], ReviewedNativeCorrection]:
    """Validate human-reviewed corrections before touching any PDF observation.

    Coordinates are block indexes from Poppler -bbox-layout (zero-based within
    the page), not visual bounding boxes that may drift between renderers.
    """
    if corrections is None:
        return {}
    if isinstance(corrections, (str, bytes, Mapping)):
        raise TypeError("verified glyph corrections must be a list of records")

    digest = hashlib.sha256(pdf_data).hexdigest()
    indexed: dict[tuple[int, int], ReviewedNativeCorrection] = {}
    for index, correction in enumerate(corrections):
        if not isinstance(correction, Mapping):
            raise TypeError(f"glyph correction {index} must be a mapping")
        if correction.get("pdf_sha256") != digest:
            raise ValueError(f"glyph correction {index} does not match the PDF SHA-256")
        page = correction.get("page")
        block = correction.get("block")
        if type(page) is not int or page < 1 or type(block) is not int or block < 0:
            raise ValueError(f"glyph correction {index} needs a 1-based page and zero-based block")
        original = correction.get("original_text")
        corrected = correction.get("corrected_text")
        evidence = correction.get("evidence")
        if not all(isinstance(v, str) and v.strip() for v in (original, corrected, evidence)):
            raise ValueError(f"glyph correction {index} requires original_text, corrected_text, and evidence")
        if original == corrected:
            raise ValueError(f"glyph correction {index} does not change its text")
        key = (page, block)
        if key in indexed:
            raise ValueError(f"duplicate glyph correction for page {page}, block {block}")
        indexed[key] = ReviewedNativeCorrection(digest, page, block, original, corrected, evidence)
    return indexed


def apply_verified_glyph_correction(
    original_text: str,
    *,
    page: int,
    block: int,
    corrections: Mapping[tuple[int, int], ReviewedNativeCorrection],
) -> tuple[str, DeepDocReviewProof | None]:
    """Return an exact reviewed correction and typed proof, or untouched text."""
    item = corrections.get((page, block))
    if item is None:
        return original_text, None
    if item.page != page or item.block != block or original_text != item.original_text:
        raise ValueError(f"Poppler text changed at page {page}, block {block}; the verified glyph correction must be reviewed again")
    return item.corrected_text, DeepDocReviewProof(
        item.pdf_sha256, page, block, hashlib.sha256(original_text.encode()).hexdigest(), hashlib.sha256(item.corrected_text.encode()).hexdigest(), item.evidence
    )


@dataclass(frozen=True, slots=True)
class VerifiedFontGlyphCorrection:
    """An internal, source-locked correction proposed from font evidence."""

    pdf_sha256: str
    page: int
    block: int
    original_text: str
    spans: tuple[tuple[int, int, str, str], ...]
    font_fingerprints: tuple[str, ...]
    evidence: tuple[DeepDocGlyphProof, ...]
    method: str
    verification_status: str = "VERIFIED"


def apply_verified_font_glyph_correction(
    original_text: str,
    *,
    pdf_sha256: str,
    page: int,
    block: int,
    correction: VerifiedFontGlyphCorrection,
) -> str:
    """Apply only a font-evidence proposal bound to this exact PDF/block text.

    Manual ``glyph_corrections`` remain a separate, higher-priority path. This
    function accepts proposals from the parser's evidence gate, never a free
    form caller-supplied mapping.
    """
    if correction.verification_status != "VERIFIED":
        raise ValueError("font glyph correction lacks VERIFIED evidence status")
    if correction.method != "font_glyph_name_negationslash_overlaid_equal":
        raise ValueError("font glyph correction uses an unsupported recovery method")
    if correction.pdf_sha256 != pdf_sha256:
        raise ValueError("font glyph correction does not match the source PDF SHA-256")
    if correction.page != page or correction.block != block:
        raise ValueError("font glyph correction is bound to a different page or block")
    if correction.original_text != original_text:
        raise ValueError("Poppler text changed; the font glyph correction must be reviewed again")
    if not correction.spans or not correction.font_fingerprints or not correction.evidence:
        raise ValueError("font glyph correction requires spans, font identity, and evidence")
    if len(correction.spans) != len(correction.evidence):
        raise ValueError("font glyph correction evidence must correspond one-to-one with text spans")

    for evidence in correction.evidence:
        if evidence.page != page or evidence.font_fingerprint not in correction.font_fingerprints or not set(evidence.equals_font_fingerprints).issubset(correction.font_fingerprints):
            raise ValueError("font glyph correction does not contain the required font and geometry evidence")

    normalized_spans = sorted(correction.spans, key=lambda item: (item[0], item[1]))
    previous_end = -1
    for start, end, expected, replacement in normalized_spans:
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > len(original_text):
            raise ValueError("font glyph correction has an invalid text span")
        if start < previous_end:
            raise ValueError("font glyph correction spans overlap")
        if original_text[start:end] != expected:
            raise ValueError("font glyph correction span no longer matches its source text")
        if not isinstance(replacement, str) or not replacement:
            raise ValueError("font glyph correction replacement must be non-empty")
        if replacement != "≠" or not re.fullmatch(r"6\s*=", expected):
            raise ValueError("this font glyph recovery only supports an evidenced 6-equals overlay")
        previous_end = end

    corrected = original_text
    for start, end, _expected, replacement in reversed(normalized_spans):
        corrected = corrected[:start] + replacement + corrected[end:]
    return corrected
