"""Chunking v8: source blocks, logical parents, bounded splitting, validation levels."""

import copy
import json
import re
from typing import ClassVar

import pytest
from rag.chunking.chunking import (
    CHUNKING_VERSION,
    chunk_text,
    protected_spans,
    split_text,
    validate_chunking,
)
from rag.chunking.text_source import parse_text
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.packing.retrieval_context import expand_context
from rag.retrieval.corpus import chunking_is_current, load_retriever
from rag.search.retrieval_plan import SearchRequest, anchors

from test_rag_core import FakeEncoder, WordCounter


class CountingWords(WordCounter):
    identity: ClassVar = WordCounter.identity

    def __init__(self):
        self.calls = 0
        self.chars = 0

    def count(self, text):
        self.calls += 1
        self.chars += len(text)
        return super().count(text)


def parents(text, max_tokens=200, **kwargs):
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=max_tokens, **kwargs)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    return bundle["parents"]


def kinds(text):
    return [(b["kind"], b["text"]) for b in parse_text(text)]


# --- C04: one block-start predicate at every line -------------------------

def test_table_directly_after_prose_is_a_table():
    text = "Đoạn văn mở đầu.\n| Chất | Ký hiệu |\n| --- | --- |\n| Nước | H2O |\n"
    assert [k for k, _ in kinds(text)] == ["text", "table"]


@pytest.mark.parametrize("formula", ["$$x^2+1=0$$", "\\[x^2+1=0\\]", "$$a$$\n$$b$$"])
def test_display_formula_paragraph_is_math(formula):
    assert [k for k, _ in kinds(formula + "\n")] == ["math"]


def test_display_line_inside_prose_and_two_inline_formulas_stay_prose():
    assert [k for k, _ in kinds("Ta có\n$$x=1$$\nVậy xong.\n")] == ["text"]
    assert [k for k, _ in kinds("$$a$$ và $$b$$\n")] == ["text"]


def test_math_environment_after_prose_is_its_own_block():
    text = "Ta có\n\\begin{align}\na&=b\\\\\nc&=d\n\\end{align}\nVậy xong.\n"
    assert [k for k, _ in kinds(text)] == ["text", "math", "text"]


def test_absolute_value_line_over_dashes_is_a_heading_not_a_table():
    assert [k for k, _ in kinds("Giá trị |x| của số\n---\n\nNội dung.\n")] == ["heading", "text"]


# --- C01: atomic block != atomic parent ----------------------------------

METHOD = ("# Cách giải phương trình bậc hai\n\n"
          "Bước 1: Xác định hệ số a, b, c.\n\nBước 2: Tính biệt thức delta.\n\n"
          "$$\n\\Delta=b^2-4ac\n$$\n\nBước 3: Xét dấu của delta để xác định nghiệm.\n")


def test_formula_stays_in_its_method_parent():
    rows = parents(METHOD)
    assert len(rows) == 1
    parent = rows[0]
    assert parent["kind"] == "text" and not parent["atomic"]
    assert [a["kind"] for a in parent["content_atoms"]] == ["math"]
    atom = parent["content_atoms"][0]
    assert parent["text"][atom["start"]:atom["end"]] == "$$\n\\Delta=b^2-4ac\n$$"


def test_split_never_cuts_inside_a_merged_formula():
    formula = "$$\n" + " + ".join(f"x_{i}" for i in range(12)) + "\n$$"
    text = "# Mục\n\n" + "Câu mở đầu dài về tổng. " * 6 + "\n\n" + formula + "\n\n" + "Câu kết luận. " * 6 + "\n"
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=60)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    joined = [c["text"] for c in bundle["children"]]
    assert any(formula in piece for piece in joined)
    for child in bundle["children"]:
        assert child["budget_fit"] or child["review_flags"]


def test_oversized_formula_is_context_eligible_not_searchable():
    formula = "$$\n" + " + ".join(f"y_{i}" for i in range(80)) + "\n$$"
    text = "# Mục\n\nCông thức tổng quát như sau.\n\n" + formula + "\n\nDùng công thức trên.\n"
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=60)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    held = [c for c in bundle["children"] if not c["retrieval_eligible"]]
    assert len(held) == 1 and held[0]["text"] == formula
    assert held[0]["review_flags"] == ["indivisible_text_exceeds_budget"]
    assert held[0]["context_eligible"] is True
    assert sum(c["retrieval_eligible"] for c in bundle["children"]) == 2
    assert bundle["report"]["context_eligible_children"] == 1


