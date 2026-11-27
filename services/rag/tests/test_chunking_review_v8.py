"""Regressions for the chunking v8 review (V8-01..V8-08), fixed in idp-text-chunking-9."""

import copy

import pytest
from rag.chunking.chunk_views import index_text
from rag.chunking.chunking import _child_spans, chunk_text, validate_chunking
from rag.chunking.text_source import parse_text
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.retrieval.corpus import load_retriever
from rag.search.retrieval_plan import SearchRequest, anchors

from test_rag_core import FakeEncoder, WordCounter


def build(text, max_tokens=200):
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=max_tokens)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    return bundle


def resplit(bundle, parent_index, cuts):
    """Rewrite one parent's children at `cuts`, with consistent text/spans/counts."""
    bundle = copy.deepcopy(bundle)
    parent = bundle["parents"][parent_index]
    template = next(c for c in bundle["children"] if c["parent_id"] == parent["id"])
    bundle["children"] = [c for c in bundle["children"] if c["parent_id"] != parent["id"]]
    bounds = [0, *cuts, len(parent["text"])]
    parents_by_id = {p["id"]: p for p in bundle["parents"]}
    parent["child_ids"] = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        child = dict(template, id=f"{template['id']}-{i}", parent_start=a, parent_end=b,
                     text=parent["text"][a:b], source_spans=_child_spans(parent, a, b))
        child["search_text"] = index_text(child, parents_by_id)
        prefix = len(" > ".join(parent["context_path"])) + 2 if parent["context_path"] else 0
        child["index_body"] = child["search_text"][prefix:]
        child["budget_count"] = child["token_count"] = WordCounter().count(child["search_text"])
        child["budget_fit"] = child["budget_count"] <= bundle["config"]["max_input_budget"]
        child["review_flags"], child["retrieval_eligible"], child["context_eligible"] = [], True, False
        bundle["children"].append(child)
        parent["child_ids"].append(child["id"])
    return bundle


# --- V8-01: fast validation checks structural invariants ------------------

FORMULA = "# Mục\n\nTa có công thức sau đây.\n\n$$\nx + y = 2\n$$\n\nVậy xong.\n"


@pytest.mark.parametrize("level", ["fast", "full"])
def test_cut_inside_a_formula_is_rejected(level):
    bundle = build(FORMULA)
    atom = bundle["parents"][0]["content_atoms"][0]
    tampered = resplit(bundle, 0, [atom["start"] + 6])
    errors = validate_chunking(tampered, FORMULA, WordCounter(), level=level)
    assert errors
    if level == "fast":
        assert any("cut inside a formula/code atom" in e for e in errors)


def test_fast_validation_rejects_table_row_and_combining_cuts():
    rows = "".join(f"| {i} | giá trị {i} |\n" for i in range(4))
    text = "| Năm | Số thỏ |\n| --- | --- |\n" + rows
    bundle = build(text)
    tampered = resplit(bundle, 0, [text.index("giá trị 1")])
    assert any("table row" in e for e in validate_chunking(tampered, text, WordCounter(), level="fast"))

    decomposed = "# Mục\n\nTi\u0301nh to\u0301an nghi\u0323\u0302m.\n"
    bundle = build(decomposed)
    cut = bundle["parents"][0]["text"].index("\u0301")
    tampered = resplit(bundle, 0, [cut])
    assert any("combining" in e for e in validate_chunking(tampered, decomposed, WordCounter(), level="fast"))


def test_fast_validation_rejects_a_size_hold_on_fitting_content():
    bundle = copy.deepcopy(build(FORMULA))
    child = bundle["children"][0]
    child.update(review_flags=["indivisible_text_exceeds_budget"], retrieval_eligible=False,
                 context_eligible=True)
    errors = validate_chunking(bundle, FORMULA, WordCounter(), level="fast")
    assert any("size hold on content that fits" in e for e in errors)


# --- V8-02: an unclosed formula is isolated, not swallowing the rest -------

@pytest.mark.parametrize("opener", ["$$", "\\[", "\\begin{align}"])
def test_unclosed_formula_stops_at_the_next_structural_boundary(opener):
    text = f"# Bài 1\n\n{opener}\nx = 1\n\n# Bài 2\n\nĐịnh nghĩa. Mệnh đề là câu khẳng định.\n"
    blocks = parse_text(text)
    assert [(b["kind"], b.get("closed")) for b in blocks] == [
        ("heading", None), ("math", False), ("heading", None), ("text", None)]
    bundle = build(text)
    definition = next(c for c in bundle["children"] if c["unit_kind"] == "statement")
    assert definition["retrieval_eligible"] and definition["section_path"] == ["Bài 2"]
    held = next(c for c in bundle["children"] if c["kind"] == "math")
    assert held["text"] == f"{opener}\nx = 1" and "unclosed_source_block" in held["review_flags"]


def test_unclosed_formula_also_stops_at_a_heading_without_blank_line():
    blocks = parse_text("$$\nx = 1\n# Bài 2\nNội dung.\n")
    assert [b["kind"] for b in blocks] == ["math", "heading", "text"]


def test_closed_multiline_formula_is_unchanged():
    blocks = parse_text("$$\na = b\n\\\\\nc = d\n$$\n")
    assert [(b["kind"], b["closed"]) for b in blocks] == [("math", True)]


# --- V8-03: independent formulas are independent atoms --------------------

def test_twenty_one_line_formulas_are_twenty_atoms():
    text = "# Mục\n\n" + "\n".join(f"$$x + {i} = {i + 1}$$" for i in range(20)) + "\n"
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=16)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    assert len(bundle["parents"][0]["content_atoms"]) == 20
    assert all(c["retrieval_eligible"] for c in bundle["children"])
    assert all(c["text"].count("$$") % 2 == 0 for c in bundle["children"])


