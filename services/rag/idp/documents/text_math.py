"""Rebuild text-layer math from glyph geometry, without a recognizer.

A TeX PDF keeps every glyph with its font, size and baseline. Line-based
extraction flattens that: ``N_0 e^{-kt}`` becomes "N0e−kt" and a stacked
fraction is split into separate blocks. This module groups the glyphs of a
region back into lines, turns small raised/lowered glyphs into scripts and
glyphs above/below a drawn rule into ``\\frac``.

The result is only used when it is provably lossless: the rebuilt glyphs
must be exactly the characters of the blocks they replace, and no glyph may
be one this module cannot interpret (control/private-use characters, big
delimiters from the math-extension font). Otherwise the caller keeps the
original blocks and their review flags.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata

from idp.documents.encoding import encoding_issues
from idp.validation.validate import validate_latex

METHOD = "text-layer-geometry-1"
_EXTENSION_FONT = re.compile(r"MathExtension|CMEX", re.I)
# showkeys labels (typewriter font) are margin annotations: kept as source
# text, never read as a script and never a reason to rebuild a block.
_LABEL_FONT = re.compile(r"Mono|CMTT", re.I)
# Without a ToUnicode entry a math-extension glyph reaches the text layer as
# its raw code, which is its slot in TeX's standard OMX (cmex10) encoding.
# Only self-contained glyphs are mapped: sized delimiters and big operators.
# Extensible pieces (vextendsingle, brace top/mid/bottom, ...), radicals and
# wide accents need their partners' geometry and stay unmapped.
_OMX = {
    0x00: "(", 0x01: ")", 0x02: "[", 0x03: "]", 0x08: "{", 0x09: "}",
    0x10: "(", 0x11: ")", 0x12: "(", 0x13: ")", 0x14: "[", 0x15: "]",
    0x1A: "{", 0x1B: "}", 0x20: "(", 0x21: ")", 0x22: "[", 0x23: "]",
    0x28: "{", 0x29: "}", 0x68: "[", 0x69: "]", 0x6E: "{", 0x6F: "}",
    0x48: "∮", 0x49: "∮", 0x50: "∑", 0x51: "∏", 0x52: "∫",
    0x58: "∑", 0x59: "∏", 0x5A: "∫",
}
# Text-style operators hang from an origin ~0.82 of their size above the
# baseline they are set on, so their real baseline is recoverable and they
# can sit in an exponent (e^{∫p dx}).
_OMX_TEXT_OPERATOR = {0x48, 0x50, 0x51, 0x52}
_OMX_DISPLAY_LIMITS = {0x58, 0x59}  # display ∑/∏ always carry limits here
_TEXT_OPERATOR_DROP = 0.82
_PROSE_WORD = re.compile(r"[^\W\d_]{2,}")
# Primes are already raised glyphs; N′(t) must not become N^{′}(t).
_PRIMES = set("′″‴")
# An extensible arrow is set as a run of minus glyphs ending in an arrow
# head, with an optional label raised over it: S −−−k−−→ I.
_ARROW = re.compile(r"−{2,}(?:\^\{([^{}]*)\})?−*→")


@dataclass
class Glyph:
    c: str
    x0: float
    y0: float
    x1: float
    y1: float
    baseline: float
    size: float
    font: str
    big: bool = False  # sized delimiter/operator: spans lines, never a script
    text_operator: bool = False  # big glyph with a recoverable baseline

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Rebuilt:
    text: str
    structured: bool
    issues: list[str]
    chars: str  # every source glyph consumed, in reading order


def page_glyphs(page, rect) -> list[Glyph]:
    """Glyphs whose centre lies inside ``rect`` (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = rect
    out = []
    raw = page.get_text("rawdict", clip=(x0 - 2, y0 - 2, x1 + 2, y1 + 2))
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    bx0, by0, bx1, by1 = ch["bbox"]
                    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
                    if not (x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5):
                        continue
                    out.append(Glyph(
                        ch["c"], bx0, by0, bx1, by1, ch["origin"][1],
                        float(span["size"]), span.get("font", ""),
                    ))
    return out


def page_rules(page) -> list[tuple[float, float, float]]:
    """Thin horizontal strokes (x0, x1, y): candidate fraction bars."""
    rules = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) < 0.5 and abs(a.x - b.x) > 2:
                    rules.append((min(a.x, b.x), max(a.x, b.x), (a.y + b.y) / 2))
            elif item[0] == "re":
                r = item[1]
                if r.height < 1.5 and r.width > 2:
                    rules.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
    return rules


