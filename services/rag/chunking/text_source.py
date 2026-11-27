"""Small lossless Markdown/TXT adapter for testing chunking without ingestion.

Offsets refer to the supplied Unicode string. No OCR, correction, heading
prediction, HTTP requests or model calls occur here.

Block starts are recognized by one predicate at every line, both at the start
of a paragraph and while scanning one: a table, display formula or fence that
directly follows a prose line is its own block, not prose.
"""
from __future__ import annotations

import re

TEXT_SOURCE_VERSION = "idp-text-source-5"

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_QUOTE = re.compile(r"^ {0,3}>")
# Display math environments that a renderer shows as one block. Prose
# environments (itemize, tabular, figure) stay prose.
MATH_ENVIRONMENTS = ("equation", "align", "alignat", "gather", "multline", "flalign",
                     "eqnarray", "displaymath", "math", "split", "cases")
_ENV_BEGIN = re.compile(r"^ {0,3}\\begin\{(" + "|".join(MATH_ENVIRONMENTS) + r")(\*?)\}")
def is_display_line(line: str) -> bool:
    """One complete display formula alone on a line: `$$...$$` or `\\[...\\]`.

    `$$a$$ và $$b$$` is prose with two formulas, not one display line.
    """
    value = line.strip()
    if len(value) <= 4:
        return False
    if value.startswith("$$") and value.endswith("$$"):
        body = value[2:-2]
        return "$$" not in body and bool(body.strip())
    if value.startswith("\\[") and value.endswith("\\]"):
        body = value[2:-2]
        return "\\[" not in body and "\\]" not in body and bool(body.strip())
    return False


def _delimiter_row(line: str) -> bool:
    # A pipe is required: a bare dash line is a setext underline or thematic break.
    return ("|" in line and "-" in line
            and bool(re.fullmatch(r"[ \t|:\-]+\r?\n?", line)))


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

    def table_start(index):
        return (index + 1 < len(lines) and "|" in lines[index] and lines[index].strip()
                and _delimiter_row(lines[index + 1]))

    def math_end(start, is_closing):
        """Index of the closing line, or of the line where an unclosed formula stops.

        A display formula never spans a blank line, a heading or a fence. An
        unclosed opener (OCR/IDP damage) is isolated up to that boundary and
        flagged; the rest of the document is parsed normally. Nothing is added
        to or removed from the source.
        """
        j = start
        while j < len(lines):
            if is_closing(lines[j]):
                return j
            if (not lines[j].strip() or _FENCE.match(lines[j])
                    or re.match(r"^ {0,3}#{1,6}[ \t]+\S", lines[j])):
                return j
            j += 1
        return j

    def block_start(index):
        """True when line `index` opens a non-prose block (never for setext text)."""
        line = lines[index]
        return bool(_FENCE.match(line) or _QUOTE.match(line) or line.strip() in {"$$", r"\["}
                    or _ENV_BEGIN.match(line) or table_start(index)
                    or (format == "markdown" and re.match(r"^ {0,3}#{1,6}[ \t]+\S", line)))

    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if format == "markdown":
            fence = _FENCE.match(lines[i])
            if fence:
                close_re = re.compile(
                    r" {0,3}" + re.escape(fence[1][0]) + "{" + str(len(fence[1])) + r",}[ \t]*\r?\n?"
                )
                j = i + 1
                while j < len(lines) and not close_re.fullmatch(lines[j]):
                    j += 1
                if j < len(lines):
                    add(i, j + 1, "code", closed=True)
                    i = j + 1
                    continue
                # Unclosed fence (OCR/IDP damage): isolate up to the next blank line
                # or structural block start so the rest of the document parses normally.
                j = i + 1
                while j < len(lines):
                    if not lines[j].strip() or block_start(j):
                        break
                    j += 1
                add(i, j, "code", closed=False)
                i = j
                continue
            if lines[i].strip() in {"$$", r"\["}:
                closing = "$$" if lines[i].strip() == "$$" else r"\]"
                j = math_end(i + 1, lambda line: line.strip() == closing)
                closed = j < len(lines) and lines[j].strip() == closing
                add(i, j + 1 if closed else j, "math", closed=closed)
                i = j + 1 if closed else j
                continue
            environment = _ENV_BEGIN.match(lines[i])
            if environment:
                end_pattern = re.compile(r"\\end\{" + re.escape(environment[1] + environment[2]) + r"\}")
                j = i if end_pattern.search(lines[i]) else math_end(i + 1, end_pattern.search)
                closed = j < len(lines) and bool(end_pattern.search(lines[j]))
                add(i, j + 1 if closed else j, "math", closed=closed)
                i = j + 1 if closed else j
                continue
            if _QUOTE.match(lines[i]):
                j = i + 1
                while j < len(lines) and _QUOTE.match(lines[j]):
                    j += 1
                add(i, j, "quote")
                i = j
                continue
            # Preserve a table as an opaque source block; table policy is deferred.
            if table_start(i):
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
            if format == "markdown" and (block_start(j) or heading(j)):
                break
            j += 1
        # A paragraph made only of complete one-line display formulas is a
        # formula block. A display line inside prose stays in that paragraph.
        kind = ("math" if format == "markdown" and all(is_display_line(lines[k]) for k in range(i, j))
                else "text")
        add(i, j, kind, **({"closed": True} if kind == "math" else {}))
        i = j
    return blocks
