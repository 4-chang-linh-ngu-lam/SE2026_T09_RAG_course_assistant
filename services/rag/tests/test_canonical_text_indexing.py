"""Tests for Canonical-to-Markdown projection, span location, and corpus roundtrip."""

import hashlib
import re
from typing import ClassVar

import numpy as np
from rag.chunking.chunking import chunk_text
from rag.indexing import canonical_to_markdown, locate_spans_in_canonical
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.retrieval.corpus import load_retriever
from rag.search.retrieval_plan import SearchRequest


class _WordCounter:
    identity: ClassVar = {"kind": "fixture_words", "unit": "tokens", "version": 1}

    def count(self, text: str) -> int:
        return len(re.findall(r"\w+|[^\w\s]", text)) + 2


class _FakeEncoder:
    counter = _WordCounter()
    identity: ClassVar = {
        "adapter": "fixture-bow",
        "dimension": 32,
        "passage_prefix": "",
    }

    def encode(self, texts, **_kwargs):
        vectors = np.zeros((len(texts), 32), dtype=np.float32)
        vectors[:, 0] = 1e-3
        for index, text in enumerate(texts):
            for word in re.findall(r"\w+", text.casefold()):
                column = hashlib.sha256(word.encode()).digest()[0] % 32
                vectors[index, column] += 1
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors, {"items": len(texts)}


def _sample_canonical() -> dict:
    return {
        "schema_version": "idp-canonical-1",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {"type": "PageHeader", "text": "Sách giáo khoa Toán 10"},
                    {"type": "SectionHeader", "text": "Chương 1. Mệnh đề và tập hợp"},
                    {"type": "Text", "text": "Mệnh đề là một câu khẳng định đúng hoặc sai."},
                    {"type": "Text", "text": "Nội dung bị giữ rà soát", "held": True},
                    {"type": "PageNumber", "text": "1"},
                ],
            },
            {
                "page_number": 2,
                "blocks": [
                    {"type": "Picture", "text": "", "markdown": "![](assets/fig1.png)"},
                    {"type": "Text", "text": "Nội dung bị loại bỏ", "excluded": True},
                    {"type": "SectionHeader", "text": "## Bài 2. Tập hợp"},
                    {
                        "type": "Text",
                        "text": "Tập hợp gồm các phần tử xác định với công thức $x^2 + 1 \\ge 1$.",
                    },
                ],
            },
        ],
    }


def test_canonical_to_markdown_filters_blocks_and_tracks_exact_offsets():
    canonical = _sample_canonical()
    text, page_ranges = canonical_to_markdown(canonical)

    assert "Sách giáo khoa Toán 10" not in text
    assert "Nội dung bị giữ rà soát" not in text
    assert "Nội dung bị loại bỏ" not in text
    assert "fig1.png" not in text
    assert "## Chương 1. Mệnh đề và tập hợp" in text
    assert "## Bài 2. Tập hợp" in text
    assert len(page_ranges) == 2

    for page_info in page_ranges:
        page_slice = text[page_info["start"] : page_info["end"]]
        assert page_slice
        for sec in page_info["sections"]:
            assert sec["title"] in text[sec["start"] : sec["end"]]

    p2_pos = text.index("phần tử xác định")
    assert locate_spans_in_canonical(canonical, [(p2_pos, p2_pos + 10)], file_type="PDF") == {
        "page": 2,
        "section": "Bài 2. Tập hợp",
    }
    assert locate_spans_in_canonical(canonical, [(p2_pos, p2_pos + 10)], file_type="PPTX") == {
        "slide": 2,
        "section": "Bài 2. Tập hợp",
    }


def test_canonical_markdown_roundtrip_with_build_corpus_and_locate(tmp_path):
    canonical = _sample_canonical()
    text, _ = canonical_to_markdown(canonical)

    bundle = chunk_text(text, source_id="doc-v1", counter=_WordCounter(), max_tokens=128)
    assert bundle["report"]["pass"]

    corpus_dir = tmp_path / "corpus"
    build_corpus(
        [TextDocument(source_id="doc-v1", text=text, format="markdown")],
        corpus_dir,
        encoder=_FakeEncoder(),
        max_tokens=128,
    )
    retriever, _, _ = load_retriever(corpus_dir, encoder=_FakeEncoder())
    allowed = set(retriever.children)
    result = retriever.retrieve(
        SearchRequest("Tập hợp gồm các phần tử công thức x^2"),
        authorize=lambda: allowed,
    )
    items = result["context"]["items"]
    assert items
    top = items[0]
    spans = [(s["source_start"], s["source_end"]) for s in top["source_spans"]]
    located = locate_spans_in_canonical(canonical, spans, file_type="PDF")
    assert located == {"page": 2, "section": "Bài 2. Tập hợp"}
