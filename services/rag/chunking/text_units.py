"""Conservative educational units over exact text-source fragments.

The author heading tree stays intact. Labels establish unit boundaries, not
subject knowledge; no model, correction or inferred answer is used.

A logical parent may hold several source blocks. A closed display formula or
code fence is atomic (it is never cut), but it is not a parent of its own: it
stays with the step, example or definition it belongs to. Tables keep their own
parent so rows can be split under a repeated header; they share the unit ID.
"""
from __future__ import annotations

import re
import unicodedata

from .text_atoms import math_closed

TEXT_UNITS_VERSION = "idp-text-units-4"
_NUMBER = r"\d+(?:\.\d+)*"
_NAMED = re.compile(
    rf"^(?P<name>bài tập|bài|câu hỏi|câu|ví dụ|hoạt động|luyện tập|vận dụng|"
    rf"exercise|problem|question|example|activity|try it)\s+(?P<number>{_NUMBER})"
    r"(?P<tail>[.):：\-–—]?)(?=\s|$)", re.I)
# Statement labels and the subtype each explicit label names. "strong" labels
# always open a new unit, so a definition after an example's solution is not
# absorbed by that example. "weak" ones (notes, remarks, methods) open a unit
# only outside an active task, because inside one they usually comment on it.
_STRONG_SUBTYPES = {
    "định nghĩa": "definition", "khái niệm": "definition", "definition": "definition",
    "định lý": "theorem", "định lí": "theorem", "theorem": "theorem",
    "tính chất": "property", "property": "property",
    "hệ quả": "corollary", "corollary": "corollary",
    "bổ đề": "lemma", "lemma": "lemma",
    "quy tắc": "rule", "qui tắc": "rule", "rule": "rule",
    "ghi nhớ": "summary", "tiên đề": "axiom", "axiom": "axiom",
    "định luật": "law", "law": "law",
    "nguyên lý": "principle", "nguyên lí": "principle", "principle": "principle",
    "proposition": "proposition",
}
_WEAK_SUBTYPES = {
    "chú ý": "note", "lưu ý": "note", "note": "note",
    "nhận xét": "remark", "remark": "remark",
    "kết luận": "conclusion",
    "phương pháp giải": "procedure", "phương pháp": "procedure", "cách giải": "procedure",
    "các bước giải": "procedure", "method": "procedure",
}
_SUBTYPES = {**_STRONG_SUBTYPES, **_WEAK_SUBTYPES}
_STATEMENT = re.compile(
    "^(?P<name>" + "|".join(sorted(_SUBTYPES, key=len, reverse=True)) + rf")(?:\s+(?P<number>{_NUMBER}))?"
    r"(?P<tail>\s*[.:：\-–—)](?=\s|$)|\s*$)", re.I)
# A table caption ("Bảng 2. Khối lượng mol", "Table 1:") ties the table to the
# prose that introduces or explains it. It needs a number and punctuation.
_CAPTION = re.compile(rf"^(?P<name>bảng|table)\s+(?P<number>{_NUMBER})\s*[.:：\-–—)](?=\s|$)", re.I)
_PRACTICE = re.compile(
    r"^(?:\d+[.)]?\s+|[ivxlcdm]+[.)]\s+)?(?:luyện tập|bài tập|thực hành|"
    r"vận dụng|câu hỏi(?: và bài tập)?|exercises?|practice|problems?|review questions?)"
    r"(?:\s*[:：\-–—].*|\s+và.*|\s*)$", re.I)
# A solution is a label ("Lời giải:", "Giải.", a "Lời giải" heading), never an
# instruction such as "Giải các phương trình sau:" that introduces exercises.
_SOLUTION = re.compile(
    r"^(?:lời giải|hướng dẫn giải|giải|đáp án|đáp số|solution|answer|explanation)"
    r"(?:\s*\d+(?:\.\d+)*)?(?:\s*[.:：\-–—]|\s*$)", re.I)
