"""Formula extraction, native glyph math rebuild, normalization, and LaTeX validation."""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass

from idp.input.validation import encoding_issues

try:
    from latex2mathml.converter import convert as latex_to_mathml
except Exception:  # pragma: no cover - optional dependency
    latex_to_mathml = None

# ---------------------------------------------------------------------------
# Text & LaTeX normalization
# ---------------------------------------------------------------------------

MATH_TERMS = {
    "tập hợp", "phần tử", "tính chất", "giao hoán", "kết hợp", "phân phối",
    "số tự nhiên", "chẵn", "lẻ", "ước", "bội", "nguyên tố", "hợp số",
    "phân tích", "thừa số", "chia hết", "phép chia", "thương", "dư",
    "trục đối xứng", "đối xứng", "hình thang cân", "lục giác đều",
    "ví dụ", "luyện tập", "bài tập", "giải", "tính", "cần", "hãy",
    "số bị chia", "số chia", "tích", "hiệu", "tổng",
}

TEXT_FIXES = [
    (r"thờa\s+số", "thừa số", "ocr:thua-so"),
    (r"thờa", "thừa", "ocr:thua"),
    (r"Lẫn\s+lượt", "Lần lượt", "ocr:lan-luot"),
    (r"tăng\s+dẫn", "tăng dần", "ocr:tang-dan"),
    (r"Vi\s+đụ", "Ví dụ", "ocr:vi-du"),
    (r"Ví\s+đụ", "Ví dụ", "ocr:vi-du"),
    (r"tập\s+họp", "tập hợp", "ocr:tap-hop"),
    (r"kết\s+họp", "kết hợp", "ocr:ket-hop"),
    (r"tính\s+họp", "tính hợp", "ocr:tinh-hop"),
    (r"thích\s+họp", "thích hợp", "ocr:thich-hop"),
    (r"mục\s+lực", "mục lục", "ocr:muc-luc"),
    (r"Dầu\s+hiệu", "Dấu hiệu", "ocr:dau-hieu"),
    (r"dầu\s+ngoặc", "dấu ngoặc", "ocr:dau-ngoac"),
    (r"Họp\s+số", "Hợp số", "ocr:hop-so"),
    (r"Hình\s+vuồng", "Hình vuông", "ocr:hinh-vuong"),
    (r"Hình\s+binh\s+hành", "Hình bình hành", "ocr:hinh-binh-hanh"),
    (r"đối\s+xúng", "đối xứng", "ocr:doi-xung"),
    (r"BẢNG\s+SÔ\s+NGUYÊN\s+TÔ", "BẢNG SỐ NGUYÊN TỐ", "ocr:bang-so-nguyen-to"),
    (r"GIÁI\s+THÍCH", "GIẢI THÍCH", "ocr:giai-thich"),
    (r"đặc\s+trung", "đặc trưng", "ocr:dac-trung"),
    (r"trục\s+đổi\s+xứng", "trục đối xứng", "ocr:truc-doi-xung"),
    (r"đổi\s+xứng", "đối xứng", "ocr:doi-xung"),
    (r"trục\s+đổi", "trục đối", "ocr:truc-doi"),
    (r"hợp\s+li", "hợp lí", "ocr:hop-li"),
    (r"nguyên\s+tổ", "nguyên tố", "ocr:nguyen-to"),
    (r"cân\s+bao\s+nhiêu", "cần bao nhiêu", "ocr:can-bao-nhieu"),
    (r"Tĩnh\s+(?=một\s+cách)", "Tính ", "ocr:tinh"),
    (r"Hấy\s+(?=nêu)", "Hãy ", "ocr:hay"),
    (r"sổ\s+tự\s+nhiên", "số tự nhiên", "ocr:so-tu-nhien"),
    (r"bồn\s+quý", "bốn quý", "ocr:bon-quy"),
    (r"nót\s+nhạc", "nốt nhạc", "ocr:not-nhac"),
    (r"truc\s+đối", "trục đối", "ocr:truc-doi"),
    (r"xúng", "xứng", "ocr:xung"),
    (r"phần\s+từ", "phần tử", "ocr:phan-tu"),
    (r"phân\s+từ", "phần tử", "ocr:phan-tu"),
    (r"chẩn(?=\s|,|\.)", "chẵn", "ocr:chan"),
    (r"/?Zình", "Hình", "ocr:hinh"),
    (r"bón\s+chiếc", "bốn chiếc", "ocr:bon-chiec"),
    (r"các\s+đính", "các đỉnh", "ocr:cac-dinh"),
    (r"ở\s+các\s+đính", "ở các đỉnh", "ocr:o-cac-dinh"),
    (r"VỀ\s+HÌNH", "vẽ hình", "ocr:ve-hinh"),
    (r"Hình:\s*(?=\d)", "hình ", "ocr:hinh-colon"),
    (r"Buớc", "bước", "ocr:buoc"),
    (r"song\s+son(?!g)", "song song", "ocr:song-song"),
    (r"thùa", "thừa", "ocr:thua"),
    (r"tíc(?!h)", "tích", "ocr:tich"),
    (r"m\u09c2", "mũ", "ocr:mu"),
    (r"\.J\s*\(enter\)", "Enter", "ocr:enter"),
    (r"sản\s+phầm", "sản phẩm", "ocr:san-pham"),
    (r"dòi\s+đi", "dời đi", "ocr:doi-di"),
    (r"Vưong", "Vương", "ocr:vuong"),
    (r"Trèn", "Trên", "ocr:tren"),
    (r"Sình\s+học", "Sinh học", "ocr:sinh-hoc"),
    (r"quyền\s+vờ", "quyển vở", "ocr:quyen-vo"),
    (r"bút\s+bị", "bút bi", "ocr:but-bi"),
    (r"bút\s+chỉ", "bút chì", "ocr:but-chi"),
    (r"lóp", "lớp", "ocr:lop"),
    (r"áo\s+phòng", "áo phông", "ocr:ao-phong"),
    (r"quản\s+soác", "quần soóc", "ocr:quan-sooc"),
    (r"tỉnh\s+huống", "tình huống", "ocr:tinh-huong"),
    (r"Thống\s+kể", "Thống kê", "ocr:thong-ke"),
    (r"Giái", "Giải", "ocr:giai"),
    (r"bóng\s+rồ", "bóng rổ", "ocr:bong-ro"),
    (r"mười\s+bày\b", "mười bảy", "ocr:muoi-bay"),
    (r"đồng\s+hỏ", "đồng hồ", "ocr:dong-ho"),
    (r"Địa\s+li\b", "Địa lí", "ocr:dia-li"),
    (r"Vi\s+dụ", "Ví dụ", "ocr:vi-du"),
    (r"vưỏng", "vuông", "ocr:vuong"),
    (r"tiều\s+học", "tiểu học", "ocr:tieu-hoc"),
    (r"áo\s+sơ\s+mì", "áo sơ mi", "ocr:ao-so-mi"),
    (r"Tim\s+(?=trên|một|số|hai|điểm)", "Tìm ", "ocr:tim"),
    (r"chịa\s+cho", "chia cho", "ocr:chia-cho"),
    (r"10ngày", "10 ngày", "ocr:space"),
]

