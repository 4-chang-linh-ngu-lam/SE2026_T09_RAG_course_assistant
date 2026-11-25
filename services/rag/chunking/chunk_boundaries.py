"""Explicit layout packets for greedy splitting, without semantic inference.

Only packets fitting their *complete* index input are protected. An oversized
list can split between items; an oversized quote remains readable prose. Hard
inline math/code protection is owned by chunking.split_text instead.
"""
from __future__ import annotations

import re

from .boundary_cost import _starts_dependent, candidate_points, quoted_spans
from .token_budget import contextualize

BOUNDARY_PACKETS_VERSION = "idp-boundary-packets-2"
_ITEM = re.compile(r"^(?P<indent>[ \t]{0,3})(?:[-+*–—]|\d{1,9}[.)]|[A-Da-d][.):：])[ \t]+\S")


def layout_packets(text):
    """Yield (start,end,kind) source intervals, not rewritten index text.

    Recognizes explicit quotes, contiguous Markdown quote blocks and top-level
    lists. Plain verse, coreference, and argument/evidence roles are not guessed.
    A blank followed by unindented prose closes a list. Wrapped item lines and
    indented continuations stay in their item.
    """
    packets = [(a, b, "quotation") for a, b in quoted_spans(text)]
    # A local explicit continuation can stay with its immediately preceding
    # sentence when both fit. This is a surface cue, not resolved coreference.
    points = candidate_points(text)
    for a, b, c in zip(points, points[1:], points[2:]):
        if text[a:b].strip() and _starts_dependent(text[b:c]):
            packets.append((a, c, "dependent_pair"))
    lines = text.splitlines(keepends=True)
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    def end(index):
        return offsets[index] + len(lines[index].rstrip())

    i = 0
    while i < len(lines):
        if re.match(r"^ {0,3}>", lines[i]):
            j = i + 1
            while j < len(lines) and re.match(r"^ {0,3}>", lines[j]):
                j += 1
            # Structured callouts/tasks can contain independent headings.
            if not any(re.match(r"^ {0,3}(?:>[ \t]*)+#{1,6}[ \t]+", line) for line in lines[i:j]):
                packets.append((offsets[i], end(j - 1), "quote_block"))
            i = j
            continue
        if not _ITEM.match(lines[i]):
            i += 1
            continue
        first, starts, j = i, [i], i + 1
        while j < len(lines):
            if _ITEM.match(lines[j]):
                starts.append(j)
            elif not lines[j].strip():
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k == len(lines) or not (_ITEM.match(lines[k]) or re.match(r"^[ \t]{2,}\S", lines[k])):
                    break
            elif re.match(r"^ {0,3}(?:>|#{1,6}[ \t]|`{3,}|~{3,}|\$\$[ \t]*$)", lines[j]):
                break
            j += 1
        last = j - 1
        while last > first and not lines[last].strip():
            last -= 1
        items = []
        for k, start in enumerate(starts):
            stop = starts[k + 1] - 1 if k + 1 < len(starts) else last
            while stop > start and not lines[stop].strip():
                stop -= 1
            items.append((offsets[start], end(stop)))
        packets.extend((a, b, "list_item") for a, b in items)
        if len(items) > 1:
            packets.append((items[0][0], items[-1][1], "list"))
        # Bind an explicit colon introduction to the list, or at least its
        # first item if the full packet exceeds the budget.
        prefix = text[:offsets[first]].rstrip()
        if prefix.endswith((":", "：")):
            paragraph_start = prefix.rfind("\n\n") + 2 if "\n\n" in prefix else 0
            # Also handle CRLF/whitespace-only paragraph separators.
            separators = list(re.finditer(r"\r?\n[ \t]*\r?\n", prefix))
            if separators:
                paragraph_start = separators[-1].end()
            packets.append((paragraph_start, items[-1][1], "introduced_list"))
            packets.append((paragraph_start, items[0][1], "introduced_first_item"))
        i = max(j, i + 1)
    return sorted(set(packets))


def fitting_layout_ranges(text, path, counter, limit, *, hard_ranges=()):
    """Protect the largest fitting packets without creating oversized unions.

    Layout protection is softer than literal math/code protection. Overlapping
    candidates are accepted only when their union and any hard atoms still fit.
    No newly held content is introduced by this helper.
    """
    selected = []
    candidates = sorted({(a, b) for a, b, _ in layout_packets(text)}, key=lambda r: (-(r[1] - r[0]), r))
    for a, b in candidates:
        # Expand to the connected component of overlapping protected intervals;
        # otherwise a fitting quote crossing a formula could create a held atom.
        changed = True
        while changed:
            changed = False
            for x, y in [*hard_ranges, *selected]:
                if x < b and a < y and (x < a or y > b):
                    a, b = min(a, x), max(b, y)
                    changed = True
        if any(x <= a and b <= y for x, y in selected):
            continue
        if counter.count(contextualize(path, text[a:b])) <= limit:
            selected = [(x, y) for x, y in selected if not (x < b and a < y)]
            selected.append((a, b))
    return sorted(selected)