_TASKS = {"exercise", "example", "activity"}
_UNIT_KEYS = ("unit_kind", "unit_subtype", "unit_label", "unit_basis")


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
    return {"unit_kind": kind, "unit_subtype": "", "unit_label": f"{match['name']} {match['number']}",
            "unit_basis": "explicit_numbered_label"}


def _statement(value, *, heading=False):
    """Definition/theorem/note/caption labels. Bare words in a sentence never match.

    A label is capitalized (a lowercase "mệnh đề." continues a wrapped
    sentence). A body line needs punctuation after the label ("Định nghĩa.",
    "Định lý 2:"), or an unnumbered box title alone on its line ("Chú ý"); a
    numbered label alone ("Định lý 6") is an index/TOC entry with a page. A
    heading needs a number, since its title already names its section.
    ("Mệnh đề" is not a label: it is also the topic of a logic chapter.)
    """
    if not value[:1].isupper():
        return None
    caption = _CAPTION.match(value)
    if caption and not heading:
        return {"unit_kind": "caption", "unit_subtype": "table",
                "unit_label": f"{caption['name']} {caption['number']}",
                "unit_basis": "explicit_caption_label", "weak": True, "numbered": True}
    match = _STATEMENT.match(value)
    if not match:
        return None
    alone = not match["tail"].strip()
    if alone and (bool(match["number"]) != heading):
        return None
    name = match["name"]
    subtype = _SUBTYPES[name.casefold()]
    weak = name.casefold() in _WEAK_SUBTYPES
    label = f"{name} {match['number']}" if match["number"] else name
    return {"unit_kind": "remark" if weak else "statement", "unit_subtype": subtype,
            "unit_label": label, "unit_basis": "explicit_statement_label",
            "weak": weak, "numbered": bool(match["number"])}


def _successor(previous, label):
    """`2` follows `1`, `1.3` follows `1.2`: the next item at the same depth."""
    if previous is None:
        return False
    a, b = previous.split("."), label.split(".")
    return len(a) == len(b) and a[:-1] == b[:-1] and int(b[-1]) == int(a[-1]) + 1


def _mergeable(block):
    """A closed formula/code block may live inside a prose logical parent."""
    if block["kind"] == "math":
        return block.get("closed", True) and math_closed(block["text"])
    return block["kind"] == "code" and block.get("closed", True)