MATH_RE = re.compile(r"<math[^>]*>(.*?)</math>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

_NUMBER_WORD = (
    r"(?:không|một|hai|ba|bốn|bón|năm|sáu|bảy|bày|tám|chín|tư|mốt|lăm|"
    r"mươi|mười|trăm|nghìn|ngàn|triệu|tỉ|tỷ|tì|linh|lẻ|chục)"
)
_NUMBER_SEQ_RE = re.compile(rf"\b{_NUMBER_WORD}(?:\s+{_NUMBER_WORD}){{2,}}\b", re.I)
_NUMBER_UNIT_RE = re.compile(r"\b(?:trăm|nghìn|ngàn|triệu|tỉ|tỷ|tì|mươi|mười|chục|linh|lẻ)\b", re.I)
_NUMBER_WORD_FIXES = {"bón": "bốn", "tì": "tỉ", "bày": "bảy"}


def _apply_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _fix_number_reading(text: str, changes: list[dict]) -> str:
    def fix_sequence(match: re.Match) -> str:
        sequence = match.group(0)
        if len(_NUMBER_UNIT_RE.findall(sequence)) < 2:
            return sequence

        def fix_word(word_match: re.Match) -> str:
            word = word_match.group(0)
            fixed = _NUMBER_WORD_FIXES.get(word.lower())
            if not fixed:
                return word
            fixed = _apply_case(word, fixed)
            changes.append({"code": "ocr:number-word", "from": word, "to": fixed})
            return fixed

        return re.sub(r"\b\w+\b", fix_word, sequence)

    return _NUMBER_SEQ_RE.sub(fix_sequence, text)


def normalize_text(
    text: str,
    profile: str | object | None = "general",
) -> tuple[str, list[dict]]:
    """Apply safe normalization, then optional domain-specific corrections."""
    if not text:
        return "", []
    from idp.config import resolve_profile

    resolved = resolve_profile(profile, text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = SPACE_RE.sub(" ", text).strip()
    changes: list[dict] = []
    if resolved.apply_domain_text_fixes:
        for pattern, replacement, code in TEXT_FIXES:
            def repl(match: re.Match) -> str:
                found = match.group(0)
                fixed = _apply_case(found, replacement)
                changes.append({"code": code, "from": found, "to": fixed})
                return fixed
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        text = _fix_number_reading(text, changes)
        text = SPACE_RE.sub(" ", text).strip()
    return text, changes


def raw_html_text(html_fragment: str) -> str:
    if not html_fragment:
        return ""
    without_math = MATH_RE.sub(" ", html_fragment)
    return html.unescape(TAG_RE.sub(" ", without_math))


def html_text(
    html_fragment: str,
    profile: str | object | None = "general",
) -> tuple[str, list[str]]:
    if not html_fragment:
        return "", []
    maths = [m.group(1).strip() for m in MATH_RE.finditer(html_fragment)]
    text, _ = normalize_text(raw_html_text(html_fragment), profile)
    return text, maths


def normalize_latex(
    latex: str,
    profile: str | object | None = "general",
) -> str:
    s = html.unescape((latex or "").strip())
    s = s.replace("$$", "").replace("$", "")
    for token in ("\\left", "\\right", "\\,", "\\;", "\\!"):
        s = s.replace(token, "")

    def fix_text_group(match: re.Match) -> str:
        fixed, _ = normalize_text(match.group(1), profile)
        return "\\text{" + fixed + "}"

    s = re.sub(r"\\text\{([^{}]*)\}", fix_text_group, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_text_lines(
    text: str,
    profile: str | object | None = "general",
) -> str:
    lines = []
    for line in (text or "").split("\n"):
        prefix = ""
        body = line
        if line.lstrip().startswith("- "):
            idx = line.find("- ")
            prefix = line[: idx + 2]
            body = line[idx + 2 :]
        fixed, _ = normalize_text(body, profile)
        lines.append(prefix + fixed)
    return "\n".join(lines)


def html_to_markdown(
    html_fragment: str,
    profile: str | object | None = "general",
) -> str:
    if not html_fragment:
        return ""
    out = []
    pos = 0
    for match in MATH_RE.finditer(html_fragment):
        before = html_fragment[pos:match.start()]
        before = re.sub(r"<br\s*/?>", "\n", before, flags=re.I)
        before = re.sub(r"</p\s*>", "\n\n", before, flags=re.I)
        before = re.sub(r"<p[^>]*>", "", before, flags=re.I)
        before = re.sub(r"<li[^>]*>", "\n- ", before, flags=re.I)
        before = re.sub(r"</li\s*>", "\n", before, flags=re.I)
        before = TAG_RE.sub(" ", before)
        before = html.unescape(before)
        out.append(normalize_text_lines(before, profile))
        latex = normalize_latex(match.group(1), profile)
        display = 'display="block"' in match.group(0) or 'block-type="Equation"' in match.group(0)
        out.append(f"\n\n$${latex}$$\n\n" if display else f" ${latex}$ ")
        pos = match.end()
    tail = html_fragment[pos:]
    tail = re.sub(r"<br\s*/?>", "\n", tail, flags=re.I)
    tail = re.sub(r"</p\s*>", "\n\n", tail, flags=re.I)
    tail = re.sub(r"<p[^>]*>", "", tail, flags=re.I)
    tail = re.sub(r"<li[^>]*>", "\n- ", tail, flags=re.I)
    tail = re.sub(r"</li\s*>", "\n", tail, flags=re.I)
    tail = TAG_RE.sub(" ", tail)
    tail = html.unescape(tail)
    out.append(normalize_text_lines(tail, profile))
    result = "".join(out)
    result = re.sub(r"[ \t]+", " ", result)
    result = re.sub(r" *\n *", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"(?m)^-\s*•\s*", "- ", result)
    result = re.sub(r"\s+([,.;:])", r"\1", result)
    return result.strip()


def latex_exact_key(latex: str) -> str:
    s = normalize_latex(latex)
    s = s.replace("\\ ", "").rstrip(";.")
    s = s.replace(" ", "")
    s = s.replace(".", "*").replace("\\cdot", "*").replace("\\times", "*")
    s = s.replace("{", "").replace("}", "")
    return s.lower()


def math_to_inline(latex: str) -> str:
    s = (latex or "").strip()
    return f"${s}$" if s else ""


# ---------------------------------------------------------------------------
# LaTeX validation & structural completeness
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    method: str
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _balanced(s: str, left: str, right: str) -> bool:
    depth = 0
    for ch in s:
        if ch == left:
            depth += 1
        elif ch == right:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _strip_intervals(s: str) -> str:
    previous = None
    while previous != s:
        previous = s
        s = re.sub(r"[\[\(][^\[\]\(\)]*;[^\[\]\(\)]*[\]\)]", "", s)
    return s


def _outside_text_groups(s: str) -> str:
    previous = None
    while previous != s:
        previous = s
        s = re.sub(r"\\text\{[^{}]*\}", "", s)
    return s


def validate_latex(latex: str) -> ValidationResult:
    s = (latex or "").strip()
    if not s:
        return ValidationResult(False, "empty", "empty latex")
    balance_source = _outside_text_groups(s)
    interval_source = _strip_intervals(balance_source)
    if not (
        _balanced(balance_source, "{", "}")
        and _balanced(interval_source, "(", ")")
        and _balanced(interval_source, "[", "]")
    ):
        return ValidationResult(False, "balance", "unbalanced delimiters")
    begins = len(re.findall(r"\\begin\{", s))
    ends = len(re.findall(r"\\end\{", s))
    if begins != ends:
        return ValidationResult(False, "environment", "begin/end mismatch")
    depth = 0
    for command in re.findall(r"\\(?:[A-Za-z]+|[^A-Za-z])", balance_source):
        if command == r"\left":
            depth += 1
        elif command == r"\right":
            depth -= 1
            if depth < 0:
                return ValidationResult(False, "left-right", "left/right mismatch")
    if depth:
        return ValidationResult(False, "left-right", "left/right mismatch")
    if latex_to_mathml is not None:
        try:
            latex_to_mathml(s)
            return ValidationResult(True, "mathml")
        except Exception as exc:
            return ValidationResult(True, "structural", str(exc)[:160])
    return ValidationResult(True, "structural")


def bbox_valid(bbox, width: float, height: float) -> bool:
    if not bbox or len(bbox) != 4:
        return False
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return 0 <= x1 < x2 <= width + 1 and 0 <= y1 < y2 <= height + 1


def looks_like_caption(text: str) -> bool:
    return bool(re.match(r"^\s*(Hình|Bảng)\s+\d+", text or "", re.I))


def incomplete_formula_reasons(values: list[str]) -> list[str]:
    joined = " ".join(values or [])
    reasons = []
    if re.search(r"\\(?:in|notin)\s*(?:[)\]}]|$)", joined):
        reasons.append("membership without set")
    if re.search(r"(?:^|=|\+|-|\*|\\cdot|\\times)\s*\\setminus\b", joined):
        reasons.append("setminus without left set")
    if re.search(r"\\(?:frac|sqrt|overline|underline)\s*\{\s*\}", joined):
        reasons.append("empty argument")
    if re.search(r"(?:=|\+|-|\*|\\cdot|\\times)\s*$", joined):
        reasons.append("dangling operator")
    for env in re.findall(r"\\begin\{([A-Za-z*]+)\}", joined):
        if "\\end{" + env + "}" not in joined:
            reasons.append(f"unclosed {env}")
    return reasons


# ---------------------------------------------------------------------------
# Region-router math cues (for selective VLM escalation on OCR regions)
# ---------------------------------------------------------------------------

_MATH_CUE_SYMBOLS = re.compile(
    r"[=<>+\-×÷^_{}\\√∑∫∞≤≥⩽⩾≠≡∈∉⊂⊃∀∃ℝℚℕℤℂαβγδΔθλμπσωφ°′″]"
)
_SCRIPT_GARBLE_CUE = re.compile(r"[A-Za-z0-9][”\"'’‘*?ˆ^°²³]\s*[=+\-−]|(?:^|\s)[A-Za-z]\d+(?:\s*[=+\-−]|$)")
_LATEX_CUE = re.compile(r"\$[^$]+\$|\\(?:frac|sqrt|sum|int|lim|vec|widehat|overline)\b")


def has_math_cues(text: str) -> bool:
    """Detect whether an OCR text region likely contains formulas needing VLM reading."""
    value = (text or "").strip()
    if not value:
        return False
    if _LATEX_CUE.search(value) or _SCRIPT_GARBLE_CUE.search(value):
        return True
    symbols = len(_MATH_CUE_SYMBOLS.findall(value))
    if symbols >= 3:
        return True
    if symbols >= 1 and re.search(r"[A-Za-z]\s*[=≤≥≠∈⊂^_]\s*[A-Za-z0-9(\\]", value):
        return True
    return False


# ---------------------------------------------------------------------------
# Lossless text-layer glyph math reconstruction (Level 0)
# ---------------------------------------------------------------------------

METHOD = "text-layer-geometry-1"
_EXTENSION_FONT = re.compile(r"MathExtension|CMEX", re.I)
_LABEL_FONT = re.compile(r"Mono|CMTT", re.I)
_OMX = {
    0x00: "(", 0x01: ")", 0x02: "[", 0x03: "]", 0x08: "{", 0x09: "}",
    0x10: "(", 0x11: ")", 0x12: "(", 0x13: ")", 0x14: "[", 0x15: "]",
    0x1A: "{", 0x1B: "}", 0x20: "(", 0x21: ")", 0x22: "[", 0x23: "]",
    0x28: "{", 0x29: "}", 0x68: "[", 0x69: "]", 0x6E: "{", 0x6F: "}",
    0x48: "∮", 0x49: "∮", 0x50: "∑", 0x51: "∏", 0x52: "∫",
    0x58: "∑", 0x59: "∏", 0x5A: "∫",
}
_OMX_TEXT_OPERATOR = {0x48, 0x50, 0x51, 0x52}
_OMX_DISPLAY_LIMITS = {0x58, 0x59}
_TEXT_OPERATOR_DROP = 0.82
_PROSE_WORD = re.compile(r"[^\W\d_]{2,}")
_PRIMES = set("′″‴")
_ARROW = re.compile(r"−{2,}(?:\^\{([^{}]*)\})?−*→")
SIDE_GAP = 6.0
LIMIT_GAP = 4.0
_RELATION = re.compile(r"[=<>≤≥⩽⩾≡≠∈→]|\\xrightarrow")
_DANGLING = re.compile(r"^[=+−\-·×,)\]}]|[=+−\-·×,(\[{]$")
SEED_CODES = {"FORMULA_TEXT_LAYER_UNVERIFIED", "FORMULA_TEXT_LAYER_FRAGMENT"}
MERGE_TYPES = {"Text", "Equation"}


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
    big: bool = False
    text_operator: bool = False

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Rebuilt:
    text: str
    structured: bool
    issues: list[str]
    chars: str


def page_glyphs(page, rect) -> list[Glyph]:
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
    if not glyphs:
        return "", False
    top = max(g.size for g in glyphs)
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
            if g.size < size * 0.9:
                shift = g.baseline - base
                if shift < -size * 0.15:
                    return "^"
                if shift > size * 0.1:
                    return "_"
            return ""

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
    small = Counter(g.c for g in glyphs if not g.big)
    big = Counter(g.c for g in glyphs if g.big)
    if (
        any(small[a] != small[b] for a, b in ("()", "[]", "{}"))
        or big["("] != big[")"] or big["["] != big["]"] or big["}"] > big["{"]
    ):
        issues.append("unbalanced")
    structured = False
    work = list(glyphs)
    for x0, x1, y in sorted(rules, key=lambda r: r[1] - r[0]):
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
    def norm(value: str) -> Counter:
        return Counter(c for c in unicodedata.normalize("NFC", value) if not c.isspace())
    return norm(a) == norm(b)


def _overlaps(a, b, pad: float = 0.0) -> bool:
    return (
        a[0] < b[2] + pad and b[0] < a[2] + pad
        and a[1] < b[3] and b[1] < a[3]
    )


def _near(a, b, pad_x: float, pad_y: float) -> bool:
    return (
        a[0] < b[2] + pad_x and b[0] < a[2] + pad_x
        and a[1] < b[3] + pad_y and b[1] < a[3] + pad_y
    )


def _encoding_problem(text: str) -> bool:
    if encoding_issues(text):
        return True
    return any(unicodedata.category(c) == "Co" for c in text)


def _incomplete(text: str) -> bool:
    core = re.sub(r"\\[A-Za-z]+", " ", text).strip()
    if not core or _DANGLING.search(core):
        return True
    return len(_PROSE_WORD.findall(core)) < 2 and not _RELATION.search(text)


def _has_scripts(glyphs: list[Glyph]) -> bool:
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
    """Merge and rebuild formula regions of one page; return the new blocks."""
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
