"""Optional, page-selective PDFium text verification with character geometry.

PDFium is an independent extraction engine, not ground truth. This adapter only
reports the text/font/box it observes; callers must combine it with source-font
metadata before deciding whether any recovery is justified.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from idp.pdf.native.geometry import to_display_bbox
from idp.pdf.native.preflight import PdfSource, source_scope


@dataclass(frozen=True, slots=True)
class PdfiumCharacter:
    page: int
    index: int
    text: str
    bbox: tuple[float, float, float, float] | None
    font_name: str | None
    geometry_status: str


class PdfiumUnavailableError(RuntimeError):
    """The optional PDFium package or native library is unavailable."""


class PdfiumTextBackend:
    """Read text characters and font names for explicitly selected PDF pages."""

    name = "pypdfium2"

    def extract_pages(self, data: bytes, pages: tuple[int, ...] | list[int], *, source: PdfSource | None = None, include_font_names: bool = True) -> dict[int, tuple[PdfiumCharacter, ...]]:
        if not isinstance(data, bytes) or not data:
            raise ValueError("PDFium verification requires non-empty source bytes")
        requested = tuple(dict.fromkeys(pages))
        if not requested:
            return {}
        if any(type(page) is not int or page < 1 for page in requested):
            raise ValueError("PDFium page numbers must be 1-based positive integers")

        result: dict[int, tuple[PdfiumCharacter, ...]] = {}
        with source_scope(data, source) as opened:
            if any(number not in opened.geometry for number in requested):
                raise ValueError("PDFium page selection is outside the source PDF")
            try:
                document = opened.pdfium
            except (ImportError, OSError) as exc:
                raise PdfiumUnavailableError(f"pypdfium2 is unavailable: {exc}") from exc
            for number in requested:
                opened.check_deadline()
                page = None
                text_page = None
                try:
                    page = document[number - 1]
                    text_page = page.get_textpage()
                    geometry = opened.geometry[number]
                    characters = []
                    character_count = text_page.count_chars()
                    if character_count > opened.policy.max_secondary_characters_per_page:
                        raise RuntimeError("PDFium secondary text exceeded the per-page character budget")
                    for index in range(character_count):
                        if index % 256 == 0:
                            opened.check_deadline()
                        try:
                            text = text_page.get_text_range(index, 1, errors="replace")
                        except (IndexError, RuntimeError, ValueError):
                            text = ""
                        if not text:
                            continue
                        font_name = _font_name(text_page, index) if include_font_names else None
                        raw_bbox = _char_box(text_page, index)
                        bbox, geometry_status = to_display_bbox(raw_bbox, geometry)
                        characters.append(PdfiumCharacter(number, index, text, bbox, font_name, geometry_status))
                    result[number] = tuple(characters)
                finally:
                    if text_page is not None:
                        text_page.close()
                    if page is not None:
                        page.close()
        return result


def _font_name(text_page, index: int) -> str | None:
    text_object = text_page.get_textobj(index)
    if text_object is None:
        return None
    try:
        return text_object.get_font().get_base_name()
    except (RuntimeError, ValueError, OSError):
        return None


def _char_box(text_page, index: int) -> tuple[float, float, float, float] | None:
    try:
        values = tuple(float(value) for value in text_page.get_charbox(index))
    except (RuntimeError, ValueError, TypeError, IndexError):
        return None
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        return None
    left, bottom, right, top = values
    if right <= left or top <= bottom:
        return None
    return left, bottom, right, top


__all__ = [
    "PdfiumCharacter",
    "PdfiumTextBackend",
    "PdfiumUnavailableError",
]
