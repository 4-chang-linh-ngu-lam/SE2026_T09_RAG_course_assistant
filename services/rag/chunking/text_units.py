"""Conservative educational units over exact text-source fragments.

The author heading tree stays intact. Labels establish task boundaries, not
subject knowledge; no model, correction or inferred answer is used.
"""
from __future__ import annotations

import re
import unicodedata

TEXT_UNITS_VERSION = "idp-text-units-1"
_NUMBER = r"\d+(?:\.\d+)*"
_NAMED = re.compile(
    rf"^(?P<name>bài tập|bài|câu hỏi|câu|ví dụ|hoạt động|luyện tập|vận dụng|"
    rf"exercise|problem|question|example|activity|try it)\s+(?P<number>{_NUMBER})"
    r"(?P<tail>[.):：\-–—]?)(?=\s|$)", re.I)
_PRACTICE = re.compile(
    r"^(?:\d+[.)]?\s+|[ivxlcdm]+[.)]\s+)?(?:luyện tập|bài tập|thực hành|"
    r"vận dụng|câu hỏi(?: và bài tập)?|exercises?|practice|problems?|review questions?)"
    r"(?:\s*[:：\-–—].*|\s+và.*|\s*)$", re.I)
_SOLUTION = re.compile(r"^(?:lời giải|hướng dẫn giải|giải|đáp án|solution|answer|explanation)\b", re.I)


def _visible(line):
    """Classification only: never use this normalization for evidence/offsets."""
    value = unicodedata.normalize("NFC", line).strip()
    value = re.sub(r"^(?:>\s*)+", "", value)
    value = re.sub(r"^#{1,6}\s+", "", value)
    value = re.sub(r"[*_]", "", value).strip()
    return value


def _named(value, *, practice, heading=False):
    match = _NAMED.match(value)
    if not match:
        return None
    name = match["name"].casefold()
    # 'Bài 1' commonly names an entire lesson. Only an explicit practice
    # context, or a punctuated body task label, disambiguates this cue.
    if name == "bài" and not practice and (heading or not match["tail"]):
        return None
    kind = ("example" if name in {"ví dụ", "example"} else
            "activity" if name in {"hoạt động", "activity"} else "exercise")
    return {"unit_kind": kind, "unit_label": f"{match['name']} {match['number']}",
            "unit_basis": "explicit_numbered_label"}


def plan_units(blocks, nodes, assignments):
    """Return deterministic parent plans; fragments may partition one block.

    Named tasks may own descendant sections (e.g. Solution). Unlabelled ordered
    lists split only inside a practice heading, outside a recognized solution.
    Opaque blocks stay separate, linked by the same unit anchor when applicable.
    """
    by_node = {n["id"]: n for n in nodes}
    heading_units, groups = {}, []
    current = active = None
    solution_mode = False

    def inherited(section):
        while section:
            if section in heading_units:
                return heading_units[section]
            section = by_node[section]["parent_id"]
        return None

    def descendant(section, ancestor):
        while section:
            if section == ancestor:
                return True
            section = by_node[section]["parent_id"]
        return False

    def make_meta(info, block, offset, section):
        return {**info, "unit_anchor": f"{block['id']}:{offset}", "section_id": section}

    def append(block, a, b, meta):
        nonlocal current
        if a == b:
            return
        section = meta["section_id"] if meta else assignments[block["id"]]
        atomic = block["kind"] not in {"text", "quote"}
        identity = meta or {"unit_kind": "prose", "unit_label": "", "unit_basis": "section_prose",
                            "unit_anchor": "", "section_id": section}
        if (current is None or atomic or current["atomic"]
                or current["section_id"] != section
                or any(current[k] != identity[k] for k in ("unit_kind", "unit_anchor"))):
            current = {**identity, "atomic": atomic,
                       "kind": block["kind"] if atomic else "text", "fragments": []}
            groups.append(current)
        current["fragments"].append({"block_id": block["id"],
            "source_start": block["source_start"] + a, "source_end": block["source_start"] + b,
            "section_id": assignments[block["id"]]})

    for block in blocks:
        section = assignments[block["id"]]
        path = by_node[section]["path"]
        practice = any(_PRACTICE.fullmatch(_visible(p)) for p in path)
        if block["kind"] == "heading":
            title = _visible(block["title"])
            info = _named(title, practice=practice, heading=True)
            if info:
                active = make_meta(info, block, 0, section)
                heading_units[section] = active
            elif active and _SOLUTION.match(title) and descendant(section, active["section_id"]):
                # Explicit solution descendant of a body-labelled task.
                heading_units[section] = active
            else:
                active = inherited(section)
            if current and (not active or current["unit_anchor"] != active["unit_anchor"]):
                current = None
            solution_mode = any(_SOLUTION.match(_visible(p)) for p in path)
            continue

        if block["kind"] not in {"text", "quote"}:
            append(block, 0, len(block["text"]), active)
            continue

        quoted = block["kind"] == "quote"
        detached_quote = quoted and any(
            _named(_visible(line), practice=practice)
            or (re.match(r"^(?:>\s*)+#{1,6}\s+", line)
                and not (active and _SOLUTION.match(_visible(line))))
            for line in block["text"].splitlines())
        if detached_quote:
            # A callout closes at the end of its quote block. Never absorb the
            # following ordinary paragraph into its task/example.
            saved_active = active
            saved_solution_mode = solution_mode
            active = None
            current = None
        cursor, part_start = 0, 0
        for line in block["text"].splitlines(keepends=True):
            value = _visible(line)
            info = _named(value, practice=practice)
            bare = re.match(r"^(\d+)[.)]\s+\S", value)
            top_level = not re.match(r"^[ \t]{2,}\S", line)
            # Inside a named task, numbered substeps are not new exercises.
            if (not info and bare and practice and not solution_mode and top_level
                    and (not active or active["unit_basis"] == "numbered_practice_item")):
                info = {"unit_kind": "exercise", "unit_label": bare[1],
                        "unit_basis": "numbered_practice_item"}
            if info:
                if cursor > part_start:
                    append(block, part_start, cursor, active)
                active = make_meta(info, block, cursor, section)
                part_start = cursor
                solution_mode = False
            elif _SOLUTION.match(value):
                solution_mode = True
            elif quoted and re.match(r"^(?:>\s*)+#{1,6}\s+", line) and not active:
                active = make_meta({"unit_kind": "callout", "unit_label": value,
                                    "unit_basis": "quoted_heading"}, block, cursor, section)
            cursor += len(line)
        append(block, part_start, len(block["text"]), active)
        if detached_quote:
            active = saved_active
            solution_mode = saved_solution_mode
            current = None
    return groups
