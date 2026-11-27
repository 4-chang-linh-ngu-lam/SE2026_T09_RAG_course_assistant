"""Pluggable native parser registry for Level-0 CPU document extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class NativeParseResult:
    pages: list[dict]
    source_type: str
    content_loss: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class NativeParser(Protocol):
    def __call__(
        self,
        source: Path,
        assets_dir: Path,
        *,
        profile_name: str = "general",
        options: dict[str, Any] | None = None,
    ) -> NativeParseResult: ...


class NativeParserRegistry:
    """Extensible mapping from validated file kind to CPU native parser."""

    def __init__(self) -> None:
        self._parsers: dict[str, NativeParser] = {}

    def register(self, file_kind: str, parser: NativeParser) -> None:
        key = file_kind.strip().lower()
        if not key:
            raise ValueError("file_kind must be a non-empty string")
        self._parsers[key] = parser

    def get(self, file_kind: str) -> NativeParser | None:
        return self._parsers.get(file_kind.strip().lower())

    def has(self, file_kind: str) -> bool:
        return file_kind.strip().lower() in self._parsers

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._parsers))

    def parse(
        self,
        file_kind: str,
        source: Path,
        assets_dir: Path,
        *,
        profile_name: str = "general",
        options: dict[str, Any] | None = None,
    ) -> NativeParseResult:
        parser = self.get(file_kind)
        if parser is None:
            from idp.input.validation import InputError

            raise InputError("UNSUPPORTED_FILE_TYPE", f"unsupported native file type: {file_kind}")
        return parser(source, assets_dir, profile_name=profile_name, options=options)


def _docx_parser(
    source: Path,
    assets_dir: Path,
    *,
    profile_name: str = "general",
    options: dict[str, Any] | None = None,
) -> NativeParseResult:
    del options
    from idp.backends.native.docx import extract_docx_pages
    from idp.input.validation import InputError
    from idp.processing.figure import classify_page

    try:
        pages, audit = extract_docx_pages(source, assets_dir)
    except RuntimeError as exc:
        raise InputError("DOCX_ENGINE_UNAVAILABLE", str(exc)) from exc

    out_tables = sum(
        sum(1 for b in p.get("blocks") or [] if b.get("block_type") == "Table")
        for p in pages
    )
    out_equations = sum(
        sum(len(b.get("latex") or []) for b in p.get("blocks") or [])
        for p in pages
    )
    out_media = sum(
        sum(len(b.get("asset_paths") or []) for b in p.get("blocks") or [])
        for p in pages
    )
    content_loss: dict[str, Any] = {
        "tables": max(0, int(audit.get("tables", 0)) - out_tables),
        "equations": max(0, int(audit.get("equations", 0)) - out_equations),
        "media": max(0, int(audit.get("media", 0)) - out_media),
        "unsupported_parts": sum(
            int(part.get("count", 0)) for part in audit.get("unsupported_parts", [])
        ),
    }
    for page in pages:
        page["profile"] = profile_name
        page["parser"] = "pandoc"
        page["source_audit"] = audit
        page["classification"] = classify_page(page["blocks"])
        page["processing_status"] = "ok"
        if audit.get("unsupported_parts"):
            review = page.setdefault("review", [])
            if not any(f.get("code") == "DOCX_UNSUPPORTED_PARTS" for f in review):
                review.append({
                    "page": page.get("page_id"),
                    "block_id": None,
                    "bbox": None,
                    "code": "DOCX_UNSUPPORTED_PARTS",
                    "severity": "warning",
                    "parts": audit["unsupported_parts"],
                })
    return NativeParseResult(pages=pages, source_type="docx", content_loss=content_loss)


def _make_office_parser(file_kind: str) -> NativeParser:
    def _parse(
        source: Path,
        assets_dir: Path,
        *,
        profile_name: str = "general",
        options: dict[str, Any] | None = None,
    ) -> NativeParseResult:
        del options
        from idp.backends.native.spreadsheets_slides import csv_pages, pptx_pages, xlsx_pages
        from idp.backends.native.text_formats import (
            decode_txt,
            email_pages,
            html_pages,
            md_pages,
            txt_pages,
        )
        from idp.processing.figure import classify_page

        if file_kind == "text":
            pages = txt_pages(source, assets_dir)
            text, encoding = decode_txt(source)
            source_type = "txt"
            metadata: dict[str, Any] = {"encoding": encoding, "chars": len(text)}
        else:
            handlers = {
                "markdown": (md_pages, "markdown"),
                "html": (html_pages, "html"),
                "csv": (csv_pages, "csv"),
                "xlsx": (xlsx_pages, "xlsx"),
                "pptx": (pptx_pages, "pptx"),
                "email": (email_pages, "email"),
            }
            fn, source_type = handlers[file_kind]
            pages = fn(source, assets_dir, profile_name)
            metadata = {}

        for page in pages:
            page["profile"] = profile_name
            page["parser"] = source_type
            page["classification"] = classify_page(page["blocks"])
            page["processing_status"] = "ok"
        return NativeParseResult(pages=pages, source_type=source_type, metadata=metadata)

    return _parse


def default_native_parser_registry() -> NativeParserRegistry:
    """Create a fresh registry pre-populated with all built-in CPU native parsers."""
    registry = NativeParserRegistry()
    registry.register("docx", _docx_parser)
    for kind in ("text", "markdown", "html", "csv", "xlsx", "pptx", "email"):
        registry.register(kind, _make_office_parser(kind))
    return registry
