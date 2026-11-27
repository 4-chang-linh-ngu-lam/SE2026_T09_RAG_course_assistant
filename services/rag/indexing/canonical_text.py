"""Canonical JSON to Markdown projection and character-span page/section locator."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from collections.abc import Sequence
from typing import Any

_SKIPPED_BLOCK_TYPES = frozenset({
    "PageHeader",
    "PageFooter",
    "PageNumber",
    "Picture",
    "PictureGroup",
    "Diagram",
    "Chart",
})
_HEADING_BLOCK_TYPES = frozenset({"Heading", "SectionHeader", "Title"})


def _page_number(page: dict[str, Any], fallback: int) -> int:
    for key in ("page_number", "page_id"):
        value = page.get(key)
        if type(value) is int and value >= 1:
            return value
    return fallback


_FORMULA_BLOCK_TYPES = frozenset({"Equation", "Formula"})
_TABLE_BLOCK_TYPES = frozenset({"Table"})
_GFM_DELIMITER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_MATH_ENVIRONMENTS = (
    "equation",
    "align",
    "alignat",
    "gather",
    "multline",
    "flalign",
    "eqnarray",
    "displaymath",
    "math",
    "split",
    "cases",
)
_MATH_ENV = re.compile(
    r"^\\begin\{(?P<env>" + "|".join(_MATH_ENVIRONMENTS) + r")(?P<star>\*?)\}"
    r"([\s\S]+?)\\end\{(?P=env)(?P=star)\}$"
)
_BLANK_LINE = re.compile(r"\n[ \t]*\r?\n")


class _HtmlTable(HTMLParser):
    """Rows of a single plain HTML table; any span or nested table is unsupported."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.cell: list[str] | None = None
        self.tables = 0
        self.unsupported = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables += 1
        elif tag == "tr":
            self.rows.append([])
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")
        elif tag in {"td", "th"}:
            spans = {name: value for name, value in attrs if name in {"colspan", "rowspan"}}
            if any((value or "1").strip() != "1" for value in spans.values()) or not self.rows:
                self.unsupported = True
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
            self.cell = None

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)


def _html_table_markdown(html: str) -> str:
    """A GFM pipe table for a plain HTML table, or "" to keep the block's text."""
    parser = _HtmlTable()
    try:
        parser.feed(html)
        parser.close()
    except (AssertionError, ValueError):
        return ""
    rows = [row for row in parser.rows if row]
    if (parser.unsupported or parser.tables != 1 or len(rows) < 2
            or len({len(row) for row in rows}) != 1 or not any(rows[0])):
        return ""
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")
    return "\n".join(lines)


def _structured_markdown(block: dict[str, Any]) -> str:
    """The block's Markdown when it keeps structure that `text` flattens.

    Display formulas keep their `$$` delimiters (chunking then treats them as
    atoms) and tables keep their rows (row-split under a repeated header).
    Anything else, or a structure that does not parse, keeps `text`.
    """
    markdown = block.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return ""
    value = markdown.strip()
    block_type = block.get("type") or block.get("block_type")
    if block_type in _FORMULA_BLOCK_TYPES:
        for left, right in (("$$", "$$"), ("\\[", "\\]")):
            if (value.startswith(left) and value.endswith(right) and len(value) > 4
                    and value[2:-2].strip() and left not in value[2:-2] and right not in value[2:-2]
                    and not _BLANK_LINE.search(value)):
                return value
        env_match = _MATH_ENV.fullmatch(value)
        if env_match:
            closing = f"\\end{{{env_match['env']}{env_match['star']}}}"
            body = env_match.group(3)
            if body.strip() and closing not in body and not _BLANK_LINE.search(value):
                return value
        return ""
    if block_type in _TABLE_BLOCK_TYPES:
        if value.lower().startswith("<table"):
            return _html_table_markdown(value)
        lines = value.splitlines()
        if len(lines) >= 3 and "|" in lines[0] and _GFM_DELIMITER.match(lines[1]):
            return value
    return ""


