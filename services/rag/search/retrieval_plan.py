"""Conservative, inspectable query plans for educational text, not an LLM router."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

PLAN_VERSION = "idp-text-search-plan-5"
_COMPARE = re.compile(r"^(?:so sánh|compare)\s+(.+?)\s+(?:và|với|and|with)\s+(.+?)[?.!]*$", re.I)
# Numbered statement and table-caption labels match the chunker's units (text_units).
_ANCHOR = re.compile(r"(?<!\w)(bài tập|câu hỏi|bài|câu|ví dụ|hoạt động|định nghĩa|định lý|định lí|"
                     r"tính chất|hệ quả|bổ đề|bảng|exercise|problem|question|example|activity|definition|"
                     r"theorem|lemma|corollary|table|section|mục|slide|trang|page)\s+(\d+(?:\.\d+)*)(?!\w|\.\d)", re.I)
_UNACCENTED_ANCHOR = re.compile(r"(?<!\w)(bai tap|cau hoi|bai|cau|vi du|hoat dong|dinh nghia|dinh ly|dinh li|"
                                r"tinh chat|he qua|bo de|bang|muc)\s+(\d+(?:\.\d+)*)(?!\w|\.\d)", re.I)
_ACCENTED_LABEL = dict(zip(("bai tap", "cau hoi", "bai", "cau", "vi du", "hoat dong", "dinh nghia",
                            "dinh ly", "dinh li", "tinh chat", "he qua", "bo de", "bang", "muc"),
                          ("bài tập", "câu hỏi", "bài", "câu", "ví dụ", "hoạt động", "định nghĩa",
                           "định lý", "định lý", "tính chất", "hệ quả", "bổ đề", "bảng", "mục")))
# Both Vietnamese spellings name the same label.
_LABEL_ALIAS = {"định lí": "định lý"}
_STOP = set(
    "a an the is are of in on for to and or with what how which compare versus "
    "và với của là có các những một về ở cho nào gì hãy so sánh sự giữa "
    "tại sao như thế trong khi được cần hỏi nêu biết theo từ đến này đó kia để mà hay hoặc nhưng nếu thì vì bởi do".split()
)


def normalized(text):
    return unicodedata.normalize("NFC", text).casefold()


_LATEX_SCRIPT = re.compile(r"[_^]\{([^{}]*)\}")
_LATEX_BARE_SUBSCRIPT = re.compile(r"(?<=[^\W_])_([^\W_])")
_LATEX_FRACTION = re.compile(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}")
_LATEX_BLACKBOARD = re.compile(r"\\mathbb\{([A-Z])\}")
_LATEX_COMMAND = re.compile(r"\\([A-Za-z]+)")
_ATOM = re.compile(r"[^\W_]+")
_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "phi": "φ", "varphi": "φ", "omega": "ω", "Delta": "Δ", "Omega": "Ω", "Sigma": "Σ",
}
_FUNCTIONS = {"sin", "cos", "tan", "cot", "ln", "log", "exp", "lim", "max", "min"}
# AB² and AB^{2} must give the same term; scripts are already flattened (y_{1} -> y1).
# ℝ and \mathbb{R} give "r", as NFKC does in the Tutor fallback.
_SCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉ℝℕℤℚℂ", "01234567890123456789RNZQC")


def _fraction(match):
    top, bottom = match.group(1).strip(), match.group(2).strip()
    if _ATOM.fullmatch(top) and _ATOM.fullmatch(bottom):
        return f" {top}/{bottom} {top} {bottom} "  # "y1/y2" as typed, and each part
    return f" {top} {bottom} "


def _command(match):
    name = match.group(1)
    if name in _GREEK:
        return f" {_GREEK[name]} "
    if name in _FUNCTIONS:
        return f" {name} "
    return " "


def _flatten_latex(text):
    """Search form of rebuilt math: y_{1} -> y1, \\frac{y_{1}}{y_{2}} -> y1/y2.

    IDP keeps structure in the source text (e^{kt}, not ekt); people type
    "y1(x)", "y1/y2", "cos A", "α". Lexical terms match the flat form; the
    stored text is unchanged.
    """
    text = text.translate(_SCRIPT_DIGITS)
    if "{" not in text and "\\" not in text and "_" not in text:
        return text
    previous = None
    while previous != text:
        previous, text = text, _LATEX_SCRIPT.sub(r"\1", text)
    text = _LATEX_BARE_SUBSCRIPT.sub(r"\1", text)
    previous = None
    while previous != text:
        previous, text = text, _LATEX_FRACTION.sub(_fraction, text)
    text = _LATEX_BLACKBOARD.sub(r" \1 ", text)
    return _LATEX_COMMAND.sub(_command, text).replace("{", " ").replace("}", " ")


def terms(text):
    # Preserve accents, chemical subscripts and unit expressions such as m/s².
    return re.findall(r"[^\W_]+(?:[/·^−+\-][^\W_]+)*", normalized(_flatten_latex(text)), re.UNICODE)


def topic_terms(text):
    return set(terms(text)) - _STOP


_EXERCISE_ALIASES = {"bài", "bài tập", "câu", "câu hỏi", "exercise", "problem", "question"}


def anchors(text, *, accept_unaccented=False):
    text = normalized(text)
    result = {(_LABEL_ALIAS.get(m[1], m[1]), m[2]) for m in _ANCHOR.finditer(text)}
    if accept_unaccented:
        result.update((_ACCENTED_LABEL[m[1]], m[2]) for m in _UNACCENTED_ANCHOR.finditer(text))
    return result


def exercise_anchors(record):
    """Bare practice numbers are task anchors only when the chunker classified them."""
    if record.get("unit_kind") != "exercise":
        return set()
    label = record.get("unit_label", "")
    if record.get("unit_basis") == "numbered_practice_item" and re.fullmatch(r"\d+(?:\.\d+)*", label):
        return {("exercise", label)}
    return {("exercise", number) for name, number in anchors(label)
            if name in _EXERCISE_ALIASES}


def exercise_query_anchors(wanted):
    return {("exercise", number) for name, number in wanted if name in _EXERCISE_ALIASES}


@dataclass(frozen=True)
class SearchRequest:
    query: str
    facets: tuple[str, ...] = ()
    context_hint: str = ""
    scope_source_ids: frozenset[str] | None = None
    focus_source_ids: frozenset[str] = frozenset()


def make_plan(request, *, decompose_comparisons=True, accent_fallback=False):
    if not isinstance(request, SearchRequest):
        raise ValueError("SearchRequest required")
    if not isinstance(request.query, str) or not request.query.strip() or len(request.query) > 8192:
        raise ValueError("query must contain 1..8192 characters")
    if not isinstance(request.context_hint, str) or len(request.context_hint) > 2048:
        raise ValueError("context_hint must be a string of at most 2048 characters")
    if not isinstance(request.facets, tuple) or len(request.facets) > 3 or any(
            not isinstance(x, str) or not x.strip() or len(x) > 512 for x in request.facets):
        raise ValueError("at most three nonempty explicit facets required")
    for value in (request.scope_source_ids, request.focus_source_ids):
        if value is not None and (not isinstance(value, frozenset) or any(
                not isinstance(x, str) or not x for x in value)):
            raise ValueError("source scopes must be explicit frozensets of IDs")
    if request.focus_source_ids is None:
        raise ValueError("focus_source_ids must be an explicit frozenset")
    query = unicodedata.normalize("NFC", request.query).strip()
    facets, basis = list(request.facets), "caller_facets" if request.facets else "original_query"
    match = _COMPARE.fullmatch(query) if decompose_comparisons and not facets else None
    if match and all(1 <= len(x.strip()) <= 120 for x in match.groups()):
        facets, basis = [x.strip() for x in match.groups()], "simple_explicit_comparison"
    raw_queries = list(dict.fromkeys([query] + facets))
    query_anchors = [sorted(anchors(value, accept_unaccented=accent_fallback)) for value in raw_queries]
    if request.context_hint.strip():
        hint = request.context_hint.strip()
        queries = [f"{hint}\n{x}" for x in raw_queries]
    else:
        queries = list(raw_queries)
    return {"version": PLAN_VERSION, "queries": queries, "raw_queries": raw_queries,
        "facets": facets, "basis": basis,
        "anchors": query_anchors[0], "query_anchors": query_anchors,
        "has_context_hint": bool(request.context_hint.strip()),
        "claims_semantic_understanding": False}


def facet_supported(facet, records):
    """Lexical topic mention only, NOT sufficient evidence or answerability."""
    wanted = topic_terms(facet)
    return bool(wanted) and any(wanted <= set(terms(r["text"])) for r in records)