def test_linked_formulas_stay_one_atom():
    text = "# Mục\n\n\\begin{align}\nx + y &= 2\\\\\nx - y &= 0\n\\end{align}\n"
    assert len(build(text)["parents"][0]["content_atoms"]) == 1


# --- V8-04: solution steps vs next exercise --------------------------------

def test_next_exercise_after_numbered_solution_steps():
    text = ("# Luyện tập\n\n1. Bài đầu.\nLời giải:\n1. Đổi đơn vị.\n2. Tính kết quả.\n\n"
            "2. Bài tiếp theo.\n3. Bài khác.\n")
    rows = build(text)["parents"]
    assert [p["unit_label"] for p in rows] == ["1", "2", "3"]
    assert "2. Tính kết quả." in rows[0]["text"] and not any(p["unit_boundary_ambiguous"] for p in rows)


# --- V8-05: a general method after an example ------------------------------

def test_method_after_solution_opens_a_unit_but_alternative_method_stays():
    text = ("Ví dụ 1. Tìm nghiệm.\n\nLời giải: Tính delta.\n\n"
            "Phương pháp giải: Đưa về dạng tích rồi xét từng nhân tử.\n")
    rows = build(text)["parents"]
    assert [(p["unit_kind"], p["unit_subtype"]) for p in rows] == [("example", ""), ("remark", "procedure")]
    alternative = "Ví dụ 1. Tìm nghiệm.\n\nLời giải: Tính delta.\n\nCách giải 2: Dùng định lý Vi-ét.\n"
    assert [p["unit_label"] for p in build(alternative)["parents"]] == ["Ví dụ 1"]
    prompt = "Ví dụ 1. Tìm nghiệm.\n\nCách giải: Đưa về dạng tích.\n"
    assert [p["unit_label"] for p in build(prompt)["parents"]] == ["Ví dụ 1"]


# --- V8-06: tables share a unit with their caption and explanation ---------

TABLE = "| Chất | Khối lượng mol |\n| --- | --- |\n| Nước | 18 |\n| Oxygen | 32 |"


@pytest.mark.parametrize("caption_first", [True, False])
def test_caption_links_table_and_explanation(caption_first):
    caption = "Bảng 2. Khối lượng mol của một số chất."
    body = [caption, TABLE] if caption_first else [TABLE, caption]
    text = "# Mục\n\nĐoạn mở đầu của mục.\n\n" + "\n\n".join(body) + "\n\nNước nhẹ hơn oxygen.\n"
    rows = build(text)["parents"]
    table = next(p for p in rows if p["kind"] == "table")
    linked = [p for p in rows if p["unit_id"] == table["unit_id"]]
    assert table["unit_kind"] == "caption" and table["unit_label"] == "Bảng 2"
    assert any("Nước nhẹ hơn oxygen." in p["text"] for p in linked)
    assert any(caption in p["text"] for p in linked)
    assert rows[0]["unit_kind"] == "prose"  # the introduction is not absorbed
    assert anchors("bảng 2 cho biết gì") == {("bảng", "2")}
    assert ("bảng", "2") in anchors("bang 2", accept_unaccented=True)


def test_caption_inside_an_example_stays_in_the_example():
    text = "Ví dụ 1. Cho bảng sau.\n\nBảng 1. Số liệu.\n\n" + TABLE + "\n\nTính tổng.\n"
    rows = build(text)["parents"]
    assert {p["unit_label"] for p in rows} == {"Ví dụ 1"}


# --- V8-07: context-only formulas reach the packed context end to end ------

def test_retriever_packs_an_oversized_formula_beside_its_seed(tmp_path):
    formula = "$$\n" + " + ".join(f"z_{i}" for i in range(80)) + "\n$$"
    text = "# Mục\n\nCông thức tổng quát cho tổng hữu hạn.\n\n" + formula + "\n\nDùng công thức trên.\n"
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", text)], tmp_path, encoder=encoder, max_tokens=60)
    retriever = load_retriever(tmp_path, encoder=encoder)[0]
    held = next(c for c in retriever.children.values() if c["context_eligible"])
    assert held["id"] not in retriever.row_ids  # never indexed
    every = set(retriever.children)
    result = retriever.retrieve(SearchRequest("công thức tổng quát tổng hữu hạn"), authorize=lambda: every)
    assert held["id"] not in result["ranked_child_ids"]
    assert formula in result["context"]["context"]
    denied = retriever.retrieve(SearchRequest("công thức tổng quát tổng hữu hạn"),
                                authorize=lambda: every - {held["id"]})
    assert formula not in denied["context"]["context"]


# --- V8-08: explicit labels carry a subtype -------------------------------

@pytest.mark.parametrize(("label", "kind", "subtype"), [
    ("Định nghĩa.", "statement", "definition"), ("Định lí 2.", "statement", "theorem"),
    ("Hệ quả:", "statement", "corollary"), ("Quy tắc.", "statement", "rule"),
    ("Chú ý:", "remark", "note"), ("Nhận xét.", "remark", "remark"),
    ("Cách giải:", "remark", "procedure"),
])
def test_statement_subtypes(label, kind, subtype):
    rows = build(f"# Mục\n\n{label} Nội dung của nhãn.\n")["parents"]
    assert (rows[0]["unit_kind"], rows[0]["unit_subtype"]) == (kind, subtype)
    children = build(f"# Mục\n\n{label} Nội dung của nhãn.\n")["children"]
    assert children[0]["unit_subtype"] == subtype
