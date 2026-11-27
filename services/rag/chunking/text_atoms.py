"""Deterministic inspection of Markdown table and display-math text atoms.

This module preserves source text and offsets. It does not repair Markdown or
interpret the contents of cells or equations.
"""
from __future__ import annotations

import re


_DELIMITER_CELL = re.compile(r":?-{3,}:?")


def _cells(line: str) -> list[str]:
    """Split one Markdown row on pipes outside matched code and escapes."""
    body = line.rstrip("\r\n")
    separators: list[int] = []
    i = 0
    while i < len(body):
        if body[i] == "`":
            backslashes = 0
            k = i - 1
            while k >= 0 and body[k] == "\\":
                backslashes += 1
                k -= 1
            if backslashes % 2:
                i += 1
                continue
            j = i + 1
            while j < len(body) and body[j] == "`":
                j += 1
            run_length = j - i
            close = -1
            scan = j
            while scan < len(body):
                found = body.find("`", scan)
                if found < 0:
                    break
                run_end = found + 1
                while run_end < len(body) and body[run_end] == "`":
                    run_end += 1
                escaped = 0
                prev = found - 1
                while prev >= 0 and body[prev] == "\\":
                    escaped += 1
                    prev -= 1
                if escaped % 2 == 0 and run_end - found == run_length:
                    close = found
                    break
                scan = run_end
            if close >= 0:
                i = close + run_length
                continue
            i = j
            continue
        if body[i] == "|":
            backslashes = 0
            k = i - 1
            while k >= 0 and body[k] == "\\":
                backslashes += 1
                k -= 1
            if backslashes % 2 == 0:
                separators.append(i)
        i += 1

    starts = [0, *(p + 1 for p in separators)]
    ends = [*separators, len(body)]
    cells = [body[a:b].strip() for a, b in zip(starts, ends)]
    if body.lstrip().startswith("|") and cells and not cells[0]:
        cells.pop(0)
    if body.rstrip().endswith("|") and cells and not cells[-1]:
        cells.pop()
    return cells


def inspect_table(text: str) -> dict:
    """Inspect a pipe table without changing it.

    `rows` contains contiguous source intervals for data rows, including their
    original line endings. The header and delimiter lines are excluded. For a
    valid table, intervals partition `[header_end, len(text))` exactly.
    """
    result = {"valid": False, "reason": None, "header_end": None, "rows": [], "columns": 0}
    lines = text.splitlines(keepends=True)
    if len(lines) < 3:
        result["reason"] = "table requires a header, delimiter, and data row"
        return result
    header, delimiter = _cells(lines[0]), _cells(lines[1])
    if not header or not any(header):
        result["reason"] = "malformed header"
        return result
    if len(delimiter) != len(header) or not all(_DELIMITER_CELL.fullmatch(cell) for cell in delimiter):
        result["reason"] = "malformed delimiter row"
        return result

    header_end = len(lines[0]) + len(lines[1])
    result["header_end"] = header_end
    row_intervals = []
    offset = header_end
    for line in lines[2:]:
        cells = _cells(line)
        if not line.rstrip("\r\n").strip() or not cells:
            result["reason"] = "empty data row"
            return result
        if len(cells) != len(header):
            result["reason"] = "ragged data row"
            return result
        next_offset = offset + len(line)
        row_intervals.append((offset, next_offset))
        offset = next_offset
    if offset != len(text):
        result["reason"] = "unparsed table suffix"
        return result
    result.update(valid=True, reason=None, rows=row_intervals, columns=len(header))
    return result


def math_closed(text: str) -> bool:
    """Return whether text is a closed, nonempty display-math block.

    Accepted: multi-line `$$`/`\\[...\\]`, one or more one-line display
    formulas, and a `\\begin{env}...\\end{env}` math environment.
    """
    from .text_source import MATH_ENVIRONMENTS, is_display_line

    lines = text.splitlines()
    if not lines:
        return False
    if all(is_display_line(line) for line in lines):
        return True
    begin = re.match(r"^\s*\\begin\{(" + "|".join(MATH_ENVIRONMENTS) + r")(\*?)\}", lines[0])
    if begin:
        closing = "\\end{" + begin[1] + begin[2] + "}"
        payload = text.strip()[len(begin[0].strip()):]
        return text.rstrip().endswith(closing) and bool(payload[:-len(closing)].strip())
    first, last = lines[0].strip(), lines[-1].strip()
    if first == "$$":
        payload = "\n".join(lines[1:-1]) if last == "$$" else ""
        return last == "$$" and bool(payload.strip())
    if first == "\\[":
        payload = "\n".join(lines[1:-1]) if last == "\\]" else ""
        return last == "\\]" and bool(payload.strip())
    if first.startswith("$$") and first.endswith("$$") and len(first) > 4 and len(lines) == 1:
        return bool(first[2:-2].strip())
    return False