def plan_units(blocks, nodes, assignments):
    """Return deterministic parent plans; fragments may partition one block.

    Named tasks may own descendant sections (e.g. Solution). Unlabelled ordered
    lists split only inside a practice heading. Inside a recognized solution a
    bare number opens the next exercise when it is the next task number and not
    the next step of the solution's own numbered list. When it is both, the
    boundary is ambiguous: the line stays in the solution and the parent is
    marked `unit_boundary_ambiguous` instead of claiming a certain structure.
    """
    by_node = {n["id"]: n for n in nodes}
    heading_units, groups = {}, []
    current = active = None
    # solution_last: last number of the current solution's own numbered steps.
    solution_mode, solution_last = False, None
    # Numbers kept inside a solution although they are also the next task
    # number. A later exercise with that number resolves the doubt.
    ambiguous = set()

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
        meta = {k: info[k] for k in _UNIT_KEYS}
        return {**meta, "unit_anchor": f"{block['id']}:{offset}", "section_id": section}

    def opens_statement(info, *, paragraph_start):
        if not info:
            return False
        if not info["weak"] or not active or active["unit_kind"] not in _TASKS:
            return True
        # An unnumbered method header that starts a paragraph after a task's
        # solution is a general method, not that solution ("Cách giải 2" is).
        return (info["unit_subtype"] == "procedure" and not info["numbered"]
                and paragraph_start and solution_mode)

    def append(block, a, b, meta):
        nonlocal current, ambiguous
        if a == b:
            return
        section = meta["section_id"] if meta else assignments[block["id"]]
        merge = block["kind"] in {"math", "code"} and _mergeable(block)
        atomic = block["kind"] not in {"text", "quote"} and not merge
        identity = meta or {"unit_kind": "prose", "unit_subtype": "", "unit_label": "",
                            "unit_basis": "section_prose", "unit_anchor": "", "section_id": section}
        if (current is None or atomic or current["atomic"]
                or current["section_id"] != section
                or any(current[k] != identity[k] for k in ("unit_kind", "unit_anchor"))):
            current = {**identity, "atomic": atomic, "unit_boundary_ambiguous": False, "_doubt": set(),
                       "kind": block["kind"] if atomic else "text", "fragments": []}
            groups.append(current)
        current["_doubt"] |= ambiguous
        ambiguous = set()
        current["fragments"].append({"block_id": block["id"],
            "source_start": block["source_start"] + a, "source_end": block["source_start"] + b,
            "section_id": assignments[block["id"]]})

    for block in blocks:
        section = assignments[block["id"]]
        path = by_node[section]["path"]
        practice = any(_PRACTICE.fullmatch(_visible(p)) for p in path)
        if block["kind"] == "heading":
            title = _visible(block["title"])
            info = _named(title, practice=practice, heading=True) or _statement(title, heading=True)
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
            solution_last = None
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
        saved_active, saved_solution = active, (solution_mode, solution_last)
        if detached_quote:
            # A callout closes at the end of its quote block. Never absorb the
            # following ordinary paragraph into its task/example.
            active = None
            current = None
        cursor, part_start = 0, 0
        for line in block["text"].splitlines(keepends=True):
            value = _visible(line)
            info = _named(value, practice=practice)
            statement = None if info else _statement(value)
            bare = re.match(rf"^({_NUMBER})[.)]\s+\S", value)
            top_level = not re.match(r"^[ \t]{2,}\S", line)
            numbered_active = active and active["unit_basis"] == "numbered_practice_item"
            if not info and not statement and bare and practice and top_level and (
                    not active or numbered_active or active["unit_kind"] in {"statement", "remark", "caption"}):
                if not solution_mode:
                    opens = True
                else:
                    next_task = numbered_active and _successor(active["unit_label"], bare[1])
                    next_step = _successor(solution_last, bare[1])
                    opens = next_task and not next_step
                    if next_task and next_step:
                        ambiguous.add(bare[1])
                if opens:
                    for group in reversed(groups):
                        if bare[1] in group["_doubt"]:
                            group["_doubt"].discard(bare[1])
                            break
                    info = {"unit_kind": "exercise", "unit_subtype": "", "unit_label": bare[1],
                            "unit_basis": "numbered_practice_item"}
            if not info and opens_statement(statement, paragraph_start=cursor == 0):
                info = statement
                if (info["unit_kind"] == "caption" and cursor == 0 and groups and current is groups[-1]
                        and current["atomic"] and current["kind"] == "table"
                        and current["unit_kind"] == "prose" and current["section_id"] == section):
                    # A caption right below a table names that table too.
                    current.update(make_meta(info, block, cursor, section))
            if info:
                if cursor > part_start:
                    append(block, part_start, cursor, active)
                active = make_meta(info, block, cursor, section)
                part_start = cursor
                solution_mode, solution_last = False, None
            elif _SOLUTION.match(value):
                solution_mode, solution_last = True, None
            elif solution_mode and bare and top_level:
                solution_last = bare[1]
            elif quoted and re.match(r"^(?:>\s*)+#{1,6}\s+", line) and not active:
                active = make_meta({"unit_kind": "callout", "unit_subtype": "", "unit_label": value,
                                    "unit_basis": "quoted_heading"}, block, cursor, section)
            cursor += len(line)
        append(block, part_start, len(block["text"]), active)
        if detached_quote:
            active = saved_active
            solution_mode, solution_last = saved_solution
            current = None
    for group in groups:
        group["unit_boundary_ambiguous"] = bool(group.pop("_doubt"))
    return groups
