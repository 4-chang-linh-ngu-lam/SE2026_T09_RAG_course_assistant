"""Regressions and architectural fixes for idp-text-chunking-10."""

import copy
import re
from typing import ClassVar

import pytest
from rag.chunking import (
    CHUNKING_VERSION,
    MemoCounter,
    chunk_text,
    index_parts,
    materialize,
    validate_chunking,
)
from rag.chunking.chunking import split_text
from rag.chunking.cli import main as cli_main
from rag.chunking.text_source import parse_text
from rag.chunking.validator import validate_chunking as validator_validate
from rag.indexing.canonical_text import canonical_to_markdown, locate_spans_in_canonical
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.retrieval.corpus import load_retriever

from test_rag_core import FakeEncoder, WordCounter


def test_version_and_split_module_entrypoints():
    assert CHUNKING_VERSION == "idp-text-chunking-10"
    assert validator_validate is validate_chunking
    assert callable(cli_main)


@pytest.mark.parametrize("fence", ["```python", "~~~"])
def test_unclosed_code_fence_is_isolated_without_swallowing_document(fence):
    text = (
        f"# Phần 1\n\n{fence}\nx = 1\ny = 2\n\n"
        "# Phần 2\n\nĐịnh nghĩa. Nội dung sau khối code lỗi vẫn phải truy hồi được.\n"
    )
    blocks = parse_text(text)
    assert [(b["kind"], b.get("closed")) for b in blocks] == [
        ("heading", None),
        ("code", False),
        ("heading", None),
        ("text", None),
    ]
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=64)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    code_child = next(c for c in bundle["children"] if c["kind"] == "code")
    assert "unclosed_source_block" in code_child["review_flags"]
    assert not code_child["retrieval_eligible"]
    later = next(c for c in bundle["children"] if c["unit_kind"] == "statement")
    assert later["retrieval_eligible"]
    assert later["section_path"] == ["Phần 2"]


def test_unclosed_code_fence_stops_at_adjacent_heading_or_math():
    blocks = parse_text("```\nx = 1\n# Tiêu đề kế tiếp\nVăn bản.\n")
    assert [(b["kind"], b.get("closed")) for b in blocks] == [
        ("code", False),
        ("heading", None),
        ("text", None),
    ]
    math_blocks = parse_text("~~~\nx = 1\n$$\na + b = c\n$$\n")
    assert [(b["kind"], b.get("closed")) for b in math_blocks] == [
        ("code", False),
        ("math", True),
    ]


def test_valid_closed_code_fence_with_blank_lines_and_comments_stays_whole():
    code = "```python\n# comment heading lookalike\nx = 1\n\ny = 2\n```"
    blocks = parse_text(code + "\n\nSau đó.\n")
    assert [(b["kind"], b.get("closed")) for b in blocks] == [("code", True), ("text", None)]
    assert blocks[0]["text"] == code


def test_greedy_avoids_tiny_orphan_paragraph_chunk_when_sentence_fits():
    intro = "Mở đầu ngắn."
    body = " ".join(f"Câu số {i} trình bày nội dung chi tiết rõ ràng hơn." for i in range(1, 7))
    text = f"{intro}\n\n{body}"
    ranges = split_text(text, [], WordCounter(), limit=45)
    first_text = text[ranges[0][0] : ranges[0][1]]
    assert first_text.startswith(intro)
    assert "Câu số 1" in first_text
    assert len(ranges) >= 2
    assert "".join(text[a:b] for a, b, _ in ranges) == text


def test_greedy_still_cuts_at_paragraph_before_oversized_atom():
    formula = "$$\n" + " + ".join(f"x_{i}" for i in range(40)) + "\n$$"
    text = f"Đoạn dẫn ngắn.\n\n{formula}\n\nKết luận."
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=24)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    eligible = [c["text"] for c in bundle["children"] if c["retrieval_eligible"]]
    assert eligible[0].strip() == "Đoạn dẫn ngắn."
    held = [c for c in bundle["children"] if not c["retrieval_eligible"]]
    assert len(held) == 1 and held[0]["text"].strip() == formula


def test_index_parts_handles_empty_and_nonempty_context_paths():
    parents = {
        "p0": {
            "id": "p0",
            "source_id": "doc",
            "text": "Nội dung mẫu.",
            "source_spans": [{"start": 0, "end": 13, "source_start": 0, "source_end": 13}],
        }
    }
    search_empty, body_empty = index_parts(
        {"text": "Nội dung mẫu.", "parent_id": "p0", "source_id": "doc", "context_path": []},
        parents,
    )
    assert search_empty == "Nội dung mẫu." and body_empty == "Nội dung mẫu."

    search_blank, body_blank = index_parts(
        {"text": "Nội dung mẫu.", "parent_id": "p0", "source_id": "doc", "context_path": [""]},
        parents,
    )
    assert search_blank == "Nội dung mẫu." and body_blank == "Nội dung mẫu."