def test_unclosed_formula_stays_a_separate_flagged_parent():
    rows = parents("# Mục\n\nTa có\n\n$$\nx = 1\n")
    math = [p for p in rows if p["kind"] == "math"]
    assert len(math) == 1 and math[0]["atomic"] and not math[0]["source_closed"]


def test_table_keeps_its_own_parent_and_unit_id():
    text = ("Ví dụ 1. Cho bảng sau.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nTính tổng.\n")
    rows = parents(text)
    assert [p["kind"] for p in rows] == ["text", "table", "text"]
    assert len({p["unit_id"] for p in rows}) == 1 and rows[0]["unit_id"]


# --- C02: statement labels close tasks -----------------------------------

def test_definition_after_example_solution_is_its_own_unit():
    text = ("Ví dụ 1. Tìm nghiệm.\n\nLời giải: Tính delta.\n\n"
            "Định nghĩa. Phương trình bậc hai có dạng tổng quát.\n\nVí dụ 2. Tìm nghiệm khác.\n")
    rows = parents(text)
    assert [(p["unit_kind"], p["unit_label"]) for p in rows] == [
        ("example", "Ví dụ 1"), ("statement", "Định nghĩa"), ("example", "Ví dụ 2")]
    assert rows[1]["context_path"] == ["Định nghĩa"]


def test_remark_inside_an_example_stays_with_the_example():
    text = "Ví dụ 1. Tìm nghiệm.\n\nLời giải: Tính delta.\n\nChú ý: delta có thể âm.\n"
    assert [p["unit_label"] for p in parents(text)] == ["Ví dụ 1"]


@pytest.mark.parametrize("line", [
    "Định nghĩa của hàm số là quy tắc.",       # a word in a sentence
    "mệnh đề. Có thể viết mệnh đề này.",       # a wrapped sentence, lowercase
    "Định lý 6",                               # an index entry with a page
    "Mệnh đề\n\nMệnh đề phủ định",             # a chapter topic word
])
def test_statement_label_false_positives(line):
    assert all(p["unit_kind"] == "prose" for p in parents("# Mục\n\n" + line + "\n"))


def test_numbered_theorem_is_a_unit_and_a_query_anchor():
    rows = parents("# Chương 3\n\nĐịnh lý 3.7.2. Nếu hàm liên tục thì khả tích.\n")
    assert rows[0]["unit_kind"] == "statement" and rows[0]["unit_label"] == "Định lý 3.7.2"
    assert anchors("định lí 3.7.2 phát biểu gì") == {("định lý", "3.7.2")}
    assert anchors("dinh ly 3.7.2", accept_unaccented=True) >= {("định lý", "3.7.2")}


# --- C03 and the instruction bug: solution scope -------------------------

def test_next_exercise_after_a_solution_starts_a_new_unit():
    text = "# Luyện tập\n\n1. Bài đầu.\nLời giải: Kết quả.\n\n2. Bài tiếp theo.\n3. Bài khác.\n"
    assert [p["unit_label"] for p in parents(text)] == ["1", "2", "3"]


def test_numbered_solution_steps_stay_in_the_solution():
    text = ("# Luyện tập\n\n1. Giải phương trình.\nLời giải:\n1. Chuyển vế.\n2. Chia hai vế.\n\n"
            "Ghi chú cuối.\n")
    rows = parents(text)
    # "2." is both the next task and the next solution step: kept, and flagged.
    assert [p["unit_label"] for p in rows] == ["1"]
    assert rows[0]["unit_boundary_ambiguous"] is True


def test_instruction_starting_with_giai_does_not_hide_exercises():
    text = "# Luyện tập\n\nGiải các phương trình sau:\n\n1. x + 1 = 0.\n\n2. x - 2 = 0.\n\n3. 2x = 4.\n"
    labels = [p["unit_label"] for p in parents(text)]
    assert labels == ["", "1", "2", "3"]


# --- C05: bounded greedy ------------------------------------------------

