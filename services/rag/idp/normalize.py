import html
import re
import unicodedata

# Domain lexicon for Vietnamese lower-secondary math. Used to avoid
# correcting arbitrary prose while still fixing recurring scan/OCR errors.
MATH_TERMS = {
    "tập hợp", "phần tử", "tính chất", "giao hoán", "kết hợp", "phân phối",
    "số tự nhiên", "chẵn", "lẻ", "ước", "bội", "nguyên tố", "hợp số",
    "phân tích", "thừa số", "chia hết", "phép chia", "thương", "dư",
    "trục đối xứng", "đối xứng", "hình thang cân", "lục giác đều",
    "ví dụ", "luyện tập", "bài tập", "giải", "tính", "cần", "hãy",
    "số bị chia", "số chia", "tích", "hiệu", "tổng",
}

# Order matters: longer / more specific patterns first.
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
_NUMBER_SEQ_RE = re.compile(
    rf"\b{_NUMBER_WORD}(?:\s+{_NUMBER_WORD}){{2,}}\b", re.I
)
_NUMBER_UNIT_RE = re.compile(
    r"\b(?:trăm|nghìn|ngàn|triệu|tỉ|tỷ|tì|mươi|mười|chục|linh|lẻ)\b", re.I
)
_NUMBER_WORD_FIXES = {"bón": "bốn", "tì": "tỉ", "bày": "bảy"}


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
            changes.append({
                "code": "ocr:number-word", "from": word, "to": fixed,
            })
            return fixed

        return re.sub(r"\b\w+\b", fix_word, sequence)

    return _NUMBER_SEQ_RE.sub(fix_sequence, text)


def _apply_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def normalize_text(
    text: str,
    profile: str | object | None = "general",
) -> tuple[str, list[dict]]:
    """Apply safe normalization, then optional domain-specific corrections.

    Domain corrections default off: arbitrary uploads must not be rewritten by
    a Vietnamese math lexicon. Math callers pass an explicit profile (or
    ``auto`` when the page is clearly math-heavy).
    """
    if not text:
        return "", []
    from .profiles import resolve_profile

    resolved = resolve_profile(profile, text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = SPACE_RE.sub(" ", text).strip()
    changes = []
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
    """Return visible prose + list of LaTeX expressions from marker HTML."""
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
    """Normalize prose while preserving intentional line breaks / bullets."""
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
    """Convert marker HTML to Markdown while preserving inline math position."""
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
        display = "display=\"block\"" in match.group(0) or "block-type=\"Equation\"" in match.group(0)
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
    """Canonical key for exact-match evaluation (not for display)."""
    s = normalize_latex(latex)
    s = s.replace("\\ ", "").rstrip(";.")
    s = s.replace(" ", "")
    s = s.replace(".", "*").replace("\\cdot", "*").replace("\\times", "*")
    s = s.replace("{", "").replace("}", "")
    return s.lower()


def math_to_inline(latex: str) -> str:
    s = (latex or "").strip()
    return f"${s}$" if s else ""