def _linear(glyphs: list[Glyph]) -> tuple[str, bool]:
    """One or more text lines with sub/superscripts, top to bottom."""
    if not glyphs:
        return "", False
    top = max(g.size for g in glyphs)
    # Space glyphs keep the span size at the script baseline; they are not
    # evidence of a text line.
    anchors = sorted(
        g.baseline for g in glyphs
        if g.size >= top * 0.9 and not g.c.isspace() and not g.big
    ) or sorted(g.baseline for g in glyphs)
    lines: list[list[float]] = []
    for value in anchors:
        if lines and value - lines[-1][-1] <= top * 0.3:
            lines[-1].append(value)
        else:
            lines.append([value])
    baselines = [sorted(v)[len(v) // 2] for v in lines]
    rows: dict[int, list[Glyph]] = {i: [] for i in range(len(baselines))}
    for g in glyphs:
        # A big delimiter's origin is not on a text baseline; place it by its
        # vertical centre (a text line's centre sits ~0.3em above baseline).
        y = (g.y0 + g.y1) / 2 + 0.3 * top if g.big and not g.text_operator else g.baseline
        index = min(range(len(baselines)), key=lambda i: abs(y - baselines[i]))
        rows[index].append(g)
    structured = False
    out_lines = []
    for index, base in enumerate(baselines):
        size = max((g.size for g in rows[index]), default=top)

        def mode_of(g: Glyph) -> str:
            if g.c.startswith("\\frac") or g.c in _PRIMES or _LABEL_FONT.search(g.font):
                return ""
            if g.text_operator:
                return "^" if g.baseline - base < -size * 0.15 else ""
            if g.big and g.size >= size * 0.9:
                return ""
            # Script-size glyphs, including an operator set in an exponent
            # (e^{∫p dx}): cmex boxes hang from the origin, so only the
            # origin and size are reliable.
            if g.size < size * 0.9:
                shift = g.baseline - base
                if shift < -size * 0.15:
                    return "^"
                if shift > size * 0.1:
                    return "_"
            return ""

        # Limits set under/over a big operator can be wider than it; they
        # belong right after the operator, not where their left edge falls.
        operators = [
            g for g in rows[index] if g.big and g.c in "∑∏∫∮" and not mode_of(g)
        ]

        def order(g: Glyph) -> tuple[float, float]:
            if mode_of(g):
                for op in operators:
                    pad = 0.6 * size
                    if op.x0 - pad <= g.cx <= op.x1 + pad:
                        return (op.x1 + 0.01, g.x0)
            return (g.x0, g.baseline)

        row = sorted(rows[index], key=order)
        parts: list[tuple[str, str]] = []
        previous = None
        for g in row:
            mode = mode_of(g)
            gap = g.x0 - previous.x1 if previous else 0.0
            if previous and gap > size * 0.2 and g.c != " " and not mode:
                parts.append(("", " "))
            parts.append((mode, g.c))
            previous = g
        # A run of script glyphs is one cluster: limits of ∫/∑ and x_1^2 are
        # set below and above each other, so x-order interleaves them.
        text, subs, sups = "", "", ""
        for mode, c in parts + [("", "")]:
            if mode == "_":
                subs += c
            elif mode == "^":
                sups += c
            else:
                if subs.strip():
                    text += "_{" + subs.strip() + "}"
                    structured = True
                if sups.strip():
                    text += "^{" + sups.strip() + "}"
                    structured = True
                subs = sups = ""
                text += c
        text = _ARROW.sub(lambda m: "\\xrightarrow{" + (m.group(1) or "") + "}", text)
        out_lines.append(re.sub(r"[ \t]+", " ", text).strip())
    return "\n".join(line for line in out_lines if line), structured


def rebuild(glyphs: list[Glyph], rules: list[tuple[float, float, float]]) -> Rebuilt:
    issues = []
    # The raw characters, before mapping, are what the source blocks hold.
    chars = "".join(g.c for g in glyphs)
    mapped = []
    for g in glyphs:
        if _EXTENSION_FONT.search(g.font):
            code = ord(g.c) if len(g.c) == 1 else -1
            symbol = _OMX.get(code)
            if symbol is None:
                issues.append("extension_glyph")
            else:
                text_operator = code in _OMX_TEXT_OPERATOR
                if code in _OMX_DISPLAY_LIMITS and not any(
                    o.size < g.size * 0.9 and g.x0 - 0.6 * g.size <= o.cx <= g.x1 + 0.6 * g.size
                    and o.y0 >= g.y1 - 2 for o in glyphs
                ):
                    issues.append("operator_limits_missing")
                g = Glyph(
                    symbol, g.x0, g.y0, g.x1, g.y1,
                    g.baseline + _TEXT_OPERATOR_DROP * g.size if text_operator else g.baseline,
                    g.size, g.font, big=True, text_operator=text_operator,
                )
        elif any(unicodedata.category(c) in {"Cc", "Co", "Cn"} for c in g.c):
            issues.append("unmapped_glyph")
        mapped.append(g)
    glyphs = mapped
    # A region cut out of a larger formula shows up as unpaired delimiters.
    # A big "{" alone is a cases brace and has no partner.
    small = Counter(g.c for g in glyphs if not g.big)
    big = Counter(g.c for g in glyphs if g.big)
    if (
        any(small[a] != small[b] for a, b in ("()", "[]", "{}"))
        or big["("] != big[")"] or big["["] != big["]"] or big["}"] > big["{"]
    ):
        issues.append("unbalanced")
    structured = False
    work = list(glyphs)
    # Innermost (narrowest) bars first, so an outer fraction sees a token.
    for x0, x1, y in sorted(rules, key=lambda r: r[1] - r[0]):
        # Numerator/denominator glyphs sit right against the bar; a text line
        # above or below the fraction is at least a line gap away.
        inside = [g for g in work if x0 - 1 <= g.cx <= x1 + 1 and not g.big]
        num = [g for g in inside if y - 1.0 * g.size <= g.y1 <= y + 0.8]
        den = [g for g in inside if y - 0.8 <= g.y0 <= y + 1.0 * g.size]
        if not num or not den or set(map(id, num)) & set(map(id, den)):
            continue
        numerator, _ = _linear(num)
        denominator, _ = _linear(den)
        if "\n" in numerator or "\n" in denominator:
            issues.append("fraction_multiline")
            continue
        size = max(g.size for g in num + den)
        token = Glyph(
            "\\frac{" + numerator + "}{" + denominator + "}", x0, y - size, x1, y + size,
            y + 0.25 * size, size, "",
        )
        consumed = set(map(id, num + den))
        work = [g for g in work if id(g) not in consumed] + [token]
        structured = True
    text, scripted = _linear(work)
    return Rebuilt(text, structured or scripted, sorted(set(issues)), chars)


def _same_characters(a: str, b: str) -> bool:
    def norm(value):
        return Counter(c for c in unicodedata.normalize("NFC", value) if not c.isspace())
    return norm(a) == norm(b)


def _overlaps(a, b, pad=0.0) -> bool:
    return (
        a[0] < b[2] + pad and b[0] < a[2] + pad
        and a[1] < b[3] and b[1] < a[3]
    )


# Pieces of one display formula set side by side on a line are a few points
# apart; a neighbouring column is further away.
SIDE_GAP = 6.0
# Limits under/over an operator are their own flagged fragment just below or
# above the line; only flagged fragments may join across such a gap.
LIMIT_GAP = 4.0


def _near(a, b, pad_x: float, pad_y: float) -> bool:
    return (
        a[0] < b[2] + pad_x and b[0] < a[2] + pad_x
        and a[1] < b[3] + pad_y and b[1] < a[3] + pad_y
    )
_RELATION = re.compile(r"[=<>≤≥⩽⩾≡≠∈→]|\\xrightarrow")
_DANGLING = re.compile(r"^[=+−\-·×,)\]}]|[=+−\-·×,(\[{]$")


def _encoding_problem(text: str) -> bool:
    """Any digital encoding finding, or private-use glyphs left in text.

    Uses the same checks as digital._encoding_issues, so a rebuilt block that
    drops TEXT_ENCODING_REVIEW always passes the digital encoding audit.
    """
    if encoding_issues(text):
        return True
    return any(unicodedata.category(c) == "Co" for c in text)


def _incomplete(text: str) -> bool:
    """A rebuilt region that is still a piece of something larger."""
    core = re.sub(r"\\[A-Za-z]+", " ", text).strip()
    if not core or _DANGLING.search(core):
        return True
    return len(_PROSE_WORD.findall(core)) < 2 and not _RELATION.search(text)


SEED_CODES = {"FORMULA_TEXT_LAYER_UNVERIFIED", "FORMULA_TEXT_LAYER_FRAGMENT"}
MERGE_TYPES = {"Text", "Equation"}


def _has_scripts(glyphs: list[Glyph]) -> bool:
    """Inline math in prose: a script-size glyph off its line's baseline.

    "I(0)e^{kt}" inside an unflagged paragraph flattens to "I(0)ekt" just as
    a display formula does, so such a block is rebuilt as well.
    """
    full = [g for g in glyphs if not g.c.isspace() and not _LABEL_FONT.search(g.font)]
    if not full:
        return False
    top = max(g.size for g in full)
    lines = [g.baseline for g in full if g.size >= top * 0.9]
    for g in full:
        if g.size < top * 0.9 and g.c not in _PRIMES and lines:
            nearest = min(lines, key=lambda b: abs(b - g.baseline))
            if abs(g.baseline - nearest) > top * 0.1:
                return True
    return False


def reconstruct_page_math(blocks: list[dict], page) -> list[dict]:
    """Merge and rebuild formula regions of one page; return the new blocks.

    Seeds are blocks flagged as text-layer formulas, and Text blocks with
    inline scripts. A region is a seed plus every Text/Equation block
    overlapping it both vertically and horizontally (pieces of one fraction
    or script run). A region is replaced by one block only when the rebuild
    is lossless.
    """
    rules = None
    consumed: set[int] = set()
    replacement: dict[int, dict] = {}
    for index, block in enumerate(blocks):
        codes = {f.get("code") for f in block.get("review_flags") or []}
        if index in consumed or block.get("block_type") not in MERGE_TYPES:
            continue
        if not codes & SEED_CODES and not (
            block.get("block_type") == "Text"
            and _has_scripts(page_glyphs(page, block["bbox"]))
        ):
            continue
        region = {index}
        bbox = list(block["bbox"])
        grown = True
        while grown:
            grown = False
            for other, candidate in enumerate(blocks):
                if other in region or other in consumed or candidate.get("block_type") not in MERGE_TYPES:
                    continue
                fragment = any(
                    f.get("code") == "FORMULA_TEXT_LAYER_FRAGMENT"
                    for f in candidate.get("review_flags") or []
                )
                if not (
                    _overlaps(bbox, candidate["bbox"], SIDE_GAP)
                    or (fragment and _near(bbox, candidate["bbox"], 0.0, LIMIT_GAP))
                ):
                    continue
                region.add(other)
                cb = candidate["bbox"]
                bbox = [min(bbox[0], cb[0]), min(bbox[1], cb[1]), max(bbox[2], cb[2]), max(bbox[3], cb[3])]
                grown = True
        members = [blocks[i] for i in sorted(region)]
        if rules is None:
            rules = page_rules(page)
        local_rules = [r for r in rules if bbox[0] - 1 <= r[0] and r[1] <= bbox[2] + 1 and bbox[1] <= r[2] <= bbox[3]]
        result = rebuild(page_glyphs(page, bbox), local_rules)
        source = "".join(m.get("text") or "" for m in members)
        if (
            result.issues or _incomplete(result.text)
            or not _same_characters(result.chars, source)
        ):
            continue
        consumed |= region
        first = members[0]
        # The member blocks' encoding findings were about raw glyph codes the
        # rebuild has now mapped; keep one only if the rebuilt text still has
        # such characters. Every other finding carries over unchanged.
        still_bad = _encoding_problem(result.text)
        flags = [
            f for m in members for f in m.get("review_flags") or []
            if f.get("code") not in SEED_CODES
            and (f.get("code") != "TEXT_ENCODING_REVIEW" or still_bad)
        ]
        flags.append({
            "block_id": first["block_id"], "code": "FORMULA_TEXT_LAYER_RECONSTRUCTED",
            "severity": "info", "method": METHOD, "structured": result.structured,
            "merged_blocks": [m["block_id"] for m in members],
        })
        prose = len(_PROSE_WORD.findall(re.sub(r"\\frac|[_^]\{[^{}]*\}", " ", result.text)))
        merged = dict(first)
        merged.update({
            "block_type": "Text", "bbox": bbox, "text": result.text,
            "markdown": result.text, "formula_text": "", "review_flags": flags,
        })
        if prose < 4:
            # A display formula is published as math: LaTeX with its validation,
            # and $$-delimited markdown so downstream parsers (question option
            # markers) treat "g)" in "(f ∗ g)(x)" as math, not an option label.
            validation = validate_latex(result.text).as_dict()
            if not validation["valid"]:
                consumed -= region
                continue
            merged.update({
                "block_type": "Equation", "markdown": "$$\n" + result.text + "\n$$",
                "formula_text": result.text, "latex": [result.text],
                "latex_validation": [validation],
            })
        replacement[min(region)] = merged
    out = []
    for index, block in enumerate(blocks):
        if index in replacement:
            out.append(replacement[index])
        elif index not in consumed:
            out.append(block)
    return out
