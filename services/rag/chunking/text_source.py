"""Small lossless Markdown/TXT adapter for testing chunking without ingestion.

Offsets refer to the supplied Unicode string. No OCR, correction, heading
prediction, HTTP requests or model calls occur here.
"""
from __future__ import annotations

import re

TEXT_SOURCE_VERSION = "idp-text-source-2"


def parse_text(text: str, *, format: str = "markdown") -> list[dict]:
    if format not in {"markdown", "text"}:
        raise ValueError("format must be markdown or text")
    lines = text.splitlines(keepends=True)
    offsets, cursor = [], 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    blocks = []

    def add(first, last, kind="text", **extra):
        start = offsets[first]
        end = offsets[last] if last < len(lines) else len(text)
        value = text[start:end]
        start += len(value) - len(value.lstrip())
        end -= len(value) - len(value.rstrip())
        if start < end:
            blocks.append({"id": f"b{len(blocks):05d}", "kind": kind,
                "source_start": start, "source_end": end, "text": text[start:end], **extra})

    def heading(index):
        match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", lines[index])
        if match:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", match[2]).strip()
            return 1, len(match[1]), title
        if index + 1 < len(lines) and lines[index].strip():
            underline = re.fullmatch(r" {0,3}(=+|-+)[ \t]*\r?\n?", lines[index + 1])
            # A list item (including a bare bullet) followed by dashes remains
            # a list/thematic break, not a setext heading. Do not manufacture a
            # section from punctuation inside textbook exercises.
            list_item = re.match(r"^ {0,3}(?:[-+*](?:\s|$)|\d{1,9}[.)](?:\s|$))", lines[index])
            if underline and not list_item:
                return 2, 1 if underline[1][0] == "=" else 2, lines[index].strip()
        return None

    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if format == "markdown":
            fence = re.match(r"^ {0,3}(`{3,}|~{3,})", lines[i])
            if fence:
                j = i + 1
                while j < len(lines) and not re.fullmatch(
                        r" {0,3}" + re.escape(fence[1][0]) + "{" + str(len(fence[1])) + r",}[ \t]*\r?\n?", lines[j]):
                    j += 1
                closed = j < len(lines)
                add(i, min(j + 1, len(lines)), "code", closed=closed)
                i = min(j + 1, len(lines))
                continue
            if lines[i].strip() in {"$$", r"\["}:
                closing = "$$" if lines[i].strip() == "$$" else r"\]"
                j = i + 1
                while j < len(lines) and lines[j].strip() != closing:
                    j += 1
                add(i, min(j + 1, len(lines)), "math", closed=j < len(lines))
                i = min(j + 1, len(lines))
                continue
            if re.match(r"^ {0,3}>", lines[i]):
                j = i + 1
                while j < len(lines) and re.match(r"^ {0,3}>", lines[j]):
                    j += 1
                add(i, j, "quote")
                i = j
                continue
            # Preserve a table as an opaque source block; table policy is deferred.
            if i + 1 < len(lines) and "|" in lines[i] and re.fullmatch(
                    r"[ \t|:\-]+\r?\n?", lines[i + 1]) and "-" in lines[i + 1]:
                j = i + 2
                while j < len(lines) and "|" in lines[j] and lines[j].strip():
                    j += 1
                add(i, j, "table")
                i = j
                continue
            found = heading(i)
            if found:
                width, level, title = found
                add(i, i + width, "heading", heading_level=level, title=title)
                i += width
                continue
        j = i + 1
        while j < len(lines) and lines[j].strip():
            if format == "markdown" and (heading(j) or re.match(r"^ {0,3}(?:`{3,}|~{3,}|>|\$\$\s*$|\\\[\s*$)", lines[j])):
                break
            j += 1
        add(i, j)
        i = j
    return blocks
