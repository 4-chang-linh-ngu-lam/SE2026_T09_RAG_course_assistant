"""Conservative text-layer quality checks for page routing.

These are adapted from RAGFlow's garbled/scan-noise checks: a PDF page with a
text layer is not trusted just because characters exist. PUA/CID/replacement
characters and noise-only pages are routed to OCR instead.
"""

from __future__ import annotations

import re
from collections import Counter

_CID_RE = re.compile(r"\(cid:\d+\)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_MODEL_TOKEN_RE = re.compile(r"<\|[^<>\r\n]{1,80}\|>|<\|\d{1,4}(?=[,\s]|$)")
_URL_RE = re.compile(r"https?://[^\s<>]+", re.I)


def has_model_artifact_tokens(text: str) -> bool:
    """Detect leaked decoder/location tokens without deleting source content.

    A document intentionally discussing such tokens can still be reviewed;
    their presence must never silently authorize an OCR transcription.
    """
    return bool(_MODEL_TOKEN_RE.search(text or ""))


def repeated_watermark_tokens(
    texts: list[str], min_occurrences: int = 4
) -> list[str]:
    """Return repetition candidates for review, never proof of a watermark.

    Repeated ASCII glyphs may also be MCQ options, table or diagram labels.
    This compatibility helper must never authorize content deletion.
    """
    counts = Counter()
    for text in texts:
        token = (text or "").strip()
        if len(token) == 1 and token.isascii() and token.isalnum():
            counts[token] += 1
    return sorted(
        token for token, count in counts.items()
        if count >= min_occurrences
    )


def _is_private_use(ch: str) -> bool:
    code = ord(ch)
    return (
        0xE000 <= code <= 0xF8FF
        or 0xF0000 <= code <= 0xFFFFD
        or 0x100000 <= code <= 0x10FFFD
    )


def is_garbled_text(text: str) -> bool:
    if not text:
        return False
    if "\ufffd" in text or _CID_RE.search(text):
        return True
    if any(_is_private_use(ch) for ch in text):
        return True
    bad = len(_CONTROL_RE.findall(text))
    return bad >= 3 and bad / max(1, len(text)) >= 0.02


def is_scan_noise(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    nonspace = [ch for ch in stripped if not ch.isspace()]
    if len(nonspace) < 4 or len(nonspace) >= 40:
        return False
    letters = len(_LETTER_RE.findall(stripped))
    digits = sum(ch.isdigit() for ch in stripped)
    if letters == 0 and digits == 0:
        return True
    symbols = sum(not ch.isalnum() for ch in nonspace)
    return letters < 2 and digits < 2 and symbols / len(nonspace) >= 0.5


def needs_ocr(text: str, *, min_chars: int = 40) -> tuple[bool, str | None]:
    stripped = (text or "").strip()
    if not stripped:
        return True, "empty_text_layer"
    if is_garbled_text(stripped):
        return True, "garbled_text_layer"
    urls = _URL_RE.findall(stripped)
    # A scan can carry a perfectly decodable overlay made only of a tiled
    # promotional URL. Character count/Unicode health cannot validate it.
    # Do not match a specific publisher, host or URL, and do not reject normal
    # prose containing links. This changes routing, never erases source text.
    remainder = _URL_RE.sub("", stripped)
    if urls and len(urls) >= 3 and max(Counter(urls).values()) >= 3 and len(re.sub(r"\s", "", remainder)) < min_chars:
        return True, "repeated_url_only_text_layer"
    if len(stripped) < min_chars and is_scan_noise(stripped):
        return True, "scan_noise"
    return False, None