def test_bounded_greedy_is_linear_and_keeps_exact_partition():
    def build(n):
        text = "# Bài\n\n" + "\n\n".join(
            f"Đoạn {i} nói về phương trình bậc hai và nghiệm." for i in range(n)) + "\n"
        counter = CountingWords()
        bundle = chunk_text(text, source_id="s", counter=counter, max_tokens=64, validation="fast")
        assert bundle["report"]["pass"], bundle["report"]["errors"]
        children = bundle["children"]
        assert all(c["budget_fit"] and c["retrieval_eligible"] for c in children)
        assert "".join(c["text"] for c in children) == bundle["parents"][0]["text"]
        assert counter.calls == (bundle["report"]["build_counter"]["counter_calls"]
                                 + bundle["report"]["validation_counter"]["counter_calls"])
        return bundle["report"]["build_counter"]["tokenized_chars"] / len(text)

    # Re-tokenizing the whole remainder on every cut doubles this ratio when
    # the text doubles; bounded windows keep it flat.
    small, large = build(200), build(800)
    assert large < 1.3 * small and large < 20


def test_split_text_inline_protection_switch():
    text = "aa $x + y$ bb " * 3
    with_inline = split_text(text, [], WordCounter(), 9)
    assert all(not (a < p < b) for p in (s for s, _, _ in with_inline)
               for a, b in protected_spans(text))
    assert protected_spans("\\[a\n\nb\\]") == []  # a blank line closes no formula


# --- C06: validation levels ---------------------------------------------

def _bundle():
    text = METHOD + "\n# Luyện tập\n\n1. Bài đầu.\nLời giải: Kết quả.\n\n2. Bài tiếp theo.\n"
    return text, chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=24)


@pytest.mark.parametrize("level", ["fast", "full"])
def test_validation_levels_accept_a_built_bundle(level):
    text, bundle = _bundle()
    assert validate_chunking(bundle, text, WordCounter(), level=level) == []


@pytest.mark.parametrize("level", ["fast", "full"])
@pytest.mark.parametrize("tamper", ["text", "count", "eligible", "context", "atoms", "flags"])
def test_both_levels_reject_tampering(level, tamper):
    text, bundle = _bundle()
    bundle = copy.deepcopy(bundle)
    child = bundle["children"][0]
    if tamper == "text":
        child["text"] = child["text"] + " "
    elif tamper == "count":
        child["budget_count"] -= 1
    elif tamper == "eligible":
        child["review_flags"] = ["indivisible_text_exceeds_budget"]
    elif tamper == "context":
        child["context_eligible"] = True
    elif tamper == "atoms":
        bundle["parents"][0]["content_atoms"] = []
    else:
        child["review_flags"] = ["made_up_flag"]
        child["retrieval_eligible"] = False
    assert validate_chunking(bundle, text, WordCounter(), level=level)


def test_only_full_level_rederives_boundaries():
    text, bundle = _bundle()
    bundle = copy.deepcopy(bundle)
    parent = next(p for p in bundle["parents"] if len(p["child_ids"]) >= 2)
    first, second = (next(c for c in bundle["children"] if c["id"] == cid) for cid in parent["child_ids"][:2])
    cut = first["parent_end"] - 1
    while not parent["text"][cut - 1].isspace():
        cut -= 1
    from rag.chunking.chunking import _child_spans
    from rag.chunking.chunk_views import index_text
    parents_by_id = {p["id"]: p for p in bundle["parents"]}
    for child, (a, b) in ((first, (first["parent_start"], cut)), (second, (cut, second["parent_end"]))):
        child.update(parent_start=a, parent_end=b, text=parent["text"][a:b],
                     source_spans=_child_spans(parent, a, b))
        child["search_text"] = index_text(child, parents_by_id)
        child["index_body"] = child["search_text"][len(" > ".join(parent["context_path"])) + 2:]
        child["budget_count"] = child["token_count"] = WordCounter().count(child["search_text"])
        child["budget_fit"] = child["budget_count"] <= 24
    assert validate_chunking(bundle, text, WordCounter(), level="fast") == []
    assert validate_chunking(bundle, text, WordCounter(), level="full")


# --- links to indexing, retrieval and packing ----------------------------