def test_materialize_fails_closed_on_missing_parent_child_and_preserves_spans():
    table = (
        "| Chất | Khối lượng |\n| --- | --- |\n"
        + "".join(f"| Chất {i} | {10 + i} |\n" for i in range(12))
    )
    bundle = chunk_text(table, source_id="s", counter=WordCounter(), max_tokens=30)
    assert bundle["report"]["pass"]
    children = {c["id"]: c for c in bundle["children"]}
    parents = {p["id"]: p for p in bundle["parents"]}
    eligible = set(children)
    later_child = bundle["children"][-1]
    record = {
        "id": later_child["id"],
        "level": "child",
        "source_id": later_child["source_id"],
        "section_path": list(later_child["section_path"]),
        "context_path": list(later_child["context_path"]),
        "parent_id": later_child["parent_id"],
        "parent_start": later_child["parent_start"],
        "parent_end": later_child["parent_end"],
        "text": later_child["text"],
        "search_text": later_child["search_text"],
        "source_spans": later_child["source_spans"],
        "child_ids": [later_child["id"]],
    }
    view = materialize(record, children, parents, eligible)
    assert view is not None
    for span in view["source_spans"]:
        assert view["text"][span["start"] : span["end"]] == table[span["source_start"] : span["source_end"]]

    broken_parents = copy.deepcopy(parents)
    broken_parents[later_child["parent_id"]]["child_ids"].append("missing-child-id")
    assert materialize(record, children, broken_parents, eligible) is None


@pytest.mark.parametrize(
    "intro",
    [
        "Dựa vào đoạn tư liệu sau: Phong trào diễn ra sôi nổi.",
        "Cho đoạn trích dưới đây: Sóng bắt đầu từ gió.",
        "Quan sát ngữ liệu bên dưới: Thành phần câu gồm chủ ngữ và vị ngữ.",
    ],
)
def test_broadened_shared_passage_cues_link_exercises(intro):
    text = f"# Phần đọc hiểu\n\n{intro}\n\nCâu 1. Xác định nội dung chính.\n"
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=100)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    exercise = next(c for c in bundle["children"] if c["unit_kind"] == "exercise")
    assert any(ref["role"] == "shared_passage" for ref in exercise["context_refs"])


def test_text_retriever_reuses_memo_counter_across_validation_and_row_binding(tmp_path):
    class CountingWords(WordCounter):
        identity: ClassVar = {"kind": "fixture_words", "unit": "tokens", "version": 1}

        def __init__(self):
            self.calls = 0

        def count(self, text):
            self.calls += 1
            return super().count(text)

    class CountingEncoder(FakeEncoder):
        def __init__(self, prefix=""):
            self.counter = CountingWords()
            self.identity = {
                "adapter": "fixture-bow",
                "dimension": 32,
                "passage_prefix": prefix,
            }

    text = "# Chương 1\n\n" + "\n\n".join(
        f"Đoạn {i} trình bày định nghĩa và ví dụ minh họa cụ thể." for i in range(10)
    )
    build_enc = CountingEncoder(prefix="passage: ")
    build_corpus([TextDocument("doc", text)], tmp_path, encoder=build_enc, max_tokens=40)

    load_enc = CountingEncoder(prefix="passage: ")
    retriever, _, _ = load_retriever(tmp_path, encoder=load_enc)
    # Only 1 count per distinct child during fast validation, with 0 extra counts in row verification.
    assert load_enc.counter.calls == len(retriever.children)
    assert isinstance(MemoCounter(WordCounter()), MemoCounter)


def test_canonical_projection_keeps_math_env_heading_hierarchy_and_block_location():
    artifact = {
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {
                        "block_id": "t1",
                        "type": "Title",
                        "text": "Giải tích 12",
                        "bbox": [10, 10, 300, 40],
                    },
                    {
                        "block_id": "h2",
                        "type": "SectionHeader",
                        "heading_level": 2,
                        "text": "Chương 1. Đạo hàm",
                        "bbox": [10, 50, 300, 80],
                    },
                    {
                        "block_id": "h3",
                        "type": "SectionHeader",
                        "heading_level": 3,
                        "text": "1. Quy tắc tính",
                        "bbox": [10, 90, 300, 120],
                    },
                    {
                        "block_id": "eq1",
                        "type": "Equation",
                        "text": "a = b",
                        "markdown": "\\begin{align}\na &= b\\\\\nc &= d\n\\end{align}",
                        "bbox": [10, 130, 300, 190],
                    },
                ],
            }
        ]
    }
    md, _ = canonical_to_markdown(artifact)
    assert md.startswith("# Giải tích 12\n\n## Chương 1. Đạo hàm\n\n### 1. Quy tắc tính")
    bundle = chunk_text(md, source_id="doc", counter=WordCounter(), max_tokens=100)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    eq_child = bundle["children"][0]
    assert eq_child["section_path"] == ["Giải tích 12", "Chương 1. Đạo hàm", "1. Quy tắc tính"]
    assert bundle["parents"][0]["content_atoms"] == [
        {"start": 0, "end": len(eq_child["text"]), "kind": "math"}
    ]

    pos = md.index("a &= b")
    assert locate_spans_in_canonical(artifact, [(pos, pos + 6)]) == {
        "page": 1,
        "section": "1. Quy tắc tính",
    }
    assert locate_spans_in_canonical(artifact, [(pos, pos + 6)], include_block=True) == {
        "page": 1,
        "section": "1. Quy tắc tính",
        "block_id": "eq1",
        "bbox": [10, 130, 300, 190],
    }
