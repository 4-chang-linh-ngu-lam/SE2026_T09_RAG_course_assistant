"""Second, independent reading of OCR lines as verification evidence.

Each Tesseract line is re-read from the page image by another recognizer
(e.g. PaddleOCR-VL through ``local_region``). Agreement on the normalized
words is evidence that the line was read correctly; disagreement marks the
line for review and keeps the other reading for the reviewer. The source
text is never replaced: overall the second reader is not more accurate, and
it may rewrite content (9,5 -> 9.5) or formulas.

Measured on three hand-checked SGK Toán 10 pages (2026-11-20, 142 lines):
lines where both readers agree were 66/66 correct; Tesseract's own score
>= 0.60 let 27 wrong lines through, all of which disagreed.
"""

from __future__ import annotations

import re
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image

DUAL_READ_VERSION = "idp-dual-read-1"
OCR_SOURCES = {"tesseract_fallback", "tesseract_fast", "tesseract"}
READ_TYPES = {"Text", "SectionHeader", "ListGroup"}
_COMMAND = re.compile(r"\\[A-Za-z]+")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def comparable_words(text: str) -> list[str]:
    """Words for agreement: NFC, case-folded, punctuation/LaTeX markup dropped."""
    value = unicodedata.normalize("NFC", _COMMAND.sub(" ", text or "")).casefold()
    return sorted(_TOKEN.findall(value))


def dual_read_page(page: dict, image_path: str | Path, reader, *, pad: int = 4) -> dict:
    """Annotate OCR line blocks of ``page`` in place; return a summary.

    ``reader(crop_path) -> str`` must expose ``identity``. Block bboxes are in
    ``page["page_size"]`` coordinates and are scaled to the image.
    """
    identity = getattr(reader, "identity", None)
    if not identity:
        raise ValueError("dual reader needs a stable identity")
    summary = {"version": DUAL_READ_VERSION, "reader": identity,
               "agreed": 0, "disagreed": 0, "failed": 0}
    width, height = page.get("page_size") or (0, 0)
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    if not width or not height:
        return summary
    sx, sy = image.width / width, image.height / height
    with tempfile.TemporaryDirectory(prefix="idp-dual-") as directory:
        crop_path = Path(directory) / "line.png"
        for block in page.get("blocks") or []:
            if (
                block.get("source") not in OCR_SOURCES
                or block.get("block_type", block.get("type")) not in READ_TYPES
                or block.get("excluded_from_content")
                or not comparable_words(block.get("text") or "")
            ):
                continue
            x0, y0, x1, y1 = block["bbox"]
            box = (max(0, x0 * sx - pad), max(0, y0 * sy - pad),
                   min(image.width, x1 * sx + pad), min(image.height, y1 * sy + pad))
            if box[0] >= box[2] or box[1] >= box[3]:
                continue
            image.crop(box).save(crop_path)
            flags = block.setdefault("review_flags", [])
            try:
                other = reader(crop_path)
            except Exception as exc:  # noqa: BLE001 - a failed check is not evidence.
                summary["failed"] += 1
                flags.append({"block_id": block.get("block_id"), "code": "OCR_DUAL_READ_FAILED",
                              "severity": "warning", "reason": type(exc).__name__})
                continue
            if comparable_words(other) == comparable_words(block.get("text") or ""):
                summary["agreed"] += 1
                flags.append({"block_id": block.get("block_id"), "code": "OCR_DUAL_READ_AGREED",
                              "severity": "info", "version": DUAL_READ_VERSION})
            else:
                summary["disagreed"] += 1
                flags.append({"block_id": block.get("block_id"), "code": "OCR_DUAL_READ_DISAGREE",
                              "severity": "warning", "version": DUAL_READ_VERSION,
                              "alternative": (other or "")[:1000]})
    page["dual_read"] = summary
    return summary