def test_packing_shows_an_oversized_formula_beside_its_seed():
    formula = "$$\n" + " + ".join(f"z_{i}" for i in range(80)) + "\n$$"
    text = "# Mục\n\nCông thức tổng quát cho tổng hữu hạn.\n\n" + formula + "\n\nDùng công thức trên.\n"
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=60)
    seed = next(c for c in bundle["children"] if c["retrieval_eligible"])
    every = {c["id"] for c in bundle["children"]}
    context = expand_context(bundle, [seed["id"]], allowed_child_ids=every, counter=WordCounter(),
                             max_tokens=1000, mode="neighbors")
    assert formula in context["context"]
    held = next(c for c in bundle["children"] if c["context_eligible"])
    alone = expand_context(bundle, [held["id"]], allowed_child_ids=every, counter=WordCounter(),
                           max_tokens=1000, mode="neighbors")
    assert alone["items"] == []  # never a seed
    revoked = expand_context(bundle, [seed["id"]], allowed_child_ids=every - {held["id"]},
                             counter=WordCounter(), max_tokens=1000, mode="neighbors")
    assert formula not in revoked["context"]


def test_corpus_version_probe_and_retriever_unit_expansion(tmp_path):
    text = ("# Chương 3\n\nĐịnh lý 3.7.2. Nếu hàm liên tục trên đoạn thì khả tích trên đoạn đó. "
            + "Chứng minh dùng tổng Riemann và tính liên tục đều. " * 6 + "\n")
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", text)], tmp_path, encoder=encoder, max_tokens=40)
    assert chunking_is_current(tmp_path)
    retriever = load_retriever(tmp_path, encoder=encoder)[0]
    unit_children = [c for c in retriever.children.values() if c["unit_label"] == "Định lý 3.7.2"]
    assert len(unit_children) >= 2
    result = retriever.retrieve(SearchRequest("định lí 3.7.2"), authorize=lambda: set(retriever.children))
    pass_trace = result["trace"]["passes"][0]
    assert set(pass_trace["primary_seeds"]) | set(pass_trace["related_unit_seeds"]) >= {
        c["id"] for c in unit_children[:2]}
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    assert manifest["chunking_version"] == CHUNKING_VERSION
    del manifest["chunking_version"]  # how every pre-v8 corpus looks
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert not chunking_is_current(tmp_path)
    assert CHUNKING_VERSION == "idp-text-chunking-10"


def test_canonical_formula_and_table_reach_the_chunker_structured():
    from rag.indexing.canonical_text import canonical_to_markdown

    rows = "".join(f"<tr><td>{1900 + i}</td><td>{30 + i}</td></tr>" for i in range(30))
    artifact = {"pages": [{"page_number": 1, "blocks": [
        {"type": "SectionHeader", "text": "Mô hình suy giảm"},
        {"type": "Text", "text": "Số hạt nhân thỏa mãn phương trình"},
        {"type": "Equation", "text": "N'(t) = -kN(t)", "markdown": "$$\nN'(t) = -kN(t)\n$$"},
        {"type": "Text", "text": "với k là hằng số phân rã."},
        {"type": "Table", "text": "flattened", "markdown": "<table><tr><th>Năm</th><th>Số thỏ</th></tr>"
                                                          + rows + "</table>"},
    ]}]}
    text, _ = canonical_to_markdown(artifact)
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=48)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    prose, table = bundle["parents"]
    assert [a["kind"] for a in prose["content_atoms"]] == ["math"]
    assert "phương trình\n\n$$\nN'(t) = -kN(t)\n$$\n\nvới k" in prose["text"]
    table_children = [c for c in bundle["children"] if c["parent_id"] == table["id"]]
    assert table["kind"] == "table" and len(table_children) > 1
    assert all(c["search_text"].count("| Năm | Số thỏ |") == 1 for c in table_children)


def test_counter_identity_mismatch_is_still_rejected():
    text, bundle = _bundle()

    class Other(WordCounter):
        identity: ClassVar = {"kind": "other", "unit": "tokens", "version": 2}

    assert "tokenizer identity mismatch" in validate_chunking(bundle, text, Other(), level="fast")


def test_report_counts_logical_structure():
    report = chunk_text(METHOD, source_id="s", counter=WordCounter(), max_tokens=200)["report"]
    assert report["mixed_content_parents"] == 1 and report["atomic_parent_count"] == 0
    assert re.fullmatch(r"\d+", str(report["build_counter"]["counter_calls"]))
