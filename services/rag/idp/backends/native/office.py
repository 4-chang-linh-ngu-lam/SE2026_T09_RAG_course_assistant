"""Compatibility facade for Level-0 Office and text-like extraction backends."""

from __future__ import annotations

from pathlib import Path

from idp.backends.native.registry import default_native_parser_registry
from idp.backends.native.spreadsheets_slides import csv_pages, pptx_pages, xlsx_pages
from idp.backends.native.text_formats import (
    _copy_asset,
    _HtmlCollector,
    _md_plain,
    _strip_html,
    decode_txt,
    email_pages,
    html_pages,
    md_pages,
    txt_pages,
)


def extract_office_pages(
    source: Path,
    file_kind: str,
    assets: Path,
    profile_name: str,
) -> tuple[list[dict], str, dict]:
    """Dispatch non-PDF native file types via the pluggable NativeParserRegistry."""
    result = default_native_parser_registry().parse(
        file_kind,
        source,
        assets,
        profile_name=profile_name,
    )
    return result.pages, result.source_type, dict(result.metadata)


__all__ = [
    "_HtmlCollector",
    "_copy_asset",
    "_md_plain",
    "_strip_html",
    "csv_pages",
    "decode_txt",
    "email_pages",
    "extract_office_pages",
    "html_pages",
    "md_pages",
    "pptx_pages",
    "txt_pages",
    "xlsx_pages",
]
