import re
from dataclasses import dataclass, asdict

try:
    from latex2mathml.converter import convert as latex_to_mathml
except Exception:  # pragma: no cover - optional dependency
    latex_to_mathml = None


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
    """Remove mixed-bracket interval notation such as [0; pi/2) or (-inf; 0]."""
    previous = None
    while previous != s:
        previous = s
        s = re.sub(r"[\[\(][^\[\]\(\)]*;[^\[\]\(\)]*[\]\)]", "", s)
    return s


def _outside_text_groups(s: str) -> str:
    # Delimiters inside \text{...} are prose punctuation, not math delimiters.
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
    if s.count(r"\left") != s.count(r"\right"):
        return ValidationResult(False, "left-right", "left/right mismatch")
    if latex_to_mathml is not None:
        try:
            latex_to_mathml(s)
            return ValidationResult(True, "mathml")
        except Exception as exc:
            # Arrays and some textbook constructs are not supported by
            # latex2mathml; structural checks above still apply.
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
    """Detect balanced LaTeX that still lost operands during OCR."""
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