def _block_text(block: dict[str, Any]) -> str:
    if (
        not isinstance(block, dict)
        or block.get("excluded")
        or block.get("excluded_from_content")
        or block.get("held")
        or block.get("retrieval_eligible") is False
        or (block.get("type") or block.get("block_type")) in _SKIPPED_BLOCK_TYPES
    ):
        return ""
    structured = _structured_markdown(block)
    if structured:
        return structured
    raw = block.get("text") or block.get("markdown") or ""
    return raw.strip() if isinstance(raw, str) else ""


def _heading_level(block: dict[str, Any]) -> int | None:
    for key in ("heading_level", "level"):
        value = block.get(key)
        if type(value) is int and 1 <= value <= 6:
            return value
    if (block.get("type") or block.get("block_type")) == "Title":
        return 1
    return None


def _block_meta(block: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None
    meta: dict[str, Any] = {}
    block_id = block.get("block_id")
    if isinstance(block_id, str) and block_id:
        meta["block_id"] = block_id
    bbox = block.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        meta["bbox"] = list(bbox)
    return meta or None


def _format_heading(text: str, level: int | None = None) -> tuple[str, str | None]:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if collapsed.startswith("#"):
        title = collapsed.lstrip("#").strip()
        if title:
            return collapsed, title
        return "", None
    depth = level if type(level) is int and 1 <= level <= 6 else 2
    return f"{'#' * depth} {collapsed}", collapsed


def _format_block(block: dict[str, Any]) -> tuple[str, str | None]:
    text = _block_text(block)
    if not text:
        return "", None
    block_type = block.get("type") or block.get("block_type")
    if block_type in _HEADING_BLOCK_TYPES:
        return _format_heading(text, _heading_level(block))
    return text, None


# A heading held only because its OCR read is unverified or low-scored still
# names the section its eligible body belongs to. Without it a formula under
# "2. CÁC TÍNH CHẤT CỦA PHÉP NHÂN VECTƠ VỚI MỘT SỐ" is indexed as bare LaTeX
# that no Vietnamese question can reach. It is kept only as a Markdown heading,
# which chunking stores as section metadata, never as quotable body text.
_CONTEXT_HEADING_REASONS = frozenset({
    "LOW_CONFIDENCE",
    "UNVERIFIED_SOURCE",
    "OCR_REGION_DISAGREEMENT",
    "STRUCTURED_BUDGET_EXHAUSTED",
})
_CONTEXT_HEADING_MAX_CHARS = 160


def _context_heading(block: dict[str, Any]) -> str:
    if (
        not isinstance(block, dict)
        or block.get("held") is not True
        or block.get("excluded")
        or block.get("excluded_from_content")
        or block.get("retrieval_eligible") is False
        or (block.get("type") or block.get("block_type")) not in _HEADING_BLOCK_TYPES
    ):
        return ""
    reasons = block.get("hold_reasons")
    if not isinstance(reasons, list) or not reasons or not set(reasons) <= _CONTEXT_HEADING_REASONS:
        return ""
    raw = block.get("text")
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or len(text) > _CONTEXT_HEADING_MAX_CHARS or "\\" in text or "$" in text:
        return ""
    return text if any(c.isalpha() for c in text) else ""


def _body_follows(blocks: list[Any], start: int) -> bool:
    """True if eligible body text follows before the next heading block."""
    for block in blocks[start:]:
        if isinstance(block, dict) and (block.get("type") or block.get("block_type")) in _HEADING_BLOCK_TYPES:
            return False
        if _block_text(block):
            return True
    return False


def _extract_pages(
    artifact: dict[str, Any],
) -> list[tuple[int, list[tuple[str, str | None, dict[str, Any] | None]]]]:
    if not isinstance(artifact, dict):
        return []
    reader_pages = artifact.get("reader_pages")
    if isinstance(reader_pages, list):
        extracted: list[tuple[int, list[tuple[str, str | None, dict[str, Any] | None]]]] = []
        for idx, page in enumerate(reader_pages, 1):
            if not isinstance(page, dict):
                continue
            num = _page_number(page, idx)
            entries = [
                (clean, None, None)
                for p in (page.get("paragraphs") or [])
                if isinstance(p, str) and (clean := p.strip())
            ]
            if entries:
                extracted.append((num, entries))
        return extracted

    pages = artifact.get("pages")
    if not isinstance(pages, list):
        return []
    extracted = []
    for idx, page in enumerate(pages, 1):
        if not isinstance(page, dict):
            continue
        num = _page_number(page, idx)
        entries = []
        blocks = page.get("blocks") or []
        for index, block in enumerate(blocks):
            formatted, heading = _format_block(block)
            if not formatted and (context := _context_heading(block)) and _body_follows(blocks, index + 1):
                formatted, heading = _format_heading(context, _heading_level(block))
            if formatted:
                entries.append((formatted, heading, _block_meta(block)))
        if entries:
            extracted.append((num, entries))
    return extracted


def canonical_to_markdown(artifact: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Project Canonical JSON into Markdown plus exact per-page/heading character offsets."""
    parts: list[str] = []
    page_ranges: list[dict[str, Any]] = []
    cursor = 0
    for page_num, entries in _extract_pages(artifact):
        if not entries:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        page_start = cursor
        sections: list[dict[str, Any]] = []
        block_entries: list[dict[str, Any]] = []
        for idx, (formatted, heading_title, block_meta) in enumerate(entries):
            if idx > 0:
                parts.append("\n\n")
                cursor += 2
            block_start = cursor
            parts.append(formatted)
            cursor += len(formatted)
            block_end = cursor
            if heading_title:
                sections.append({"start": block_start, "end": block_end, "title": heading_title})
            if block_meta:
                block_entries.append({"start": block_start, "end": block_end, **block_meta})
        page_ranges.append(
            {
                "page": page_num,
                "start": page_start,
                "end": cursor,
                "sections": sections,
                "blocks": block_entries,
            }
        )
    return "".join(parts), page_ranges


def locate_spans_in_canonical(
    artifact: dict[str, Any],
    spans: Sequence[tuple[int, int]],
    *,
    file_type: str = "PDF",
    include_block: bool = False,
) -> dict[str, Any] | None:
    """Resolve character spans in projected Markdown back to page/slide and section."""
    if not spans:
        return None
    _, page_ranges = canonical_to_markdown(artifact)
    if not page_ranges:
        return None
    first = spans[0]
    if len(first) != 2:
        return None
    anchor, span_end = first[0], first[1]
    if type(anchor) is not int or type(span_end) is not int or anchor < 0 or span_end <= anchor:
        return None

    matched: dict[str, Any] | None = None
    for entry in page_ranges:
        if entry["start"] <= anchor < entry["end"] or (
            anchor == entry["end"] and span_end == entry["end"]
        ):
            matched = entry
            break
    if matched is None:
        for entry in page_ranges:
            if max(entry["start"], anchor) < min(entry["end"], span_end):
                matched = entry
                break
    if matched is None and page_ranges[0]["start"] <= anchor <= page_ranges[-1]["end"]:
        for entry in page_ranges:
            if entry["start"] <= anchor:
                matched = entry
            else:
                break
    if matched is None:
        return None

    section: str | None = None
    for entry in page_ranges:
        for sec in entry["sections"]:
            if sec["start"] <= anchor:
                section = sec["title"]

    key = "slide" if file_type == "PPTX" else "page"
    location: dict[str, Any] = {key: matched["page"]}
    if section:
        location["section"] = section
    if include_block:
        matched_blocks = matched.get("blocks") or []
        block_match = next(
            (
                b
                for b in matched_blocks
                if b["start"] <= anchor < b["end"] or (anchor == b["end"] and span_end == b["end"])
            ),
            None,
        )
        if block_match is None:
            block_match = next(
                (b for b in matched_blocks if max(b["start"], anchor) < min(b["end"], span_end)),
                None,
            )
        if block_match is not None:
            if "block_id" in block_match:
                location["block_id"] = block_match["block_id"]
            if "bbox" in block_match:
                location["bbox"] = block_match["bbox"]
    return location


__all__ = ["canonical_to_markdown", "locate_spans_in_canonical"]
