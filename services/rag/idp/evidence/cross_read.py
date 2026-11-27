"""Level 4 verification: formula/table cross-read, token confirmation, and selective dual-read."""

from __future__ import annotations

import re
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

from idp.input.validation import encoding_issues, is_garbled_text
from idp.processing.formula import has_math_cues

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

LOW = 0.60

DUAL_READ_VERSION = "idp-dual-read-1"
OCR_SOURCES = {"tesseract_fallback", "tesseract_fast", "tesseract", "tesseract_ocr"}
READ_TYPES = {"Text", "SectionHeader", "ListGroup"}
_COMMAND = re.compile(r"\\[A-Za-z]+")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

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
_UNWRAP = {
    "mathrm", "mathbf", "mathit", "text", "operatorname", "boldsymbol",
    "overline", "bar", "vec", "overrightarrow", "hat", "widehat", "dot", "tilde",
}
_IGNORED = {"left", "right", "displaystyle", "big", "Big", "bigl", "bigr", ",", ";", "!", " "}
_REJECT = re.compile(
    r"[　-鿿가-힯]"
    r"|\\(?:quad|qquad|xrightarrow|textmu|begin|end|hline)|\$"
    r"|\\(?:forall|exists|times)\s*\\(?:vec|widehat|hat|overline|overrightarrow|bar)"
    r"|\\vec\{[^{}]*\}\s*\\vec"
)
_CONFUSIONS = {
    "∀": "∀|V|W|Y|v", "∃": "∃|3|a|E", "∈": "∈|€|e|E|c|C|6", "∉": "∉|£|€|e|g",
    "⊂": "⊂|c|C", "⊃": "⊃|o|O|D", "ℝ": "ℝ|IR|lR|\\]R|JR|R", "ℚ": "ℚ|Q|@|O",
    "ℕ": "ℕ|N", "ℤ": "ℤ|Z", "≤": "≤|<=|<|s|=", "≥": "≥|>=|>|=", "≠": "≠|\\+|z|#|=",
    "⇒": "⇒|=>|>|=", "⇔": "⇔|<=>|<>|=|&", "→": "→|->|>", "∞": "∞|00|oo|°°|>",
    "×": "×|x|X", "Δ": "Δ|A", "π": "π|n", "°": "°|\"|”|\\*|o|º", "|": "\\||I|l|\\]",
    "−": "-|—|–|_|~", "-": "-|—|–|_|~", "÷": "÷|:",
}
_OPTIONAL = {"·": "·|-", "√": "√|xJ|x/|4j|J|V|/"}
_BRACKETS = {
    "(": "\\(|\\[|\\{", ")": "\\)|\\]|\\}", "[": "\\[|\\(|\\{", "]": "\\]|\\)|\\}",
    "{": "\\{|\\(|\\[", "}": "\\}|\\)|\\]",
}
_SHAPE_CASE = set("cosvwxzpCOSVWXZP")
_SCRIPT_GARBLE = "[”“\"'’‘`´*?ˆ^°²³27]{0,2}"
_SCRIPT = "\x00"
_SUPER = "\x01"
_SUPER_TRACE = set("”“\"'’‘`´*?ˆ^°²³27,·")
_DROP = str.maketrans("", "", ",.;: \t\n“”\"'’‘`´")
_MATH_DELIM = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]|\$\$(.+?)\$\$|\$(.+?)\$", re.S)
_DELIMS = re.compile(r"^\s*(?:\\\[|\\\(|\$\$|\$)|(?:\\\]|\\\)|\$\$|\$)\s*$")


def _group(text: str, start: int) -> tuple[str, int]:
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
    if not isinstance(latex, str) or not latex.strip() or _REJECT.search(latex):
        return None
    if re.search(r"(\\[A-Za-z]+\{?)(?:[^\\]{0,6}\1){3,}", latex):
        return None
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
                return None
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
    first, last = positions[match.start()], positions[match.end() - 1]
    return not (
        (first > 0 and raw[first - 1].isalnum() and raw[first].isalnum())
        or (last + 1 < len(raw) and raw[last + 1].isalnum() and raw[last].isalnum())
    )


