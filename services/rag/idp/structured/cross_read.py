"""Cross-read checks that make structured regions retrievable as text.

A formula model and the page OCR read the same pixels independently. Where
the formula's base characters agree with the OCR line under it, the formula
is evidence the OCR alone cannot give (superscripts, ∀/∈/ℝ, which Tesseract
cannot emit). A table's grid reader reads each cell twice (whole-crop hOCR
and a per-cell crop); cells where the two agree are kept.

Nothing here edits source text. Results are recorded as flags, and the
block's retrievable ``text`` is derived from the structured payload:
- ``FORMULA_OCR_AGREED`` (verified): the formula skeleton matches the OCR line
  exactly, allowing only known one-way OCR confusions and garbled scripts,
  and every claimed superscript left a trace in the OCR;
- ``FORMULA_OCR_CONSISTENT`` (scored): it mostly matches (similarity bound,
  same digits, no unconfirmed Greek/symbol);
- ``TABLE_CELLS_AGREED`` / ``TABLE_CELLS_PARTIAL`` (scored): every / most
  non-empty cells agree between the two readings; disagreeing cells are
  rendered as ``?`` instead of guessed.

Not checked, because OCR never sees them: subscripts, primes, overlines and
other decorations are taken from the formula model as read.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

CROSS_READ_VERSION = "idp-cross-read-1"
FORMULA_AGREED = "FORMULA_OCR_AGREED"
FORMULA_CONSISTENT = "FORMULA_OCR_CONSISTENT"
TABLE_AGREED = "TABLE_CELLS_AGREED"
TABLE_PARTIAL = "TABLE_CELLS_PARTIAL"
LINE_SUPERSEDED = "FORMULA_LINE_SUPERSEDED"
CROSS_READ_CODES = {FORMULA_AGREED, FORMULA_CONSISTENT, TABLE_AGREED, TABLE_PARTIAL}

CONSISTENT_MIN_RATIO = 0.8
CONSISTENT_MIN_CHARS = 8
TABLE_PARTIAL_MIN = 0.6
SUPERSEDE_MIN_COVERAGE = 0.7

# LaTeX command -> the character it prints.
_SYMBOLS = {
    "forall": "∀", "exists": "∃", "in": "∈", "notin": "∉", "ni": "∋",
    "subset": "⊂", "subseteq": "⊂", "supset": "⊃", "supseteq": "⊃",
    "cap": "∩", "cup": "∪", "emptyset": "∅", "varnothing": "∅",
    "leq": "≤", "le": "≤", "leqslant": "≤", "geq": "≥", "ge": "≥", "geqslant": "≥",
    "neq": "≠", "ne": "≠", "approx": "≈", "equiv": "≡",
    "Rightarrow": "⇒", "Leftrightarrow": "⇔", "rightarrow": "→", "to": "→",
    "infty": "∞", "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mid": "|",
    "Delta": "Δ", "alpha": "α", "beta": "β", "gamma": "γ", "pi": "π", "theta": "θ",
    "Theta": "Θ", "lambda": "λ", "mu": "μ", "sigma": "σ", "omega": "ω", "varphi": "φ",
    "phi": "φ", "ldots": "", "cdots": "", "dots": "", "circ": "°", "angle": "∠",
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot", "log": "log", "ln": "ln",
    "%": "%", "{": "{", "}": "}", "|": "|", "lbrace": "{", "rbrace": "}",
}
_BLACKBOARD = {"R": "ℝ", "Q": "ℚ", "N": "ℕ", "Z": "ℤ", "C": "ℂ"}
# Decorations and wrappers OCR does not see; their argument is kept.
_UNWRAP = {
    "mathrm", "mathbf", "mathit", "text", "operatorname", "boldsymbol",
    "overline", "bar", "vec", "overrightarrow", "hat", "widehat", "dot", "tilde",
}
_IGNORED = {"left", "right", "displaystyle", "big", "Big", "bigl", "bigr", ",", ";", "!", " "}
_REJECT = re.compile(
    r"[　-鿿가-힯]"
    r"|\\(?:quad|qquad|xrightarrow|textmu|begin|end|hline)|\$"
    # "và" (and) read as a quantifier/operator before a decorated letter:
    # "b=8, c=5 và B=80°" -> "b=8,c=5\forall\widehat{B}=80^{\circ}".
    r"|\\(?:forall|exists|times)\s*\\(?:vec|widehat|hat|overline|overrightarrow|bar)"
    r"|\\vec\{[^{}]*\}\s*\\vec"
)

# Formula character -> what Tesseract prints for it (one way: the OCR side).
_CONFUSIONS = {
    "∀": "∀|V|W|Y|v", "∃": "∃|3|a|E", "∈": "∈|€|e|E|c|C|6", "∉": "∉|£|€|e|g",
    "⊂": "⊂|c|C", "⊃": "⊃|o|O|D", "ℝ": "ℝ|IR|lR|\\]R|JR|R", "ℚ": "ℚ|Q|@|O",
    "ℕ": "ℕ|N", "ℤ": "ℤ|Z", "≤": "≤|<=|<|s|=", "≥": "≥|>=|>|=", "≠": "≠|\\+|z|#|=",
    "⇒": "⇒|=>|>|=", "⇔": "⇔|<=>|<>|=|&", "→": "→|->|>", "∞": "∞|00|oo|°°|>",
    "×": "×|x|X", "Δ": "Δ|A", "π": "π|n", "°": "°|\"|”|\\*|o|º", "|": "\\||I|l|\\]",
    "−": "-|—|–|_|~", "-": "-|—|–|_|~", "÷": "÷|:",
}
_OPTIONAL = {"·": "·|-", "√": "√|xJ|x/|4j|J|V|/"}
# Brackets must be present (a dropped closing brace let "D={7}" match the
# start of "D={7; 11; 13; 17; 19}"), but their shape may be confused.
_BRACKETS = {
    "(": "\\(|\\[|\\{", ")": "\\)|\\]|\\}", "[": "\\[|\\(|\\{", "]": "\\]|\\)|\\}",
    "{": "\\{|\\(|\\[", "}": "\\}|\\)|\\]",
}
_SHAPE_CASE = set("cosvwxzpCOSVWXZP")
_SCRIPT_GARBLE = "[”“\"'’‘`´*?ˆ^°²³27]{0,2}"
_SCRIPT = "\x00"  # subscript or prime: OCR often prints nothing (or a comma)
_SUPER = "\x01"  # superscript: OCR prints *something* (”, ?, *, ˆ, 2, 7…)
# Raw OCR characters that show a superscript was printed at that place.
_SUPER_TRACE = set("”“\"'’‘`´*?ˆ^°²³27,·")
_DROP = str.maketrans("", "", ",.;: \t\n“”\"'’‘`´")


def _group(text: str, start: int) -> tuple[str, int]:
    """The braced (or single-token) argument at ``start`` and the end index."""
    while start < len(text) and text[start] == " ":
        start += 1
    if start >= len(text):
        return "", start
    if text[start] == "{":
        depth = 0
        for index in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            if depth == 0:
                return text[start + 1:index], index + 1
        return text[start + 1:], len(text)
    if text[start] == "\\":
        match = re.match(r"\\(?:[A-Za-z]+|.)", text[start:])
        token = match.group() if match else "\\"
        return token, start + len(token)
    return text[start], start + 1


def formula_skeleton(latex: str) -> str | None:
    """Printed base characters of a formula; scripts become markers.

    None when the LaTeX looks like model noise (CJK, layout commands, long
    repetitions, "và" read as a symbol) or uses an unknown command.
    """
    if not isinstance(latex, str) or not latex.strip() or _REJECT.search(latex):
        return None
    if re.search(r"(\\[A-Za-z]+\{?)(?:[^\\]{0,6}\1){3,}", latex):
        return None  # \bar{\bar{U}}\bar{\bar{U}}… style repetition
    out, index = [], 0
    while index < len(latex):
        char = latex[index]
        if char == "\\":
            match = re.match(r"\\([A-Za-z]+|.)", latex[index:])
            if match is None:
                return None
            name = match.group(1)
            index += len(match.group())
            if name in _IGNORED:
                continue
            if name == "mathbb":
                arg, index = _group(latex, index)
                out.append(_BLACKBOARD.get(arg.strip(), arg))
            elif name in _UNWRAP:
                arg, index = _group(latex, index)
                inner = formula_skeleton(arg) if arg else ""
                if inner is None:
                    return None
                out.append(inner)
            elif name in {"frac", "dfrac", "tfrac"}:
                top, index = _group(latex, index)
                bottom, index = _group(latex, index)
                top, bottom = formula_skeleton(top), formula_skeleton(bottom)
                if top is None or bottom is None:
                    return None
                out.append(f"{top}/{bottom}")
            elif name == "sqrt":
                arg, index = _group(latex, index)
                inner = formula_skeleton(arg)
                if inner is None:
                    return None
                out.append("√" + inner)
            elif name == "prime":
                out.append(_SCRIPT)
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name])
            else:
                return None
        elif char in "^_":
            arg, index = _group(latex, index + 1)
            arg = arg.strip()
            if arg in {"*", "\\ast", ""}:
                return None  # "D_{*}^{*}": stray marks read as scripts
            if arg in {"\\circ", "{\\circ}", "o"}:
                out.append("°")
            elif char == "^" and arg not in {"\\prime", "'"}:
                out.append(_SUPER)
            else:
                out.append(_SCRIPT)
        elif char in "{}" or char == "~" or char.isspace():
            index += 1
        else:
            out.append(char)
            index += 1
    return re.sub(
        f"[{_SCRIPT}{_SUPER}]+",
        lambda m: _SUPER if _SUPER in m.group() else _SCRIPT,
        "".join(out),
    )


def _ocr_form(text: str) -> tuple[str, list[int], str]:
    """OCR text without spaces/separators/quotes, its raw indices, the raw."""
    raw = unicodedata.normalize("NFC", text or "")
    kept = [(i, c) for i, c in enumerate(raw) if c.translate(_DROP)]
    return "".join(c for _, c in kept), [i for i, _ in kept], raw


def _pattern(skeleton: str) -> str:
    parts, supers = [], 0
    for char in skeleton.translate(_DROP):
        if char == _SUPER:
            parts.append(f"(?P<s{supers}>{_SCRIPT_GARBLE})")
            supers += 1
        elif char == _SCRIPT:
            parts.append(_SCRIPT_GARBLE)
        elif char in _CONFUSIONS:
            parts.append(f"(?:{_CONFUSIONS[char]})")
        elif char in _OPTIONAL:
            parts.append(f"(?:{_OPTIONAL[char]})?")
        elif char in _BRACKETS:
            parts.append(f"(?:{_BRACKETS[char]})")
        elif char in _SHAPE_CASE:
            parts.append(f"[{char.lower()}{char.upper()}]")
        else:
            parts.append(re.escape(char))
    return "".join(parts)


def _plain(skeleton: str) -> str:
    return skeleton.replace(_SCRIPT, "").replace(_SUPER, "").translate(_DROP)


def _significant(skeleton: str) -> bool:
    core = _plain(skeleton)
    has_operator = bool(re.search(r"[=<>+\-−×/·∈∉⊂⊃≤≥≠⇒⇔→∀∃√|°]", core))
    has_letter = any(c.isalpha() for c in core)
    return len(core) >= 3 and (has_operator or (len(core) >= 4 and has_letter))


def _supers_printed(match, positions: list[int], raw: str) -> bool:
    """Every superscript the formula claims left a trace in the raw OCR."""
    for name, value in match.groupdict().items():
        if value:
            continue
        start = match.start(name)
        before = positions[start - 1] if start > 0 else -1
        after = positions[start] if start < len(positions) else len(raw)
        if not any(c in _SUPER_TRACE for c in raw[before + 1:after]):
            return False
    return True


def _bounded(match, positions: list[int], raw: str) -> bool:
    """The match does not cut a word or number of the raw OCR in two."""
    first, last = positions[match.start()], positions[match.end() - 1]
    return not (
        (first > 0 and raw[first - 1].isalnum() and raw[first].isalnum())
        or (last + 1 < len(raw) and raw[last + 1].isalnum() and raw[last].isalnum())
    )


def formula_agreement(latex: str, ocr_text: str) -> dict | None:
    """Agreement of one formula with the OCR line it sits on, or None."""
    skeleton = formula_skeleton(latex)
    if skeleton is None or not _significant(skeleton):
        return None
    ocr, positions, raw = _ocr_form(ocr_text)
    if not ocr:
        return None
    shown = skeleton.replace(_SCRIPT, "_").replace(_SUPER, "^")
    for match in re.finditer(_pattern(skeleton), ocr):
        if (
            match.end() > match.start()
            and _bounded(match, positions, raw)
            and _supers_printed(match, positions, raw)
        ):
            return {"code": FORMULA_AGREED, "skeleton": shown,
                    "ocr_coverage": round(len(match.group()) / len(ocr), 3)}
    plain = _plain(skeleton)
    if len(plain) < CONSISTENT_MIN_CHARS:
        return None
    best, best_window = 0.0, ""
    for size in range(max(1, len(plain) - 3), len(plain) + 4):
        for start in range(0, max(1, len(ocr) - size + 1)):
            window = ocr[start:start + size]
            if not window:
                continue
            first, last = positions[start], positions[start + len(window) - 1]
            if (
                (first > 0 and raw[first - 1].isalnum() and raw[first].isalnum())
                or (last + 1 < len(raw) and raw[last + 1].isalnum() and raw[last].isalnum())
            ):
                continue  # would cut a word or number in two ("2400V" of "và")
            ratio = SequenceMatcher(None, plain, window, autojunk=False).ratio()
            if ratio > best:
                best, best_window = ratio, window
    digits = re.findall(r"\d+", plain)
    # A symbol OCR could have printed (Greek, ∑…) but did not is a
    # disagreement, not noise: "2cαcosB" over a printed "2cacosB".
    unconfirmed = [
        c for c in plain
        if not c.isascii() and c not in _CONFUSIONS and c not in _OPTIONAL and c not in best_window
    ]
    # Garbled glyphs inside are tolerated; a letter or digit the formula adds
    # at either end ("…2400V" over "…2 400 và") is model junk.
    edges = {0, len(plain) - 1}
    junk_edge = any(
        tag == "delete" and any(
            i in edges and plain[i].isascii() and plain[i].isalnum() for i in range(i1, i2)
        )
        for tag, i1, i2, _, _ in SequenceMatcher(None, plain, best_window, autojunk=False).get_opcodes()
    )
    if (
        best >= CONSISTENT_MIN_RATIO and digits == re.findall(r"\d+", best_window)
        and not unconfirmed and not junk_edge
    ):
        return {"code": FORMULA_CONSISTENT, "skeleton": shown, "ratio": round(best, 3),
                "ocr_coverage": round(len(best_window) / len(ocr), 3)}
    return None


def _cell_norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").casefold()
    text = re.sub(r"[—–−_]", "-", text)
    return re.sub(r"[\s“”\"'’‘|]", "", text)


def table_agreement(cells: list[dict]) -> dict | None:
    """Rows of a grid table keeping only cells both readings agree on."""
    if not cells or not all(isinstance(c, dict) and isinstance(c.get("row"), int)
                            and isinstance(c.get("column"), int) for c in cells):
        return None
    filled = agreed = 0
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in cells:
        text = (cell.get("text") or "").strip()
        local = cell.get("cell_local_reading")
        if not text and not (local or "").strip():
            value = ""
        elif local is None or _cell_norm(local) == _cell_norm(text):
            filled += 1
            agreed += 1
            value = text
        else:
            filled += 1
            value = "?"
        rows.setdefault(cell["row"], []).append((cell["column"], value))
    if not filled:
        return None
    ratio = agreed / filled
    if ratio < TABLE_PARTIAL_MIN:
        return None
    lines = [" | ".join(v for _, v in sorted(row)) for _, row in sorted(rows.items())]
    return {"code": TABLE_AGREED if agreed == filled else TABLE_PARTIAL,
            "text": "\n".join(lines), "agreed_cells": agreed, "filled_cells": filled}
