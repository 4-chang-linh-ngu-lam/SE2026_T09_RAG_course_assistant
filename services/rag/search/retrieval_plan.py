"""Conservative, inspectable query plans for educational text, not an LLM router."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

PLAN_VERSION = "idp-text-search-plan-2"
_COMPARE = re.compile(r"^(?:so sánh|compare)\s+(.+?)\s+(?:và|với|and|with)\s+(.+?)[?.!]*$", re.I)
_ANCHOR = re.compile(r"(?<!\w)(bài tập|câu hỏi|bài|câu|ví dụ|hoạt động|exercise|problem|question|example|activity|section|mục|slide|trang|page)\s+(\d+(?:\.\d+)*)(?!\w|\.\d)", re.I)
_UNACCENTED_ANCHOR = re.compile(r"(?<!\w)(bai tap|cau hoi|bai|cau|vi du|hoat dong|muc)\s+(\d+(?:\.\d+)*)(?!\w|\.\d)", re.I)
_ACCENTED_LABEL = dict(zip(("bai tap", "cau hoi", "bai", "cau", "vi du", "hoat dong", "muc"),
                          ("bài tập", "câu hỏi", "bài", "câu", "ví dụ", "hoạt động", "mục")))
_STOP = set("a an the is are of in on for to and or with what how which compare versus và với của là có các những một về ở cho nào gì hãy so sánh sự giữa".split())


def normalized(text):
    return unicodedata.normalize("NFC", text).casefold()


_LATEX_SCRIPT = re.compile(r"[_^]\{([^{}]*)\}")
_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+")


def _flatten_latex(text):
    """Search form of rebuilt math: y_{1} -> y1, \\frac{a}{b} -> a b.

    IDP keeps structure in the source text (e^{kt}, not ekt); people type
    "y1(x)". Lexical terms match the flat form; the stored text is unchanged.
    """
    if "{" not in text and "\\" not in text:
        return text
    previous = None
    while previous != text:
        previous, text = text, _LATEX_SCRIPT.sub(r"\1", text)
    return _LATEX_COMMAND.sub(" ", text).replace("{", " ").replace("}", " ")


def terms(text):
    # Preserve accents, chemical subscripts and unit expressions such as m/s².
    return re.findall(r"[^\W_]+(?:[/·^−+\-][^\W_]+)*", normalized(_flatten_latex(text)), re.UNICODE)


def topic_terms(text):
    return set(terms(text)) - _STOP


_EXERCISE_ALIASES = {"bài", "bài tập", "câu", "câu hỏi", "exercise", "problem", "question"}


def anchors(text, *, accept_unaccented=False):
    text = normalized(text)
    result = {(m[1], m[2]) for m in _ANCHOR.finditer(text)}
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
    queries = list(dict.fromkeys([query] + facets))
    query_anchors = [sorted(anchors(value, accept_unaccented=accent_fallback)) for value in queries]
    if request.context_hint.strip():
        queries = [f"{request.context_hint.strip()}\n{x}" for x in queries]
    return {"version": PLAN_VERSION, "queries": queries, "facets": facets, "basis": basis,
        "anchors": query_anchors[0], "query_anchors": query_anchors,
        "has_context_hint": bool(request.context_hint.strip()),
        "claims_semantic_understanding": False}


def facet_supported(facet, records):
    """Lexical topic mention only, NOT sufficient evidence or answerability."""
    wanted = topic_terms(facet)
    return bool(wanted) and any(wanted <= set(terms(r["text"])) for r in records)