def formula_agreement(latex: str, ocr_text: str) -> dict | None:
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
            return {
                "code": FORMULA_AGREED,
                "skeleton": shown,
                "ocr_coverage": round(len(match.group()) / len(ocr), 3),
            }
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
                continue
            ratio = SequenceMatcher(None, plain, window, autojunk=False).ratio()
            if ratio > best:
                best, best_window = ratio, window
    digits = re.findall(r"\d+", plain)
    unconfirmed = [
        c for c in plain
        if not c.isascii() and c not in _CONFUSIONS and c not in _OPTIONAL and c not in best_window
    ]
    edges = {0, len(plain) - 1}
    junk_edge = any(
        tag == "delete" and any(
            i in edges and plain[i].isascii() and plain[i].isalnum() for i in range(i1, i2)
        )
        for tag, i1, i2, _, _ in SequenceMatcher(None, plain, best_window, autojunk=False).get_opcodes()
    )
    if (
        best >= CONSISTENT_MIN_RATIO
        and digits == re.findall(r"\d+", best_window)
        and not unconfirmed
        and not junk_edge
    ):
        return {
            "code": FORMULA_CONSISTENT,
            "skeleton": shown,
            "ratio": round(best, 3),
            "ocr_coverage": round(len(best_window) / len(ocr), 3),
        }
    return None


def _cell_norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").casefold()
    text = re.sub(r"[—–−_]", "-", text)
    return re.sub(r"[\s“”\"'’‘|]", "", text)


def table_agreement(cells: list[dict]) -> dict | None:
    if not cells or not all(
        isinstance(c, dict) and isinstance(c.get("row"), int) and isinstance(c.get("column"), int)
        for c in cells
    ):
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
    return {
        "code": TABLE_AGREED if agreed == filled else TABLE_PARTIAL,
        "text": "\n".join(lines),
        "agreed_cells": agreed,
        "filled_cells": filled,
    }


# ---------------------------------------------------------------------------
# Token logprob confirmation and safe diacritic repair (VLM <-> Tesseract)
# ---------------------------------------------------------------------------

def flat(word: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFKC", word)).casefold()


def fold(word: str) -> str:
    value = unicodedata.normalize("NFD", word.casefold()).replace("đ", "d")
    return "".join(c for c in value if unicodedata.category(c) != "Mn")


def _wordchar(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LNM"


def word_probs(tokens) -> list[tuple[str, float]]:
    words, current, low, command, previous = [], "", 1.0, False, ""
    for item in tokens:
        text, prob = item[0], item[1]
        for ch in text:
            if ch in "_^{}" and current:
                continue
            if _wordchar(ch):
                if not current:
                    command = previous == "\\"
                current += ch
                low = min(low, prob)
            else:
                if current and not command:
                    words.append((flat(current), low))
                current, low = "", 1.0
            previous = ch
    if current and not command:
        words.append((flat(current), low))
    return words


def split_lines(tokens) -> list[list[tuple]]:
    lines, current = [], []
    for item in tokens:
        text, prob = item[0], item[1]
        alts = item[2] if len(item) > 2 and "\n" not in text else []
        for i, part in enumerate(text.split("\n")):
            if i:
                lines.append(current)
                current = []
            if part:
                current.append((part, prob, alts))
    lines.append(current)
    return [line for line in lines if "".join(t[0] for t in line).strip()]


def repair_line(tokens, tess_words: set[str]) -> tuple[list[tuple], list[dict]]:
    def words_of(seq):
        return [w for w, _ in word_probs([(t[0], 1.0) for t in seq])]

    tokens = [tuple(t) for t in tokens]
    before = words_of(tokens)
    repairs = []
    for i in range(len(tokens)):
        text, prob, alts = tokens[i]
        if prob >= LOW or not alts or not any(_wordchar(c) for c in text):
            continue
        for alt, alt_prob in sorted(alts, key=lambda a: -a[1]):
            if alt_prob < 0.02 or "\n" in alt:
                continue
            candidate = tokens[:i] + [(alt, 1.0, [])] + tokens[i + 1:]
            after = words_of(candidate)
            if len(after) != len(before):
                continue
            changed = [k for k, (x, y) in enumerate(zip(before, after)) if x != y]
            if len(changed) != 1:
                continue
            k = changed[0]
            if (
                before[k] in tess_words
                or after[k] not in tess_words
                or fold(before[k]) != fold(after[k])
                or after[k].count("đ") < before[k].count("đ")
            ):
                continue
            repairs.append({"from": before[k], "to": after[k], "probability": round(prob, 4)})
            tokens, before = candidate, after
            break
    return tokens, repairs


def line_confidence(tokens, kind: str, tess_text: str, tess_words: set[str]) -> float | None:
    chars = [(c, t[1]) for t in tokens for c in t[0]]
    text = "".join(c for c, _ in chars)
    confirmed = [False] * len(chars)
    if tess_text.strip():
        spans = (
            [(0, len(text), text)]
            if kind == "Equation"
            else [(m.start(), m.end(), next(g for g in m.groups() if g is not None)) for m in _MATH_DELIM.finditer(text)]
        )
        for start, end, latex in spans:
            if formula_agreement(_DELIMS.sub("", latex).strip(), tess_text):
                for k in range(start, end):
                    confirmed[k] = True
    rest = [(c, p) for (c, p), done in zip(chars, confirmed) if not done]
    words = word_probs(rest)
    if not words and not any(confirmed):
        return None
    unconfirmed = [p for w, p in words if w not in tess_words]
    return round(min(unconfirmed), 4) if unconfirmed else 1.0


# ---------------------------------------------------------------------------
# Selective or full dual-read verification
# ---------------------------------------------------------------------------

def comparable_words(text: str) -> list[str]:
    value = unicodedata.normalize("NFC", _COMMAND.sub(" ", text or "")).casefold()
    return sorted(_TOKEN.findall(value))


def _is_risky_ocr_block(block: dict, risk_threshold: float) -> bool:
    conf = block.get("confidence")
    text = block.get("text") or ""
    if conf is not None and float(conf) < risk_threshold:
        return True
    if has_math_cues(text) or is_garbled_text(text) or encoding_issues(text):
        return True
    return any(f.get("severity") in {"warning", "error"} for f in block.get("review_flags") or [])


def dual_read_page(
    page: dict,
    image_path: str | Path,
    reader,
    *,
    pad: int = 4,
    selective: bool = False,
    risk_confidence_threshold: float = 0.85,
) -> dict:
    """Annotate OCR line blocks of ``page`` in place with independent verification evidence."""
    identity = getattr(reader, "identity", None)
    if not identity:
        raise ValueError("dual reader needs a stable identity")
    summary = {
        "version": DUAL_READ_VERSION,
        "reader": identity,
        "agreed": 0,
        "disagreed": 0,
        "failed": 0,
        "skipped_clean": 0,
        "selective": selective,
    }
    width, height = page.get("page_size") or (0, 0)
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    if not width or not height:
        return summary
    sx, sy = image.width / width, image.height / height
    with tempfile.TemporaryDirectory(prefix="idp-dual-") as directory:
        crop_path = Path(directory) / "line.png"
        for block in page.get("blocks") or []:
            if (
                block.get("source") not in OCR_SOURCES
                or block.get("block_type", block.get("type")) not in READ_TYPES
                or block.get("excluded_from_content")
                or not comparable_words(block.get("text") or "")
            ):
                continue
            if selective and not _is_risky_ocr_block(block, risk_confidence_threshold):
                summary["skipped_clean"] += 1
                continue
            x0, y0, x1, y1 = block["bbox"]
            box = (
                max(0, x0 * sx - pad),
                max(0, y0 * sy - pad),
                min(image.width, x1 * sx + pad),
                min(image.height, y1 * sy + pad),
            )
            if box[0] >= box[2] or box[1] >= box[3]:
                continue
            image.crop(box).save(crop_path)
            flags = block.setdefault("review_flags", [])
            try:
                other = reader(crop_path)
            except Exception as exc:
                summary["failed"] += 1
                flags.append({
                    "block_id": block.get("block_id"),
                    "code": "OCR_DUAL_READ_FAILED",
                    "severity": "warning",
                    "reason": type(exc).__name__,
                })
                continue
            if comparable_words(other) == comparable_words(block.get("text") or ""):
                summary["agreed"] += 1
                flags.append({
                    "block_id": block.get("block_id"),
                    "code": "OCR_DUAL_READ_AGREED",
                    "severity": "info",
                    "version": DUAL_READ_VERSION,
                })
            else:
                summary["disagreed"] += 1
                flags.append({
                    "block_id": block.get("block_id"),
                    "code": "OCR_DUAL_READ_DISAGREE",
                    "severity": "warning",
                    "version": DUAL_READ_VERSION,
                    "alternative": (other or "")[:1000],
                })
    page["dual_read"] = summary
    return summary
